"""aoc-core：个人模式本地 API sidecar（FastAPI，仅 127.0.0.1）。

启动：
    python apps/aoc-core/main.py --port 0 --static-dir apps/client/dist --open

Tauri 会传入 --port/--token/--home；浏览器开发模式直接打开 bootstrap 页面。
所有 /local/*（bootstrap/health 除外）都要求 X-AOC-Token，防止本机跨站请求。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import secrets
import socket
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

def _find_root(start: Path) -> Path:
    """兼容两种布局：仓库 apps/aoc-core/main.py 与 Tauri resources/aoc-core/main.py。"""
    for parent in (start, *start.parents):
        if (parent / "packages" / "aoc_core").is_dir():
            return parent
    return start.parents[2]


ROOT = _find_root(Path(__file__).resolve().parent)
for pkg in (ROOT / "packages" / "aoc_protocol", ROOT / "packages" / "aoc_core",
            ROOT / "packages" / "aoc_navdata", ROOT / "packages" / "aoc_route",
            ROOT / "packages" / "aoc_integrations"):
    if str(pkg) not in sys.path:
        sys.path.insert(0, str(pkg))

from aoc_core import __version__  # noqa: E402
from aoc_core.paths import AppPaths  # noqa: E402
from aoc_core.service import PersonalService  # noqa: E402
from aoc_protocol.schemas import (  # noqa: E402
    CoverageRequest,
    FlownLegIn,
    RecommendRequest,
    RouteRequest,
    ValidateRouteRequest,
    VolantaSyncRequest,
)

log = logging.getLogger("aoc-core")
PUBLIC_PATHS = {"/local/bootstrap", "/local/health", "/healthz", "/readyz", "/local/runtime"}


@dataclass
class CoreConfig:
    home: Path | None = None
    port: int = 0
    token: str = ""
    static_dir: Path | None = None
    open_browser: bool = False
    simlink_url: str | None = None
    simlink_token: str | None = None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def create_app(config: CoreConfig) -> FastAPI:
    paths = AppPaths.create(config.home)
    service = PersonalService(paths)
    if config.simlink_url and config.simlink_token:
        service.set_simlink(config.simlink_url, config.simlink_token)
    static_dir = config.static_dir or (ROOT / "apps" / "client" / "dist")
    token = config.token or secrets.token_urlsafe(24)
    started_at = _now()

    async def _watch_simlink() -> None:
        last: str | None = None
        while True:
            runtime = _read_json(paths.home / "simlink-runtime.json")
            if runtime and runtime.get("url") and runtime.get("token"):
                key = f"{runtime['url']}|{runtime['token']}"
                if key != last:
                    service.set_simlink(runtime["url"], runtime["token"])
                    last = key
            await asyncio.sleep(2.0)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        watcher = asyncio.create_task(_watch_simlink())
        await service.start_polling()
        if config.open_browser:
            threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{config.port}/")).start()
        try:
            yield
        finally:
            watcher.cancel()
            await service.close()

    app = FastAPI(title="AOC Core", version=__version__, lifespan=lifespan)
    app.state.service = service
    app.state.token = token
    app.state.paths = paths
    app.state.started_at = started_at
    app.state.config = config

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173",
                       "http://127.0.0.1:5199", "http://localhost:5199",
                       "tauri://localhost", "https://tauri.localhost"],
        allow_methods=["*"], allow_headers=["*"], allow_credentials=False,
    )

    @app.middleware("http")
    async def auth_and_request_id(request: Request, call_next):
        request_id = secrets.token_hex(8)
        if request.method == "OPTIONS":
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        path = request.url.path
        if path.startswith("/local") and path not in PUBLIC_PATHS:
            supplied = request.headers.get("X-AOC-Token") or request.headers.get("Authorization", "").removeprefix("Bearer ")
            if supplied != token:
                return JSONResponse(status_code=401, content={
                    "code": "AUTH_INVALID", "message": "本地令牌无效，请重新打开 AOC 客户端",
                    "request_id": request_id})
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={
            "code": "PARAM_OUT_OF_RANGE", "message": str(exc),
            "request_id": request.headers.get("X-Request-ID", "")})

    # ---------------- 基础 ----------------
    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/readyz")
    def readyz():
        nav = service.navdata_status()
        return {"ok": True, "db": str(paths.db), "navdata": nav.available,
                "route_engine": nav.available, "simlink": service.flights.simlink_connected}

    @app.get("/local/bootstrap")
    def bootstrap():
        return {
            "token": token,
            "version": __version__,
            "url": f"http://127.0.0.1:{config.port}",
            "home": str(paths.home),
            "db": str(paths.db),
            "navdata": service.navdata_status().model_dump(),
            "recording": service.recording_status(),
            "simlink": {
                "configured": service._simlink_client is not None,
                "connected": service.flights.simlink_connected,
                "version": service.flights.simlink_version,
            },
            "started_at": started_at,
        }

    @app.get("/local/health")
    def local_health():
        return {
            "ok": True, "version": __version__, "db": str(paths.db),
            "navdata": service.navdata_status().model_dump(),
            "recording": service.recording_status(),
            "simlink_connected": service.flights.simlink_connected,
            "started_at": started_at,
        }

    @app.get("/local/runtime")
    def runtime():
        return _read_json(paths.runtime) or {}

    # ---------------- 设置 ----------------
    @app.get("/local/settings")
    def get_settings():
        return {"settings": service.settings}

    @app.put("/local/settings")
    def put_settings(patch: dict[str, Any]):
        return {"settings": service.update_settings(patch)}

    @app.get("/local/aircraft-types")
    def aircraft_types():
        return {"items": service.catalog.list()}

    # ---------------- navdata / 机场 ----------------
    @app.get("/local/navdata/status")
    def navdata_status():
        return service.navdata_status().model_dump()

    @app.post("/local/navdata/select")
    def navdata_select(body: dict[str, Any]):
        return service.select_navdata(body.get("path")).model_dump()

    @app.get("/local/airports")
    def airports(q: str = Query(default="", max_length=40), limit: int = Query(default=20, ge=1, le=50)):
        return {"items": [a.model_dump() for a in service.search_airports(q, limit)]}

    @app.get("/local/airports/{icao}")
    def airport(icao: str):
        info = service.airport_detail(icao)
        if not info:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "机场不在 navdata 中"})
        return info

    # ---------------- 推荐 ----------------
    @app.post("/local/recommend")
    def recommend(request: RecommendRequest):
        return service.recommend(request).model_dump()

    # ---------------- 航路 ----------------
    @app.post("/local/routes/generate")
    def route_generate(request: RouteRequest):
        return service.generate_route(request.dep, request.arr, request.cruise_fl,
                                      request.aircraft_type, request.force_graph).model_dump()

    @app.get("/local/routes/simbrief")
    def route_simbrief(dep: str, arr: str, aircraft_type: str | None = None,
                       cruise_fl: int = 350, route: str | None = None):
        return {"simbrief_url": service.route.simbrief(dep, arr, cruise_fl, aircraft_type, route)}

    @app.post("/local/routes/coverage")
    def route_coverage(request: CoverageRequest):
        return service.route.coverage(request.dep, request.arr, request.cruise_fl).model_dump()

    @app.post("/local/routes/validate")
    def route_validate(request: ValidateRouteRequest):
        return service.route.validate(request.tokens, request.cruise_fl).model_dump()

    @app.post("/local/routes/export")
    def route_export(request: RouteRequest, format: str = Query(default="pln")):
        if format == "pln":
            try:
                text = service.export_pln(request.dep, request.arr, request.cruise_fl)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail={"code": "INVALID_ROUTE", "message": str(exc)}) from exc
            return Response(content=text, media_type="application/xml",
                            headers={"Content-Disposition": f'attachment; filename="{request.dep}-{request.arr}.pln"'})
        result = service.generate_route(request.dep, request.arr, request.cruise_fl,
                                        request.aircraft_type, request.force_graph)
        return PlainTextResponse(result.route or "", headers={
            "X-Route-Status": result.status,
            "X-Route-Source": result.route_source,
        })

    # ---------------- 飞行记录 ----------------
    @app.get("/local/flights")
    def flights(limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0),
                search: str | None = None, status: str | None = None):
        items, total = service.list_flights(limit, offset, search, status)
        return {"items": items, "total": total,
                "next_cursor": str(offset + limit) if offset + limit < total else None}

    @app.get("/local/flights/{flight_id}")
    def flight(flight_id: str):
        item = service.get_flight(flight_id)
        if not item:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "飞行记录不存在"})
        return item

    @app.patch("/local/flights/{flight_id}")
    def flight_update(flight_id: str, body: dict[str, Any]):
        item = service.update_flight(flight_id, body)
        if not item:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "飞行记录不存在"})
        return item

    @app.delete("/local/flights/{flight_id}")
    def flight_delete(flight_id: str):
        return {"ok": service.delete_flight(flight_id)}

    @app.get("/local/flights/{flight_id}/track")
    def flight_track(flight_id: str):
        if not service.get_flight(flight_id):
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "飞行记录不存在"})
        return service.get_track(flight_id)

    @app.get("/local/flights/{flight_id}/export")
    def flight_export(flight_id: str, format: str = Query(default="gpx")):
        try:
            text, filename = service.export_track_text(flight_id, format)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
        media = {"gpx": "application/gpx+xml", "csv": "text/csv", "json": "application/json"}.get(format, "text/plain")
        return Response(content=text, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    # ---------------- 已飞航段 / Volanta ----------------
    @app.get("/local/flown-legs")
    def flown_legs():
        return {"items": [leg.model_dump() for leg in service.list_flown_legs()]}

    @app.post("/local/flown-legs")
    def flown_leg_add(leg: FlownLegIn):
        saved = service.add_flown_leg(leg)
        if saved is None:
            return {"ok": False, "duplicate": True}
        return {"ok": True, "item": saved.model_dump()}

    @app.delete("/local/flown-legs/{leg_id}")
    def flown_leg_delete(leg_id: str):
        return {"ok": service.db.delete_flown_leg(leg_id)}

    @app.get("/local/volanta/status")
    def volanta_status():
        return service.volanta_status()

    @app.post("/local/volanta/sync")
    def volanta_sync(request: VolantaSyncRequest):
        return service.sync_volanta(request.token, request.csv_text).model_dump()

    @app.get("/local/volanta/flights")
    def volanta_flights():
        return {"items": service.volanta_flights()}

    @app.get("/local/volanta/flights/{flight_id}")
    def volanta_flight(flight_id: str):
        item = service.volanta_flight(flight_id)
        if item is None:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "导入航班不存在"})
        return item

    # ---------------- 统计 / 地图 ----------------
    @app.get("/local/stats")
    def stats():
        return service.stats().model_dump()

    @app.get("/local/map")
    def map_data(year: int | None = None):
        return service.map_data(year)

    # ---------------- 录制 ----------------
    @app.get("/local/recording/status")
    def recording_status():
        return service.recording_status()

    @app.post("/local/recording/start")
    async def recording_start():
        try:
            return await service.start_recording()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"code": "SIMLINK_UNAVAILABLE",
                                                         "message": str(exc)}) from exc

    @app.post("/local/recording/stop")
    async def recording_stop(body: dict[str, Any] | None = None):
        return await service.stop_recording(abort=bool((body or {}).get("abort")))

    @app.get("/local/simlink/status")
    async def simlink_status():
        client = service._simlink_client
        if client is None:
            return {"configured": False, "connected": False}
        try:
            status = await client.status()
            return {"configured": True, "connected": True, **status}
        except Exception as exc:  # noqa: BLE001
            return {"configured": True, "connected": False, "error": type(exc).__name__}

    # ---------------- 档案 ----------------
    @app.post("/local/export")
    def export_archive():
        path = service.export_archive()
        return {"ok": True, "path": str(path), "bytes": path.stat().st_size, "format": "zip"}

    @app.get("/local/export/archive")
    def export_archive_download():
        path = service.export_archive()
        return FileResponse(path, media_type="application/zip", filename=path.name)

    @app.post("/local/import-archive")
    def import_archive(body: dict[str, Any]):
        try:
            return service.import_archive(body.get("path", ""))
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail={"code": "IMPORT_FAILED", "message": str(exc)}) from exc

    # ---------------- 静态 SPA ----------------
    assets = static_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("local/"):
            return JSONResponse(status_code=404, content={"code": "NOT_FOUND"})
        index = static_dir / "index.html"
        candidate = (static_dir / full_path).resolve()
        if full_path and candidate.is_file() and static_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        if index.exists():
            return FileResponse(index)
        return JSONResponse({
            "ok": True, "message": "AOC core 已启动，但前端未构建。",
            "hint": "在 apps/client 执行 npm install && npm run build，或用 npm run dev（Vite 代理 /local）。",
        })

    return app


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_runtime(paths: AppPaths, port: int, token: str, simlink: dict | None) -> None:
    payload = {
        "pid": os.getpid(),
        "port": port,
        "url": f"http://127.0.0.1:{port}",
        "token": token,
        "started_at": _now(),
        "version": __version__,
        "simlink": simlink or {},
    }
    paths.runtime.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="AOC core sidecar")
    parser.add_argument("--home", default=None, help="数据目录（默认 %%LOCALAPPDATA%%/AOC）")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default=os.environ.get("AOC_TOKEN", ""))
    parser.add_argument("--static-dir", default=None)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--simlink-url", default=os.environ.get("AOC_SIMLINK_URL"))
    parser.add_argument("--simlink-token", default=os.environ.get("AOC_SIMLINK_TOKEN"))
    args = parser.parse_args()

    home = Path(args.home) if args.home else None
    paths = AppPaths.create(home)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stderr),
                  logging.FileHandler(paths.logs / "aoc-core.log", encoding="utf-8")],
    )
    port = args.port or _free_port()
    token = args.token or secrets.token_urlsafe(24)
    simlink_runtime = _read_json(paths.home / "simlink-runtime.json") or {}
    _write_runtime(paths, port, token, {
        "url": simlink_runtime.get("url"),
        "token": simlink_runtime.get("token"),
        "port": simlink_runtime.get("port"),
    })
    config = CoreConfig(home=home, port=port, token=token,
                        static_dir=Path(args.static_dir) if args.static_dir else None,
                        open_browser=args.open and not os.environ.get("AOC_NO_BROWSER"),
                        simlink_url=args.simlink_url, simlink_token=args.simlink_token)
    app = create_app(config)
    log.info("AOC core %s listening on http://127.0.0.1:%s (home=%s)", __version__, port, paths.home)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
