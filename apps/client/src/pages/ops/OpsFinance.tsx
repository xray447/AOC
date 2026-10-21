import { ReloadOutlined } from "@ant-design/icons";
import { Button, Card, Col, Row, Space, Table, Tabs, Typography, message } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useI18n } from "../../i18n";
import { money } from "../../ops";
import type { OpsFinanceSummary } from "../../types";
import { OpsLedgerPage } from "./OpsLedger";
import { OpsSettlements } from "./OpsSettlements";

const { Text } = Typography;

type FinanceTab = "settlements" | "ledger";

const TAB_PATH: Record<FinanceTab, string> = {
  settlements: "/ops/settlements",
  ledger: "/ops/ledger",
};

const PERIOD_LABEL: Record<string, { zh: string; en: string }> = {
  WEEK: { zh: "本周", en: "This week" },
  MONTH: { zh: "本月", en: "This month" },
  YEAR: { zh: "今年", en: "This year" },
};

/** 结算与账本合并为一页；顶部是总计与周期统计（不算账户余额）。 */
export function OpsFinance() {
  const { tr } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const [refreshKey, setRefreshKey] = useState(0);
  const [summary, setSummary] = useState<OpsFinanceSummary | null>(null);

  const tab = useMemo<FinanceTab>(() => {
    const found = (Object.keys(TAB_PATH) as FinanceTab[])
      .find((key) => TAB_PATH[key] === location.pathname);
    return found ?? "settlements";
  }, [location.pathname]);

  const load = useCallback(async () => {
    setSummary(await api<OpsFinanceSummary>("/local/ops/finance/summary"));
  }, []);

  useEffect(() => {
    void load().catch((e: Error) => message.error(e.message));
  }, [load, refreshKey]);

  const totals = summary?.totals;
  const columns = [
    { title: tr("周期", "Period"), dataIndex: "label", width: 110 },
    { title: tr("航班", "Flights"), dataIndex: "flights", width: 70 },
    {
      title: tr("收入", "Revenue"), dataIndex: "revenue", width: 120,
      render: (v: number) => <span className="mono">{money(v)}</span>,
    },
    {
      title: tr("成本", "Cost"), dataIndex: "cost", width: 120,
      render: (v: number) => <span className="mono">{money(v)}</span>,
    },
    {
      title: tr("利润", "Profit"), dataIndex: "profit", width: 120,
      render: (v: number) => (
        <Text type={v >= 0 ? "success" : "danger"} className="mono">{money(v)}</Text>
      ),
    },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("财务", "Finance")}</h2>
          <p>{tr("按结算统计：总计与本周/本月/今年；结算与账本在同一页。",
            "Settlement-based totals plus this week/month/year; settlements and ledger in one place.")}</p>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => setRefreshKey((v) => v + 1)}>
            {tr("刷新", "Refresh")}
          </Button>
        </Space>
      </div>

      <div className="metric-grid">
        <StatCard title={tr("总计利润", "Total profit")} value={totals?.profit} accent />
        <StatCard title={tr("总收入", "Total revenue")} value={totals?.revenue} />
        <StatCard title={tr("总成本", "Total cost")} value={totals?.cost} />
        <StatCard
          title={tr("已结算航班", "Settled flights")}
          value={totals?.flights}
          raw
          suffix={summary?.held ? tr(`（${summary.held} 待复核）`, ` (${summary.held} held)`) : ""}
        />
      </div>

      <Row gutter={16}>
        <Col xs={24} lg={10}>
          <Card className="panel" variant="borderless" title={tr("周期统计", "By period")}
            styles={{ body: { padding: 0 } }}>
            <Table
              rowKey="key"
              size="small"
              pagination={false}
              dataSource={(summary?.periods || []).map((p) => ({
                ...p,
                label: PERIOD_LABEL[p.key] ? tr(PERIOD_LABEL[p.key].zh, PERIOD_LABEL[p.key].en) : p.key,
              }))}
              columns={columns}
            />
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card className="panel" variant="borderless" title={tr("近 6 个月", "Last 6 months")}
            styles={{ body: { padding: 0 } }}>
            <Table
              rowKey="month"
              size="small"
              pagination={false}
              dataSource={summary?.monthly || []}
              columns={[
                { ...columns[0], title: tr("月份", "Month"), dataIndex: "month", width: 100 },
                ...columns.slice(1),
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Tabs
        activeKey={tab}
        onChange={(key) => navigate(TAB_PATH[key as FinanceTab])}
        items={[
          {
            key: "settlements",
            label: tr("结算", "Settlements"),
            children: <div key={`settlements-${refreshKey}`}><OpsSettlements embedded /></div>,
          },
          {
            key: "ledger",
            label: tr("账本", "Ledger"),
            children: <div key={`ledger-${refreshKey}`}><OpsLedgerPage embedded /></div>,
          },
        ]}
      />
    </div>
  );
}

function StatCard({ title, value, suffix, accent, raw }: {
  title: string;
  value?: number;
  suffix?: string;
  accent?: boolean;
  raw?: boolean;
}) {
  const number = value ?? 0;
  const color = accent && value !== undefined ? (number >= 0 ? "#22c55e" : "#ef4444") : undefined;
  return (
    <Card size="small" variant="borderless" className="metric-card">
      <div className="muted">{title}</div>
      <div className="hero-title mono" style={{ fontSize: 24, color }}>
        {value === undefined ? "—" : raw ? number.toLocaleString() : money(number)}
        {suffix ? <span className="muted" style={{ fontSize: 13 }}>{suffix}</span> : null}
      </div>
    </Card>
  );
}
