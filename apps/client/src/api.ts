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

/**
 * 用系统默认浏览器打开外链（SimBrief 等）。
 * Tauri webview 里的 window.open 会新开应用内窗口，因此交给 aoc-core 调 webbrowser；
 * 后端不可用时退回 window.open。
 */
export async function openExternal(url: string): Promise<void> {
  if (!url) return;
  try {
    const res = await api<{ ok: boolean }>("/local/system/open-external", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    if (res.ok) return;
  } catch {
    /* aoc-core 未就绪：退回 webview 打开 */
  }
  window.open(url, "_blank", "noopener");
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
