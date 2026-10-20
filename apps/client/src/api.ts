import type { Bootstrap } from "./types";

let token = "";
let bootstrapData: Bootstrap | null = null;

export const coreBase = (import.meta.env.VITE_CORE_URL as string | undefined) ?? "";

export async function initApi(): Promise<Bootstrap> {
  if (bootstrapData) return bootstrapData;
  const res = await fetch(`${coreBase}/local/bootstrap`, { cache: "no-store" });
  if (!res.ok) throw new Error(`无法连接 aoc-core（HTTP ${res.status}）`);
  bootstrapData = (await res.json()) as Bootstrap;
  token = bootstrapData.token;
  return bootstrapData;
}

export function getBootstrap(): Bootstrap | null {
  return bootstrapData;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-AOC-Token", token);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const res = await fetch(`${coreBase}${path}`, { ...init, headers });
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      message = data?.message || data?.detail?.message || data?.detail || message;
    } catch {
      /* keep status text */
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function apiUrl(path: string): string {
  return `${coreBase}${path}`;
}

export async function download(path: string, filename: string, init: RequestInit = {}): Promise<void> {
  const headers = new Headers(init.headers);
  headers.set("X-AOC-Token", token);
  const res = await fetch(`${coreBase}${path}`, { ...init, headers });
  if (!res.ok) throw new Error(`下载失败（HTTP ${res.status}）`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
