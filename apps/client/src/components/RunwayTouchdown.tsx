import type { AirportRunway, TrackPoint } from "../types";

interface Props {
  runway: AirportRunway | null;
  touchdownLat?: number | null;
  touchdownLon?: number | null;
  thresholdDistanceM?: number | null;
  centerlineOffsetM?: number | null;
  points?: TrackPoint[];
  height?: number;
}

interface Projected {
  along: number;
  lateral: number;
}

const M_PER_DEG_LAT = 110540;
const M_PER_DEG_LON = 111320;

/** 与后端 `project_on_runway` 同口径：沿跑道方向距入口米数 + 横向偏移（右偏为正）。 */
export function projectOnRunway(runway: AirportRunway, lat: number, lon: number): Projected {
  const rLat = Number(runway.lat);
  const rLon = Number(runway.lon);
  const hdg = Number(runway.heading) || 0;
  const kx = M_PER_DEG_LON * Math.cos((rLat * Math.PI) / 180);
  const dx = (lon - rLon) * kx;
  const dy = (lat - rLat) * M_PER_DEG_LAT;
  const th = (hdg * Math.PI) / 180;
  return {
    along: dy * Math.cos(th) + dx * Math.sin(th),
    lateral: dx * Math.cos(th) - dy * Math.sin(th),
  };
}

function runwayLength(runway: AirportRunway): number {
  const len = Number(runway.length_m);
  return Number.isFinite(len) && len > 200 ? len : 3000;
}

/**
 * 跑道接地区俯视图：跑道轮廓/中线/入口 + 接地点 + 接地后滑跑轨迹 + 距入口/中心线偏移。
 * 横向按米单独缩放（默认放大 1.6×），纵向为真实比例，图中标注了横向放大倍数。
 */
export function RunwayTouchdown({
  runway, touchdownLat, touchdownLon, thresholdDistanceM, centerlineOffsetM, points = [], height = 260,
}: Props) {
  if (!runway || runway.lat == null || runway.lon == null) return null;
  const hasTouchdown = touchdownLat != null && touchdownLon != null;
  const length = runwayLength(runway);
  const width = 960;
  const padX = 56;
  const centerY = height / 2;
  const xScale = (width - 2 * padX) / length;

  const td = hasTouchdown
    ? projectOnRunway(runway, touchdownLat as number, touchdownLon as number)
    : null;

  // 接地后的滑跑轨迹：从最接近接地点的采样点开始，取跑道附近的点
  const projected = points.map((p) => ({ t: p.t, ...projectOnRunway(runway, p.lat, p.lon) }));
  let start = 0;
  if (hasTouchdown && projected.length) {
    let best = Number.POSITIVE_INFINITY;
    projected.forEach((p, i) => {
      const d = Math.hypot(p.along - (td ? td.along : 0), p.lateral - (td ? td.lateral : 0));
      if (d < best) { best = d; start = i; }
    });
  }
  const rollout = projected.slice(start).filter(
    (p) => p.along >= -60 && p.along <= length + 400 && Math.abs(p.lateral) <= 90,
  );

  const extents = [
    24,
    ...rollout.map((p) => Math.abs(p.lateral)),
    td ? Math.abs(td.lateral) : 0,
  ];
  const maxAbs = Math.max(...extents);
  const lateralScale = Math.min(3.2, Math.max(0.9, (centerY - 24) / maxAbs));
  const exaggeration = lateralScale / xScale;

  const y = (lateral: number) => centerY + lateral * lateralScale;
  const x = (along: number) => padX + along * xScale;

  const halfWidthM = 22.5; // 典型跑道半宽，仅用于示意
  const rolloutPath = rollout
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.along).toFixed(1)},${y(p.lateral).toFixed(1)}`)
    .join(" ");

  const tdAlong = td ? td.along : thresholdDistanceM ?? null;
  const tdLateral = td ? td.lateral : centerlineOffsetM ?? null;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img"
      aria-label="Runway touchdown view">
      <rect x={x(0)} y={y(-halfWidthM)} width={x(length) - x(0)}
        height={y(halfWidthM) - y(-halfWidthM)}
        fill="currentColor" fillOpacity={0.08} stroke="currentColor" strokeOpacity={0.35} />
      {/* 中线 */}
      <line x1={x(0)} y1={centerY} x2={x(length)} y2={centerY}
        stroke="currentColor" strokeOpacity={0.5} strokeDasharray="10 8" />
      {/* 入口（阈值） */}
      <line x1={x(0)} y1={y(-halfWidthM)} x2={x(0)} y2={y(halfWidthM)}
        stroke="currentColor" strokeOpacity={0.8} strokeWidth={2.5} />
      <text x={x(0)} y={y(-halfWidthM) - 8} fontSize={12} fill="currentColor" fillOpacity={0.75}>
        {runway.ident || "RWY"} 入口
      </text>
      <text x={x(length)} y={y(-halfWidthM) - 8} fontSize={12} textAnchor="end"
        fill="currentColor" fillOpacity={0.6}>
        {Math.round(length)} m
      </text>

      {rolloutPath ? (
        <path d={rolloutPath} fill="none" stroke="#1677ff" strokeWidth={2.5} strokeOpacity={0.9} />
      ) : null}

      {td ? (
        <>
          <circle cx={x(td.along)} cy={y(td.lateral)} r={6} fill="#fa541c" />
          <line x1={x(td.along)} y1={centerY} x2={x(td.along)} y2={y(td.lateral)}
            stroke="#fa541c" strokeWidth={1.5} strokeDasharray="4 3" />
          <text x={x(td.along)} y={y(td.lateral) + (td.lateral >= 0 ? 22 : -14)}
            fontSize={12} textAnchor="middle" fill="currentColor" fillOpacity={0.85}>
            接地点 {tdAlong != null ? `${Math.round(tdAlong)} m` : ""}
            {tdLateral != null ? ` / 偏移 ${tdLateral > 0 ? "+" : ""}${Math.round(tdLateral)} m` : ""}
          </text>
        </>
      ) : null}

      {tdAlong != null ? (
        <line x1={x(0)} y1={centerY} x2={x(tdAlong)} y2={centerY}
          stroke="#fa541c" strokeOpacity={0.45} strokeWidth={1} />
      ) : null}

      <text x={padX} y={height - 12} fontSize={11} fill="currentColor" fillOpacity={0.55}>
        横向放大 {exaggeration.toFixed(1)}×（纵向真实比例）· 距入口 {tdAlong != null ? `${Math.round(tdAlong)} m` : "—"}
        {" · "}中心线偏移 {tdLateral != null ? `${tdLateral > 0 ? "+" : ""}${tdLateral.toFixed(1)} m` : "—"}
      </text>
    </svg>
  );
}
