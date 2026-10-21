import { PlusOutlined, ReloadOutlined, UnlockOutlined } from "@ant-design/icons";
import {
  Alert, Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag, message,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { useI18n } from "../../i18n";
import { aircraftStatus, money, typeLabel } from "../../ops";
import type { OpsAircraft, OpsAircraftType } from "../../types";

interface AddForm {
  type_id: string;
  registration: string;
  base_airport_icao: string;
  acquisition_type: "LEASE" | "OWNED";
  lease_per_hour?: number;
}

export function OpsFleet() {
  const { tr } = useI18n();
  const [fleet, setFleet] = useState<OpsAircraft[]>([]);
  const [types, setTypes] = useState<OpsAircraftType[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm<AddForm>();

  const load = useCallback(async () => {
    const [f, t] = await Promise.all([
      api<{ items: OpsAircraft[] }>("/local/ops/fleet"),
      api<{ items: OpsAircraftType[] }>("/local/ops/aircraft-types"),
    ]);
    setFleet(f.items);
    setTypes(t.items);
  }, []);

  useEffect(() => { void load().catch((e: Error) => message.error(e.message)); }, [load]);

  const typeOptions = useMemo(() => types.map((t) => ({
    value: t.id,
    label: `${typeLabel(t)} · ${t.pax_capacity}${tr("座", "pax")}`,
  })), [types, tr]);

  const add = async () => {
    const values = await form.validateFields();
    setBusy(true);
    try {
      await api("/local/ops/fleet", { method: "POST", body: JSON.stringify(values) });
      setOpen(false);
      form.resetFields();
      await load();
      message.success(tr("飞机已加入机队", "Aircraft added"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const patch = async (row: OpsAircraft, body: Record<string, unknown>) => {
    try {
      await api(`/local/ops/fleet/${row.id}`, { method: "PATCH", body: JSON.stringify(body) });
      await load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const release = async (row: OpsAircraft) => {
    try {
      await api(`/local/ops/fleet/${row.id}/release`, {
        method: "POST", body: JSON.stringify({ reason: "手工释放" }),
      });
      await load();
      message.success(tr("已释放占用", "Released"));
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("机队", "Fleet")}</h2>
          <p>{tr("逐机档案：注册号、构型、当前位置、总小时与状态；公务机不进入普通抽班。", "Per-aircraft records: registration, configuration, position, hours and status. Bizjets stay out of normal roster draws.")}</p>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>{tr("刷新", "Refresh")}</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>{tr("新增飞机", "Add aircraft")}</Button>
        </Space>
      </div>

      {fleet.length === 0 ? (
        <Alert type="info" showIcon message={tr("机队为空", "Fleet is empty")}
          description={tr("先从机型模板新增一架飞机。", "Add an aircraft from a type template first.")} />
      ) : (
        <Card className="panel" variant="borderless" styles={{ body: { padding: 0 } }}>
          <Table
            rowKey="id"
            size="small"
            dataSource={fleet}
            pagination={false}
            columns={[
              {
                title: tr("注册号", "Registration"), dataIndex: "registration", width: 110,
                render: (v: string) => <strong>{v}</strong>,
              },
              {
                title: tr("机型", "Type"), key: "type",
                render: (_: unknown, r: OpsAircraft) => (
                  <span>
                    {r.type_icao || "—"}
                    {r.type_variant && r.type_variant !== "STANDARD" ? <Tag color="purple">{r.type_variant}</Tag> : null}
                    <span className="muted"> {r.type_name}</span>
                  </span>
                ),
              },
              { title: tr("基地", "Base"), dataIndex: "base_airport_icao", width: 80 },
              {
                title: tr("当前位置", "Position"), dataIndex: "current_airport_icao", width: 100,
                render: (v: string) => <span className="mono">{v || "—"}</span>,
              },
              {
                title: tr("状态", "Status"), dataIndex: "status", width: 100,
                render: (v: string) => (
                  <Tag color={aircraftStatus[v]?.color}>{aircraftStatus[v] ? tr(aircraftStatus[v].zh, aircraftStatus[v].en) : v}</Tag>
                ),
              },
              {
                title: tr("小时 / 循环", "Hours / cycles"), key: "hours", width: 130,
                render: (_: unknown, r: OpsAircraft) => `${r.total_hours.toFixed(1)} h · ${r.total_cycles}`,
              },
              {
                title: tr("租赁", "Lease"), dataIndex: "lease_per_hour", width: 110,
                render: (v: number | null, r: OpsAircraft) => (r.acquisition_type === "OWNED" ? tr("自有", "Owned") : money(v)),
              },
              {
                title: tr("操作", "Actions"), key: "actions", width: 240,
                render: (_: unknown, r: OpsAircraft) => (
                  <Space size={4} wrap>
                    {r.locked ? (
                      <Popconfirm title={tr("强制释放飞机？会取消相关班表", "Force release? Related rosters are cancelled")}
                        onConfirm={() => void release(r)}>
                        <Button size="small" danger icon={<UnlockOutlined />}>{tr("释放", "Release")}</Button>
                      </Popconfirm>
                    ) : null}
                    {r.status === "ACTIVE" || r.status === "MAINTENANCE" ? (
                      <Button size="small" onClick={() => void patch(r, {
                        status: r.status === "ACTIVE" ? "MAINTENANCE" : "ACTIVE", version: r.version,
                      })}>
                        {r.status === "ACTIVE" ? tr("送修", "Maintenance") : tr("恢复", "Restore")}
                      </Button>
                    ) : null}
                    {r.status !== "RETIRED" && !r.locked ? (
                      <Popconfirm title={tr("退役后不能再执行航班", "Retire this aircraft?")}
                        onConfirm={() => void patch(r, { status: "RETIRED", version: r.version })}>
                        <Button size="small" danger type="text">{tr("退役", "Retire")}</Button>
                      </Popconfirm>
                    ) : null}
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      )}

      <Modal
        open={open}
        title={tr("新增飞机", "Add aircraft")}
        onCancel={() => setOpen(false)}
        onOk={() => void add()}
        confirmLoading={busy}
        okText={tr("加入机队", "Add")}
      >
        <Form form={form} layout="vertical" initialValues={{ acquisition_type: "LEASE", base_airport_icao: "ZBAA" }}>
          <Form.Item name="type_id" label={tr("机型模板", "Type template")} rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" options={typeOptions} />
          </Form.Item>
          <Form.Item name="registration" label={tr("注册号", "Registration")} rules={[{ required: true }]}>
            <Input maxLength={12} placeholder="B-1671" />
          </Form.Item>
          <Form.Item name="base_airport_icao" label={tr("基地机场", "Base airport")} rules={[{ required: true }]}>
            <Input maxLength={4} />
          </Form.Item>
          <Form.Item name="acquisition_type" label={tr("引进方式", "Acquisition")}>
            <Select options={[
              { value: "LEASE", label: tr("租赁", "Lease") },
              { value: "OWNED", label: tr("自有", "Owned") },
            ]} />
          </Form.Item>
          <Form.Item name="lease_per_hour" label={tr("租赁/小时（留空用机型默认）", "Lease per hour (blank = type default)")}>
            <InputNumber min={0} style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
