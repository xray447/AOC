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
  max_g_flight?: number | null;
  max_g_landing?: number | null;
  touchdown_g?: number | null;
  touchdown_vs_fpm?: number | null;
  runway_ident?: string | null;
  threshold_distance_m?: number | null;
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
