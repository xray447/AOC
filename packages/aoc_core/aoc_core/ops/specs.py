"""机型模板补全、经济参数默认值与运营种子数据。

`data/aircraft_types.json` 只有推荐/航路需要的少量字段；运营模式需要
OEW/MTOW/油耗/构型/包机价等，这里按 `category` 补全，并对常用机型写死一组
近似真值。默认值来自 docs/04 §7，可在「运营规则」页修改（草稿→预览→发布）。
"""
from __future__ import annotations

from typing import Any

from ..db import utcnow, new_id

# 按 category 的兜底参数（近似值，仅用于未单独列出的机型）
CATEGORY_DEFAULTS: dict[str, dict[str, Any]] = {
    "ga": {
        "role": "BIZJET", "demand_profile": "BIZJET", "allow_scheduled": False,
        "allow_charter": True, "charter_rate_per_hour": 800,
        "pax_capacity": 6, "cargo_capacity_kg": 300, "oew_kg": 2400, "mtow_kg": 5000,
        "mzfw_kg": 4200, "mlw_kg": 4600, "fuel_capacity_kg": 1200, "fuel_burn_kg_h": 220,
        "lease_per_hour": 350, "cabin": {"first": 0, "business": 0, "premium_economy": 0, "economy": 6},
    },
    "regional": {
        "role": "AIRLINER", "demand_profile": "MASS", "allow_scheduled": True,
        "allow_charter": True, "charter_rate_per_hour": 0,
        "pax_capacity": 74, "cargo_capacity_kg": 2500, "oew_kg": 21000, "mtow_kg": 29500,
        "mzfw_kg": 25000, "mlw_kg": 27000, "fuel_capacity_kg": 6500, "fuel_burn_kg_h": 900,
        "lease_per_hour": 900, "cabin": {"first": 0, "business": 6, "premium_economy": 0, "economy": 68},
    },
    "narrow": {
        "role": "AIRLINER", "demand_profile": "MASS", "allow_scheduled": True,
        "allow_charter": True, "charter_rate_per_hour": 0,
        "pax_capacity": 160, "cargo_capacity_kg": 9000, "oew_kg": 42600, "mtow_kg": 78000,
        "mzfw_kg": 62500, "mlw_kg": 66000, "fuel_capacity_kg": 19000, "fuel_burn_kg_h": 2400,
        "lease_per_hour": 2000, "cabin": {"first": 0, "business": 16, "premium_economy": 0, "economy": 144},
    },
    "wide": {
        "role": "AIRLINER", "demand_profile": "MASS", "allow_scheduled": True,
        "allow_charter": True, "charter_rate_per_hour": 0,
        "pax_capacity": 280, "cargo_capacity_kg": 20000, "oew_kg": 120000, "mtow_kg": 233000,
        "mzfw_kg": 180000, "mlw_kg": 190000, "fuel_capacity_kg": 100000, "fuel_burn_kg_h": 6500,
        "lease_per_hour": 6000, "cabin": {"first": 8, "business": 42, "premium_economy": 24, "economy": 206},
    },
}

# 常用机型的近似真值（只写与兜底不同的字段）
SPEC_OVERRIDES: dict[str, dict[str, Any]] = {
    "C172": {"pax_capacity": 4, "cabin": {"first": 0, "business": 0, "premium_economy": 0, "economy": 4},
             "cargo_capacity_kg": 120, "oew_kg": 770, "mtow_kg": 1160, "mzfw_kg": 1000,
             "mlw_kg": 1000, "fuel_capacity_kg": 200, "fuel_burn_kg_h": 35, "lease_per_hour": 150},
    "B350": {"pax_capacity": 11, "cabin": {"first": 0, "business": 0, "premium_economy": 0, "economy": 11},
             "cargo_capacity_kg": 700, "oew_kg": 4300, "mtow_kg": 6800, "mzfw_kg": 5900,
             "mlw_kg": 5900, "fuel_capacity_kg": 1650, "fuel_burn_kg_h": 400, "lease_per_hour": 700},
    "C25C": {"pax_capacity": 9, "cabin": {"first": 0, "business": 0, "premium_economy": 0, "economy": 9},
             "cargo_capacity_kg": 500, "oew_kg": 4700, "mtow_kg": 10400, "mzfw_kg": 7000,
             "mlw_kg": 7800, "fuel_capacity_kg": 2600, "fuel_burn_kg_h": 600, "lease_per_hour": 1200,
             "charter_rate_per_hour": 2500},
    "AT76": {"pax_capacity": 70, "cabin": {"first": 0, "business": 0, "premium_economy": 0, "economy": 70},
             "cargo_capacity_kg": 1500, "oew_kg": 13500, "mtow_kg": 23000, "mzfw_kg": 20000,
             "mlw_kg": 21000, "fuel_capacity_kg": 5000, "fuel_burn_kg_h": 640, "lease_per_hour": 700},
    "E190": {"pax_capacity": 100, "cabin": {"first": 0, "business": 8, "premium_economy": 0, "economy": 92},
             "cargo_capacity_kg": 3500, "oew_kg": 28000, "mtow_kg": 51800, "mzfw_kg": 40000,
             "mlw_kg": 44000, "fuel_capacity_kg": 13000, "fuel_burn_kg_h": 1500, "lease_per_hour": 1300},
    "CRJ9": {"pax_capacity": 90, "cabin": {"first": 0, "business": 8, "premium_economy": 0, "economy": 82},
             "cargo_capacity_kg": 3000, "oew_kg": 21500, "mtow_kg": 38300, "mzfw_kg": 31000,
             "mlw_kg": 34000, "fuel_capacity_kg": 8800, "fuel_burn_kg_h": 1400, "lease_per_hour": 1200},
    "A319": {"pax_capacity": 134, "cabin": {"first": 0, "business": 12, "premium_economy": 0, "economy": 122},
             "oew_kg": 40800, "mtow_kg": 75500, "mzfw_kg": 58500, "mlw_kg": 62500,
             "fuel_capacity_kg": 17800, "fuel_burn_kg_h": 2200, "lease_per_hour": 1800},
    "A320": {"pax_capacity": 180, "cabin": {"first": 0, "business": 18, "premium_economy": 0, "economy": 162},
             "oew_kg": 42600, "mtow_kg": 78000, "mzfw_kg": 62500, "mlw_kg": 66000,
             "fuel_capacity_kg": 19000, "fuel_burn_kg_h": 2400, "lease_per_hour": 2000},
    "A321": {"pax_capacity": 200, "cabin": {"first": 0, "business": 20, "premium_economy": 0, "economy": 180},
             "oew_kg": 48500, "mtow_kg": 93500, "mzfw_kg": 73800, "mlw_kg": 77800,
             "fuel_capacity_kg": 22000, "fuel_burn_kg_h": 2600, "lease_per_hour": 2300},
    "B738": {"pax_capacity": 186, "cabin": {"first": 0, "business": 16, "premium_economy": 0, "economy": 170},
             "oew_kg": 41400, "mtow_kg": 79000, "mzfw_kg": 62700, "mlw_kg": 66300,
             "fuel_capacity_kg": 20000, "fuel_burn_kg_h": 2500, "lease_per_hour": 2100},
    "B39M": {"pax_capacity": 193, "cabin": {"first": 0, "business": 16, "premium_economy": 0, "economy": 177},
             "oew_kg": 45300, "mtow_kg": 88000, "mzfw_kg": 69000, "mlw_kg": 71000,
             "fuel_capacity_kg": 21000, "fuel_burn_kg_h": 2300, "lease_per_hour": 2500},
    "B752": {"pax_capacity": 200, "cabin": {"first": 0, "business": 20, "premium_economy": 0, "economy": 180},
             "oew_kg": 58000, "mtow_kg": 116000, "mzfw_kg": 84000, "mlw_kg": 90000,
             "fuel_capacity_kg": 34000, "fuel_burn_kg_h": 3300, "lease_per_hour": 2600},
    "A332": {"pax_capacity": 260, "cabin": {"first": 6, "business": 36, "premium_economy": 20, "economy": 198},
             "oew_kg": 120000, "mtow_kg": 233000, "mzfw_kg": 170000, "mlw_kg": 180000,
             "fuel_capacity_kg": 109000, "fuel_burn_kg_h": 5900, "lease_per_hour": 5500},
    "A333": {"pax_capacity": 290, "cabin": {"first": 8, "business": 42, "premium_economy": 24, "economy": 216},
             "oew_kg": 124000, "mtow_kg": 242000, "mzfw_kg": 174000, "mlw_kg": 186000,
             "fuel_capacity_kg": 109000, "fuel_burn_kg_h": 6200, "lease_per_hour": 5800},
    "A343": {"pax_capacity": 300, "cabin": {"first": 8, "business": 42, "premium_economy": 30, "economy": 220},
             "oew_kg": 129000, "mtow_kg": 271000, "mzfw_kg": 178000, "mlw_kg": 190000,
             "fuel_capacity_kg": 110000, "fuel_burn_kg_h": 6800, "lease_per_hour": 6000},
    "A359": {"pax_capacity": 325, "cabin": {"first": 8, "business": 48, "premium_economy": 28, "economy": 241},
             "oew_kg": 142000, "mtow_kg": 280000, "mzfw_kg": 192000, "mlw_kg": 207000,
             "fuel_capacity_kg": 110000, "fuel_burn_kg_h": 5800, "lease_per_hour": 8000},
    "A388": {"pax_capacity": 525, "cabin": {"first": 14, "business": 76, "premium_economy": 44, "economy": 391},
             "oew_kg": 276000, "mtow_kg": 575000, "mzfw_kg": 361000, "mlw_kg": 394000,
             "fuel_capacity_kg": 250000, "fuel_burn_kg_h": 11500, "lease_per_hour": 12000},
    "B77W": {"pax_capacity": 396, "cabin": {"first": 8, "business": 52, "premium_economy": 32, "economy": 304},
             "oew_kg": 167800, "mtow_kg": 351500, "mzfw_kg": 237700, "mlw_kg": 251300,
             "fuel_capacity_kg": 145000, "fuel_burn_kg_h": 7500, "lease_per_hour": 9000},
    "B789": {"pax_capacity": 296, "cabin": {"first": 8, "business": 42, "premium_economy": 24, "economy": 222},
             "oew_kg": 138000, "mtow_kg": 254000, "mzfw_kg": 181000, "mlw_kg": 193000,
             "fuel_capacity_kg": 126000, "fuel_burn_kg_h": 5600, "lease_per_hour": 8500},
}

# 翼展（米，docs/TODO §26）：抽班按「翼展 ≤ 跑道宽度推出的上限」过滤机场。
# 目录里不写翼展，按 category 兜底；常用机型写近似真值。
WINGSPAN_BY_CATEGORY = {"ga": 15.0, "regional": 28.0, "narrow": 36.0, "wide": 65.0}
WINGSPAN_OVERRIDES: dict[str, float] = {
    "C172": 11.0, "B350": 17.7, "C25C": 15.5, "AT76": 27.1, "E190": 28.7, "CRJ9": 24.9,
    "A319": 35.8, "A320": 35.8, "A321": 35.8, "B738": 35.9, "B39M": 35.9, "B752": 38.0,
    "A332": 60.3, "A333": 60.3, "A343": 60.3, "A359": 64.8, "A388": 79.8,
    "B77W": 64.8, "B789": 60.1,
}

# SimLink `aircraft_title` 的常见写法（MSFS 里的机型名）：只用于自动识别机型。
# 自定义机型优先用 `title_keyword`；内置机型靠这张表 + ICAO 兜底（法：最长匹配）。
TITLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "C172": ("CESSNA 172", "SKYHAWK", "C172"),
    "B350": ("KING AIR", "B350"),
    "C25C": ("CITATION", "CJ4", "C25C"),
    "AT76": ("ATR 72", "ATR-72", "AT76"),
    "E190": ("EMBRAER 190", "E190"),
    "CRJ9": ("CRJ-900", "CRJ9"),
    "A319": ("A319",),
    "A320": ("A320",),
    "A321": ("A321",),
    "B738": ("737-800", "737 800", "B738"),
    "B39M": ("737 MAX", "737MAX", "B39M"),
    "B752": ("757", "B752"),
    "A332": ("A330-200", "A332"),
    "A333": ("A330-300", "A330", "A333"),
    "A343": ("A340", "A343"),
    "A359": ("A350-900", "A350", "A359"),
    "A388": ("A380", "A388"),
    "B77W": ("777-300", "777", "B77W"),
    "B789": ("787-9", "787", "B789"),
}


def title_keywords(item: dict[str, Any]) -> tuple[str, ...]:
    """机型可用于标题匹配的关键词（去重、大写、最长匹配优先由调用方处理）。"""
    values: list[str] = []
    custom = str(item.get("title_keyword") or "").strip().upper()
    if custom:
        values.append(custom)
    icao = str(item.get("icao") or "").upper()
    values.extend(TITLE_KEYWORDS.get(icao, ()))
    if icao:
        values.append(icao)
    return tuple(dict.fromkeys(v for v in values if v))


# 公务机变体：与干线同 ICAO，唯一键 (icao, variant)
EXTRA_VARIANTS: list[dict[str, Any]] = [
    {
        "icao": "A343", "variant": "BIZJET", "name": "Airbus A340-300 (Bizjet)",
        "manufacturer": "Airbus", "role": "BIZJET", "demand_profile": "BIZJET",
        "allow_scheduled": False, "allow_charter": True, "charter_rate_per_hour": 12000,
        "cabin": {"first": 12, "business": 24, "premium_economy": 0, "economy": 0},
        "fare_multiplier": 1.5,
    },
    {
        "icao": "C25C", "variant": "BIZJET", "name": "Cessna Citation CJ4 (Charter)",
        "manufacturer": "Cessna", "role": "BIZJET", "demand_profile": "BIZJET",
        "allow_scheduled": False, "allow_charter": True, "charter_rate_per_hour": 2500,
        "cabin": {"first": 0, "business": 0, "premium_economy": 0, "economy": 9},
        "fare_multiplier": 1.2,
    },
]


def default_economy() -> dict[str, Any]:
    """docs/04 §7 的默认值（可在运营规则页修改）。"""
    return {
        "initial_balance": 5_000_000.0,
        "currency": "USD",
        "fare_economy_base": 25.0,
        "fare_economy_per_nm": 0.10,
        "fare_business_multiplier": 2.6,
        "fare_first_multiplier": 4.0,
        "cargo_rate": 0.45,
        "mail_rate": 0.30,
        "ancillary_per_pax": 6.0,
        "fuel_price": 1.05,
        "landing_per_ton": 24.0,
        "night_surcharge": 50.0,
        "handling_per_pax": 11.0,
        "handling_per_cargo_ton": 30.0,
        "crew_per_block_hour": 900.0,
        "maintenance_per_block_hour": 600.0,
        "maintenance_per_cycle": 60.0,
        "parking_per_hour": 20.0,
        "parking_free_hours": 2.0,
        "atc_per_nm": 0.70,
        "insurance_rate": 0.012,
        "load_factor_cap": 0.95,
        "business_ratio_large": 0.10,
        "business_ratio_medium": 0.06,
        "business_ratio_small": 0.03,
        "first_ratio_large": 0.02,
        "cargo_kg_per_pax": 8.0,
        "repeat_route_decay": 0.92,
        "repeat_route_floor": 0.5,
        "bizjet_load_min": 0.35,
        "bizjet_load_max": 0.80,
        "no_show_fee": 5000.0,
        "pilot_cancel_fee": 5000.0,
        "diversion_revenue_factor": 0.50,
        "cancel_cost_factor": 0.20,
        "on_time_bonus_factor": 1.02,
        "delay_penalty_factor": 0.95,
        "off_schedule_factor": 0.97,
        "time_tolerance_min": 15,
        "delay_threshold_min": 60,
        "off_schedule_threshold_min": 180,
    }


def default_policy() -> dict[str, Any]:
    """docs/04 §11.3 的默认异常与结算策略。"""
    return {
        "scope_mode": "COMPANY_ONLY",
        "default_action": "REVIEW",
        "reject_cost_mode": "FULL",
        "review_advance_ratio": 0.0,
        "review_sla_hours": 24,
        "min_payout_factor": 0.40,
        "rules": {
            "DATA_GAP": {"enabled": True, "action": "WEIGHTED",
                         "penalty_per_10min": 0.05, "max_penalty": 0.30},
            "SIM_RATE": {"enabled": True, "action": "WEIGHTED", "tiers": [
                {"gt": 2, "penalty": 0.20}, {"gt": 4, "penalty": 0.50},
                {"gt": 8, "action": "REJECT"}]},
            "PAUSE": {"enabled": True, "action": "WEIGHTED", "ratio_gt": 0.20, "penalty": 0.10},
            "TELEPORT": {"enabled": True, "action": "REJECT"},
            "FUEL_JUMP": {"enabled": True, "action": "REVIEW"},
            "TRACK_DISTANCE": {"enabled": True, "action": "REVIEW"},
            "MISSING_TRACK": {"enabled": True, "action": "REVIEW"},
        },
        "overrides": [],
    }


PARAM_SCHEMA: list[dict[str, Any]] = [
    # 初始资金只在建本机档案时生效，后续改动不影响余额，故不作为可调参数暴露
    {"key": "fare_economy_base", "group": "票价与收入", "label": "经济舱基础价", "unit": "USD", "min": 10, "max": 80, "step": 1},
    {"key": "fare_economy_per_nm", "group": "票价与收入", "label": "经济舱每海里", "unit": "USD/NM", "min": 0.03, "max": 0.30, "step": 0.01},
    {"key": "fare_business_multiplier", "group": "票价与收入", "label": "商务舱倍率", "unit": "×", "min": 1.8, "max": 4.0, "step": 0.1},
    {"key": "fare_first_multiplier", "group": "票价与收入", "label": "头等舱倍率", "unit": "×", "min": 3.0, "max": 6.0, "step": 0.1},
    {"key": "cargo_rate", "group": "票价与收入", "label": "货运单价", "unit": "USD/kg", "min": 0.2, "max": 1.0, "step": 0.05},
    {"key": "mail_rate", "group": "票价与收入", "label": "邮件单价", "unit": "USD/kg", "min": 0.1, "max": 0.8, "step": 0.05},
    {"key": "ancillary_per_pax", "group": "票价与收入", "label": "附加服务", "unit": "USD/客", "min": 0, "max": 20, "step": 1},
    {"key": "fuel_price", "group": "成本", "label": "燃油单价", "unit": "USD/kg", "min": 0.5, "max": 1.5, "step": 0.01},
    {"key": "landing_per_ton", "group": "成本", "label": "起降费", "unit": "USD/吨", "min": 5, "max": 30, "step": 1},
    {"key": "night_surcharge", "group": "成本", "label": "夜间附加", "unit": "USD", "min": 0, "max": 300, "step": 10},
    {"key": "handling_per_pax", "group": "成本", "label": "地面服务（客）", "unit": "USD/客", "min": 0, "max": 40, "step": 1},
    {"key": "handling_per_cargo_ton", "group": "成本", "label": "地面服务（货）", "unit": "USD/吨", "min": 0, "max": 100, "step": 5},
    {"key": "crew_per_block_hour", "group": "成本", "label": "机组", "unit": "USD/block h", "min": 200, "max": 1500, "step": 50},
    {"key": "maintenance_per_block_hour", "group": "成本", "label": "维护（小时）", "unit": "USD/block h", "min": 0, "max": 2000, "step": 50},
    {"key": "maintenance_per_cycle", "group": "成本", "label": "维护（循环）", "unit": "USD/循环", "min": 0, "max": 500, "step": 10},
    {"key": "atc_per_nm", "group": "成本", "label": "空管", "unit": "USD/NM", "min": 0, "max": 3, "step": 0.05},
    {"key": "insurance_rate", "group": "成本", "label": "保险", "unit": "收入比例", "min": 0, "max": 0.05, "step": 0.001},
    {"key": "load_factor_cap", "group": "需求与载客", "label": "载客率上限", "unit": "", "min": 0.5, "max": 1.0, "step": 0.01},
    {"key": "cargo_kg_per_pax", "group": "需求与载客", "label": "货物生成", "unit": "kg/客", "min": 2, "max": 15, "step": 1},
    {"key": "no_show_fee", "group": "惩罚", "label": "失约费", "unit": "USD", "min": 0, "max": 20000, "step": 500},
    {"key": "pilot_cancel_fee", "group": "惩罚", "label": "首段后取消费", "unit": "USD", "min": 0, "max": 20000, "step": 500},
    {"key": "diversion_revenue_factor", "group": "惩罚", "label": "备降收入系数", "unit": "", "min": 0.2, "max": 0.8, "step": 0.05},
]


def build_aircraft_types(catalog_items: list[dict[str, Any]], now: str | None = None) -> list[dict[str, Any]]:
    """把推荐用的机型目录补全为运营机型模板（含 A343/BIZJET 等变体）。"""
    stamp = now or utcnow()
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in catalog_items:
        icao = (item.get("icao") or "").upper()
        if not icao:
            continue
        category = item.get("category") or _guess_category(item)
        base = dict(CATEGORY_DEFAULTS["narrow"])
        base.update(CATEGORY_DEFAULTS.get(category, {}))
        base.update(SPEC_OVERRIDES.get(icao, {}))
        cabin = base.pop("cabin")
        row = {
            "id": new_id(), "icao": icao, "variant": "STANDARD",
            # 内置模板的标记：不可编辑/删除，只能「复制为自定义」
            "source": "BUILTIN", "builtin_key": f"{icao}:STANDARD",
            "name": item.get("name") or icao, "manufacturer": item.get("manufacturer"),
            "cabin_config_json": cabin,
            "cruise_speed_kt": item.get("cruise_speed_kt") or 440,
            "cruise_fl": item.get("cruise_fl") or 350,
            "min_runway_m": item.get("min_runway_m") or 1600,
            "range_nm": item.get("range_nm") or 3000,
            "pax_capacity": sum(int(v or 0) for v in cabin.values()),
            "wingspan_m": WINGSPAN_OVERRIDES.get(
                icao, WINGSPAN_BY_CATEGORY.get(category, 36.0)),
            "engine_count": 2, "engine_type": "JET",
            "wake_category": "M" if category in ("narrow", "regional") else ("H" if category == "wide" else "L"),
            "fare_multiplier": 1.0,
            "created_at": stamp,
        }
        for key in ("pax_capacity", "cargo_capacity_kg", "mtow_kg", "mzfw_kg", "mlw_kg", "oew_kg",
                    "fuel_capacity_kg", "fuel_burn_kg_h", "role", "demand_profile",
                    "allow_scheduled", "allow_charter", "charter_rate_per_hour", "lease_per_hour"):
            if key in base:
                row[key] = base[key]
        row["pax_capacity"] = int(base.get("pax_capacity") or row["pax_capacity"])
        rows.append(row)
        seen.add((icao, "STANDARD"))
    for variant in EXTRA_VARIANTS:
        key = (variant["icao"], variant["variant"])
        if key in seen:
            continue
        template = next((r for r in rows if r["icao"] == variant["icao"]), None)
        if template is None:
            continue
        row = dict(template)
        row.update({k: v for k, v in variant.items() if k != "cabin"})
        row["source"] = "BUILTIN"
        row["builtin_key"] = f"{variant['icao']}:{variant['variant']}"
        cabin = variant.get("cabin") or template["cabin_config_json"]
        row["cabin_config_json"] = cabin
        row["pax_capacity"] = sum(int(v or 0) for v in cabin.values())
        row["id"] = new_id()
        row["created_at"] = stamp
        rows.append(row)
    return rows


def _guess_category(item: dict[str, Any]) -> str:
    seats = int(item.get("pax_capacity") or 0)
    if item.get("category"):
        return str(item["category"])
    if seats and seats <= 10:
        return "ga"
    if seats and seats <= 110:
        return "regional"
    if seats and seats <= 230:
        return "narrow"
    return "wide"
