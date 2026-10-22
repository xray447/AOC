import {
  ArrowRightOutlined,
  CompassOutlined,
  DatabaseOutlined,
  PlayCircleOutlined,
  PoweroffOutlined,
  RocketOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Empty, Space, Table, Tag, Tooltip, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { MetricCard } from "../components/MetricCard";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import type { FlightList, FlightRecord, Stats } from "../types";
import { flightTitle, fmtDate, fmtDistance, fmtHms, fmtMinutes, ratingLabels, statusLabels } from "../utils";

const { Text } = Typography;

export function Dashboard() {
  const { tr } = useI18n();
  const { settings, navdata, recording, bootstrap, refresh } = useApp();
  const navigate = useNavigate();
  const [stats, setStats] = useState<Stats | null>(null);
  const [recent, setRecent] = useState<FlightRecord[]>([]);
  const [volanta, setVolanta] = useState<{ flown_legs: number; last_sync?: { synced_at: string } | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  const load = useCallback(async () => {
    const [s, f, v] = await Promise.all([
      api<Stats>("/local/stats"),
      api<FlightList>("/local/flights?limit=6"),
      api<{ flown_legs: number; last_sync?: { synced_at: string } | null }>("/local/volanta/status"),
    ]);
    setStats(s);
    setRecent(f.items);
    setVolanta(v);
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (!recording.active) void load(); }, [recording.active, load]);

  useEffect(() => {
    if (!recording.active || !recording.started_at) { setElapsed(0); return; }
    const tick = () => setElapsed((Date.now() - new Date(recording.started_at!).getTime()) / 1000);
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [recording.active, recording.started_at]);

  const start = async () => {
    setBusy(true);
    try {
      await api("/local/recording/start", { method: "POST" });
      message.success(tr("已开始记录", "Recording started"));
      await refresh();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    try {
      const res = await api<{ flight: FlightRecord | null }>("/local/recording/stop", {
        method: "POST",
        body: JSON.stringify({ abort: false }),
      });
      await refresh();
      if (res.flight?.id) {
        message.success(tr("飞行已保存", "Flight saved"));
        navigate(`/logs/${res.flight.id}`);
      } else {
        message.info(tr("记录已结束（样本不足，未生成日志）", "Recording ended (not enough samples)"));
      }
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const clock = (seconds: number) => {
    const s = Math.max(0, Math.floor(seconds));
    return `${Math.floor(s / 3600).toString().padStart(2, "0")}:${Math.floor((s % 3600) / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;
  };

  const columns = [
    {
      title: tr("日期", "Date"), dataIndex: "block_off_utc", width: 110,
      render: (v: string) => <span className="mono">{fmtDate(v)}</span>,
    },
    {
      title: tr("航段", "Leg"), key: "leg",
      render: (_: unknown, f: FlightRecord) => (
        <Link to={`/logs/${f.id}`} style={{ fontWeight: 600 }}>{flightTitle(f)}</Link>
      ),
    },
    { title: tr("机型", "Type"), dataIndex: "aircraft_type", width: 90, render: (v: string) => v || "—" },
    { title: tr("时长", "Block"), dataIndex: "block_minutes", width: 90, render: (v: number) => fmtMinutes(v) },
    { title: tr("距离", "Distance"), dataIndex: "distance_nm", width: 100, render: (v: number) => fmtDistance(v, settings.units) },
    {
      title: tr("落地", "Landing"), key: "landing", width: 130,
      render: (_: unknown, f: FlightRecord) => f.landing_rating ? (
        <Tag color={ratingLabels[f.landing_rating]?.color || "default"}>
          {f.touchdown_vs_fpm != null ? `${Math.round(f.touchdown_vs_fpm)} fpm` : ratingLabels[f.landing_rating]?.zh}
        </Tag>
      ) : "—",
    },
    {
      title: tr("状态", "Status"), dataIndex: "status", width: 100,
      render: (v: string) => <Tag color={statusLabels[v]?.color}>{statusLabels[v] ? tr(statusLabels[v].zh, statusLabels[v].en) : v}</Tag>,
    },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("运行概览", "Overview")}</h2>
          <p>{tr("今天的飞行、数据源状态与最近记录", "Today's flying, data sources and recent logbook")}</p>
        </div>
        <Space>
          <Button icon={<CompassOutlined />} onClick={() => navigate("/recommend")}>{tr("找机场", "Discover")}</Button>
          <Button type="primary" icon={<RocketOutlined />} onClick={() => navigate("/route")}>{tr("生成航路", "Plan route")}</Button>
        </Space>
      </div>

      <div className="hero">
        <div className="panel hero-main">
          <div className="hero-kicker">{recording.active ? tr("正在记录", "Recording") : tr("个人模式", "Personal mode")}</div>
          {recording.active ? (
            <>
              <div className="hero-title mono">{clock(elapsed)}</div>
              <div className="hero-sub">
                {tr("阶段", "Phase")} <Tag color="processing">{recording.phase}</Tag>
                {tr("发动机", "Engine")} {fmtHms(recording.engine_seconds)} · {tr("已飞", "Airborne")} {fmtHms(recording.flight_seconds)}
                {recording.engine_estimated ? ` (${tr("估算", "estimated")})` : ""}
                {" · "}{recording.aircraft_title || settings.aircraft_type}
              </div>
              <Space>
                <Button danger type="primary" icon={<PoweroffOutlined />} loading={busy} onClick={() => void stop()}>
                  {tr("结束并生成日志", "Stop & save")}
                </Button>
                <Button onClick={() => void refresh()}>{tr("刷新状态", "Refresh")}</Button>
              </Space>
            </>
          ) : (
            <>
              <div className="hero-title">{tr("准备下一次飞行", "Ready for the next flight")}</div>
              <div className="hero-sub">
                {recording.simlink_connected
                  ? tr("SimLink 已连接，起飞后会自动开始记录；也可手动开始。", "SimLink is online — recording starts automatically after takeoff, or manually now.")
                  : tr("SimLink 离线。请启动 aoc-simlink（或 Tauri 客户端），否则没有遥测可记录。", "SimLink is offline. Start aoc-simlink (or the Tauri client) to record telemetry.")}
              </div>
              <Space wrap>
                <Button type="primary" size="large" icon={<PlayCircleOutlined />} loading={busy} onClick={() => void start()}>
                  {tr("开始记录", "Start recording")}
                </Button>
                <Button size="large" icon={<RocketOutlined />} onClick={() => navigate("/route")}>{tr("先规划航路", "Plan first")}</Button>
                {recording.last_error ? <Text type="warning">{recording.last_error}</Text> : null}
              </Space>
            </>
          )}
          {!navdata.available ? (
            <Alert
              style={{ marginTop: 16 }}
              type="warning"
              showIcon
              message={tr("navdata 未导入", "navdata missing")}
              description={tr("推荐、航路图与跑道识别不可用；SimBrief 仍可正常使用。", "Discovery, graph routes and runway detection are unavailable; SimBrief still works.")}
              action={<Button size="small" onClick={() => navigate("/settings")}>{tr("去导入", "Import")}</Button>}
            />
          ) : null}
        </div>

        <div className="panel panel-pad">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <strong>{tr("数据源", "Data sources")}</strong>
            <Button type="text" size="small" icon={<SyncOutlined />} onClick={() => void load()}>{tr("检查", "Check")}</Button>
          </div>
          <div className="source-grid" style={{ gridTemplateColumns: "1fr" }}>
            <div className="source-card">
              <div className="source-title">{tr("导航数据", "navdata")}<Tag color={navdata.available ? "blue" : "default"}>{navdata.available ? `AIRAC ${navdata.airac}` : "missing"}</Tag></div>
              <div className="source-value">{navdata.available ? `${navdata.airports.toLocaleString()} ${tr("机场", "airports")} · ${navdata.airways.toLocaleString()} ${tr("航路", "airways")}` : navdata.error}</div>
            </div>
            <div className="source-card">
              <div className="source-title">SimLink<Tag color={recording.simlink_connected ? "green" : "default"}>{recording.simlink_connected ? tr("在线", "online") : tr("离线", "offline")}</Tag></div>
              <div className="source-value">{recording.sim_connected ? `${tr("模拟器已连接", "Sim connected")} · ${recording.simlink_version || ""}` : tr("等待模拟器 / demo 源", "Waiting for simulator / demo source")}</div>
            </div>
            <div className="source-card">
              <div className="source-title">Volanta<Tag color={settings.volanta_enabled ? "cyan" : "default"}>{settings.volanta_enabled ? tr("已启用", "enabled") : tr("关闭", "off")}</Tag></div>
              <div className="source-value">{volanta?.flown_legs ?? 0} {tr("条历史航段", "historical legs")}{volanta?.last_sync ? ` · ${volanta.last_sync.synced_at.slice(0, 10)}` : ""}</div>
            </div>
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 10 }}>
            {tr("本地库", "Local DB")} · {bootstrap.home}
          </div>
        </div>
      </div>

      <div className="metric-grid">
        <MetricCard title={tr("总飞行", "Flights")} value={stats?.flights ?? 0} suffix={tr("班", "flights")} />
        <MetricCard title={tr("总时间", "Total time")} value={fmtMinutes(stats?.total_minutes)} />
        <MetricCard title={tr("总距离", "Distance")} value={Math.round(stats?.total_distance_nm ?? 0)} suffix="NM" />
        <MetricCard title={tr("机场", "Airports")} value={stats?.airports ?? 0} extra={`${stats?.countries ?? 0} ${tr("个国家/地区", "countries")}`} />
        <MetricCard title={tr("平均接地 VS", "Avg touchdown")} value={stats?.avg_landing_vs_fpm != null ? Math.round(stats.avg_landing_vs_fpm) : "—"} suffix="fpm" />
        <MetricCard title={tr("最大过载", "Max G")} value={stats?.max_g_flight != null ? stats.max_g_flight.toFixed(2) : "—"} suffix="G" />
      </div>

      <Card
        className="panel"
        variant="borderless"
        title={tr("最近飞行", "Recent flights")}
        extra={<Link to="/logs">{tr("全部日志", "All flights")} <ArrowRightOutlined /></Link>}
        styles={{ body: { padding: 0 } }}
      >
        {recent.length ? (
          <Table rowKey="id" size="small" pagination={false} dataSource={recent} columns={columns} />
        ) : (
          <Empty
            style={{ padding: 28 }}
            description={tr("还没有飞行记录。开始记录或导入 Volanta CSV。", "No flights yet. Start recording or import a Volanta CSV.")}
          />
        )}
      </Card>

      <div className="source-grid">
        <div className="panel panel-pad">
          <Space direction="vertical" size={4}>
            <strong><DatabaseOutlined /> {tr("轨迹与档案", "Tracks & archive")}</strong>
            <span className="muted">{tr("轨迹按段存储（BIN_V1），可在日志详情回放并导出 GPX/CSV/JSON；档案导出为 zip。", "Tracks are stored per segment (BIN_V1), replayable and exportable as GPX/CSV/JSON; archive export is a zip.")}</span>
            <Link to="/settings">{tr("打开档案与备份", "Open archive & backup")}</Link>
          </Space>
        </div>
        <div className="panel panel-pad">
          <Space direction="vertical" size={4}>
            <strong><Tooltip title={tr("AIP → 覆盖检查 → 图，任何一步失败都给 SimBrief", "AIP → coverage → graph; any failure falls back to SimBrief")}>{tr("航路引擎", "Route engine")}</Tooltip></strong>
            <span className="muted">{tr("当前优先级：AIP 官方航路 > 覆盖检查 > Pre-train 图。链路结果会显示来源与警告，不伪造航路。", "Priority: AIP > coverage > Pre-train graph. Results show source and warnings; no fabricated routes.")}</span>
            <Link to="/route">{tr("规划示例航路", "Plan a route")}</Link>
          </Space>
        </div>
      </div>
    </div>
  );
}
