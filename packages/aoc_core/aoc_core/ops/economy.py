"""配载生成与收入/成本计算（docs/04 §3~§5）。

纯函数：输入航班、机型、飞机、经济参数与随机种子，输出配载单与明细。
结算与预估复用同一套公式；预估值只用于展示，最终以结算为准。
"""
from __future__ import annotations

import hashlib
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# 机场时区兜底表（navdata 没有时区字段；缺少 tzdata 时用固定偏移）
TZ_BY_ICAO = {
    "ZBAA": "Asia/Shanghai", "ZBAD": "Asia/Shanghai", "ZSSS": "Asia/Shanghai",
    "ZSPD": "Asia/Shanghai", "ZSHC": "Asia/Shanghai", "ZSNJ": "Asia/Shanghai",
    "ZUUU": "Asia/Shanghai", "ZPPP": "Asia/Shanghai", "ZLXY": "Asia/Shanghai",
    "ZHHH": "Asia/Shanghai", "ZGHA": "Asia/Shanghai", "ZJHK": "Asia/Shanghai",
    "ZBTJ": "Asia/Shanghai", "ZBSJ": "Asia/Shanghai", "ZBYN": "Asia/Shanghai",
    "ZSCN": "Asia/Shanghai", "ZGSZ": "Asia/Shanghai", "ZGGG": "Asia/Shanghai",
    "RJTT": "Asia/Tokyo", "RJAA": "Asia/Tokyo", "RJBB": "Asia/Tokyo", "RJCC": "Asia/Tokyo",
    "VHHH": "Asia/Hong_Kong", "WSSS": "Asia/Singapore", "OMDB": "Asia/Dubai",
    "LROP": "Europe/Bucharest", "LFPG": "Europe/Paris", "EGLL": "Europe/London",
    "EDDF": "Europe/Berlin", "LEMD": "Europe/Madrid", "LIRF": "Europe/Rome",
    "KJFK": "America/New_York", "KLAX": "America/Los_Angeles", "KORD": "America/Chicago",
    "KSEA": "America/Los_Angeles", "CYYZ": "America/Toronto",
    "YSSY": "Australia/Sydney", "NZAA": "Pacific/Auckland",
}

FIXED_OFFSET_MIN = {
    "Asia/Shanghai": 480, "Asia/Tokyo": 540, "Asia/Hong_Kong": 480,
    "Asia/Singapore": 480, "Asia/Dubai": 240, "Europe/Bucharest": 180,
    "Europe/Paris": 120, "Europe/London": 60, "Europe/Berlin": 120,
    "Europe/Madrid": 120, "Europe/Rome": 120, "America/New_York": -240,
    "America/Chicago": -300, "America/Los_Angeles": -420, "America/Toronto": -240,
    "Australia/Sydney": 600, "Pacific/Auckland": 720,
}

SIZE_CLASS = {
    "large": {"demand": 180, "tier": 1.10, "business_ratio": 0.10, "first_ratio": 0.02},
    "medium": {"demand": 90, "tier": 1.00, "business_ratio": 0.06, "first_ratio": 0.0},
    "small": {"demand": 40, "tier": 0.90, "business_ratio": 0.03, "first_ratio": 0.0},
}

TIME_FACTORS = ((6, 9, 1.10), (9, 17, 1.00), (17, 21, 1.15))
NIGHT_FACTOR = 0.60
DOW_FACTORS = (1.05, 1.00, 0.95, 0.95, 1.00, 1.10, 0.95)  # 周一..周日


# ---------------------------------------------------------------- 时间/机场
def _zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


def tz_name_for(icao: str | None) -> str:
    return TZ_BY_ICAO.get((icao or "").upper(), "UTC")


def parse_utc(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def local_hour(iso_utc: str | None, icao: str | None) -> int:
    dt = parse_utc(iso_utc)
    zone = _zone(tz_name_for(icao))
    if zone is not None:
        return dt.astimezone(zone).hour
    offset = FIXED_OFFSET_MIN.get(tz_name_for(icao), 0)
    return (dt + timedelta(minutes=offset)).hour


def local_dow(iso_utc: str | None, icao: str | None) -> int:
    dt = parse_utc(iso_utc)
    zone = _zone(tz_name_for(icao))
    local = dt.astimezone(zone) if zone else dt + timedelta(minutes=FIXED_OFFSET_MIN.get(tz_name_for(icao), 0))
    return local.weekday()


def local_now(icao: str | None, at: datetime | None = None) -> datetime:
    dt = at or datetime.now(timezone.utc)
    zone = _zone(tz_name_for(icao))
    if zone is not None:
        return dt.astimezone(zone)
    return dt + timedelta(minutes=FIXED_OFFSET_MIN.get(tz_name_for(icao), 0))


def local_to_utc(day: datetime, hhmm: str, icao: str | None) -> str:
    """把机场本地日期 + HH:MM 转成 UTC ISO；DST 由 zoneinfo 处理。"""
    hour, minute = (int(x) for x in (hhmm or "00:00").split(":")[:2])
    naive = datetime(day.year, day.month, day.day, hour, minute)
    zone = _zone(tz_name_for(icao))
    if zone is not None:
        return to_iso(naive.replace(tzinfo=zone))
    offset = FIXED_OFFSET_MIN.get(tz_name_for(icao), 0)
    return to_iso((naive - timedelta(minutes=offset)).replace(tzinfo=timezone.utc))


def airport_meta(nav: Any, icao: str | None) -> dict[str, Any]:
    info = nav.airport(icao) if nav is not None else None
    if not info:
        return {"icao": (icao or "").upper(), "size_class": "medium", "known": False,
                **SIZE_CLASS["medium"], "lat": None, "lon": None, "runway_m": None,
                "name": None, "country": None}
    runway_ft = info.get("longest_runway_ft")
    runway_m = round(float(runway_ft) / 3.280839895) if runway_ft else None
    if runway_m is None:
        size = "medium"
    elif runway_m >= 3000:
        size = "large"
    elif runway_m >= 1800:
        size = "medium"
    else:
        size = "small"
    return {
        "icao": info["ident"], "size_class": size, "known": True, **SIZE_CLASS[size],
        "lat": info.get("lat"), "lon": info.get("lon"), "runway_m": runway_m,
        "name": info.get("name"), "country": info.get("country"),
    }


def gcd_nm(a: dict | None, b: dict | None) -> float:
    if not a or not b or a.get("lat") is None or b.get("lat") is None:
        return 0.0
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(h)))


# ---------------------------------------------------------------- 配载
def seeded_rng(seed: str, salt: str = "") -> random.Random:
    digest = hashlib.sha256(f"{seed}|{salt}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def estimate_block_minutes(distance_nm: float, cruise_speed_kt: float) -> float:
    speed = cruise_speed_kt or 440.0
    return round(max(20.0, distance_nm / speed * 60.0 + 25.0), 1)


def generate_load_sheet(
    *,
    dep: str,
    arr: str,
    distance_nm: float,
    block_minutes: float,
    aircraft_type: dict[str, Any],
    params: dict[str, Any],
    seed: str,
    dep_time_utc: str | None = None,
    repeat_index: int = 0,
    dep_meta: dict[str, Any] | None = None,
    arr_meta: dict[str, Any] | None = None,
    mission_type: str = "SCHEDULED",
) -> dict[str, Any]:
    """按机型角色生成配载单（BIZJET/VIP/CARGO 不走 95% 客座率模型）。"""
    role = (aircraft_type.get("role") or "AIRLINER").upper()
    profile = (aircraft_type.get("demand_profile") or "MASS").upper()
    cabin = aircraft_type.get("cabin_config_json") or {}
    if isinstance(cabin, str):
        cabin = {}
    cap = int(aircraft_type.get("pax_capacity") or 0)
    cargo_cap = float(aircraft_type.get("cargo_capacity_kg") or 0)
    burn = float(aircraft_type.get("fuel_burn_kg_h") or 2400)
    oew = float(aircraft_type.get("oew_kg") or 0)
    mtow = float(aircraft_type.get("mtow_kg") or 0)
    mzfw = float(aircraft_type.get("mzfw_kg") or 0)
    fuel_cap = float(aircraft_type.get("fuel_capacity_kg") or 0)
    dep_meta = dep_meta or {"demand": 90, "tier": 1.0, "size_class": "medium", "business_ratio": 0.06}
    arr_meta = arr_meta or dep_meta

    rng = seeded_rng(seed, "loadsheet")
    distance_nm = max(0.0, float(distance_nm or 0))
    block_minutes = max(15.0, float(block_minutes or 60))
    block_hours = block_minutes / 60.0
    hour = local_hour(dep_time_utc, dep)
    dow = local_dow(dep_time_utc, dep)

    base_demand = float(dep_meta.get("demand", 90)) * float(arr_meta.get("demand", 90)) / 120.0
    route_factor = min(1.10, max(0.35, 1.20 - distance_nm / 5000.0))
    time_factor = next((f for lo, hi, f in TIME_FACTORS if lo <= hour < hi), NIGHT_FACTOR)
    dow_factor = DOW_FACTORS[dow % 7]
    noise = rng.uniform(0.85, 1.15)
    decay = max(float(params.get("repeat_route_floor", 0.5)),
                float(params.get("repeat_route_decay", 0.92)) ** max(0, repeat_index))
    demand = base_demand * route_factor * time_factor * dow_factor * noise * decay

    pax_first = pax_business = pax_premium = pax_economy = 0
    cargo_kg = mail_kg = 0.0
    market_factor = 1.0
    if role in ("BIZJET", "VIP") or profile in ("BIZJET", "NONE") or mission_type == "VIP":
        cap = max(0, cap)
        if role == "VIP" or profile == "NONE" or mission_type == "VIP":
            pax_total = 0
        else:
            ratio = rng.uniform(float(params.get("bizjet_load_min", 0.35)),
                                float(params.get("bizjet_load_max", 0.80)))
            pax_total = min(cap, max(4, round(cap * ratio))) if cap else 0
        pax_first = min(int(cabin.get("first") or 0), pax_total)
        pax_business = min(int(cabin.get("business") or 0), pax_total - pax_first)
        pax_premium = min(int(cabin.get("premium_economy") or 0), pax_total - pax_first - pax_business)
        pax_economy = max(0, pax_total - pax_first - pax_business - pax_premium)
        cargo_kg = 0.0
        mail_kg = 0.0
        market_factor = rng.uniform(0.9, 1.1)
    elif role == "CARGO" or profile == "CARGO":
        pax_total = 0
        cargo_kg = min(cargo_cap, max(0.0, base_demand * float(params.get("cargo_kg_per_pax", 8)) * noise))
        mail_kg = round(cargo_kg * 0.05, 1)
    else:
        cap_limit = int(round(cap * float(params.get("load_factor_cap", 0.95))))
        pax_total = int(max(0, min(round(demand), cap_limit)))
        avg_tier = (float(dep_meta.get("tier", 1.0)) + float(arr_meta.get("tier", 1.0))) / 2
        business_ratio = float(params.get("business_ratio_large", 0.10))
        biz_dep = {"large": params.get("business_ratio_large", 0.10),
                   "medium": params.get("business_ratio_medium", 0.06),
                   "small": params.get("business_ratio_small", 0.03)}
        business_ratio = (biz_dep.get(dep_meta.get("size_class", "medium"), 0.06)
                          + biz_dep.get(arr_meta.get("size_class", "medium"), 0.06)) / 2
        first_ratio = 0.0
        if "large" in (dep_meta.get("size_class"), arr_meta.get("size_class")) and int(cabin.get("first") or 0) > 0:
            first_ratio = float(params.get("first_ratio_large", 0.02))
        pax_first = min(int(cabin.get("first") or 0), round(pax_total * first_ratio))
        pax_business = min(int(cabin.get("business") or 0), round(pax_total * business_ratio))
        pax_business = min(pax_business, pax_total - pax_first)
        pax_premium = 0
        pax_economy = max(0, pax_total - pax_first - pax_business)
        if pax_economy > int(cabin.get("economy") or cap):
            overflow = pax_economy - int(cabin.get("economy") or cap)
            pax_economy -= overflow
            pax_total = pax_first + pax_business + pax_economy
        cargo_kg = round(min(cargo_cap, max(0.0, demand * float(params.get("cargo_kg_per_pax", 8.0)))), 1)
        mail_kg = round(cargo_kg * 0.05, 1)
        _ = avg_tier  # 票价里按下机/上机机场重新计算

    pax_weight = pax_total * 95.0
    cargo_weight = cargo_kg + mail_kg
    zfw = oew + pax_weight + cargo_weight
    trip_fuel = burn * block_hours
    reserve = burn * 0.5
    taxi = 200.0
    fuel = min(fuel_cap, trip_fuel + reserve + taxi) if fuel_cap else trip_fuel + reserve + taxi
    tow = zfw + fuel

    # 超重削减：货物 → 邮件 → 旅客 → 燃油
    if mzfw and zfw > mzfw:
        over = zfw - mzfw
        cut = min(cargo_kg, over)
        cargo_kg -= cut
        over -= cut
        if over > 0:
            cut = min(mail_kg, over)
            mail_kg -= cut
            over -= cut
        if over > 0 and pax_total:
            drop = min(pax_total, math.ceil(over / 95.0))
            pax_economy = max(0, pax_economy - drop)
            pax_total -= drop
        zfw = oew + pax_total * 95.0 + cargo_kg + mail_kg
        tow = zfw + fuel
    if mtow and tow > mtow:
        over = tow - mtow
        cut = min(fuel, over)
        fuel -= cut
        tow -= cut
        over -= cut
        if over > 0:
            cut = min(cargo_kg, over)
            cargo_kg -= cut
            tow -= cut
            zfw -= cut

    revenue_items = _revenue_items(
        params=params, role=role, dep=dep, arr=arr, distance_nm=distance_nm,
        pax_economy=pax_economy, pax_premium=pax_premium, pax_business=pax_business,
        pax_first=pax_first, pax_total=pax_total, cargo_kg=cargo_kg, mail_kg=mail_kg,
        dep_meta=dep_meta, arr_meta=arr_meta, aircraft_type=aircraft_type,
        block_hours=block_hours, market_factor=market_factor)
    revenue = round(sum(item["amount"] for item in revenue_items), 2)
    cost_items = _cost_items(
        params=params, distance_nm=distance_nm, block_hours=block_hours,
        pax_total=pax_total, cargo_kg=cargo_kg + mail_kg,
        mtow_kg=mtow, fuel_used_kg=trip_fuel, aircraft=aircraft_type,
        arr=arr, arr_time_utc=dep_time_utc, revenue=revenue)
    cost = round(sum(item["amount"] for item in cost_items), 2)
    return {
        "pax_total": pax_total, "pax_economy": pax_economy, "pax_premium_economy": pax_premium,
        "pax_business": pax_business, "pax_first": pax_first,
        "cargo_kg": round(cargo_kg, 1), "mail_kg": round(mail_kg, 1),
        "oew_kg": round(oew, 1), "zfw_kg": round(zfw, 1), "tow_kg": round(tow, 1),
        "fuel_kg": round(fuel, 1), "block_minutes": round(block_minutes, 1),
        "distance_nm": round(distance_nm, 1),
        "estimated_revenue": revenue, "estimated_cost": cost,
        "estimated_profit": round(revenue - cost, 2),
        "demand": round(demand, 1),
        "breakdown": {"inputs": {
            "distance_nm": round(distance_nm, 1), "block_minutes": round(block_minutes, 1),
            "pax_total": pax_total, "demand": round(demand, 1),
            "route_factor": round(route_factor, 3), "time_factor": time_factor,
            "dow_factor": dow_factor, "noise": round(noise, 3), "decay": round(decay, 3),
            "market_factor": round(market_factor, 3),
            "dep_tier": dep_meta.get("tier", 1.0), "arr_tier": arr_meta.get("tier", 1.0),
            "dep_size_class": dep_meta.get("size_class", "medium"),
            "arr_size_class": arr_meta.get("size_class", "medium"),
        }, "revenue": revenue_items, "costs": cost_items},
    }


def price_index(params: dict[str, Any], dep_meta: dict, arr_meta: dict) -> float:
    return (float(dep_meta.get("tier", 1.0)) + float(arr_meta.get("tier", 1.0))) / 2


def _revenue_items(*, params: dict[str, Any], role: str, dep: str, arr: str, distance_nm: float,
                   pax_economy: int, pax_premium: int, pax_business: int, pax_first: int,
                   pax_total: int, cargo_kg: float, mail_kg: float,
                   dep_meta: dict, arr_meta: dict, aircraft_type: dict[str, Any],
                   block_hours: float, market_factor: float) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if role in ("BIZJET", "VIP") or (aircraft_type.get("demand_profile") or "").upper() in ("BIZJET", "NONE"):
        if role != "VIP" and (aircraft_type.get("demand_profile") or "").upper() != "NONE":
            rate = float(aircraft_type.get("charter_rate_per_hour") or 0)
            if rate > 0:
                items.append({"type": "REVENUE_CHARTER",
                              "amount": round(rate * block_hours * market_factor, 2),
                              "note": f"{rate:.0f}/h × {block_hours:.2f}h × {market_factor:.2f}"})
        return items

    tier = price_index(params, dep_meta, arr_meta)
    fare_economy = (float(params.get("fare_economy_base", 25.0))
                    + float(params.get("fare_economy_per_nm", 0.10)) * distance_nm) * tier
    mult = float(aircraft_type.get("fare_multiplier") or 1.0)
    fare_business = fare_economy * float(params.get("fare_business_multiplier", 2.6)) * mult
    fare_first = fare_economy * float(params.get("fare_first_multiplier", 4.0)) * mult
    if pax_economy:
        items.append({"type": "REVENUE_PAX", "amount": round(pax_economy * fare_economy, 2),
                      "note": f"{pax_economy} × {fare_economy:.2f}"})
    if pax_business:
        items.append({"type": "REVENUE_PAX_BUSINESS", "amount": round(pax_business * fare_business, 2),
                      "note": f"{pax_business} × {fare_business:.2f}"})
    if pax_first:
        items.append({"type": "REVENUE_PAX_FIRST", "amount": round(pax_first * fare_first, 2),
                      "note": f"{pax_first} × {fare_first:.2f}"})
    if cargo_kg:
        items.append({"type": "REVENUE_CARGO",
                      "amount": round(cargo_kg * float(params.get("cargo_rate", 0.45)), 2),
                      "note": f"{cargo_kg:.0f} kg"})
    if mail_kg:
        items.append({"type": "REVENUE_MAIL",
                      "amount": round(mail_kg * float(params.get("mail_rate", 0.30)), 2),
                      "note": f"{mail_kg:.0f} kg"})
    if pax_total:
        items.append({"type": "REVENUE_ANCILLARY",
                      "amount": round(pax_total * float(params.get("ancillary_per_pax", 6.0)), 2),
                      "note": f"{pax_total} pax"})
    return items


def _cost_items(*, params: dict[str, Any], distance_nm: float, block_hours: float,
                pax_total: int, cargo_kg: float, mtow_kg: float, fuel_used_kg: float,
                aircraft: dict[str, Any], arr: str | None, arr_time_utc: str | None,
                revenue: float) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items.append({"type": "COST_FUEL",
                  "amount": round(fuel_used_kg * float(params.get("fuel_price", 1.05)), 2),
                  "note": f"{fuel_used_kg:.0f} kg"})
    mtow_ton = mtow_kg / 1000.0
    landing = mtow_ton * float(params.get("landing_per_ton", 24.0))
    if arr:
        hour = local_hour(arr_time_utc, arr)
        if hour >= 22 or hour < 6:
            landing += float(params.get("night_surcharge", 50.0))
    items.append({"type": "COST_LANDING", "amount": round(landing, 2), "note": f"{mtow_ton:.1f} t"})
    handling = (pax_total * float(params.get("handling_per_pax", 11.0))
                + cargo_kg / 1000.0 * float(params.get("handling_per_cargo_ton", 30.0)))
    items.append({"type": "COST_HANDLING", "amount": round(handling, 2), "note": f"{pax_total} pax"})
    items.append({"type": "COST_CREW",
                  "amount": round(block_hours * float(params.get("crew_per_block_hour", 900.0)), 2),
                  "note": f"{block_hours:.2f} h"})
    items.append({"type": "COST_MAINTENANCE",
                  "amount": round(block_hours * float(params.get("maintenance_per_block_hour", 600.0))
                                  + float(params.get("maintenance_per_cycle", 60.0)), 2),
                  "note": f"{block_hours:.2f} h + 1 cycle"})
    lease_hour = aircraft.get("lease_per_hour") or aircraft.get("_lease_per_hour") or 0
    items.append({"type": "COST_LEASE", "amount": round(block_hours * float(lease_hour), 2),
                  "note": f"{float(lease_hour):.0f}/h"})
    items.append({"type": "COST_ATC",
                  "amount": round(distance_nm * float(params.get("atc_per_nm", 0.70)), 2),
                  "note": f"{distance_nm:.0f} NM"})
    items.append({"type": "COST_INSURANCE",
                  "amount": round(revenue * float(params.get("insurance_rate", 0.012)), 2),
                  "note": "收入 1.2%"})
    return items


# ---------------------------------------------------------------- 结算
def settle_amounts(
    *,
    params: dict[str, Any],
    aircraft: dict[str, Any],
    aircraft_type: dict[str, Any],
    load_sheet: dict[str, Any],
    distance_nm: float,
    block_minutes: float,
    fuel_used_kg: float,
    scheduled_dep_utc: str | None,
    actual_dep_utc: str | None,
    arr: str | None,
    arr_time_utc: str | None,
) -> dict[str, Any]:
    """用实际数据重算收入/成本（收入项先按配载与票价算，再按准点/异常折算）。"""
    role = (aircraft_type.get("role") or "AIRLINER").upper()
    pax_total = int(load_sheet.get("pax_total") or 0)
    cargo_kg = float(load_sheet.get("cargo_kg") or 0) + float(load_sheet.get("mail_kg") or 0)
    block_hours = max(0.05, float(block_minutes or 0) / 60.0)
    inputs: dict[str, Any] = {}
    if isinstance(load_sheet.get("breakdown_json"), dict):
        inputs = load_sheet["breakdown_json"].get("inputs") or {}
    dep_meta = {"tier": float(inputs.get("dep_tier") or 1.0),
                "size_class": inputs.get("dep_size_class") or "medium"}
    arr_meta = {"tier": float(inputs.get("arr_tier") or 1.0),
                "size_class": inputs.get("arr_size_class") or "medium"}
    revenue_items = _revenue_items(
        params=params, role=role, dep=load_sheet.get("dep_icao") or "",
        arr=load_sheet.get("arr_icao") or "", distance_nm=distance_nm,
        pax_economy=int(load_sheet.get("pax_economy") or 0),
        pax_premium=int(load_sheet.get("pax_premium_economy") or 0),
        pax_business=int(load_sheet.get("pax_business") or 0),
        pax_first=int(load_sheet.get("pax_first") or 0),
        pax_total=pax_total, cargo_kg=float(load_sheet.get("cargo_kg") or 0),
        mail_kg=float(load_sheet.get("mail_kg") or 0),
        dep_meta=dep_meta, arr_meta=arr_meta, aircraft_type=aircraft_type,
        block_hours=block_hours,
        market_factor=float(inputs.get("market_factor") or 1.0))
    revenue_gross = round(sum(i["amount"] for i in revenue_items), 2)
    factor, on_time_note = on_time_factor(params, scheduled_dep_utc, actual_dep_utc)
    if factor != 1.0:
        revenue_items = [dict(i, amount=round(i["amount"] * factor, 2)) for i in revenue_items]
        revenue_gross = round(revenue_gross * factor, 2)
    cost_aircraft = dict(aircraft_type)
    cost_aircraft.update({k: v for k, v in (aircraft or {}).items() if v is not None})
    if not cost_aircraft.get("lease_per_hour") and isinstance(aircraft_type.get("lease_per_hour"), (int, float)):
        cost_aircraft["lease_per_hour"] = aircraft_type["lease_per_hour"]
    cost_items = _cost_items(
        params=params, distance_nm=distance_nm, block_hours=block_hours,
        pax_total=pax_total, cargo_kg=cargo_kg,
        mtow_kg=float(aircraft_type.get("mtow_kg") or 0), fuel_used_kg=fuel_used_kg,
        aircraft=cost_aircraft, arr=arr, arr_time_utc=arr_time_utc,
        revenue=revenue_gross)
    cost_total = round(sum(i["amount"] for i in cost_items), 2)
    return {
        "revenue_gross": revenue_gross, "revenue_items": revenue_items,
        "cost_items": cost_items, "cost_total": cost_total,
        "profit": round(revenue_gross - cost_total, 2),
        "on_time_factor": factor, "on_time_note": on_time_note,
    }


def on_time_factor(params: dict[str, Any], scheduled: str | None, actual: str | None) -> tuple[float, str]:
    if not scheduled or not actual:
        return 1.0, "无计划时刻"
    delta = abs((parse_utc(actual) - parse_utc(scheduled)).total_seconds()) / 60.0
    tolerance = float(params.get("time_tolerance_min", 15))
    delay = float(params.get("delay_threshold_min", 60))
    off = float(params.get("off_schedule_threshold_min", 180))
    if delta <= tolerance:
        return float(params.get("on_time_bonus_factor", 1.02)), f"准点（{delta:.0f}min）"
    if delta <= delay:
        return 1.0, f"偏离 {delta:.0f}min"
    if delta <= off:
        return float(params.get("delay_penalty_factor", 0.95)), f"延误 {delta:.0f}min"
    return float(params.get("off_schedule_factor", 0.97)), f"严重偏离 {delta:.0f}min（OFF_SCHEDULE）"


def synthetic_preview(params: dict[str, Any], *, samples: int = 100) -> dict[str, Any]:
    """参数预览：用一组固定航段跑合成航班，返回利润/载客率/亏损比例。"""
    fleet = [
        ("A320", {"dep": "ZBAA", "arr": "ZSSS", "distance_nm": 612, "role": "AIRLINER"},
         {"role": "AIRLINER", "demand_profile": "MASS", "pax_capacity": 180,
          "cabin_config_json": {"first": 0, "business": 18, "premium_economy": 0, "economy": 162},
          "oew_kg": 42600, "mtow_kg": 78000, "mzfw_kg": 62500, "fuel_capacity_kg": 19000,
          "fuel_burn_kg_h": 2400, "cargo_capacity_kg": 9000, "lease_per_hour": 2000,
          "cruise_speed_kt": 440}),
        ("B738", {"dep": "ZSSS", "arr": "ZSHC", "distance_nm": 90, "role": "AIRLINER"},
         {"role": "AIRLINER", "demand_profile": "MASS", "pax_capacity": 186,
          "cabin_config_json": {"first": 0, "business": 16, "premium_economy": 0, "economy": 170},
          "oew_kg": 41400, "mtow_kg": 79000, "mzfw_kg": 62700, "fuel_capacity_kg": 20000,
          "fuel_burn_kg_h": 2500, "cargo_capacity_kg": 9000, "lease_per_hour": 2100,
          "cruise_speed_kt": 445}),
        ("A333", {"dep": "ZBAA", "arr": "EGLL", "distance_nm": 4400, "role": "AIRLINER"},
         {"role": "AIRLINER", "demand_profile": "MASS", "pax_capacity": 290,
          "cabin_config_json": {"first": 8, "business": 42, "premium_economy": 24, "economy": 216},
          "oew_kg": 124000, "mtow_kg": 242000, "mzfw_kg": 174000, "fuel_capacity_kg": 109000,
          "fuel_burn_kg_h": 6200, "cargo_capacity_kg": 20000, "lease_per_hour": 5800,
          "cruise_speed_kt": 470}),
    ]
    big = {"demand": 180, "tier": 1.10, "size_class": "large", "business_ratio": 0.10}
    small = {"demand": 90, "tier": 1.00, "size_class": "medium", "business_ratio": 0.06}
    profits, loads = [], []
    for i in range(max(1, samples)):
        name, leg, spec = fleet[i % len(fleet)]
        type_row = dict(spec, name=name, icao=name, _lease_per_hour=spec["lease_per_hour"])
        block = estimate_block_minutes(leg["distance_nm"], spec["cruise_speed_kt"])
        sheet = generate_load_sheet(
            dep=leg["dep"], arr=leg["arr"], distance_nm=leg["distance_nm"], block_minutes=block,
            aircraft_type=type_row, params=params, seed=f"preview-{i}",
            repeat_index=i % 3, dep_meta=big if leg["distance_nm"] > 1000 else small,
            arr_meta=big if leg["distance_nm"] > 1000 else big)
        revenue = sheet["estimated_revenue"]
        cost_items = _cost_items(
            params=params, distance_nm=leg["distance_nm"], block_hours=block / 60.0,
            pax_total=sheet["pax_total"], cargo_kg=sheet["cargo_kg"] + sheet["mail_kg"],
            mtow_kg=spec["mtow_kg"],
            fuel_used_kg=spec["fuel_burn_kg_h"] * block / 60.0, aircraft=type_row,
            arr=leg["arr"], arr_time_utc=None, revenue=revenue)
        cost = sum(c["amount"] for c in cost_items)
        profits.append(revenue - cost)
        loads.append(sheet["pax_total"] / max(1, spec["pax_capacity"]))
    avg_profit = sum(profits) / len(profits)
    loss_ratio = sum(1 for p in profits if p < 0) / len(profits)
    return {
        "samples": len(profits),
        "avg_profit": round(avg_profit, 2),
        "median_profit": round(sorted(profits)[len(profits) // 2], 2),
        "avg_load_factor": round(sum(loads) / len(loads), 3),
        "loss_ratio": round(loss_ratio, 3),
        "bankruptcy_probability": round(sum(1 for p in profits if p < -20000) / len(profits), 3),
    }
