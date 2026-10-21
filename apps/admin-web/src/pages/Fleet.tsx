import { Alert, Button, Card, Form, Input, InputNumber, Modal, Select, Switch, Table, Tabs, Tag, message } from "antd";
import { useEffect, useState } from "react";
import { ApiError, api, money } from "../api";
import { useAuth } from "../App";
import type { Aircraft, AircraftType } from "../types";

export function FleetPage() {
  const { auth } = useAuth();
  const [types, setTypes] = useState<AircraftType[]>([]);
  const [aircraft, setAircraft] = useState<Aircraft[]>([]);
  const [error, setError] = useState("");
  const [typeOpen, setTypeOpen] = useState(false);
  const [aircraftOpen, setAircraftOpen] = useState(false);
  const [releaseTarget, setReleaseTarget] = useState<Aircraft | null>(null);
  const [releaseReason, setReleaseReason] = useState("");
  const [typeForm] = Form.useForm();
  const [aircraftForm] = Form.useForm();
  const readonly = auth?.user.role !== "ADMIN";

  const load = async () => {
    try {
      const [typeRows, aircraftRows] = await Promise.all([
        api<AircraftType[]>("/api/v1/admin/fleet/types"),
        api<Aircraft[]>("/api/v1/admin/fleet/aircraft"),
      ]);
      setTypes(typeRows);
      setAircraft(aircraftRows);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败");
    }
  };

  useEffect(() => { void load(); }, []);

  if (error) return <Alert type="error" showIcon message={error} />;

  const createType = async (values: Record<string, unknown>) => {
    try {
      await api("/api/v1/admin/fleet/types", { method: "POST", body: JSON.stringify(values) });
      setTypeOpen(false);
      typeForm.resetFields();
      message.success("机型已创建");
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "创建失败");
    }
  };

  const createAircraft = async (values: Record<string, unknown>) => {
    try {
      await api("/api/v1/admin/fleet/aircraft", { method: "POST", body: JSON.stringify(values) });
      setAircraftOpen(false);
      aircraftForm.resetFields();
      message.success("飞机已加入机队");
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "创建失败");
    }
  };

  const release = async () => {
    if (!releaseTarget) return;
    if (!releaseReason.trim()) {
      message.warning("请填写原因");
      return;
    }
    try {
      await api(`/api/v1/admin/fleet/aircraft/${releaseTarget.id}/release-lock`, {
        method: "POST", body: JSON.stringify({ reason: releaseReason }),
      });
      setReleaseTarget(null);
      setReleaseReason("");
      message.success("锁已释放，相关航班标记 ABANDONED");
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "释放失败");
    }
  };

  return (
    <Card title="机队"
      extra={!readonly ? <Button type="primary" onClick={() => (types.length ? setAircraftOpen(true) : setTypeOpen(true))}>
        添加飞机
      </Button> : null}>
      <Tabs
        items={[
          {
            key: "aircraft", label: `单机档案（${aircraft.length}）`,
            children: (
              <Table<Aircraft> rowKey="id" size="small" dataSource={aircraft} pagination={{ pageSize: 12 }}
                columns={[
                  { title: "注册号", dataIndex: "registration", render: (v: string) => <strong>{v}</strong> },
                  { title: "机型", render: (_, row) => `${row.type?.icao || "—"} / ${row.type?.name || ""}` },
                  { title: "位置", dataIndex: "current_icao" },
                  { title: "状态", dataIndex: "status", render: (v: string) => <Tag>{v}</Tag> },
                  { title: "小时", dataIndex: "total_hours", render: (v: number) => v.toFixed(0) },
                  { title: "循环", dataIndex: "total_cycles" },
                  { title: "租赁/小时", dataIndex: "lease_per_hour", render: (v: number | null) => money(v) },
                  { title: "锁", render: (_, row) => row.lock ? <Tag color="orange">已锁定</Tag> : <Tag>空闲</Tag> },
                  {
                    title: "操作", width: 120, render: (_, row) => row.lock ? (
                      <Button size="small" danger disabled={readonly}
                        onClick={() => setReleaseTarget(row)}>释放锁</Button>
                    ) : null,
                  },
                ]} />
            ),
          },
          {
            key: "types", label: `机型模板（${types.length}）`,
            children: (
              <>
                {!readonly ? <Button size="small" style={{ marginBottom: 10 }} onClick={() => setTypeOpen(true)}>新建机型</Button> : null}
                <Table<AircraftType> rowKey="id" size="small" dataSource={types} pagination={{ pageSize: 12 }}
                  columns={[
                    { title: "ICAO", dataIndex: "icao" },
                    { title: "变体", dataIndex: "variant" },
                    { title: "名称", dataIndex: "name" },
                    { title: "角色", dataIndex: "role", render: (v: string) => <Tag color={v === "BIZJET" ? "purple" : "blue"}>{v}</Tag> },
                    { title: "座位", dataIndex: "pax_capacity" },
                    { title: "MTOW", dataIndex: "mtow_kg", render: (v: number) => `${Math.round(v / 1000)} t` },
                    { title: "包机/小时", dataIndex: "charter_rate_per_hour", render: (v: number) => v ? money(v) : "—" },
                    { title: "定期", dataIndex: "allow_scheduled", render: (v: boolean) => (v ? "是" : "否") },
                  ]} />
              </>
            ),
          },
        ]} />

      <Modal title="新建机型模板" open={typeOpen} onCancel={() => setTypeOpen(false)}
        onOk={() => typeForm.submit()} width={720}>
        <Form form={typeForm} layout="vertical" onFinish={createType} initialValues={{ variant: "STANDARD", role: "AIRLINER" }}>
          <div className="admin-param-grid">
            <Form.Item name="icao" label="ICAO" rules={[{ required: true }]}><Input maxLength={6} /></Form.Item>
            <Form.Item name="variant" label="变体"><Input /></Form.Item>
            <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="role" label="角色">
              <Select options={["AIRLINER", "BIZJET", "VIP", "CARGO"].map((v) => ({ value: v, label: v }))} />
            </Form.Item>
            <Form.Item name="pax_capacity" label="座位"><InputNumber style={{ width: "100%" }} min={0} /></Form.Item>
            <Form.Item name="mtow_kg" label="MTOW（kg）"><InputNumber style={{ width: "100%" }} min={0} /></Form.Item>
            <Form.Item name="fuel_burn_kg_h" label="油耗（kg/h）"><InputNumber style={{ width: "100%" }} min={0} /></Form.Item>
            <Form.Item name="lease_per_hour" label="租赁/小时"><InputNumber style={{ width: "100%" }} min={0} /></Form.Item>
            <Form.Item name="charter_rate_per_hour" label="包机/小时"><InputNumber style={{ width: "100%" }} min={0} /></Form.Item>
            <Form.Item name="allow_scheduled" label="允许定期" valuePropName="checked" initialValue><Switch /></Form.Item>
          </div>
        </Form>
      </Modal>

      <Modal title="添加飞机" open={aircraftOpen} onCancel={() => setAircraftOpen(false)}
        onOk={() => aircraftForm.submit()} width={640}>
        <Form form={aircraftForm} layout="vertical" onFinish={createAircraft}
          initialValues={{ base_icao: auth?.company.base_icao, acquisition: "LEASE", status: "ACTIVE" }}>
          <div className="admin-param-grid">
            <Form.Item name="registration" label="注册号" rules={[{ required: true }]}><Input placeholder="B-1004" /></Form.Item>
            <Form.Item name="type_id" label="机型" rules={[{ required: true }]}>
              <Select showSearch optionFilterProp="label"
                options={types.map((item) => ({ value: item.id, label: `${item.icao} ${item.variant} · ${item.name}` }))} />
            </Form.Item>
            <Form.Item name="base_icao" label="基地"><Input maxLength={4} /></Form.Item>
            <Form.Item name="current_icao" label="当前位置"><Input maxLength={4} /></Form.Item>
            <Form.Item name="acquisition" label="引进方式">
              <Select options={["LEASE", "OWN"].map((v) => ({ value: v, label: v }))} />
            </Form.Item>
            <Form.Item name="lease_per_hour" label="租赁/小时（覆盖）"><InputNumber style={{ width: "100%" }} min={0} /></Form.Item>
            <Form.Item name="fuel_kg" label="初始油量（kg）"><InputNumber style={{ width: "100%" }} min={0} /></Form.Item>
            <Form.Item name="livery" label="涂装"><Input /></Form.Item>
          </div>
        </Form>
      </Modal>

      <Modal title={`释放 ${releaseTarget?.registration || ""} 的锁`} open={!!releaseTarget}
        onCancel={() => setReleaseTarget(null)} onOk={release} okText="确认释放" okButtonProps={{ danger: true }}>
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="释放后关联的 HELD/IN_FLIGHT 航班标记 ABANDONED，操作写审计。" />
        <Input.TextArea rows={3} value={releaseReason} onChange={(e) => setReleaseReason(e.target.value)}
          placeholder="原因（必填）" />
      </Modal>
    </Card>
  );
}
