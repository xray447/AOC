import { ReloadOutlined } from "@ant-design/icons";
import { Button, Card, Drawer, Empty, Space, Table, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { LoadError } from "../../components/LoadError";
import { SettlementSummary } from "../../components/SettlementSummary";
import { useRefreshKey } from "../../context";
import { useI18n } from "../../i18n";
import { fmtBlock, fmtUtc, money, policyAction, settlementStatus, settlementTitle } from "../../ops";
import type { OpsSettlement } from "../../types";

const { Text } = Typography;

export function OpsSettlements({ embedded = false }: { embedded?: boolean }) {
  const { tr } = useI18n();
  const refreshKey = useRefreshKey();
  const [rows, setRows] = useState<OpsSettlement[]>([]);
  const [detail, setDetail] = useState<OpsSettlement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();
  const focus = params.get("focus");

  const load = useCallback(async () => {
    try {
      const res = await api<{ items: OpsSettlement[] }>("/local/ops/settlements?limit=200");
      setRows(res.items);
      setError(null);
      if (focus) {
        try {
          setDetail(await api<OpsSettlement>(`/local/ops/settlements/${focus}`));
        } catch {
          setDetail(null);
        }
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, [focus]);

  useEffect(() => { void load(); }, [load, refreshKey]);

  const open = async (row: OpsSettlement) => {
    setParams({ focus: row.id });
  };

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

      {error ? <LoadError message={error} onRetry={() => void load()} /> : null}

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
            {/* IA-05：状态/策略/金额/拆分/账本统一走 SettlementSummary，不再各页各写一套 */}
            <SettlementSummary settlement={detail} detailed />
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
