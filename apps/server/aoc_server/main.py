"""aoc-server 入口（M3 联机模式）。

开发：
    python apps/server/main.py --port 8080 --demo
部署：
    uvicorn aoc_server.main:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

def _find_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "packages" / "aoc_core").is_dir():
            return parent
    return start.parents[3]


ROOT = _find_root(Path(__file__).resolve().parent)
for pkg in (ROOT / "packages" / "aoc_protocol", ROOT / "packages" / "aoc_core",
            ROOT / "packages" / "aoc_navdata", ROOT / "packages" / "aoc_route",
            ROOT / "apps" / "server"):
    if str(pkg) not in sys.path:
        sys.path.insert(0, str(pkg))

from aoc_server import API_VERSION, __version__  # noqa: E402
from aoc_server.config import Settings  # noqa: E402
from aoc_server.db import Database, utcnow  # noqa: E402
from aoc_server.errors import ApiError  # noqa: E402
from aoc_server.security import LoginThrottle  # noqa: E402
from aoc_server.services import bootstrap as bootstrap_service  # noqa: E402
from aoc_server.routers import (admin_auth, admin_config, admin_core, admin_fleet,  # noqa: E402
                                admin_network, admin_ops, auth, player, sync)

log = logging.getLogger("aoc-server")


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings.from_env()
        if not os.environ.get("AOC_SECRET"):
            log.warning("未设置 AOC_SECRET，正在使用开发回退密钥；生产部署必须显式配置")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db: Database = app.state.db
        db.create_all()
        with db.session() as session:
            info = bootstrap_service.bootstrap(session, settings)
        app.state.bootstrap_info = info
        app.state.started_at = utcnow()
        log.info("aoc-server 就绪：%s（API %s）", settings.database_url.split("://", 1)[0],
                 API_VERSION)
        try:
            yield
        finally:
            db.dispose()

    app = FastAPI(title="AOC Server", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.state.login_throttle = LoginThrottle(settings.login_max_failures,
                                             settings.login_window_seconds)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=settings.cors_origins,
            allow_origin_regex=r"^(http://(127\.0\.0\.1|localhost)(:\d+)?|https?://tauri\.localhost|tauri://localhost)$",
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-CSRF-Token",
                           "Idempotency-Key", "X-Request-ID"],
            expose_headers=["X-Request-ID"])

    @app.middleware("http")
    async def _request_id(request: Request, call_next):  # noqa: ANN001
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-AOC-API-Version"] = API_VERSION
        return response

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):  # noqa: ANN001
        return JSONResponse(status_code=exc.status_code, content=exc.payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):  # noqa: ANN001
        fields = []
        for item in exc.errors():
            fields.append({"loc": ".".join(str(x) for x in item.get("loc", [])),
                           "message": item.get("msg")})
        return JSONResponse(status_code=400, content={
            "error": {"code": "VALIDATION_ERROR", "message": "请求参数校验失败",
                      "details": {"fields": fields}}})

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError):  # noqa: ANN001
        log.warning("数据库约束冲突：%s", exc)
        return JSONResponse(status_code=409, content={
            "error": {"code": "CONFLICT", "message": "数据冲突，请刷新后重试"}})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):  # noqa: ANN001
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=exc.status_code, content={
                "error": {"code": f"HTTP_{exc.status_code}", "message": str(exc.detail)}})
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail)})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # noqa: ANN001
        log.exception("未处理异常：%s", exc)
        return JSONResponse(status_code=500, content={
            "error": {"code": "INTERNAL_ERROR", "message": "服务端内部错误"}})

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(player.router, prefix="/api/v1")
    app.include_router(sync.router, prefix="/api/v1")
    app.include_router(admin_auth.router, prefix="/api/v1")
    app.include_router(admin_core.router, prefix="/api/v1")
    app.include_router(admin_config.router, prefix="/api/v1")
    app.include_router(admin_fleet.router, prefix="/api/v1")
    app.include_router(admin_network.router, prefix="/api/v1")
    app.include_router(admin_ops.router, prefix="/api/v1")

    @app.get("/health", tags=["meta"])
    @app.get("/healthz", include_in_schema=False)
    def health() -> dict:
        return {"status": "ok", "version": __version__, "api_version": API_VERSION,
                "time": utcnow().isoformat().replace("+00:00", "Z")}

    @app.get("/readyz", include_in_schema=False)
    def ready(request: Request) -> dict:
        database: Database = request.app.state.db
        with database.session() as session:
            session.execute(sa_text("SELECT 1"))
        return {"status": "ready"}

    @app.get("/api/v1/meta", tags=["meta"])
    def meta() -> dict:
        return {"version": __version__, "api_version": API_VERSION,
                "admin_roles": ["ADMIN", "DISPATCHER"],
                "player_auth": "Bearer", "admin_auth": "Cookie+CSRF",
                "features": ["roster", "sync", "outbox", "review", "audit", "config_versions"]}

    _mount_admin(app, settings)
    return app


def _mount_admin(app: FastAPI, settings: Settings) -> None:
    static_dir = Path(settings.admin_static_dir)
    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/admin/assets", StaticFiles(directory=assets), name="admin-assets")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/admin")

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/{path:path}", include_in_schema=False)
    def admin_spa(path: str = ""):
        index = static_dir / "index.html"
        if path and ".." not in path:
            candidate = (static_dir / path).resolve()
            try:
                candidate.relative_to(static_dir.resolve())
            except ValueError:
                candidate = index
            if candidate.is_file():
                return FileResponse(candidate)
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-store"})
        return JSONResponse(status_code=503, content={
            "error": {"code": "ADMIN_NOT_BUILT",
                      "message": "管理端尚未构建：cd apps/admin-web && npm install && npm run build"}})


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="AOC 联机模式服务端")
    parser.add_argument("--host", default=os.environ.get("AOC_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AOC_PORT", "8080")))
    parser.add_argument("--demo", action="store_true", help="首次启动写入演示机队/航线/航班")
    args = parser.parse_args()
    if args.demo:
        os.environ["AOC_SEED_DEMO"] = "1"
        globals()["app"] = create_app(Settings.from_env())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(globals()["app"], host=args.host, port=args.port)


if __name__ == "__main__":
    main()
