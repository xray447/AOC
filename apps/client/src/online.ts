/**
 * 联机模式（M3）客户端通道：只做账号、航段抽取与同步状态展示。
 * 服务器是机队/航班/结算的权威；本地 aoc-core 仍负责个人模式与 SimLink 采集。
 */
export interface OnlineUser {
  id: string;
  username: string;
  display_name: string;
  role: string;
}

export interface OnlineCompany {
  id: string;
  name: string;
  icao: string;
  currency: string;
  balance: number;
}

export interface OnlineFlight {
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
}

export interface OnlineRoster {
  id: string;
  status: string;
  expires_at: string;
  aircraft: { registration: string; current_icao: string; type?: { icao: string } } | null;
  legs: Array<OnlineFlight & { leg_status: string; sequence: number }>;
}

export interface OnlineState {
  server: string;
  accessToken: string;
  refreshToken: string;
  user: OnlineUser;
  company: OnlineCompany;
}

const KEY = "aoc.online";
const CURSOR_KEY = "aoc.online.cursor";

export function loadOnline(): OnlineState | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as OnlineState) : null;
  } catch {
    return null;
  }
}

export function saveOnline(state: OnlineState | null): void {
  if (state) localStorage.setItem(KEY, JSON.stringify(state));
  else localStorage.removeItem(KEY);
}

export function onlineCursor(): number {
  return Number(localStorage.getItem(CURSOR_KEY) || 0) || 0;
}

export function setOnlineCursor(value: number): void {
  localStorage.setItem(CURSOR_KEY, String(value));
}

export class OnlineError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const body = data as { error?: { code?: string; message?: string } };
    throw new OnlineError(res.status, body?.error?.code || `HTTP_${res.status}`,
      body?.error?.message || `HTTP ${res.status}`);
  }
  return data as T;
}

async function rawRequest<T>(base: string, path: string, token: string, init: RequestInit = {},
                             idempotencyKey?: string): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
  const res = await fetch(`${base.replace(/\/$/, "")}${path}`, { ...init, headers });
  return parse<T>(res);
}

export async function loginOnline(server: string, username: string, password: string): Promise<OnlineState> {
  const base = server.replace(/\/$/, "");
  const res = await fetch(`${base}/api/v1/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await parse<{
    access_token: string; refresh_token: string; user: OnlineUser; company: OnlineCompany;
  }>(res);
  const state: OnlineState = {
    server: base, accessToken: data.access_token, refreshToken: data.refresh_token,
    user: data.user, company: data.company,
  };
  saveOnline(state);
  return state;
}

export async function logoutOnline(state: OnlineState): Promise<void> {
  try {
    await fetch(`${state.server}/api/v1/auth/logout`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: state.refreshToken }),
    });
  } catch {
    /* 离线也能本地退出 */
  }
  saveOnline(null);
}

export async function onlineRequest<T>(state: OnlineState, path: string,
                                       init: RequestInit = {},
                                       idempotencyKey?: string): Promise<T> {
  try {
    return await rawRequest<T>(state.server, path, state.accessToken, init, idempotencyKey);
  } catch (err) {
    if (!(err instanceof OnlineError) || err.status !== 401 || !state.refreshToken) throw err;
    const res = await fetch(`${state.server}/api/v1/auth/refresh`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: state.refreshToken }),
    });
    const data = await parse<{ access_token: string; refresh_token: string }>(res);
    state.accessToken = data.access_token;
    state.refreshToken = data.refresh_token;
    saveOnline(state);
    return rawRequest<T>(state.server, path, state.accessToken, init, idempotencyKey);
  }
}

export async function onlineHealth(server: string): Promise<{ status: string; version: string }> {
  const res = await fetch(`${server.replace(/\/$/, "")}/health`, { cache: "no-store" });
  return parse(res);
}

export async function onlineFlights(state: OnlineState): Promise<OnlineFlight[]> {
  return onlineRequest<OnlineFlight[]>(state, "/api/v1/flights?status=SCHEDULED&limit=30");
}

export async function onlineDraw(state: OnlineState, flightId: string): Promise<OnlineRoster> {
  return onlineRequest<OnlineRoster>(state, "/api/v1/roster/draw", {
    method: "POST",
    body: JSON.stringify({ flight_ids: [flightId], max_legs: 1 }),
  }, `draw-${flightId}-${Date.now()}`);
}

export async function onlineCurrentRoster(state: OnlineState): Promise<OnlineRoster | null> {
  const data = await onlineRequest<{ roster: OnlineRoster | null }>(state, "/api/v1/roster/current");
  return data.roster;
}

export async function onlineSync(state: OnlineState, cursor: number): Promise<{
  cursor: number; server_time: string; has_more: boolean;
  events: Array<{ id: number; kind: string; entity: string | null; entity_id: string | null;
    payload: Record<string, unknown> | null; created_at: string }>;
}> {
  return onlineRequest(state, `/api/v1/sync?cursor=${cursor}&limit=100`);
}
