import { Alert, Card, Col, Descriptions, Empty, Row, Statistic, Table, Tag, Typography } from "antd";
import { useI18n } from "../i18n";
import { anomalyLabel, entryLabel, fmtUtc, money, policyAction, settlementStatus } from "../ops";
import type { OpsSettlement } from "../types";

const { Text } = Typography;

interface Props {
  settlement: OpsSettlement;
  /** 只显示四个数字（执行页的「结算结果」卡）。 */
  compact?: boolean;
  /** 明细：异常政策、收入/成本拆分、账本条目（财务抽屉、日志详情用）。 */
  detailed?: boolean;
  title?: string;
  extra?: React.ReactNode;
}

/**
 * IA-05：结算信息以前在 4 个地方各写了一遍（执行页 / 财务抽屉 / 复核 / 首页）。
 * 口径（金额取负、状态本地化、策略标签）统一收敛到这里，避免再次漂移。
 */
export function SettlementSummary({ settlement, compact = false, detailed = false, title, extra }: Props) {
  const { tr } = useI18n();
  const status = settlementStatus[settlement.status];
  const policy = policyAction[settlement.policy_action];
  const revenue = settlement.breakdown?.revenue || [];
  const costs = settlement.breakdown?.costs || [];
  const policyBreakdown = settlement.policy_breakdown;

  const tags = (
    <>
      <Tag color={policy?.color}>{policy ? tr(policy.zh, policy.en) : settlement.policy_action}</Tag>
      <Tag color={status?.color}>{status ? tr(status.zh, status.en) : settlement.status}</Tag>
    </>
  );

  if (compact) {
    return (
      <Card className="panel" variant="borderless" title={title || tr("结算结果", "Settlement")} extra={extra || tags}>
        <Row gutter={16}>
          <Col span={6}><Statistic title={tr("毛收入", "Gross revenue")} value={money(settlement.revenue_gross)} /></Col>
          <Col span={6}><Statistic title={tr("结算收入", "Settled revenue")} value={money(settlement.revenue_total)} /></Col>
          <Col span={6}><Statistic title={tr("总成本", "Costs")} value={money(settlement.cost_total)} /></Col>
          <Col span={6}>
            <Statistic title={tr("利润", "Profit")} value={money(settlement.profit)}
              valueStyle={{ color: settlement.profit >= 0 ? "#22c55e" : "#ef4444" }} />
          </Col>
        </Row>
      </Card>
    );
  }

  return (
    <div className="settlement-summary">
      <Descriptions size="small" column={2} bordered>
        <Descriptions.Item label={tr("状态", "Status")}>
          <Tag color={status?.color}>{status ? tr(status.zh, status.en) : settlement.status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label={tr("策略", "Policy")}>
          <Tag color={policy?.color}>
            {policy ? tr(policy.zh, policy.en) : settlement.policy_action} · ×{settlement.payout_factor.toFixed(2)}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label={tr("毛收入", "Gross revenue")}>{money(settlement.revenue_gross)}</Descriptions.Item>
        <Descriptions.Item label={tr("结算收入", "Settled revenue")}>{money(settlement.revenue_total)}</Descriptions.Item>
        <Descriptions.Item label={tr("成本", "Costs")}>{money(settlement.cost_total)}</Descriptions.Item>
        <Descriptions.Item label={tr("利润", "Profit")}>
          <Text type={settlement.profit >= 0 ? "success" : "danger"}>{money(settlement.profit)}</Text>
        </Descriptions.Item>
        <Descriptions.Item label={tr("预付款", "Advance")}>{money(settlement.advance_amount)}</Descriptions.Item>
        <Descriptions.Item label={tr("结算时间", "Computed")}>{fmtUtc(settlement.computed_at)}</Descriptions.Item>
      </Descriptions>

      {detailed && policyBreakdown?.breakdown?.length ? (
        <Card size="small" style={{ marginTop: 12 }} title={tr("异常与政策明细", "Anomalies & policy")}>
          <Table
            rowKey={(row) => `${row.kind}-${row.detail}`}
            size="small"
            pagination={false}
            dataSource={policyBreakdown.breakdown}
            columns={[
              {
                title: tr("异常", "Anomaly"), dataIndex: "kind",
                render: (v: string) => (anomalyLabel[v] ? tr(anomalyLabel[v].zh, anomalyLabel[v].en) : v),
              },
              {
                title: tr("动作", "Action"), dataIndex: "action", width: 110,
                render: (v: string) => (policyAction[v] ? tr(policyAction[v].zh, policyAction[v].en) : v),
              },
              { title: tr("扣减", "Penalty"), dataIndex: "penalty", width: 90, render: (v: number) => `${(v * 100).toFixed(0)}%` },
              { title: tr("说明", "Detail"), dataIndex: "detail" },
            ]}
          />
        </Card>
      ) : null}

      {detailed ? (
        <>
          <Row gutter={12} style={{ marginTop: 12 }}>
            <Col span={12}>
              <Card size="small" title={tr("收入", "Revenue")}>
                {revenue.map((item) => (
                  <div key={item.type} style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>{entryLabel[item.type] ? tr(entryLabel[item.type].zh, entryLabel[item.type].en) : item.type}</span>
                    <span className="mono">{money(item.amount)}</span>
                  </div>
                ))}
                {!revenue.length ? <Empty description={tr("无收入", "No revenue")} /> : null}
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small" title={tr("成本", "Costs")}>
                {costs.map((item) => (
                  <div key={item.type} style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>{entryLabel[item.type] ? tr(entryLabel[item.type].zh, entryLabel[item.type].en) : item.type}</span>
                    {/* UI-04：成本统一取负显示，不再出现 `--$1,234` */}
                    <span className="mono">{money(-Math.abs(Number(item.amount) || 0))}</span>
                  </div>
                ))}
                {!costs.length ? <Empty description={tr("无成本", "No costs")} /> : null}
              </Card>
            </Col>
          </Row>

          <Card size="small" style={{ marginTop: 12 }} title={tr("账本条目", "Ledger entries")}>
            {(settlement.ledger || []).length ? (
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={settlement.ledger}
                columns={[
                  {
                    title: tr("类型", "Type"), dataIndex: "entry_type",
                    render: (v: string) => (entryLabel[v] ? tr(entryLabel[v].zh, entryLabel[v].en) : v),
                  },
                  {
                    title: tr("金额", "Amount"), dataIndex: "amount", width: 120,
                    render: (v: number) => <Text type={v >= 0 ? "success" : "danger"}>{money(v)}</Text>,
                  },
                  {
                    title: tr("余额", "Balance"), dataIndex: "balance_after", width: 130,
                    render: (v: number) => <span className="mono">{money(v)}</span>,
                  },
                ]}
              />
            ) : (
              <Alert type="info" showIcon message={tr("HELD/VOID 不写账本", "HELD/VOID flights write no ledger")} />
            )}
          </Card>
        </>
      ) : null}
    </div>
  );
}
