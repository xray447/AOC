"""管理端：概览、公司档案、用户/邀请码、审计、系统状态。"""
from __future__ import annotations

import csv
import io
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import API_VERSION, __version__
from ..db import utcnow
from ..errors import bad_request, conflict, not_found
from ..models import (Aircraft, AircraftLock, Airport, AppUser, AuditLog, FlightInstance,
                      InviteCode, LedgerEntry, RefreshToken, Settlement, WebSession)
from ..security import (ROLE_ADMIN, ROLE_DISPATCHER, ROLE_PILOT, AdminContext, client_ip,
                        get_db, hash_password, new_token, require_admin,
                        require_admin_or_dispatcher)
from ..services import ops, store
from .auth import company_dict, user_dict

router = APIRouter(prefix="/admin", tags=["admin"])


def _today_start() -> Any:
    now = utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/overview")
def overview(ctx: AdminContext = Depends(require_admin_or_dispatcher),
             db: Session = Depends(get_db)) -> dict:
    company_id = ctx.company.id
    today = _today_start()
    revenue = db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0.0)).where(
        LedgerEntry.company_id == company_id, LedgerEntry.direction == "CREDIT",
        LedgerEntry.created_at >= today)) or 0.0
    cost = db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0.0)).where(
        LedgerEntry.company_id == company_id, LedgerEntry.direction == "DEBIT",
        LedgerEntry.created_at >= today)) or 0.0
    in_flight = db.scalar(select(func.count(FlightInstance.id)).where(
        FlightInstance.company_id == company_id,
        FlightInstance.status == ops.IN_FLIGHT)) or 0
    held = db.scalar(select(func.count(Settlement.id)).where(
        Settlement.company_id == company_id, Settlement.status == "HELD")) or 0
    locks = db.scalar(select(func.count(AircraftLock.id)).where(
        AircraftLock.company_id == company_id,
        AircraftLock.status == ops.ACTIVE)) or 0
    online = db.scalar(select(func.count(func.distinct(AircraftLock.user_id))).where(
        AircraftLock.company_id == company_id,
        AircraftLock.status == ops.ACTIVE)) or 0
    flights = db.scalars(select(FlightInstance).where(
        FlightInstance.company_id == company_id)
        .order_by(FlightInstance.scheduled_dep_utc.desc()).limit(10)).all()
    audits = db.scalars(select(AuditLog).where(AuditLog.company_id == company_id)
                        .order_by(AuditLog.created_at.desc()).limit(10)).all()
    reviews = db.scalars(select(Settlement).where(
        Settlement.company_id == company_id, Settlement.status == "HELD")
        .order_by(Settlement.created_at).limit(5)).all()
    return {
        "company": company_dict(ctx.company),
        "cards": {
            "balance": ctx.company.balance, "today_revenue": round(float(revenue), 2),
            "today_cost": round(float(cost), 2),
            "today_profit": round(float(revenue) - float(cost), 2),
            "in_flight": in_flight, "online_pilots": online,
            "review_pending": held, "active_locks": locks,
        },
        "recent_flights": [ops.flight_dict(row) for row in flights],
        "recent_audit": [audit_dict(row) for row in audits],
        "review_queue": [ops.settlement_dict(row) for row in reviews],
        "server_time": store.iso(utcnow()),
    }


def audit_dict(row: AuditLog) -> dict[str, Any]:
    return {"id": row.id, "actor_id": row.actor_id, "actor_name": row.actor_name,
            "action": row.action, "entity": row.entity, "entity_id": row.entity_id,
            "result": row.result, "reason": row.reason, "ip": row.ip,
            "request_id": row.request_id, "before": row.before_json,
            "after": row.after_json, "created_at": store.iso(row.created_at)}


# ---------------------------------------------------------------- 公司
@router.get("/company")
def get_company(ctx: AdminContext = Depends(require_admin_or_dispatcher),
                db: Session = Depends(get_db)) -> dict:
    return company_dict(ctx.company)


@router.put("/company")
def update_company(body: dict[str, Any], request: Request,
                   ctx: AdminContext = Depends(require_admin),
                   db: Session = Depends(get_db)) -> dict:
    company = ctx.company
    before = company_dict(company)
    reason = str(body.get("reason") or "").strip()
    for field in ("name", "callsign_prefix", "base_icao", "timezone", "description"):
        if field in body and body[field] is not None:
            value = str(body[field]).strip()
            if field == "base_icao":
                value = value.upper()
                if not db.scalar(select(Airport.id).where(Airport.ident == value)):
                    raise bad_request("AIRPORT_UNKNOWN", f"机场 {value} 不在机场库中")
            if value:
                setattr(company, field, value)
    if "currency" in body and str(body["currency"]).upper() != company.currency.upper():
        raise bad_request("CURRENCY_READONLY", "货币创建后不可修改（MVP 不做汇率）")
    store.audit(db, company_id=company.id, actor=ctx.user, action="COMPANY_UPDATE",
                entity="company", entity_id=company.id, before=before,
                after=company_dict(company), reason=reason, ip=client_ip(request))
    store.emit(db, company.id, "COMPANY_UPDATED", entity="company", entity_id=company.id)
    db.flush()
    return company_dict(company)


@router.post("/company/balance")
def adjust_balance(body: dict[str, Any], request: Request,
                   ctx: AdminContext = Depends(require_admin),
                   db: Session = Depends(get_db)) -> dict:
    try:
        amount = float(body.get("amount"))
    except (TypeError, ValueError) as exc:
        raise bad_request("AMOUNT_INVALID", "amount 必须是数字") from exc
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise bad_request("REASON_REQUIRED", "调整资金必须填写原因")
    before = ctx.company.balance
    if before + amount < 0:
        raise bad_request("BALANCE_NEGATIVE", "调整后余额不能为负")
    ctx.company.balance = round(before + amount, 2)
    db.add(LedgerEntry(company_id=ctx.company.id, entry_type="ADJUSTMENT",
                       direction="CREDIT" if amount >= 0 else "DEBIT",
                       amount=abs(round(amount, 2)), balance_after=ctx.company.balance,
                       note=reason[:255]))
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="BALANCE_ADJUST",
                entity="company", entity_id=ctx.company.id,
                before={"balance": before}, after={"balance": ctx.company.balance},
                reason=reason, ip=client_ip(request))
    db.flush()
    return company_dict(ctx.company)


# ---------------------------------------------------------------- 用户
@router.get("/users")
def list_users(ctx: AdminContext = Depends(require_admin),
               db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(AppUser).where(AppUser.company_id == ctx.company.id)
                      .order_by(AppUser.created_at)).all()
    return [user_dict(row) for row in rows]


@router.post("/users")
def create_user(body: dict[str, Any], request: Request,
                ctx: AdminContext = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if len(username) < 3:
        raise bad_request("USERNAME_INVALID", "用户名至少 3 位")
    role = str(body.get("role") or ROLE_PILOT).upper()
    if role not in {ROLE_ADMIN, ROLE_DISPATCHER, ROLE_PILOT}:
        raise bad_request("ROLE_INVALID", "角色必须是 ADMIN/DISPATCHER/PILOT")
    if len(password) < 8:
        raise bad_request("PASSWORD_WEAK", "密码至少 8 位")
    exists = db.scalar(select(AppUser.id).where(AppUser.company_id == ctx.company.id,
                                               AppUser.username == username))
    if exists:
        raise conflict("USERNAME_TAKEN", "用户名已存在")
    try:
        hashed = hash_password(password)
    except ValueError as exc:
        raise bad_request("PASSWORD_WEAK", str(exc)) from exc
    user = AppUser(company_id=ctx.company.id, username=username,
                   display_name=str(body.get("display_name") or username),
                   email=body.get("email"), role=role, password_hash=hashed, active=True)
    db.add(user)
    db.flush()
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="USER_CREATE",
                entity="app_user", entity_id=user.id,
                after={"username": username, "role": role}, ip=client_ip(request))
    return user_dict(user)


@router.put("/users/{user_id}")
def update_user(user_id: str, body: dict[str, Any], request: Request,
                ctx: AdminContext = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    user = db.get(AppUser, user_id)
    if not user or user.company_id != ctx.company.id:
        raise not_found("USER_NOT_FOUND", "用户不存在")
    before = user_dict(user)
    if "role" in body:
        role = str(body["role"]).upper()
        if role not in {ROLE_ADMIN, ROLE_DISPATCHER, ROLE_PILOT}:
            raise bad_request("ROLE_INVALID", "角色必须是 ADMIN/DISPATCHER/PILOT")
        if user.id == ctx.user.id and role != ROLE_ADMIN:
            raise bad_request("SELF_DEMOTE", "不能降级自己的管理员角色")
        if user.role == ROLE_ADMIN and role != ROLE_ADMIN:
            other = db.scalar(select(func.count(AppUser.id)).where(
                AppUser.company_id == ctx.company.id, AppUser.role == ROLE_ADMIN,
                AppUser.active.is_(True), AppUser.id != user.id)) or 0
            if other == 0:
                raise bad_request("LAST_ADMIN", "不能降级最后一个管理员")
        user.role = role
    if "active" in body:
        active = bool(body["active"])
        if user.id == ctx.user.id and not active:
            raise bad_request("SELF_DISABLE", "不能停用自己")
        if not active and user.role == ROLE_ADMIN:
            other = db.scalar(select(func.count(AppUser.id)).where(
                AppUser.company_id == ctx.company.id, AppUser.role == ROLE_ADMIN,
                AppUser.active.is_(True), AppUser.id != user.id)) or 0
            if other == 0:
                raise bad_request("LAST_ADMIN", "不能停用最后一个管理员")
        user.active = active
        if not active:
            _revoke_credentials(db, user.id)
    for field in ("display_name", "email"):
        if field in body and body[field] is not None:
            setattr(user, field, str(body[field]))
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="USER_UPDATE",
                entity="app_user", entity_id=user.id, before=before, after=user_dict(user),
                reason=body.get("reason"), ip=client_ip(request))
    db.flush()
    return user_dict(user)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: str, body: dict[str, Any], request: Request,
                   ctx: AdminContext = Depends(require_admin),
                   db: Session = Depends(get_db)) -> dict:
    user = db.get(AppUser, user_id)
    if not user or user.company_id != ctx.company.id:
        raise not_found("USER_NOT_FOUND", "用户不存在")
    password = str(body.get("password") or "")
    if len(password) < 8:
        raise bad_request("PASSWORD_WEAK", "密码至少 8 位")
    user.password_hash = hash_password(password)
    _revoke_credentials(db, user.id)
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="USER_RESET_PASSWORD",
                entity="app_user", entity_id=user.id, ip=client_ip(request))
    db.flush()
    return {"ok": True}


def _revoke_credentials(db: Session, user_id: str) -> None:
    for row in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user_id,
                                                    RefreshToken.revoked.is_(False))).all():
        row.revoked = True
    for row in db.scalars(select(WebSession).where(WebSession.user_id == user_id,
                                                   WebSession.revoked.is_(False))).all():
        row.revoked = True
    db.flush()


# ---------------------------------------------------------------- 邀请码
@router.get("/invites")
def list_invites(ctx: AdminContext = Depends(require_admin),
                 db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(InviteCode).where(InviteCode.company_id == ctx.company.id)
                      .order_by(InviteCode.created_at.desc())).all()
    return [invite_dict(row) for row in rows]


def invite_dict(row: InviteCode) -> dict:
    return {"id": row.id, "code": row.code, "role": row.role, "max_uses": row.max_uses,
            "used_count": row.used_count, "expires_at": store.iso(row.expires_at),
            "created_at": store.iso(row.created_at),
            "exhausted": row.used_count >= row.max_uses}


@router.post("/invites")
def create_invite(body: dict[str, Any], request: Request,
                  ctx: AdminContext = Depends(require_admin),
                  db: Session = Depends(get_db)) -> dict:
    role = str(body.get("role") or ROLE_PILOT).upper()
    if role not in {ROLE_ADMIN, ROLE_DISPATCHER, ROLE_PILOT}:
        raise bad_request("ROLE_INVALID", "角色必须是 ADMIN/DISPATCHER/PILOT")
    hours = max(1, int(body.get("expires_in_hours") or 168))
    row = InviteCode(company_id=ctx.company.id, code=new_token()[:12].upper(), role=role,
                     max_uses=max(1, int(body.get("max_uses") or 1)),
                     expires_at=utcnow() + timedelta(hours=hours), created_by=ctx.user.id)
    db.add(row)
    db.flush()
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="INVITE_CREATE",
                entity="invite_code", entity_id=row.id, after={"role": role},
                ip=client_ip(request))
    return invite_dict(row)


@router.delete("/invites/{invite_id}")
def delete_invite(invite_id: str, request: Request,
                  ctx: AdminContext = Depends(require_admin),
                  db: Session = Depends(get_db)) -> dict:
    row = db.get(InviteCode, invite_id)
    if not row or row.company_id != ctx.company.id:
        raise not_found("INVITE_NOT_FOUND", "邀请码不存在")
    row.max_uses = row.used_count
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="INVITE_REVOKE",
                entity="invite_code", entity_id=row.id, ip=client_ip(request))
    db.flush()
    return {"ok": True}


# ---------------------------------------------------------------- 审计
@router.get("/audit")
def list_audit(action: str | None = None, actor: str | None = None,
               limit: int = Query(200, le=1000), fmt: str = Query("json", alias="format"),
               ctx: AdminContext = Depends(require_admin_or_dispatcher),
               db: Session = Depends(get_db)):
    query = select(AuditLog).where(AuditLog.company_id == ctx.company.id)
    if action:
        query = query.where(AuditLog.action.like(f"%{action}%"))
    if actor:
        query = query.where(AuditLog.actor_name.like(f"%{actor}%"))
    rows = db.scalars(query.order_by(AuditLog.created_at.desc()).limit(limit)).all()
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["time", "actor", "action", "entity", "entity_id", "result", "ip", "reason"])
        for row in rows:
            writer.writerow([store.iso(row.created_at), row.actor_name, row.action, row.entity,
                             row.entity_id, row.result, row.ip, row.reason or ""])
        return PlainTextResponse(buffer.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=audit.csv"})
    return [audit_dict(row) for row in rows]


# ---------------------------------------------------------------- 系统
@router.get("/system")
def system(request: Request, ctx: AdminContext = Depends(require_admin_or_dispatcher),
           db: Session = Depends(get_db)) -> dict:
    economy = store.current_setting(db, ctx.company.id, store.ECONOMY)
    policy = store.current_setting(db, ctx.company.id, store.POLICY)
    counts = {
        "users": db.scalar(select(func.count(AppUser.id)).where(
            AppUser.company_id == ctx.company.id)) or 0,
        "aircraft": db.scalar(select(func.count(Aircraft.id)).where(
            Aircraft.company_id == ctx.company.id)) or 0,
        "flights": db.scalar(select(func.count(FlightInstance.id)).where(
            FlightInstance.company_id == ctx.company.id)) or 0,
        "settlements": db.scalar(select(func.count(Settlement.id)).where(
            Settlement.company_id == ctx.company.id)) or 0,
        "ledger_entries": db.scalar(select(func.count(LedgerEntry.id)).where(
            LedgerEntry.company_id == ctx.company.id)) or 0,
    }
    return {
        "server": {"version": __version__, "api_version": API_VERSION,
                   "started_at": store.iso(getattr(request.app.state, "started_at", None)),
                   "database": (request.app.state.db.url or "").split("://", 1)[0]},
        "company": company_dict(ctx.company),
        "config": {"economy_version": economy.version if economy else 0,
                   "policy_version": policy.version if policy else 0},
        "counts": counts,
        "admin_static_dir": str(request.app.state.settings.admin_static_dir),
        "server_time": store.iso(utcnow()),
    }
