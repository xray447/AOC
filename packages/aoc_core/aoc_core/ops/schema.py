"""M2 单机运营模式的本地表（SQLite，无 company_id / 无账号）。

与 docs/03 §2 的对应关系：
- 公司实体 → `ops_profile`（本机档案，单条记录，余额与货币在此）
- `aircraft_type` / `aircraft` / `aircraft_lock` / `route` / `schedule_template` /
  `flight_instance` / `roster` / `roster_leg` / `load_sheet` / `settlement` /
  `ledger_entry` / `company_config_version` → 同名或 `ops_` 前缀
- 金额用 REAL（两位小数），时间用 TEXT（ISO8601 UTC），与 M1 一致
- 不使用 `app_user` / `company` / `web_session` / 邀请码 / 角色表
"""
from __future__ import annotations

from ..db import Database

OPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_profile (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icao_code TEXT,
    callsign_prefix TEXT,
    flight_prefix TEXT,
    base_airport_icao TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    balance REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aircraft_type (
    id TEXT PRIMARY KEY,
    icao TEXT NOT NULL,
    variant TEXT NOT NULL DEFAULT 'STANDARD',
    -- BUILTIN = 程序内置模板（不可改/删，只能复制为 CUSTOM）；CUSTOM = 玩家自己加的机型
    source TEXT NOT NULL DEFAULT 'BUILTIN',
    builtin_key TEXT,
    -- 可选：用 SimLink /status 的 aircraft_title 关键字自动匹配机型
    title_keyword TEXT,
    name TEXT,
    manufacturer TEXT,
    role TEXT NOT NULL DEFAULT 'AIRLINER',
    cabin_config_json TEXT,
    pax_capacity INTEGER NOT NULL DEFAULT 0,
    cargo_capacity_kg REAL NOT NULL DEFAULT 0,
    mtow_kg REAL NOT NULL DEFAULT 0,
    mzfw_kg REAL NOT NULL DEFAULT 0,
    mlw_kg REAL NOT NULL DEFAULT 0,
    oew_kg REAL NOT NULL DEFAULT 0,
    fuel_capacity_kg REAL NOT NULL DEFAULT 0,
    cruise_speed_kt REAL NOT NULL DEFAULT 440,
    cruise_fl INTEGER NOT NULL DEFAULT 350,
    fuel_burn_kg_h REAL NOT NULL DEFAULT 2400,
    min_runway_m INTEGER NOT NULL DEFAULT 1600,
    -- 翼展（米）：抽班/机型替换按「翼展 ≤ 跑道宽度推出的上限」过滤（docs/TODO §26）
    wingspan_m REAL NOT NULL DEFAULT 0,
    range_nm REAL NOT NULL DEFAULT 3000,
    engine_count INTEGER NOT NULL DEFAULT 2,
    engine_type TEXT,
    wake_category TEXT,
    demand_profile TEXT NOT NULL DEFAULT 'MASS',
    allow_scheduled INTEGER NOT NULL DEFAULT 1,
    allow_charter INTEGER NOT NULL DEFAULT 1,
    charter_rate_per_hour REAL NOT NULL DEFAULT 0,
    fare_multiplier REAL NOT NULL DEFAULT 1,
    lease_per_hour REAL NOT NULL DEFAULT 2000,
    created_at TEXT NOT NULL,
    UNIQUE (icao, variant)
);
CREATE TABLE IF NOT EXISTS aircraft (
    id TEXT PRIMARY KEY,
    type_id TEXT NOT NULL,
    registration TEXT NOT NULL UNIQUE,
    tail_number TEXT,
    livery TEXT,
    base_airport_icao TEXT,
    current_airport_icao TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    fuel_kg REAL,
    total_hours REAL NOT NULL DEFAULT 0,
    total_cycles INTEGER NOT NULL DEFAULT 0,
    condition_pct REAL NOT NULL DEFAULT 100,
    acquisition_type TEXT NOT NULL DEFAULT 'LEASE',
    purchase_price REAL,
    lease_per_hour REAL,
    depreciation_per_hour REAL,
    acquired_at TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aircraft_status ON aircraft(status);
CREATE TABLE IF NOT EXISTS aircraft_lock (
    id TEXT PRIMARY KEY,
    aircraft_id TEXT NOT NULL,
    roster_id TEXT,
    free_flight_id TEXT,
    flight_record_id TEXT,
    lock_type TEXT NOT NULL,
    status TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT,
    heartbeat_at TEXT,
    released_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_aircraft_lock_active
    ON aircraft_lock(aircraft_id) WHERE status IN ('HELD', 'IN_FLIGHT');
CREATE TABLE IF NOT EXISTS ops_route (
    id TEXT PRIMARY KEY,
    dep_icao TEXT NOT NULL,
    arr_icao TEXT NOT NULL,
    distance_nm REAL,
    block_minutes INTEGER,
    min_aircraft_category TEXT,
    default_route_string TEXT,
    default_sid TEXT,
    default_star TEXT,
    cruise_fl INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (dep_icao, arr_icao)
);
CREATE TABLE IF NOT EXISTS schedule_template (
    id TEXT PRIMARY KEY,
    route_id TEXT NOT NULL,
    flight_number TEXT NOT NULL,
    dep_local_time TEXT NOT NULL,
    days_of_week INTEGER NOT NULL DEFAULT 127,
    valid_from TEXT,
    valid_to TEXT,
    aircraft_type_id TEXT,
    turnaround_min INTEGER NOT NULL DEFAULT 45,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS flight_instance (
    id TEXT PRIMARY KEY,
    schedule_id TEXT,
    route_id TEXT,
    flight_number TEXT NOT NULL,
    dep_icao TEXT NOT NULL,
    arr_icao TEXT NOT NULL,
    scheduled_dep_utc TEXT NOT NULL,
    scheduled_arr_utc TEXT NOT NULL,
    aircraft_type_id TEXT,
    mission_type TEXT NOT NULL DEFAULT 'SCHEDULED',
    status TEXT NOT NULL DEFAULT 'SCHEDULED',
    assigned_aircraft_id TEXT,
    roster_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (flight_number, scheduled_dep_utc)
);
CREATE INDEX IF NOT EXISTS idx_instance_dep ON flight_instance(scheduled_dep_utc);
CREATE TABLE IF NOT EXISTS roster (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'ROSTER',
    aircraft_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'LOCKED',
    base_airport_icao TEXT,
    window_start_utc TEXT NOT NULL,
    window_end_utc TEXT NOT NULL,
    constraints_json TEXT,
    redraw_count INTEGER NOT NULL DEFAULT 0,
    locked_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    expires_at TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_roster_status ON roster(status);
CREATE TABLE IF NOT EXISTS roster_leg (
    id TEXT PRIMARY KEY,
    roster_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    flight_instance_id TEXT,
    status TEXT NOT NULL DEFAULT 'PLANNED',
    planned_dep_utc TEXT,
    planned_arr_utc TEXT,
    actual_dep_utc TEXT,
    actual_arr_utc TEXT,
    dep_icao TEXT,
    arr_icao TEXT,
    flight_record_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (roster_id, sequence)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_roster_leg_instance
    ON roster_leg(flight_instance_id) WHERE status IN ('PLANNED', 'IN_PROGRESS');
CREATE TABLE IF NOT EXISTS free_flight (
    id TEXT PRIMARY KEY,
    aircraft_id TEXT NOT NULL,
    flight_instance_id TEXT,
    dep_icao TEXT NOT NULL,
    arr_icao TEXT NOT NULL,
    dep_time_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'LOCKED',
    lock_expires_at TEXT,
    flight_record_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_free_flight_status ON free_flight(status);
CREATE TABLE IF NOT EXISTS load_sheet (
    id TEXT PRIMARY KEY,
    flight_record_id TEXT,
    flight_instance_id TEXT,
    aircraft_id TEXT NOT NULL,
    aircraft_type_id TEXT,
    seed TEXT NOT NULL,
    dep_icao TEXT,
    arr_icao TEXT,
    distance_nm REAL,
    block_minutes REAL,
    pax_total INTEGER NOT NULL DEFAULT 0,
    pax_economy INTEGER NOT NULL DEFAULT 0,
    pax_premium_economy INTEGER NOT NULL DEFAULT 0,
    pax_business INTEGER NOT NULL DEFAULT 0,
    pax_first INTEGER NOT NULL DEFAULT 0,
    cargo_kg REAL NOT NULL DEFAULT 0,
    mail_kg REAL NOT NULL DEFAULT 0,
    oew_kg REAL,
    zfw_kg REAL,
    tow_kg REAL,
    fuel_kg REAL,
    estimated_revenue REAL,
    estimated_cost REAL,
    breakdown_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (flight_record_id)
);
CREATE TABLE IF NOT EXISTS economy_snapshot (
    id TEXT PRIMARY KEY,
    flight_record_id TEXT,
    config_version INTEGER NOT NULL,
    params_json TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    policy_sources_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (flight_record_id)
);
CREATE TABLE IF NOT EXISTS settlement (
    id TEXT PRIMARY KEY,
    flight_record_id TEXT NOT NULL UNIQUE,
    task_kind TEXT,
    roster_id TEXT,
    roster_leg_id TEXT,
    free_flight_id TEXT,
    aircraft_id TEXT,
    config_version INTEGER,
    revenue_gross REAL NOT NULL DEFAULT 0,
    revenue_total REAL NOT NULL DEFAULT 0,
    cost_total REAL NOT NULL DEFAULT 0,
    profit REAL NOT NULL DEFAULT 0,
    payout_factor REAL NOT NULL DEFAULT 1,
    advance_amount REAL NOT NULL DEFAULT 0,
    policy_action TEXT NOT NULL DEFAULT 'ACCEPT',
    policy_snapshot_json TEXT,
    policy_breakdown_json TEXT,
    breakdown_json TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    review_status TEXT NOT NULL DEFAULT 'NONE',
    reviewed_at TEXT,
    review_note TEXT,
    computed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_settlement_status ON settlement(status);
CREATE TABLE IF NOT EXISTS ledger_entry (
    id TEXT PRIMARY KEY,
    flight_record_id TEXT,
    settlement_id TEXT,
    entry_type TEXT NOT NULL,
    amount REAL NOT NULL,
    balance_after REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    description TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_flight ON ledger_entry(flight_record_id);
CREATE TABLE IF NOT EXISTS ops_config (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ops_config_version (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PUBLISHED',
    note TEXT,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ops_config_history (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (version, key)
);
CREATE TABLE IF NOT EXISTS ops_audit (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    before_json TEXT,
    after_json TEXT,
    reason TEXT,
    actor TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON ops_audit(created_at DESC);
CREATE TABLE IF NOT EXISTS ops_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- §36 兜底 C（1.4）：手工跑道覆盖。场景库扫不到 / 玩家装了 add-on 机场时用，
-- find_runway() 优先读它（source=override），不影响 navdata 原库。
CREATE TABLE IF NOT EXISTS airport_runway_override (
    icao TEXT NOT NULL,
    ident TEXT NOT NULL,
    length_m REAL,
    width_m REAL,
    threshold_lat REAL,
    threshold_lon REAL,
    hdg REAL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (icao, ident)
);
-- docs/12 §7.1：预计/实际停机位（一段航班一条；改派留 before/after 到 ops_audit）
CREATE TABLE IF NOT EXISTS flight_stand (
    flight_record_id TEXT PRIMARY KEY,
    airport_icao     TEXT NOT NULL,
    stand_ident      TEXT,
    stand_name TEXT, stand_number INTEGER, stand_suffix TEXT,
    stand_type       TEXT,
    lat REAL, lon REAL, heading REAL, radius_m REAL, has_jetway INTEGER,
    source           TEXT NOT NULL,
    terminal         TEXT,
    terminal_source  TEXT,
    score_json       TEXT,
    status           TEXT NOT NULL DEFAULT 'PROPOSED',
    eta_min_at_pick  REAL, remaining_nm_at_pick REAL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flight_stand_airport ON flight_stand(airport_icao);
-- 到机位的真实样本（落地/收尾时写）：校验场景库编号 + 给无机位机场补候选
CREATE TABLE IF NOT EXISTS stand_sample (
    id TEXT PRIMARY KEY,
    airport_icao TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
    heading REAL, stand_ident TEXT,
    flight_record_id TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stand_sample_airport ON stand_sample(airport_icao);
-- 手工机位覆盖（与 airport_runway_override 同模式）
CREATE TABLE IF NOT EXISTS airport_stand_override (
    icao TEXT NOT NULL, stand_ident TEXT NOT NULL,
    lat REAL NOT NULL, lon REAL NOT NULL, heading REAL, radius_m REAL,
    has_jetway INTEGER, stand_type TEXT, note TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY (icao, stand_ident)
);
-- 通知收件箱（多消费者共用一条队列：前端 / Tauri Rust / 便携启动器）
CREATE TABLE IF NOT EXISTS flight_notice (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL,
    flight_record_id TEXT, airport_icao TEXT,
    title TEXT NOT NULL, body TEXT NOT NULL, payload_json TEXT,
    created_at TEXT NOT NULL, ack_by TEXT, ack_at TEXT,
    UNIQUE (flight_record_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_flight_notice_created ON flight_notice(created_at DESC);
-- docs/12 §4.5：机场事实（T1 是「哪一片机位」）与承运人规则（T1 给谁用）分两张表
CREATE TABLE IF NOT EXISTS airport_terminal (
    icao TEXT NOT NULL, terminal TEXT NOT NULL,
    matchers_json TEXT NOT NULL,
    note TEXT, source TEXT NOT NULL DEFAULT 'USER',
    verified_at TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY (icao, terminal)
);
CREATE TABLE IF NOT EXISTS terminal_rule (
    id TEXT PRIMARY KEY,
    icao TEXT NOT NULL, terminal TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'BOTH',
    airlines_json TEXT NOT NULL DEFAULT '[]',
    priority INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_terminal_rule_icao ON terminal_rule(icao);
"""


def ensure_schema(db: Database) -> None:
    with db.session() as con:
        con.executescript(OPS_SCHEMA)
        # 老库补列：`CREATE TABLE IF NOT EXISTS` 不会给已存在的表加列
        existing = {row["name"] for row in con.execute("pragma table_info(ops_profile)")}
        for name in ("flight_prefix",):
            if name not in existing:
                con.execute(f"alter table ops_profile add column {name} TEXT")
        # docs/12 §4.5：公司级承运人代码（多值，逗号分隔：9C,HBH,CXA）
        if "airline_codes" not in existing:
            con.execute("alter table ops_profile add column airline_codes TEXT")
        # 机型模板：老库补 source/builtin_key/title_keyword（内置模板统一标 BUILTIN）
        type_cols = {row["name"] for row in con.execute("pragma table_info(aircraft_type)")}
        for name, ddl in (("source", "TEXT NOT NULL DEFAULT 'BUILTIN'"),
                          ("builtin_key", "TEXT"), ("title_keyword", "TEXT"),
                          ("wingspan_m", "REAL NOT NULL DEFAULT 0")):
            if name not in type_cols:
                con.execute(f"alter table aircraft_type add column {name} {ddl}")
        con.execute("update aircraft_type set source='BUILTIN' where source is null or source=''")
        # 老库没有翼展：按最短跑道给一个保守值（36/52/60.3/65 m），内置模板随后可被覆盖
        con.execute(
            "update aircraft_type set wingspan_m = case "
            "when min_runway_m < 1800 then 36 when min_runway_m < 2500 then 52 "
            "when min_runway_m < 3200 then 60.3 else 65 end "
            "where wingspan_m is null or wingspan_m <= 0")
        con.execute("update aircraft_type set builtin_key = upper(icao) || ':' || upper(variant) "
                    "where builtin_key is null and source='BUILTIN'")
