"""玩家账号：登录 / 刷新 / 登出 / 邀请码注册 / 当前身份。"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..errors import bad_request, forbidden, unauthorized
from ..models import AppUser, Company, InviteCode, RefreshToken
from ..security import (LoginThrottle, UserContext, client_ip, current_user, get_db,
                        hash_password, hash_token, new_token, sign_access_token,
                        verify_password)
from ..services import store

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str


class RegisterIn(BaseModel):
    invite_code: str
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)


def user_dict(user: AppUser) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name,
            "email": user.email, "role": user.role, "active": user.active,
            "company_id": user.company_id, "last_login_at": store.iso(user.last_login_at)}


def company_dict(company: Company) -> dict:
    return {"id": company.id, "name": company.name, "icao": company.icao,
            "callsign_prefix": company.callsign_prefix, "base_icao": company.base_icao,
            "currency": company.currency, "balance": company.balance,
            "initial_balance": company.initial_balance, "timezone": company.timezone,
            "description": company.description}


def _throttle(request: Request) -> LoginThrottle:
    return request.app.state.login_throttle


def _issue(db: Session, request: Request, user: AppUser, company: Company) -> dict:
    settings = request.app.state.settings
    access = sign_access_token(settings.secret, user, settings.access_token_minutes * 60)
    refresh = new_token()
    db.add(RefreshToken(user_id=user.id, token_hash=hash_token(refresh),
                        expires_at=utcnow() + timedelta(days=settings.refresh_token_days)))
    user.last_login_at = utcnow()
    db.flush()
    return {
        "access_token": access, "refresh_token": refresh,
        "expires_in": settings.access_token_minutes * 60,
        "token_type": "Bearer", "user": user_dict(user), "company": company_dict(company),
    }


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> dict:
    throttle = _throttle(request)
    key = f"{client_ip(request)}|{body.username.lower()}"
    if not throttle.check(key):
        raise unauthorized("LOGIN_RATE_LIMITED", "登录失败次数过多，请稍后再试")
    user = db.scalar(select(AppUser).where(AppUser.username == body.username))
    if not user or not verify_password(body.password, user.password_hash):
        throttle.fail(key)
        raise unauthorized("LOGIN_FAILED", "用户名或密码错误")
    if not user.active:
        raise forbidden("USER_DISABLED", "账号已停用")
    company = db.get(Company, user.company_id)
    if not company:
        raise unauthorized("COMPANY_MISSING", "公司不存在")
    throttle.reset(key)
    return _issue(db, request, user, company)


@router.post("/refresh")
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db)) -> dict:
    row = db.scalar(select(RefreshToken).where(
        RefreshToken.token_hash == hash_token(body.refresh_token)))
    if not row or row.revoked or row.expires_at <= utcnow():
        raise unauthorized("REFRESH_INVALID", "刷新令牌无效或已过期")
    user = db.get(AppUser, row.user_id)
    if not user or not user.active:
        raise unauthorized("USER_DISABLED", "账号不存在或已停用")
    company = db.get(Company, user.company_id)
    if not company:
        raise unauthorized("COMPANY_MISSING", "公司不存在")
    row.revoked = True
    db.flush()
    return _issue(db, request, user, company)


@router.post("/logout")
def logout(body: RefreshIn | None = None, db: Session = Depends(get_db)) -> dict:
    if body and body.refresh_token:
        row = db.scalar(select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(body.refresh_token)))
        if row:
            row.revoked = True
            db.flush()
    return {"ok": True}


@router.get("/me")
def me(ctx: UserContext = Depends(current_user)) -> dict:
    return {"user": user_dict(ctx.user), "company": company_dict(ctx.company)}


@router.post("/register")
def register(body: RegisterIn, db: Session = Depends(get_db)) -> dict:
    invite = db.scalar(select(InviteCode).where(InviteCode.code == body.invite_code.upper()))
    if not invite:
        raise bad_request("INVITE_INVALID", "邀请码不存在")
    if invite.expires_at and invite.expires_at <= utcnow():
        raise bad_request("INVITE_EXPIRED", "邀请码已过期")
    if invite.used_count >= invite.max_uses:
        raise bad_request("INVITE_EXHAUSTED", "邀请码已用完")
    exists = db.scalar(select(AppUser.id).where(AppUser.company_id == invite.company_id,
                                               AppUser.username == body.username))
    if exists:
        raise bad_request("USERNAME_TAKEN", "用户名已存在")
    user = AppUser(company_id=invite.company_id, username=body.username,
                   display_name=body.display_name or body.username, role=invite.role,
                   password_hash=hash_password(body.password), active=True)
    db.add(user)
    invite.used_count += 1
    db.flush()
    store.audit(db, company_id=invite.company_id, actor=user, action="USER_REGISTER",
                entity="app_user", entity_id=user.id, after={"role": user.role})
    company = db.get(Company, invite.company_id)
    return {"user": user_dict(user), "company": company_dict(company) if company else None}
