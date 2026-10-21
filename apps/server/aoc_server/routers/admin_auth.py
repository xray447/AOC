"""管理端认证：HttpOnly 会话 Cookie + CSRF；与玩家 Bearer 令牌分离。"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..errors import forbidden, unauthorized
from ..models import AppUser, Company, WebSession
from ..security import (ADMIN_ROLES, AdminContext, LoginThrottle, client_ip, current_admin,
                        get_db, hash_token, new_token, verify_password)
from ..services import store
from .auth import company_dict, user_dict

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


class AdminLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


def _throttle(request: Request) -> LoginThrottle:
    return request.app.state.login_throttle


@router.post("/login")
def login(body: AdminLoginIn, request: Request, response: Response,
          db: Session = Depends(get_db)) -> dict:
    settings = request.app.state.settings
    key = f"admin|{client_ip(request)}|{body.username.lower()}"
    throttle = _throttle(request)
    if not throttle.check(key):
        store.audit(db, company_id=None, actor=None, action="ADMIN_LOGIN",
                    result="RATE_LIMITED", ip=client_ip(request),
                    user_agent=request.headers.get("user-agent"))
        raise unauthorized("LOGIN_RATE_LIMITED", "登录失败次数过多，请稍后再试")
    user = db.scalar(select(AppUser).where(AppUser.username == body.username))
    if not user or not verify_password(body.password, user.password_hash) or not user.active:
        throttle.fail(key)
        store.audit(db, company_id=user.company_id if user else None, actor=user,
                    action="ADMIN_LOGIN", result="FAILED", ip=client_ip(request),
                    user_agent=request.headers.get("user-agent"))
        raise unauthorized("LOGIN_FAILED", "用户名或密码错误")
    if user.role not in ADMIN_ROLES:
        throttle.fail(key)
        store.audit(db, company_id=user.company_id, actor=user, action="ADMIN_LOGIN",
                    result="FORBIDDEN", ip=client_ip(request))
        raise forbidden("ADMIN_REQUIRED", "该账号不能访问管理端")
    company = db.get(Company, user.company_id)
    if not company:
        raise unauthorized("COMPANY_MISSING", "公司不存在")
    throttle.reset(key)
    now = utcnow()
    raw = new_token()
    session = WebSession(
        user_id=user.id, token_hash=hash_token(raw), csrf_token=new_token(),
        ip=client_ip(request), user_agent=(request.headers.get("user-agent") or "")[:255],
        last_seen_at=now, idle_expires_at=now + timedelta(minutes=settings.session_idle_minutes),
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
    )
    db.add(session)
    user.last_login_at = now
    db.flush()
    store.audit(db, company_id=company.id, actor=user, action="ADMIN_LOGIN",
                entity="web_session", entity_id=session.id, ip=client_ip(request),
                user_agent=request.headers.get("user-agent"))
    response.set_cookie(
        settings.cookie_name, raw, httponly=True, secure=settings.cookie_secure,
        samesite="lax", max_age=settings.session_absolute_hours * 3600, path="/")
    return {"user": user_dict(user), "company": company_dict(company),
            "csrf_token": session.csrf_token, "expires_at": store.iso(session.expires_at),
            "idle_expires_at": store.iso(session.idle_expires_at)}


@router.get("/me")
def me(ctx: AdminContext = Depends(current_admin)) -> dict:
    return {"user": user_dict(ctx.user), "company": company_dict(ctx.company),
            "csrf_token": ctx.session.csrf_token,
            "expires_at": store.iso(ctx.session.expires_at),
            "idle_expires_at": store.iso(ctx.session.idle_expires_at)}


@router.post("/logout")
def logout(request: Request, response: Response,
           ctx: AdminContext = Depends(current_admin),
           db: Session = Depends(get_db)) -> dict:
    ctx.session.revoked = True
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="ADMIN_LOGOUT",
                entity="web_session", entity_id=ctx.session.id, ip=client_ip(request))
    db.flush()
    response.delete_cookie(request.app.state.settings.cookie_name, path="/")
    return {"ok": True}
