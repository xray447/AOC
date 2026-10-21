"""M2 单机运营服务：机队、航线/班期、抽班、自由飞、配载、结算、账本、规则版本。

全部逻辑在本机 SQLite 内完成（无服务端、无账号、无公司实体）。
API 层只做参数校验与序列化。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import statistics
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from aoc_navdata import NavData

from ..aircraft import AircraftCatalog
from ..db import Database, new_id, utcnow
from . import economy as eco
from .policy import SEVERITY, cost_item_allowed, detect_anomalies, evaluate, resolve_policy
from .schema import ensure_schema
from .specs import (
    PARAM_SCHEMA,
    build_aircraft_types,
    default_economy,
    default_policy,
)

CONSTRAINT_LIMITS = {
    "window_hours": (1, 168, 24),
    "max_legs": (1, 8, 3),
    "max_block_minutes": (30, 1440, 480),
    "min_turnaround_min": (15, 240, 45),
    "max_turnaround_min": (30, 1440, 360),
}
FREE_LOCK_MINUTES = 30
CANDIDATE_TTL_SECONDS = 300
LEDGER_TYPES = (
    "REVENUE_PAX", "REVENUE_PAX_BUSINESS", "REVENUE_PAX_FIRST", "REVENUE_CARGO",
    "REVENUE_MAIL", "REVENUE_ANCILLARY", "REVENUE_CHARTER", "REVENUE_INSURANCE",
    "POLICY_ADJUSTMENT", "REVENUE_ADJUSTMENT", "ADVANCE_PAYOUT", "ADVANCE_CLAWBACK",
    "COST_FUEL", "COST_LANDING", "COST_HANDLING", "COST_CREW", "COST_MAINTENANCE",
    "COST_LEASE", "COST_PARKING", "COST_ATC", "COST_INSURANCE", "COST_REPAIR",
    "PENALTY_CANCEL", "PENALTY_NO_SHOW", "PENALTY_DIVERSION",
)
ACTIVE_TASK_KEY = "ops_active_task"
NO_SHOW_KEY = "ops_no_show_count"


class OpsError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


def _json_load(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_prefix(value: Any) -> str:
    """呼号/航班号前缀：大写字母数字，最多 4 位。"""
    text = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()[:4]
    return text


def _with_prefix(flight_number: str | None, prefix: str) -> str:
    """把航班号的字母前缀换成 prefix（AOC101 → AUV101）；没有数字时原样返回。"""
    number = (flight_number or "").strip().upper()
    if not number:
        return ""
    digits = re.sub(r"^[A-Z0-9]*?(\d+)$", r"\1", number)
    if not digits or digits == number:
        return number
    return f"{prefix}{digits}"


def _simbrief_payload(*, dep: str | None = None, arr: str | None = None,
                      aircraft_type: str | None = None, callsign: str | None = None,
                      registration: str | None = None,
                      sheet: dict[str, Any] | None = None) -> dict[str, Any]:
    """SimBrief 预填参数：机场/机型/呼号/注册号，有配载单时再带上旅客与重量。"""
    payload: dict[str, Any] = {
        "dep": (dep or "").upper(), "arr": (arr or "").upper(),
        "aircraft_type": aircraft_type, "callsign": callsign,
        "registration": registration, "pax": None, "payload_kg": None,
        "fuel_kg": None, "zfw_kg": None, "tow_kg": None, "block_minutes": None,
    }
    if sheet:
        zfw = float(sheet.get("zfw_kg") or 0)
        oew = float(sheet.get("oew_kg") or 0)
        payload.update({
            "pax": int(sheet.get("pax_total") or 0),
            # SimBrief 只吃一个 kg 的 payload（旅客 + 货物 + 邮件 = ZFW − OEW）
            "payload_kg": round(zfw - oew, 1) if zfw and oew else None,
            "fuel_kg": round(float(sheet.get("fuel_kg") or 0), 1),
            "zfw_kg": round(zfw, 1),
            "tow_kg": round(float(sheet.get("tow_kg") or 0), 1),
            "block_minutes": sheet.get("block_minutes"),
        })
    return payload


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class OpsService:
    def __init__(self, db: Database, nav_provider, catalog: AircraftCatalog):
        self.db = db
        self._nav = nav_provider
        self.catalog = catalog
        self._tx_depth = 0
        self._expiring = False
        ensure_schema(db)
        self._seed_types()
        self._seed_profile()

    @contextmanager
    def _tx(self):
        """写事务；事务内禁止再做会写库的维护动作（如过期清理）。"""
        self._tx_depth += 1
        con = self.db.connect()
        try:
            with con:
                yield con
        finally:
            con.close()
            self._tx_depth -= 1

    # ------------------------------------------------------------------ 基础
    @property
    def nav(self) -> NavData | None:
        try:
            return self._nav()
        except Exception:  # noqa: BLE001
            return None

    def _rows(self, sql: str, args: tuple | list = ()) -> list[dict[str, Any]]:
        with self._tx() as con:
            return [dict(r) for r in con.execute(sql, args).fetchall()]

    def _one(self, sql: str, args: tuple | list = ()) -> dict[str, Any] | None:
        rows = self._rows(sql, args)
        return rows[0] if rows else None

    def _meta_get(self, key: str, default: Any = None) -> Any:
        row = self._one("select value from ops_meta where key=?", (key,))
        return _json_load(row["value"], default) if row else default

    def _meta_set(self, key: str, value: Any, con=None) -> None:
        sql = ("insert into ops_meta(key, value) values(?,?) "
               "on conflict(key) do update set value=excluded.value")
        payload = json.dumps(value, ensure_ascii=False)
        if con is not None:
            con.execute(sql, (key, payload))
        else:
            with self.db.session() as c:
                c.execute(sql, (key, payload))

    def _audit(self, con, action: str, entity_type: str, entity_id: str | None,
               before: Any = None, after: Any = None, reason: str | None = None) -> None:
        profile = self.profile() or {}
        con.execute(
            "insert into ops_audit(id, action, entity_type, entity_id, before_json, after_json, "
            "reason, actor, created_at) values(?,?,?,?,?,?,?,?,?)",
            (new_id(), action, entity_type, entity_id,
             json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
             json.dumps(after, ensure_ascii=False, default=str) if after is not None else None,
             reason, profile.get("name") or "local", utcnow()))

    def _secret(self) -> str:
        secret = self._meta_get("secret")
        if not secret:
            secret = hashlib.sha256(f"{new_id()}-{utcnow()}".encode()).hexdigest()
            self._meta_set("secret", secret)
        return str(secret)

    # ------------------------------------------------------------------ 种子
    def _seed_types(self) -> None:
        row = self._one("select count(*) as n from aircraft_type")
        if row and row["n"]:
            return
        stamp = utcnow()
        with self._tx() as con:
            for item in build_aircraft_types(self.catalog.list(), stamp):
                self._insert_type(con, item)

    def _insert_type(self, con, item: dict[str, Any]) -> str:
        type_id = item.get("id") or new_id()
        con.execute(
            "insert or ignore into aircraft_type(id, icao, variant, name, manufacturer, role, "
            "cabin_config_json, pax_capacity, cargo_capacity_kg, mtow_kg, mzfw_kg, mlw_kg, oew_kg, "
            "fuel_capacity_kg, cruise_speed_kt, cruise_fl, fuel_burn_kg_h, min_runway_m, range_nm, "
            "engine_count, engine_type, wake_category, demand_profile, allow_scheduled, allow_charter, "
            "charter_rate_per_hour, fare_multiplier, lease_per_hour, created_at) "
            "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (type_id, item["icao"], item.get("variant", "STANDARD"), item.get("name"),
             item.get("manufacturer"), item.get("role", "AIRLINER"),
             json.dumps(item.get("cabin_config_json") or {}, ensure_ascii=False),
             int(item.get("pax_capacity") or 0), float(item.get("cargo_capacity_kg") or 0),
             float(item.get("mtow_kg") or 0), float(item.get("mzfw_kg") or 0),
             float(item.get("mlw_kg") or 0), float(item.get("oew_kg") or 0),
             float(item.get("fuel_capacity_kg") or 0), float(item.get("cruise_speed_kt") or 440),
             int(item.get("cruise_fl") or 350), float(item.get("fuel_burn_kg_h") or 2400),
             int(item.get("min_runway_m") or 1600), float(item.get("range_nm") or 3000),
             int(item.get("engine_count") or 2), item.get("engine_type"),
             item.get("wake_category"), item.get("demand_profile", "MASS"),
             1 if item.get("allow_scheduled", True) else 0,
             1 if item.get("allow_charter", True) else 0,
             float(item.get("charter_rate_per_hour") or 0), float(item.get("fare_multiplier") or 1),
             float(item.get("lease_per_hour") or 2000), item.get("created_at") or utcnow()))
        return type_id

    def _seed_profile(self) -> None:
        if self.profile() is not None:
            return
        economy = default_economy()
        stamp = utcnow()
        with self._tx() as con:
            con.execute(
                "insert into ops_profile(id, name, icao_code, callsign_prefix, flight_prefix, "
                "base_airport_icao, currency, balance, created_at, updated_at) "
                "values('local',?,?,?,?,?,?,?,?,?)",
                ("Aurora Virtual", "AUV", "AUV", "AOC", "ZBAA", economy["currency"],
                 economy["initial_balance"], stamp, stamp))
            con.execute(
                "insert into ledger_entry(id, flight_record_id, settlement_id, entry_type, amount, "
                "balance_after, currency, description, created_at) values(?,?,?,?,?,?,?,?,?)",
                (new_id(), None, None, "CAPITAL", float(economy["initial_balance"]),
                 float(economy["initial_balance"]), economy["currency"], "初始资金（本机档案）", stamp))
            for key, value in (("economy", economy), ("settlement_policy", default_policy())):
                con.execute(
                    "insert or replace into ops_config(key, value_json, version, updated_at) "
                    "values(?,?,0,?)", (key, json.dumps(value, ensure_ascii=False), stamp))
            con.execute(
                "insert into ops_config_version(id, version, status, note, snapshot_json, created_at) "
                "values(?,?,?,?,?,?)",
                (new_id(), 1, "PUBLISHED", "初始配置",
                 json.dumps({"economy": economy, "policy": default_policy()}, ensure_ascii=False), stamp))
            for key, value in (("economy", economy), ("settlement_policy", default_policy())):
                con.execute(
                    "insert or replace into ops_config_history(id, version, key, value_json, created_at) "
                    "values(?,?,?,?,?)",
                    (new_id(), 1, key, json.dumps(value, ensure_ascii=False), stamp))
            con.execute("update ops_config set version=1")
            self._audit(con, "PROFILE_SEED", "profile", "local", None, {"name": "Aurora Virtual"})

    def seed_demo(self) -> dict[str, Any]:
        """装一批演示数据：3 架 A320/B738/AT76 + 1 架 A343 公务机 + 航线/班期/航班实例。"""
        existing = self._one("select count(*) as n from aircraft")
        if existing and existing["n"]:
            return {"seeded": False, "aircraft": existing["n"]}
        types = {(t["icao"], t["variant"]): t for t in self.list_types()}
        picks = [
            ("A320", "STANDARD", "B-1671", "LEASE"),
            ("A320", "STANDARD", "B-1672", "LEASE"),
            ("B738", "STANDARD", "B-5721", "OWNED"),
            ("AT76", "STANDARD", "B-3301", "LEASE"),
            ("A343", "BIZJET", "B-7788", "OWNED"),
        ]
        stamp = utcnow()
        with self._tx() as con:
            for icao, variant, reg, acquisition in picks:
                t = types.get((icao, variant))
                if not t:
                    continue
                con.execute(
                    "insert into aircraft(id, type_id, registration, base_airport_icao, "
                    "current_airport_icao, status, fuel_kg, total_hours, total_cycles, condition_pct, "
                    "acquisition_type, purchase_price, lease_per_hour, acquired_at, created_at, updated_at) "
                    "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), t["id"], reg, "ZBAA", "ZBAA", "ACTIVE",
                     t["fuel_capacity_kg"], 0, 0, 100, acquisition,
                     t["mtow_kg"] * 120 if acquisition == "OWNED" else None,
                     t["lease_per_hour"], stamp, stamp, stamp))
        routes = [
            ("ZBAA", "ZSSS", 612, 130), ("ZSSS", "ZBAA", 612, 130),
            ("ZBAA", "ZSHC", 720, 145), ("ZSHC", "ZBAA", 720, 145),
            ("ZSSS", "ZSNJ", 145, 55), ("ZSNJ", "ZSSS", 145, 55),
            ("ZBAA", "ZLXY", 490, 105), ("ZLXY", "ZBAA", 490, 105),
            ("ZBAA", "ZPPP", 1090, 205), ("ZPPP", "ZBAA", 1090, 205),
            ("ZSSS", "ZHHH", 380, 85), ("ZHHH", "ZSSS", 380, 85),
        ]
        with self._tx() as con:
            for dep, arr, dist, block in routes:
                con.execute(
                    "insert or ignore into ops_route(id, dep_icao, arr_icao, distance_nm, block_minutes, "
                    "cruise_fl, enabled, created_at, updated_at) values(?,?,?,?,?,?,?,?,?)",
                    (new_id(), dep, arr, dist, block, 350, 1, stamp, stamp))
            route_rows = {(r["dep_icao"], r["arr_icao"]): r
                          for r in (dict(x) for x in con.execute("select * from ops_route"))}
            a320 = types.get(("A320", "STANDARD"))
            b738 = types.get(("B738", "STANDARD"))
            at76 = types.get(("AT76", "STANDARD"))
            prefix = (self.profile() or {}).get("flight_prefix") or "AOC"
            schedules = [
                ("101", "ZBAA", "ZSSS", "08:00", 127, a320, 45),
                ("102", "ZSSS", "ZBAA", "12:30", 127, a320, 45),
                ("201", "ZBAA", "ZSHC", "07:30", 127, b738, 45),
                ("202", "ZSHC", "ZBAA", "11:30", 127, b738, 45),
                ("301", "ZSSS", "ZSNJ", "15:30", 127, at76, 35),
                ("302", "ZSNJ", "ZSSS", "17:10", 127, at76, 35),
                ("401", "ZBAA", "ZLXY", "13:00", 127, a320, 45),
                ("501", "ZBAA", "ZPPP", "09:30", 127, a320, 60),
            ]
            for digits, dep, arr, hhmm, days, ac_type, turn in schedules:
                route = route_rows.get((dep, arr))
                if not route or not ac_type:
                    continue
                number = f"{prefix}{digits}"
                con.execute(
                    "insert into schedule_template(id, route_id, flight_number, dep_local_time, "
                    "days_of_week, aircraft_type_id, turnaround_min, enabled, created_at, updated_at) "
                    "values(?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), route["id"], number, hhmm, days, ac_type["id"], turn, 1, stamp, stamp))
            self._audit(con, "SEED_DEMO", "ops", None, None, {"aircraft": len(picks), "routes": len(routes)})
        generated = self.generate_instances(days=7)
        return {"seeded": True, "aircraft": len(picks), "instances": generated}

    # ------------------------------------------------------------------ 档案
    def profile(self) -> dict[str, Any] | None:
        row = self._one("select * from ops_profile where id='local'")
        if not row:
            return None
        row["flight_prefix"] = (row.get("flight_prefix") or "").strip().upper() or "AOC"
        row["callsign_prefix"] = (row.get("callsign_prefix") or "").strip().upper() or "AUV"
        row["no_show_count"] = int(self._meta_get(NO_SHOW_KEY, 0) or 0)
        return row

    def update_profile(self, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {k: v for k, v in (patch or {}).items()
                   if k in ("name", "icao_code", "callsign_prefix", "flight_prefix",
                            "base_airport_icao", "currency")}
        for key in ("callsign_prefix", "flight_prefix"):
            if key in allowed:
                cleaned = _clean_prefix(allowed[key])
                # 留空视为不修改，避免把航班号改成纯数字
                if cleaned:
                    allowed[key] = cleaned
                else:
                    allowed.pop(key, None)
        if not allowed:
            return self.profile() or {}
        before = self.profile() or {}
        with self._tx() as con:
            con.execute(
                f"update ops_profile set {','.join(f'{k}=?' for k in allowed)}, updated_at=? where id='local'",
                (*allowed.values(), utcnow()))
            if "flight_prefix" in allowed and allowed["flight_prefix"] != (before.get("flight_prefix") or ""):
                self._renumber_flights(allowed["flight_prefix"], con)
            self._audit(con, "PROFILE_UPDATE", "profile", "local", before, allowed)
        return self.profile() or {}

    def _renumber_flights(self, prefix: str, con) -> int:
        """改航班号前缀：同步改写班期与未开始的航班实例（只保留数字部分）。"""
        changed = 0
        for row in con.execute("select id, flight_number from schedule_template").fetchall():
            number = _with_prefix(row["flight_number"], prefix)
            if number != row["flight_number"]:
                con.execute("update schedule_template set flight_number=?, updated_at=? where id=?",
                            (number, utcnow(), row["id"]))
                changed += 1
        for row in con.execute("select id, flight_number from flight_instance "
                               "where status in ('SCHEDULED','ASSIGNED')").fetchall():
            number = _with_prefix(row["flight_number"], prefix)
            if number != row["flight_number"]:
                # 与既有航班号冲突时跳过（update or ignore 避免整笔事务失败）
                con.execute("update or ignore flight_instance set flight_number=?, updated_at=? where id=?",
                            (number, utcnow(), row["id"]))
                changed += 1
        return changed

    # ------------------------------------------------------------------ 机型/机队
    def list_types(self) -> list[dict[str, Any]]:
        rows = self._rows("select * from aircraft_type order by icao, variant")
        for row in rows:
            row["cabin_config_json"] = _json_load(row.get("cabin_config_json"), {})
            row["allow_scheduled"] = bool(row.get("allow_scheduled"))
            row["allow_charter"] = bool(row.get("allow_charter"))
        return rows

    def get_type(self, type_id: str) -> dict[str, Any] | None:
        for item in self.list_types():
            if item["id"] == type_id:
                return item
        return None

    def list_fleet(self) -> list[dict[str, Any]]:
        self._expire_locks()
        rows = self._rows(
            "select a.*, t.icao as type_icao, t.variant as type_variant, t.name as type_name, "
            "t.role as type_role, t.pax_capacity, t.range_nm, t.min_runway_m, t.mtow_kg "
            "from aircraft a left join aircraft_type t on t.id=a.type_id order by a.registration")
        locks = {r["aircraft_id"]: r for r in self._rows(
            "select * from aircraft_lock where status in ('HELD','IN_FLIGHT')")}
        for row in rows:
            lock = locks.get(row["id"])
            row["lock"] = lock
            row["locked"] = bool(lock)
        return rows

    def get_aircraft(self, aircraft_id: str) -> dict[str, Any] | None:
        for row in self.list_fleet():
            if row["id"] == aircraft_id:
                return row
        return None

    def add_aircraft(self, data: dict[str, Any]) -> dict[str, Any]:
        registration = (data.get("registration") or "").strip().upper()
        if not registration:
            raise OpsError("VALIDATION", "注册号必填")
        type_id = data.get("type_id")
        type_row = self.get_type(type_id) if type_id else None
        if type_row is None:
            raise OpsError("VALIDATION", "机型不存在")
        base = (data.get("base_airport_icao") or (self.profile() or {}).get("base_airport_icao") or "").upper()
        if not base:
            raise OpsError("VALIDATION", "基地机场必填")
        if self._one("select id from aircraft where registration=?", (registration,)):
            raise OpsError("DUPLICATE_REGISTRATION", f"注册号 {registration} 已存在")
        acquisition = (data.get("acquisition_type") or "LEASE").upper()
        if acquisition not in ("LEASE", "OWNED"):
            raise OpsError("VALIDATION", "引进方式只能是 LEASE 或 OWNED")
        stamp = utcnow()
        aircraft_id = new_id()
        lease = data.get("lease_per_hour")
        if lease is None:
            lease = type_row.get("lease_per_hour") if acquisition == "LEASE" else 0
        with self._tx() as con:
            con.execute(
                "insert into aircraft(id, type_id, registration, tail_number, livery, base_airport_icao, "
                "current_airport_icao, status, fuel_kg, total_hours, total_cycles, condition_pct, "
                "acquisition_type, purchase_price, lease_per_hour, acquired_at, created_at, updated_at) "
                "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (aircraft_id, type_id, registration, data.get("tail_number"),
                 data.get("livery"), base, (data.get("current_airport_icao") or base).upper(),
                 "ACTIVE", data.get("fuel_kg", type_row.get("fuel_capacity_kg")), 0, 0, 100,
                 acquisition, data.get("purchase_price") or (type_row["mtow_kg"] * 120 if acquisition == "OWNED" else None),
                 lease, stamp, stamp, stamp))
            self._audit(con, "AIRCRAFT_ADD", "aircraft", aircraft_id, None,
                        {"registration": registration, "type": type_row["icao"], "base": base})
        return self.get_aircraft(aircraft_id) or {}

    def update_aircraft(self, aircraft_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        before = self.get_aircraft(aircraft_id)
        if not before:
            raise OpsError("NOT_FOUND", "飞机不存在")
        allowed = {k: v for k, v in (patch or {}).items() if k in (
            "base_airport_icao", "current_airport_icao", "status", "fuel_kg", "livery",
            "tail_number", "lease_per_hour", "condition_pct", "version")}
        if not allowed:
            return before
        if "status" in allowed:
            status = str(allowed["status"]).upper()
            if status not in ("ACTIVE", "MAINTENANCE", "RETIRED"):
                raise OpsError("VALIDATION", "只允许手工改成 ACTIVE/MAINTENANCE/RETIRED")
            if before.get("locked"):
                raise OpsError("AIRCRAFT_LOCKED", "飞机已被班表/自由飞占用，先取消任务")
            allowed["status"] = status
        expected = allowed.pop("version", None)
        if expected is not None and int(expected) != int(before.get("version") or 1):
            raise OpsError("VERSION_CONFLICT", "飞机档案已被修改，请刷新后重试")
        allowed["updated_at"] = utcnow()
        allowed["version"] = int(before.get("version") or 1) + 1
        with self._tx() as con:
            con.execute(
                f"update aircraft set {','.join(f'{k}=?' for k in allowed)} where id=?",
                (*allowed.values(), aircraft_id))
            self._audit(con, "AIRCRAFT_UPDATE", "aircraft", aircraft_id, before, allowed)
        return self.get_aircraft(aircraft_id) or {}

    def release_aircraft(self, aircraft_id: str, reason: str | None = None) -> dict[str, Any]:
        aircraft = self.get_aircraft(aircraft_id)
        if not aircraft:
            raise OpsError("NOT_FOUND", "飞机不存在")
        stamp = utcnow()
        with self._tx() as con:
            con.execute("update aircraft_lock set status='RELEASED', released_at=? "
                        "where aircraft_id=? and status in ('HELD','IN_FLIGHT')", (stamp, aircraft_id))
            con.execute("update aircraft set status='ACTIVE', updated_at=?, version=version+1 where id=?",
                        (stamp, aircraft_id))
            for roster in self._rows("select * from roster where aircraft_id=? and status in "
                                     "('LOCKED','IN_PROGRESS')", (aircraft_id,)):
                con.execute("update roster set status='CANCELLED', updated_at=? where id=?",
                            (stamp, roster["id"]))
                con.execute("update roster_leg set status='CANCELLED', updated_at=? "
                            "where roster_id=? and status in ('PLANNED','IN_PROGRESS')",
                            (stamp, roster["id"]))
            con.execute("update free_flight set status='CANCELLED', updated_at=? "
                        "where aircraft_id=? and status in ('LOCKED','IN_FLIGHT')", (stamp, aircraft_id))
            self._audit(con, "AIRCRAFT_RELEASE", "aircraft", aircraft_id, {"locked": True}, None, reason)
        return self.get_aircraft(aircraft_id) or {}

    # ------------------------------------------------------------------ 航线/班期
    def list_routes(self) -> list[dict[str, Any]]:
        rows = self._rows("select * from ops_route order by dep_icao, arr_icao")
        for row in rows:
            row["enabled"] = bool(row.get("enabled"))
        return rows

    def _route_payload(self, data: dict[str, Any], nav_meta: bool = True) -> dict[str, Any]:
        dep = (data.get("dep_icao") or "").strip().upper()
        arr = (data.get("arr_icao") or "").strip().upper()
        if len(dep) != 4 or len(arr) != 4 or dep == arr:
            raise OpsError("VALIDATION", "起降机场必须是两个不同的 4 字码")
        distance = data.get("distance_nm")
        if not distance and nav_meta:
            distance = eco.gcd_nm(eco.airport_meta(self.nav, dep), eco.airport_meta(self.nav, arr)) or None
        if not distance:
            raise OpsError("VALIDATION", "缺少距离且 navdata 不可用，无法估算")
        block = data.get("block_minutes")
        if not block:
            block = int(round(float(distance) / 440.0 * 60 + 25))
        return {
            "dep_icao": dep, "arr_icao": arr, "distance_nm": round(float(distance), 1),
            "block_minutes": int(block), "min_aircraft_category": data.get("min_aircraft_category"),
            "default_route_string": data.get("default_route_string"),
            "default_sid": data.get("default_sid"), "default_star": data.get("default_star"),
            "cruise_fl": int(data.get("cruise_fl") or 350),
            "enabled": 1 if data.get("enabled", True) else 0,
        }

    def add_route(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = self._route_payload(data)
        if self._one("select id from ops_route where dep_icao=? and arr_icao=?",
                     (payload["dep_icao"], payload["arr_icao"])):
            raise OpsError("DUPLICATE_ROUTE", "该起降对已存在航线")
        stamp = utcnow()
        route_id = new_id()
        with self._tx() as con:
            con.execute(
                "insert into ops_route(id, dep_icao, arr_icao, distance_nm, block_minutes, "
                "min_aircraft_category, default_route_string, default_sid, default_star, cruise_fl, "
                "enabled, created_at, updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (route_id, payload["dep_icao"], payload["arr_icao"], payload["distance_nm"],
                 payload["block_minutes"], payload["min_aircraft_category"],
                 payload["default_route_string"], payload["default_sid"], payload["default_star"],
                 payload["cruise_fl"], payload["enabled"], stamp, stamp))
            self._audit(con, "ROUTE_ADD", "route", route_id, None, payload)
        return self._one("select * from ops_route where id=?", (route_id,)) or {}

    def update_route(self, route_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        before = self._one("select * from ops_route where id=?", (route_id,))
        if not before:
            raise OpsError("NOT_FOUND", "航线不存在")
        payload = self._route_payload({**before, **patch})
        with self._tx() as con:
            con.execute(
                "update ops_route set dep_icao=?, arr_icao=?, distance_nm=?, block_minutes=?, "
                "min_aircraft_category=?, default_route_string=?, default_sid=?, default_star=?, "
                "cruise_fl=?, enabled=?, updated_at=? where id=?",
                (payload["dep_icao"], payload["arr_icao"], payload["distance_nm"],
                 payload["block_minutes"], payload["min_aircraft_category"],
                 payload["default_route_string"], payload["default_sid"], payload["default_star"],
                 payload["cruise_fl"], payload["enabled"], utcnow(), route_id))
            self._audit(con, "ROUTE_UPDATE", "route", route_id, before, payload)
        return self._one("select * from ops_route where id=?", (route_id,)) or {}

    def delete_route(self, route_id: str) -> bool:
        before = self._one("select * from ops_route where id=?", (route_id,))
        if not before:
            return False
        with self._tx() as con:
            con.execute("delete from ops_route where id=?", (route_id,))
            self._audit(con, "ROUTE_DELETE", "route", route_id, before, None)
        return True

    def list_schedules(self) -> list[dict[str, Any]]:
        rows = self._rows(
            "select s.*, r.dep_icao, r.arr_icao, r.distance_nm, r.block_minutes, "
            "t.icao as type_icao, t.variant as type_variant "
            "from schedule_template s left join ops_route r on r.id=s.route_id "
            "left join aircraft_type t on t.id=s.aircraft_type_id "
            "order by s.flight_number")
        for row in rows:
            row["enabled"] = bool(row.get("enabled"))
        return rows

    def add_schedule(self, data: dict[str, Any]) -> dict[str, Any]:
        route = self._one("select * from ops_route where id=?", (data.get("route_id"),))
        if not route:
            raise OpsError("VALIDATION", "航线不存在")
        number = (data.get("flight_number") or "").strip().upper()
        if not number:
            raise OpsError("VALIDATION", "航班号必填")
        hhmm = (data.get("dep_local_time") or "").strip()
        if not _valid_hhmm(hhmm):
            raise OpsError("VALIDATION", "起飞时刻格式应为 HH:MM")
        days = int(data.get("days_of_week", 127))
        if days < 1 or days > 127:
            raise OpsError("VALIDATION", "days_of_week 必须是 1–127 的位图")
        type_id = data.get("aircraft_type_id")
        if type_id and not self.get_type(type_id):
            raise OpsError("VALIDATION", "机型不存在")
        stamp = utcnow()
        schedule_id = new_id()
        with self._tx() as con:
            con.execute(
                "insert into schedule_template(id, route_id, flight_number, dep_local_time, "
                "days_of_week, valid_from, valid_to, aircraft_type_id, turnaround_min, enabled, "
                "created_at, updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                (schedule_id, route["id"], number, hhmm, days, data.get("valid_from"),
                 data.get("valid_to"), type_id, int(data.get("turnaround_min") or 45),
                 1 if data.get("enabled", True) else 0, stamp, stamp))
            self._audit(con, "SCHEDULE_ADD", "schedule", schedule_id, None,
                        {"flight_number": number, "route": [route["dep_icao"], route["arr_icao"]]})
        return next((s for s in self.list_schedules() if s["id"] == schedule_id), {})

    def update_schedule(self, schedule_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        before = self._one("select * from schedule_template where id=?", (schedule_id,))
        if not before:
            raise OpsError("NOT_FOUND", "班期不存在")
        merged = {**before, **patch}
        if not _valid_hhmm(str(merged.get("dep_local_time") or "")):
            raise OpsError("VALIDATION", "起飞时刻格式应为 HH:MM")
        days = int(merged.get("days_of_week") or 0)
        if days < 1 or days > 127:
            raise OpsError("VALIDATION", "days_of_week 必须是 1–127 的位图")
        with self._tx() as con:
            con.execute(
                "update schedule_template set route_id=?, flight_number=?, dep_local_time=?, "
                "days_of_week=?, valid_from=?, valid_to=?, aircraft_type_id=?, turnaround_min=?, "
                "enabled=?, updated_at=? where id=?",
                (merged.get("route_id"), merged.get("flight_number"), merged.get("dep_local_time"),
                 days, merged.get("valid_from"), merged.get("valid_to"), merged.get("aircraft_type_id"),
                 int(merged.get("turnaround_min") or 45), 1 if merged.get("enabled") else 0,
                 utcnow(), schedule_id))
            self._audit(con, "SCHEDULE_UPDATE", "schedule", schedule_id, before, patch)
        return next((s for s in self.list_schedules() if s["id"] == schedule_id), {})

    def delete_schedule(self, schedule_id: str) -> bool:
        before = self._one("select * from schedule_template where id=?", (schedule_id,))
        if not before:
            return False
        with self._tx() as con:
            con.execute("delete from schedule_template where id=?", (schedule_id,))
            self._audit(con, "SCHEDULE_DELETE", "schedule", schedule_id, before, None)
        return True

    def generate_instances(self, days: int = 7) -> int:
        days = max(1, min(31, int(days)))
        schedules = [s for s in self.list_schedules() if s["enabled"] and s.get("route_id")]
        if not schedules:
            return 0
        created = 0
        now = _now()
        with self._tx() as con:
            for schedule in schedules:
                base_local = eco.local_now(schedule["dep_icao"], now)
                for offset in range(days):
                    local_date = base_local + timedelta(days=offset)
                    weekday = local_date.weekday()
                    if not (int(schedule["days_of_week"]) >> weekday) & 1:
                        continue
                    if schedule.get("valid_from") and local_date.date().isoformat() < schedule["valid_from"]:
                        continue
                    if schedule.get("valid_to") and local_date.date().isoformat() > schedule["valid_to"]:
                        continue
                    dep_utc = eco.local_to_utc(local_date, schedule["dep_local_time"], schedule["dep_icao"])
                    if eco.parse_utc(dep_utc) < now - timedelta(minutes=5):
                        continue
                    block = int(schedule.get("block_minutes") or 90)
                    arr_utc = _iso(eco.parse_utc(dep_utc) + timedelta(minutes=block))
                    cur = con.execute(
                        "insert or ignore into flight_instance(id, schedule_id, route_id, flight_number, "
                        "dep_icao, arr_icao, scheduled_dep_utc, scheduled_arr_utc, aircraft_type_id, "
                        "mission_type, status, created_at, updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (new_id(), schedule["id"], schedule["route_id"], schedule["flight_number"],
                         schedule["dep_icao"], schedule["arr_icao"], dep_utc, arr_utc,
                         schedule.get("aircraft_type_id"), "SCHEDULED", "SCHEDULED",
                         utcnow(), utcnow()))
                    created += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            if created:
                self._audit(con, "INSTANCE_GENERATE", "flight_instance", None, None, {"created": created})
        return created

    def list_instances(self, *, status: str | None = None, dep: str | None = None,
                       arr: str | None = None, days: int = 7, limit: int = 500) -> list[dict[str, Any]]:
        where = ["scheduled_dep_utc >= ?", "scheduled_dep_utc <= ?"]
        args: list[Any] = [utcnow(), _iso(_now() + timedelta(days=max(1, days)))]
        if status:
            where.append("status=?")
            args.append(status.upper())
        if dep:
            where.append("dep_icao=?")
            args.append(dep.upper())
        if arr:
            where.append("arr_icao=?")
            args.append(arr.upper())
        rows = self._rows(
            "select * from flight_instance where " + " and ".join(where) +
            " order by scheduled_dep_utc limit ?", (*args, limit))
        return rows

    def cancel_instance(self, instance_id: str) -> dict[str, Any]:
        row = self._one("select * from flight_instance where id=?", (instance_id,))
        if not row:
            raise OpsError("NOT_FOUND", "航班实例不存在")
        if row["status"] not in ("SCHEDULED", "ASSIGNED"):
            raise OpsError("INVALID_STATE", "只有未开始的航班可以取消")
        with self._tx() as con:
            con.execute("update flight_instance set status='CANCELLED', updated_at=? where id=?",
                        (utcnow(), instance_id))
            self._audit(con, "INSTANCE_CANCEL", "flight_instance", instance_id, row["status"], "CANCELLED")
        return self._one("select * from flight_instance where id=?", (instance_id,)) or {}

    # ------------------------------------------------------------------ 抽班
    def _constraints(self, req: dict[str, Any] | None) -> dict[str, Any]:
        req = req or {}
        out: dict[str, Any] = {}
        for key, (lo, hi, default) in CONSTRAINT_LIMITS.items():
            raw = req.get(key)
            value = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else (
                int(raw) if isinstance(raw, str) and raw.isdigit() else default)
            if value < lo or value > hi:
                raise OpsError("PARAM_OUT_OF_RANGE", f"{key} 超出范围 {lo}–{hi}", {"key": key})
            out[key] = value
        if out["max_turnaround_min"] < out["min_turnaround_min"]:
            raise OpsError("PARAM_OUT_OF_RANGE", "最大过站不能小于最小过站")
        base = (req.get("base_airport") or "").strip().upper() or None
        out["base_airport"] = base
        out["aircraft_type_id"] = req.get("aircraft_type_id") or None
        out["registration"] = (req.get("registration") or "").strip().upper() or None
        out["prefer_new_airports"] = bool(req.get("prefer_new_airports", True))
        return out

    def _available_instances(self, start: str, end: str) -> list[dict[str, Any]]:
        rows = self._rows(
            "select * from flight_instance where status='SCHEDULED' "
            "and scheduled_dep_utc >= ? and scheduled_dep_utc <= ? order by scheduled_dep_utc",
            (start, end))
        return rows

    def _type_map(self) -> dict[str, dict[str, Any]]:
        return {t["id"]: t for t in self.list_types()}

    def _visited_airports(self) -> set[str]:
        with self._tx() as con:
            rows = con.execute("select distinct dep_icao, arr_icao from flight_record "
                               "where status in ('COMPLETED','DIVERTED')").fetchall()
        out: set[str] = set()
        for row in rows:
            for icao in (row[0], row[1]):
                if icao:
                    out.add(str(icao).upper())
        return out

    def draw(self, req: dict[str, Any] | None) -> dict[str, Any]:
        constraints = self._constraints(req)
        self._expire_locks()
        types = self._type_map()
        now = _now()
        window_end = now + timedelta(hours=constraints["window_hours"])
        aircraft = [a for a in self.list_fleet()
                    if a["status"] == "ACTIVE" and not a.get("locked")]
        if constraints["base_airport"]:
            aircraft = [a for a in aircraft if (a.get("current_airport_icao") or "").upper() == constraints["base_airport"]]
        if constraints["aircraft_type_id"]:
            aircraft = [a for a in aircraft if a["type_id"] == constraints["aircraft_type_id"]]
        if constraints["registration"]:
            aircraft = [a for a in aircraft if (a.get("registration") or "").upper() == constraints["registration"]]
        aircraft = [a for a in aircraft
                    if (types.get(a["type_id"]) or {}).get("allow_scheduled", True)]

        instances = self._available_instances(
            _iso(now - timedelta(minutes=15)), _iso(window_end))
        instances = [i for i in instances if (i.get("mission_type") or "SCHEDULED") != "CHARTER"]
        by_dep: dict[str, list[dict[str, Any]]] = {}
        for item in instances:
            by_dep.setdefault(item["dep_icao"].upper(), []).append(item)
        for items in by_dep.values():
            items.sort(key=lambda x: x["scheduled_dep_utc"])

        visited = self._visited_airports()
        candidates: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for ac in aircraft:
            ac_type = types.get(ac["type_id"]) or {}
            chains = self._build_chains(ac, ac_type, by_dep, constraints, now, window_end)
            for chain in chains[:24]:
                # 同机同航线形状只保留一个（避免三个候选都是同一航班的不同日期）
                shape = (ac["id"], tuple((leg["dep_icao"], leg["arr_icao"]) for leg in chain))
                if shape in seen:
                    continue
                seen.add(shape)
                candidate = self._candidate(ac, ac_type, chain, constraints, visited, types)
                if candidate:
                    candidates.append(candidate)
        candidates.sort(key=lambda c: c["score"], reverse=True)
        top = candidates[:3]
        token = self._sign({
            "aircraft_id": None,
            "candidates": [{"aircraft_id": c["aircraft"]["id"],
                            "instance_ids": [leg["flight_instance_id"] for leg in c["legs"]]} for c in top],
            "constraints": constraints,
            "exp": _iso(now + timedelta(seconds=CANDIDATE_TTL_SECONDS)),
        })
        for item in top:
            item["candidate_token"] = token
        return {
            "candidates": top,
            "constraints": constraints,
            "expires_at": _iso(now + timedelta(seconds=CANDIDATE_TTL_SECONDS)),
            "considered": len(candidates),
        }

    def _build_chains(self, aircraft: dict[str, Any], ac_type: dict[str, Any],
                      by_dep: dict[str, list[dict[str, Any]]], constraints: dict[str, Any],
                      now: datetime, window_end: datetime) -> list[list[dict[str, Any]]]:
        start = (aircraft.get("current_airport_icao") or "").upper()
        min_turn = timedelta(minutes=constraints["min_turnaround_min"])
        max_turn = timedelta(minutes=constraints["max_turnaround_min"])
        max_block = constraints["max_block_minutes"]
        max_legs = constraints["max_legs"]
        results: list[list[dict[str, Any]]] = []

        def walk(position: str, earliest: datetime, latest: datetime | None,
                 chain: list[dict[str, Any]], block_total: int) -> None:
            if chain:
                results.append(list(chain))
            if len(chain) >= max_legs or len(results) > 200:
                return
            for inst in by_dep.get(position, []):
                dep_dt = eco.parse_utc(inst["scheduled_dep_utc"])
                if dep_dt < earliest or dep_dt > window_end:
                    continue
                if latest is not None and dep_dt > latest:
                    continue
                type_id = inst.get("aircraft_type_id")
                if type_id and type_id != aircraft["type_id"]:
                    continue
                block = self._instance_block(inst, ac_type)
                if block_total + block > max_block:
                    continue
                arr_dt = eco.parse_utc(inst["scheduled_arr_utc"]) if inst.get("scheduled_arr_utc") else (
                    dep_dt + timedelta(minutes=block))
                chain.append(inst)
                walk(inst["arr_icao"].upper(), arr_dt + min_turn, arr_dt + max_turn,
                     chain, block_total + block)
                chain.pop()

        walk(start, now - timedelta(minutes=15), None, [], 0)
        # 优先更长的链（利用率）与更早的时间
        results.sort(key=lambda c: (-len(c), c[0]["scheduled_dep_utc"]))
        return results

    def _instance_block(self, inst: dict[str, Any], ac_type: dict[str, Any]) -> int:
        dep = eco.parse_utc(inst["scheduled_dep_utc"])
        arr = eco.parse_utc(inst["scheduled_arr_utc"])
        minutes = int(round((arr - dep).total_seconds() / 60))
        if minutes > 0:
            return minutes
        route = self._one("select block_minutes from ops_route where id=?", (inst.get("route_id"),))
        return int((route or {}).get("block_minutes") or 90)

    def _candidate(self, aircraft: dict[str, Any], ac_type: dict[str, Any],
                   chain: list[dict[str, Any]], constraints: dict[str, Any],
                   visited: set[str], types: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        if not chain:
            return None
        legs = []
        total_block = 0
        total_distance = 0.0
        est_revenue = 0.0
        est_cost = 0.0
        airports: set[str] = set()
        block_minutes: list[int] = []
        params = self.economy_params()
        for index, inst in enumerate(chain):
            block = self._instance_block(inst, ac_type)
            route = self._one("select * from ops_route where id=?", (inst.get("route_id"),)) or {}
            distance = float(route.get("distance_nm") or 0)
            if not distance:
                distance = eco.gcd_nm(eco.airport_meta(self.nav, inst["dep_icao"]),
                                      eco.airport_meta(self.nav, inst["arr_icao"]))
            dep_meta = eco.airport_meta(self.nav, inst["dep_icao"])
            arr_meta = eco.airport_meta(self.nav, inst["arr_icao"])
            sheet = eco.generate_load_sheet(
                dep=inst["dep_icao"], arr=inst["arr_icao"], distance_nm=distance,
                block_minutes=block, aircraft_type=ac_type, params=params,
                seed=f"candidate-{aircraft['id']}-{inst['id']}-{index}",
                dep_time_utc=inst["scheduled_dep_utc"], dep_meta=dep_meta, arr_meta=arr_meta,
                repeat_index=0)
            est_revenue += sheet["estimated_revenue"]
            est_cost += sheet["estimated_cost"]
            total_block += block
            total_distance += distance
            block_minutes.append(block)
            airports.update((inst["dep_icao"].upper(), inst["arr_icao"].upper()))
            legs.append({
                "flight_instance_id": inst["id"], "flight_number": inst["flight_number"],
                "callsign": self._callsign(inst["flight_number"]),
                "dep": inst["dep_icao"], "arr": inst["arr_icao"],
                "scheduled_dep_utc": inst["scheduled_dep_utc"],
                "scheduled_arr_utc": inst["scheduled_arr_utc"], "block_minutes": block,
                "distance_nm": round(distance, 1),
                "estimated_revenue": sheet["estimated_revenue"],
            })
        est_profit = est_revenue - est_cost
        new_airports = len({a for a in airports if a not in visited})
        max_block = constraints["max_block_minutes"]
        utilization = min(1.0, total_block / max_block) if max_block else 0
        novelty = min(1.0, new_airports / max(1, len(chain)))
        profit_norm = max(0.0, min(1.0, est_profit / 50000.0))
        balance = 1.0
        if len(block_minutes) > 1 and statistics.mean(block_minutes) > 0:
            balance = max(0.0, 1.0 - statistics.pstdev(block_minutes) / statistics.mean(block_minutes))
        rng = eco.seeded_rng(f"{aircraft['id']}|{chain[0]['id']}", "score")
        random_part = rng.random()
        weights = (0.35, 0.40, 0.10, 0.15, 0.05) if constraints["prefer_new_airports"] else (
            0.35, 0.25, 0.20, 0.15, 0.05)
        total_weight = sum(weights)
        score = (weights[0] * utilization + weights[1] * novelty + weights[2] * profit_norm
                 + weights[3] * balance + weights[4] * random_part) / total_weight
        reasons = [f"机型匹配 {ac_type.get('icao', '')}"]
        if new_airports:
            reasons.append(f"包含 {new_airports} 个未飞机场")
        if len(chain) > 1:
            reasons.append(f"{len(chain)} 段 · 总过站约 {constraints['min_turnaround_min']}min+")
        reasons.append(f"预计利润 ${est_profit:,.0f}")
        return {
            "aircraft": {
                "id": aircraft["id"], "registration": aircraft["registration"],
                "type_id": aircraft["type_id"], "type": ac_type.get("icao"),
                "variant": ac_type.get("variant"), "current_airport_icao": aircraft.get("current_airport_icao"),
            },
            "legs": legs,
            "total_block_minutes": total_block,
            "total_distance_nm": round(total_distance, 1),
            "estimated_revenue": round(est_revenue, 2),
            "estimated_cost": round(est_cost, 2),
            "estimated_profit": round(est_profit, 2),
            "score": round(score, 4),
            "reasons": reasons,
        }

    def _sign(self, payload: dict[str, Any]) -> str:
        body = base64.urlsafe_b64encode(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).decode().rstrip("=")
        sig = hmac.new(self._secret().encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{body}.{sig}"

    def _verify(self, token: str) -> dict[str, Any]:
        try:
            body, sig = (token or "").split(".", 1)
        except ValueError as exc:
            raise OpsError("INVALID_TOKEN", "候选已失效，请重新抽班") from exc
        expect = hmac.new(self._secret().encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expect):
            raise OpsError("INVALID_TOKEN", "候选已失效，请重新抽班")
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if eco.parse_utc(payload.get("exp")) < _now():
            raise OpsError("CANDIDATE_EXPIRED", "候选已过期，请重新抽班")
        return payload

    def confirm_roster(self, candidate_token: str, candidate_index: int = 0) -> dict[str, Any]:
        payload = self._verify(candidate_token)
        candidates = payload.get("candidates") or []
        if not candidates:
            raise OpsError("INVALID_TOKEN", "候选为空，请重新抽班")
        index = max(0, min(len(candidates) - 1, int(candidate_index or 0)))
        candidate = candidates[index]
        constraints = payload.get("constraints") or {}
        aircraft_id = candidate["aircraft_id"]
        aircraft = self.get_aircraft(aircraft_id)
        if not aircraft:
            raise OpsError("NOT_FOUND", "飞机不存在")
        if aircraft.get("locked") or aircraft["status"] != "ACTIVE":
            raise OpsError("AIRCRAFT_LOCKED", "飞机已被其他任务占用", {"aircraft_id": aircraft_id})
        instance_ids = candidate["instance_ids"]
        instances = []
        for instance_id in instance_ids:
            inst = self._one("select * from flight_instance where id=?", (instance_id,))
            if not inst or inst["status"] != "SCHEDULED":
                raise OpsError("INSTANCE_UNAVAILABLE", "航班实例已被占用或取消，请重新抽班")
            instances.append(inst)
        now = _now()
        window_end = now + timedelta(hours=int(constraints.get("window_hours") or 24))
        roster_id = new_id()
        stamp = utcnow()
        with self._tx() as con:
            con.execute(
                "insert into roster(id, kind, aircraft_id, status, base_airport_icao, window_start_utc, "
                "window_end_utc, constraints_json, redraw_count, locked_at, expires_at, version, "
                "created_at, updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (roster_id, "ROSTER", aircraft_id, "LOCKED",
                 constraints.get("base_airport") or aircraft.get("current_airport_icao"),
                 _iso(now), _iso(window_end), json.dumps(constraints, ensure_ascii=False),
                 0, stamp, _iso(window_end), 1, stamp, stamp))
            for index, inst in enumerate(instances, start=1):
                con.execute(
                    "insert into roster_leg(id, roster_id, sequence, flight_instance_id, status, "
                    "planned_dep_utc, planned_arr_utc, dep_icao, arr_icao, created_at, updated_at) "
                    "values(?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), roster_id, index, inst["id"], "PLANNED",
                     inst["scheduled_dep_utc"], inst["scheduled_arr_utc"],
                     inst["dep_icao"], inst["arr_icao"], stamp, stamp))
                con.execute("update flight_instance set status='ASSIGNED', assigned_aircraft_id=?, "
                            "roster_id=?, updated_at=? where id=?",
                            (aircraft_id, roster_id, stamp, inst["id"]))
            con.execute("update aircraft set status='HELD', updated_at=?, version=version+1 where id=?",
                        (stamp, aircraft_id))
            con.execute(
                "insert into aircraft_lock(id, aircraft_id, roster_id, lock_type, status, acquired_at, "
                "expires_at, heartbeat_at) values(?,?,?,?,?,?,?,?)",
                (new_id(), aircraft_id, roster_id, "ROSTER", "HELD", stamp, _iso(window_end), stamp))
            self._audit(con, "ROSTER_CONFIRM", "roster", roster_id, None,
                        {"aircraft": aircraft["registration"], "legs": len(instances)})
        return self.roster(roster_id) or {}

    def roster(self, roster_id: str) -> dict[str, Any] | None:
        row = self._one("select * from roster where id=?", (roster_id,))
        if not row:
            return None
        row["constraints"] = _json_load(row.pop("constraints_json", None), {})
        legs = self._rows(
            "select l.*, i.flight_number as flight_number, i.mission_type as mission_type "
            "from roster_leg l left join flight_instance i on i.id=l.flight_instance_id "
            "where l.roster_id=? order by l.sequence", (roster_id,))
        for leg in legs:
            leg["callsign"] = self._callsign(leg.get("flight_number")) if leg.get("flight_number") else ""
        row["legs"] = legs
        aircraft = self.get_aircraft(row["aircraft_id"]) or {}
        row["aircraft"] = {
            "id": aircraft.get("id"), "registration": aircraft.get("registration"),
            "type": aircraft.get("type_icao"), "variant": aircraft.get("type_variant"),
            "current_airport_icao": aircraft.get("current_airport_icao"),
            "status": aircraft.get("status"),
        }
        row["settlements"] = [r for r in self._rows(
            "select id, flight_record_id, profit, revenue_total, cost_total, status, policy_action "
            "from settlement where roster_id=?", (roster_id,))]
        return row

    def current_roster(self) -> dict[str, Any] | None:
        self._expire_locks()
        row = self._one("select * from roster where status in ('LOCKED','IN_PROGRESS') "
                        "order by created_at desc limit 1")
        return self.roster(row["id"]) if row else None

    def list_rosters(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._rows("select * from roster order by created_at desc limit ?", (limit,))
        return [self.roster(r["id"]) or r for r in rows]

    def redraw(self, roster_id: str) -> dict[str, Any]:
        roster = self.roster(roster_id)
        if not roster:
            raise OpsError("NOT_FOUND", "班表不存在")
        if roster["status"] != "LOCKED" or any(leg["status"] != "PLANNED" for leg in roster["legs"]):
            raise OpsError("INVALID_STATE", "首段已开始，不能重抽")
        constraints = dict(roster.get("constraints") or {})
        self._cancel_roster(roster_id, reason="重抽", redraw=True)
        result = self.draw(constraints)
        return result

    def cancel_roster(self, roster_id: str, reason: str | None = None) -> dict[str, Any]:
        roster = self.roster(roster_id)
        if not roster:
            raise OpsError("NOT_FOUND", "班表不存在")
        if roster["status"] not in ("LOCKED", "IN_PROGRESS"):
            raise OpsError("INVALID_STATE", "班表已结束，不能取消")
        return self._cancel_roster(roster_id, reason=reason or "飞行员取消")

    def _cancel_roster(self, roster_id: str, *, reason: str, redraw: bool = False) -> dict[str, Any]:
        roster = self.roster(roster_id)
        if not roster:
            raise OpsError("NOT_FOUND", "班表不存在")
        stamp = utcnow()
        params = self.economy_params()
        fee = 0.0
        if roster["status"] == "IN_PROGRESS" and not redraw:
            fee = float(params.get("pilot_cancel_fee", 5000.0))
        no_show = roster["status"] == "LOCKED" and not redraw
        with self._tx() as con:
            con.execute("update roster set status='CANCELLED', updated_at=? where id=?",
                        (stamp, roster_id))
            for leg in roster["legs"]:
                if leg["status"] in ("PLANNED", "IN_PROGRESS"):
                    if leg.get("flight_instance_id"):
                        con.execute("update flight_instance set status='SCHEDULED', assigned_aircraft_id=NULL, "
                                    "roster_id=NULL, updated_at=? where id=? and status in "
                                    "('ASSIGNED','SCHEDULED')", (stamp, leg["flight_instance_id"]))
                    con.execute("update roster_leg set status='CANCELLED', updated_at=? where id=?",
                                (stamp, leg["id"]))
            con.execute("update aircraft_lock set status='RELEASED', released_at=? "
                        "where roster_id=? and status in ('HELD','IN_FLIGHT')", (stamp, roster_id))
            still_locked = con.execute(
                "select count(*) from aircraft_lock where aircraft_id=? and status in ('HELD','IN_FLIGHT')",
                (roster["aircraft_id"],)).fetchone()[0]
            if not still_locked:
                con.execute("update aircraft set status='ACTIVE', updated_at=?, version=version+1 "
                            "where id=?", (stamp, roster["aircraft_id"]))
            if no_show:
                count = int(self._meta_get(NO_SHOW_KEY, 0) or 0) + 1
                self._meta_set(NO_SHOW_KEY, count, con)
            if fee:
                self._ledger_entries(con, None, None, [
                    {"type": "PENALTY_CANCEL", "amount": -fee,
                     "description": f"首段后取消班表 {roster_id[:8]}"}])
            self._audit(con, "ROSTER_REDRAW" if redraw else "ROSTER_CANCEL", "roster", roster_id,
                        roster["status"], "CANCELLED", reason)
            task = self._meta_get(ACTIVE_TASK_KEY)
            if isinstance(task, dict) and task.get("roster_id") == roster_id:
                self._meta_set(ACTIVE_TASK_KEY, {**task, "finished": True}, con)
        return self.roster(roster_id) or {}

    def expire_roster(self, roster_id: str) -> dict[str, Any]:
        roster = self.roster(roster_id)
        if not roster or roster["status"] != "LOCKED":
            raise OpsError("INVALID_STATE", "只有未开始的班表可以过期")
        params = self.economy_params()
        fee = float(params.get("no_show_fee", 5000.0))
        stamp = utcnow()
        with self._tx() as con:
            con.execute("update roster set status='EXPIRED', updated_at=? where id=?",
                        (stamp, roster_id))
            for leg in roster["legs"]:
                if leg.get("flight_instance_id"):
                    con.execute("update flight_instance set status='SCHEDULED', assigned_aircraft_id=NULL, "
                                "roster_id=NULL, updated_at=? where id=?", (stamp, leg["flight_instance_id"]))
                con.execute("update roster_leg set status='CANCELLED', updated_at=? where id=?",
                            (stamp, leg["id"]))
            con.execute("update aircraft_lock set status='EXPIRED', released_at=? where roster_id=?",
                        (stamp, roster_id))
            con.execute("update aircraft set status='ACTIVE', updated_at=?, version=version+1 where id=?",
                        (stamp, roster["aircraft_id"]))
            self._meta_set(NO_SHOW_KEY, int(self._meta_get(NO_SHOW_KEY, 0) or 0) + 1, con)
            if fee:
                self._ledger_entries(con, None, None, [
                    {"type": "PENALTY_NO_SHOW", "amount": -fee,
                     "description": f"班表过期 {roster_id[:8]}"}])
            self._audit(con, "ROSTER_EXPIRE", "roster", roster_id, "LOCKED", "EXPIRED")
        return self.roster(roster_id) or {}

    # ------------------------------------------------------------------ 自由飞
    def free_aircraft(self, dep: str | None = None, type_id: str | None = None) -> list[dict[str, Any]]:
        fleet = [a for a in self.list_fleet() if a["status"] == "ACTIVE" and not a.get("locked")]
        if dep:
            fleet = [a for a in fleet if (a.get("current_airport_icao") or "").upper() == dep.upper()]
        if type_id:
            fleet = [a for a in fleet if a["type_id"] == type_id]
        return fleet

    def create_free_flight(self, data: dict[str, Any]) -> dict[str, Any]:
        aircraft_id = data.get("aircraft_id")
        aircraft = self.get_aircraft(aircraft_id) if aircraft_id else None
        if not aircraft:
            raise OpsError("NOT_FOUND", "飞机不存在")
        if aircraft.get("locked") or aircraft["status"] != "ACTIVE":
            raise OpsError("AIRCRAFT_LOCKED", "飞机已被占用或不可用")
        dep = (data.get("dep_icao") or "").strip().upper()
        arr = (data.get("arr_icao") or "").strip().upper()
        current = (aircraft.get("current_airport_icao") or "").upper()
        if not dep or not arr:
            raise OpsError("VALIDATION", "请填写起降机场")
        if dep != current:
            raise OpsError("AIRCRAFT_NOT_AT_DEPARTURE",
                           f"飞机当前在 {current or '未知'}，需调机后才能从 {dep} 起飞",
                           {"current": current, "required": dep})
        type_row = self.get_type(aircraft["type_id"]) or {}
        dep_meta = eco.airport_meta(self.nav, dep)
        arr_meta = eco.airport_meta(self.nav, arr)
        distance = eco.gcd_nm(dep_meta, arr_meta)
        if not distance:
            raise OpsError("VALIDATION", "无法计算距离（navdata 缺少机场）")
        if distance > float(type_row.get("range_nm") or 0) * 0.9:
            raise OpsError("OUT_OF_RANGE", f"{distance:.0f}NM 超出机型航程")
        if arr_meta.get("runway_m") and type_row.get("min_runway_m"):
            if arr_meta["runway_m"] < type_row["min_runway_m"]:
                raise OpsError("RUNWAY_TOO_SHORT", "到达机场跑道短于机型要求")
        instance = None
        if data.get("flight_instance_id"):
            instance = self._one("select * from flight_instance where id=?", (data["flight_instance_id"],))
            if not instance or instance["status"] != "SCHEDULED":
                raise OpsError("INSTANCE_UNAVAILABLE", "航班实例不可用")
            if instance["dep_icao"].upper() != dep or instance["arr_icao"].upper() != arr:
                raise OpsError("VALIDATION", "自由飞行与所选航班实例的起降不一致")
        now = _now()
        expires = now + timedelta(minutes=FREE_LOCK_MINUTES)
        free_id = new_id()
        stamp = utcnow()
        with self._tx() as con:
            con.execute(
                "insert into free_flight(id, aircraft_id, flight_instance_id, dep_icao, arr_icao, "
                "dep_time_utc, status, lock_expires_at, created_at, updated_at) "
                "values(?,?,?,?,?,?,?,?,?,?)",
                (free_id, aircraft_id, data.get("flight_instance_id"), dep, arr,
                 data.get("dep_time_utc") or stamp, "LOCKED", _iso(expires), stamp, stamp))
            if instance:
                con.execute("update flight_instance set status='ASSIGNED', assigned_aircraft_id=?, updated_at=? "
                            "where id=?", (aircraft_id, stamp, instance["id"]))
            con.execute("update aircraft set status='HELD', updated_at=?, version=version+1 where id=?",
                        (stamp, aircraft_id))
            con.execute(
                "insert into aircraft_lock(id, aircraft_id, free_flight_id, lock_type, status, "
                "acquired_at, expires_at, heartbeat_at) values(?,?,?,?,?,?,?,?)",
                (new_id(), aircraft_id, free_id, "FREE", "HELD", stamp, _iso(expires), stamp))
            self._audit(con, "FREE_FLIGHT_CREATE", "free_flight", free_id, None,
                        {"aircraft": aircraft["registration"], "dep": dep, "arr": arr})
        return self.free_flight(free_id) or {}

    def free_flight(self, free_id: str) -> dict[str, Any] | None:
        row = self._one("select * from free_flight where id=?", (free_id,))
        if not row:
            return None
        row["aircraft"] = self.get_aircraft(row["aircraft_id"]) or {}
        row["callsign"] = self._free_callsign(row["id"])
        return row

    def current_free_flight(self) -> dict[str, Any] | None:
        row = self._one("select * from free_flight where status in ('LOCKED','IN_FLIGHT') "
                        "order by created_at desc limit 1")
        return self.free_flight(row["id"]) if row else None

    def heartbeat_free(self, free_id: str) -> dict[str, Any]:
        row = self._one("select * from free_flight where id=?", (free_id,))
        if not row or row["status"] != "LOCKED":
            raise OpsError("INVALID_STATE", "自由飞行锁不存在或已开始")
        expires = _iso(_now() + timedelta(minutes=FREE_LOCK_MINUTES))
        with self._tx() as con:
            con.execute("update free_flight set lock_expires_at=?, updated_at=? where id=?",
                        (expires, utcnow(), free_id))
            con.execute("update aircraft_lock set expires_at=?, heartbeat_at=? where free_flight_id=? "
                        "and status='HELD'", (expires, utcnow(), free_id))
        return self.free_flight(free_id) or {}

    def cancel_free(self, free_id: str) -> dict[str, Any]:
        row = self._one("select * from free_flight where id=?", (free_id,))
        if not row:
            raise OpsError("NOT_FOUND", "自由飞行任务不存在")
        if row["status"] not in ("LOCKED", "IN_FLIGHT"):
            raise OpsError("INVALID_STATE", "任务已结束")
        stamp = utcnow()
        with self._tx() as con:
            con.execute("update free_flight set status='CANCELLED', updated_at=? where id=?",
                        (stamp, free_id))
            if row.get("flight_instance_id"):
                con.execute("update flight_instance set status='SCHEDULED', assigned_aircraft_id=NULL, "
                            "updated_at=? where id=?", (stamp, row["flight_instance_id"]))
            con.execute("update aircraft_lock set status='RELEASED', released_at=? where free_flight_id=?",
                        (stamp, free_id))
            con.execute("update aircraft set status='ACTIVE', updated_at=?, version=version+1 where id=?",
                        (stamp, row["aircraft_id"]))
            self._audit(con, "FREE_FLIGHT_CANCEL", "free_flight", free_id, row["status"], "CANCELLED")
        return self.free_flight(free_id) or {}

    # ------------------------------------------------------------------ 配置
    def economy_params(self) -> dict[str, Any]:
        row = self._one("select value_json from ops_config where key='economy'")
        value = _json_load(row["value_json"] if row else None, None)
        return value if isinstance(value, dict) else default_economy()

    def settlement_policy(self) -> dict[str, Any]:
        row = self._one("select value_json from ops_config where key='settlement_policy'")
        value = _json_load(row["value_json"] if row else None, None)
        return value if isinstance(value, dict) else default_policy()

    def config(self) -> dict[str, Any]:
        row = self._one("select max(version) as v from ops_config_version")
        versions = self._rows(
            "select id, version, status, note, created_at from ops_config_version order by version desc limit 20")
        return {
            "economy": self.economy_params(),
            "policy": self.settlement_policy(),
            "version": int((row or {}).get("v") or 0),
            "versions": versions,
            "param_schema": PARAM_SCHEMA,
        }

    def _validate_economy(self, economy: dict[str, Any]) -> dict[str, Any]:
        defaults = default_economy()
        merged = {**defaults, **(economy or {})}
        for item in PARAM_SCHEMA:
            key = item["key"]
            value = merged.get(key)
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise OpsError("VALIDATION", f"{item['label']} 必须是数字") from exc
            if number < float(item["min"]) or number > float(item["max"]):
                raise OpsError("PARAM_OUT_OF_RANGE",
                               f"{item['label']} 超出范围 {item['min']}–{item['max']}")
            merged[key] = number
        if float(merged["fare_business_multiplier"]) < 1.0:
            raise OpsError("VALIDATION", "商务舱倍率必须 ≥ 1")
        if float(merged["fare_first_multiplier"]) <= float(merged["fare_business_multiplier"]):
            raise OpsError("VALIDATION", "头等舱倍率必须大于商务舱倍率")
        return merged

    def _validate_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        base = default_policy()
        merged = {**base, **(policy or {})}
        scope = str(merged.get("scope_mode") or "COMPANY_ONLY").upper()
        if scope not in ("COMPANY_ONLY", "ALLOW_OVERRIDES"):
            raise OpsError("VALIDATION", "scope_mode 只能是 COMPANY_ONLY / ALLOW_OVERRIDES")
        merged["scope_mode"] = scope
        action = str(merged.get("default_action") or "REVIEW").upper()
        if action not in SEVERITY:
            raise OpsError("VALIDATION", "default_action 不合法")
        merged["default_action"] = action
        cost_mode = str(merged.get("reject_cost_mode") or "FULL").upper()
        if cost_mode not in ("FULL", "DIRECT_ONLY", "NONE"):
            raise OpsError("VALIDATION", "reject_cost_mode 只能是 FULL/DIRECT_ONLY/NONE")
        merged["reject_cost_mode"] = cost_mode
        ratio = float(merged.get("review_advance_ratio") or 0)
        if ratio < 0 or ratio > 0.5:
            raise OpsError("PARAM_OUT_OF_RANGE", "review_advance_ratio 必须在 0–0.5")
        merged["review_advance_ratio"] = ratio
        min_factor = float(merged.get("min_payout_factor") or 0.4)
        if min_factor < 0 or min_factor > 1:
            raise OpsError("PARAM_OUT_OF_RANGE", "min_payout_factor 必须在 0–1")
        merged["min_payout_factor"] = min_factor
        merged["rules"] = {**base["rules"], **(merged.get("rules") or {})}
        merged["overrides"] = merged.get("overrides") or []
        return merged

    def publish_config(self, economy: dict[str, Any] | None, policy: dict[str, Any] | None,
                       note: str, expected_version: int | None = None) -> dict[str, Any]:
        if not note or len(note.strip()) < 2:
            raise OpsError("VALIDATION", "请填写变更原因（至少 2 个字）")
        new_economy = self._validate_economy(economy if economy is not None else self.economy_params())
        new_policy = self._validate_policy(policy if policy is not None else self.settlement_policy())
        row = self._one("select max(version) as v from ops_config_version")
        current = int((row or {}).get("v") or 0)
        if expected_version is not None and int(expected_version) != current:
            raise OpsError("CONFIG_VERSION_CONFLICT",
                           f"配置已被他人修改（当前 v{current}），请刷新后合并",
                           {"current_version": current})
        before_econ, before_policy = self.economy_params(), self.settlement_policy()
        version = current + 1
        stamp = utcnow()
        with self._tx() as con:
            con.execute(
                "insert into ops_config_version(id, version, status, note, snapshot_json, created_at) "
                "values(?,?,?,?,?,?)",
                (new_id(), version, "PUBLISHED", note.strip(),
                 json.dumps({"economy": new_economy, "policy": new_policy}, ensure_ascii=False), stamp))
            for key, value, before in (("economy", new_economy, before_econ),
                                       ("settlement_policy", new_policy, before_policy)):
                con.execute(
                    "insert or replace into ops_config(key, value_json, version, updated_at) values(?,?,?,?)",
                    (key, json.dumps(value, ensure_ascii=False), version, stamp))
                con.execute(
                    "insert or replace into ops_config_history(id, version, key, value_json, created_at) "
                    "values(?,?,?,?,?)",
                    (new_id(), version, key, json.dumps(value, ensure_ascii=False), stamp))
                self._audit(con, "CONFIG_PUBLISH", "config", key, before, value, note.strip())
        return self.config()

    def rollback_config(self, version: int, note: str | None = None) -> dict[str, Any]:
        row = self._one("select * from ops_config_version where version=?", (int(version),))
        if not row:
            raise OpsError("NOT_FOUND", "配置版本不存在")
        snapshot = _json_load(row["snapshot_json"], {})
        return self.publish_config(snapshot.get("economy"), snapshot.get("policy"),
                                   note or f"回滚到 v{version}")

    def config_history(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._rows("select * from ops_config_history order by version desc limit ?", (limit,))
        for row in rows:
            row["value"] = _json_load(row.pop("value_json", None), {})
        return rows

    def preview_config(self, economy: dict[str, Any] | None, policy: dict[str, Any] | None,
                       anomalies: list[str] | None = None) -> dict[str, Any]:
        params = self._validate_economy(economy if economy is not None else self.economy_params())
        result = {"economy": eco.synthetic_preview(params)}
        if anomalies is not None or policy is not None:
            policy_row = self._validate_policy(policy if policy is not None else self.settlement_policy())
            samples = []
            for kind in (anomalies or ["DATA_GAP", "SIM_RATE", "PAUSE", "TELEPORT"]):
                kind = str(kind).upper()
                samples.append({"kind": kind, "units": 1.2 if kind == "DATA_GAP" else 1,
                                "value": 12 if kind == "DATA_GAP" else 3,
                                "detail": kind})
            result["policy"] = evaluate(policy_row, samples)
        return result

    def resolve_effective_policy(self, aircraft_id: str | None) -> dict[str, Any]:
        aircraft = self.get_aircraft(aircraft_id) if aircraft_id else None
        type_row = self.get_type(aircraft["type_id"]) if aircraft else None
        return dict(zip(("policy", "sources"),
                        resolve_policy(self.settlement_policy(), aircraft_type=type_row, aircraft=aircraft)))

    # ------------------------------------------------------------------ 班段执行
    def active_task(self) -> dict[str, Any] | None:
        task = self._meta_get(ACTIVE_TASK_KEY)
        if not isinstance(task, dict) or task.get("finished"):
            return None
        return task

    def start_leg(self, roster_id: str, sequence: int) -> dict[str, Any]:
        roster = self.roster(roster_id)
        if not roster:
            raise OpsError("NOT_FOUND", "班表不存在")
        if roster["status"] not in ("LOCKED", "IN_PROGRESS"):
            raise OpsError("INVALID_STATE", "班表不在可执行状态")
        leg = next((l for l in roster["legs"] if int(l["sequence"]) == int(sequence)), None)
        if not leg:
            raise OpsError("NOT_FOUND", "航段不存在")
        if leg["status"] != "PLANNED":
            raise OpsError("INVALID_STATE", "该航段已经开始或已结束")
        previous = [l for l in roster["legs"] if int(l["sequence"]) < int(sequence)]
        if any(l["status"] != "COMPLETED" for l in previous):
            raise OpsError("INVALID_STATE", "请先完成前序航段")
        if roster["status"] == "LOCKED" and int(sequence) != 1:
            raise OpsError("INVALID_STATE", "班表必须先开始第一段")
        aircraft = self.get_aircraft(roster["aircraft_id"])
        if not aircraft:
            raise OpsError("NOT_FOUND", "飞机不存在")
        dep = (leg.get("dep_icao") or "").upper()
        if (aircraft.get("current_airport_icao") or "").upper() != dep:
            raise OpsError("AIRCRAFT_NOT_AT_DEPARTURE",
                           f"飞机当前在 {aircraft.get('current_airport_icao')}，无法从 {dep} 起飞")
        if self.active_task():
            raise OpsError("TASK_IN_PROGRESS", "已有正在执行的任务")
        type_row = self.get_type(aircraft["type_id"]) or {}
        flight_id = new_id()
        params, policy = self.economy_params(), self.settlement_policy()
        policy_row, sources = resolve_policy(policy, aircraft_type=type_row, aircraft=aircraft)
        version = int((self._one("select max(version) as v from ops_config_version") or {}).get("v") or 0)
        instance = self._one("select * from flight_instance where id=?",
                             (leg["flight_instance_id"],)) if leg.get("flight_instance_id") else None
        # seed 与航段绑定（而非随机 flight_id），保证「开始前」的 SimBrief 配载与开始时固化的一致
        load = self._leg_load(leg, type_row, seed=f"roster-{leg['id']}", params=params)
        task = {
            "kind": "ROSTER", "roster_id": roster_id, "roster_leg_id": leg["id"],
            "flight_instance_id": leg.get("flight_instance_id"), "flight_record_id": flight_id,
            "aircraft_id": aircraft["id"], "dep_icao": leg.get("dep_icao"),
            "arr_icao": leg.get("arr_icao"), "aircraft_type": type_row.get("icao"),
            "callsign": self._callsign(instance["flight_number"] if instance else None),
            "scheduled_dep_utc": (instance or {}).get("scheduled_dep_utc"),
            "mission_type": (instance or {}).get("mission_type") or "SCHEDULED",
            "started_at": utcnow(),
        }
        stamp = utcnow()
        with self._tx() as con:
            con.execute(
                "insert into load_sheet(id, flight_record_id, flight_instance_id, aircraft_id, "
                "aircraft_type_id, seed, dep_icao, arr_icao, distance_nm, block_minutes, pax_total, "
                "pax_economy, pax_premium_economy, pax_business, pax_first, cargo_kg, mail_kg, oew_kg, "
                "zfw_kg, tow_kg, fuel_kg, estimated_revenue, estimated_cost, breakdown_json, created_at) "
                "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id(), flight_id, task["flight_instance_id"], aircraft["id"], type_row.get("id"),
                 flight_id, leg.get("dep_icao"), leg.get("arr_icao"), load["distance_nm"],
                 load["block_minutes"], load["pax_total"], load["pax_economy"],
                 load["pax_premium_economy"], load["pax_business"], load["pax_first"],
                 load["cargo_kg"], load["mail_kg"], load["oew_kg"], load["zfw_kg"], load["tow_kg"],
                 load["fuel_kg"], load["estimated_revenue"], load["estimated_cost"],
                 json.dumps(load["breakdown"], ensure_ascii=False), stamp))
            con.execute(
                "insert into economy_snapshot(id, flight_record_id, config_version, params_json, "
                "policy_json, policy_sources_json, created_at) values(?,?,?,?,?,?,?)",
                (new_id(), flight_id, version, json.dumps(params, ensure_ascii=False),
                 json.dumps(policy_row, ensure_ascii=False),
                 json.dumps(sources, ensure_ascii=False), stamp))
            con.execute("update roster_leg set status='IN_PROGRESS', flight_record_id=?, "
                        "actual_dep_utc=?, updated_at=? where id=?", (flight_id, stamp, stamp, leg["id"]))
            con.execute("update roster set status='IN_PROGRESS', started_at=coalesce(started_at, ?), "
                        "updated_at=? where id=?", (stamp, stamp, roster_id))
            con.execute("update flight_instance set status='STARTED', updated_at=? where id=?",
                        (stamp, leg["flight_instance_id"]))
            con.execute("update aircraft set status='IN_FLIGHT', updated_at=?, version=version+1 "
                        "where id=?", (stamp, aircraft["id"]))
            con.execute("update aircraft_lock set status='IN_FLIGHT', heartbeat_at=?, expires_at=NULL "
                        "where roster_id=? and status='HELD'", (stamp, roster_id))
            self._meta_set(ACTIVE_TASK_KEY, task, con)
            self._audit(con, "LEG_START", "roster_leg", leg["id"], "PLANNED", "IN_PROGRESS")
        return {"task": task, "load_sheet": self.load_sheet(flight_id), "roster": self.roster(roster_id)}

    def start_free_flight(self, free_id: str) -> dict[str, Any]:
        free = self.free_flight(free_id)
        if not free:
            raise OpsError("NOT_FOUND", "自由飞行任务不存在")
        if free["status"] != "LOCKED":
            raise OpsError("INVALID_STATE", "任务不在待执行状态")
        if free["lock_expires_at"] and eco.parse_utc(free["lock_expires_at"]) < _now():
            raise OpsError("LOCK_EXPIRED", "自由飞行锁已过期，请重新领取")
        aircraft = free.get("aircraft") or {}
        type_row = self.get_type(aircraft.get("type_id")) or {}
        if (aircraft.get("current_airport_icao") or "").upper() != free["dep_icao"].upper():
            raise OpsError("AIRCRAFT_NOT_AT_DEPARTURE", "飞机不在出发机场")
        flight_id = new_id()
        params, policy = self.economy_params(), self.settlement_policy()
        policy_row, sources = resolve_policy(policy, aircraft_type=type_row, aircraft=aircraft)
        version = int((self._one("select max(version) as v from ops_config_version") or {}).get("v") or 0)
        load = self._free_load(free, type_row, seed=f"free-{free_id}", params=params)
        task = {
            "kind": "FREE", "free_flight_id": free_id, "flight_record_id": flight_id,
            "aircraft_id": aircraft.get("id"), "dep_icao": free["dep_icao"],
            "arr_icao": free["arr_icao"], "aircraft_type": type_row.get("icao"),
            "callsign": self._free_callsign(free_id), "scheduled_dep_utc": free.get("dep_time_utc"),
            "mission_type": "FREE", "started_at": utcnow(),
        }
        stamp = utcnow()
        with self._tx() as con:
            con.execute(
                "insert into load_sheet(id, flight_record_id, flight_instance_id, aircraft_id, "
                "aircraft_type_id, seed, dep_icao, arr_icao, distance_nm, block_minutes, pax_total, "
                "pax_economy, pax_premium_economy, pax_business, pax_first, cargo_kg, mail_kg, oew_kg, "
                "zfw_kg, tow_kg, fuel_kg, estimated_revenue, estimated_cost, breakdown_json, created_at) "
                "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id(), flight_id, free.get("flight_instance_id"), aircraft.get("id"), type_row.get("id"),
                 flight_id, free["dep_icao"], free["arr_icao"], load["distance_nm"], load["block_minutes"],
                 load["pax_total"], load["pax_economy"], load["pax_premium_economy"],
                 load["pax_business"], load["pax_first"], load["cargo_kg"], load["mail_kg"],
                 load["oew_kg"], load["zfw_kg"], load["tow_kg"], load["fuel_kg"],
                 load["estimated_revenue"], load["estimated_cost"],
                 json.dumps(load["breakdown"], ensure_ascii=False), stamp))
            con.execute(
                "insert into economy_snapshot(id, flight_record_id, config_version, params_json, "
                "policy_json, policy_sources_json, created_at) values(?,?,?,?,?,?,?)",
                (new_id(), flight_id, version, json.dumps(params, ensure_ascii=False),
                 json.dumps(policy_row, ensure_ascii=False),
                 json.dumps(sources, ensure_ascii=False), stamp))
            con.execute("update free_flight set status='IN_FLIGHT', flight_record_id=?, updated_at=? "
                        "where id=?", (flight_id, stamp, free_id))
            con.execute("update flight_instance set status='STARTED', updated_at=? where id=?",
                        (stamp, free.get("flight_instance_id")))
            con.execute("update aircraft set status='IN_FLIGHT', updated_at=?, version=version+1 "
                        "where id=?", (stamp, aircraft.get("id")))
            con.execute("update aircraft_lock set status='IN_FLIGHT', heartbeat_at=?, expires_at=NULL "
                        "where free_flight_id=? and status='HELD'", (stamp, free_id))
            self._meta_set(ACTIVE_TASK_KEY, task, con)
            self._audit(con, "FREE_FLIGHT_START", "free_flight", free_id, "LOCKED", "IN_FLIGHT")
        return {"task": task, "load_sheet": self.load_sheet(flight_id), "free_flight": self.free_flight(free_id)}

    def _callsign(self, flight_number: str | None) -> str:
        """抽班：用档案里的航班号前缀改写班期号（AOC101 → 自定义前缀）。"""
        if flight_number:
            prefix = (self.profile() or {}).get("flight_prefix") or "AOC"
            return _with_prefix(flight_number, prefix)
        return self._free_callsign(None)

    def _free_callsign(self, free_id: str | None) -> str:
        """自由飞：呼号前缀 + 3 位数字；同一任务每次计算结果一致，便于 SimBrief 预填。"""
        prefix = (self.profile() or {}).get("callsign_prefix") or "AUV"
        if free_id:
            number = int(hashlib.sha256(free_id.encode()).hexdigest()[:4], 16) % 900 + 100
        else:
            number = int(_now().timestamp()) % 900 + 100
        return f"{prefix}{number:03d}"

    def _repeat_index(self, dep: str | None, arr: str | None, day_iso: str | None) -> int:
        if not dep or not arr:
            return 0
        day = (day_iso or utcnow())[:10]
        row = self._one(
            "select count(*) as n from flight_record where dep_icao=? and arr_icao=? "
            "and substr(coalesce(block_off_utc, created_at),1,10)=? "
            "and status in ('COMPLETED','DIVERTED')", (dep, arr, day))
        return int((row or {}).get("n") or 0)

    def load_sheet(self, flight_record_id: str) -> dict[str, Any] | None:
        row = self._one("select * from load_sheet where flight_record_id=?", (flight_record_id,))
        if not row:
            return None
        row["breakdown_json"] = _json_load(row.get("breakdown_json"), {})
        row["aircraft"] = self.get_aircraft(row["aircraft_id"]) or {}
        return row

    # ------------------------------------------------------- 配载（可预算）
    def _leg_load(self, leg: dict[str, Any], type_row: dict[str, Any], *, seed: str,
                  params: dict[str, Any] | None = None) -> dict[str, Any]:
        """按班表航段生成配载；seed 与航段绑定，开始前预算 == 开始后固化。"""
        instance = self._one("select * from flight_instance where id=?",
                             (leg["flight_instance_id"],)) if leg.get("flight_instance_id") else None
        route = self._one("select * from ops_route where id=?",
                          ((instance or {}).get("route_id"),)) if instance else None
        distance = float((route or {}).get("distance_nm") or 0)
        if not distance:
            distance = eco.gcd_nm(eco.airport_meta(self.nav, leg.get("dep_icao")),
                                  eco.airport_meta(self.nav, leg.get("arr_icao")))
        block = float((route or {}).get("block_minutes") or eco.estimate_block_minutes(
            distance, type_row.get("cruise_speed_kt") or 440))
        repeat = self._repeat_index(leg.get("dep_icao"), leg.get("arr_icao"),
                                    instance["scheduled_dep_utc"] if instance else utcnow())
        return eco.generate_load_sheet(
            dep=leg.get("dep_icao") or "", arr=leg.get("arr_icao") or "", distance_nm=distance,
            block_minutes=block, aircraft_type=type_row, params=params or self.economy_params(),
            seed=seed, dep_time_utc=(instance or {}).get("scheduled_dep_utc") or utcnow(),
            repeat_index=repeat,
            dep_meta=eco.airport_meta(self.nav, leg.get("dep_icao")),
            arr_meta=eco.airport_meta(self.nav, leg.get("arr_icao")),
            mission_type=(instance or {}).get("mission_type") or "SCHEDULED")

    def _free_load(self, free: dict[str, Any], type_row: dict[str, Any], *, seed: str,
                   params: dict[str, Any] | None = None) -> dict[str, Any]:
        dep_meta = eco.airport_meta(self.nav, free.get("dep_icao"))
        arr_meta = eco.airport_meta(self.nav, free.get("arr_icao"))
        distance = eco.gcd_nm(dep_meta, arr_meta)
        block = eco.estimate_block_minutes(distance, type_row.get("cruise_speed_kt") or 440)
        return eco.generate_load_sheet(
            dep=free.get("dep_icao") or "", arr=free.get("arr_icao") or "",
            distance_nm=distance, block_minutes=block, aircraft_type=type_row,
            params=params or self.economy_params(), seed=seed,
            dep_time_utc=free.get("dep_time_utc"), dep_meta=dep_meta, arr_meta=arr_meta)

    def simbrief_context(self, *, roster_id: str | None = None, sequence: int | None = None,
                         free_id: str | None = None,
                         flight_record_id: str | None = None) -> dict[str, Any]:
        """SimBrief 预填：起降、机型、呼号、注册号 + 配载（旅客/货物/燃油）。"""
        if flight_record_id:
            sheet = self.load_sheet(flight_record_id)
            flight = self._one("select callsign, dep_icao, arr_icao from flight_record where id=?",
                               (flight_record_id,)) or {}
            task = self.active_task() or {}
            if sheet:
                aircraft = sheet.get("aircraft") or {}
                type_row = self.get_type(sheet.get("aircraft_type_id")) or {}
                return _simbrief_payload(
                    dep=sheet.get("dep_icao"), arr=sheet.get("arr_icao"),
                    aircraft_type=type_row.get("icao") or task.get("aircraft_type"),
                    callsign=flight.get("callsign") or task.get("callsign"),
                    registration=aircraft.get("registration"), sheet=sheet)
            if flight:
                return _simbrief_payload(
                    dep=flight.get("dep_icao"), arr=flight.get("arr_icao"),
                    aircraft_type=task.get("aircraft_type"), callsign=flight.get("callsign"))
        if roster_id:
            roster = self.roster(roster_id)
            if not roster:
                raise OpsError("NOT_FOUND", "班表不存在")
            wanted = int(sequence or 0)
            leg = next((l for l in roster["legs"] if int(l["sequence"]) == wanted), None) \
                or next((l for l in roster["legs"] if l["status"] == "PLANNED"), None)
            if not leg:
                raise OpsError("INVALID_STATE", "班表没有可用航段")
            aircraft = self.get_aircraft(roster["aircraft_id"]) or {}
            type_row = self.get_type(aircraft.get("type_id")) or {}
            sheet = self._leg_load(leg, type_row, seed=f"roster-{leg['id']}")
            return _simbrief_payload(
                dep=leg.get("dep_icao"), arr=leg.get("arr_icao"),
                aircraft_type=type_row.get("icao"), callsign=leg.get("callsign"),
                registration=aircraft.get("registration"), sheet=sheet)
        if free_id:
            free = self.free_flight(free_id)
            if not free:
                raise OpsError("NOT_FOUND", "自由飞行任务不存在")
            aircraft = free.get("aircraft") or {}
            type_row = self.get_type(aircraft.get("type_id")) or {}
            sheet = self._free_load(free, type_row, seed=f"free-{free_id}")
            return _simbrief_payload(
                dep=free.get("dep_icao"), arr=free.get("arr_icao"),
                aircraft_type=type_row.get("icao"), callsign=free.get("callsign"),
                registration=aircraft.get("registration"), sheet=sheet)
        raise OpsError("VALIDATION", "缺少航段参数")

    # ------------------------------------------------------------------ SimLink 接入
    def context_for_recording(self) -> dict[str, Any] | None:
        task = self.active_task()
        if not task:
            return None
        if task.get("finished"):
            return None
        return task

    def abort_task(self, reason: str | None = None,
                   task: dict[str, Any] | None = None) -> dict[str, Any]:
        """飞行员放弃当前航班：取消本段与剩余航段、释放飞机、清空任务（不结算）。"""
        current = task or self.active_task()
        if not current:
            raise OpsError("INVALID_STATE", "没有正在执行的任务")
        flight = self._one("select * from flight_record where id=?",
                           (current.get("flight_record_id"),))
        result = self._abort_task(current, flight)
        with self._tx() as con:
            self._audit(con, "TASK_ABORT_MANUAL", current.get("kind") or "task",
                        current.get("roster_id") or current.get("free_flight_id"), None, None,
                        reason or "飞行员取消")
        return {**result, "task": current}

    def on_flight_finalized(self, flight: dict[str, Any]) -> dict[str, Any] | None:
        task = self.active_task()
        if not task or task.get("flight_record_id") != flight.get("id"):
            return None
        status = (flight.get("status") or "").upper()
        if status in ("COMPLETED", "DIVERTED"):
            return self.settle_flight(flight)
        return self._abort_task(task, flight)

    def _abort_task(self, task: dict[str, Any], flight: dict[str, Any] | None) -> dict[str, Any]:
        stamp = utcnow()
        aircraft_id = task.get("aircraft_id")
        with self._tx() as con:
            if task.get("kind") == "ROSTER" and task.get("roster_leg_id"):
                con.execute("update roster_leg set status='CANCELLED', updated_at=? where id=?",
                            (stamp, task["roster_leg_id"]))
            if task.get("kind") == "ROSTER" and task.get("roster_id"):
                con.execute("update roster set status='CANCELLED', updated_at=? where id=?",
                            (stamp, task["roster_id"]))
                con.execute("update roster_leg set status='CANCELLED', updated_at=? "
                            "where roster_id=? and status='PLANNED'", (stamp, task["roster_id"]))
            if task.get("kind") == "FREE" and task.get("free_flight_id"):
                con.execute("update free_flight set status='ABORTED', updated_at=? where id=?",
                            (stamp, task["free_flight_id"]))
            if aircraft_id:
                con.execute("update aircraft_lock set status='RELEASED', released_at=? "
                            "where aircraft_id=? and status in ('HELD','IN_FLIGHT')", (stamp, aircraft_id))
                con.execute("update aircraft set status='ACTIVE', updated_at=?, version=version+1 "
                            "where id=?", (stamp, aircraft_id))
            self._meta_set(ACTIVE_TASK_KEY, {**task, "finished": True}, con)
            self._audit(con, "TASK_ABORT", task.get("kind") or "task",
                        task.get("roster_id") or task.get("free_flight_id"), None, None,
                        (flight or {}).get("status"))
        return {"ok": True, "aborted": True}

    def settle_flight(self, flight: dict[str, Any], *, review_action: str | None = None,
                      review_note: str | None = None, force: bool = False) -> dict[str, Any]:
        """结算：收入/成本重算 → 策略折算 → settlement + ledger + 飞机/航班/班表状态。"""
        existing = self._one("select * from settlement where flight_record_id=?", (flight["id"],))
        if existing and not force:
            return existing
        task = self.active_task() or self._task_for_flight(flight["id"])
        load = self.load_sheet(flight["id"])
        snapshot = self._one("select * from economy_snapshot where flight_record_id=?", (flight["id"],))
        if not load or not snapshot:
            return None
        params = _json_load(snapshot["params_json"], default_economy())
        policy_row = _json_load(snapshot["policy_json"], default_policy())
        config_version = int(snapshot.get("config_version") or 0)
        aircraft = (self.get_aircraft(task.get("aircraft_id"))
                    if task and task.get("aircraft_id") else None) or {}
        type_row = self.get_type(aircraft.get("type_id") or load.get("aircraft_type_id")) or {}
        distance = float(flight.get("distance_nm") or load.get("distance_nm") or 0)
        block_minutes = float(flight.get("block_minutes") or load.get("block_minutes") or 0)
        fuel_used = flight.get("fuel_used_kg")
        if fuel_used is None:
            fuel_used = float(type_row.get("fuel_burn_kg_h") or 2400) * block_minutes / 60.0
        arr = flight.get("arr_icao") or load.get("arr_icao")
        amounts = eco.settle_amounts(
            params=params, aircraft=aircraft, aircraft_type=type_row, load_sheet=load,
            distance_nm=distance, block_minutes=block_minutes, fuel_used_kg=float(fuel_used),
            scheduled_dep_utc=(self._instance_dep(task) if task else None)
            or flight.get("scheduled_dep_utc"),
            actual_dep_utc=flight.get("takeoff_utc") or flight.get("block_off_utc"),
            arr=arr, arr_time_utc=flight.get("landing_utc") or flight.get("block_on_utc"))

        anomalies = detect_anomalies(flight, self.db.list_events(flight["id"]))
        policy_result = evaluate(policy_row, anomalies)
        action = policy_result["action"]
        factor = policy_result["payout_factor"]
        if review_action:
            action = review_action.upper()
            factor = 1.0 if action == "ACCEPT" else (factor if action == "WEIGHTED" else 0.0)
            policy_result["breakdown"].append({
                "kind": "REVIEW", "action": action, "penalty": round(1 - factor, 4),
                "detail": review_note or "复核"})

        reject_mode = str(policy_row.get("reject_cost_mode") or "FULL").upper()
        revenue_gross = float(amounts["revenue_gross"])
        revenue_items = amounts["revenue_items"]
        cost_items = amounts["cost_items"]
        status = "SETTLED"
        review_status = "NONE"
        advance = 0.0
        already_advanced = float(existing.get("advance_amount") or 0) if existing else 0.0
        if action == "REVIEW":
            status = "HELD"
            review_status = "PENDING"
            ratio = float(policy_row.get("review_advance_ratio") or 0)
            estimated_profit = float(load.get("estimated_revenue") or 0) - float(load.get("estimated_cost") or 0)
            advance = already_advanced or round(max(0.0, estimated_profit) * ratio, 2)
        elif review_action:
            advance = already_advanced
        if action == "REJECT":
            factor = 0.0
            if reject_mode == "NONE":
                status = "VOID"
                revenue_items, cost_items = [], []
        elif action == "ACCEPT":
            factor = 1.0

        revenue_total = round(revenue_gross * factor, 2)
        if action == "REJECT":
            revenue_total = 0.0
        cost_total = 0.0 if status == "VOID" else round(sum(
            float(i["amount"]) for i in cost_items
            if action != "REJECT" or cost_item_allowed(reject_mode, i["type"])), 2)
        if action == "REJECT" and reject_mode == "DIRECT_ONLY":
            # 非直接成本从明细里剔除，账本与明细保持一致
            cost_items = [i for i in cost_items if cost_item_allowed(reject_mode, i["type"])]
        if status == "VOID":
            cost_items = []
        profit = round(revenue_total - cost_total, 2)

        settlement_id = existing["id"] if existing else new_id()
        stamp = utcnow()
        breakdown = {
            "inputs": {
                "distance_nm": round(distance, 1), "block_minutes": round(block_minutes, 1),
                "pax_total": load.get("pax_total"), "fuel_used_kg": round(float(fuel_used), 1),
                "on_time": amounts["on_time_note"],
            },
            "revenue": revenue_items, "costs": cost_items,
            "gross_revenue": revenue_gross, "payout_factor": factor,
            "policy_action": action, "policy": policy_result,
            "profit": profit, "currency": (self.profile() or {}).get("currency", "USD"),
        }
        with self._tx() as con:
            con.execute(
                "insert or replace into settlement(id, flight_record_id, task_kind, roster_id, roster_leg_id, "
                "free_flight_id, aircraft_id, config_version, revenue_gross, revenue_total, cost_total, "
                "profit, payout_factor, advance_amount, policy_action, policy_snapshot_json, "
                "policy_breakdown_json, breakdown_json, status, review_status, review_note, computed_at, "
                "created_at, updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (settlement_id, flight["id"], (task or {}).get("kind"), (task or {}).get("roster_id"),
                 (task or {}).get("roster_leg_id"), (task or {}).get("free_flight_id"),
                 aircraft.get("id") or load.get("aircraft_id"), config_version, revenue_gross,
                 revenue_total, cost_total, profit, factor, advance, action,
                 json.dumps(policy_row, ensure_ascii=False),
                 json.dumps(policy_result, ensure_ascii=False),
                 json.dumps(breakdown, ensure_ascii=False), status, review_status, review_note,
                 stamp, existing["created_at"] if existing else stamp, stamp))
            if status == "SETTLED":
                self._write_settlement_ledger(con, settlement_id, flight["id"], revenue_items,
                                              cost_items, factor, action, 0.0)
                if review_action and advance > 0:
                    # 复核前已付预付款：先用反向条目冲抵，再按最终利润记账，账本合计 = 最终利润
                    self._ledger_entries(con, settlement_id, flight["id"], [{
                        "type": "ADVANCE_CLAWBACK", "amount": -round(advance, 2),
                        "description": f"冲抵复核预付款 ${advance:,.2f}（多退少补）"}])
            elif status == "HELD" and advance > 0 and not already_advanced:
                self._write_settlement_ledger(con, settlement_id, flight["id"], [], [], 1.0,
                                              action, advance, advance_only=True)
            # 复核改判时飞机已落过账（位置/小时/循环），只推进航班与班表状态，避免重复累计
            self._finalize_assets(con, flight, task, aircraft, load, block_minutes, action,
                                  apply_aircraft=existing is None)
            self._audit(con, "SETTLE", "settlement", settlement_id, None,
                        {"profit": profit, "action": action, "factor": factor})
            if not review_action:
                self._meta_set(ACTIVE_TASK_KEY, {**(task or {}), "finished": True}, con)
        return self.settlement(settlement_id) or {}

    def _instance_dep(self, task: dict[str, Any] | None) -> str | None:
        if not task:
            return None
        if task.get("flight_instance_id"):
            row = self._one("select scheduled_dep_utc from flight_instance where id=?",
                            (task["flight_instance_id"],))
            return (row or {}).get("scheduled_dep_utc")
        return None

    def _task_for_flight(self, flight_id: str) -> dict[str, Any] | None:
        row = self._one("select * from roster_leg where flight_record_id=?", (flight_id,))
        if row:
            roster = self._one("select * from roster where id=?", (row["roster_id"],)) or {}
            return {"kind": "ROSTER", "roster_id": row["roster_id"], "roster_leg_id": row["id"],
                    "flight_instance_id": row.get("flight_instance_id"),
                    "aircraft_id": roster.get("aircraft_id"), "flight_record_id": flight_id}
        row = self._one("select * from free_flight where flight_record_id=?", (flight_id,))
        if row:
            return {"kind": "FREE", "free_flight_id": row["id"], "aircraft_id": row["aircraft_id"],
                    "flight_record_id": flight_id, "flight_instance_id": row.get("flight_instance_id")}
        return None

    def _finalize_assets(self, con, flight: dict[str, Any], task: dict[str, Any] | None,
                         aircraft: dict[str, Any], load: dict[str, Any], block_minutes: float,
                         action: str, apply_aircraft: bool = True) -> None:
        stamp = utcnow()
        arr = (flight.get("arr_icao") or load.get("arr_icao") or "").upper()
        aircraft_id = aircraft.get("id") or load.get("aircraft_id")
        if aircraft_id and apply_aircraft:
            fuel_end = flight.get("fuel_end_kg")
            con.execute(
                "update aircraft set current_airport_icao=?, total_hours=total_hours+?, "
                "total_cycles=total_cycles+1, fuel_kg=coalesce(?, fuel_kg), status='ACTIVE', "
                "updated_at=?, version=version+1 where id=?",
                (arr or None, round(block_minutes / 60.0, 3), fuel_end, stamp, aircraft_id))
            con.execute("update aircraft_lock set status='RELEASED', released_at=? "
                        "where aircraft_id=? and status in ('HELD','IN_FLIGHT')", (stamp, aircraft_id))
        if task and task.get("kind") == "ROSTER" and task.get("roster_leg_id"):
            con.execute("update roster_leg set status='COMPLETED', actual_arr_utc=?, updated_at=? "
                        "where id=?", (flight.get("block_on_utc") or stamp, stamp, task["roster_leg_id"]))
            if task.get("flight_instance_id"):
                con.execute("update flight_instance set status=?, updated_at=? where id=?",
                            ("SETTLED" if action != "REVIEW" else "LANDED", stamp,
                             task["flight_instance_id"]))
            remaining = con.execute(
                "select count(*) from roster_leg where roster_id=? and status in ('PLANNED','IN_PROGRESS')",
                (task.get("roster_id"),)).fetchone()[0]
            if not remaining:
                con.execute("update roster set status='COMPLETED', completed_at=?, updated_at=? "
                            "where id=?", (stamp, stamp, task["roster_id"]))
        if task and task.get("kind") == "FREE" and task.get("free_flight_id"):
            con.execute("update free_flight set status='COMPLETED', updated_at=? where id=?",
                        (stamp, task["free_flight_id"]))
            if task.get("flight_instance_id"):
                con.execute("update flight_instance set status=?, updated_at=? where id=?",
                            ("SETTLED" if action != "REVIEW" else "LANDED", stamp,
                             task["flight_instance_id"]))

    def _write_settlement_ledger(self, con, settlement_id: str, flight_id: str,
                                 revenue_items: list[dict[str, Any]], cost_items: list[dict[str, Any]],
                                 factor: float, action: str, advance: float,
                                 advance_only: bool = False) -> None:
        entries: list[dict[str, Any]] = []
        if not advance_only:
            gross = sum(float(i["amount"]) for i in revenue_items)
            if action == "REJECT":
                for item in cost_items:
                    entries.append({"type": item["type"], "amount": -round(float(item["amount"]), 2),
                                    "description": item.get("note") or ""})
            else:
                for item in revenue_items:
                    entries.append({"type": item["type"], "amount": round(float(item["amount"]), 2),
                                    "description": item.get("note") or ""})
                if factor < 1.0:
                    entries.append({"type": "POLICY_ADJUSTMENT",
                                    "amount": -round(gross * (1.0 - factor), 2),
                                    "description": f"策略折算 ×{factor:.2f}（{action}）"})
                for item in cost_items:
                    entries.append({"type": item["type"], "amount": -round(float(item["amount"]), 2),
                                    "description": item.get("note") or ""})
        if advance > 0:
            entries.append({"type": "ADVANCE_PAYOUT", "amount": round(advance, 2),
                            "description": "复核前预付款"})
        self._ledger_entries(con, settlement_id, flight_id, entries)

    def _ledger_entries(self, con, settlement_id: str | None, flight_id: str | None,
                        entries: list[dict[str, Any]]) -> None:
        if not entries:
            return
        row = con.execute("select balance, currency from ops_profile where id='local'").fetchone()
        balance = float(row["balance"]) if row else 0.0
        currency = row["currency"] if row else "USD"
        stamp = utcnow()
        for entry in entries:
            amount = round(float(entry["amount"]), 2)
            if amount == 0:
                continue
            balance = round(balance + amount, 2)
            con.execute(
                "insert into ledger_entry(id, flight_record_id, settlement_id, entry_type, amount, "
                "balance_after, currency, description, created_at) values(?,?,?,?,?,?,?,?,?)",
                (new_id(), flight_id, settlement_id, entry["type"], amount, balance, currency,
                 entry.get("description"), stamp))
        con.execute("update ops_profile set balance=?, updated_at=? where id='local'", (balance, stamp))

    # ------------------------------------------------------------------ 结算查询 / 复核
    def settlement(self, settlement_id: str) -> dict[str, Any] | None:
        row = self._one("select * from settlement where id=?", (settlement_id,))
        if not row:
            return None
        for key in ("policy_snapshot_json", "policy_breakdown_json", "breakdown_json"):
            row[key.replace("_json", "")] = _json_load(row.pop(key, None), {})
        row["ledger"] = self._rows(
            "select * from ledger_entry where settlement_id=? order by created_at", (settlement_id,))
        flight = self.db.get_flight(row["flight_record_id"])
        row["flight"] = flight
        return row

    def settlement_for_flight(self, flight_record_id: str) -> dict[str, Any] | None:
        row = self._one("select id from settlement where flight_record_id=?", (flight_record_id,))
        return self.settlement(row["id"]) if row else None

    def settlements(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        where, args = "", []
        if status:
            where = " where s.status=?"
            args.append(status.upper())
        rows = self._rows(
            "select s.*, f.callsign, f.dep_icao, f.arr_icao, f.block_off_utc, f.block_minutes, "
            "f.touchdown_vs_fpm, f.landing_rating "
            "from settlement s left join flight_record f on f.id=s.flight_record_id" + where +
            " order by s.computed_at desc limit ?", (*args, limit))
        for row in rows:
            row["policy_breakdown"] = _json_load(row.pop("policy_breakdown_json", None), {})
            row["policy_snapshot"] = _json_load(row.pop("policy_snapshot_json", None), {})
            row["breakdown"] = _json_load(row.pop("breakdown_json", None), {})
        return rows

    def review_queue(self) -> list[dict[str, Any]]:
        rows = self.settlements(limit=200, status="HELD")
        return rows

    def resolve_review(self, settlement_id: str, action: str, note: str | None = None,
                       payout_factor: float | None = None) -> dict[str, Any]:
        settlement = self.settlement(settlement_id)
        if not settlement:
            raise OpsError("NOT_FOUND", "结算不存在")
        if settlement["status"] != "HELD":
            raise OpsError("INVALID_STATE", "只有 HELD 的结算需要复核")
        action = (action or "").upper()
        if action not in ("ACCEPT", "WEIGHTED", "REJECT"):
            raise OpsError("VALIDATION", "复核动作只能是 ACCEPT / WEIGHTED / REJECT")
        flight = settlement.get("flight") or {}
        result = self.settle_flight(flight, review_action=action, review_note=note,
                                    force=True) if flight else None
        if result is None:
            raise OpsError("NOT_FOUND", "飞行记录不存在")
        if payout_factor is not None:
            # 允许手工覆盖系数（0–1），写审计
            with self._tx() as con:
                con.execute("update settlement set payout_factor=?, updated_at=? where id=?",
                            (float(payout_factor), utcnow(), settlement_id))
                self._audit(con, "REVIEW_FACTOR_OVERRIDE", "settlement", settlement_id,
                            settlement.get("payout_factor"), payout_factor, note)
        return self.settlement(settlement_id) or {}

    # ------------------------------------------------------------------ 账本 / 看板
    def ledger(self, limit: int = 200) -> dict[str, Any]:
        rows = self._rows("select * from ledger_entry order by created_at desc limit ?", (limit,))
        totals: dict[str, float] = {}
        for row in self._rows("select entry_type, sum(amount) as total from ledger_entry group by entry_type"):
            totals[row["entry_type"]] = round(float(row["total"] or 0), 2)
        profile = self.profile() or {}
        summed = round(sum(totals.values()), 2)
        return {
            "balance": profile.get("balance"), "currency": profile.get("currency", "USD"),
            "items": rows, "totals": totals,
            "ledger_sum": summed,
            "reconciled": abs(summed - float(profile.get("balance") or 0)) < 0.01,
        }

    def finance_summary(self) -> dict[str, Any]:
        """财务统计：总计 + 本周/本月/今年 + 近 6 个月（只看结算，不算账户余额）。"""
        profile = self.profile() or {}
        now = _now()
        day = now.date()
        week_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) \
            - timedelta(days=day.weekday())
        month_start = datetime(day.year, day.month, 1, tzinfo=timezone.utc)
        year_start = datetime(day.year, 1, 1, tzinfo=timezone.utc)
        rows = self._rows(
            "select status, revenue_total, cost_total, profit, computed_at from settlement "
            "where status in ('SETTLED','HELD')")
        settled = [r for r in rows if (r.get("status") or "").upper() == "SETTLED"]

        def bucket(items: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "flights": len(items),
                "revenue": round(sum(float(i.get("revenue_total") or 0) for i in items), 2),
                "cost": round(sum(float(i.get("cost_total") or 0) for i in items), 2),
                "profit": round(sum(float(i.get("profit") or 0) for i in items), 2),
            }

        def since(start: datetime) -> list[dict[str, Any]]:
            stamp = _iso(start)
            return [r for r in settled if (r.get("computed_at") or "") >= stamp]

        months: dict[str, list[dict[str, Any]]] = {}
        for row in settled:
            key = (row.get("computed_at") or "")[:7]
            months.setdefault(key, []).append(row)
        monthly = []
        for offset in range(5, -1, -1):
            year = day.year
            month = day.month - offset
            while month <= 0:
                month += 12
                year -= 1
            key = f"{year:04d}-{month:02d}"
            monthly.append({"month": key, **bucket(months.get(key, []))})
        return {
            "currency": profile.get("currency", "USD"),
            "totals": bucket(settled),
            "held": len(rows) - len(settled),
            "periods": [
                {"key": "WEEK", "start": _iso(week_start), **bucket(since(week_start))},
                {"key": "MONTH", "start": _iso(month_start), **bucket(since(month_start))},
                {"key": "YEAR", "start": _iso(year_start), **bucket(since(year_start))},
            ],
            "monthly": monthly,
        }

    def dashboard(self) -> dict[str, Any]:
        self._expire_locks()
        self._ensure_schedule_inventory()
        profile = self.profile() or {}
        fleet = self.list_fleet()
        active_roster = self.current_roster()
        free = self.current_free_flight()
        today = utcnow()[:10]
        today_rows = self._rows(
            "select count(*) as n, coalesce(sum(revenue_total),0) as revenue, "
            "coalesce(sum(cost_total),0) as cost, coalesce(sum(profit),0) as profit "
            "from settlement where substr(computed_at,1,10)=?", (today,))
        today_stats = today_rows[0] if today_rows else {}
        review = self._one("select count(*) as n from settlement where status='HELD'")
        scheduled = self._one("select count(*) as n from flight_instance where status='SCHEDULED'")
        return {
            "profile": profile,
            "fleet": {
                "total": len(fleet),
                "active": sum(1 for a in fleet if a["status"] == "ACTIVE"),
                "held": sum(1 for a in fleet if a["status"] == "HELD"),
                "in_flight": sum(1 for a in fleet if a["status"] == "IN_FLIGHT"),
                "maintenance": sum(1 for a in fleet if a["status"] == "MAINTENANCE"),
            },
            "active_roster": active_roster,
            "active_free_flight": free,
            "active_task": self.active_task(),
            "today": {
                "settlements": int(today_stats.get("n") or 0),
                "revenue": round(float(today_stats.get("revenue") or 0), 2),
                "cost": round(float(today_stats.get("cost") or 0), 2),
                "profit": round(float(today_stats.get("profit") or 0), 2),
            },
            "review_count": int((review or {}).get("n") or 0),
            "scheduled_instances": int((scheduled or {}).get("n") or 0),
            "no_show_count": int(self._meta_get(NO_SHOW_KEY, 0) or 0),
            "config_version": int((self._one("select max(version) as v from ops_config_version") or {}).get("v") or 0),
        }

    def audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._rows("select * from ops_audit order by created_at desc limit ?", (limit,))
        for row in rows:
            row["before"] = _json_load(row.pop("before_json", None), None)
            row["after"] = _json_load(row.pop("after_json", None), None)
        return rows

    # ------------------------------------------------------------------ 维护
    def _ensure_schedule_inventory(self) -> None:
        """每天首次打开时补生成未来 7 天实例（等同 docs/04 §10.4 的每日 00:00 任务）。"""
        if self._tx_depth:
            return
        today = utcnow()[:10]
        if self._meta_get("last_instance_gen") == today:
            return
        try:
            self.generate_instances(days=7)
            self._meta_set("last_instance_gen", today)
        except Exception:  # noqa: BLE001
            return

    def _expire_locks(self) -> None:
        if self._tx_depth or self._expiring:
            return
        self._expiring = True
        now = utcnow()
        try:
            rosters = self._rows("select id from roster where status='LOCKED' and expires_at < ?", (now,))
            for row in rosters:
                self.expire_roster(row["id"])
            frees = self._rows("select id from free_flight where status='LOCKED' and lock_expires_at < ?",
                               (now,))
            for row in frees:
                with self._tx() as con:
                    free = con.execute("select * from free_flight where id=?", (row["id"],)).fetchone()
                    if not free:
                        continue
                    con.execute("update free_flight set status='EXPIRED', updated_at=? where id=?",
                                (now, row["id"]))
                    if free["flight_instance_id"]:
                        con.execute("update flight_instance set status='SCHEDULED', "
                                    "assigned_aircraft_id=NULL, updated_at=? where id=?",
                                    (now, free["flight_instance_id"]))
                    con.execute("update aircraft_lock set status='EXPIRED', released_at=? "
                                "where free_flight_id=?", (now, row["id"]))
                    con.execute("update aircraft set status='ACTIVE', updated_at=?, version=version+1 "
                                "where id=?", (now, free["aircraft_id"]))
        except Exception:  # noqa: BLE001
            return
        finally:
            self._expiring = False

    def reset(self) -> dict[str, Any]:
        """危险操作：清空运营数据并重新种演示数据（保留个人模式日志与轨迹）。"""
        tables = ("ledger_entry", "settlement", "load_sheet", "economy_snapshot", "roster_leg",
                  "roster", "free_flight", "aircraft_lock", "flight_instance", "schedule_template",
                  "ops_route", "aircraft", "ops_config_history", "ops_config_version", "ops_config",
                  "ops_audit", "ops_meta")
        with self._tx() as con:
            for table in tables:
                con.execute(f"delete from {table}")
            con.execute("delete from ops_profile")
        self._seed_profile()
        return self.seed_demo()


def _valid_hhmm(value: str) -> bool:
    try:
        hour, minute = (int(x) for x in value.strip().split(":")[:2])
    except (ValueError, AttributeError):
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59
