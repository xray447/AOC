"""个人模式应用服务：把本地库、navdata、航路、Volanta、SimLink、记录器串起来。

API 层（apps/aoc-core）只做参数校验与 JSON 序列化，业务都在这里。
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import shutil
import time as _time
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aoc_integrations.volanta import VolantaClient, extract_track, parse_csv, parse_stored_flight
from aoc_navdata import NavData, NavDataError
from aoc_protocol.schemas import (
    AirportOut,
    FlownLegIn,
    FlownLegOut,
    NavdataStatus,
    RecommendRequest,
    RecommendResponse,
    RouteResult,
    Settings,
    StatsOut,
    VolantaSyncResult,
)
from aoc_route import RouteService, build_pln

from .aircraft import AircraftCatalog
from .db import Database, utcnow
from .flights import FlightService
from .paths import AppPaths
from .recommend import recommend as build_recommend
from .simlink import SimLinkClient
from .stats import compute_stats
from .track import decode_chunks

ROOT = Path(__file__).resolve().parents[3]


class PersonalService:
    def __init__(self, paths: AppPaths | None = None):
        self.paths = paths or AppPaths.create()
        self.db = Database(self.paths)
        self.db.init()
        self._repair_imported_flights()
        self._settings = self._load_settings()
        self.catalog = AircraftCatalog(ROOT / "data" / "aircraft_types.json")
        self._nav: NavData | None = None
        self._nav_path: str | None = None
        self._nav_error: str | None = None
        self._route: RouteService | None = None
        self._simlink_url: str | None = None
        self._simlink_token: str | None = None
        self._simlink_client: SimLinkClient | None = None
        self._evt_seq = -1
        self._auto_start_sent: bool | None = None
        self._last_persist = 0.0
        self._poller_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_status: dict[str, Any] = {}
        self.flights = FlightService(
            self.db, self.paths, lambda: self.nav, lambda: self.settings,
            aircraft_type=lambda: self.settings.get("aircraft_type", "A320"),
            callsign=lambda: self.settings.get("callsign", "AOC001"),
        )
        self.flights.resume()
        self._build_route()

    # -- settings --------------------------------------------------------
    @property
    def settings(self) -> dict[str, Any]:
        return self._settings

    def _load_settings(self) -> dict[str, Any]:
        default = Settings().model_dump()
        stored = self.db.setting_get("settings") or {}
        merged = _deep_merge(default, stored if isinstance(stored, dict) else {})
        try:
            return Settings(**merged).model_dump()
        except Exception:  # noqa: BLE001
            return default

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        merged = _deep_merge(self._settings, patch)
        validated = Settings(**merged).model_dump()
        old_nav = self._settings.get("navdata_path")
        self._settings = validated
        self.db.setting_set("settings", validated)
        if validated.get("navdata_path") != old_nav:
            self._close_nav()
        self._build_route()
        return validated

    # -- navdata ---------------------------------------------------------
    def _navdata_candidate(self) -> str | None:
        path = self._settings.get("navdata_path")
        if path:
            return path
        env = os.environ.get("AOC_NAVDATA")
        if env:
            return env
        appdata = os.environ.get("APPDATA")
        lnm_default = (Path(appdata) / "ABarthel" / "little_navmap_db"
                       / "little_navmap_navigraph.sqlite" if appdata else None)
        candidates = (ROOT / "data" / "little_navmap_navigraph.sqlite",
                      ROOT / "data" / "navdata.sqlite")
        for candidate in (lnm_default, *candidates):
            if candidate is not None and candidate.exists():
                return str(candidate)
        return None

    def _close_nav(self) -> None:
        if self._nav is not None:
            self._nav.close()
        self._nav = None
        self._nav_path = None
        self._nav_error = None

    @property
    def nav(self) -> NavData | None:
        path = self._navdata_candidate()
        if not path:
            return None
        if self._nav is not None and self._nav_path == path:
            return self._nav
        self._close_nav()
        self._nav_path = path
        try:
            self._nav = NavData(path)
        except (NavDataError, Exception) as exc:  # noqa: BLE001
            self._nav_error = f"{type(exc).__name__}: {exc}"
            self._nav = None
        return self._nav

    def navdata_status(self) -> NavdataStatus:
        nav = self.nav
        if nav is None:
            return NavdataStatus(available=False, path=self._navdata_candidate(),
                                 error=self._nav_error or "未配置 navdata")
        counts = nav.counts()
        return NavdataStatus(
            available=True, path=str(nav.path), airac=nav.airac, version=nav.navdata_version,
            airports=counts["airports"], runways=counts["runways"], airways=counts["airways"],
            coverage_ready=counts["airways"] > 0,
        )

    def select_navdata(self, path: str | None) -> NavdataStatus:
        if path:
            p = Path(path).expanduser()
            if not p.exists():
                raise ValueError(f"navdata 文件不存在: {p}")
            if p.is_dir():
                raise ValueError("请选择 SQLite 文件，不是目录")
            self.update_settings({"navdata_path": str(p.resolve())})
        else:
            self.update_settings({"navdata_path": None})
        return self.navdata_status()

    # -- route -----------------------------------------------------------
    def _build_route(self) -> None:
        self._route = RouteService(
            navdata=self.nav,
            aip_path=self._settings.get("aip_path") or None,
            pre_train_dir=self._settings.get("pre_train_dir") or None,
            network_pkl=self._settings.get("network_pkl") or None,
        )

    @property
    def route(self) -> RouteService:
        if self._route is None:
            self._build_route()
        assert self._route is not None
        return self._route

    def generate_route(self, dep: str, arr: str, cruise_fl: int = 350,
                       aircraft: str | None = None, force_graph: bool = False) -> RouteResult:
        ac = aircraft or self._settings.get("aircraft_type") or "A320"
        return self.route.generate(dep, arr, cruise_fl, ac, force_graph)

    # -- airports --------------------------------------------------------
    def search_airports(self, query: str, limit: int = 20) -> list[AirportOut]:
        nav = self.nav
        if nav is None:
            return []
        visited = self.db.visited_airports()
        return [AirportOut(
            icao=a["ident"], iata=a.get("iata"), name=a.get("name"), city=a.get("city"),
            country=a.get("country"), lat=a["lat"], lon=a["lon"], elev_ft=a.get("elev_ft"),
            longest_runway_m=(round(a["longest_runway_ft"] / 3.280839895, 0)
                              if a.get("longest_runway_ft") else None),
            visited=a["ident"] in visited,
        ) for a in nav.search_airports(query, limit)]

    def airport_detail(self, icao: str) -> dict | None:
        nav = self.nav
        if nav is None:
            return None
        info = nav.airport(icao)
        if not info:
            return None
        runways = nav.runways(icao)
        visited = self.db.visited_airports()
        return {
            **info, "icao": info["ident"],
            "visited": info["ident"] in visited,
            "runways": [{
                "ident": r.get("name"), "heading": r.get("hdg"),
                "length_m": r.get("length_m"), "ils": r.get("ils"),
            } for r in runways],
        }

    def map_data(self, year: int | None = None) -> dict:
        nav = self.nav
        flights, _ = self.db.list_flights(limit=5000, status="COMPLETED")
        if year:
            flights = [f for f in flights if (f.get("block_off_utc") or "")[:4] == str(year)]
        aoc_counts: dict[tuple[str, str], int] = {}
        imported_counts: dict[tuple[str, str], int] = {}
        sources: dict[tuple[str, str], set[str]] = {}
        airports: set[str] = set()
        for f in flights:
            dep, arr = f.get("dep_icao"), f.get("arr_icao")
            if dep and arr:
                aoc_counts[(dep, arr)] = aoc_counts.get((dep, arr), 0) + 1
                sources.setdefault((dep, arr), set()).add("AOC")
                airports.update((dep, arr))
        # Volanta / 手动补录的航段：每条都计数（同一对机场飞过多次则线更粗）
        for leg in self.db.list_flown_legs():
            dep = (leg.get("dep_icao") or "").upper()
            arr = (leg.get("arr_icao") or "").upper()
            if not dep or not arr:
                continue
            if year and (leg.get("flight_date") or "")[:4] != str(year):
                continue
            key = (dep, arr)
            imported_counts[key] = imported_counts.get(key, 0) + 1
            sources.setdefault(key, set()).add((leg.get("source") or "MANUAL").upper())
            airports.update(key)
        # 同一对机场的班次取「本地记录」与「导入记录」的较大值：
        # 既不会把两边重复统计成双倍，也不会因为本地有一班就把导入的几十班压成 1
        legs = {key: max(aoc_counts.get(key, 0), imported_counts.get(key, 0))
                for key in set(aoc_counts) | set(imported_counts)}
        for icao in self.db.visited_airports():
            airports.add(icao)
        points = []
        for icao in airports:
            if nav is not None:
                info = nav.airport(icao)
                if info:
                    points.append({"icao": icao, "lat": info["lat"], "lon": info["lon"],
                                   "country": info.get("country"), "name": info.get("name"),
                                   "iata": info.get("iata"), "city": info.get("city"),
                                   "elev_ft": info.get("elev_ft"), "visited": True})
                    continue
            points.append({"icao": icao, "lat": None, "lon": None, "visited": True})
        return {
            "airports": points,
            "legs": [{"dep": d, "arr": a, "count": c,
                      "sources": sorted(sources.get((d, a), {"AOC"}))}
                     for (d, a), c in legs.items()],
            "flights": [{
                "id": f["id"], "dep_icao": f.get("dep_icao"), "arr_icao": f.get("arr_icao"),
                "block_off_utc": f.get("block_off_utc"), "aircraft_type": f.get("aircraft_type"),
                "landing_rating": f.get("landing_rating"),
            } for f in flights],
            "imported_flights": [
                f for f in self.db.list_volanta_flights()
                if not year or (f.get("flight_date") or "")[:4] == str(year)
            ],
        }

    # -- recommend -------------------------------------------------------
    def recommend(self, request: RecommendRequest) -> RecommendResponse:
        home = request.base_icao or self._settings.get("home_airport")
        if not home and self.db.list_flown_legs(1):
            home = self.db.list_flown_legs(1)[0].get("arr_icao")
        if home:
            request = request.model_copy(update={"base_icao": home})
        return build_recommend(
            request, self.nav, self.db.visited_arrivals(), self.db.visited_airports(),
            self.catalog, home_airport=home)

    # -- flights ---------------------------------------------------------
    def list_flights(self, limit: int = 50, offset: int = 0, search: str | None = None,
                     status: str | None = None) -> tuple[list[dict], int]:
        return self.db.list_flights(limit=limit, offset=offset, search=search, status=status)

    def get_flight(self, flight_id: str) -> dict | None:
        return self.db.get_flight(flight_id)

    def get_track(self, flight_id: str) -> dict:
        chunks = self.db.list_chunks(flight_id)
        points, segments = decode_chunks(chunks, self.paths)
        flight = self.db.get_flight(flight_id) or {}
        return {
            "flight_id": flight_id, "points": points, "segments": segments,
            "events": self.db.list_events(flight_id),
            "total_points": len(points), "raw_points": (flight.get("track_profile") or {}).get("raw_points"),
            "fidelity_m": flight.get("track_fidelity_m"), "encoding": "BIN_V1",
        }

    def delete_flight(self, flight_id: str) -> bool:
        ok = self.db.delete_flight(flight_id)
        folder = self.paths.tracks / flight_id
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        return ok

    def update_flight(self, flight_id: str, data: dict) -> dict | None:
        allowed = {k: v for k, v in data.items() if k in ("notes", "dep_icao", "arr_icao", "callsign")}
        return self.db.update_flight(flight_id, allowed) if allowed else self.db.get_flight(flight_id)

    # -- recording -------------------------------------------------------
    def set_simlink(self, url: str | None, token: str | None) -> None:
        self._simlink_url, self._simlink_token = url, token
        self._simlink_client = SimLinkClient(url, token) if url and token else None
        self._auto_start_sent = None

    def recording_status(self) -> dict:
        st = self.flights.status().model_dump()
        st["simlink_last"] = self._last_status
        return st

    async def start_recording(self) -> dict:
        if not self._simlink_client:
            raise RuntimeError("SimLink 未连接，无法开始记录；请确认模拟器和 SimLink 已启动")
        try:
            resp = await self._simlink_client.command("start_recording")
        except Exception as exc:  # noqa: BLE001
            self.flights.last_error = f"SimLink 未响应: {type(exc).__name__}"
            raise RuntimeError("SimLink 未连接，无法开始记录；请确认模拟器和 SimLink 已启动") from exc
        self._evt_seq = -1
        self.flights.start(resp.get("recording_id"), resp.get("recording_started_at"), manual=True)
        return self.recording_status()

    async def stop_recording(self, abort: bool = False) -> dict:
        if self._simlink_client:
            try:
                await self._simlink_client.command("stop_recording")
            except Exception:  # noqa: BLE001
                pass
        flight = self.flights.stop(abort=abort)
        return {"ok": True, "flight": flight}

    # -- simlink polling -------------------------------------------------
    async def poll_simlink_once(self) -> None:
        client = self._simlink_client
        if client is None:
            return
        try:
            status = await client.status()
        except Exception as exc:  # noqa: BLE001
            if self.flights.simlink_connected:
                self.flights.last_error = f"SimLink 连接中断: {type(exc).__name__}"
            self.flights.simlink_connected = False
            return
        self._last_status = status
        self.flights.simlink_connected = True
        self.flights.simlink_version = status.get("version")
        self.flights.sim_connected = bool(status.get("sim_connected"))
        self.flights.aircraft_title = status.get("aircraft_title") or self.flights.aircraft_title
        desired_auto = bool(self._settings.get("auto_start", True))
        if self._auto_start_sent != desired_auto:
            try:
                await client.command("set_auto_start", enabled=desired_auto)
                self._auto_start_sent = desired_auto
            except Exception:  # noqa: BLE001
                pass
        recording = bool(status.get("recording"))
        rec = self.flights.recorder
        if recording:
            if rec is None:
                self.flights.start(status.get("recording_id"), status.get("recording_started_at"),
                                   manual=False)
                self._evt_seq = -1
                rec = self.flights.recorder
            assert rec is not None
            samples = await client.samples(rec.last_seq)
            events = await client.events(self._evt_seq)
            for ev in events:
                seq = ev.get("seq")
                if isinstance(seq, int) and seq > self._evt_seq:
                    self._evt_seq = seq
            self.flights.ingest(samples, events, status.get("recording_id"),
                                status.get("recording_started_at"))
            if _time.monotonic() - self._last_persist >= 5.0:
                self._last_persist = _time.monotonic()
                self.flights._save_persisted()
        elif rec is not None:
            # SimLink 已停止（自动或外部），把已有数据收尾
            self.flights.stop(abort=False)

    async def start_polling(self) -> None:
        if self._poller_task is not None:
            return
        self._stop.clear()
        self._poller_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.poll_simlink_once()
            except Exception as exc:  # noqa: BLE001
                self.flights.last_error = f"遥测轮询失败: {type(exc).__name__}: {exc}"
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

    async def close(self) -> None:
        self._stop.set()
        if self._poller_task:
            self._poller_task.cancel()
            try:
                await self._poller_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self.flights.recorder is not None:
            try:
                self.flights.stop(abort=False)
            except Exception:  # noqa: BLE001
                pass
        self._close_nav()

    # -- flown legs / volanta -------------------------------------------
    def add_flown_leg(self, leg: FlownLegIn) -> FlownLegOut | None:
        data = leg.model_dump()
        if not self.db.add_flown_leg(data):
            return None
        rows = self.db.list_flown_legs(1)
        return FlownLegOut(**rows[0]) if rows else None

    def list_flown_legs(self) -> list[FlownLegOut]:
        return [FlownLegOut(**r) for r in self.db.list_flown_legs()]

    # 导入解析器升级后，用库里已存的原始数据补全/纠正历史行的版本号（见 _repair_imported_flights）
    IMPORTED_REPAIR_VERSION = 2

    def _repair_imported_flights(self) -> int:
        """用已存的原始数据补全旧导入数据的字段（航班号/注册号/日期/机型/时长等）。

        解析器改过字段映射后，历史行里的空值或错值（例如机型被存成嵌套对象的字符串）
        可以在不改动用户数据的前提下就地修正；只跑一次，之后靠版本号跳过。
        """
        marker = "imported_flight_repair"
        current = self.db.setting_get(marker) or 0
        if isinstance(current, int) and current >= self.IMPORTED_REPAIR_VERSION:
            return 0
        fixed = 0
        for flight_id, raw in self.db.volanta_raw_rows():
            leg = parse_stored_flight(raw)
            if leg and self.db.patch_volanta_flight(flight_id, leg):
                fixed += 1
        self.db.setting_set(marker, self.IMPORTED_REPAIR_VERSION)
        return fixed

    def sync_volanta(self, token: str | None = None, csv_text: str | None = None) -> VolantaSyncResult:
        """导入 Volanta 数据：完整航班原始 JSON + 轨迹都落库，只增不删。"""
        client: VolantaClient | None = None
        if csv_text:
            legs = parse_csv(csv_text)
            source = "CSV"
            diagnostic = f"CSV 解析 {len(legs)} 条"
            warnings: list[str] = []
        else:
            client = VolantaClient(token)
            resp = client.fetch_raw()
            legs = resp.get("flights", [])
            source = "VOLANTA"
            diagnostic = resp.get("diagnostic", "")
            warnings = list(resp.get("warnings", []))
        legs_imported = 0
        flights_stored = 0
        tracks_stored = 0
        for leg in legs:
            item = {**leg, "source": source}
            # 列表接口没带轨迹时，按需请求单航班详情（需配置 AOC_VOLANTA_FLIGHT_URL）
            if client is not None and not item.get("track") and item.get("external_id"):
                payload, _error = client.fetch_detail(str(item["external_id"]))
                if payload is not None:
                    item["raw"] = {"list": item.get("raw"), "detail": payload}
                    item["track"] = extract_track(payload)
            if self.db.upsert_volanta_flight(item):
                flights_stored += 1
            if item.get("track"):
                tracks_stored += 1
            if self.db.add_flown_leg(item):
                legs_imported += 1
        self.db.log_volanta_sync(source if legs else "ERROR", len(legs), legs_imported,
                                 "" if legs else diagnostic)
        return VolantaSyncResult(ok=not bool(warnings) or bool(legs), source=source,
                                 legs_found=len(legs), legs_imported=legs_imported,
                                 flights_stored=flights_stored, tracks_stored=tracks_stored,
                                 diagnostic=diagnostic, warnings=warnings)

    def volanta_flights(self, limit: int = 2000) -> list[dict]:
        return self.db.list_volanta_flights(limit)

    def volanta_flight(self, flight_id: str) -> dict | None:
        return self.db.get_volanta_flight(flight_id)

    def volanta_status(self) -> dict:
        return {
            "last_sync": self.db.last_volanta_sync(),
            "flown_legs": self.db.flown_legs_count(),
            "enabled": bool(self._settings.get("volanta_enabled")),
        }

    # -- stats -----------------------------------------------------------
    def stats(self) -> StatsOut:
        flights = self.db.all_completed_flights()
        return compute_stats(flights, self.nav, self.db.visited_airports())

    # -- export ----------------------------------------------------------
    def export_track_text(self, flight_id: str, fmt: str) -> tuple[str, str]:
        flight = self.db.get_flight(flight_id)
        if not flight:
            raise ValueError("飞行记录不存在")
        points, _segments = decode_chunks(self.db.list_chunks(flight_id), self.paths)
        start = flight.get("block_off_utc") or utcnow()
        if fmt == "gpx":
            return _gpx(flight, points, start), f"{flight_id}.gpx"
        if fmt == "csv":
            return _csv(points), f"{flight_id}.csv"
        payload = {"flight": flight, "points": points,
                   "events": self.db.list_events(flight_id)}
        return json.dumps(payload, ensure_ascii=False, default=str), f"{flight_id}.json"

    def export_pln(self, dep: str, arr: str, cruise_fl: int = 350) -> str:
        result = self.generate_route(dep, arr, cruise_fl)
        if not result.route:
            raise ValueError("当前没有可用航路，无法导出 .pln；请使用 SimBrief")
        return build_pln(result, self.nav)

    def export_archive(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target = self.paths.backups / f"AOC-backup-{stamp}.zip"
        db_backup = self.paths.backups / f"aoc-{stamp}.db"
        self.db.backup(db_backup)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_backup, "aoc.db")
            zf.writestr("settings.json", json.dumps(self._settings, ensure_ascii=False, indent=2))
            if self.paths.tracks.exists():
                for path in self.paths.tracks.rglob("*"):
                    if path.is_file():
                        zf.write(path, str(path.relative_to(self.paths.home)))
        try:
            db_backup.unlink()
        except OSError:
            pass
        return target

    def import_archive(self, archive_path: str) -> dict:
        src = Path(archive_path)
        if not src.exists():
            raise ValueError("档案文件不存在")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(src) as zf:
                zf.extractall(tmp_path)
            db_file = tmp_path / "aoc.db"
            if not db_file.exists():
                raise ValueError("档案缺少 aoc.db")
            self.db.backup(self.paths.backups / f"pre-import-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.db")
            if self.flights.recorder is not None:
                self.flights.stop(abort=True)
            self._close_nav()
            shutil.copy2(db_file, self.paths.db)
            tracks = tmp_path / "tracks"
            if tracks.exists():
                shutil.rmtree(self.paths.tracks, ignore_errors=True)
                shutil.copytree(tracks, self.paths.tracks)
        self._settings = self._load_settings()
        self.flights = FlightService(
            self.db, self.paths, lambda: self.nav, lambda: self.settings,
            aircraft_type=lambda: self.settings.get("aircraft_type", "A320"),
            callsign=lambda: self.settings.get("callsign", "AOC001"))
        self.flights.resume()
        self._build_route()
        return {"ok": True, "settings": self._settings}


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _gpx(flight: dict, points: list[dict], start_iso: str) -> str:
    try:
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except ValueError:
        start = datetime.now(timezone.utc)
    from datetime import timedelta
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="AOC" xmlns="http://www.topografix.com/GPX/1/1">',
        f"  <metadata><name>{flight.get('callsign') or flight['id']}</name></metadata>",
        "  <trk>",
        f"    <name>{flight.get('dep_icao') or '????'} → {flight.get('arr_icao') or '????'}</name>",
        "    <trkseg>",
    ]
    for p in points:
        ts = (start + timedelta(seconds=float(p["t"]))).isoformat(timespec="seconds").replace("+00:00", "Z")
        lines.append(
            f'      <trkpt lat="{float(p["lat"]):.6f}" lon="{float(p["lon"]):.6f}">'
            f"<ele>{float(p.get('alt_ft') or 0) * 0.3048:.1f}</ele><time>{ts}</time></trkpt>")
    lines += ["    </trkseg>", "  </trk>", "</gpx>", ""]
    return "\n".join(lines)


def _csv(points: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["t", "lat", "lon", "alt_ft", "gs_kt", "vs_fpm", "hdg_true", "fuel_kg", "g"])
    for p in points:
        writer.writerow([p.get("t"), p.get("lat"), p.get("lon"), p.get("alt_ft"),
                         p.get("gs_kt"), p.get("vs_fpm"), p.get("hdg_true"),
                         p.get("fuel_kg"), p.get("g")])
    return buf.getvalue()
