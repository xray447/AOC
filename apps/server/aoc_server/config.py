"""服务端配置：全部来自环境变量，敏感项不进仓库。"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / "packages" / "aoc_core").is_dir():
            return parent
    return here.parents[3]


@dataclass
class Settings:
    database_url: str = ""
    secret: str = ""
    admin_static_dir: Path = field(default_factory=lambda: repo_root() / "apps" / "admin-web" / "dist")
    cookie_name: str = "aoc_admin_session"
    cookie_secure: bool = False
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    access_token_minutes: int = 120
    refresh_token_days: int = 30
    cors_origins: list[str] = field(default_factory=lambda: [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "tauri://localhost", "https://tauri.localhost",
    ])
    bootstrap_company: str = "AOC Virtual"
    bootstrap_icao: str = "AOC"
    bootstrap_callsign: str = "AOC"
    bootstrap_base: str = "ZBAA"
    bootstrap_currency: str = "USD"
    bootstrap_admin: str = "admin"
    bootstrap_password: str = ""
    seed_types: bool = True
    seed_demo: bool = False
    login_max_failures: int = 5
    login_window_seconds: int = 300

    @classmethod
    def from_env(cls) -> "Settings":
        root = repo_root()
        home = Path(os.environ.get("AOC_SERVER_HOME", str(root / "out" / "server")))
        database_url = os.environ.get("AOC_DATABASE_URL", "").strip()
        if not database_url:
            home.mkdir(parents=True, exist_ok=True)
            database_url = f"sqlite+pysqlite:///{(home / 'aoc-server.sqlite').as_posix()}"
        secret = os.environ.get("AOC_SECRET", "").strip()
        if not secret:
            # 开发期固定回退值仅用于本机；生产必须显式配置，否则每次重启会话失效。
            secret = "dev-only-aoc-secret-" + str(root)
        static_dir = Path(os.environ.get("AOC_ADMIN_STATIC_DIR", str(root / "apps" / "admin-web" / "dist")))
        return cls(
            database_url=database_url,
            secret=secret,
            admin_static_dir=static_dir,
            cookie_name=os.environ.get("AOC_COOKIE_NAME", "aoc_admin_session"),
            cookie_secure=_bool("AOC_COOKIE_SECURE", False),
            session_idle_minutes=_int("AOC_SESSION_IDLE_MINUTES", 30),
            session_absolute_hours=_int("AOC_SESSION_ABSOLUTE_HOURS", 12),
            access_token_minutes=_int("AOC_ACCESS_TOKEN_MINUTES", 120),
            refresh_token_days=_int("AOC_REFRESH_TOKEN_DAYS", 30),
            cors_origins=_list("AOC_CORS_ORIGINS", cls.__dataclass_fields__["cors_origins"].default_factory()),
            bootstrap_company=os.environ.get("AOC_BOOTSTRAP_COMPANY", "AOC Virtual"),
            bootstrap_icao=os.environ.get("AOC_BOOTSTRAP_ICAO", "AOC"),
            bootstrap_callsign=os.environ.get("AOC_BOOTSTRAP_CALLSIGN", "AOC"),
            bootstrap_base=os.environ.get("AOC_BOOTSTRAP_BASE", "ZBAA"),
            bootstrap_currency=os.environ.get("AOC_BOOTSTRAP_CURRENCY", "USD"),
            bootstrap_admin=os.environ.get("AOC_BOOTSTRAP_ADMIN", "admin"),
            bootstrap_password=os.environ.get("AOC_BOOTSTRAP_PASSWORD", ""),
            seed_types=_bool("AOC_SEED_TYPES", True),
            seed_demo=_bool("AOC_SEED_DEMO", False),
            login_max_failures=_int("AOC_LOGIN_MAX_FAILURES", 5),
            login_window_seconds=_int("AOC_LOGIN_WINDOW_SECONDS", 300),
        )


def new_secret() -> str:
    return secrets.token_urlsafe(48)
