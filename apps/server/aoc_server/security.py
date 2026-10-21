"""认证与授权：密码哈希、访问令牌、浏览器会话、CSRF、角色校验、登录限流。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import utcnow
from .errors import forbidden, unauthorized
from .models import AppUser, Company, WebSession

ROLE_ADMIN = "ADMIN"
ROLE_DISPATCHER = "DISPATCHER"
ROLE_PILOT = "PILOT"
ADMIN_ROLES = {ROLE_ADMIN, ROLE_DISPATCHER}

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1


# ---------------------------------------------------------------- 密码
def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("密码至少 8 位")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R,
                            p=_SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r),
                                p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- 令牌
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def sign_access_token(secret: str, user: AppUser, ttl_seconds: int) -> str:
    now = int(time.time())
    payload = {"sub": user.id, "cid": user.company_id, "role": user.role, "iat": now,
               "exp": now + ttl_seconds}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def decode_access_token(secret: str, token: str) -> dict[str, Any]:
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        payload = json.loads(_unb64(body))
        if int(payload.get("exp") or 0) < int(time.time()):
            raise ValueError("expired")
        return payload
    except (ValueError, json.JSONDecodeError, TypeError) as exc:
        raise unauthorized("TOKEN_INVALID", "访问令牌无效或已过期") from exc


# ---------------------------------------------------------------- 限流
class LoginThrottle:
    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str) -> list[float]:
        cutoff = time.time() - self.window
        items = [t for t in self._fails.get(key, []) if t >= cutoff]
        if items:
            self._fails[key] = items
        else:
            self._fails.pop(key, None)
        return items

    def check(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key)) < self.max_failures

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails.setdefault(key, []).append(time.time())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


# ---------------------------------------------------------------- 依赖
def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.db.session() as session:
        yield session


@dataclass
class UserContext:
    user: AppUser
    company: Company
    token: str


@dataclass
class AdminContext:
    user: AppUser
    company: Company
    session: WebSession


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def current_user(request: Request, db: Session = Depends(get_db)) -> UserContext:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise unauthorized()
    token = header.split(" ", 1)[1].strip()
    payload = decode_access_token(request.app.state.settings.secret, token)
    user = db.get(AppUser, payload.get("sub"))
    if not user or not user.active:
        raise unauthorized("USER_DISABLED", "账号不存在或已停用")
    if user.company_id != payload.get("cid"):
        raise unauthorized("TOKEN_STALE", "令牌与账号所属公司不一致")
    company = db.get(Company, user.company_id)
    if not company:
        raise unauthorized("COMPANY_MISSING", "公司不存在")
    return UserContext(user=user, company=company, token=token)


def current_admin(request: Request, db: Session = Depends(get_db)) -> AdminContext:
    settings = request.app.state.settings
    raw = request.cookies.get(settings.cookie_name, "")
    if not raw:
        raise unauthorized("SESSION_REQUIRED", "请先登录管理端")
    session = db.scalar(select(WebSession).where(WebSession.token_hash == hash_token(raw)))
    if not session or session.revoked:
        raise unauthorized("SESSION_REQUIRED", "会话不存在或已退出")
    now = utcnow()
    if session.expires_at <= now or session.idle_expires_at <= now:
        session.revoked = True
        db.flush()
        raise unauthorized("SESSION_EXPIRED", "会话已过期，请重新登录")
    user = db.get(AppUser, session.user_id)
    if not user or not user.active:
        raise unauthorized("USER_DISABLED", "账号已停用")
    if user.role not in ADMIN_ROLES:
        raise forbidden("ADMIN_REQUIRED", "该账号不能访问管理端")
    company = db.get(Company, user.company_id)
    if not company:
        raise unauthorized("COMPANY_MISSING", "公司不存在")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf or not hmac.compare_digest(csrf, session.csrf_token):
            raise forbidden("CSRF_INVALID", "CSRF 令牌缺失或不匹配")
    # 滑动空闲窗口；每 30s 落一次，避免每个请求都写。
    if (now - session.last_seen_at).total_seconds() > 30:
        session.last_seen_at = now
        session.idle_expires_at = now + timedelta(minutes=settings.session_idle_minutes)
        db.flush()
    return AdminContext(user=user, company=company, session=session)


def require_roles(*roles: str):
    allowed = set(roles)

    def _dep(ctx: AdminContext = Depends(current_admin)) -> AdminContext:
        if ctx.user.role not in allowed:
            raise forbidden("FORBIDDEN", f"需要角色：{', '.join(sorted(allowed))}")
        return ctx

    return _dep


require_admin = require_roles(ROLE_ADMIN)
require_admin_or_dispatcher = require_roles(ROLE_ADMIN, ROLE_DISPATCHER)


def client_ip(request: Request) -> str:
    return _client_ip(request)
