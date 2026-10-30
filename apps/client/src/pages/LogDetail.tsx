import { ArrowLeftOutlined, CloudDownloadOutlined, DeleteOutlined, FileTextOutlined, SaveOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Collapse, Descriptions, Empty, Input, Popconfirm, Row, Space, Spin, Table, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, download } from "../api";
import { LandingReport } from "../components/LandingReport";
import { TrackMap } from "../components/TrackMap";
import { projectOnRunway } from "../components/RunwayTouchdown";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import type { AirportDetail, AirportRunway, FlightRecord, TrackData } from "../types";
import { fmtAltitude, fmtDateTime, fmtDistance, fmtMinutes, fmtWeight, ratingLabels, statusLabels } from "../utils";

const { Text } = Typography;

/** 两个 ISO 时刻之间的秒数（用于「已飞时间」）。 */
function secondsBetween(from?: string | null, to?: string | null): number {
  if (!from || !to) return 0;
  const a = Date.parse(from);
  const b = Date.parse(to);
  return Number.isFinite(a) && Number.isFinite(b) ? (b - a) / 1000 : 0;
}

/** 优先按跑道号匹配；没有跑道号时取与接地点横向偏移最小的点。 */
function pickRunway(airport: AirportDetail | null, ident?: string | null,
                    lat?: number | null, lon?: number | null): AirportRunway | null {
  const runways = airport?.runways?.filter((r) => r.lat != null && r.lon != null && r.heading != null) || [];
  if (!runways.length) return null;
  const wanted = (ident || "").trim().toUpperCase();
  if (wanted) {
    const exact = runways.find((r) => (r.ident || "").trim().toUpperCase() === wanted);
    if (exact) return exact;
  }
  if (lat != null && lon != null) {
    let best: AirportRunway | null = null;
    let bestOffset = Number.POSITIVE_INFINITY;
    for (const r of runways) {
      const offset = Math.abs(projectOnRunway(r, lat, lon).lateral);
      if (offset < bestOffset) { bestOffset = offset; best = r; }
    }
    if (best) return best;
  }
  return runways[0];
}

export function LogDetail() {
  const { id } = useParams<{ id: string }>();
  const { tr } = useI18n();
  const { settings, dark, recording } = useApp();
  const navigate = useNavigate();
  const [flight, setFlight] = useState<FlightRecord | null>(null);
  const [track, setTrack] = useState<TrackData | null>(null);
  const [airport, setAirport] = useState<AirportDetail | null>(null);
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const [f, t] = await Promise.all([
        api<FlightRecord>(`/local/flights/${id}`),
        api<TrackData>(`/local/flights/${id}/track`),
      ]);
      setFlight(f);
      setTrack(t);
      setNotes(f.notes || "");
      // 到达机场跑道几何（入口坐标/真航向/长度）：接地区俯视图用；无 navdata 时降级
      if (f.arr_icao) {
        try {
          setAirport(await api<AirportDetail>(`/local/airports/${encodeURIComponent(f.arr_icao)}`));
        } catch {
          setAirport(null);
        }
      } else {
        setAirport(null);
      }
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { void load(); }, [load]);

  const saveNotes = async () => {
    if (!id) return;
    setSaving(true);
    try {
      await api(`/local/flights/${id}`, { method: "PATCH", body: JSON.stringify({ notes }) });
      message.success(tr("备注已保存", "Notes saved"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!id) return;
    try {
      await api(`/local/flights/${id}`, { method: "DELETE" });
      message.success(tr("记录已删除", "Flight deleted"));
      navigate("/logs");
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  if (loading) return <div className="page"><Spin size="large" /></div>;
  if (!flight) return <div className="page"><Empty description={tr("记录不存在", "Flight not found")} /></div>;

  const rating = flight.landing_rating ? ratingLabels[flight.landing_rating] : null;
  const status = statusLabels[flight.status];
  const runway = pickRunway(airport, flight.runway_ident, flight.touchdown_lat, flight.touchdown_lon);
  const points = track?.points || [];

  return (
    <div className="page">
      <div className="page-head">
        <Space align="start">
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/logs")} />
          <div>
            <h2>{flight.dep_icao || "????"} → {flight.arr_icao || "????"}</h2>
            <p>
              {fmtDateTime(flight.block_off_utc)} · {flight.aircraft_type || "—"} · {flight.callsign || "—"}
              {flight.aircraft_title ? <span className="muted"> · {flight.aircraft_title}</span> : null}
              {status ? <Tag style={{ marginLeft: 8 }} color={status.color}>{tr(status.zh, status.en)}</Tag> : null}
              {rating ? <Tag color={rating.color}>{tr(rating.zh, rating.en)}</Tag> : null}
            </p>
          </div>
        </Space>
        <Space wrap>
          <Button icon={<FileTextOutlined />} onClick={() => void download(`/local/flights/${flight.id}/export?format=html`, `${flight.id}.html`).catch((e: Error) => message.error(e.message))}>
            {tr("报告 HTML", "Report HTML")}
          </Button>
          <Button icon={<CloudDownloadOutlined />} onClick={() => void download(`/local/flights/${flight.id}/export?format=gpx`, `${flight.id}.gpx`).catch((e: Error) => message.error(e.message))}>
            GPX
          </Button>
          <Button onClick={() => void download(`/local/flights/${flight.id}/export?format=csv`, `${flight.id}.csv`).catch((e: Error) => message.error(e.message))}>
            CSV
          </Button>
          <Button onClick={() => void download(`/local/flights/${flight.id}/export?format=json`, `${flight.id}.json`).catch((e: Error) => message.error(e.message))}>
            JSON
          </Button>
          <Popconfirm title={tr("删除这条记录？", "Delete this flight?")} onConfirm={() => void remove()}>
            <Button danger icon={<DeleteOutlined />}>{tr("删除", "Delete")}</Button>
          </Popconfirm>
        </Space>
      </div>

      {flight.anomaly_flags?.length ? (
        <Alert
          type="warning"
          showIcon
          message={tr("检测到异常数据（个人模式只提示，不惩罚）", "Anomalies detected (personal mode only warns)")}
          description={flight.anomaly_flags.join(" · ")}
        />
      ) : null}

      <LandingReport
        flight={flight}
        points={points}
        runway={runway}
        arrElevFt={airport?.elev_ft ?? null}
        aircraftTitle={flight.aircraft_title}
        dataSource={recording?.simlink_source || flight.mode || "AOC"}
      />

      <Card className="panel" variant="borderless" title={tr("轨迹回放", "Track replay")} extra={<Text className="muted">{track?.total_points ?? 0} {tr("点", "pts")} · {track?.encoding}</Text>}>
        {track ? (
          <TrackMap
            points={points}
            events={track.events}
            dark={dark}
            tilesUrl={settings.tiles_url}
            basemap={settings.map_style}
            height={420}
          />
        ) : <Empty />}
      </Card>

      <Collapse
        defaultActiveKey={["details"]}
        items={[{
          key: "details",
          label: tr("详细信息（飞行参数 / 事件 / 备注）", "Details (parameters / events / notes)"),
          children: (
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <Row gutter={[12, 12]}>
                <Col xs={24} lg={14}>
                  <Card className="panel" variant="borderless" title={tr("飞行详情", "Flight details")} size="small">
                    <Descriptions size="small" column={{ xs: 1, sm: 2 }}>
                      <Descriptions.Item label={tr("起飞", "Takeoff")}>{fmtDateTime(flight.takeoff_utc)}</Descriptions.Item>
                      <Descriptions.Item label={tr("落地", "Landing")}>{fmtDateTime(flight.landing_utc)}</Descriptions.Item>
                      <Descriptions.Item label={tr("轮挡时间", "Block")}>{fmtMinutes(flight.block_minutes)}</Descriptions.Item>
                      <Descriptions.Item label={tr("距离", "Distance")}>{fmtDistance(flight.distance_nm, settings.units)}</Descriptions.Item>
                      <Descriptions.Item label={tr("发动机时间", "Engine time")}>
                        {flight.engine_seconds != null
                          ? `${Math.floor(flight.engine_seconds / 3600)}:${String(Math.floor((flight.engine_seconds % 3600) / 60)).padStart(2, "0")}:${String(flight.engine_seconds % 60).padStart(2, "0")}`
                          : "—"}
                        {flight.engine_estimated ? <span className="muted"> ({tr("估算", "estimated")})</span> : null}
                      </Descriptions.Item>
                      <Descriptions.Item label={tr("已飞时间", "Flight time")}>
                        {flight.takeoff_utc && flight.landing_utc ? fmtMinutes(secondsBetween(flight.takeoff_utc, flight.landing_utc) / 60) : "—"}
                      </Descriptions.Item>
                      <Descriptions.Item label={tr("燃油", "Fuel")}>
                        {flight.fuel_start_kg != null ? `${fmtWeight(flight.fuel_start_kg, settings.units)} → ${fmtWeight(flight.fuel_end_kg, settings.units)}` : "—"}
                        {flight.fuel_used_kg != null ? <span className="muted"> ({fmtWeight(flight.fuel_used_kg, settings.units)})</span> : null}
                      </Descriptions.Item>
                      <Descriptions.Item label={tr("实际 ZFW", "Actual ZFW")}>
                        {flight.actual_zfw_kg != null ? fmtWeight(flight.actual_zfw_kg, settings.units) : "—"}
                        {flight.zfw_delta_kg != null ? (
                          <span className="muted">
                            {" "}({flight.zfw_delta_kg > 0 ? "+" : ""}{Math.round(flight.zfw_delta_kg)} kg)
                          </span>
                        ) : null}
                      </Descriptions.Item>
                      <Descriptions.Item label={tr("机型标题", "Aircraft title")}>{flight.aircraft_title || "—"}</Descriptions.Item>
                      <Descriptions.Item label="AIRAC">{flight.airac || "—"}</Descriptions.Item>
                      <Descriptions.Item label={tr("高度", "Altitude")}>
                        {points.length ? fmtAltitude(points[points.length - 1].alt_ft, settings.units) : "—"}
                      </Descriptions.Item>
                      <Descriptions.Item label={tr("轨迹点", "Track points")}>{flight.track_points ?? "—"} / {tr("原始", "raw")} {(flight as unknown as { track_profile?: { raw_points?: number } }).track_profile?.raw_points ?? "—"}</Descriptions.Item>
                      <Descriptions.Item label={tr("体积", "Size")}>{flight.track_bytes != null ? `${(flight.track_bytes / 1024).toFixed(1)} KB` : "—"}</Descriptions.Item>
                      <Descriptions.Item label={tr("保真度", "Fidelity")}>{flight.track_fidelity_m != null ? `${flight.track_fidelity_m} m` : "—"}</Descriptions.Item>
                      <Descriptions.Item label={tr("校验", "Validation")}>{flight.validation_status || "—"}</Descriptions.Item>
                    </Descriptions>
                  </Card>
                </Col>
                <Col xs={24} lg={10}>
                  <Card className="panel" variant="borderless" title={tr("事件", "Events")} size="small" styles={{ body: { padding: 0 } }}>
                    <Table
                      size="small"
                      rowKey={(e, i) => `${e.type}-${i}`}
                      pagination={false}
                      dataSource={track?.events || []}
                      locale={{ emptyText: tr("无事件", "No events") }}
                      columns={[
                        {
                          title: tr("时间", "Time"), dataIndex: "t_offset_ms",
                          render: (v: number) => {
                            const s = Math.round(v / 1000);
                            return <span className="mono">{Math.floor(s / 60)}:{String(s % 60).padStart(2, "0")}</span>;
                          },
                          width: 80,
                        },
                        { title: tr("类型", "Type"), dataIndex: "type", render: (v: string) => <Tag>{v}</Tag> },
                        { title: tr("数据", "Data"), dataIndex: "payload", render: (v: Record<string, unknown>) => <span className="muted" style={{ fontSize: 11 }}>{JSON.stringify(v)}</span> },
                      ]}
                    />
                  </Card>
                </Col>
              </Row>

              <Card className="panel" variant="borderless" title={tr("备注", "Notes")} size="small">
                <Space direction="vertical" style={{ width: "100%" }}>
                  <Input.TextArea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} placeholder={tr("这次飞行的备注…", "Notes about this flight…")} />
                  <Button icon={<SaveOutlined />} loading={saving} onClick={() => void saveNotes()}>{tr("保存备注", "Save notes")}</Button>
                </Space>
              </Card>
            </Space>
          ),
        }]}
      />
    </div>
  );
}
