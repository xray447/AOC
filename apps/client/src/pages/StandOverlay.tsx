import { useEffect, useState } from "react";
import { api, initApi } from "../api";
import type { StandNotice } from "../types";

/**
 * docs/12 §6.3.2：Tauri 置顶迷你浮窗（`?overlay=1`）。
 *
 * 独立于主窗口渲染：只显示最近一条到达提醒，不抢焦点、不写数据库；
 * 窗口可见性由 Rust 侧控制（有通知就 show，3 min 后 hide）。
 * 独占全屏下会被模拟器盖住 —— 这是已知边界，系统通知兜底。
 */
export function StandOverlay() {
  const [notice, setNotice] = useState<StandNotice | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer = 0;
    const tick = async () => {
      try {
        const res = await api<{ items: StandNotice[] }>(
          "/local/notifications?include_acked=1&limit=1");
        if (alive) {
          setNotice(res.items[0] || null);
          setError(null);
        }
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
      if (alive) timer = window.setTimeout(() => void tick(), 8000);
    };
    initApi()
      .then(() => tick())
      .catch((e: Error) => setError(e.message));
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, []);

  return (
    <div
      style={{
        fontFamily: '"Segoe UI", "Microsoft YaHei", system-ui, sans-serif',
        height: "100vh",
        boxSizing: "border-box",
        borderRadius: 12,
        padding: "10px 12px",
        background: "rgba(8, 14, 26, 0.82)",
        color: "#e6edf7",
        border: "1px solid rgba(14, 165, 233, 0.55)",
        overflow: "hidden",
        userSelect: "none",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span style={{ fontSize: 11, letterSpacing: 1, color: "#7dd3fc" }}>AOC · ARRIVAL</span>
        <span style={{ fontSize: 10, color: "#64748b" }}>
          {notice?.created_at?.slice(11, 16)}Z
        </span>
      </div>
      {error ? (
        <div style={{ marginTop: 8, fontSize: 12, color: "#fca5a5" }}>
          未连接 aoc-core
        </div>
      ) : notice ? (
        <>
          <div style={{ marginTop: 4, fontSize: 15, fontWeight: 600, lineHeight: 1.3 }}>
            {notice.title}
          </div>
          <div style={{ marginTop: 4, fontSize: 12, color: "#cbd5e1", lineHeight: 1.4 }}>
            {notice.body}
          </div>
          {notice.payload?.acars?.verdict ? (
            <div style={{ marginTop: 6, fontSize: 10, color: "#94a3b8" }}>
              ACARS {notice.payload.acars.verdict} · 回执未知
            </div>
          ) : null}
        </>
      ) : (
        <div style={{ marginTop: 8, fontSize: 12, color: "#94a3b8" }}>
          等待到达提醒…
        </div>
      )}
      <div style={{ marginTop: 6, fontSize: 10, color: "#64748b" }}>
        仅为 AOC 计划信息，模拟器内请自行滑行到位
      </div>
    </div>
  );
}
