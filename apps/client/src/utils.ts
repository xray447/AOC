import dayjs from "dayjs";
import type { FlightRecord, Settings } from "./types";

export type LonLat = [number, number];

/** 转义地图弹窗里的文本（navdata 字段可能含 & < > 等字符）。 */
export function escapeHtml(value: unknown): string {
  const map: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value ?? "").replace(/[&<>"']/g, (ch) => map[ch]);
}

/**
 * 跨 ±180° 经线的折线拆成多段，避免地图把跨太平洋的线画成绕地球一圈。
 * 只有相邻两点经度差超过 180° 时才切分，切点纬度按经度线性插值。
 */
export function splitAntimeridian(coords: LonLat[]): LonLat[][] {
  if (coords.length < 2) return [];
  const out: LonLat[][] = [];
  let current: LonLat[] = [coords[0]];
  for (let i = 1; i < coords.length; i += 1) {
    const [lon1, lat1] = coords[i - 1];
    const [lon2, lat2] = coords[i];
    const dLon = lon2 - lon1;
    if (Math.abs(dLon) <= 180) {
      current.push(coords[i]);
      continue;
    }
    // 把 lon2 平移到 lon1 附近，走较短的经向路径
    const lon2Adj = lon2 + (dLon > 180 ? -360 : 360);
    const edge = lon2Adj > lon1 ? 180 : -180;
    const t = (edge - lon1) / (lon2Adj - lon1);
    const latCross = lat1 + (lat2 - lat1) * t;
    current.push([edge, latCross]);
    out.push(current);
    current = [[-edge, latCross], coords[i]];
  }
  out.push(current);
  return out.filter((seg) => seg.length >= 2);
}

/** 深比较（设置页判断是否有未保存改动）。 */
export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object") return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((v, i) => deepEqual(v, b[i]));
  }
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  const keys = Object.keys(left);
  if (keys.length !== Object.keys(right).length) return false;
  return keys.every((k) => deepEqual(left[k], right[k]));
}

export function fmtMinutes(min?: number | null): string {
  if (min === null || min === undefined || Number.isNaN(min)) return "—";
  const total = Math.round(min);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h > 0 ? `${h}h${m.toString().padStart(2, "0")}m` : `${m}m`;
}

export function fmtDateTime(iso?: string | null): string {
  if (!iso) return "—";
  return dayjs(iso).format("YYYY-MM-DD HH:mm");
}

export function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  return dayjs(iso).format("YYYY-MM-DD");
}

export function fmtDistance(nm?: number | null, units?: Settings["units"]): string {
  if (nm === null || nm === undefined) return "—";
  if (units?.speed === "kmh") return `${Math.round(nm * 1.852)} km`;
  return `${Math.round(nm)} NM`;
}

export function fmtAltitude(ft?: number | null, units?: Settings["units"]): string {
  if (ft === null || ft === undefined) return "—";
  if (units?.altitude === "m") return `${Math.round(ft * 0.3048)} m`;
  return `${Math.round(ft)} ft`;
}

export function fmtWeight(kg?: number | null, units?: Settings["units"]): string {
  if (kg === null || kg === undefined) return "—";
  if (units?.weight === "lb") return `${Math.round(kg * 2.20462)} lb`;
  return `${Math.round(kg)} kg`;
}

export const ratingLabels: Record<string, { zh: string; en: string; color: string }> = {
  GREAT: { zh: "优秀", en: "Great", color: "success" },
  GOOD: { zh: "良好", en: "Good", color: "cyan" },
  HARD: { zh: "重着陆", en: "Hard", color: "warning" },
  SEVERE: { zh: "严重", en: "Severe", color: "error" },
  UNKNOWN: { zh: "未评估", en: "Unknown", color: "default" },
};

export const statusLabels: Record<string, { zh: string; en: string; color: string }> = {
  COMPLETED: { zh: "已完成", en: "Completed", color: "success" },
  DIVERTED: { zh: "备降", en: "Diverted", color: "warning" },
  ABORTED: { zh: "中止", en: "Aborted", color: "error" },
  RECORDING: { zh: "记录中", en: "Recording", color: "processing" },
  CRASHED: { zh: "坠机", en: "Crashed", color: "error" },
  ABANDONED: { zh: "已放弃", en: "Abandoned", color: "default" },
};

export function flightTitle(f: FlightRecord): string {
  return `${f.dep_icao || "????"} → ${f.arr_icao || "????"}`;
}

export function pct(value: number, total: number): number {
  return total > 0 ? Math.round((value / total) * 100) : 0;
}
