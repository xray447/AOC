import type { AirportRunway, TrackPoint } from "../types";

interface Props {
  runway: AirportRunway | null;
  touchdownLat?: number | null;
  touchdownLon?: number | null;
  thresholdDistanceM?: number | null;
  centerlineOffsetM?: number | null;
  /** 内移入口（米）：着陆入口 = 物理入口 + 内移；0/缺省时与物理入口重合。 */
  displacedThresholdM?: number | null;
  points?: TrackPoint[];
  height?: number;
}

interface Projected {
  along: number;
  lateral: number;
}

const M_PER_DEG_LAT = 110540;
const M_PER_DEG_LON = 111320;
/** `AirportRunway` 还没有宽度字段时的兜底值（典型窄体跑道 45 m）。 */
const DEFAULT_RUNWAY_WIDTH_M = 45;
/** 刻度间隔（米）：与跑道标志的 300 m 分组一致。 */
const TICK_STEP_M = 300;
/** 瞄准点标志距着陆入口 900 ft ≈ 274 m。 */
const AIMING_POINT_M = 274;

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

/** 跑道宽度（米）：navdata 有 `width` 就用，脏数据/缺失回落到常量。 */
function runwayWidth(runway: AirportRunway): number {
  const raw = Number(runway.width_m);
  return Number.isFinite(raw) && raw >= 15 && raw <= 80 ? raw : DEFAULT_RUNWAY_WIDTH_M;
}

/** 内移入口不会超过跑道的一半，脏数据也不至于把图压没。 */
function displacedLength(runway: AirportRunway, length: number, explicit?: number | null): number {
  const raw = Number(explicit ?? runway.displaced_threshold_m ?? 0);
  if (!Number.isFinite(raw) || raw <= 0) return 0;
  return Math.min(raw, length * 0.5);
}

/**
 * 跑道接地区俯视图：跑道轮廓/内移段 + 跑道编号/入口条纹/中线/接地区与瞄准点标志
 * + 每 300 m 刻度 + 物理入口与着陆入口 + 接地点与接地后滑跑轨迹 + 距入口/中心线偏移。
 * 横向按米单独缩放，纵向为真实比例，图中给出横向放大倍数、100 m 比例尺与图例。
 */
export function RunwayTouchdown({
  runway, touchdownLat, touchdownLon, thresholdDistanceM, centerlineOffsetM,
  displacedThresholdM, points = [], height = 300,
}: Props) {
  if (!runway || runway.lat == null || runway.lon == null) return null;
  const hasTouchdown = touchdownLat != null && touchdownLon != null;
  const length = runwayLength(runway);
  const displaced = displacedLength(runway, length, displacedThresholdM);
  const halfWidthM = runwayWidth(runway) / 2;
  const W = 960;
  const padX = 56;
  const centerY = height / 2;
  const xScale = (W - 2 * padX) / length;

  const td = hasTouchdown
    ? projectOnRunway(runway, touchdownLat as number, touchdownLon as number)
    : null;

  // 接地后的滑跑轨迹：跑道段（10Hz）优先，退化时才用接地后全部点
  const runwayPoints = points.filter((p) => p.mode === "RUNWAY");
  const sourcePoints = runwayPoints.length >= 2 ? runwayPoints : points;
  const projected = sourcePoints.map((p) => ({ t: p.t, ...projectOnRunway(runway, p.lat, p.lon) }));
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
    halfWidthM,
    ...rollout.map((p) => Math.abs(p.lateral)),
    td ? Math.abs(td.lateral) : 0,
  ];
  const maxAbs = Math.max(...extents, 1);
  const lateralScale = Math.min(3.2, Math.max(0.9, (centerY - 80) / maxAbs));
  const exaggeration = lateralScale / xScale;

  const y = (lateral: number) => centerY + lateral * lateralScale;
  const x = (along: number) => padX + along * xScale;

  const rolloutPath = rollout
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.along).toFixed(1)},${y(p.lateral).toFixed(1)}`)
    .join(" ");

  // 距入口距离以着陆入口（物理入口 + 内移）为基准
  const tdAlong = td ? td.along - displaced : thresholdDistanceM ?? null;
  const tdLateral = td ? td.lateral : centerlineOffsetM ?? null;

  // ---- 跑道标志（位置都是「距着陆入口的米数」） ----
  const usableEnd = Math.max(60, length - displaced - 40);
  const bar = (key: string, along: number, lenM: number, lateral: number, widM: number) => (
    <rect
      key={key}
      x={x(displaced + along)}
      y={y(lateral - widM / 2)}
      width={Math.max(0.8, lenM * xScale)}
      height={Math.max(1, widM * lateralScale)}
      fill="currentColor"
      fillOpacity={0.5}
    />
  );

  const thresholdBars = [0.24, 0.41, 0.58, 0.75].flatMap((f, i) => [
    bar(`tbL${i}`, 6, 30, -halfWidthM * f, 1.8),
    bar(`tbR${i}`, 6, 30, halfWidthM * f, 1.8),
  ]);

  const aimingPoint = AIMING_POINT_M + 45 <= usableEnd
    ? [0.34, -0.34].map((f, i) => bar(`ap${i}`, AIMING_POINT_M, 45, halfWidthM * f, 6))
    : null;

  const tdz = [300, 600, 900, 1200]
    .filter((d) => d + 22.5 <= usableEnd)
    .flatMap((d) => [0.55, 0.72, 0.89].flatMap((f, gi) => [
      bar(`tdzL${d}-${gi}`, d, 22.5, -halfWidthM * f, 1.8),
      bar(`tdzR${d}-${gi}`, d, 22.5, halfWidthM * f, 1.8),
    ]));

  const ticks: { d: number; label: string; major: boolean }[] = [];
  for (let d = 0; d <= length - displaced; d += TICK_STEP_M) {
    ticks.push({ d, label: `${Math.round(d)} m`, major: d === 0 });
  }
  if (ticks.length && ticks[ticks.length - 1].d < length - displaced - 30) {
    ticks.push({ d: length - displaced, label: `${Math.round(length)} m`, major: true });
  }

  const tickY = y(halfWidthM);
  const tickLabelY = tickY + 16;

  return (
    <svg viewBox={`0 0 ${W} ${height}`} width="100%" height={height} role="img"
      aria-label="Runway touchdown view">
      <defs>
        <pattern id="aoc-displaced-hatch" width="8" height="8" patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)">
          <line x1={0} y1={0} x2={0} y2={8} stroke="currentColor" strokeOpacity={0.45} strokeWidth={2} />
        </pattern>
      </defs>

      {/* 跑道轮廓（物理长度） */}
      <rect x={x(0)} y={y(-halfWidthM)} width={x(length) - x(0)}
        height={y(halfWidthM) - y(-halfWidthM)}
        fill="currentColor" fillOpacity={0.08} stroke="currentColor" strokeOpacity={0.35} />
      {/* 内移段（不可用着陆区） */}
      {displaced > 0 ? (
        <rect x={x(0)} y={y(-halfWidthM)} width={x(displaced) - x(0)}
          height={y(halfWidthM) - y(-halfWidthM)} fill="url(#aoc-displaced-hatch)" fillOpacity={0.25} />
      ) : null}

      {/* 跑道标志：入口条纹 / 瞄准点 / 接地区条纹 */}
      {thresholdBars}
      {aimingPoint}
      {tdz}

      {/* 跑道编号（着陆入口内侧） */}
      {runway.ident ? (
        <text x={x(displaced + 44)} y={centerY} fontSize={18} fontWeight={700}
          letterSpacing={2} fill="currentColor" fillOpacity={0.45} dominantBaseline="middle">
          {runway.ident}
        </text>
      ) : null}

      {/* 中线：着陆入口处实线（跑道号位置），其余虚线 */}
      <line x1={x(displaced + 6)} y1={centerY} x2={x(displaced + 40)} y2={centerY}
        stroke="currentColor" strokeOpacity={0.55} strokeWidth={2} />
      <line x1={x(displaced + 40)} y1={centerY} x2={x(length - 30)} y2={centerY}
        stroke="currentColor" strokeOpacity={0.45} strokeDasharray="12 10" />

      {/* 物理入口 */}
      <line x1={x(0)} y1={y(-halfWidthM)} x2={x(0)} y2={y(halfWidthM)}
        stroke="currentColor" strokeOpacity={displaced > 0 ? 0.45 : 0.8} strokeWidth={2.5} />
      {/* 着陆入口（内移后） */}
      <line x1={x(displaced)} y1={y(-halfWidthM)} x2={x(displaced)} y2={y(halfWidthM)}
        stroke="currentColor" strokeOpacity={0.85} strokeWidth={2.5} />

      {/* 每 300 m 刻度 + 米数 */}
      {ticks.map((t) => (
        <g key={`tick-${t.d}`}>
          <line x1={x(displaced + t.d)} y1={tickY} x2={x(displaced + t.d)} y2={tickY + (t.major ? 6 : 4)}
            stroke="currentColor" strokeOpacity={t.major ? 0.6 : 0.35} />
          <text x={x(displaced + t.d)} y={tickLabelY} fontSize={10} fill="currentColor"
            fillOpacity={0.55} textAnchor={t.d === 0 ? "start" : "middle"}>
            {t.label}
          </text>
        </g>
      ))}

      {rolloutPath ? (
        <path d={rolloutPath} fill="none" stroke="#1677ff" strokeWidth={2.5} strokeOpacity={0.9} />
      ) : null}

      {td ? (
        <>
          <circle cx={x(td.along)} cy={y(td.lateral)} r={6} fill="#fa541c" />
          <line x1={x(td.along)} y1={centerY} x2={x(td.along)} y2={y(td.lateral)}
            stroke="#fa541c" strokeWidth={1.5} strokeDasharray="4 3" />
          <text x={x(td.along)} y={y(td.lateral) + (td.lateral >= 0 ? 20 : -12)}
            fontSize={12} textAnchor="middle" fill="currentColor" fillOpacity={0.85}>
            接地点 {tdAlong != null ? `${Math.round(tdAlong)} m` : ""}
            {tdLateral != null ? ` / 偏移 ${tdLateral > 0 ? "+" : ""}${Math.round(tdLateral)} m` : ""}
          </text>
        </>
      ) : null}

      {tdAlong != null ? (
        <line x1={x(displaced)} y1={centerY} x2={x(displaced + tdAlong)} y2={centerY}
          stroke="#fa541c" strokeOpacity={0.45} strokeWidth={1} />
      ) : null}

      {/* 入口说明（放到跑道下面，避免与编号/瞄准点重叠） */}
      <text x={x(displaced)} y={tickLabelY + 16} fontSize={12} fill="currentColor" fillOpacity={0.75}>
        {runway.ident || "RWY"} {displaced > 0 ? "着陆入口" : "入口"}
        {displaced > 0 ? `（内移 ${Math.round(displaced)} m，物理入口 ${Math.round(length)} m 跑道头）` : ""}
      </text>

      {/* 图例 + 比例尺 */}
      <g transform={`translate(${padX}, ${height - 12})`} fontSize={11} fill="currentColor" fillOpacity={0.6}>
        <line x1={0} y1={-4} x2={16} y2={-4} stroke="#1677ff" strokeWidth={2.5} />
        <text x={20} y={0}>接地后滑跑</text>
        <circle cx={104} cy={-4} r={4} fill="#fa541c" />
        <text x={112} y={0}>接地点</text>
        <rect x={172} y={-10} width={12} height={10} fill="url(#aoc-displaced-hatch)" fillOpacity={0.5}
          stroke="currentColor" strokeOpacity={0.3} />
        <text x={190} y={0}>内移段</text>
        <text x={244} y={0}>
          横向放大 {exaggeration.toFixed(1)}×（纵向真实比例）· 距{displaced > 0 ? "着陆" : ""}入口{" "}
          {tdAlong != null ? `${Math.round(tdAlong)} m` : "—"}
          {" · "}中心线偏移 {tdLateral != null ? `${tdLateral > 0 ? "+" : ""}${tdLateral.toFixed(1)} m` : "—"}
        </text>
      </g>
      <g transform={`translate(${W - padX - 150}, ${height - 12})`} fontSize={11}
        fill="currentColor" fillOpacity={0.6}>
        <line x1={0} y1={-4} x2={100 * xScale} y2={-4} stroke="currentColor" strokeOpacity={0.7} />
        <line x1={0} y1={-9} x2={0} y2={1} stroke="currentColor" strokeOpacity={0.7} />
        <line x1={100 * xScale} y1={-9} x2={100 * xScale} y2={1} stroke="currentColor" strokeOpacity={0.7} />
        <text x={100 * xScale + 8} y={0}>100 m</text>
      </g>
    </svg>
  );
}
