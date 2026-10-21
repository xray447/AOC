import { Alert, Button, Card, Descriptions, Drawer, Form, Input, InputNumber, Modal, Select, Table, Tabs, Tag, message } from "antd";
import { useEffect, useState } from "react";
import { ApiError, api, money, timeText } from "../api";
import type { Flight, LockItem, Settlement } from "../types";

interface FlightPage {
  items: Flight[];
  total: number;
}

interface FlightDetail {
  flight: Flight;
  loadsheet: Record<string, unknown> | null;
  settlement: Settlement | null;
  track: { chunks: number; points: number; sampled: Array<Record<string, unknown>> };
}

export function OpsPage() {
  const [flights, setFlights] = useState<FlightPage>({ items: [], total: 0 });
  const [review, setReview] = useState<Settlement[]>([]);
  const [locks, setLocks] = useState<LockItem[]>([]);
  const [status, setStatus] = useState<string | undefined>();
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<FlightDetail | null>(null);
  const [reviewTarget, setReviewTarget] = useState<Settlement | null>(null);
  const [releaseTarget, setReleaseTarget] = useState<LockItem | null>(null);
  const [reason, setReason] = useState("");
  const [reviewForm] = Form.useForm();

  const load = async () => {
    try {
      const query = new URLSearchParams({ page_size: "100" });
      if (status) query.set("status", status);
      const [flightPage, reviewRows, lockRows] = await Promise.all([
        api<FlightPage>(`/api/v1/admin/ops/flights?${query.toString()}`),
        api<Settlement[]>("/api/v1/admin/ops/review"),
        api<LockItem[]>("/api/v1/admin/ops/locks"),
      ]);
      setFlights(flightPage);
      setReview(reviewRows);
      setLocks(lockRows);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败");
    }
  };

  useEffect(() => { void load(); }, [status]);

  if (error) return <Alert type="error" showIcon message={error} />;

  const openDetail = async (flight: Flight) => {
    try {
      setDetail(await api<FlightDetail>(`/api/v1/admin/ops/flights/${flight.id}`));
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "加载详情失败");
    }
  };

  const submitReview = async (values: { action: string; factor?: number; reason: string }) => {
    if (!reviewTarget) return;
    try {
      await api(`/api/v1/admin/ops/review/${reviewTarget.id}`, {
        method: "POST", body: JSON.stringify(values),
      });
      message.success("复核完成，已写账本与审计");
      setReviewTarget(null);
      reviewForm.resetFields();
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "复核失败");
    }
  };

  const release = async () => {
    if (!releaseTarget) return;
    if (!reason.trim()) {
      message.warning("请填写原因");
      return;
    }
    try {
      await api(`/api/v1/admin/ops/locks/${releaseTarget.id}/release`, {
        method: "POST", body: JSON.stringify({ reason }),
      });
      setReleaseTarget(null);
      setReason("");
      message.success("锁已释放");
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "释放失败");
    }
  };

  return (
    <Card title="运行监控" extra={<Button onClick={load}>刷新</Button>}>
      <Tabs
        items={[
          {
            key: "flights", label: `航班（${flights.total}）`,
            children: (
              <>
                <Select allowClear placeholder="状态筛选" style={{ width: 160, marginBottom: 10 }} value={status}
                  onChange={setStatus}
                  options={["SCHEDULED", "HELD", "IN_FLIGHT", "COMPLETED", "CANCELLED", "ABANDONED"].map((v) => ({ value: v, label: v }))} />
                <Table<Flight> rowKey="id" size="small" dataSource={flights.items}
                  pagination={{ pageSize: 20 }}
                  columns={[
                    { title: "航班", dataIndex: "flight_number" },
                    { title: "航段", render: (_, row) => `${row.dep_icao} → ${row.arr_icao}` },
                    { title: "计划起飞", dataIndex: "scheduled_dep_utc", render: timeText },
                    { title: "飞行员", render: (_, row) => row.pilot?.display_name || "—" },
                    { title: "飞机", render: (_, row) => row.aircraft?.registration || "—" },
                    { title: "状态", dataIndex: "status", render: (v: string) => <Tag>{v}</Tag> },
                    { title: "结算", dataIndex: "settlement_status", render: (v: string | null) => v ? <Tag color={v === "HELD" ? "orange" : "green"}>{v}</Tag> : "—" },
                    { title: "", width: 80, render: (_, row) => <Button size="small" onClick={() => openDetail(row)}>详情</Button> },
                  ]} />
              </>
            ),
          },
          {
            key: "review", label: `待复核（${review.length}）`,
            children: (
              <Table<Settlement> rowKey="id" size="small" dataSource={review} pagination={false}
                columns={[
                  { title: "航班", render: (_, row) => row.flight?.flight_number || row.flight_id.slice(0, 8) },
                  { title: "飞行员", render: (_, row) => row.pilot?.display_name || "—" },
                  { title: "异常", render: (_, row) => row.anomalies.map((a) => a.detail || a.kind).join("；") || "—" },
                  { title: "收入", dataIndex: "revenue_gross", render: (v: number) => money(v) },
                  { title: "成本", dataIndex: "cost_total", render: (v: number) => money(v) },
                  { title: "预付款", dataIndex: "advance_amount", render: (v: number) => money(v) },
                  { title: "时间", dataIndex: "created_at", render: timeText },
                  { title: "", width: 90, render: (_, row) => <Button size="small" type="primary" onClick={() => { setReviewTarget(row); reviewForm.setFieldsValue({ action: "ACCEPT", factor: 1 }); }}>复核</Button> },
                ]} />
            ),
          },
          {
            key: "locks", label: `飞机锁（${locks.length}）`,
            children: (
              <Table<LockItem> rowKey="id" size="small" dataSource={locks} pagination={false}
                columns={[
                  { title: "飞机", render: (_, row) => row.aircraft?.registration || row.aircraft_id.slice(0, 8) },
                  { title: "位置", render: (_, row) => row.aircraft?.current_icao || "—" },
                  { title: "飞行员", render: (_, row) => row.user?.display_name || row.user_id.slice(0, 8) },
                  { title: "类型", dataIndex: "kind" },
                  { title: "到期", dataIndex: "expires_at", render: timeText },
                  { title: "", width: 110, render: (_, row) => <Button size="small" danger onClick={() => setReleaseTarget(row)}>强制释放</Button> },
                ]} />
            ),
          },
        ]} />

      <Drawer title={detail ? `${detail.flight.flight_number} 详情` : "航班详情"} width={720}
        open={!!detail} onClose={() => setDetail(null)}>
        {detail ? (
          <>
            <Descriptions size="small" column={2} bordered style={{ marginBottom: 14 }}>
              <Descriptions.Item label="航段">{detail.flight.dep_icao} → {detail.flight.arr_icao}</Descriptions.Item>
              <Descriptions.Item label="状态">{detail.flight.status}</Descriptions.Item>
              <Descriptions.Item label="计划起飞">{timeText(detail.flight.scheduled_dep_utc)}</Descriptions.Item>
              <Descriptions.Item label="计划到达">{timeText(detail.flight.scheduled_arr_utc)}</Descriptions.Item>
              <Descriptions.Item label="距离">{Math.round(detail.flight.distance_nm)} NM</Descriptions.Item>
              <Descriptions.Item label="轨迹点">{detail.track.points}（分块 {detail.track.chunks}）</Descriptions.Item>
            </Descriptions>
            {detail.settlement ? (
              <Card size="small" title="结算" style={{ marginBottom: 12 }}>
                <Descriptions size="small" column={2}>
                  <Descriptions.Item label="状态">{detail.settlement.status}</Descriptions.Item>
                  <Descriptions.Item label="动作">{detail.settlement.action}</Descriptions.Item>
                  <Descriptions.Item label="因子">{detail.settlement.factor}</Descriptions.Item>
                  <Descriptions.Item label="利润">{money(detail.settlement.profit)}</Descriptions.Item>
                </Descriptions>
                <div className="admin-json">{JSON.stringify(detail.settlement.anomalies, null, 2)}</div>
              </Card>
            ) : null}
            {detail.loadsheet ? (
              <Card size="small" title="配载">
                <div className="admin-json">{JSON.stringify(detail.loadsheet, null, 2)}</div>
              </Card>
            ) : null}
          </>
        ) : null}
      </Drawer>

      <Modal title="异常结算复核" open={!!reviewTarget} onCancel={() => setReviewTarget(null)}
        onOk={() => reviewForm.submit()} okText="提交复核">
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="必须填写原因；ACCEPT=1，REJECT=0，WEIGHTED 需 0–1 因子。处理完写账本与审计。" />
        <Form form={reviewForm} layout="vertical" onFinish={submitReview}>
          <Form.Item name="action" label="动作" rules={[{ required: true }]}>
            <Select options={["ACCEPT", "WEIGHTED", "REJECT"].map((v) => ({ value: v, label: v }))} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, next) => prev.action !== next.action}>
            {({ getFieldValue }) => getFieldValue("action") === "WEIGHTED" ? (
              <Form.Item name="factor" label="折算因子" rules={[{ required: true }]}>
                <InputNumber style={{ width: "100%" }} min={0} max={1} step={0.01} />
              </Form.Item>
            ) : null}
          </Form.Item>
          <Form.Item name="reason" label="原因" rules={[{ required: true }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="强制释放飞机锁" open={!!releaseTarget} onCancel={() => setReleaseTarget(null)}
        onOk={release} okText="确认释放" okButtonProps={{ danger: true }}>
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="关联的 HELD/IN_FLIGHT 航班会标记 ABANDONED，操作写审计。" />
        <Input.TextArea rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder="原因（必填）" />
      </Modal>
    </Card>
  );
}
