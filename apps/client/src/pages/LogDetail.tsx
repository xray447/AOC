import { ArrowLeftOutlined, CloudDownloadOutlined, DeleteOutlined, SaveOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Descriptions, Empty, Input, Popconfirm, Row, Space, Spin, Table, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, download } from "../api";
import { MetricCard } from "../components/MetricCard";
import { TrackMap } from "../components/TrackMap";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import type { FlightRecord, TrackData } from "../types";
import { fmtAltitude, fmtDateTime, fmtDistance, fmtMinutes, fmtWeight, ratingLabels, statusLabels } from "../utils";

const { Text } = Typography;

export function LogDetail() {
  const { id } = useParams<{ id: string }>();
  const { tr } = useI18n();
  const { settings, dark } = useApp();
  const navigate = useNavigate();
  const [flight, setFlight] = useState<FlightRecord | null>(null);
  const [track, setTrack] = useState<TrackData | null>(null);
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

  return (
    <div className="page">
      <div className="page-head">
        <Space align="start">
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/logs")} />
          <div>
            <h2>{flight.dep_icao || "????"} → {flight.arr_icao || "????"}</h2>
            <p>
              {fmtDateTime(flight.block_off_utc)} · {flight.aircraft_type || "—"} · {flight.callsign || "—"}
              {status ? <Tag style={{ marginLeft: 8 }} color={status.color}>{tr(status.zh, status.en)}</Tag> : null}
              {rating ? <Tag color={rating.color}>{tr(rating.zh, rating.en)}</Tag> : null}
            </p>
          </div>
        </Space>
        <Space wrap>
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

      <div className="metric-grid">
        <MetricCard title={tr("接地 VS", "Touchdown V/S")} value={flight.touchdown_vs_fpm != null ? Math.round(flight.touchdown_vs_fpm) : "—"} suffix="fpm" />
        <MetricCard title={tr("接地过载", "Touchdown G")} value={flight.touchdown_g != null ? flight.touchdown_g.toFixed(2) : "—"} suffix="G" />
        <MetricCard title={tr("窗口最大 G", "Max G landing")} value={flight.max_g_landing != null ? flight.max_g_landing.toFixed(2) : "—"} suffix="G" />
        <MetricCard title={tr("全程最大 G", "Max G flight")} value={flight.max_g_flight != null ? flight.max_g_flight.toFixed(2) : "—"} suffix="G" />
        <MetricCard title={tr("跑道", "Runway")} value={flight.runway_ident || "—"} extra={flight.threshold_distance_m != null ? `${tr("距入口", "From threshold")} ${Math.round(flight.threshold_distance_m)} m` : undefined} />
        <MetricCard title={tr("中心线偏移", "Centerline")} value={flight.centerline_offset_m != null ? Math.round(flight.centerline_offset_m) : "—"} suffix="m" />
        <MetricCard title={tr("弹跳", "Bounces")} value={flight.bounce_count ?? 0} />
        <MetricCard title={tr("滑跑距离", "Landing roll")} value={flight.landing_distance_m != null ? Math.round(flight.landing_distance_m) : "—"} suffix="m" />
      </div>

      <Card className="panel" variant="borderless" title={tr("轨迹回放", "Track replay")} extra={<Text className="muted">{track?.total_points ?? 0} {tr("点", "pts")} · {track?.encoding}</Text>}>
        {track ? (
          <TrackMap
            points={track.points}
            events={track.events}
            dark={dark}
            tilesUrl={settings.tiles_url}
            basemap={settings.map_style}
            height={420}
          />
        ) : <Empty />}
      </Card>

      <Row gutter={[12, 12]}>
        <Col xs={24} lg={14}>
          <Card className="panel" variant="borderless" title={tr("飞行详情", "Flight details")} size="small">
            <Descriptions size="small" column={{ xs: 1, sm: 2 }}>
              <Descriptions.Item label={tr("起飞", "Takeoff")}>{fmtDateTime(flight.takeoff_utc)}</Descriptions.Item>
              <Descriptions.Item label={tr("落地", "Landing")}>{fmtDateTime(flight.landing_utc)}</Descriptions.Item>
              <Descriptions.Item label={tr("轮挡时间", "Block")}>{fmtMinutes(flight.block_minutes)}</Descriptions.Item>
              <Descriptions.Item label={tr("距离", "Distance")}>{fmtDistance(flight.distance_nm, settings.units)}</Descriptions.Item>
              <Descriptions.Item label={tr("燃油", "Fuel")}>
                {flight.fuel_start_kg != null ? `${fmtWeight(flight.fuel_start_kg, settings.units)} → ${fmtWeight(flight.fuel_end_kg, settings.units)}` : "—"}
                {flight.fuel_used_kg != null ? <span className="muted"> ({fmtWeight(flight.fuel_used_kg, settings.units)})</span> : null}
              </Descriptions.Item>
              <Descriptions.Item label="AIRAC">{flight.airac || "—"}</Descriptions.Item>
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
    </div>
  );
}
