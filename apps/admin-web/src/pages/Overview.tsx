import { Alert, Card, Col, Row, Statistic, Table, Tag } from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, money, timeText } from "../api";
import type { Flight, OverviewData, Settlement } from "../types";

export function OverviewPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const result = await api<OverviewData>("/api/v1/admin/overview");
        if (alive) {
          setData(result);
          setError("");
        }
      } catch (err) {
        if (alive) setError(err instanceof ApiError ? err.message : "加载失败");
      }
    };
    void load();
    const timer = window.setInterval(load, 10000);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  if (error) return <Alert type="error" showIcon message={error} />;
  if (!data) return <Card loading />;

  const currency = data.company.currency;
  const cards = data.cards;
  return (
    <div>
      <Row gutter={[14, 14]}>
        <Col xs={12} md={6}><Card><Statistic title="公司余额" value={cards.balance} precision={2} prefix={currency} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="今日收入" value={cards.today_revenue} precision={2} prefix={currency} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="今日成本" value={cards.today_cost} precision={2} prefix={currency} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="今日利润" value={cards.today_profit} precision={2} prefix={currency}
          valueStyle={{ color: cards.today_profit >= 0 ? "#13803f" : "#c0392b" }} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="在飞航班" value={cards.in_flight} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="在线飞行员" value={cards.online_pilots} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="待复核" value={cards.review_pending}
          valueStyle={{ color: cards.review_pending ? "#c77700" : undefined }} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="锁定飞机" value={cards.active_locks} /></Card></Col>
      </Row>

      <Row gutter={[14, 14]} style={{ marginTop: 14 }}>
        <Col xs={24} xl={14}>
          <Card title="最近航班" extra={<Link to="/ops">运行监控</Link>}>
            <Table<Flight> size="small" rowKey="id" pagination={false}
              dataSource={data.recent_flights}
              columns={[
                { title: "航班", dataIndex: "flight_number" },
                { title: "航段", render: (_, row) => `${row.dep_icao} → ${row.arr_icao}` },
                { title: "计划起飞", dataIndex: "scheduled_dep_utc", render: timeText },
                { title: "状态", dataIndex: "status", render: (v: string) => <Tag>{v}</Tag> },
              ]} />
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card title="待复核" extra={<Link to="/ops">去处理</Link>}>
            {data.review_queue.length === 0 ? <div className="admin-hint">没有待复核结算。</div> : (
              <Table<Settlement> size="small" rowKey="id" pagination={false}
                dataSource={data.review_queue}
                columns={[
                  { title: "航班", render: (_, row) => row.flight?.flight_number || row.flight_id.slice(0, 8) },
                  { title: "预估利润", dataIndex: "profit", render: (v: number) => money(v, currency) },
                  { title: "异常", render: (_, row) => row.anomalies.map((a) => a.kind).join(", ") || "—" },
                ]} />
            )}
          </Card>
        </Col>
        <Col xs={24}>
          <Card title="最近审计" extra={<Link to="/audit">全部</Link>}>
            <Table size="small" rowKey="id" pagination={false} dataSource={data.recent_audit}
              columns={[
                { title: "时间", dataIndex: "created_at", render: timeText, width: 180 },
                { title: "操作人", dataIndex: "actor_name", render: (v: string | null) => v || "系统" },
                { title: "动作", dataIndex: "action", render: (v: string) => <Tag color="blue">{v}</Tag> },
                { title: "对象", render: (_, row) => `${row.entity || ""} ${row.entity_id || ""}` },
                { title: "结果", dataIndex: "result" },
                { title: "原因", dataIndex: "reason", render: (v: string | null) => v || "—" },
              ]} />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
