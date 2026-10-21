"""AOC 数据契约。

约定（见 docs/03）：
* 时间一律 ISO 8601 UTC 字符串（"Z" 结尾）；
* 距离 NM、高度 ft、重量 kg、速度 kt、垂直速度 fpm；
* 可选字段尽量给默认值，保证前向兼容（客户端忽略未知字段）。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0.0"

Theme = Literal["system", "light", "dark"]
Language = Literal["zh", "en"]
Density = Literal["adaptive", "fixed_1hz", "fixed_2hz"]
FlightMode = Literal["PERSONAL", "ROSTER", "FREE"]
FlightStatus = Literal["RECORDING", "COMPLETED", "DIVERTED", "ABORTED", "CRASHED", "ABANDONED"]
LandingRating = Literal["GREAT", "GOOD", "HARD", "SEVERE", "UNKNOWN"]
RouteStatus = Literal["OK", "REQUIRES_SIMBRIEF", "NO_ROUTE", "NO_AIRPORT", "NAVDATA_MISSING"]
RouteSource = Literal["AIP", "GRAPH", "NONE"]
CoverageState = Literal["AIP", "HIGH_ALT_AIRWAY", "NO_HIGH_ALT", "OCEANIC", "NO_DATA"]
FlownSource = Literal["AOC", "VOLANTA", "CSV", "MANUAL"]


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# --------------------------------------------------------------------------
# 设置
# --------------------------------------------------------------------------
class Units(Model):
    altitude: Literal["ft", "m"] = "ft"
    speed: Literal["kt", "kmh"] = "kt"
    weight: Literal["kg", "lb"] = "kg"


class RecommendPrefs(Model):
    only_never_visited: bool = True
    prefer_new_country: bool = True
    max_distance_nm: int | None = None
    min_runway_m: int = 1200
    random_seed: int | None = None


class Settings(Model):
    theme: Theme = "system"
    language: Language = "zh"
    units: Units = Field(default_factory=Units)
    auto_start: bool = True
    auto_stop: bool = True
    record_taxi: bool = True
    density: Density = "adaptive"
    max_gap_s: int = Field(default=45, ge=5, le=120)
    turn_threshold_dps: float = Field(default=4.0, ge=1.0, le=12.0)
    navdata_path: str | None = None
    aip_path: str | None = None
    # None = 用内置 jp-routes 地址自动同步；"" = 关闭
    aip_url: str | None = None
    aip_auto_sync: bool = True
    network_pkl: str | None = None
    pre_train_dir: str | None = None
    volanta_enabled: bool = False
    volanta_auto_sync: bool = True
    # 底图：离线经纬网 / OSM / CARTO 系列 / Esri 卫星 / 自定义瓦片；dark/light/satellite 为旧值别名
    map_style: Literal[
        "offline", "osm", "carto_light", "carto_dark", "carto_voyager",
        "esri_satellite", "custom",
        "dark", "light", "satellite",
    ] = "osm"
    tiles_url: str | None = None
    onboarded: bool = False
    recommend: RecommendPrefs = Field(default_factory=RecommendPrefs)
    home_airport: str | None = None
    callsign: str = "AOC001"
    aircraft_type: str = "A320"


# --------------------------------------------------------------------------
# 航路
# --------------------------------------------------------------------------
class ProcedureOption(Model):
    name: str
    runway: str | None = None
    source: str = "navdata"


class RunwayOption(Model):
    airport: str
    ident: str
    heading: float | None = None
    length_m: float | None = None
    ils: bool | None = None


class CoverageGap(Model):
    start_nm: float
    end_nm: float
    center_lat: float | None = None
    center_lon: float | None = None
    length_nm: float | None = None


class RouteAttempt(Model):
    provider: str
    status: str
    reason: str = ""
    ms: float = 0.0


class RouteRequest(Model):
    dep: str
    arr: str
    aircraft_type: str | None = None
    cruise_fl: int = 350
    avoid: list[str] = Field(default_factory=list)
    force_graph: bool = False


class RouteResult(Model):
    dep: str = ""
    arr: str = ""
    status: RouteStatus = "NO_ROUTE"
    route_source: RouteSource = "NONE"
    coverage: CoverageState = "NO_DATA"
    altitude_valid: bool | None = None
    requires_simbrief: bool = True
    simbrief_url: str = ""
    route: str | None = None
    tokens: list[str] = Field(default_factory=list)
    tokens_full: list[str] = Field(default_factory=list)
    distance_nm: float | None = None
    gcd_nm: float | None = None
    cruise_fl: int = 350
    sid_options: list[ProcedureOption] = Field(default_factory=list)
    star_options: list[ProcedureOption] = Field(default_factory=list)
    runway_options: list[RunwayOption] = Field(default_factory=list)
    valid: bool = False
    warnings: list[str] = Field(default_factory=list)
    coverage_gaps: list[CoverageGap] = Field(default_factory=list)
    airac: str | None = None
    aip_version: str | None = None
    coverage_version: str | None = None
    attempts: list[RouteAttempt] = Field(default_factory=list)
    elapsed_ms: float = 0.0


class CoverageRequest(Model):
    dep: str
    arr: str
    cruise_fl: int = 350


class CoverageResult(Model):
    coverage: CoverageState = "NO_DATA"
    requires_simbrief: bool = True
    checked: bool = False
    gcd_nm: float | None = None
    coverage_gaps: list[CoverageGap] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ValidateRouteRequest(Model):
    tokens: list[str] | str
    cruise_fl: int | None = None


class ValidateRouteResult(Model):
    valid: bool | None = None
    altitude_valid: bool | None = None
    violations: list[dict[str, Any]] = Field(default_factory=list)
    unknown: int = 0
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 机场 / navdata
# --------------------------------------------------------------------------
class AirportOut(Model):
    icao: str
    iata: str | None = None
    name: str | None = None
    city: str | None = None
    country: str | None = None
    lat: float
    lon: float
    elev_ft: float | None = None
    longest_runway_m: float | None = None
    visited: bool = False


class NavdataStatus(Model):
    available: bool = False
    path: str | None = None
    airac: str | None = None
    version: str | None = None
    airports: int = 0
    runways: int = 0
    airways: int = 0
    error: str | None = None
    coverage_ready: bool = False


# --------------------------------------------------------------------------
# 推荐
# --------------------------------------------------------------------------
class RecommendRequest(Model):
    available_minutes: int = Field(default=90, ge=20, le=1080)
    base_icao: str | None = None
    aircraft_type: str | None = None
    only_never_visited: bool = True
    prefer_new_country: bool = True
    max_distance_nm: int | None = None
    min_runway_m: int | None = None
    limit: int = Field(default=8, ge=1, le=20)
    random_seed: int | None = None


class RecommendCandidate(Model):
    icao: str
    iata: str | None = None
    name: str | None = None
    city: str | None = None
    country: str | None = None
    lat: float
    lon: float
    distance_nm: float
    block_minutes_min: int
    block_minutes_max: int
    block_minutes: int
    longest_runway_m: float | None = None
    visited: bool = False
    reasons: list[str] = Field(default_factory=list)
    score: float = 0.0


class RecommendResponse(Model):
    base_icao: str
    generated_at: str
    candidates: list[RecommendCandidate] = Field(default_factory=list)
    candidates_considered: int = 0
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 已飞航段
# --------------------------------------------------------------------------
class FlownLegIn(Model):
    dep_icao: str
    arr_icao: str
    flight_date: str | None = None
    aircraft_type: str | None = None
    duration_min: int | None = None
    landing_rate_fpm: float | None = None
    source: FlownSource = "MANUAL"
    external_id: str | None = None


class FlownLegOut(FlownLegIn):
    id: str
    created_at: str


class VolantaSyncRequest(Model):
    token: str | None = None
    csv_text: str | None = None


class VolantaSyncResult(Model):
    ok: bool
    source: str = "VOLANTA"
    legs_found: int = 0
    legs_imported: int = 0
    # 完整航班记录（含原始 JSON）与轨迹的入库数量
    flights_stored: int = 0
    tracks_stored: int = 0
    diagnostic: str = ""
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 飞行记录 / 轨迹 / 事件
# --------------------------------------------------------------------------
class LandingMetrics(Model):
    touchdown_vs_fpm: float | None = None
    touchdown_g: float | None = None
    max_g_landing: float | None = None
    max_g_flight: float | None = None
    touchdown_lat: float | None = None
    touchdown_lon: float | None = None
    runway_ident: str | None = None
    runway_airport: str | None = None
    threshold_distance_m: float | None = None
    centerline_offset_m: float | None = None
    bounce_count: int = 0
    landing_distance_m: float | None = None
    landing_rating: LandingRating = "UNKNOWN"


class FlightEventOut(Model):
    id: str | None = None
    t_offset_ms: int
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class TrackPoint(Model):
    t: float
    lat: float
    lon: float
    alt_ft: float | None = None
    agl_ft: float | None = None
    gs_kt: float | None = None
    ias_kt: float | None = None
    vs_fpm: float | None = None
    hdg_true: float | None = None
    pitch_deg: float | None = None
    bank_deg: float | None = None
    fuel_kg: float | None = None
    g: float | None = None
    on_ground: bool | None = None
    mode: str | None = None


class TrackOut(Model):
    flight_id: str
    points: list[TrackPoint] = Field(default_factory=list)
    segments: list[dict[str, Any]] = Field(default_factory=list)
    events: list[FlightEventOut] = Field(default_factory=list)
    total_points: int = 0
    raw_points: int = 0
    fidelity_m: float | None = None
    encoding: str = "BIN_V1"


class FlightRecordOut(Model):
    id: str
    mode: FlightMode = "PERSONAL"
    status: FlightStatus = "RECORDING"
    callsign: str | None = None
    aircraft_type: str | None = None
    aircraft_title: str | None = None
    airac: str | None = None
    dep_icao: str | None = None
    arr_icao: str | None = None
    block_off_utc: str | None = None
    takeoff_utc: str | None = None
    landing_utc: str | None = None
    block_on_utc: str | None = None
    block_minutes: float | None = None
    route_string: str | None = None
    route_source: str | None = None
    coverage: str | None = None
    altitude_valid: bool | None = None
    distance_nm: float | None = None
    fuel_start_kg: float | None = None
    fuel_end_kg: float | None = None
    fuel_used_kg: float | None = None
    max_g_flight: float | None = None
    max_g_landing: float | None = None
    touchdown_g: float | None = None
    touchdown_vs_fpm: float | None = None
    touchdown_lat: float | None = None
    touchdown_lon: float | None = None
    runway_ident: str | None = None
    threshold_distance_m: float | None = None
    centerline_offset_m: float | None = None
    bounce_count: int | None = None
    landing_distance_m: float | None = None
    landing_rating: LandingRating | None = None
    track_points: int | None = None
    track_bytes: int | None = None
    track_fidelity_m: float | None = None
    track_sha256: str | None = None
    data_gap_seconds: float | None = None
    validation_status: str | None = None
    anomaly_flags: list[str] = Field(default_factory=list)
    notes: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class FlightListResponse(Model):
    items: list[FlightRecordOut] = Field(default_factory=list)
    total: int = 0
    next_cursor: str | None = None


class RecordingStatus(Model):
    active: bool = False
    flight_id: str | None = None
    started_at: str | None = None
    samples: int = 0
    phase: str = "PREFLIGHT"
    simlink_connected: bool = False
    simlink_version: str | None = None
    sim_connected: bool = False
    aircraft_title: str | None = None
    last_error: str | None = None


# --------------------------------------------------------------------------
# 统计
# --------------------------------------------------------------------------
class MonthlyCount(Model):
    month: str
    flights: int = 0
    minutes: float = 0
    distance_nm: float = 0


class StatsOut(Model):
    flights: int = 0
    total_minutes: float = 0
    total_distance_nm: float = 0
    airports: int = 0
    countries: int = 0
    aircraft_types: int = 0
    avg_landing_vs_fpm: float | None = None
    max_g_flight: float | None = None
    landing_ratings: dict[str, int] = Field(default_factory=dict)
    monthly: list[MonthlyCount] = Field(default_factory=list)
    top_aircraft: list[dict[str, Any]] = Field(default_factory=list)
    distinct_airports: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 飞行阶段 / 事件（SimLink → aoc-core）
# --------------------------------------------------------------------------
class Phase:
    PREFLIGHT = "PREFLIGHT"
    TAXI = "TAXI"
    TAKEOFF = "TAKEOFF"
    CLIMB = "CLIMB"
    CRUISE = "CRUISE"
    DESCENT = "DESCENT"
    APPROACH = "APPROACH"
    LANDING = "LANDING"
    TAXI_IN = "TAXI_IN"
    SHUTDOWN = "SHUTDOWN"


class ExportRequest(Model):
    flight_ids: list[str] = Field(default_factory=list)
    format: Literal["zip", "gpx", "csv", "json"] = "zip"


class ExportResult(Model):
    ok: bool
    path: str
    bytes: int
    format: str
