export interface Units {
  altitude: "ft" | "m";
  speed: "kt" | "kmh";
  weight: "kg" | "lb";
}

export interface Settings {
  theme: "system" | "light" | "dark";
  language: "zh" | "en";
  units: Units;
  auto_start: boolean;
  auto_stop: boolean;
  record_taxi: boolean;
  density: "adaptive" | "fixed_1hz" | "fixed_2hz";
  max_gap_s: number;
  turn_threshold_dps: number;
  navdata_path: string | null;
  aip_path: string | null;
  network_pkl: string | null;
  pre_train_dir: string | null;
  volanta_enabled: boolean;
  volanta_auto_sync: boolean;
  map_style:
    | "offline"
    | "osm"
    | "carto_light"
    | "carto_dark"
    | "carto_voyager"
    | "esri_satellite"
    | "custom"
    | "dark"
    | "light"
    | "satellite";
  tiles_url: string | null;
  onboarded: boolean;
  recommend: {
    only_never_visited: boolean;
    prefer_new_country: boolean;
    max_distance_nm: number | null;
    min_runway_m: number;
    random_seed: number | null;
  };
  home_airport: string | null;
  callsign: string;
  aircraft_type: string;
  [key: string]: unknown;
}

export interface NavdataStatus {
  available: boolean;
  path: string | null;
  airac: string | null;
  version: string | null;
  airports: number;
  runways: number;
  airways: number;
  error: string | null;
  coverage_ready: boolean;
}

export interface Airport {
  icao: string;
  iata?: string | null;
  name?: string | null;
  city?: string | null;
  country?: string | null;
  lat: number;
  lon: number;
  elev_ft?: number | null;
  longest_runway_m?: number | null;
  visited?: boolean;
}

/** 跑道几何（入口坐标 + 真航向 + 长度），跑道接地区俯视图用。 */
export interface AirportRunway {
  ident?: string | null;
  heading?: number | null;
  length_m?: number | null;
  ils?: boolean | null;
  lat?: number | null;
  lon?: number | null;
  elev_ft?: number | null;
  /** 内移入口（米）：着陆入口 = 物理入口 + 内移；旧库或缺失时为 0。 */
  displaced_threshold_m?: number | null;
}

export interface AirportDetail extends Airport {
  runways: AirportRunway[];
}

export interface Candidate {
  icao: string;
  iata?: string | null;
  name?: string | null;
  city?: string | null;
  country?: string | null;
  lat: number;
  lon: number;
  distance_nm: number;
  block_minutes: number;
  block_minutes_min: number;
  block_minutes_max: number;
  longest_runway_m?: number | null;
  visited: boolean;
  reasons: string[];
  score: number;
}

export interface RecommendResult {
  base_icao: string;
  generated_at: string;
  candidates: Candidate[];
  candidates_considered: number;
  warnings: string[];
}

export interface ProcedureOption {
  name: string;
  runway?: string | null;
  source?: string;
}

export interface RunwayOption {
  airport: string;
  ident: string;
  heading?: number | null;
  length_m?: number | null;
  ils?: boolean | null;
}

export interface CoverageGap {
  start_nm: number;
  end_nm: number;
  center_lat?: number | null;
  center_lon?: number | null;
  length_nm?: number | null;
}

export interface RouteResult {
  dep: string;
  arr: string;
  status: "OK" | "REQUIRES_SIMBRIEF" | "NO_ROUTE" | "NO_AIRPORT" | "NAVDATA_MISSING";
  route_source: "AIP" | "GRAPH" | "NONE";
  coverage: "AIP" | "HIGH_ALT_AIRWAY" | "NO_HIGH_ALT" | "OCEANIC" | "NO_DATA";
  altitude_valid: boolean | null;
  requires_simbrief: boolean;
  simbrief_url: string;
  route: string | null;
  tokens: string[];
  tokens_full: string[];
  distance_nm: number | null;
  gcd_nm: number | null;
  cruise_fl: number;
  sid_options: ProcedureOption[];
  star_options: ProcedureOption[];
  runway_options: RunwayOption[];
  valid: boolean;
  warnings: string[];
  coverage_gaps: CoverageGap[];
  airac: string | null;
  aip_version: string | null;
  coverage_version: string | null;
  attempts: { provider: string; status: string; reason: string; ms: number }[];
  elapsed_ms: number;
}

export interface TrackPoint {
  t: number;
  lat: number;
  lon: number;
  alt_ft?: number | null;
  gs_kt?: number | null;
  ias_kt?: number | null;
  vs_fpm?: number | null;
  hdg_true?: number | null;
  fuel_kg?: number | null;
  g?: number | null;
  mode?: string | null;
}

export interface FlightEvent {
  id?: string;
  t_offset_ms: number;
  type: string;
  payload: Record<string, unknown>;
}

export interface TrackData {
  flight_id: string;
  points: TrackPoint[];
  segments: { seq: number; mode: string; start_t: number; end_t: number; points: number; bytes?: number }[];
  events: FlightEvent[];
  total_points: number;
  raw_points?: number | null;
  fidelity_m?: number | null;
  encoding: string;
}

export interface FlightRecord {
  id: string;
  mode: string;
  status: string;
  callsign?: string | null;
  aircraft_type?: string | null;
  aircraft_title?: string | null;
  airac?: string | null;
  dep_icao?: string | null;
  arr_icao?: string | null;
  block_off_utc?: string | null;
  takeoff_utc?: string | null;
  landing_utc?: string | null;
  block_on_utc?: string | null;
  block_minutes?: number | null;
  distance_nm?: number | null;
  fuel_start_kg?: number | null;
  fuel_end_kg?: number | null;
  fuel_used_kg?: number | null;
  actual_zfw_kg?: number | null;
  zfw_delta_kg?: number | null;
  max_g_flight?: number | null;
  max_g_landing?: number | null;
  touchdown_g?: number | null;
  touchdown_vs_fpm?: number | null;
  touchdown_lat?: number | null;
  touchdown_lon?: number | null;
  runway_ident?: string | null;
  threshold_distance_m?: number | null;
  /** 着陆入口内移量（米），距入口距离已扣掉这段。 */
  displaced_threshold_m?: number | null;
  centerline_offset_m?: number | null;
  bounce_count?: number | null;
  landing_distance_m?: number | null;
  landing_rating?: string | null;
  track_points?: number | null;
  track_bytes?: number | null;
  track_fidelity_m?: number | null;
  validation_status?: string | null;
  anomaly_flags?: string[];
  notes?: string | null;
  created_at?: string | null;
}

export interface FlightList {
  items: FlightRecord[];
  total: number;
  next_cursor: string | null;
}

export interface Stats {
  flights: number;
  total_minutes: number;
  total_distance_nm: number;
  airports: number;
  countries: number;
  aircraft_types: number;
  avg_landing_vs_fpm: number | null;
  max_g_flight: number | null;
  landing_ratings: Record<string, number>;
  monthly: { month: string; flights: number; minutes: number; distance_nm: number }[];
  top_aircraft: { icao: string; flights: number }[];
  distinct_airports: string[];
}

export interface RecordingStatus {
  active: boolean;
  flight_id: string | null;
  started_at: string | null;
  samples: number;
  phase: string;
  engine_seconds: number;
  flight_seconds: number;
  engine_estimated: boolean;
  simlink_connected: boolean;
  simlink_version: string | null;
  sim_connected: boolean;
  aircraft_title: string | null;
  last_error: string | null;
}

export interface Bootstrap {
  token: string;
  version: string;
  url: string;
  home: string;
  db: string;
  navdata: NavdataStatus;
  recording: RecordingStatus;
  simlink: { configured: boolean; connected: boolean; version: string | null };
  started_at: string;
}

export interface ImportedFlight {
  id: string;
  source: string;
  external_id?: string | null;
  callsign?: string | null;
  registration?: string | null;
  dep_icao: string | null;
  arr_icao: string | null;
  flight_date?: string | null;
  aircraft_type?: string | null;
  duration_min?: number | null;
  landing_rate_fpm?: number | null;
  point_count: number;
  imported_at: string;
  updated_at: string;
}

export interface MapData {
  airports: {
    icao: string;
    lat: number | null;
    lon: number | null;
    country?: string | null;
    name?: string | null;
    iata?: string | null;
    city?: string | null;
    elev_ft?: number | null;
  }[];
  legs: { dep: string; arr: string; count: number; sources?: string[] }[];
  flights: { id: string; dep_icao: string; arr_icao: string; block_off_utc?: string; aircraft_type?: string; landing_rating?: string }[];
  imported_flights?: ImportedFlight[];
}

export interface AircraftType {
  icao: string;
  name: string;
  cruise_speed_kt: number;
  cruise_fl: number;
  min_runway_m: number;
  range_nm: number;
  category?: string;
}

// ---------------------------------------------------------------- 运营模式（M2）
export interface OpsProfile {
  id: string;
  name: string;
  icao_code: string | null;
  callsign_prefix: string | null;
  flight_prefix: string | null;
  base_airport_icao: string | null;
  currency: string;
  balance: number;
  no_show_count: number;
}

export interface CabinConfig {
  first: number;
  business: number;
  premium_economy: number;
  economy: number;
}

export interface OpsAircraftType {
  id: string;
  icao: string;
  variant: string;
  name: string | null;
  manufacturer: string | null;
  role: string;
  demand_profile: string;
  cabin_config_json: CabinConfig;
  pax_capacity: number;
  cargo_capacity_kg: number;
  mtow_kg: number;
  mzfw_kg: number;
  mlw_kg: number;
  oew_kg: number;
  fuel_capacity_kg: number;
  cruise_speed_kt: number;
  cruise_fl: number;
  fuel_burn_kg_h: number;
  min_runway_m: number;
  range_nm: number;
  allow_scheduled: boolean;
  allow_charter: boolean;
  charter_rate_per_hour: number;
  fare_multiplier: number;
  lease_per_hour: number;
}

export interface OpsLock {
  id: string;
  lock_type: string;
  status: string;
  roster_id: string | null;
  free_flight_id: string | null;
  expires_at: string | null;
}

export interface OpsAircraft {
  id: string;
  type_id: string;
  registration: string;
  tail_number: string | null;
  livery: string | null;
  base_airport_icao: string | null;
  current_airport_icao: string | null;
  status: string;
  fuel_kg: number | null;
  total_hours: number;
  total_cycles: number;
  condition_pct: number;
  acquisition_type: string;
  lease_per_hour: number | null;
  version: number;
  type_icao?: string | null;
  type_variant?: string | null;
  type_name?: string | null;
  type_role?: string | null;
  pax_capacity?: number | null;
  range_nm?: number | null;
  min_runway_m?: number | null;
  mtow_kg?: number | null;
  locked?: boolean;
  lock?: OpsLock | null;
}

export interface OpsRoute {
  id: string;
  dep_icao: string;
  arr_icao: string;
  distance_nm: number | null;
  block_minutes: number | null;
  default_route_string: string | null;
  default_sid: string | null;
  default_star: string | null;
  cruise_fl: number | null;
  min_aircraft_category: string | null;
  enabled: boolean;
}

export interface OpsSchedule {
  id: string;
  route_id: string;
  flight_number: string;
  dep_local_time: string;
  days_of_week: number;
  valid_from: string | null;
  valid_to: string | null;
  aircraft_type_id: string | null;
  turnaround_min: number;
  enabled: boolean;
  dep_icao?: string | null;
  arr_icao?: string | null;
  distance_nm?: number | null;
  block_minutes?: number | null;
  type_icao?: string | null;
  type_variant?: string | null;
}

export interface OpsInstance {
  id: string;
  flight_number: string;
  dep_icao: string;
  arr_icao: string;
  scheduled_dep_utc: string;
  scheduled_arr_utc: string;
  status: string;
  mission_type: string;
  aircraft_type_id: string | null;
  route_id: string | null;
}

export interface OpsLeg {
  id: string;
  roster_id: string;
  sequence: number;
  flight_instance_id: string | null;
  status: string;
  planned_dep_utc: string | null;
  planned_arr_utc: string | null;
  actual_dep_utc: string | null;
  actual_arr_utc: string | null;
  dep_icao: string | null;
  arr_icao: string | null;
  flight_record_id: string | null;
  flight_number?: string | null;
  callsign?: string | null;
  mission_type?: string | null;
}

export interface OpsCandidateLeg {
  flight_instance_id: string;
  flight_number: string;
  callsign?: string | null;
  dep: string;
  arr: string;
  scheduled_dep_utc: string;
  scheduled_arr_utc: string;
  block_minutes: number;
  distance_nm: number;
  estimated_revenue: number;
}

export interface OpsCandidate {
  aircraft: {
    id: string;
    registration: string;
    type_id: string;
    type: string;
    variant: string;
    current_airport_icao: string | null;
  };
  legs: OpsCandidateLeg[];
  total_block_minutes: number;
  total_distance_nm: number;
  estimated_revenue: number;
  estimated_cost: number;
  estimated_profit: number;
  score: number;
  reasons: string[];
  candidate_token: string;
}

export interface OpsDrawResult {
  candidates: OpsCandidate[];
  constraints: Record<string, number | string | boolean | null>;
  expires_at: string;
  considered: number;
}

export interface OpsRoster {
  id: string;
  kind: string;
  aircraft_id: string;
  status: string;
  base_airport_icao: string | null;
  window_start_utc: string;
  window_end_utc: string;
  constraints: Record<string, unknown>;
  redraw_count: number;
  locked_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  expires_at: string | null;
  created_at: string;
  aircraft: {
    id: string;
    registration: string;
    type: string;
    variant: string;
    current_airport_icao: string | null;
    status: string;
  };
  legs: OpsLeg[];
  settlements: { id: string; flight_record_id: string; profit: number; status: string; policy_action: string }[];
}

export interface OpsTask {
  kind: string;
  roster_id?: string;
  roster_leg_id?: string;
  free_flight_id?: string;
  flight_record_id: string;
  aircraft_id: string;
  dep_icao: string;
  arr_icao: string;
  aircraft_type: string;
  callsign: string;
  scheduled_dep_utc?: string | null;
  started_at: string;
}

export interface OpsLoadSheet {
  id: string;
  flight_record_id: string;
  aircraft_id: string;
  dep_icao: string | null;
  arr_icao: string | null;
  distance_nm: number | null;
  block_minutes: number | null;
  pax_total: number;
  pax_economy: number;
  pax_business: number;
  pax_first: number;
  cargo_kg: number;
  mail_kg: number;
  oew_kg: number | null;
  zfw_kg: number | null;
  tow_kg: number | null;
  fuel_kg: number | null;
  estimated_revenue: number;
  estimated_cost: number;
}

export interface OpsLedgerEntry {
  id: string;
  flight_record_id: string | null;
  settlement_id: string | null;
  entry_type: string;
  amount: number;
  balance_after: number;
  currency: string;
  description: string | null;
  created_at: string;
}

export interface OpsSettlement {
  id: string;
  flight_record_id: string;
  task_kind: string | null;
  roster_id: string | null;
  aircraft_id: string | null;
  revenue_gross: number;
  revenue_total: number;
  cost_total: number;
  profit: number;
  payout_factor: number;
  advance_amount: number;
  policy_action: string;
  status: string;
  review_status: string;
  review_note: string | null;
  computed_at: string;
  callsign?: string | null;
  dep_icao?: string | null;
  arr_icao?: string | null;
  block_off_utc?: string | null;
  block_minutes?: number | null;
  touchdown_vs_fpm?: number | null;
  landing_rating?: string | null;
  breakdown?: {
    inputs?: Record<string, unknown>;
    revenue?: { type: string; amount: number; note?: string }[];
    costs?: { type: string; amount: number; note?: string }[];
    gross_revenue?: number;
    payout_factor?: number;
    policy_action?: string;
    policy?: OpsPolicyResult;
    profit?: number;
  };
  policy_breakdown?: OpsPolicyResult;
  policy_snapshot?: Record<string, unknown>;
  ledger?: OpsLedgerEntry[];
  flight?: FlightRecord | null;
}

export interface OpsPolicyResult {
  payout_factor: number;
  action: string;
  review_required: boolean;
  breakdown: { kind: string; action: string; penalty: number; detail: string; value?: number }[];
}

/** 有可用飞机的机场（自由飞出发机场下拉数据源）。 */
export interface OpsFreeAirport {
  icao: string;
  iata?: string | null;
  name?: string | null;
  city?: string | null;
  country?: string | null;
  lat?: number | null;
  lon?: number | null;
  aircraft: number;
}

/** 执行页实时状态（取 SimLink 最新采样；缺失字段为 null，界面显示「—」）。 */
export interface FlightStatus {
  available: boolean;
  on_ground: boolean | null;
  gs_kt: number | null;
  ias_kt: number | null;
  alt_ft: number | null;
  agl_ft: number | null;
  lat: number | null;
  lon: number | null;
  vs_fpm: number | null;
  phase: string | null;
  remaining_nm: number | null;
  ete_min: number | null;
  eta_utc: string | null;
  total_weight_kg: number | null;
  fuel_weight_kg: number | null;
  actual_zfw_kg: number | null;
}

export interface OpsFreeFlight {
  id: string;
  aircraft_id: string;
  flight_instance_id: string | null;
  dep_icao: string;
  arr_icao: string;
  dep_time_utc: string;
  status: string;
  lock_expires_at: string | null;
  callsign?: string | null;
  aircraft?: OpsAircraft;
}

export interface OpsFinanceBucket {
  flights: number;
  revenue: number;
  cost: number;
  profit: number;
}

export interface OpsFinancePeriod extends OpsFinanceBucket {
  key: "WEEK" | "MONTH" | "YEAR";
  start: string;
}

export interface OpsFinanceMonth extends OpsFinanceBucket {
  month: string;
}

/** 财务统计：总计 + 本周/本月/今年 + 近 6 个月（不含账户余额）。 */
export interface OpsFinanceSummary {
  currency: string;
  totals: OpsFinanceBucket;
  held: number;
  periods: OpsFinancePeriod[];
  monthly: OpsFinanceMonth[];
}

/** 顶部状态条：当前是空闲 / 地面等待 / 飞行中。 */
export interface OpsStatus {
  state: "IDLE" | "GROUND" | "FLIGHT";
  phase: string;
  recording: boolean;
  callsign?: string | null;
  dep_icao?: string | null;
  arr_icao?: string | null;
  task_kind?: string | null;
  roster_status?: string | null;
  free_flight_status?: string | null;
}

export interface OpsDashboard {
  profile: OpsProfile;
  fleet: { total: number; active: number; held: number; in_flight: number; maintenance: number };
  active_roster: OpsRoster | null;
  active_free_flight: OpsFreeFlight | null;
  active_task: OpsTask | null;
  today: { settlements: number; revenue: number; cost: number; profit: number };
  review_count: number;
  scheduled_instances: number;
  no_show_count: number;
  config_version: number;
}

export interface OpsParamSchema {
  key: string;
  group: string;
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
}

export interface OpsPolicy {
  scope_mode: string;
  default_action: string;
  reject_cost_mode: string;
  review_advance_ratio: number;
  review_sla_hours: number;
  min_payout_factor: number;
  rules: Record<string, Record<string, unknown>>;
  overrides: Record<string, unknown>[];
}

export interface OpsConfig {
  economy: Record<string, number | string>;
  policy: OpsPolicy;
  version: number;
  versions: { id: string; version: number; status: string; note: string | null; created_at: string }[];
  param_schema: OpsParamSchema[];
}

export interface OpsLedger {
  balance: number;
  currency: string;
  items: OpsLedgerEntry[];
  totals: Record<string, number>;
  ledger_sum: number;
  reconciled: boolean;
}

export interface OpsAudit {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before: unknown;
  after: unknown;
  reason: string | null;
  actor: string | null;
  created_at: string;
}
