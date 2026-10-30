import type { CSSProperties } from "react";

export interface TrendPoint {
  t: number;
  v?: number | null;
}

interface Props {
  title: string;
  unit?: string;
  color: string;
  series: TrendPoint[];
  /** 落地时刻（秒，相对记录开始）：画一条黄色虚线 + TD 标签。 */
  markerT?: number | null;
  height?: number;
  /** 曲线下方的小字说明（例如「AGL 近似」）。 */
  note?: string;
  emptyText?: string;
}

const W = 1040;
const PAD_L = 52;
const PAD_R = 14;
const PAD_T = 14;
const PAD_B = 22;

function fmt(value: number, digits: number): string {
  if (!Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

/** 2%–98% 分位裁剪：载入瞬间的脏值（AGL 5 万英尺、VS 6250fpm、G=0）会把曲线压平。 */
function percentile(values: number[], ratio: number): number {
  const index = Math.min(values.length - 1, Math.max(0, Math.floor(values.length * ratio)));
  return values[index];
}

/**
 * 单指标折线图（`spikes/simconnect_probe/Report.cs::AppendChart` 的 React 版）：
 * 内联 SVG、5 条水平网格 + 左侧数值 + 5 个时间刻度、TD 竖线、分位裁剪、样本不足空态。
 * 逐点画折线，不做等距重采样——采样密度本来不均（滑行 10s / 巡航 1s / 跑道 0.1s）。
 */
export function TrendChart({
  title, unit, color, series, markerT, height = 200, note, emptyText,
}: Props) {
  const points = series
    .filter((p) => Number.isFinite(p.t) && typeof p.v === "number" && Number.isFinite(p.v))
    .map((p) => ({ t: p.t, v: p.v as number }))
    .sort((a, b) => a.t - b.t);

  const wrap: CSSProperties = {
    background: "#0e131a", border: "1px solid #1b2431", borderRadius: 8,
    padding: "10px 12px", marginBottom: 12,
  };
  const empty: CSSProperties = { color: "#6b7c93", fontSize: 12, padding: "18px 4px" };

  if (points.length < 2) {
    return (
      <div style={wrap} data-testid={`chart-${title}`}>
        <div style={{ fontSize: 10, letterSpacing: 1.4, color: "#8fa3ba", marginBottom: 4 }}>
          {title}{unit ? <span style={{ color: "#6b7c93" }}> · {unit}</span> : null}
        </div>
        <div style={empty}>{emptyText || "样本不足，无法绘图"}</div>
      </div>
    );
  }

  const t0 = points[0].t;
  const t1 = points[points.length - 1].t;
  const sorted = points.map((p) => p.v).sort((a, b) => a - b);
  let yMin = percentile(sorted, 0.02);
  let yMax = percentile(sorted, 0.98);
  if (yMax - yMin < 1e-6) { yMax += 1; yMin -= 1; }
  const pad = (yMax - yMin) * 0.08;
  yMin -= pad;
  yMax += pad;
  const span = yMax - yMin;
  const digits = span >= 20 ? 0 : span >= 2 ? 1 : 2;

  const sx = (t: number) => PAD_L + ((t - t0) / Math.max(1e-6, t1 - t0)) * (W - PAD_L - PAD_R);
  const sy = (v: number) => {
    const y = height - PAD_B - ((v - yMin) / (yMax - yMin)) * (height - PAD_T - PAD_B);
    return Math.min(height - PAD_B, Math.max(PAD_T, y));
  };

  const polyline = points.map((p) => `${sx(p.t).toFixed(1)},${sy(p.v).toFixed(1)}`).join(" ");
  const marker = typeof markerT === "number" && markerT >= t0 && markerT <= t1 ? markerT : null;

  return (
    <div style={wrap} data-testid={`chart-${title}`}>
      <div style={{ fontSize: 10, letterSpacing: 1.4, color: "#8fa3ba", marginBottom: 4 }}>
        {title}{unit ? <span style={{ color: "#6b7c93" }}> · {unit}</span> : null}
      </div>
      <svg viewBox={`0 0 ${W} ${height}`} width="100%" height={height}
        preserveAspectRatio="none" role="img" aria-label={title}>
        {[0, 1, 2, 3, 4].map((i) => {
          const value = yMin + ((yMax - yMin) * i) / 4;
          const y = sy(value);
          return (
            <g key={`grid-${i}`}>
              <line x1={PAD_L} y1={y} x2={W - PAD_R} y2={y} stroke="#1d2634" strokeWidth={1} />
              <text x={PAD_L - 6} y={y + 3.5} fill="#6b7c93" fontSize={10} textAnchor="end">
                {fmt(value, digits)}
              </text>
            </g>
          );
        })}
        {[0, 1, 2, 3, 4].map((i) => {
          const t = t0 + ((t1 - t0) * i) / 4;
          return (
            <text key={`tick-${i}`} x={sx(t)} y={height - 6} fill="#6b7c93" fontSize={10}
              textAnchor="middle">
              {Math.round(t)}s
            </text>
          );
        })}
        <polyline fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round"
          strokeLinecap="round" points={polyline} />
        {marker != null ? (
          <g>
            <line x1={sx(marker)} y1={PAD_T} x2={sx(marker)} y2={height - PAD_B}
              stroke="#ffb547" strokeWidth={1} strokeDasharray="3 3" />
            <text x={sx(marker) + 4} y={PAD_T + 10} fill="#ffb547" fontSize={10}>TD</text>
          </g>
        ) : null}
      </svg>
      <div style={{ fontSize: 10, color: "#6b7c93", marginTop: 2 }}>
        {note ? `${note} · ` : ""}{points.length} 点 · {fmt(t1 - t0, 0)}s
      </div>
    </div>
  );
}
