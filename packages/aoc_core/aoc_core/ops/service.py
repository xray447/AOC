"""M2 单机运营服务：机队、航线/班期、抽班、自由飞、配载、结算、账本、规则版本。

全部逻辑在本机 SQLite 内完成（无服务端、无账号、无公司实体）。
API 层只做参数校验与序列化。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import random
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
    title_keywords,
)

CONSTRAINT_LIMITS = {
    "window_hours": (1, 168, 24),
    "max_legs": (1, 8, 3),
    # 「合计」航时：整条班表所有航段之和
    "max_block_minutes": (30, 1440, 480),
    # 「每程」航时区间：单段的最短/最长飞行时间
    "min_leg_block_minutes": (5, 1440, 30),
    "max_leg_block_minutes": (10, 1440, 480),
    "min_turnaround_min": (15, 240, 45),
    "max_turnaround_min": (30, 1440, 360),
}
FREE_LOCK_MINUTES = 30
FREE_DEP_OFFSET_MINUTES = 50
# 不遵循航线时：首段最早起飞偏移、每个航点最多评估的候选机场数、每个出发点最多评估的分支数
VIRTUAL_FIRST_DEPART_MINUTES = 60
VIRTUAL_POOL_LIMIT = 160
VIRTUAL_BRANCH_LIMIT = 10
# 自定义机型模板：可编辑字段与「机型参数」范围（docs/04 §7）
TYPE_FIELDS = (
    "icao", "variant", "name", "manufacturer", "role", "demand_profile",
    "pax_capacity", "cabin_config_json", "cargo_capacity_kg",
    "oew_kg", "mzfw_kg", "mlw_kg", "mtow_kg", "fuel_capacity_kg", "fuel_burn_kg_h",
    "cruise_speed_kt", "cruise_fl", "min_runway_m", "wingspan_m", "range_nm",
    "lease_per_hour", "charter_rate_per_hour", "fare_multiplier",
    "allow_scheduled", "allow_charter", "engine_count", "engine_type",
    "wake_category", "title_keyword",
)
TYPE_ROLES = ("AIRLINER", "BIZJET", "VIP", "CARGO")
TYPE_DEMAND_PROFILES = ("MASS", "BIZJET", "CARGO", "NONE")
CABIN_KEYS = ("first", "business", "premium_economy", "economy")
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


def candidate_score(*, utilization: float, new_airports: int, profit: float,
                    block_minutes: list[int], leg_count: int, max_legs: int,
                    random_part: float, prefer_new_airports: bool) -> float:
    """候选评分（docs/TODO §24）。

    旧口径的两个偏差：`balance` 单段恒为 1.0（多段只要一段短就被拉低）、
    `profit_norm = max(0, ...)` 让亏损长航线靠利用率拿第一。现在：
    - 新机场按绝对数量给分（单段最多 2 个新机场，不再「新机场/段数」拿满分）；
    - 亏损按金额扣分；
    - 单段均衡基准降到 0.6，多段按航时离散度给分；
    - 单独给「段数」加分，避免 478 min 单段永远压过 464 min 多段链。
    """
    utilization = min(1.0, max(0.0, utilization))
    novelty = min(1.0, new_airports / 3.0)
    profit_norm = min(1.0, max(0.0, profit) / 50000.0)
    loss_penalty = 0.0 if profit >= 0 else min(0.35, abs(profit) / 200000.0)
    balance = 0.6
    if leg_count > 1 and block_minutes and statistics.mean(block_minutes) > 0:
        balance = max(0.0, 1.0 - statistics.pstdev(block_minutes) / statistics.mean(block_minutes))
    leg_credit = min(1.0, leg_count / max(1, max_legs))
    weights = ((0.30, 0.25, 0.15, 0.10, 0.15, 0.05) if prefer_new_airports
               else (0.30, 0.15, 0.25, 0.10, 0.15, 0.05))
    total = sum(weights)
    return (weights[0] * utilization + weights[1] * novelty + weights[2] * profit_norm
            + weights[3] * balance + weights[4] * leg_credit
            + weights[5] * random_part) / total - loss_penalty


def _simbrief_payload(*, dep: str | None = None, arr: str | None = None,
                      aircraft_type: str | None = None, callsign: str | None = None,
                      registration: str | None = None,
                      sheet: dict[str, Any] | None = None) -> dict[str, Any]:
    """SimBrief 预填参数：机场/机型/呼号/注册号，有配载单时再带上旅客与 ZFW。

    链接里只传 `airline`+`fltnum` 与 `manualzfw`（千磅）；`pax` 仅用于界面展示。
    """
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


def _actual_zfw(value: Any) -> float | None:
    """把前端/SimVar 传上来的实际 ZFW 转成 kg；非法值返回 None。"""
    if value is None or value == "":
        return None
    try:
        actual = float(value)
    except (TypeError, ValueError):
        return None
    return round(actual, 1) if actual > 0 else None


def zfw_check(actual_zfw_kg: Any, planned_zfw_kg: Any) -> tuple[float | None, float | None, list[str]]:
    """实际 ZFW 与配载单比对：返回 (实际值, 差异, 警告)。偏低只提示，不阻断开始。"""
    actual = _actual_zfw(actual_zfw_kg)
    try:
        planned = float(planned_zfw_kg) if planned_zfw_kg else None
    except (TypeError, ValueError):
        planned = None
    if actual is None:
        return None, None, []
    if not planned:
        return actual, None, []
    delta = round(actual - planned, 1)
    warnings: list[str] = []
    if delta < 0:
        warnings.append(
            f"实际 ZFW {actual:.0f} kg 低于配载单 {planned:.0f} kg（少 {abs(delta):.0f} kg），"
            "可能漏装旅客/货物")
    return actual, delta, warnings


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
        """写事务；事务内禁止再做会写库的维护动作（如过期清理）。

        底层用 `Database.session()`：每线程常驻连接 + 可重入事务（最外层提交）。
        """
        self._tx_depth += 1
        try:
            with self.db.session() as con:
                yield con
        finally:
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
        source = "CUSTOM" if str(item.get("source") or "").upper() == "CUSTOM" else "BUILTIN"
        con.execute(
            "insert or ignore into aircraft_type(id, icao, variant, source, builtin_key, title_keyword, "
            "name, manufacturer, role, cabin_config_json, pax_capacity, cargo_capacity_kg, mtow_kg, "
            "mzfw_kg, mlw_kg, oew_kg, fuel_capacity_kg, cruise_speed_kt, cruise_fl, fuel_burn_kg_h, "
            "min_runway_m, wingspan_m, range_nm, engine_count, engine_type, wake_category, demand_profile, "
            "allow_scheduled, allow_charter, charter_rate_per_hour, fare_multiplier, lease_per_hour, "
            "created_at) "
            "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (type_id, item["icao"], item.get("variant", "STANDARD"), source,
             item.get("builtin_key") or (f"{item['icao']}:{item.get('variant', 'STANDARD')}"
                                         if source == "BUILTIN" else None),
             item.get("title_keyword"), item.get("name"),
             item.get("manufacturer"), item.get("role", "AIRLINER"),
             json.dumps(item.get("cabin_config_json") or {}, ensure_ascii=False),
             int(item.get("pax_capacity") or 0), float(item.get("cargo_capacity_kg") or 0),
             float(item.get("mtow_kg") or 0), float(item.get("mzfw_kg") or 0),
             float(item.get("mlw_kg") or 0), float(item.get("oew_kg") or 0),
             float(item.get("fuel_capacity_kg") or 0), float(item.get("cruise_speed_kt") or 440),
             int(item.get("cruise_fl") or 350), float(item.get("fuel_burn_kg_h") or 2400),
             int(item.get("min_runway_m") or 1600), float(item.get("wingspan_m") or 0),
             float(item.get("range_nm") or 3000),
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
            self._parse_type_row(row)
        return rows

    @staticmethod
    def _parse_type_row(row: dict[str, Any]) -> dict[str, Any]:
        row["cabin_config_json"] = _json_load(row.get("cabin_config_json"), {})
        row["allow_scheduled"] = bool(row.get("allow_scheduled"))
        row["allow_charter"] = bool(row.get("allow_charter"))
        row["source"] = (row.get("source") or "BUILTIN").upper()
        return row

    def get_type(self, type_id: str) -> dict[str, Any] | None:
        row = self._one("select * from aircraft_type where id=?", (type_id,))
        return self._parse_type_row(row) if row else None

    def _type_payload(self, data: dict[str, Any], before: dict[str, Any] | None = None
                      ) -> dict[str, Any]:
        """校验并补全机型参数：非法值一律 PARAM_OUT_OF_RANGE（带 `key` 供前端就地高亮）。"""
        merged: dict[str, Any] = {key: (before or {}).get(key) for key in TYPE_FIELDS}
        for key, value in (data or {}).items():
            if key in TYPE_FIELDS and value is not None:
                merged[key] = value

        icao = str(merged.get("icao") or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{2,5}", icao):
            raise OpsError("PARAM_OUT_OF_RANGE", "机型 ICAO 代码必须是 2–5 位字母/数字",
                           {"key": "icao"})
        variant = (str(merged.get("variant") or "STANDARD").strip().upper() or "STANDARD")[:16]
        role = str(merged.get("role") or "AIRLINER").strip().upper()
        if role not in TYPE_ROLES:
            raise OpsError("VALIDATION", "机型角色只能是 AIRLINER / BIZJET / VIP / CARGO")
        demand = str(merged.get("demand_profile")
                     or ("BIZJET" if role == "BIZJET" else "MASS")).strip().upper()
        if demand not in TYPE_DEMAND_PROFILES:
            raise OpsError("VALIDATION", "需求类型只能是 MASS / BIZJET / CARGO / NONE")

        def number(key: str, lo: float, hi: float, default: float, label: str) -> float:
            raw = merged.get(key)
            if raw is None or raw == "":
                value = float(default)
            else:
                try:
                    value = float(raw)
                except (TypeError, ValueError) as exc:
                    raise OpsError("VALIDATION", f"{label}必须是数字", {"key": key}) from exc
            if value < lo or value > hi:
                raise OpsError("PARAM_OUT_OF_RANGE", f"{label}超出范围 {lo:g}–{hi:g}",
                               {"key": key})
            return value

        cabin_raw = merged.get("cabin_config_json")
        cabin = _json_load(cabin_raw, {}) if isinstance(cabin_raw, (str, dict)) else {}
        if not isinstance(cabin, dict):
            cabin = {}
        cabin_counts: dict[str, int] = {}
        for key in CABIN_KEYS:
            try:
                cabin_counts[key] = max(0, int(float(cabin.get(key) or 0)))
            except (TypeError, ValueError) as exc:
                raise OpsError("VALIDATION", f"客舱构型 {key} 必须是整数",
                               {"key": "cabin_config_json"}) from exc
        cabin_sum = sum(cabin_counts.values())
        pax_raw = merged.get("pax_capacity")
        has_pax = pax_raw not in (None, "")
        pax = int(number("pax_capacity", 0, 900, cabin_sum, "座位数"))
        if not cabin_sum and pax:
            cabin_counts = {"first": 0, "business": 0, "premium_economy": 0, "economy": pax}
            cabin_sum = pax
        if has_pax and pax != cabin_sum:
            raise OpsError("PARAM_OUT_OF_RANGE",
                           f"座位数 {pax} 与客舱构型合计 {cabin_sum} 不一致",
                           {"key": "pax_capacity"})

        for key, label in (("oew_kg", "OEW（空重）"), ("mzfw_kg", "MZFW（最大零油重量）"),
                           ("mtow_kg", "MTOW（最大起飞重量）")):
            if merged.get(key) in (None, ""):
                raise OpsError("VALIDATION", f"{label}必填", {"key": key})
        oew = number("oew_kg", 1, 700_000, 1, "OEW（空重）")
        mzfw = number("mzfw_kg", 1, 700_000, oew, "MZFW（最大零油重量）")
        mlw = number("mlw_kg", 1, 800_000, mzfw, "MLW（最大落地重量）")
        mtow = number("mtow_kg", 1, 900_000, mzfw, "MTOW（最大起飞重量）")
        if not (0 < oew < mzfw <= mtow):
            key = "oew_kg" if oew >= mzfw else "mzfw_kg"
            raise OpsError("PARAM_OUT_OF_RANGE", "重量必须满足 0 < OEW < MZFW ≤ MTOW",
                           {"key": key})
        if mlw > mtow:
            raise OpsError("PARAM_OUT_OF_RANGE", "MLW 不能大于 MTOW", {"key": "mlw_kg"})

        fuel_cap = number("fuel_capacity_kg", 0, 600_000, max(0.0, mtow - oew), "燃油容量")
        burn = number("fuel_burn_kg_h", 0.1, 30_000, 2400, "油耗")
        speed = number("cruise_speed_kt", 60, 600, 440, "巡航速度")
        cruise_fl = int(number("cruise_fl", 0, 600, 350, "巡航高度层"))
        runway = int(number("min_runway_m", 0, 5000, 1600, "最短跑道"))
        # 翼展缺省按最短跑道推保守值（docs/TODO §26）：36 / 52 / 60.3 / 65 m
        default_wingspan = 36.0 if runway < 1800 else (
            52.0 if runway < 2500 else (60.3 if runway < 3200 else 65.0))
        wingspan = number("wingspan_m", 0, 90, default_wingspan, "翼展")
        if wingspan <= 0:
            wingspan = default_wingspan
        range_nm = number("range_nm", 1, 20_000, 3000, "航程")
        cargo_cap = number("cargo_capacity_kg", 0, 400_000, 0, "货舱容量")
        lease = number("lease_per_hour", 0, 100_000, 2000, "租赁/小时")
        charter = number("charter_rate_per_hour", 0, 200_000,
                         2000 if role == "BIZJET" else 0, "包机/小时")
        fare = number("fare_multiplier", 0.2, 10, 1.0, "票价倍率")
        engine_count = int(number("engine_count", 1, 6, 2, "发动机数量"))

        allow_sched = merged.get("allow_scheduled")
        allow_sched = (role != "BIZJET") if allow_sched is None else bool(allow_sched)
        allow_charter = merged.get("allow_charter")
        allow_charter = True if allow_charter is None else bool(allow_charter)
        return {
            "icao": icao, "variant": variant,
            "name": str(merged.get("name") or icao)[:120],
            "manufacturer": str(merged.get("manufacturer") or "").strip()[:80] or None,
            "role": role, "demand_profile": demand,
            "cabin_config_json": cabin_counts,
            "pax_capacity": int(pax if has_pax else cabin_sum),
            "cargo_capacity_kg": round(cargo_cap, 1),
            "oew_kg": round(oew, 1), "mzfw_kg": round(mzfw, 1),
            "mlw_kg": round(mlw, 1), "mtow_kg": round(mtow, 1),
            "fuel_capacity_kg": round(fuel_cap, 1),
            "fuel_burn_kg_h": round(burn, 1),
            "cruise_speed_kt": round(speed, 1), "cruise_fl": cruise_fl,
            "min_runway_m": runway, "wingspan_m": round(wingspan, 1),
            "range_nm": round(range_nm, 1),
            "engine_count": engine_count,
            "engine_type": (str(merged.get("engine_type") or "JET").strip().upper() or "JET")[:8],
            "wake_category": (str(merged.get("wake_category") or "M").strip().upper() or "M")[:2],
            "allow_scheduled": allow_sched,
            "allow_charter": allow_charter,
            "charter_rate_per_hour": round(charter, 2),
            "fare_multiplier": round(fare, 2),
            "lease_per_hour": round(lease, 2),
            "title_keyword": str(merged.get("title_keyword") or "").strip()[:80] or None,
            "created_at": (before or {}).get("created_at") or utcnow(),
        }

    def create_type(self, data: dict[str, Any]) -> dict[str, Any]:
        """新增自定义机型模板（source=CUSTOM）；内置模板不可改，只能复制一份再改。"""
        payload = self._type_payload(data)
        if self._one("select id from aircraft_type where upper(icao)=? and upper(variant)=?",
                     (payload["icao"], payload["variant"])):
            raise OpsError("DUPLICATE_TYPE",
                           f"机型 {payload['icao']} {payload['variant']} 已存在")
        payload["source"] = "CUSTOM"
        payload["builtin_key"] = None
        with self._tx() as con:
            type_id = self._insert_type(con, payload)
            self._audit(con, "AIRCRAFT_TYPE_ADD", "aircraft_type", type_id, None, payload)
        return self.get_type(type_id) or {}

    def update_type(self, type_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        before = self.get_type(type_id)
        if not before:
            raise OpsError("NOT_FOUND", "机型不存在")
        if before["source"] != "CUSTOM":
            raise OpsError("BUILTIN_TYPE_READONLY",
                           "内置机型不可修改：请用「从现有模板复制」建一个自定义机型再改",
                           {"type_id": type_id})
        payload = self._type_payload(patch, before)
        if self._one("select id from aircraft_type where upper(icao)=? and upper(variant)=? "
                     "and id<>?", (payload["icao"], payload["variant"], type_id)):
            raise OpsError("DUPLICATE_TYPE",
                           f"机型 {payload['icao']} {payload['variant']} 已存在")
        with self._tx() as con:
            con.execute(
                "update aircraft_type set icao=?, variant=?, name=?, manufacturer=?, role=?, "
                "cabin_config_json=?, pax_capacity=?, cargo_capacity_kg=?, mtow_kg=?, mzfw_kg=?, "
                "mlw_kg=?, oew_kg=?, fuel_capacity_kg=?, cruise_speed_kt=?, cruise_fl=?, "
                "fuel_burn_kg_h=?, min_runway_m=?, wingspan_m=?, range_nm=?, engine_count=?, engine_type=?, "
                "wake_category=?, demand_profile=?, allow_scheduled=?, allow_charter=?, "
                "charter_rate_per_hour=?, fare_multiplier=?, lease_per_hour=?, title_keyword=? "
                "where id=?",
                (payload["icao"], payload["variant"], payload["name"], payload["manufacturer"],
                 payload["role"], json.dumps(payload["cabin_config_json"], ensure_ascii=False),
                 payload["pax_capacity"], payload["cargo_capacity_kg"], payload["mtow_kg"],
                 payload["mzfw_kg"], payload["mlw_kg"], payload["oew_kg"],
                 payload["fuel_capacity_kg"], payload["cruise_speed_kt"], payload["cruise_fl"],
                 payload["fuel_burn_kg_h"], payload["min_runway_m"], payload["wingspan_m"],
                 payload["range_nm"],
                 payload["engine_count"], payload["engine_type"], payload["wake_category"],
                 payload["demand_profile"], 1 if payload["allow_scheduled"] else 0,
                 1 if payload["allow_charter"] else 0, payload["charter_rate_per_hour"],
                 payload["fare_multiplier"], payload["lease_per_hour"], payload["title_keyword"],
                 type_id))
            self._audit(con, "AIRCRAFT_TYPE_UPDATE", "aircraft_type", type_id, before, payload)
        return self.get_type(type_id) or {}

    def delete_type(self, type_id: str) -> bool:
        """删除自定义机型：内置不可删，仍被机队/班期/未完成实例引用时返回 AIRCRAFT_TYPE_IN_USE。"""
        before = self.get_type(type_id)
        if not before:
            raise OpsError("NOT_FOUND", "机型不存在")
        if before["source"] != "CUSTOM":
            raise OpsError("BUILTIN_TYPE_READONLY", "内置机型不可删除", {"type_id": type_id})
        fleet = self._one("select count(*) as n from aircraft where type_id=?", (type_id,)) or {"n": 0}
        if int(fleet["n"] or 0):
            raise OpsError("AIRCRAFT_TYPE_IN_USE",
                           f"机队里还有 {int(fleet['n'])} 架飞机在用这个机型，先改机型或退役",
                           {"in_fleet": int(fleet["n"])})
        scheduled = self._one(
            "select (select count(*) from schedule_template where aircraft_type_id=?) + "
            "(select count(*) from flight_instance where aircraft_type_id=? and status in "
            "('SCHEDULED','ASSIGNED')) as n", (type_id, type_id)) or {"n": 0}
        if int(scheduled["n"] or 0):
            raise OpsError("AIRCRAFT_TYPE_IN_USE",
                           "还有班期/未完成航班实例在用这个机型", {"in_schedule": int(scheduled["n"])})
        with self._tx() as con:
            con.execute("delete from aircraft_type where id=?", (type_id,))
            self._audit(con, "AIRCRAFT_TYPE_DELETE", "aircraft_type", type_id, before, None)
        return True

    def match_type_by_title(self, title: str | None) -> dict[str, Any] | None:
        """按 SimLink 的 aircraft_title 匹配机型：命中关键词最长的那一个。

        关键词 = 自定义机型的 `title_keyword` + 内置机型的常见写法（specs.TITLE_KEYWORDS）
        + ICAO（"Airbus A320 Neo" 这类标题没有 `737-800` 但常带 ICAO）。
        """
        if not title:
            return None
        needle = str(title).upper()
        best: tuple[int, dict[str, Any]] | None = None
        for item in self.list_types():
            for keyword in title_keywords(item):
                if keyword in needle and (best is None or len(keyword) > best[0]):
                    best = (len(keyword), item)
        return best[1] if best else None

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
        if type_row is None and not type_id:
            # 没选机型时按 SimLink 的 aircraft_title 关键字自动匹配（自定义机型填了 title_keyword 才有用）
            matched = self.match_type_by_title(data.get("aircraft_title"))
            if matched is not None:
                type_row, type_id = matched, matched["id"]
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
        if out["min_leg_block_minutes"] > out["max_leg_block_minutes"]:
            raise OpsError("PARAM_OUT_OF_RANGE", "每程最短航时不能大于每程最长航时",
                           {"key": "min_leg_block_minutes"})
        base = (req.get("base_airport") or "").strip().upper() or None
        out["base_airport"] = base
        out["aircraft_type_id"] = req.get("aircraft_type_id") or None
        out["registration"] = (req.get("registration") or "").strip().upper() or None
        out["prefer_new_airports"] = bool(req.get("prefer_new_airports", True))
        # 遵循航线（默认）：候选只来自已有的航线+班期；关掉后用 navdata 机场库任意组合
        out["follow_routes"] = bool(req.get("follow_routes", True))
        excluded = req.get("excluded_airports") or []
        if isinstance(excluded, str):
            excluded = excluded.split(",")
        out["excluded_airports"] = sorted({
            str(item).strip().upper() for item in excluded
            if re.fullmatch(r"[A-Za-z0-9]{4}", str(item).strip())
        })
        # 抽班用 navdata 机场库时不选军用机场（默认开）；飞机当前所在机场不拦
        out["exclude_military"] = bool(req.get("exclude_military", True))
        # 按跑道宽度推的翼展上限过滤（默认开，关掉回到旧行为）
        out["consider_wingspan"] = bool(req.get("consider_wingspan", True))
        return out

    def _available_instances(self, start: str, end: str,
                             excluded: set[str] | None = None) -> list[dict[str, Any]]:
        rows = self._rows(
            "select * from flight_instance where status='SCHEDULED' "
            "and scheduled_dep_utc >= ? and scheduled_dep_utc <= ? order by scheduled_dep_utc",
            (start, end))
        if excluded:
            rows = [r for r in rows
                    if (r["dep_icao"] or "").upper() not in excluded
                    and (r["arr_icao"] or "").upper() not in excluded]
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

        excluded = set(constraints["excluded_airports"])
        by_dep: dict[str, list[dict[str, Any]]] = {}
        instances: list[dict[str, Any]] = []
        if constraints["follow_routes"]:
            instances = self._available_instances(
                _iso(now - timedelta(minutes=15)), _iso(window_end), excluded)
            instances = [i for i in instances if (i.get("mission_type") or "SCHEDULED") != "CHARTER"]
            for item in instances:
                by_dep.setdefault(item["dep_icao"].upper(), []).append(item)
            for items in by_dep.values():
                items.sort(key=lambda x: x["scheduled_dep_utc"])

        visited = self._visited_airports()
        candidates: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        # 不遵循航线时候选完全由随机池生成：跨飞机也按机场对去重，避免三个候选同一条路线
        route_seen: set[tuple[Any, ...]] = set()
        # 不遵循航线时同一出发点会被多次评估：机场池缓存一次，避免重复扫 navdata
        pool_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for ac in aircraft:
            ac_type = types.get(ac["type_id"]) or {}
            if constraints["follow_routes"]:
                chains = self._build_chains(ac, ac_type, by_dep, constraints, now, window_end,
                                            excluded)
                if not chains and str(ac_type.get("source") or "").upper() == "CUSTOM":
                    # 自定义机型在班期里没有同名机型：放宽机型匹配，只要航程/跑道放得下
                    # 就允许「机型替换」。内置机型仍走严格匹配（默认路径零回归）。
                    chains = self._build_chains(ac, ac_type, by_dep, constraints, now, window_end,
                                                excluded, lenient_types=True)
            else:
                chains = self._virtual_chains(ac, ac_type, constraints, now, window_end,
                                              pool_cache)
            for chain in chains[:24]:
                # 同机同航线形状只保留一个（避免三个候选都是同一航班的不同日期）；
                # 遵循航线时也要跨飞机按航线形状去重（旧逻辑只在虚拟航段生效）
                route_shape = tuple((leg["dep_icao"], leg["arr_icao"]) for leg in chain)
                shape = (ac["id"], route_shape)
                if shape in seen or route_shape in route_seen:
                    continue
                seen.add(shape)
                route_seen.add(route_shape)
                candidate = self._candidate(ac, ac_type, chain, constraints, visited, types)
                if candidate:
                    candidates.append(candidate)
        candidates.sort(key=lambda c: c["score"], reverse=True)
        top = self._select_top(candidates, 3)
        token = self._sign({
            "aircraft_id": None,
            "candidates": [{
                "aircraft_id": c["aircraft"]["id"],
                # 航班实例为空 = 关掉「遵循航线」时生成的虚拟航段，确认时再落一次性实例
                "instance_ids": [leg["flight_instance_id"] for leg in c["legs"]],
                "virtual_legs": [{
                    "dep": leg["dep"], "arr": leg["arr"],
                    "scheduled_dep_utc": leg["scheduled_dep_utc"],
                    "scheduled_arr_utc": leg["scheduled_arr_utc"],
                } for leg in c["legs"] if leg.get("virtual")],
            } for c in top],
            "constraints": constraints,
            "exp": _iso(now + timedelta(seconds=CANDIDATE_TTL_SECONDS)),
        })
        for item in top:
            item["candidate_token"] = token
        result = {
            "candidates": top,
            "constraints": constraints,
            "expires_at": _iso(now + timedelta(seconds=CANDIDATE_TTL_SECONDS)),
            "considered": len(candidates),
            "follow_routes": constraints["follow_routes"],
            "excluded_airports": constraints["excluded_airports"],
        }
        if not top:
            result["reason"] = self._no_candidate_reason(
                aircraft, types, instances, constraints)
        return result

    @staticmethod
    def _select_top(candidates: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
        """top-N 去重：同一架飞机最多 1 条、航线形状互不相同。

        旧逻辑直接取评分前 3：实测 top3 全是同一架 A359 的同一起飞时刻、同为向西单段，
        或者两班只差机尾（起降机场与时刻完全相同），看起来像同一个候选。
        """
        picked: list[dict[str, Any]] = []
        used_aircraft: set[str] = set()
        used_shapes: set[tuple[Any, ...]] = set()
        for candidate in candidates:
            aircraft_id = candidate["aircraft"]["id"]
            if aircraft_id in used_aircraft:
                continue
            shape = tuple((leg["dep"], leg["arr"]) for leg in candidate["legs"])
            if shape in used_shapes:
                continue
            used_aircraft.add(aircraft_id)
            used_shapes.add(shape)
            picked.append(candidate)
            if len(picked) >= limit:
                break
        return picked

    def _build_chains(self, aircraft: dict[str, Any], ac_type: dict[str, Any],
                      by_dep: dict[str, list[dict[str, Any]]], constraints: dict[str, Any],
                      now: datetime, window_end: datetime,
                      excluded: set[str] | None = None,
                      lenient_types: bool = False) -> list[list[dict[str, Any]]]:
        start = (aircraft.get("current_airport_icao") or "").upper()
        min_turn = timedelta(minutes=constraints["min_turnaround_min"])
        max_turn = timedelta(minutes=constraints["max_turnaround_min"])
        max_block = constraints["max_block_minutes"]
        min_leg = constraints["min_leg_block_minutes"]
        max_leg = constraints["max_leg_block_minutes"]
        max_legs = constraints["max_legs"]
        excluded = excluded or set()
        results: list[list[dict[str, Any]]] = []

        def walk(position: str, earliest: datetime, latest: datetime | None,
                 chain: list[dict[str, Any]], block_total: int) -> None:
            if chain:
                results.append(list(chain))
            if len(chain) >= max_legs or len(results) > 200:
                return
            for inst in by_dep.get(position, []):
                dep_icao = (inst.get("dep_icao") or "").upper()
                arr_icao = (inst.get("arr_icao") or "").upper()
                if dep_icao in excluded or arr_icao in excluded:
                    continue
                dep_dt = eco.parse_utc(inst["scheduled_dep_utc"])
                if dep_dt < earliest or dep_dt > window_end:
                    continue
                if latest is not None and dep_dt > latest:
                    continue
                type_id = inst.get("aircraft_type_id")
                if type_id and type_id != aircraft["type_id"]:
                    if not lenient_types or not self._can_operate(inst, ac_type):
                        continue
                block = self._instance_block(inst, ac_type)
                # 每程航时区间（与「合计」max_block 是两个维度）
                if block < min_leg or block > max_leg:
                    continue
                if block_total + block > max_block:
                    continue
                arr_dt = eco.parse_utc(inst["scheduled_arr_utc"]) if inst.get("scheduled_arr_utc") else (
                    dep_dt + timedelta(minutes=block))
                chain.append(inst)
                walk(arr_icao, arr_dt + min_turn, arr_dt + max_turn,
                     chain, block_total + block)
                chain.pop()

        walk(start, now - timedelta(minutes=15), None, [], 0)
        # 优先更长的链（利用率）与更早的时间
        results.sort(key=lambda c: (-len(c), c[0]["scheduled_dep_utc"]))
        return results

    # ------------------------------------------------------- 不遵循航线（虚拟航段）
    def _airport_pool(self, origin: str, ac_type: dict[str, Any],
                      constraints: dict[str, Any], rng) -> list[dict[str, Any]]:
        """从 navdata 机场库里挑「从 origin 起飞、机型能落」的机场（不依赖航线/班期）。

        先用经纬度包围盒过滤，再算大圆距离；结果按种子打乱，保证同条件可复现又有多样性。
        """
        nav = self.nav
        if nav is None:
            return []
        origin_meta = eco.airport_meta(nav, origin)
        if not origin_meta.get("known"):
            return []
        max_range = float(ac_type.get("range_nm") or 3000) * 0.9
        if max_range <= 0:
            return []
        min_runway = float(ac_type.get("min_runway_m") or 0)
        min_block = constraints["min_leg_block_minutes"]
        max_block_leg = constraints["max_leg_block_minutes"]
        speed = float(ac_type.get("cruise_speed_kt") or 440)
        excluded = set(constraints["excluded_airports"])
        exclude_military = bool(constraints.get("exclude_military", True))
        wingspan = float(ac_type.get("wingspan_m") or 0)
        check_wingspan = bool(constraints.get("consider_wingspan", True)) and wingspan > 0
        lat0, lon0 = float(origin_meta["lat"]), float(origin_meta["lon"])
        dlat = max_range / 60.0
        dlon = max_range / (60.0 * max(0.15, math.cos(math.radians(lat0))))
        out: list[dict[str, Any]] = []
        for info in nav.airports.values():
            icao = info.get("ident")
            if not icao or icao == origin or icao in excluded:
                continue
            if exclude_military and info.get("military"):
                continue   # 军用机场不进候选（出发机场不拦）
            if abs(float(info["lat"]) - lat0) > dlat or abs(float(info["lon"]) - lon0) > dlon:
                continue
            runway = info.get("longest_runway_m")
            if min_runway and runway and float(runway) < min_runway:
                continue
            if min_runway >= 1800 and not runway:
                continue   # 机型要长跑道但该机场没有跑道数据：不冒险
            if check_wingspan:
                limit = nav.max_wingspan_m(icao)
                if limit is not None and wingspan > limit:
                    continue   # 跑道太窄：宽体不能落
            distance = eco.gcd_nm(origin_meta, {"lat": info["lat"], "lon": info["lon"]})
            if distance < 25 or distance > max_range:
                continue
            block = eco.estimate_block_minutes(distance, speed)
            if block < min_block or block > max_block_leg:
                continue
            out.append({"icao": icao, "distance_nm": round(distance, 1),
                        "block_minutes": max(1, int(round(block)))})
        rng.shuffle(out)
        return out[:VIRTUAL_POOL_LIMIT]

    def _virtual_chains(self, aircraft: dict[str, Any], ac_type: dict[str, Any],
                        constraints: dict[str, Any], now: datetime, window_end: datetime,
                        pool_cache: dict[tuple[str, str], list[dict[str, Any]]]
                        ) -> list[list[dict[str, Any]]]:
        """关闭「遵循航线」时的候选链：起飞机场 → navdata 任意机场对（最多 max_legs 段）。"""
        start = (aircraft.get("current_airport_icao") or "").upper()
        if not start:
            return []
        key = json.dumps(constraints, sort_keys=True, ensure_ascii=False)
        rng = eco.seeded_rng(f"{aircraft['id']}|{start}|{key}", "virtual")
        min_turn = timedelta(minutes=constraints["min_turnaround_min"])
        max_block = constraints["max_block_minutes"]
        max_legs = constraints["max_legs"]
        results: list[list[dict[str, Any]]] = []

        def walk(position: str, earliest: datetime, chain: list[dict[str, Any]],
                 block_total: int) -> None:
            if chain:
                results.append(list(chain))
            if len(chain) >= max_legs or len(results) > 60:
                return
            # 每架飞机/出发点一份池：不同飞机的随机顺序不同，候选才不会完全一样
            cache_key = (str(aircraft.get("id")), position)
            if cache_key not in pool_cache:
                pool_cache[cache_key] = self._airport_pool(position, ac_type, constraints, rng)
            for dest in pool_cache[cache_key][:VIRTUAL_BRANCH_LIMIT]:
                if dest["icao"] in {c["dep_icao"] for c in chain}:
                    continue
                block = dest["block_minutes"]
                if block_total + block > max_block:
                    continue
                dep_dt = earliest
                if dep_dt > window_end:
                    continue
                arr_dt = dep_dt + timedelta(minutes=block)
                leg = {
                    "id": None, "virtual": True, "route_id": None,
                    "schedule_id": None, "aircraft_type_id": aircraft["type_id"],
                    "flight_number": "", "mission_type": "FREE",
                    "dep_icao": position, "arr_icao": dest["icao"],
                    "scheduled_dep_utc": _iso(dep_dt),
                    "scheduled_arr_utc": _iso(arr_dt),
                }
                chain.append(leg)
                walk(dest["icao"], arr_dt + min_turn, chain, block_total + block)
                chain.pop()

        # 起飞时刻按飞机随机错开 0–120 min：否则同一窗口内所有候选都是同一时刻
        first_dep = now + timedelta(
            minutes=VIRTUAL_FIRST_DEPART_MINUTES + rng.randrange(0, 120))
        walk(start, first_dep, [], 0)
        results.sort(key=lambda c: (-len(c), c[0]["scheduled_dep_utc"]))
        return results

    def _no_candidate_reason(self, aircraft: list[dict[str, Any]],
                             types: dict[str, dict[str, Any]],
                             instances: list[dict[str, Any]],
                             constraints: dict[str, Any]) -> str:
        """抽不到候选时按原因分类提示，避免只显示「无候选」。"""
        if not aircraft:
            return "没有可用飞机：检查机队状态/是否被占用，或放宽机型与基地限制"
        if constraints["follow_routes"] and not instances:
            return "窗口内没有可用航班实例：先加航线+班期并生成班次，或关掉「遵循航线」"
        hints = []
        if constraints["excluded_airports"]:
            hints.append(f"当前排除 {len(constraints['excluded_airports'])} 个机场")
        if constraints.get("exclude_military"):
            hints.append("已排除军用机场")
        if constraints.get("consider_wingspan"):
            hints.append("已按跑道宽度过滤翼展")
        if hints:
            return ("候选被排除机场/军用机场/翼展或跑道宽度/每程航时区间/合计航时或过站时间挡掉了："
                    + "，".join(hints))
        return "候选被每程航时区间/合计航时/过站时间挡掉了：试试放宽这些约束"

    def _can_operate(self, inst: dict[str, Any], ac_type: dict[str, Any]) -> bool:
        """机型替换是否可行：到达机场跑道够长够宽、距离在航程内（0.9 余量）。"""
        arr_meta = eco.airport_meta(self.nav, inst.get("arr_icao"))
        runway = arr_meta.get("runway_m")
        min_runway = float(ac_type.get("min_runway_m") or 0)
        if runway and min_runway and float(runway) < min_runway:
            return False
        wingspan = float(ac_type.get("wingspan_m") or 0)
        limit = arr_meta.get("max_wingspan_m")
        if wingspan and limit is not None and wingspan > float(limit):
            return False
        route = self._one("select distance_nm from ops_route where id=?", (inst.get("route_id"),))
        distance = float((route or {}).get("distance_nm") or 0)
        if not distance:
            distance = eco.gcd_nm(eco.airport_meta(self.nav, inst.get("dep_icao")), arr_meta)
        max_range = float(ac_type.get("range_nm") or 0) * 0.9
        return not (max_range and distance > max_range)

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
        wingspan_limit: int | None = None
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
            seed_id = inst.get("id") or (
                f"{inst['dep_icao']}-{inst['arr_icao']}-{inst.get('scheduled_dep_utc')}")
            sheet = eco.generate_load_sheet(
                dep=inst["dep_icao"], arr=inst["arr_icao"], distance_nm=distance,
                block_minutes=block, aircraft_type=ac_type, params=params,
                seed=f"candidate-{aircraft['id']}-{seed_id}-{index}",
                dep_time_utc=inst["scheduled_dep_utc"], dep_meta=dep_meta, arr_meta=arr_meta,
                repeat_index=0)
            est_revenue += sheet["estimated_revenue"]
            est_cost += sheet["estimated_cost"]
            total_block += block
            total_distance += distance
            block_minutes.append(block)
            airports.update((inst["dep_icao"].upper(), inst["arr_icao"].upper()))
            virtual = bool(inst.get("virtual"))
            # 到达机场的翼展上限（按跑道宽度推断）：候选卡片上标注，让玩家知道是近似值
            leg_limit = arr_meta.get("max_wingspan_m")
            if isinstance(leg_limit, int):
                wingspan_limit = leg_limit if wingspan_limit is None else min(wingspan_limit, leg_limit)
            legs.append({
                "flight_instance_id": inst.get("id"), "flight_number": inst["flight_number"],
                "callsign": self._callsign(inst["flight_number"]) if not virtual else None,
                "dep": inst["dep_icao"], "arr": inst["arr_icao"],
                "scheduled_dep_utc": inst["scheduled_dep_utc"],
                "scheduled_arr_utc": inst["scheduled_arr_utc"], "block_minutes": block,
                "distance_nm": round(distance, 1),
                "estimated_revenue": sheet["estimated_revenue"],
                "max_wingspan_m": leg_limit,
                "virtual": virtual,
            })
        est_profit = est_revenue - est_cost
        new_airports = len({a for a in airports if a not in visited})
        leg_count = len(chain)
        max_block = constraints["max_block_minutes"]
        utilization = total_block / max_block if max_block else 0.0
        seed_tail = chain[0].get("id") or f"{chain[0]['dep_icao']}-{chain[0]['arr_icao']}"
        rng = eco.seeded_rng(f"{aircraft['id']}|{seed_tail}", "score")
        score = candidate_score(
            utilization=utilization, new_airports=new_airports, profit=est_profit,
            block_minutes=block_minutes, leg_count=leg_count,
            max_legs=constraints["max_legs"], random_part=rng.random(),
            prefer_new_airports=bool(constraints["prefer_new_airports"]))
        reasons = [f"机型匹配 {ac_type.get('icao', '')}"]
        if new_airports:
            reasons.append(f"包含 {new_airports} 个未飞机场")
        if leg_count > 1:
            reasons.append(f"{leg_count} 段 · 总过站约 {constraints['min_turnaround_min']}min+")
        reasons.append(f"预计利润 ${est_profit:,.0f}")
        if constraints.get("consider_wingspan") and wingspan_limit is not None \
                and float(ac_type.get("wingspan_m") or 0) > 0:
            reasons.append(
                f"翼展 {float(ac_type['wingspan_m']):.1f} m ≤ 上限 {wingspan_limit} m"
                "（按跑道宽度推断，未含 AIP 等级）")
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
        instance_ids = list(candidate.get("instance_ids") or [])
        virtual_legs = list(candidate.get("virtual_legs") or [])
        now = _now()
        window_end = now + timedelta(hours=int(constraints.get("window_hours") or 24))
        roster_id = new_id()
        stamp = utcnow()
        with self._tx() as con:
            legs: list[dict[str, Any]] = []
            virtual_index = 0
            used_numbers: set[str] = set()
            for instance_id in instance_ids:
                if instance_id:
                    inst = con.execute("select * from flight_instance where id=?",
                                       (instance_id,)).fetchone()
                    if inst is None or inst["status"] != "SCHEDULED":
                        raise OpsError("INSTANCE_UNAVAILABLE", "航班实例已被占用或取消，请重新抽班")
                    legs.append(dict(inst))
                    continue
                # 虚拟航段（不遵循航线）：确认时才落一次性 flight_instance
                if virtual_index >= len(virtual_legs):
                    raise OpsError("INVALID_TOKEN", "候选数据不完整，请重新抽班")
                legs.append(self._create_virtual_instance(
                    con, aircraft, virtual_legs[virtual_index], stamp, used_numbers))
                virtual_index += 1
            if not legs:
                raise OpsError("INVALID_TOKEN", "候选为空，请重新抽班")
            con.execute(
                "insert into roster(id, kind, aircraft_id, status, base_airport_icao, window_start_utc, "
                "window_end_utc, constraints_json, redraw_count, locked_at, expires_at, version, "
                "created_at, updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (roster_id, "ROSTER", aircraft_id, "LOCKED",
                 constraints.get("base_airport") or aircraft.get("current_airport_icao"),
                 _iso(now), _iso(window_end), json.dumps(constraints, ensure_ascii=False),
                 0, stamp, _iso(window_end), 1, stamp, stamp))
            for index, inst in enumerate(legs, start=1):
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
                        {"aircraft": aircraft["registration"], "legs": len(legs),
                         "virtual_legs": len(virtual_legs)})
        return self.roster(roster_id) or {}

    def _create_virtual_instance(self, con, aircraft: dict[str, Any], spec: dict[str, Any],
                                 stamp: str, used_numbers: set[str] | None = None) -> dict[str, Any]:
        """「不遵循航线」的候选航段：落一条无航线/无班期的一次性航班实例。"""
        dep = (spec.get("dep") or "").strip().upper()
        arr = (spec.get("arr") or "").strip().upper()
        dep_utc = spec.get("scheduled_dep_utc")
        if len(dep) != 4 or len(arr) != 4 or dep == arr or not dep_utc:
            raise OpsError("INVALID_TOKEN", "候选航段不合法，请重新抽班")
        prefix = (self.profile() or {}).get("flight_prefix") or "AOC"
        number = self._virtual_flight_number(con, prefix, dep_utc, used_numbers)
        instance_id = new_id()
        con.execute(
            "insert into flight_instance(id, schedule_id, route_id, flight_number, dep_icao, arr_icao, "
            "scheduled_dep_utc, scheduled_arr_utc, aircraft_type_id, mission_type, status, "
            "created_at, updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (instance_id, None, None, number, dep, arr, dep_utc,
             spec.get("scheduled_arr_utc"), aircraft.get("type_id"), "FREE", "SCHEDULED",
             stamp, stamp))
        return {
            "id": instance_id, "virtual": True, "route_id": None, "schedule_id": None,
            "aircraft_type_id": aircraft.get("type_id"), "flight_number": number,
            "mission_type": "FREE", "dep_icao": dep, "arr_icao": arr,
            "scheduled_dep_utc": dep_utc, "scheduled_arr_utc": spec.get("scheduled_arr_utc"),
        }

    @staticmethod
    def _virtual_flight_number(con, prefix: str, dep_utc: str | None,
                               used: set[str] | None = None) -> str:
        """空闲的航班号：同一 (航班号, 起飞时刻) 唯一，且同一班表内不复用。

        不遵循航线生成的虚拟航段用**随机** 3 位号（OVO001/002/003 这类连号一看就是
        程序生成的，还容易和班期号段混淆）。随机源用 `SystemRandom`，不受抽班种子影响
        （同条件重抽不会又得到同一批号）；撞号重试若干次后退回顺序号，保证唯一性。
        """
        used = used if used is not None else set()

        def available(number: str) -> bool:
            if number in used:
                return False
            row = con.execute(
                "select 1 from flight_instance where flight_number=? and scheduled_dep_utc=?",
                (number, dep_utc)).fetchone()
            return row is None

        rng = random.SystemRandom()
        for _ in range(50):
            number = f"{prefix}{rng.randint(1, 999):03d}"
            if available(number):
                used.add(number)
                return number
        # 随机撞号（极端情况）→ 退回顺序号，语义与旧逻辑一致
        for n in range(1, 1000):
            number = f"{prefix}{n:03d}"
            if available(number):
                used.add(number)
                return number
        number = f"{prefix}{new_id()[:3].upper()}"
        used.add(number)
        return number

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
                        # 虚拟航段（mission_type=FREE）没有班期来源，取消时直接作废，不放回候选池
                        con.execute(
                            "update flight_instance set "
                            "status=case when mission_type='FREE' then 'CANCELLED' else 'SCHEDULED' end, "
                            "assigned_aircraft_id=NULL, roster_id=NULL, updated_at=? "
                            "where id=? and status in ('ASSIGNED','SCHEDULED')",
                            (stamp, leg["flight_instance_id"]))
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
                    con.execute(
                        "update flight_instance set "
                        "status=case when mission_type='FREE' then 'CANCELLED' else 'SCHEDULED' end, "
                        "assigned_aircraft_id=NULL, roster_id=NULL, updated_at=? where id=?",
                        (stamp, leg["flight_instance_id"]))
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
    def free_airports(self) -> list[dict[str, Any]]:
        """有可用飞机（ACTIVE 且未锁/未在飞）的机场：出发机场下拉只列这些。

        按飞机当前位置（`aircraft.current_airport_icao`）去重，无机队的机场不出现。
        """
        counts: dict[str, int] = {}
        for row in self.free_aircraft():
            icao = (row.get("current_airport_icao") or "").strip().upper()
            if icao:
                counts[icao] = counts.get(icao, 0) + 1
        nav = self.nav
        items: list[dict[str, Any]] = []
        for icao in sorted(counts):
            info = nav.airport(icao) if nav is not None else None
            info = info or {}
            items.append({
                "icao": icao,
                "iata": info.get("iata"),
                "name": info.get("name"),
                "city": info.get("city"),
                "country": info.get("country"),
                "lat": info.get("lat"), "lon": info.get("lon"),
                "aircraft": counts[icao],
            })
        return items

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
                 data.get("dep_time_utc") or _iso(now + timedelta(minutes=FREE_DEP_OFFSET_MINUTES)),
                 "LOCKED", _iso(expires), stamp, stamp))
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

    def start_leg(self, roster_id: str, sequence: int,
                  actual_zfw_kg: Any = None) -> dict[str, Any]:
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
        # 推出前 ZFW 校验：低于配载单只提示，不阻断（C-08）
        actual_zfw, zfw_delta, warnings = zfw_check(actual_zfw_kg, load.get("zfw_kg"))
        task = {
            "kind": "ROSTER", "roster_id": roster_id, "roster_leg_id": leg["id"],
            "flight_instance_id": leg.get("flight_instance_id"), "flight_record_id": flight_id,
            "aircraft_id": aircraft["id"], "dep_icao": leg.get("dep_icao"),
            "arr_icao": leg.get("arr_icao"), "aircraft_type": type_row.get("icao"),
            "callsign": self._callsign(instance["flight_number"] if instance else None),
            "scheduled_dep_utc": (instance or {}).get("scheduled_dep_utc"),
            "mission_type": (instance or {}).get("mission_type") or "SCHEDULED",
            "started_at": utcnow(),
            "actual_zfw_kg": actual_zfw, "zfw_delta_kg": zfw_delta,
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
        return {"task": task, "load_sheet": self.load_sheet(flight_id),
                "roster": self.roster(roster_id), "warnings": warnings}

    def start_free_flight(self, free_id: str, actual_zfw_kg: Any = None) -> dict[str, Any]:
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
        actual_zfw, zfw_delta, warnings = zfw_check(actual_zfw_kg, load.get("zfw_kg"))
        task = {
            "kind": "FREE", "free_flight_id": free_id, "flight_record_id": flight_id,
            "aircraft_id": aircraft.get("id"), "dep_icao": free["dep_icao"],
            "arr_icao": free["arr_icao"], "aircraft_type": type_row.get("icao"),
            "callsign": self._free_callsign(free_id), "scheduled_dep_utc": free.get("dep_time_utc"),
            "mission_type": "FREE", "started_at": utcnow(),
            "actual_zfw_kg": actual_zfw, "zfw_delta_kg": zfw_delta,
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
        return {"task": task, "load_sheet": self.load_sheet(flight_id),
                "free_flight": self.free_flight(free_id), "warnings": warnings}

    def set_actual_zfw(self, actual_zfw_kg: Any) -> list[str]:
        """记录开始前补录实际 ZFW（由 SimLink 采样换算），返回偏低警告。

        差异写进当前任务，开始录制时带入 `flight_record`，供事后核对。
        """
        task = self.active_task()
        if not task:
            return []
        sheet = self.load_sheet(task.get("flight_record_id") or "") or {}
        actual, delta, warnings = zfw_check(actual_zfw_kg, sheet.get("zfw_kg"))
        if actual is None:
            return []
        task["actual_zfw_kg"] = actual
        task["zfw_delta_kg"] = delta
        self._meta_set(ACTIVE_TASK_KEY, task)
        return warnings

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
        flight = self.db.get_flight(row["flight_record_id"]) or {}
        row["flight"] = flight or None
        # 与 settlements() 的行同名字段：详情 Drawer 的标题直接读平铺字段，
        # 只嵌套 flight 时前端拿不到呼号/起降，会退化成「— ????→????」。
        for key in ("callsign", "dep_icao", "arr_icao", "block_off_utc", "block_minutes",
                    "touchdown_vs_fpm", "landing_rating"):
            row[key] = flight.get(key)
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
