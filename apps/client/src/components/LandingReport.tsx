import type { CSSProperties, ReactNode } from "react";
import { Empty } from "antd";
import type { AirportRunway, FlightRecord, TrackPoint } from "../types";
import { useI18n } from "../i18n";
import { RunwayTouchdown } from "./RunwayTouchdown";
import { TrendChart } from "./TrendChart";

interface Props {
  flight: FlightRecord;
  points: TrackPoint[];
  runway: AirportRunway | null;
  /** 到达机场标高：ALT 曲线的「AGL 近似」用。 */
  arrElevFt?: number | null;
  aircraftTitle?: string | null;
  dataSource?: string | null;
}

const C_ALT = "#3ddc97";
const C_VS = "#5b9dff";
const C_G = "#ffb547";

const cardStyle: CSSProperties = {
  background: "#0e131a", border: "1px solid #1b2431", borderRadius: 8, padding: "9px 11px",
};
const labelStyle: CSSProperties = {
  fontSize: 10, letterSpacing: 1, color: "#6b7c93", textTransform: "uppercase",
};
const valueStyle: CSSProperties = {
  fontFamily: "Consolas, 'SF Mono', monospace", fontWeight: 600, fontSize: 20,
  lineHeight: 1.2, color: "#e6edf6", marginTop: 2,
};
const unitStyle: CSSProperties = { fontSize: 10, color: "#7d8ea6", marginLeft: 4, fontWeight: 400 };
const subStyle: CSSProperties = { fontSize: 10, color: "#6b7c93", marginTop: 2 };

function Card({ label, value, unit, sub }: {
  label: string; value: ReactNode; unit?: string; sub?: ReactNode;
}) {
  return (
    <div style={cardStyle} data-card={label}>
      <div style={labelStyle}>{label}</div>
      <div style={valueStyle}>
        {value}
        {unit ? <span style={unitStyle}>{unit}</span> : null}
      </div>
      {sub ? <div style={subStyle}>{sub}</div> : null}
    </div>
  );
}

function secondsBetween(from?: string | null, to?: string | null): number | null {
  if (!from || !to) return null;
  const a = Date.parse(from);
  const b = Date.parse(to);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  return (b - a) / 1000;
}

function round(value: number | null | undefined): string {
  return value == null || !Number.isFinite(Number(value)) ? "—" : String(Math.round(Number(value)));
}

/**
 * 落地报告（版式对齐 `spikes/simconnect_probe/out2_report/report.html`）：
 * 报告头 + 落地行 + 卡片网格 + ALT/VS/G 三张曲线 + 跑道接地区。
 * 暗色 token 只作用在这个容器里，不跟全局 AntD 主题走。
 */
export function LandingReport({
  flight, points, runway, arrElevFt, aircraftTitle, dataSource,
}: Props) {
  const { tr } = useI18n();
  const landingT = secondsBetween(flight.block_off_utc, flight.landing_utc);
  const duration = landingT != null
    ? landingT
    : (points.length ? points[points.length - 1].t : null);
  const hasLanding = landingT != null && flight.touchdown_lat != null && flight.touchdown_lon != null;

  const elev = Number(arrElevFt ?? 0) || 0;
  const altSeries = points.map((p) => ({ t: p.t, v: p.alt_ft == null ? null : p.alt_ft - elev }));
  const vsSeries = points.map((p) => ({ t: p.t, v: p.vs_fpm }));
  const gSeries = points.map((p) => ({ t: p.t, v: p.g }));
  // 旧 BIN_V1 / demo 源可能没有 G：全 0 或缺失时整图跳过
  const hasG = gSeries.some((p) => typeof p.v === "number" && Math.abs(p.v) > 0.01);

  const title = (aircraftTitle || "").trim() || flight.aircraft_type || tr("机型未记录", "Type not recorded");
  const runwayLength = Number(runway?.length_m);
  const remaining = runwayLength > 0 && flight.threshold_distance_m != null
    ? Math.max(0, Math.round(runwayLength - flight.threshold_distance_m))
    : null;
  const tdDev = flight.centerline_offset_m;
  const marker = hasLanding ? landingT : null;

  return (
    <div
      className="landing-report"
      data-testid="landing-report"
      style={{
        background: "#080b10", border: "1px solid #1b2431", borderRadius: 10,
        color: "#e6edf6", padding: "20px 18px 18px", fontSize: 13, lineHeight: 1.45,
      }}
    >
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "flex-start",
        gap: 16, borderBottom: "1px solid #1c2532", paddingBottom: 14, marginBottom: 18,
      }}>
        <div>
          <div style={{ fontSize: 10, letterSpacing: 2, color: "#5f7387" }}>LANDING REPORT</div>
          <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: 0.5 }}>{title}</div>
        </div>
        <div style={{ textAlign: "right", color: "#7d8ea6", fontSize: 11, lineHeight: 1.6 }}>
          {duration != null ? `${tr("时长", "duration")} ${Math.round(duration)}s · ` : ""}
          {tr("样本", "samples")} {points.length}
          <br />
          {dataSource || "AOC"} · {flight.dep_icao || "????"} → {flight.arr_icao || "????"}
        </div>
      </div>

      {!hasLanding ? (
        <div style={{ ...cardStyle, color: "#6b7c93", marginBottom: 16 }}>
          {tr("未检测到落地（轨迹里没有空中→地面的跳变）", "No landing detected (no airborne→ground transition)")}
        </div>
      ) : (
        <>
          <div style={{
            display: "flex", alignItems: "center", gap: 8, fontSize: 12,
            color: "#9fb0c6", margin: "6px 0 10px",
          }}>
            <span style={{
              width: 7, height: 7, borderRadius: "50%", background: C_ALT,
              boxShadow: `0 0 8px ${C_ALT}`, display: "inline-block",
            }} />
            {tr("落地", "Landing")} {flight.arr_icao || "????"}/{flight.runway_ident || "—"} @ t={Math.round(landingT)}s
            <span style={{ color: "#6b7c93" }}>
              {flight.threshold_distance_m != null
                ? ` · ${tr("距着陆入口", "from threshold")} ${round(flight.threshold_distance_m)} m`
                : ""}
              {tdDev != null ? ` · ${tr("中心线", "centerline")} ${Math.abs(Math.round(tdDev))} m ${tdDev >= 0 ? tr("右", "right") : tr("左", "left")}` : ""}
            </span>
          </div>

          <div style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(120px,1fr))",
            gap: 8, marginBottom: 18,
          }}>
            <Card label="V/S" value={round(flight.touchdown_vs_fpm)} unit="fpm" />
            <Card
              label="G-FORCE"
              value={flight.max_g_landing != null ? flight.max_g_landing.toFixed(2) : round(flight.touchdown_g)}
              unit="g"
              sub={flight.max_g_landing != null && flight.touchdown_g != null
                ? `${tr("峰值", "peak")} ${flight.max_g_landing.toFixed(2)} / ${tr("触地帧", "touchdown")} ${flight.touchdown_g.toFixed(2)}`
                : tr("触地帧", "touchdown frame")}
            />
            <Card label="RUNWAY" value={flight.runway_ident || "—"} sub={flight.arr_icao || "—"} />
            <Card
              label={tr("接地区", "Touchdown zone")}
              value={round(flight.threshold_distance_m)}
              unit="m"
              sub={remaining != null ? `${tr("剩余", "remaining")} ${remaining} m` : tr("距入口", "from threshold")}
            />
            <Card
              label="TD DEV"
              value={tdDev != null ? Math.abs(tdDev).toFixed(1) : "—"}
              unit={tdDev == null ? "m" : tdDev >= 0 ? tr("m 右", "m right") : tr("m 左", "m left")}
              sub={tr("中心线横向偏差", "centerline deviation")}
            />
            <Card label={tr("弹跳", "Bounces")} value={flight.bounce_count ?? 0} />
            <Card label={tr("滑跑距离", "Landing roll")} value={round(flight.landing_distance_m)} unit="m" />
            <Card label={tr("全程最大 G", "Max G flight")}
              value={flight.max_g_flight != null ? flight.max_g_flight.toFixed(2) : "—"} unit="g" />
          </div>
        </>
      )}

      <TrendChart title="ALT PROFILE" unit="ft" color={C_ALT} series={altSeries} markerT={marker}
        note={tr("AGL 近似（已减到达机场标高）", "AGL approximation (airport elevation subtracted)")} />
      <TrendChart title="VERTICAL SPEED" unit="fpm" color={C_VS} series={vsSeries} markerT={marker} />
      {hasG ? (
        <TrendChart title="G FORCE" unit="g" color={C_G} series={gSeries} markerT={marker} />
      ) : (
        <TrendChart title="G FORCE" unit="g" color={C_G} series={[]} markerT={marker}
          emptyText={tr("样本不足（旧 BIN_V1 或 demo 源没有 G）", "Not enough samples (no G in BIN_V1/demo)")} />
      )}

      <div style={{
        background: "#0e131a", border: "1px solid #1b2431", borderRadius: 8,
        padding: "10px 12px",
      }}>
        <div style={{ fontSize: 10, letterSpacing: 1.4, color: "#8fa3ba", marginBottom: 6 }}>
          RUNWAY TOUCHDOWN ZONE
          <span style={{ color: "#6b7c93" }}>
            {" · "}{flight.arr_icao || "—"}/{flight.runway_ident || "—"}
            {runwayLength > 0 ? ` · ${tr("全长", "full length")} ${Math.round(runwayLength)} m` : ""}
          </span>
        </div>
        {runway && hasLanding ? (
          <RunwayTouchdown
            runway={runway}
            touchdownLat={flight.touchdown_lat}
            touchdownLon={flight.touchdown_lon}
            thresholdDistanceM={flight.threshold_distance_m}
            centerlineOffsetM={flight.centerline_offset_m}
            displacedThresholdM={flight.displaced_threshold_m ?? runway.displaced_threshold_m ?? 0}
            points={points}
            height={300}
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={tr("无跑道数据（navdata 缺失或未识别跑道号）", "No runway data")} />
        )}
      </div>
    </div>
  );
}
