import { PlusOutlined, ReloadOutlined, SettingOutlined, UnlockOutlined } from "@ant-design/icons";
import {
  Alert, Button, Card, Col, Drawer, Form, Input, InputNumber, Modal, Popconfirm, Row, Select,
  Space, Switch, Table, Tag, Tooltip, message,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type ApiError } from "../../api";
import { useApp } from "../../context";
import { useI18n } from "../../i18n";
import { aircraftStatus, money, typeLabel } from "../../ops";
import type { OpsAircraft, OpsAircraftType } from "../../types";

interface AddForm {
  type_id?: string;
  registration: string;
  base_airport_icao: string;
  acquisition_type: "LEASE" | "OWNED";
  lease_per_hour?: number;
}

/** 机型模板表单：字段名与后端 `aircraft_type` 列一致，客舱构型用嵌套字段。 */
interface TypeFormValues {
  icao: string;
  variant: string;
  name: string;
  manufacturer?: string;
  role: string;
  title_keyword?: string;
  pax_capacity: number;
  cabin_config_json: { first: number; business: number; premium_economy: number; economy: number };
  cargo_capacity_kg: number;
  oew_kg: number;
  mzfw_kg: number;
  mlw_kg: number;
  mtow_kg: number;
  fuel_capacity_kg: number;
  fuel_burn_kg_h: number;
  cruise_speed_kt: number;
  cruise_fl: number;
  min_runway_m: number;
  wingspan_m: number;
  range_nm: number;
  lease_per_hour: number;
  charter_rate_per_hour: number;
  allow_scheduled: boolean;
  allow_charter: boolean;
}

const TYPE_DEFAULTS: TypeFormValues = {
  icao: "",
  variant: "STANDARD",
  name: "",
  manufacturer: "",
  role: "AIRLINER",
  title_keyword: "",
  pax_capacity: 180,
  cabin_config_json: { first: 0, business: 18, premium_economy: 0, economy: 162 },
  cargo_capacity_kg: 9000,
  oew_kg: 42600,
  mzfw_kg: 62500,
  mlw_kg: 66000,
  mtow_kg: 78000,
  fuel_capacity_kg: 19000,
  fuel_burn_kg_h: 2400,
  cruise_speed_kt: 440,
  cruise_fl: 350,
  min_runway_m: 1600,
  wingspan_m: 36,
  range_nm: 3000,
  lease_per_hour: 2000,
  charter_rate_per_hour: 0,
  allow_scheduled: true,
  allow_charter: true,
};

function typeFormValues(row: OpsAircraftType): TypeFormValues {
  return {
    icao: row.icao,
    variant: row.variant,
    name: row.name || "",
    manufacturer: row.manufacturer || "",
    role: row.role,
    title_keyword: row.title_keyword || "",
    pax_capacity: row.pax_capacity,
    cabin_config_json: {
      first: row.cabin_config_json?.first || 0,
      business: row.cabin_config_json?.business || 0,
      premium_economy: row.cabin_config_json?.premium_economy || 0,
      economy: row.cabin_config_json?.economy || 0,
    },
    cargo_capacity_kg: row.cargo_capacity_kg,
    oew_kg: row.oew_kg,
    mzfw_kg: row.mzfw_kg,
    mlw_kg: row.mlw_kg,
    mtow_kg: row.mtow_kg,
    fuel_capacity_kg: row.fuel_capacity_kg,
    fuel_burn_kg_h: row.fuel_burn_kg_h,
    cruise_speed_kt: row.cruise_speed_kt,
    cruise_fl: row.cruise_fl,
    min_runway_m: row.min_runway_m,
    wingspan_m: row.wingspan_m || 0,
    range_nm: row.range_nm,
    lease_per_hour: row.lease_per_hour,
    charter_rate_per_hour: row.charter_rate_per_hour,
    allow_scheduled: row.allow_scheduled,
    allow_charter: row.allow_charter,
  };
}

export function OpsFleet() {
  const { tr } = useI18n();
  const { recording } = useApp();
  const [fleet, setFleet] = useState<OpsAircraft[]>([]);
  const [types, setTypes] = useState<OpsAircraftType[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm<AddForm>();

  // 机型模板抽屉
  const [typeOpen, setTypeOpen] = useState(false);
  const [typeModal, setTypeModal] = useState(false);
  const [editing, setEditing] = useState<OpsAircraftType | null>(null);
  const [typeBusy, setTypeBusy] = useState(false);
  const [typeForm] = Form.useForm<TypeFormValues>();

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

  // ---- 机型模板 ----
  const openCreateType = () => {
    setEditing(null);
    typeForm.resetFields();
    typeForm.setFieldsValue(TYPE_DEFAULTS);
    setTypeModal(true);
  };

  const openEditType = (row: OpsAircraftType) => {
    setEditing(row);
    typeForm.resetFields();
    typeForm.setFieldsValue(typeFormValues(row));
    setTypeModal(true);
  };

  /** 内置机型只读：复制一份填进新增表单（变体名默认 CUSTOM，避免与内置撞唯一键）。 */
  const openCopyType = (row: OpsAircraftType) => {
    setEditing(null);
    typeForm.resetFields();
    typeForm.setFieldsValue({
      ...typeFormValues(row),
      variant: row.variant === "STANDARD" ? "CUSTOM" : `${row.variant}C`.slice(0, 16),
      name: `${row.name || row.icao} ${tr("（自定义）", "(custom)")}`,
    });
    setTypeModal(true);
  };

  const submitType = async () => {
    const values = await typeForm.validateFields();
    setTypeBusy(true);
    try {
      const body = JSON.stringify(values);
      if (editing) {
        await api(`/local/ops/aircraft-types/${editing.id}`, { method: "PATCH", body });
      } else {
        await api("/local/ops/aircraft-types", { method: "POST", body });
      }
      setTypeModal(false);
      setEditing(null);
      typeForm.resetFields();
      await load();
      message.success(editing
        ? tr("机型参数已更新", "Type updated")
        : tr("自定义机型已新增", "Custom type created"));
    } catch (e) {
      const err = e as ApiError;
      const key = typeof err.details?.key === "string" ? err.details.key : undefined;
      if (key) typeForm.setFields([{ name: key as keyof TypeFormValues, errors: [err.message] }]);
      message.error(err.message);
    } finally {
      setTypeBusy(false);
    }
  };

  const disableType = async (row: OpsAircraftType) => {
    try {
      await api(`/local/ops/aircraft-types/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ allow_scheduled: false, allow_charter: false }),
      });
      await load();
      message.success(tr("机型已停用（不再参与抽班/包机）", "Type disabled"));
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const deleteType = async (row: OpsAircraftType) => {
    try {
      await api(`/local/ops/aircraft-types/${row.id}`, { method: "DELETE" });
      await load();
      message.success(tr("自定义机型已删除", "Custom type deleted"));
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
          <Button icon={<SettingOutlined />} onClick={() => setTypeOpen(true)}>{tr("机型模板", "Type templates")}</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>{tr("新增飞机", "Add aircraft")}</Button>
        </Space>
      </div>

      {fleet.length === 0 ? (
        <Alert type="info" showIcon message={tr("机队为空", "Fleet is empty")}
          description={tr("先从机型模板新增一架飞机；目录里没有的机型可在「机型模板」里自己加。",
            "Add an aircraft from a type template first; add your own model under “Type templates” if it is missing.")} />
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

      <Drawer
        open={typeOpen}
        width={1040}
        title={tr("机型模板", "Aircraft type templates")}
        onClose={() => setTypeOpen(false)}
        extra={(
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void load()}>{tr("刷新", "Refresh")}</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreateType}>
              {tr("新增机型", "New type")}
            </Button>
          </Space>
        )}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message={tr("内置模板只读，可「复制」成自定义机型再改参数",
            "Built-in templates are read-only — copy one to a custom type and edit it")}
          description={tr("自定义机型的重量/座位/油耗会直接影响配载、航时估算与结算成本。",
            "Custom weights, seats and fuel burn feed load sheets, block-time estimates and settlement costs.")}
        />
        <Table
          rowKey="id"
          size="small"
          dataSource={types}
          pagination={{ pageSize: 12, showSizeChanger: false }}
          columns={[
            {
              title: tr("机型", "Type"), key: "type",
              render: (_: unknown, r: OpsAircraftType) => <span>{typeLabel(r)}</span>,
            },
            {
              title: tr("来源", "Source"), dataIndex: "source", width: 84,
              render: (v: string) => (v === "CUSTOM"
                ? <Tag color="purple">{tr("自定义", "Custom")}</Tag>
                : <Tag>{tr("内置", "Built-in")}</Tag>),
            },
            { title: tr("座位", "Seats"), dataIndex: "pax_capacity", width: 70 },
            {
              title: "OEW / MTOW", key: "w", width: 140,
              render: (_: unknown, r: OpsAircraftType) =>
                `${Math.round(r.oew_kg / 1000)}t / ${Math.round(r.mtow_kg / 1000)}t`,
            },
            {
              title: tr("油耗", "Fuel burn"), dataIndex: "fuel_burn_kg_h", width: 96,
              render: (v: number) => `${Math.round(v)} kg/h`,
            },
            {
              title: tr("租赁", "Lease"), dataIndex: "lease_per_hour", width: 96,
              render: (v: number) => `${money(v)}/h`,
            },
            {
              title: tr("运营", "Ops"), key: "ops", width: 130,
              render: (_: unknown, r: OpsAircraftType) => (
                <Space size={4}>
                  {r.allow_scheduled ? <Tag color="blue">{tr("定期", "Scheduled")}</Tag> : null}
                  {r.allow_charter ? <Tag color="cyan">{tr("包机", "Charter")}</Tag> : null}
                  {!r.allow_scheduled && !r.allow_charter
                    ? <Tag color="default">{tr("已停用", "Disabled")}</Tag> : null}
                </Space>
              ),
            },
            {
              title: tr("操作", "Actions"), key: "act", width: 220,
              render: (_: unknown, r: OpsAircraftType) => (
                <Space size={4} wrap>
                  {r.source === "CUSTOM" ? (
                    <Button size="small" onClick={() => openEditType(r)}>{tr("编辑", "Edit")}</Button>
                  ) : null}
                  <Button size="small" onClick={() => openCopyType(r)}>{tr("复制", "Copy")}</Button>
                  {r.source === "CUSTOM" ? (
                    <>
                      <Tooltip title={tr("停用后不再参与抽班/包机", "Disabled types are excluded from draws")}>
                        <Button size="small" onClick={() => void disableType(r)}>{tr("停用", "Disable")}</Button>
                      </Tooltip>
                      <Popconfirm
                        title={tr("删除这个自定义机型？", "Delete this custom type?")}
                        description={tr("机队里还有飞机在用时会拒绝删除。", "Deletion is rejected while aircraft still use it.")}
                        onConfirm={() => void deleteType(r)}
                      >
                        <Button size="small" danger type="text">{tr("删除", "Delete")}</Button>
                      </Popconfirm>
                    </>
                  ) : null}
                </Space>
              ),
            },
          ]}
        />
      </Drawer>

      <Modal
        open={typeModal}
        width={860}
        title={editing
          ? tr("编辑自定义机型", "Edit custom type")
          : tr("新增自定义机型", "New custom type")}
        onCancel={() => { setTypeModal(false); setEditing(null); }}
        onOk={() => void submitType()}
        confirmLoading={typeBusy}
        okText={editing ? tr("保存", "Save") : tr("新增", "Create")}
      >
        <Form form={typeForm} layout="vertical" initialValues={TYPE_DEFAULTS}>
          <Row gutter={12}>
            <Col span={6}>
              <Form.Item name="icao" label="ICAO" rules={[{ required: true, message: "ICAO" }]}>
                <Input maxLength={5} placeholder="A320 / XWJ" />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="variant" label={tr("变体", "Variant")}>
                <Input maxLength={16} placeholder="STANDARD / BIZJET" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="name" label={tr("名称", "Name")}>
                <Input maxLength={120} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="manufacturer" label={tr("制造商", "Manufacturer")}>
                <Input maxLength={80} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="role" label={tr("角色", "Role")}>
                <Select options={[
                  { value: "AIRLINER", label: tr("干线", "Airliner") },
                  { value: "BIZJET", label: tr("公务机", "Bizjet") },
                  { value: "VIP", label: "VIP" },
                  { value: "CARGO", label: tr("货机", "Cargo") },
                ]} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="title_keyword"
                label={tr("机模标题关键字", "Sim title keyword")}
                tooltip={tr("新增飞机时留空机型，会按 SimLink 的 aircraft_title 包含该关键字自动匹配",
                  "When adding an aircraft without a type, this keyword is matched against SimLink aircraft_title")}
              >
                <Input maxLength={80} placeholder="Fenix A320" />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="pax_capacity" label={tr("座位数", "Seats")}
                rules={[{ required: true }]}>
                <InputNumber min={0} max={900} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name={["cabin_config_json", "economy"]} label={tr("经济舱", "Economy")}>
                <InputNumber min={0} max={900} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name={["cabin_config_json", "business"]} label={tr("商务舱", "Business")}>
                <InputNumber min={0} max={200} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name={["cabin_config_json", "first"]} label={tr("头等舱", "First")}>
                <InputNumber min={0} max={100} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="cargo_capacity_kg" label={tr("货舱（kg）", "Cargo (kg)")}>
                <InputNumber min={0} max={400000} step={500} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="oew_kg" label="OEW (kg)" rules={[{ required: true }]}>
                <InputNumber min={1} max={700000} step={100} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="mzfw_kg" label="MZFW (kg)" rules={[{ required: true }]}>
                <InputNumber min={1} max={700000} step={100} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="mlw_kg" label="MLW (kg)">
                <InputNumber min={1} max={800000} step={100} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="mtow_kg" label="MTOW (kg)" rules={[{ required: true }]}>
                <InputNumber min={1} max={900000} step={100} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="fuel_capacity_kg" label={tr("燃油容量（kg）", "Fuel capacity (kg)")}>
                <InputNumber min={0} max={600000} step={100} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="fuel_burn_kg_h" label={tr("油耗（kg/h）", "Fuel burn (kg/h)")}>
                <InputNumber min={0.1} max={30000} step={50} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="cruise_speed_kt" label={tr("巡航速度（kt）", "Cruise (kt)")}>
                <InputNumber min={60} max={600} step={5} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="cruise_fl" label={tr("巡航高度层", "Cruise FL")}>
                <InputNumber min={0} max={600} step={10} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="min_runway_m" label={tr("最短跑道（m）", "Min runway (m)")}>
                <InputNumber min={0} max={5000} step={100} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="wingspan_m" label={tr("翼展（m）", "Wingspan (m)")}
                tooltip={tr("抽班按翼展 ≤ 跑道宽度推出的上限过滤（45 m → 52 m）；0 表示按最短跑道推断",
                  "Draw filters airports by wingspan ≤ runway-width limit (45 m → 52 m); 0 = derive from min runway")}>
                <InputNumber min={0} max={90} step={0.5} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="range_nm" label={tr("航程（NM）", "Range (NM)")}>
                <InputNumber min={1} max={20000} step={100} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="lease_per_hour" label={tr("租赁/小时", "Lease/h")}>
                <InputNumber min={0} max={100000} step={100} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="charter_rate_per_hour" label={tr("包机/小时", "Charter/h")}>
                <InputNumber min={0} max={200000} step={100} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="allow_scheduled" label={tr("参与定期班", "Scheduled")} valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="allow_charter" label={tr("参与包机", "Charter")} valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
          <div className="muted" style={{ fontSize: 12 }}>
            {tr("校验：0 < OEW < MZFW ≤ MTOW、MLW ≤ MTOW、座位数与客舱构型一致；超范围会就地高亮。",
              "Checks: 0 < OEW < MZFW ≤ MTOW, MLW ≤ MTOW, seats must match the cabin config.")}
          </div>
        </Form>
      </Modal>

      <Modal
        open={open}
        title={tr("新增飞机", "Add aircraft")}
        onCancel={() => setOpen(false)}
        onOk={() => void add()}
        confirmLoading={busy}
        okText={tr("加入机队", "Add")}
      >
        <Form form={form} layout="vertical" initialValues={{ acquisition_type: "LEASE", base_airport_icao: "ZBAA" }}>
          <Form.Item name="type_id" label={tr("机型模板", "Type template")}
            extra={recording.aircraft_title
              ? tr(`当前模拟器机模：${recording.aircraft_title}（留空则按关键字自动匹配）`,
                `Current sim aircraft: ${recording.aircraft_title} (leave empty to auto-match)`)
              : undefined}>
            <Select showSearch optionFilterProp="label" allowClear options={typeOptions} />
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
