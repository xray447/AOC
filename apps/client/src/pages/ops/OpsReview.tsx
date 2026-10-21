import { CheckOutlined, CloseOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  Alert, Button, Card, Empty, Input, Modal, Space, Table, Tag, Typography, message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useI18n } from "../../i18n";
import { anomalyLabel, fmtUtc, money, settlementTitle } from "../../ops";
import type { OpsSettlement } from "../../types";

const { Text } = Typography;

export function OpsReview() {
  const { tr } = useI18n();
  const [rows, setRows] = useState<OpsSettlement[]>([]);
  const [target, setTarget] = useState<{ row: OpsSettlement; action: string } | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const res = await api<{ items: OpsSettlement[] }>("/local/ops/review");
    setRows(res.items);
  }, []);

  useEffect(() => { void load().catch((e: Error) => message.error(e.message)); }, [load]);

  const resolve = async () => {
    if (!target) return;
    setBusy(true);
    try {
      await api(`/local/ops/review/${target.row.id}`, {
        method: "POST",
        body: JSON.stringify({ action: target.action, note }),
      });
      setTarget(null);
      setNote("");
      await load();
      message.success(tr("复核完成，已写账本", "Reviewed and posted to ledger"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("复核队列", "Review queue")}</h2>
          <p>{tr("HELD 的航班在复核前不写账本；确认后可正常结算或拒绝（成本按 reject_cost_mode）。",
            "HELD flights write no ledger until reviewed; accept to settle normally, or reject with costs per reject_cost_mode.")}</p>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>{tr("刷新", "Refresh")}</Button>
      </div>

      {!rows.length ? (
        <Card className="panel" variant="borderless">
          <Empty description={tr("没有待复核的结算", "Nothing to review")} />
        </Card>
      ) : (
        <Card className="panel" variant="borderless" styles={{ body: { padding: 0 } }}>
          <Table
            rowKey="id"
            size="small"
            dataSource={rows}
            pagination={false}
            columns={[
              {
                title: tr("航班", "Flight"), key: "t",
                render: (_: unknown, r: OpsSettlement) => (
                  <Link to={`/ops/settlements?focus=${r.id}`}>{settlementTitle(r)}</Link>
                ),
              },
              { title: tr("结算时间", "Computed"), dataIndex: "computed_at", width: 130, render: (v: string) => <span className="mono">{fmtUtc(v)}</span> },
              { title: tr("毛收入", "Gross"), dataIndex: "revenue_gross", width: 110, render: (v: number) => money(v) },
              {
                title: tr("净利润（预估）", "Profit"), dataIndex: "profit", width: 140,
                render: (v: number) => <Text type={v >= 0 ? "success" : "danger"}>{money(v)}</Text>,
              },
              { title: tr("预付款", "Advance"), dataIndex: "advance_amount", width: 110, render: (v: number) => money(v) },
              {
                title: tr("异常", "Anomalies"), key: "anomalies",
                render: (_: unknown, r: OpsSettlement) => (
                  <Space size={4} wrap>
                    {(r.policy_breakdown?.breakdown || []).map((item) => (
                      <Tag key={`${item.kind}-${item.detail}`} color="orange">
                        {anomalyLabel[item.kind] ? tr(anomalyLabel[item.kind].zh, anomalyLabel[item.kind].en) : item.kind}
                        {item.penalty ? ` −${(item.penalty * 100).toFixed(0)}%` : ""}
                      </Tag>
                    ))}
                  </Space>
                ),
              },
              {
                title: "", key: "act", width: 190,
                render: (_: unknown, r: OpsSettlement) => (
                  <Space wrap>
                    <Button size="small" type="primary" icon={<CheckOutlined />}
                      onClick={() => { setTarget({ row: r, action: "ACCEPT" }); setNote(""); }}>
                      {tr("接受", "Accept")}
                    </Button>
                    <Button size="small"
                      onClick={() => { setTarget({ row: r, action: "WEIGHTED" }); setNote(""); }}>
                      {tr("按系数", "Weighted")}
                    </Button>
                    <Button size="small" danger icon={<CloseOutlined />}
                      onClick={() => { setTarget({ row: r, action: "REJECT" }); setNote(""); }}>
                      {tr("拒绝", "Reject")}
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      )}

      <Alert
        style={{ marginTop: 16 }}
        type="info"
        showIcon
        message={tr("单人运营里复核人就是本人", "In single-player mode you are the reviewer")}
        description={tr("M3 联机后改由管理员在网页端处理；策略与折算口径一致。",
          "In M3 this moves to the web admin; the policy and formulas stay the same.")}
      />

      <Modal
        open={Boolean(target)}
        title={target?.action === "ACCEPT"
          ? tr("接受并结算", "Accept & settle")
          : target?.action === "WEIGHTED"
            ? tr("按系数结算", "Settle weighted")
            : tr("拒绝并结算", "Reject & settle")}
        onCancel={() => setTarget(null)}
        onOk={() => void resolve()}
        confirmLoading={busy}
        okText={tr("确认", "Confirm")}
      >
        <p>
          {target ? settlementTitle(target.row) : ""} · {tr("净利润", "Profit")}{" "}
          {target ? money(target.row.profit) : ""}
        </p>
        <Input.TextArea rows={3} value={note} onChange={(e) => setNote(e.target.value)}
          placeholder={tr("复核备注（可选）", "Review note (optional)")} />
      </Modal>
    </div>
  );
}
