import { api } from "./api";
import type { RecordingStatus } from "./types";

export type SimlinkLevel = "offline" | "no-sim" | "online";

export interface SimlinkStateMeta {
  level: SimlinkLevel;
  color: string;
  zh: string;
  en: string;
  /** 数据源（simconnect / demo / replay），tooltip 用。 */
  source?: string | null;
  /** 第二态（SimLink 在跑但没连上模拟器）的原始错误。 */
  error?: string | null;
}

/**
 * SimLink 三态：`simlink_connected` 只表示 core ↔ SimLink 通了，
 * 不代表模拟器连上了；MSFS 没开时按第二态提示排查步骤。
 */
export function simlinkState(recording: RecordingStatus | null | undefined): SimlinkStateMeta {
  if (!recording?.simlink_connected) {
    return {
      level: "offline", color: "default",
      zh: "SimLink 未运行", en: "SimLink not running",
    };
  }
  const source = recording.simlink_source || null;
  if (!recording.sim_connected) {
    return {
      level: "no-sim", color: "orange",
      zh: "SimLink 在运行 · 模拟器未连接",
      en: "SimLink running · simulator not connected",
      source, error: recording.last_connect_error,
    };
  }
  const demo = Boolean(source && source !== "simconnect");
  return {
    level: "online", color: "green",
    zh: demo ? `已连接模拟器（${source}）` : "已连接模拟器",
    en: demo ? `Simulator connected (${source})` : "Simulator connected",
    source,
  };
}

/** 打开日志目录；纯浏览器/权限不足时返回 false，由调用方降级为显示路径。 */
export async function openLogFolder(): Promise<boolean> {
  try {
    const res = await api<{ ok?: boolean }>("/local/system/open-logs", { method: "POST" });
    return Boolean(res?.ok);
  } catch {
    return false;
  }
}
