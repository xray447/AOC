import { Card, Col, Empty, Progress, Row, Space, Table, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { MetricCard } from "../components/MetricCard";
import { useI18n } from "../i18n";
import type { Stats as StatsData } from "../types";
import { fmtMinutes, pct, ratingLabels } from "../utils";

const { Text } = Typography;

export function Stats() {
  const { tr } = useI18n();
  const [stats, setStats] = useState<StatsData | null>(null);

  useEffect(() => {
    api<StatsData>("/local/stats").then(setStats).catch(() => undefined);
  }, []);

  const maxMonthly = useMemo(
    () => Math.max(1, ...(stats?.monthly.map((m) => m.flights) ?? [1])),
    [stats],
  );
  const ratingTotal = useMemo(
    () => Object.values(stats?.landing_ratings ?? {}).reduce((a, b) => a + b, 0),
    [stats],
  );

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("统计", "Statistics")}</h2>
          <p>{tr("只统计 AOC 本地完成的飞行；Volanta 历史仅参与机场去重", "Only completed AOC flights count here; Volanta history only feeds airport dedupe")}</p>
        </div>
      </div>

      <div className="metric-grid">
        <MetricCard title={tr("总飞行", "Flights")} value={stats?.flights ?? 0} />
        <MetricCard title={tr("总时间", "Total time")} value={fmtMinutes(stats?.total_minutes)} />
        <MetricCard title={tr("总距离", "Total distance")} value={Math.round(stats?.total_distance_nm ?? 0)} suffix="NM" />
        <MetricCard title={tr("机场", "Airports")} value={stats?.airports ?? 0} />
        <MetricCard title={tr("国家/地区", "Countries")} value={stats?.countries ?? 0} />
        <MetricCard title={tr("机型", "Types")} value={stats?.aircraft_types ?? 0} />
        <MetricCard title={tr("平均接地", "Avg touchdown")} value={stats?.avg_landing_vs_fpm != null ? Math.round(stats.avg_landing_vs_fpm) : "—"} suffix="fpm" />
        <MetricCard title={tr("最大过载", "Max G")} value={stats?.max_g_flight != null ? stats.max_g_flight.toFixed(2) : "—"} suffix="G" />
      </div>

      <Row gutter={[12, 12]}>
        <Col xs={24} lg={14}>
          <Card className="panel" variant="borderless" title={tr("月度飞行", "Monthly flights")}>
            {stats?.monthly.length ? (
              <div className="monthly-bars">
                {stats.monthly.map((m) => (
                  <div className="month-bar" key={m.month} title={`${m.month}: ${m.flights} flights · ${fmtMinutes(m.minutes)}`}>
                    <span className="muted" style={{ fontSize: 10 }}>{m.flights}</span>
                    <div className="bar" style={{ height: `${Math.max(4, (m.flights / maxMonthly) * 120)}px` }} />
                    <span className="label">{m.month.slice(2)}</span>
                  </div>
                ))}
              </div>
            ) : <Empty description={tr("还没有数据", "No data yet")} />}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card className="panel" variant="borderless" title={tr("落地评级分布", "Landing rating mix")}>
            {ratingTotal ? (
              <Space direction="vertical" style={{ width: "100%" }} size={10}>
                {Object.entries(stats?.landing_ratings ?? {}).map(([k, v]) => {
                  const meta = ratingLabels[k] || ratingLabels.UNKNOWN;
                  const color = k === "GREAT" ? "#22c55e" : k === "GOOD" ? "#06b6d4" : k === "HARD" ? "#f59e0b" : "#ef4444";
                  return (
                    <div key={k}>
                      <Space style={{ width: "100%", justifyContent: "space-between" }}>
                        <Text>{tr(meta.zh, meta.en)}</Text>
                        <Text className="muted">{v} · {pct(v, ratingTotal)}%</Text>
                      </Space>
                      <Progress percent={pct(v, ratingTotal)} showInfo={false} strokeColor={color} size="small" />
                    </div>
                  );
                })}
              </Space>
            ) : <Empty description={tr("还没有落地数据", "No landing data")} />}
          </Card>
        </Col>
      </Row>

      <Row gutter={[12, 12]}>
        <Col xs={24} lg={12}>
          <Card className="panel" variant="borderless" title={tr("机型分布", "Aircraft mix")} size="small" styles={{ body: { padding: 0 } }}>
            <Table
              size="small"
              rowKey="icao"
              pagination={false}
              dataSource={stats?.top_aircraft ?? []}
              columns={[
                { title: tr("机型", "Type"), dataIndex: "icao" },
                { title: tr("班次", "Flights"), dataIndex: "flights" },
                { title: "", key: "bar", render: (_, r) => <Progress percent={pct(r.flights, stats?.flights ?? 1)} showInfo={false} size="small" /> },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card className="panel" variant="borderless" title={tr("机场收集", "Airport collection")} size="small">
            <Space wrap>
              {(stats?.distinct_airports ?? []).slice(0, 120).map((a) => <Tag key={a}>{a}</Tag>)}
              {(stats?.distinct_airports?.length ?? 0) > 120 ? <Tag>{tr("更多", "more")}…</Tag> : null}
            </Space>
            {!stats?.distinct_airports?.length ? <Text className="muted">{tr("还没有机场记录", "No airports yet")}</Text> : null}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
