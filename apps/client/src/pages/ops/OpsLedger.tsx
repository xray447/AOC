import { ReloadOutlined } from "@ant-design/icons";
import {
  Button, Card, Col, Empty, InputNumber, Row, Space, Table, Typography, message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { LoadError } from "../../components/LoadError";
import { useRefreshKey } from "../../context";
import { useI18n } from "../../i18n";
import { entryLabel, fmtUtc, money } from "../../ops";
import type { OpsLedger } from "../../types";

const { Text } = Typography;

export function OpsLedgerPage({ embedded = false }: { embedded?: boolean }) {
  const { tr } = useI18n();
  const refreshKey = useRefreshKey();
  const [data, setData] = useState<OpsLedger | null>(null);
  const [limit, setLimit] = useState(200);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api<OpsLedger>(`/local/ops/ledger?limit=${limit}`));
      setError(null);
    } catch (e) {
      // UI-09：此前只有一条会消失的 toast，页面永远停在骨架屏
      setError((e as Error).message);
    }
  }, [limit]);

  useEffect(() => { void load(); }, [load, refreshKey]);

  /** UI-19：合并页里也要能改条数/刷新（以前这两个控件只在非合并页渲染）。 */
  const toolbar = (
    <Space>
      <InputNumber min={50} max={1000} step={50} value={limit}
        onChange={(v) => setLimit(Number(v || 200))} />
      <Button icon={<ReloadOutlined />} onClick={() => void load()}>{tr("刷新", "Refresh")}</Button>
    </Space>
  );

  const totals = Object.entries(data?.totals || {}).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));

  return (
    <div className={embedded ? "ops-embedded" : "page"}>
      {embedded ? null : (
        <div className="page-head">
          <div>
            <h2>{tr("账本", "Ledger")}</h2>
            <p>{tr("只追加不修改；按类型汇总当期收入与成本。", "Append-only entries, summarised by type.")}</p>
          </div>
          {toolbar}
        </div>
      )}

      {embedded ? <div style={{ display: "flex", justifyContent: "flex-end" }}>{toolbar}</div> : null}

      {error ? <LoadError message={error} onRetry={() => void load()} /> : null}

      {!data ? (error ? null : <Card loading />) : (
        <>
          <Row gutter={16}>
            <Col xs={24} lg={8}>
              <Card className="panel" variant="borderless" title={tr("按类型汇总", "Totals by type")}>
                {totals.length ? totals.map(([type, amount]) => (
                  <div key={type} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0" }}>
                    <span>{entryLabel[type] ? tr(entryLabel[type].zh, entryLabel[type].en) : type}</span>
                    <Text type={amount >= 0 ? "success" : "danger"} className="mono">{money(amount)}</Text>
                  </div>
                )) : <Empty description={tr("暂无条目", "No entries")} />}
              </Card>
            </Col>
            <Col xs={24} lg={16}>
              <Card className="panel" variant="borderless" styles={{ body: { padding: 0 } }}>
                <Table
                  rowKey="id"
                  size="small"
                  dataSource={data.items}
                  pagination={{ pageSize: 12, showSizeChanger: false }}
                  columns={[
                    { title: tr("时间", "Time"), dataIndex: "created_at", width: 130, render: (v: string) => <span className="mono">{fmtUtc(v)}</span> },
                    {
                      title: tr("类型", "Type"), dataIndex: "entry_type",
                      render: (v: string) => (entryLabel[v] ? tr(entryLabel[v].zh, entryLabel[v].en) : v),
                    },
                    {
                      title: tr("金额", "Amount"), dataIndex: "amount", width: 120,
                      render: (v: number) => <Text type={v >= 0 ? "success" : "danger"} className="mono">{money(v)}</Text>,
                    },

                    {
                      title: tr("来源", "Source"), dataIndex: "settlement_id", width: 110,
                      render: (v: string | null) => (v ? <Link to={`/ops/settlements?focus=${v}`}>{tr("结算", "Settlement")}</Link> : "—"),
                    },
                  ]}
                />
              </Card>
            </Col>
          </Row>
        </>
      )}
    </div>
  );
}
