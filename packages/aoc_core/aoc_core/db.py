"""SQLite 本地库（WAL）。

个人模式只使用 docs/03 §2.6 列出的表 + `flight_record`/`track_chunk`/`flight_event`；
公司模式表结构在 M2 的服务端实现，这里不建空表。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .paths import AppPaths

SCHEMA_VERSION = 1

JSON_FIELDS = {
    "track_profile_json": "track_profile",
    "validation_notes_json": "validation_notes",
    "anomaly_flags_json": "anomaly_flags",
}
JSON_ALIASES = {v: k for k, v in JSON_FIELDS.items()}

FLIGHT_COLUMNS = [
    "id", "mode", "status", "callsign", "aircraft_type", "aircraft_title", "airac",
    "dep_icao", "arr_icao", "scheduled_dep_utc", "scheduled_arr_utc",
    "block_off_utc", "takeoff_utc", "landing_utc", "block_on_utc", "block_minutes",
    "route_string", "route_source", "coverage", "altitude_valid", "mission_type",
    "distance_nm", "fuel_start_kg", "fuel_end_kg", "fuel_used_kg",
    "actual_zfw_kg", "zfw_delta_kg",
    "max_g_flight", "max_g_landing", "touchdown_g", "touchdown_vs_fpm",
    "touchdown_lat", "touchdown_lon", "runway_ident", "threshold_distance_m",
    "centerline_offset_m", "bounce_count", "landing_distance_m", "landing_rating",
    "displaced_threshold_m",
    "track_profile_json", "track_points", "track_bytes", "track_fidelity_m",
    "track_sha256", "data_gap_seconds", "validation_status",
    "validation_notes_json", "anomaly_flags_json", "notes", "created_at", "updated_at",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_setting (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS flown_leg (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT,
    dep_icao TEXT NOT NULL,
    arr_icao TEXT NOT NULL,
    flight_date TEXT,
    aircraft_type TEXT,
    duration_min INTEGER,
    landing_rate_fpm REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flown_leg_arr ON flown_leg(arr_icao);
CREATE INDEX IF NOT EXISTS idx_flown_leg_pair ON flown_leg(dep_icao, arr_icao, flight_date);
-- Volanta / 导入航班的完整数据：原始 JSON + 轨迹点，导入不覆盖已有记录（同一条则更新）
CREATE TABLE IF NOT EXISTS volanta_flight (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT,
    callsign TEXT,
    registration TEXT,
    dep_icao TEXT,
    arr_icao TEXT,
    flight_date TEXT,
    aircraft_type TEXT,
    duration_min INTEGER,
    landing_rate_fpm REAL,
    point_count INTEGER NOT NULL DEFAULT 0,
    track_json TEXT,
    raw_json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_volanta_flight_pair ON volanta_flight(dep_icao, arr_icao, flight_date);
CREATE TABLE IF NOT EXISTS volanta_sync (
    id TEXT PRIMARY KEY,
    synced_at TEXT NOT NULL,
    status TEXT NOT NULL,
    legs_count INTEGER NOT NULL DEFAULT 0,
    imported_count INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS flight_record (
    id TEXT PRIMARY KEY,
    company_id TEXT,
    user_id TEXT,
    aircraft_id TEXT,
    flight_instance_id TEXT,
    roster_leg_id TEXT,
    mode TEXT NOT NULL DEFAULT 'PERSONAL',
    status TEXT NOT NULL DEFAULT 'RECORDING',
    callsign TEXT,
    aircraft_type TEXT,
    aircraft_title TEXT,
    airac TEXT,
    dep_icao TEXT,
    arr_icao TEXT,
    scheduled_dep_utc TEXT,
    scheduled_arr_utc TEXT,
    block_off_utc TEXT,
    takeoff_utc TEXT,
    landing_utc TEXT,
    block_on_utc TEXT,
    block_minutes REAL,
    route_string TEXT,
    route_source TEXT,
    coverage TEXT,
    altitude_valid INTEGER,
    mission_type TEXT,
    distance_nm REAL,
    fuel_start_kg REAL,
    fuel_end_kg REAL,
    fuel_used_kg REAL,
    actual_zfw_kg REAL,
    zfw_delta_kg REAL,
    max_g_flight REAL,
    max_g_landing REAL,
    touchdown_g REAL,
    touchdown_vs_fpm REAL,
    touchdown_lat REAL,
    touchdown_lon REAL,
    runway_ident TEXT,
    threshold_distance_m REAL,
    centerline_offset_m REAL,
    bounce_count INTEGER,
    landing_distance_m REAL,
    landing_rating TEXT,
    displaced_threshold_m REAL,
    track_profile_json TEXT,
    track_points INTEGER,
    track_bytes INTEGER,
    track_fidelity_m REAL,
    track_sha256 TEXT,
    data_gap_seconds REAL,
    validation_status TEXT,
    validation_notes_json TEXT,
    anomaly_flags_json TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flight_created ON flight_record(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_flight_status ON flight_record(status);
CREATE TABLE IF NOT EXISTS track_chunk (
    id TEXT PRIMARY KEY,
    flight_record_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    mode TEXT NOT NULL,
    start_t_offset_ms INTEGER NOT NULL,
    end_t_offset_ms INTEGER NOT NULL,
    sample_interval_ms INTEGER,
    encoding TEXT NOT NULL,
    point_count INTEGER NOT NULL,
    payload_path TEXT NOT NULL,
    sha256 TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (flight_record_id, seq)
);
CREATE TABLE IF NOT EXISTS flight_event (
    id TEXT PRIMARY KEY,
    flight_record_id TEXT NOT NULL,
    t_offset_ms INTEGER NOT NULL,
    type TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_flight ON flight_event(flight_record_id, t_offset_ms);
"""

FLIGHT_DDL = ";".join(
    f'ALTER TABLE flight_record ADD COLUMN "{c}" TEXT' for c in ()
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def _json(value: Any, default: Any) -> str:
    return json.dumps(default if value is None else value, ensure_ascii=False)


class Database:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.path = paths.db

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=15.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=5000")
        return con

    @contextmanager
    def session(self):
        """连接 + 事务 + **一定关闭**（sqlite3 的 with 不会 close，长跑会泄漏锁）。"""
        con = self.connect()
        try:
            with con:
                yield con
        finally:
            con.close()

    def init(self) -> None:
        con = self.connect()
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)
            con.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
                        (str(SCHEMA_VERSION),))
            con.commit()
        finally:
            con.close()
        self._ensure_columns()
        self._backfill_volanta_flights()

    def _ensure_columns(self) -> None:
        """老库补列：`CREATE TABLE IF NOT EXISTS` 不会给已存在的表加列。"""
        with self.session() as con:
            existing = {r["name"] for r in con.execute("pragma table_info(volanta_flight)")}
            for name, ddl in (("callsign", "TEXT"), ("registration", "TEXT")):
                if name not in existing:
                    con.execute(f"alter table volanta_flight add column {name} {ddl}")
            flight_cols = {r["name"] for r in con.execute("pragma table_info(flight_record)")}
            for name, ddl in (("actual_zfw_kg", "REAL"), ("zfw_delta_kg", "REAL"),
                              ("displaced_threshold_m", "REAL")):
                if name not in flight_cols:
                    con.execute(f"alter table flight_record add column {name} {ddl}")

    def _backfill_volanta_flights(self) -> None:
        """旧版本只把导入航段写进 flown_leg：这里补齐 volanta_flight（幂等，不删任何数据）。"""
        now = utcnow()
        with self.session() as con:
            # AOC 自己记录的航班不属于“导入”，若早先被补进来则清掉
            con.execute("delete from volanta_flight where source = 'AOC'")
            rows = con.execute(
                "select * from flown_leg fl where fl.source <> 'AOC' and not exists ("
                " select 1 from volanta_flight vf where vf.source = fl.source"
                " and coalesce(vf.dep_icao,'') = coalesce(fl.dep_icao,'')"
                " and coalesce(vf.arr_icao,'') = coalesce(fl.arr_icao,'')"
                " and coalesce(vf.flight_date,'') = coalesce(fl.flight_date,'')"
                " and coalesce(vf.aircraft_type,'') = coalesce(fl.aircraft_type,'')"
                " and coalesce(vf.duration_min,-1) = coalesce(fl.duration_min,-1)"
                " and coalesce(vf.landing_rate_fpm,-1) = coalesce(fl.landing_rate_fpm,-1))"
            ).fetchall()
            for row in rows:
                con.execute(
                    "insert into volanta_flight(id, source, external_id, dep_icao, arr_icao, flight_date, "
                    "aircraft_type, duration_min, landing_rate_fpm, point_count, track_json, raw_json, "
                    "imported_at, updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), row["source"], row["external_id"], row["dep_icao"], row["arr_icao"],
                     row["flight_date"], row["aircraft_type"], row["duration_min"],
                     row["landing_rate_fpm"], 0, None,
                     json.dumps({"backfilled_from": "flown_leg", "id": row["id"]}, ensure_ascii=False),
                     now, now))

    # -- settings --------------------------------------------------------
    def settings_all(self) -> dict[str, Any]:
        with self.session() as con:
            return {r["key"]: json.loads(r["value_json"])
                    for r in con.execute("select key, value_json from app_setting")}

    def setting_get(self, key: str) -> Any:
        with self.session() as con:
            row = con.execute("select value_json from app_setting where key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def setting_set(self, key: str, value: Any) -> None:
        with self.session() as con:
            con.execute(
                "INSERT INTO app_setting(key, value_json, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                (key, _json(value, {}), utcnow()))

    def settings_put(self, values: dict[str, Any]) -> None:
        now = utcnow()
        with self.session() as con:
            for key, value in values.items():
                con.execute(
                    "INSERT INTO app_setting(key, value_json, updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                    (key, _json(value, {}), now))

    # -- flights ---------------------------------------------------------
    def insert_flight(self, data: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        data = {JSON_ALIASES.get(k, k): v for k, v in data.items()}
        record = {"id": data.get("id") or new_id(), "created_at": data.get("created_at") or now,
                  "updated_at": now}
        for key in FLIGHT_COLUMNS:
            if key in ("id", "created_at", "updated_at"):
                continue
            if key in data:
                record[key] = data[key]
        if "track_profile_json" in record and not isinstance(record["track_profile_json"], str):
            record["track_profile_json"] = _json(record["track_profile_json"], {})
        if "validation_notes_json" in record and not isinstance(record["validation_notes_json"], str):
            record["validation_notes_json"] = _json(record["validation_notes_json"], [])
        if "anomaly_flags_json" in record and not isinstance(record["anomaly_flags_json"], str):
            record["anomaly_flags_json"] = _json(record["anomaly_flags_json"], [])
        for key, value in list(record.items()):
            if isinstance(value, bool):
                record[key] = 1 if value else 0
        cols = [c for c in record if c in FLIGHT_COLUMNS]
        sql = f"insert into flight_record ({','.join(cols)}) values ({','.join('?' * len(cols))})"
        with self.session() as con:
            con.execute(sql, [record[c] for c in cols])
        return self.get_flight(record["id"]) or {}

    def update_flight(self, flight_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        updates = {}
        data = {JSON_ALIASES.get(k, k): v for k, v in data.items()}
        for key, value in data.items():
            if key not in FLIGHT_COLUMNS or key in ("id", "created_at"):
                continue
            if key in JSON_FIELDS and not isinstance(value, str):
                updates[JSON_FIELDS[key] + "_json"] = _json(value, {} if key == "track_profile_json" else [])
            elif key.endswith("_json") and not isinstance(value, str):
                updates[key] = _json(value, {})
            else:
                updates[key] = 1 if isinstance(value, bool) else value
        updates["updated_at"] = utcnow()
        if not updates:
            return self.get_flight(flight_id)
        sql = f"update flight_record set {','.join(f'{k}=?' for k in updates)} where id=?"
        with self.session() as con:
            cur = con.execute(sql, [*updates.values(), flight_id])
            if cur.rowcount == 0:
                return None
        return self.get_flight(flight_id)

    def get_flight(self, flight_id: str) -> dict[str, Any] | None:
        with self.session() as con:
            row = con.execute("select * from flight_record where id=?", (flight_id,)).fetchone()
        return self._flight_row(row) if row else None

    def _flight_row(self, row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        for json_col, alias in JSON_FIELDS.items():
            raw = out.pop(json_col, None)
            try:
                out[alias] = json.loads(raw) if raw else ({} if alias == "track_profile" else [])
            except json.JSONDecodeError:
                out[alias] = {} if alias == "track_profile" else []
        for key in ("altitude_valid",):
            if out.get(key) is not None:
                out[key] = bool(out[key])
        return out

    def list_flights(self, limit: int = 50, offset: int = 0, search: str | None = None,
                     status: str | None = None, dep: str | None = None, arr: str | None = None,
                     sort: str = "recent") -> tuple[list[dict[str, Any]], int]:
        where, args = [], []
        if search:
            where.append("(callsign like ? or dep_icao like ? or arr_icao like ? or aircraft_type like ?)")
            args += [f"%{search.upper()}%"] * 4
        if status:
            where.append("status=?")
            args.append(status)
        if dep:
            where.append("dep_icao=?")
            args.append(dep.upper())
        if arr:
            where.append("arr_icao=?")
            args.append(arr.upper())
        clause = (" where " + " and ".join(where)) if where else ""
        order = ("order by coalesce(block_off_utc, created_at) desc"
                 if sort == "recent" else "order by distance_nm desc")
        with self.session() as con:
            total = con.execute(f"select count(*) from flight_record{clause}", args).fetchone()[0]
            rows = con.execute(
                f"select * from flight_record{clause} {order} limit ? offset ?",
                [*args, limit, offset]).fetchall()
        return [self._flight_row(r) for r in rows], int(total)

    def delete_flight(self, flight_id: str) -> bool:
        with self.session() as con:
            con.execute("delete from track_chunk where flight_record_id=?", (flight_id,))
            con.execute("delete from flight_event where flight_record_id=?", (flight_id,))
            cur = con.execute("delete from flight_record where id=?", (flight_id,))
            return cur.rowcount > 0

    # -- chunks / events --------------------------------------------------
    def add_chunks(self, flight_id: str, chunks: Iterable[dict[str, Any]]) -> None:
        now = utcnow()
        with self.session() as con:
            for chunk in chunks:
                con.execute(
                    "INSERT OR REPLACE INTO track_chunk(id, flight_record_id, seq, mode, "
                    "start_t_offset_ms, end_t_offset_ms, sample_interval_ms, encoding, point_count, "
                    "payload_path, sha256, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), flight_id, chunk["seq"], chunk["mode"], chunk["start_t_offset_ms"],
                     chunk["end_t_offset_ms"], chunk.get("sample_interval_ms"), chunk["encoding"],
                     chunk["point_count"], chunk["payload_path"], chunk.get("sha256"), now))

    def list_chunks(self, flight_id: str) -> list[dict[str, Any]]:
        with self.session() as con:
            rows = con.execute(
                "select * from track_chunk where flight_record_id=? order by seq", (flight_id,)).fetchall()
        return [dict(r) for r in rows]

    def add_events(self, flight_id: str, events: Iterable[dict[str, Any]]) -> None:
        now = utcnow()
        with self.session() as con:
            for ev in events:
                con.execute(
                    "insert into flight_event(id, flight_record_id, t_offset_ms, type, payload_json, created_at) "
                    "values(?,?,?,?,?,?)",
                    (new_id(), flight_id, int(ev.get("t_offset_ms", 0)), ev["type"],
                     _json(ev.get("payload"), {}), now))

    def list_events(self, flight_id: str) -> list[dict[str, Any]]:
        with self.session() as con:
            rows = con.execute(
                "select * from flight_event where flight_record_id=? order by t_offset_ms",
                (flight_id,)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
            except json.JSONDecodeError:
                item["payload"] = {}
            out.append(item)
        return out

    # -- flown legs -------------------------------------------------------
    def add_flown_leg(self, leg: dict[str, Any]) -> bool:
        dep, arr = (leg.get("dep_icao") or "").upper(), (leg.get("arr_icao") or "").upper()
        if not dep or not arr:
            return False
        source = leg.get("source") or "MANUAL"
        with self.session() as con:
            if leg.get("external_id"):
                row = con.execute("select id from flown_leg where source=? and external_id=?",
                                  (source, leg["external_id"])).fetchone()
                if row:
                    return False
            row = con.execute(
                "select id from flown_leg where source=? and dep_icao=? and arr_icao=? "
                "and coalesce(flight_date,'')=coalesce(?,'') "
                "and coalesce(aircraft_type,'')=coalesce(?,'') "
                "and coalesce(duration_min,-1)=coalesce(?,-1) "
                "and coalesce(landing_rate_fpm,-1)=coalesce(?,-1)",
                (source, dep, arr, leg.get("flight_date"), leg.get("aircraft_type"),
                 leg.get("duration_min"), leg.get("landing_rate_fpm"))).fetchone()
            if row:
                return False
            con.execute(
                "insert into flown_leg(id, source, external_id, dep_icao, arr_icao, flight_date, "
                "aircraft_type, duration_min, landing_rate_fpm, created_at) values(?,?,?,?,?,?,?,?,?,?)",
                (new_id(), source, leg.get("external_id"), dep, arr, leg.get("flight_date"),
                 leg.get("aircraft_type"), leg.get("duration_min"), leg.get("landing_rate_fpm"), utcnow()))
        return True

    def list_flown_legs(self, limit: int = 5000, offset: int = 0) -> list[dict[str, Any]]:
        with self.session() as con:
            rows = con.execute(
                "select * from flown_leg order by coalesce(flight_date, created_at) desc limit ? offset ?",
                (limit, offset)).fetchall()
        return [dict(r) for r in rows]

    def flown_legs_count(self) -> int:
        with self.session() as con:
            return int(con.execute("select count(*) from flown_leg").fetchone()[0])

    def visited_arrivals(self) -> set[str]:
        with self.session() as con:
            return {r[0].upper() for r in con.execute("select distinct arr_icao from flown_leg") if r[0]}

    def visited_airports(self) -> set[str]:
        with self.session() as con:
            rows = con.execute("select dep_icao, arr_icao from flown_leg").fetchall()
        out: set[str] = set()
        for r in rows:
            if r[0]:
                out.add(r[0].upper())
            if r[1]:
                out.add(r[1].upper())
        return out

    # -- 导入航班（原始数据 + 轨迹） ------------------------------------
    def upsert_volanta_flight(self, flight: dict[str, Any]) -> bool:
        """写入或更新一条导入航班；返回是否新增（不删除任何历史记录）。"""
        source = (flight.get("source") or "VOLANTA").upper()
        external_id = flight.get("external_id")
        dep = (flight.get("dep_icao") or "").upper() or None
        arr = (flight.get("arr_icao") or "").upper() or None
        track = flight.get("track")
        track_json = json.dumps(track, ensure_ascii=False) if track else None
        raw = flight.get("raw") if flight.get("raw") is not None else flight
        raw_json = json.dumps(raw, ensure_ascii=False, default=str)
        point_count = len(track) if track else 0
        now = utcnow()
        with self.session() as con:
            row = None
            if external_id:
                row = con.execute("select id from volanta_flight where source=? and external_id=?",
                                  (source, str(external_id))).fetchone()
            if row is None:
                row = con.execute(
                    "select id from volanta_flight where source=? and coalesce(dep_icao,'')=coalesce(?,'') "
                    "and coalesce(arr_icao,'')=coalesce(?,'') and coalesce(flight_date,'')=coalesce(?,'') "
                    "and coalesce(aircraft_type,'')=coalesce(?,'') "
                    "and coalesce(duration_min,-1)=coalesce(?,-1) "
                    "and coalesce(landing_rate_fpm,-1)=coalesce(?,-1)",
                    (source, dep, arr, flight.get("flight_date"), flight.get("aircraft_type"),
                     flight.get("duration_min"), flight.get("landing_rate_fpm"))).fetchone()
            if row:
                con.execute(
                    "update volanta_flight set dep_icao=?, arr_icao=?, callsign=coalesce(?, callsign), "
                    "registration=coalesce(?, registration), "
                    "flight_date=?, aircraft_type=?, "
                    "duration_min=?, landing_rate_fpm=?, point_count=?, "
                    "track_json=coalesce(?, track_json), raw_json=?, updated_at=? where id=?",
                    (dep, arr, flight.get("callsign"), flight.get("registration"),
                     flight.get("flight_date"), flight.get("aircraft_type"),
                     flight.get("duration_min"), flight.get("landing_rate_fpm"), point_count,
                     track_json, raw_json, now, row["id"]))
                return False
            con.execute(
                "insert into volanta_flight(id, source, external_id, callsign, registration, dep_icao, "
                "arr_icao, flight_date, aircraft_type, duration_min, landing_rate_fpm, point_count, "
                "track_json, raw_json, imported_at, updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id(), source, str(external_id) if external_id else None, flight.get("callsign"),
                 flight.get("registration"), dep, arr, flight.get("flight_date"),
                 flight.get("aircraft_type"), flight.get("duration_min"),
                 flight.get("landing_rate_fpm"), point_count, track_json, raw_json, now, now))
        return True

    def list_volanta_flights(self, limit: int = 5000, offset: int = 0) -> list[dict[str, Any]]:
        with self.session() as con:
            rows = con.execute(
                "select id, source, external_id, callsign, registration, dep_icao, arr_icao, "
                "flight_date, aircraft_type, duration_min, landing_rate_fpm, point_count, "
                "imported_at, updated_at "
                "from volanta_flight where source <> 'AOC' "
                "order by coalesce(flight_date, imported_at) desc limit ? offset ?",
                (limit, offset)).fetchall()
        return [dict(r) for r in rows]

    VOLANTA_FIELDS = ("callsign", "registration", "flight_date", "aircraft_type",
                      "duration_min", "landing_rate_fpm")

    def volanta_raw_rows(self) -> list[tuple[str, Any]]:
        """取出所有导入航班的原始数据，供解析器升级后重新解析（只读）。"""
        with self.session() as con:
            rows = con.execute("select id, raw_json from volanta_flight").fetchall()
        out: list[tuple[str, Any]] = []
        for row in rows:
            try:
                out.append((row["id"], json.loads(row["raw_json"] or "{}")))
            except json.JSONDecodeError:
                continue
        return out

    def patch_volanta_flight(self, flight_id: str, patch: dict[str, Any]) -> bool:
        """只写入发生变化的标准字段；没有任何变化时返回 False。"""
        fields = {k: v for k, v in patch.items() if k in self.VOLANTA_FIELDS and v is not None}
        if not fields:
            return False
        with self.session() as con:
            row = con.execute(
                f"select {','.join(self.VOLANTA_FIELDS)} from volanta_flight where id=?",
                (flight_id,)).fetchone()
            if row is None:
                return False
            changed = {k: v for k, v in fields.items() if row[k] != v}
            if not changed:
                return False
            con.execute(
                f"update volanta_flight set {','.join(f'{k}=?' for k in changed)}, updated_at=? "
                "where id=?",
                (*changed.values(), utcnow(), flight_id))
        return True

    def get_volanta_flight(self, flight_id: str) -> dict[str, Any] | None:
        with self.session() as con:
            row = con.execute("select * from volanta_flight where id=?", (flight_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["track"] = json.loads(item.pop("track_json") or "null")
        except json.JSONDecodeError:
            item["track"] = None
        try:
            item["raw"] = json.loads(item.pop("raw_json") or "{}")
        except json.JSONDecodeError:
            item["raw"] = {}
        return item

    def volanta_flight_count(self) -> int:
        with self.session() as con:
            return int(con.execute("select count(*) from volanta_flight").fetchone()[0])

    def delete_flown_leg(self, leg_id: str) -> bool:
        with self.session() as con:
            return con.execute("delete from flown_leg where id=?", (leg_id,)).rowcount > 0

    def log_volanta_sync(self, status: str, legs_count: int, imported_count: int, error: str = "") -> None:
        with self.session() as con:
            con.execute(
                "insert into volanta_sync(id, synced_at, status, legs_count, imported_count, error) "
                "values(?,?,?,?,?,?)",
                (new_id(), utcnow(), status, legs_count, imported_count, error or None))

    def last_volanta_sync(self) -> dict[str, Any] | None:
        with self.session() as con:
            row = con.execute("select * from volanta_sync order by synced_at desc limit 1").fetchone()
        return dict(row) if row else None

    # -- stats ------------------------------------------------------------
    def all_completed_flights(self) -> list[dict[str, Any]]:
        with self.session() as con:
            rows = con.execute(
                "select * from flight_record where status in ('COMPLETED','DIVERTED') "
                "order by coalesce(block_off_utc, created_at)").fetchall()
        return [self._flight_row(r) for r in rows]

    def backup(self, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(str(self.path))
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return target
