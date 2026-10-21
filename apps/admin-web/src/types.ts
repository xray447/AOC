export interface User {
  id: string;
  username: string;
  display_name: string;
  role: "ADMIN" | "DISPATCHER" | "PILOT";
  active: boolean;
  email?: string | null;
  last_login_at?: string | null;
}

export interface Company {
  id: string;
  name: string;
  icao: string;
  callsign_prefix: string;
  base_icao: string;
  currency: string;
  balance: number;
  initial_balance: number;
  timezone: string;
  description?: string | null;
}

export interface AuthState {
  user: User;
  company: Company;
  csrf_token: string;
}

export interface ParamSpec {
  key: string;
  group: string;
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
}

export interface SettingResponse {
  version: number;
  payload: Record<string, number | string | unknown>;
  defaults: Record<string, number | string | unknown>;
  schema?: ParamSpec[];
  updated_at?: string | null;
  updated_by?: string | null;
}

export interface OverviewData {
  company: Company;
  cards: {
    balance: number;
    today_revenue: number;
    today_cost: number;
    today_profit: number;
    in_flight: number;
    online_pilots: number;
    review_pending: number;
    active_locks: number;
  };
  recent_flights: Flight[];
  recent_audit: AuditEntry[];
  review_queue: Settlement[];
  server_time: string;
}

export interface Flight {
  id: string;
  flight_number: string;
  dep_icao: string;
  arr_icao: string;
  scheduled_dep_utc: string;
  scheduled_arr_utc: string;
  status: string;
  distance_nm: number;
  block_minutes: number;
  aircraft?: { registration: string } | null;
  pilot?: { username: string; display_name: string } | null;
  settlement_status?: string | null;
}

export interface Settlement {
  id: string;
  flight_id: string;
  user_id: string;
  status: string;
  action: string;
  factor: number;
  revenue_gross: number;
  cost_total: number;
  profit: number;
  anomalies: Array<{ kind: string; detail?: string; action?: string }>;
  review_reason?: string | null;
  advance_amount: number;
  created_at: string;
  flight?: Flight | null;
  pilot?: User | null;
}

export interface AuditEntry {
  id: string;
  actor_name: string | null;
  action: string;
  entity: string | null;
  entity_id: string | null;
  result: string;
  reason: string | null;
  ip: string | null;
  before: unknown;
  after: unknown;
  created_at: string;
}

export interface Aircraft {
  id: string;
  registration: string;
  type_id: string;
  base_icao: string;
  current_icao: string;
  status: string;
  acquisition: string;
  total_hours: number;
  total_cycles: number;
  lease_per_hour?: number | null;
  type?: { icao: string; name: string; role: string };
  lock?: { id: string; user_id: string; expires_at: string } | null;
}

export interface AircraftType {
  id: string;
  icao: string;
  variant: string;
  name: string;
  role: string;
  pax_capacity: number;
  mtow_kg: number;
  lease_per_hour: number;
  charter_rate_per_hour: number;
  allow_scheduled: boolean;
  allow_charter: boolean;
  active: boolean;
}

export interface NetworkRoute {
  id: string;
  dep_icao: string;
  arr_icao: string;
  distance_nm: number;
  block_minutes: number;
  active: boolean;
}

export interface Schedule {
  id: string;
  flight_number: string;
  route_id: string;
  dep_local: string;
  days_of_week: number[];
  dep_icao?: string | null;
  arr_icao?: string | null;
  aircraft_type_id?: string | null;
  active: boolean;
}

export interface LockItem {
  id: string;
  aircraft_id: string;
  user_id: string;
  roster_id?: string | null;
  kind: string;
  status: string;
  expires_at: string;
  aircraft?: { registration: string; current_icao: string } | null;
  user?: { username: string; display_name: string } | null;
}
