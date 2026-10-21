import { ReloadOutlined } from "@ant-design/icons";
import {
  Alert, Button, Card, Col, Descriptions, Drawer, Empty, Row, Space, Table, Tag, Typography, message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useI18n } from "../../i18n";
import {
  anomalyLabel, entryLabel, fmtBlock, fmtUtc, money, policyAction, settlementStatus, settlementTitle,
} from "../../ops";
import type { OpsSettlement } from "../../types";

const { Text } = Typography;

export function OpsSettlements({ embedded = false }: { embedded?: boolean }) {
  const { tr } = useI18n();
  const [rows, setRows] = useState<OpsSettlement[]>([]);
  const [detail, setDetail] = useState<OpsSettlement | null>(null);
  const [params, setParams] = useSearchParams();
  const focus = params.get("focus");

  const load = useCallback(async () => {
    const res = await api<{ items: OpsSettlement[] }>("/local/ops/settlements?limit=200");
    setRows(res.items);
    if (focus) {
      try {
        setDetail(await api<OpsSettlement>(`/local/ops/settlements/${focus}`));
      } catch {
        setDetail(null);
      }
    }
  }, [focus]);

  useEffect(() => { void load().catch((e: Error) => message.error(e.message)); }, [load]);

  const open = async (row: OpsSettlement) => {
    setParams({ focus: row.id });
  };

  const revenue = detail?.breakdown?.revenue || [];
  const costs = detail?.breakdown?.costs || [];
  const policy = detail?.policy_breakdown;

  return (
    <div className={embedded ? "ops-embedded" : "page"}>
      {embedded ? null : (
        <div className="page-head">
          <div>
            <h2>{tr("结算", "Settlements")}</h2>
            <p>{tr("收入/成本按实际数据重算，异常按策略折算；HELD 需在复核队列确认。", "Revenue and costs are recomputed from actual data and adjusted by policy; HELD flights need review.")}</p>
          </div>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void load()}>{tr("刷新", "Refresh")}</Button>
            <Link to="/ops/review"><Button>{tr("复核队列", "Review queue")}</Button></Link>
          </Space>
        </div>
      )}

      <Card className="panel" variant="borderless" styles={{ body: { padding: 0 } }}>
        {rows.length ? (
          <Table
            rowKey="id"
            size="small"
            dataSource={rows}
            pagination={{ pageSize: 15, showSizeChanger: false }}
            onRow={(row) => ({ onClick: () => void open(row), style: { cursor: "pointer" } })}
            columns={[
              { title: tr("航班", "Flight"), key: "t", render: (_: unknown, r: OpsSettlement) => settlementTitle(r) },
              { title: tr("时间", "Time"), dataIndex: "computed_at", width: 130, render: (v: string) => <span className="mono">{fmtUtc(v)}</span> },
              { title: tr("航时", "Block"), dataIndex: "block_minutes", width: 80, render: (v: number) => fmtBlock(v) },
              { title: tr("毛收入", "Gross"), dataIndex: "revenue_gross", width: 110, render: (v: number) => money(v) },
              { title: tr("结算收入", "Revenue"), dataIndex: "revenue_total", width: 110, render: (v: number) => money(v) },
              { title: tr("成本", "Cost"), dataIndex: "cost_total", width: 110, render: (v: number) => money(v) },
              {
                title: tr("利润", "Profit"), dataIndex: "profit", width: 110,
                render: (v: number) => <Text type={v >= 0 ? "success" : "danger"}>{money(v)}</Text>,
              },
              {
                title: tr("系数", "Factor"), dataIndex: "payout_factor", width: 80,
                render: (v: number) => v.toFixed(2),
              },
              {
                title: tr("策略", "Policy"), dataIndex: "policy_action", width: 100,
                render: (v: string) => <Tag color={policyAction[v]?.color}>{policyAction[v] ? tr(policyAction[v].zh, policyAction[v].en) : v}</Tag>,
              },
              {
                title: tr("状态", "Status"), dataIndex: "status", width: 90,
                render: (v: string) => <Tag color={settlementStatus[v]?.color}>{settlementStatus[v] ? tr(settlementStatus[v].zh, settlementStatus[v].en) : v}</Tag>,
              },
            ]}
          />
        ) : (
          <Empty style={{ padding: 32 }} description={tr("还没有结算", "No settlements yet")} />
        )}
      </Card>

      <Drawer
        open={Boolean(detail)}
        width={720}
        title={detail ? settlementTitle(detail) : ""}
        onClose={() => {
          setDetail(null);
          setParams({});
        }}
      >
        {detail ? (
          <>
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label={tr("状态", "Status")}>
                <Tag color={settlementStatus[detail.status]?.color}>{detail.status}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label={tr("策略", "Policy")}>
                <Tag color={policyAction[detail.policy_action]?.color}>{detail.policy_action} · ×{detail.payout_factor.toFixed(2)}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label={tr("毛收入", "Gross revenue")}>{money(detail.revenue_gross)}</Descriptions.Item>
              <Descriptions.Item label={tr("结算收入", "Settled revenue")}>{money(detail.revenue_total)}</Descriptions.Item>
              <Descriptions.Item label={tr("成本", "Costs")}>{money(detail.cost_total)}</Descriptions.Item>
              <Descriptions.Item label={tr("利润", "Profit")}>
                <Text type={detail.profit >= 0 ? "success" : "danger"}>{money(detail.profit)}</Text>
              </Descriptions.Item>
              <Descriptions.Item label={tr("预付款", "Advance")}>{money(detail.advance_amount)}</Descriptions.Item>
              <Descriptions.Item label={tr("结算时间", "Computed")}>{fmtUtc(detail.computed_at)}</Descriptions.Item>
            </Descriptions>

            {policy && policy.breakdown?.length ? (
              <Card size="small" style={{ marginTop: 12 }} title={tr("异常与政策明细", "Anomalies & policy")}>
                <Table
                  rowKey={(row) => `${row.kind}-${row.detail}`}
                  size="small"
                  pagination={false}
                  dataSource={policy.breakdown}
                  columns={[
                    {
                      title: tr("异常", "Anomaly"), dataIndex: "kind",
                      render: (v: string) => anomalyLabel[v] ? tr(anomalyLabel[v].zh, anomalyLabel[v].en) : v,
                    },
                    { title: tr("动作", "Action"), dataIndex: "action", width: 100, render: (v: string) => <Tag color={policyAction[v]?.color || "default"}>{v}</Tag> },
                    { title: tr("扣减", "Penalty"), dataIndex: "penalty", width: 90, render: (v: number) => `${(v * 100).toFixed(0)}%` },
                    { title: tr("说明", "Detail"), dataIndex: "detail" },
                  ]}
                />
              </Card>
            ) : null}

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
                      <span className="mono">-{money(item.amount).replace("$", "$")}</span>
                    </div>
                  ))}
                  {!costs.length ? <Empty description={tr("无成本", "No costs")} /> : null}
                </Card>
              </Col>
            </Row>

            <Card size="small" style={{ marginTop: 12 }} title={tr("账本条目", "Ledger entries")}>
              {(detail.ledger || []).length ? (
                <Table
                  rowKey="id"
                  size="small"
                  pagination={false}
                  dataSource={detail.ledger}
                  columns={[
                    {
                      title: tr("类型", "Type"), dataIndex: "entry_type",
                      render: (v: string) => entryLabel[v] ? tr(entryLabel[v].zh, entryLabel[v].en) : v,
                    },
                    {
                      title: tr("金额", "Amount"), dataIndex: "amount", width: 120,
                      render: (v: number) => <Text type={v >= 0 ? "success" : "danger"}>{money(v)}</Text>,
                    },
                    { title: tr("余额", "Balance"), dataIndex: "balance_after", width: 130, render: (v: number) => <span className="mono">{money(v)}</span> },
                  ]}
                />
              ) : (
                <Alert type="info" showIcon message={tr("HELD/VOID 不写账本", "HELD/VOID flights write no ledger")} />
              )}
            </Card>

            <Space style={{ marginTop: 12 }}>
              <Link to={`/logs/${detail.flight_record_id}`}><Button>{tr("回放轨迹", "Replay")}</Button></Link>
              {detail.status === "HELD" ? <Link to="/ops/review"><Button type="primary">{tr("去复核", "Review")}</Button></Link> : null}
            </Space>
          </>
        ) : null}
      </Drawer>
    </div>
  );
}
