let csrfToken = "";

export function setCsrf(token: string): void {
  csrfToken = token || "";
}

export function getCsrf(): string {
  return csrfToken;
}

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const method = (init.method || "GET").toUpperCase();
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const res = await fetch(path, { ...init, headers, credentials: "include" });
  if (res.status === 401) {
    window.dispatchEvent(new Event("aoc:unauthorized"));
  }
  let data: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const body = data as { error?: { code?: string; message?: string; details?: unknown } };
    throw new ApiError(res.status, body?.error?.code || `HTTP_${res.status}`,
      body?.error?.message || `请求失败（HTTP ${res.status}）`, body?.error?.details);
  }
  return data as T;
}

export function money(value: number | null | undefined, currency = "USD"): string {
  return `${currency} ${Number(value || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`;
}

export function timeText(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}
