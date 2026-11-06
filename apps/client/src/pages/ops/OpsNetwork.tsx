import { DeleteOutlined, PlusOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import {
  Alert, Button, Card, Checkbox, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tabs, Tag, message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { AirportSelect } from "../../components/AirportSelect";
import { useApp } from "../../context";
import { useI18n } from "../../i18n";
import { fmtBlock, fmtUtc, hoursFromMinutes } from "../../ops";
import type { OpsAircraftType, OpsInstance, OpsRoute, OpsSchedule } from "../../types";

// UI-13：星期标签要走 i18n（英文模式下以前仍是「一二三四五六日」）
const WEEKDAYS = [
  { zh: "一", en: "Mon", value: 1 }, { zh: "二", en: "Tue", value: 2 },
  { zh: "三", en: "Wed", value: 4 }, { zh: "四", en: "Thu", value: 8 },
  { zh: "五", en: "Fri", value: 16 }, { zh: "六", en: "Sat", value: 32 },
  { zh: "日", en: "Sun", value: 64 },
];

const instanceColor: Record<string, string> = {
  SCHEDULED: "green", ASSIGNED: "gold", STARTED: "blue", LANDED: "cyan",
  SETTLED: "default", CANCELLED: "red", ABORTED: "orange",
};

const instanceLabel: Record<string, { zh: string; en: string }> = {
  SCHEDULED: { zh: "已排班", en: "Scheduled" },
  ASSIGNED: { zh: "已分配", en: "Assigned" },
  STARTED: { zh: "已开始", en: "Started" },
  LANDED: { zh: "已落地", en: "Landed" },
  SETTLED: { zh: "已结算", en: "Settled" },
  CANCELLED: { zh: "已取消", en: "Cancelled" },
  ABORTED: { zh: "已中止", en: "Aborted" },
};

export function OpsNetwork() {
  const { tr } = useI18n();
  // IA-07：联机模式下航线/班期由服务端维护，本页只读
  const { onlineMode, refreshKey } = useApp();
  const readOnly = onlineMode;
  const [routes, setRoutes] = useState<OpsRoute[]>([]);
  const [schedules, setSchedules] = useState<OpsSchedule[]>([]);
  const [instances, setInstances] = useState<OpsInstance[]>([]);
  const [types, setTypes] = useState<OpsAircraftType[]>([]);
  const [routeOpen, setRouteOpen] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [routeForm] = Form.useForm();
  const [scheduleForm] = Form.useForm();

  const load = useCallback(async () => {
    const [r, s, i, t] = await Promise.all([
      api<{ items: OpsRoute[] }>("/local/ops/routes"),
      api<{ items: OpsSchedule[] }>("/local/ops/schedules"),
      api<{ items: OpsInstance[] }>("/local/ops/instances?days=7"),
      api<{ items: OpsAircraftType[] }>("/local/ops/aircraft-types"),
    ]);
    setRoutes(r.items);
    setSchedules(s.items);
    setInstances(i.items);
    setTypes(t.items);
  }, []);

  useEffect(() => { void load().catch((e: Error) => message.error(e.message)); }, [load, refreshKey]);

  const addRoute = async () => {
    const values = await routeForm.validateFields();
    setBusy(true);
    try {
      await api("/local/ops/routes", { method: "POST", body: JSON.stringify(values) });
      setRouteOpen(false);
      routeForm.resetFields();
      await load();
      message.success(tr("航线已创建", "Route created"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const addSchedule = async () => {
    const values = await scheduleForm.validateFields();
    // UI-12：全部取消勾选以前会被静默改成「每天」，用户会以为不排班 —— 直接拦住
    const days = (values.days as number[] | undefined) || [];
    if (!days.length) {
      message.warning(tr("请至少选一个运行日（留空不等于不排班，以前会被当成每天）",
        "Pick at least one operating day (an empty set used to mean every day)"));
      return;
    }
    setBusy(true);
    try {
      await api("/local/ops/schedules", {
        method: "POST",
        body: JSON.stringify({ ...values, days_of_week: days.reduce((acc, v) => acc + v, 0) }),
      });
      setScheduleOpen(false);
      scheduleForm.resetFields();
      await load();
      message.success(tr("班期已创建", "Schedule created"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    try {
      const res = await api<{ created: number }>("/local/ops/schedules/generate?days=7", { method: "POST" });
      await load();
      message.success(`${tr("生成航班实例", "Instances created")} ${res.created}`);
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const cancelInstance = async (row: OpsInstance) => {
    try {
      await api(`/local/ops/instances/${row.id}/cancel`, { method: "POST" });
      await load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const removeRoute = async (row: OpsRoute) => {
    try {
      await api(`/local/ops/routes/${row.id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const removeSchedule = async (row: OpsSchedule) => {
    try {
      await api(`/local/ops/schedules/${row.id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const toggleSchedule = async (row: OpsSchedule, enabled: boolean) => {
    try {
      await api(`/local/ops/schedules/${row.id}`, {
        method: "PATCH", body: JSON.stringify({ enabled }),
      });
      await load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("航线与班期", "Routes & schedules")}</h2>
          <p>{tr("三层结构：航线 → 班期模板 → 航班实例；实例是抽班的库存。", "Three layers: route → schedule template → flight instances (the roster inventory).")}</p>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>{tr("刷新", "Refresh")}</Button>
          <Button icon={<SyncOutlined />} disabled={readOnly} onClick={() => void generate()}>
            {tr("生成未来 7 天", "Generate 7 days")}
          </Button>
        </Space>
      </div>

      {readOnly ? (
        <Alert type="info" showIcon
          message={tr("联机模式：该数据由公司服务端维护", "Online mode: maintained by the company server")}
          description={tr("客户端的航线/班期编辑已隐藏或置灰；未开启联机时仍可自由编辑。",
            "Route/schedule editing is disabled in online mode; turn online mode off to edit locally.")} />
      ) : null}

      <Tabs
        items={[
          {
            key: "routes",
            label: `${tr("航线", "Routes")} (${routes.length})`,
            children: (
              <Card className="panel" variant="borderless" styles={{ body: { padding: 0 } }}
                title={<span>{tr("航线网络", "Network")}</span>}
                extra={<Button size="small" type="primary" icon={<PlusOutlined />} disabled={readOnly}
                  onClick={() => setRouteOpen(true)}>{tr("新增航线", "Add route")}</Button>}>
                <Table
                  rowKey="id"
                  size="small"
                  dataSource={routes}
                  pagination={false}
                  columns={[
                    { title: tr("起降", "Pair"), key: "pair", render: (_: unknown, r: OpsRoute) => `${r.dep_icao} → ${r.arr_icao}` },
                    { title: tr("距离", "Distance"), dataIndex: "distance_nm", width: 100, render: (v: number) => `${Math.round(v)} NM` },
                    { title: tr("计划航时", "Block"), dataIndex: "block_minutes", width: 100, render: (v: number) => fmtBlock(v) },
                    { title: tr("巡航", "Cruise"), dataIndex: "cruise_fl", width: 80, render: (v: number) => `FL${v}` },
                    { title: "SID/STAR", key: "proc", render: (_: unknown, r: OpsRoute) => `${r.default_sid || "—"} / ${r.default_star || "—"}` },
                    {
                      title: "", key: "del", width: 60,
                      render: (_: unknown, r: OpsRoute) => (
                        <Popconfirm title={tr("删除航线？", "Delete route?")} onConfirm={() => void removeRoute(r)}>
                          <Button size="small" type="text" danger icon={<DeleteOutlined />} disabled={readOnly} />
                        </Popconfirm>
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: "schedules",
            label: `${tr("班期", "Schedules")} (${schedules.length})`,
            children: (
              <Card className="panel" variant="borderless" styles={{ body: { padding: 0 } }}
                extra={<Button size="small" type="primary" icon={<PlusOutlined />} disabled={readOnly}
                  onClick={() => setScheduleOpen(true)}>{tr("新增班期", "Add schedule")}</Button>}>
                <Table
                  rowKey="id"
                  size="small"
                  dataSource={schedules}
                  pagination={false}
                  columns={[
                    { title: tr("航班号", "Flight"), dataIndex: "flight_number", width: 100, render: (v: string) => <strong>{v}</strong> },
                    { title: tr("航线", "Route"), key: "route", render: (_: unknown, r: OpsSchedule) => `${r.dep_icao || "—"} → ${r.arr_icao || "—"}` },
                    { title: tr("本地时刻", "Local dep"), dataIndex: "dep_local_time", width: 100 },
                    { title: tr("航时", "Block"), dataIndex: "block_minutes", width: 80, render: (v: number) => fmtBlock(v) },
                    { title: tr("机型", "Type"), key: "type", render: (_: unknown, r: OpsSchedule) => r.type_icao ? `${r.type_icao}${r.type_variant && r.type_variant !== "STANDARD" ? ` ${r.type_variant}` : ""}` : tr("任意", "Any") },
                    { title: tr("过站", "Turn"), dataIndex: "turnaround_min", width: 70, render: (v: number) => `${v}min` },
                    {
                      // UI-11：以前是个「看起来像标签」的控件，点一下就切换 —— 改成明确的开关
                      title: tr("启用", "Enabled"), dataIndex: "enabled", width: 90,
                      render: (v: boolean, r: OpsSchedule) => (
                        <Space size={6}>
                          <Switch size="small" checked={v} disabled={readOnly}
                            onChange={(next) => void toggleSchedule(r, next)} />
                          <span className="muted" style={{ fontSize: 12 }}>{v ? tr("启用", "on") : tr("停用", "off")}</span>
                        </Space>
                      ),
                    },
                    {
                      title: "", key: "del", width: 60,
                      render: (_: unknown, r: OpsSchedule) => (
                        <Popconfirm title={tr("删除班期？", "Delete schedule?")} onConfirm={() => void removeSchedule(r)}>
                          <Button size="small" type="text" danger icon={<DeleteOutlined />} disabled={readOnly} />
                        </Popconfirm>
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: "instances",
            label: `${tr("航班实例", "Instances")} (${instances.length})`,
            children: (
              <Card className="panel" variant="borderless" styles={{ body: { padding: 0 } }}>
                <Table
                  rowKey="id"
                  size="small"
                  dataSource={instances}
                  pagination={{ pageSize: 12, showSizeChanger: false }}
                  columns={[
                    { title: tr("航班号", "Flight"), dataIndex: "flight_number", width: 100 },
                    { title: tr("起降", "Pair"), key: "pair", render: (_: unknown, r: OpsInstance) => `${r.dep_icao} → ${r.arr_icao}` },
                    { title: tr("计划起飞 (UTC)", "ETD (UTC)"), dataIndex: "scheduled_dep_utc", render: (v: string) => <span className="mono">{fmtUtc(v)}</span> },
                    { title: tr("计划到达", "ETA"), dataIndex: "scheduled_arr_utc", render: (v: string) => <span className="mono">{fmtUtc(v)}</span> },
                    { title: tr("任务", "Mission"), dataIndex: "mission_type", width: 100 },
                    {
                      title: tr("状态", "Status"), dataIndex: "status", width: 110,
                      render: (v: string) => (
                        <Tag color={instanceColor[v] || "default"}>
                          {instanceLabel[v] ? tr(instanceLabel[v].zh, instanceLabel[v].en) : v}
                        </Tag>
                      ),
                    },
                    {
                      title: "", key: "act", width: 80,
                      render: (_: unknown, r: OpsInstance) => (r.status === "SCHEDULED" ? (
                        <Popconfirm title={tr("取消该航班实例？", "Cancel this instance?")} onConfirm={() => void cancelInstance(r)}>
                          <Button size="small" type="text" danger disabled={readOnly}>{tr("取消", "Cancel")}</Button>
                        </Popconfirm>
                      ) : null),
                    },
                  ]}
                />
              </Card>
            ),
          },
        ]}
      />

      <Modal open={routeOpen} title={tr("新增航线", "Add route")} onCancel={() => setRouteOpen(false)}
        onOk={() => void addRoute()} confirmLoading={busy} okText={tr("创建", "Create")}>
        <Form form={routeForm} layout="vertical">
          <Form.Item name="dep_icao" label={tr("起飞机场", "Departure")} rules={[{ required: true }]}>
            <AirportSelect placeholder="ZBAA" />
          </Form.Item>
          <Form.Item name="arr_icao" label={tr("到达机场", "Arrival")} rules={[{ required: true }]}>
            <AirportSelect placeholder="ZSSS" />
          </Form.Item>
          <Space size={12} style={{ display: "flex" }}>
            <Form.Item name="distance_nm" label={tr("距离 NM（留空自动）", "Distance NM (auto)")} style={{ flex: 1 }}>
              <InputNumber min={10} max={12000} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="block_minutes" label={tr("计划航时 min（留空自动）", "Block min (auto)")} style={{ flex: 1 }}>
              <InputNumber min={15} max={1440} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="cruise_fl" label={tr("巡航高度", "Cruise FL")} initialValue={350} style={{ width: 120 }}>
              <InputNumber min={50} max={450} style={{ width: "100%" }} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      <Modal open={scheduleOpen} title={tr("新增班期", "Add schedule")} onCancel={() => setScheduleOpen(false)}
        onOk={() => void addSchedule()} confirmLoading={busy} okText={tr("创建", "Create")} width={560}>
        <Form form={scheduleForm} layout="vertical" initialValues={{ turnaround_min: 45, days: [1, 2, 4, 8, 16, 32, 64] }}>
          <Form.Item name="route_id" label={tr("航线", "Route")} rules={[{ required: true }]}>
            <Select options={routes.map((r) => ({
              value: r.id, label: `${r.dep_icao} → ${r.arr_icao} · ${fmtBlock(r.block_minutes)}`,
            }))} />
          </Form.Item>
          <Space size={12} style={{ display: "flex" }}>
            <Form.Item name="flight_number" label={tr("航班号", "Flight number")} rules={[{ required: true }]} style={{ flex: 1 }}>
              <Input maxLength={8} placeholder="AOC101" />
            </Form.Item>
            {/* UI-12：时刻不再随便填 —— 统一成 HH:MM，非法值就地报错 */}
            <Form.Item
              name="dep_local_time"
              label={tr("本地起飞 HH:MM", "Local dep HH:MM")}
              style={{ width: 160 }}
              normalize={(value: string) => {
                const raw = String(value ?? "").trim();
                const match = /^(\d{1,2}):(\d{2})$/.exec(raw);
                return match ? `${match[1].padStart(2, "0")}:${match[2]}` : raw;
              }}
              rules={[
                { required: true },
                {
                  pattern: /^([01]\d|2[0-3]):[0-5]\d$/,
                  message: tr("格式为 HH:MM（00:00–23:59）", "Use HH:MM (00:00–23:59)"),
                },
              ]}
            >
              <Input placeholder="08:00" maxLength={5} />
            </Form.Item>
          </Space>
          <Form.Item
            name="days"
            label={tr("运行日（本地）", "Days (local)")}
            rules={[{
              validator: (_rule, value: number[] | undefined) => (value && value.length
                ? Promise.resolve()
                : Promise.reject(new Error(tr("至少选一天", "Pick at least one day")))),
            }]}
          >
            <Checkbox.Group options={WEEKDAYS.map((d) => ({ value: d.value, label: tr(d.zh, d.en) }))} />
          </Form.Item>
          <Space size={12} style={{ display: "flex" }}>
            <Form.Item name="aircraft_type_id" label={tr("机型要求", "Aircraft type")} style={{ flex: 1 }}>
              <Select allowClear options={types.map((t) => ({
                value: t.id, label: `${t.icao}${t.variant !== "STANDARD" ? ` ${t.variant}` : ""} · ${t.pax_capacity}${tr("座", "pax")}`,
              }))} />
            </Form.Item>
            <Form.Item name="turnaround_min" label={tr("过站 min", "Turnaround")} style={{ width: 130 }}>
              <InputNumber min={15} max={1440} style={{ width: "100%" }} />
            </Form.Item>
          </Space>
          <div className="muted" style={{ fontSize: 12 }}>
            {tr("班期按起飞机场本地时区换算 UTC；生成窗口为未来 7 天。",
              "Local departure times are converted to UTC using the departure airport timezone; instances are generated for the next 7 days.")}
          </div>
        </Form>
      </Modal>
    </div>
  );
}
