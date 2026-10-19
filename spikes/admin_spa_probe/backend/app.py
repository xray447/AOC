"""V-09 管理端最小可用面：登录 / CSRF / 角色隔离 / 分组表单读写。

FastAPI + 单页前端。会话是服务端 Session + HttpOnly Cookie，写操作要求
CSRF 双提交；管理员才能改网络参数，pilot 访问管理接口直接 403。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
PROFILE_FILE = DATA_DIR / "network_profile.json"
WEB_DIST = BASE.parent / "web" / "dist"

SESSION_TTL_S = 8 * 3600
COOKIE_SESSION = "aoc_session"
COOKIE_CSRF = "aoc_csrf"

DEFAULT_PROFILE = {
    "min_fl": 290,
    "max_fl": 410,
    "route_provider_order": ["AIP", "GRAPH", "SIMBRIEF"],
    "coverage_ignore_below_nm": 200,
    "updated_at": None,
    "updated_by": None,
}


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000).hex()


USERS = {
    "admin": {"salt": b"aoc-admin-demo", "hash": _hash("admin123", b"aoc-admin-demo"), "role": "admin"},
    "pilot": {"salt": b"aoc-pilot-demo", "hash": _hash("pilot123", b"aoc-pilot-demo"), "role": "pilot"},
}

sessions: dict[str, dict] = {}
app = FastAPI(title="AOC admin probe", docs_url=None, redoc_url=None)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class ProfileIn(BaseModel):
    min_fl: int = Field(ge=100, le=450)
    max_fl: int = Field(ge=100, le=450)
    route_provider_order: list[str]
    coverage_ignore_below_nm: int = Field(ge=50, le=1000)


def _load_profile() -> dict:
    if PROFILE_FILE.exists():
        try:
            return {**DEFAULT_PROFILE, **json.loads(PROFILE_FILE.read_text(encoding="utf-8"))}
        except json.JSONDecodeError:
            pass
    return dict(DEFAULT_PROFILE)


def _save_profile(profile: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


def _current(request: Request) -> tuple[str, dict]:
    sid = request.cookies.get(COOKIE_SESSION)
    sess = sessions.get(sid or "")
    if not sess:
        raise HTTPException(status_code=401, detail="not_authenticated")
    if sess["expires_at"] < time.time():
        sessions.pop(sid, None)
        raise HTTPException(status_code=401, detail="session_expired")
    return sid, sess


def current_session(request: Request) -> dict:
    return _current(request)[1]


def admin_session(sess: dict = Depends(current_session)) -> dict:
    if sess["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin_required")
    return sess


def _require_csrf(request: Request, sess: dict, csrf_header: str | None) -> None:
    cookie = request.cookies.get(COOKIE_CSRF, "")
    if not csrf_header or not cookie or not hmac.compare_digest(csrf_header, cookie) \
            or not hmac.compare_digest(csrf_header, sess["csrf"]):
        raise HTTPException(status_code=403, detail="csrf_failed")


@app.post("/api/login")
def login(body: LoginIn, response: Response) -> dict:
    user = USERS.get(body.username)
    if not user or not hmac.compare_digest(_hash(body.password, user["salt"]), user["hash"]):
        raise HTTPException(status_code=401, detail="bad_credentials")
    sid = secrets.token_urlsafe(24)
    csrf = secrets.token_urlsafe(24)
    sessions[sid] = {"username": body.username, "role": user["role"],
                     "csrf": csrf, "expires_at": time.time() + SESSION_TTL_S}
    response.set_cookie(COOKIE_SESSION, sid, httponly=True, samesite="lax", max_age=SESSION_TTL_S)
    response.set_cookie(COOKIE_CSRF, csrf, httponly=False, samesite="lax", max_age=SESSION_TTL_S)
    return {"username": body.username, "role": user["role"], "csrf": csrf}


@app.get("/api/session")
def session_info(request: Request) -> dict:
    _, sess = _current(request)
    return {"username": sess["username"], "role": sess["role"], "csrf": sess["csrf"]}


@app.post("/api/logout")
def logout(request: Request, response: Response) -> dict:
    sid = request.cookies.get(COOKIE_SESSION)
    sessions.pop(sid or "", None)
    response.delete_cookie(COOKIE_SESSION)
    response.delete_cookie(COOKIE_CSRF)
    return {"ok": True}


@app.get("/api/network-profile")
def get_profile(request: Request) -> dict:
    _current(request)
    return _load_profile()


@app.put("/api/network-profile")
def put_profile(body: ProfileIn, request: Request,
                sess: dict = Depends(admin_session)) -> dict:
    _require_csrf(request, sess, request.headers.get("x-csrf-token"))
    if body.min_fl >= body.max_fl:
        raise HTTPException(status_code=422, detail="min_fl_must_be_less_than_max_fl")
    for p in body.route_provider_order:
        if p not in {"AIP", "GRAPH", "SIMBRIEF"}:
            raise HTTPException(status_code=422, detail=f"unknown_provider:{p}")
    profile = {**body.model_dump(), "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "updated_by": sess["username"]}
    _save_profile(profile)
    return profile


@app.post("/api/network-profile/reset")
def reset_profile(request: Request,
                  sess: dict = Depends(admin_session)) -> dict:
    _require_csrf(request, sess, request.headers.get("x-csrf-token"))
    _save_profile(dict(DEFAULT_PROFILE))
    return _load_profile()


if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


@app.get("/")
def index():
    if WEB_DIST.exists():
        return FileResponse(WEB_DIST / "index.html")
    return HTMLResponse("<h1>admin_spa_probe</h1><p>前端未构建：cd web && npm install && npm run build</p>")
