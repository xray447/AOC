import { Alert, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tabs, Tag, message } from "antd";
import { useEffect, useState } from "react";
import { ApiError, api, timeText } from "../api";
import type { AircraftType, Flight, NetworkRoute, Schedule } from "../types";

interface FlightPage {
  items: Flight[];
  total: number;
  page: number;
  page_size: number;
}

export function NetworkPage() {
  const [routes, setRoutes] = useState<NetworkRoute[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [types, setTypes] = useState<AircraftType[]>([]);
  const [flights, setFlights] = useState<FlightPage>({ items: [], total: 0, page: 1, page_size: 50 });
  const [status, setStatus] = useState<string | undefined>();
  const [error, setError] = useState("");
  const [routeOpen, setRouteOpen] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [csv, setCsv] = useState("flight_number,dep,arr,dep_local,days\nAOC901,ZBAA,ZSSS,07:30,0,1,2,3,4\n");
  const [importResult, setImportResult] = useState<{ imported: number; errors: Array<{ line: number; message: string }> } | null>(null);
  const [routeForm] = Form.useForm();
  const [scheduleForm] = Form.useForm();

  const load = async () => {
    try {
      const [routeRows, scheduleRows, typeRows, flightPage] = await Promise.all([
        api<NetworkRoute[]>("/api/v1/admin/network/routes"),
        api<Schedule[]>("/api/v1/admin/network/schedules"),
        api<AircraftType[]>("/api/v1/admin/fleet/types"),
        api<FlightPage>("/api/v1/admin/network/flights", { method: "GET" }),
      ]);
      setRoutes(routeRows);
      setSchedules(scheduleRows);
      setTypes(typeRows);
      setFlights(flightPage);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败");
    }
  };

  const loadFlights = async (page = 1, wanted = status) => {
    const query = new URLSearchParams({ page: String(page), page_size: "50" });
    if (wanted) query.set("status", wanted);
    setFlights(await api<FlightPage>(`/api/v1/admin/network/flights?${query.toString()}`));
  };

  useEffect(() => { void load(); }, []);

  if (error) return <Alert type="error" showIcon message={error} />;

  const createRoute = async (values: Record<string, unknown>) => {
    try {
      await api("/api/v1/admin/network/routes", { method: "POST", body: JSON.stringify(values) });
      setRouteOpen(false);
      routeForm.resetFields();
      message.success("航线已创建");
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "创建失败");
    }
  };

  const createSchedule = async (values: Record<string, unknown>) => {
    try {
      await api("/api/v1/admin/network/schedules", { method: "POST", body: JSON.stringify(values) });
      setScheduleOpen(false);
      scheduleForm.resetFields();
      message.success("班期已创建");
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "创建失败");
    }
  };

  const generate = async () => {
    try {
      const result = await api<{ created: number; skipped: number }>("/api/v1/admin/network/flights/generate", {
        method: "POST", body: JSON.stringify({ days: 7 }),
      });
      message.success(`生成 ${result.created} 班，跳过 ${result.skipped} 班`);
      await loadFlights();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "生成失败");
    }
  };

  const cancel = async (flight: Flight) => {
    try {
      await api(`/api/v1/admin/network/flights/${flight.id}/cancel`, {
        method: "POST", body: JSON.stringify({ reason: "管理端取消" }),
      });
      message.success("航班已取消");
      await loadFlights(flights.page);
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "取消失败");
    }
  };

  const doImport = async () => {
    try {
      const result = await api<{ imported: number; errors: Array<{ line: number; message: string }> }>(
        "/api/v1/admin/network/schedules/import", {
          method: "POST", body: JSON.stringify({ csv }),
        });
      setImportResult(result);
      message.success(`导入 ${result.imported} 条，失败 ${result.errors.length} 条`);
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "导入失败");
    }
  };

  return (
    <Card title="航线与班期" extra={<Space><Button onClick={() => setImportOpen(true)}>CSV 导入班期</Button><Button type="primary" onClick={generate}>生成未来 7 天</Button></Space>}>
      <Tabs
        items={[
          {
            key: "routes", label: `商业航线（${routes.length}）`,
            children: (
              <>
                <Button size="small" type="primary" style={{ marginBottom: 10 }}
                  onClick={() => setRouteOpen(true)}>新建航线</Button>
                <Table<NetworkRoute> rowKey="id" size="small" dataSource={routes} pagination={{ pageSize: 12 }}
                  columns={[
                    { title: "航段", render: (_, row) => `${row.dep_icao} → ${row.arr_icao}` },
                    { title: "距离", dataIndex: "distance_nm", render: (v: number) => `${Math.round(v)} NM` },
                    { title: "Block", dataIndex: "block_minutes", render: (v: number) => `${Math.round(v)} min` },
                    { title: "状态", dataIndex: "active", render: (v: boolean) => <Tag color={v ? "green" : "default"}>{v ? "启用" : "停用"}</Tag> },
                  ]} />
              </>
            ),
          },
          {
            key: "schedules", label: `班期模板（${schedules.length}）`,
            children: (
              <>
                <Button size="small" type="primary" style={{ marginBottom: 10 }}
                  onClick={() => setScheduleOpen(true)}>新建班期</Button>
                <Table<Schedule> rowKey="id" size="small" dataSource={schedules} pagination={{ pageSize: 12 }}
                  columns={[
                    { title: "航班号", dataIndex: "flight_number" },
                    { title: "航段", render: (_, row) => `${row.dep_icao || "—"} → ${row.arr_icao || "—"}` },
                    { title: "本地起飞", dataIndex: "dep_local" },
                    { title: "星期", dataIndex: "days_of_week", render: (v: number[]) => v.join(",") },
                    { title: "状态", dataIndex: "active", render: (v: boolean) => <Tag>{v ? "启用" : "停用"}</Tag> },
                  ]} />
              </>
            ),
          },
          {
            key: "flights", label: "航班实例",
            children: (
              <>
                <Space style={{ marginBottom: 10 }}>
                  <Select allowClear placeholder="状态" style={{ width: 150 }} value={status}
                    onChange={(value) => { setStatus(value); void loadFlights(1, value); }}
                    options={["SCHEDULED", "HELD", "IN_FLIGHT", "COMPLETED", "CANCELLED", "ABANDONED"].map((v) => ({ value: v, label: v }))} />
                  <span className="admin-hint">共 {flights.total} 条</span>
                </Space>
                <Table<Flight> rowKey="id" size="small" dataSource={flights.items}
                  pagination={{ current: flights.page, pageSize: flights.page_size, total: flights.total, onChange: (p) => loadFlights(p) }}
                  columns={[
                    { title: "航班", dataIndex: "flight_number" },
                    { title: "航段", render: (_, row) => `${row.dep_icao} → ${row.arr_icao}` },
                    { title: "计划起飞", dataIndex: "scheduled_dep_utc", render: timeText },
                    { title: "飞机", render: (_, row) => row.aircraft?.registration || "—" },
                    { title: "状态", dataIndex: "status", render: (v: string) => <Tag>{v}</Tag> },
                    { title: "操作", width: 90, render: (_, row) => ["COMPLETED", "CANCELLED", "ABANDONED"].includes(row.status)
                      ? null : <Button size="small" danger onClick={() => cancel(row)}>取消</Button> },
                  ]} />
              </>
            ),
          },
        ]} />

      <Modal title="新建商业航线" open={routeOpen} onCancel={() => setRouteOpen(false)}
        onOk={() => routeForm.submit()}>
        <Form form={routeForm} layout="vertical" onFinish={createRoute}>
          <Form.Item name="dep_icao" label="起飞机场" rules={[{ required: true }]}><Input maxLength={4} /></Form.Item>
          <Form.Item name="arr_icao" label="到达机场" rules={[{ required: true }]}><Input maxLength={4} /></Form.Item>
          <Form.Item name="distance_nm" label="距离（留空自动计算）"><InputNumber style={{ width: "100%" }} min={1} /></Form.Item>
          <Form.Item name="block_minutes" label="Block 分钟（留空自动）"><InputNumber style={{ width: "100%" }} min={20} /></Form.Item>
          <Form.Item name="default_route" label="默认航路"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      <Modal title="新建班期" open={scheduleOpen} onCancel={() => setScheduleOpen(false)}
        onOk={() => scheduleForm.submit()} width={620}>
        <Form form={scheduleForm} layout="vertical" onFinish={createSchedule}
          initialValues={{ dep_local: "09:00", days_of_week: [0, 1, 2, 3, 4, 5, 6], turn_minutes: 45 }}>
          <div className="admin-param-grid">
            <Form.Item name="flight_number" label="航班号" rules={[{ required: true }]}><Input placeholder="AOC901" /></Form.Item>
            <Form.Item name="route_id" label="航线" rules={[{ required: true }]}>
              <Select options={routes.map((r) => ({ value: r.id, label: `${r.dep_icao} → ${r.arr_icao}` }))} />
            </Form.Item>
            <Form.Item name="dep_local" label="本地起飞时刻" rules={[{ required: true }]}><Input placeholder="09:00" /></Form.Item>
            <Form.Item name="days_of_week" label="星期（0=周一）">
              <Select mode="multiple" options={[0, 1, 2, 3, 4, 5, 6].map((d) => ({ value: d, label: String(d) }))} />
            </Form.Item>
            <Form.Item name="aircraft_type_id" label="机型（可选）">
              <Select allowClear options={types.map((t) => ({ value: t.id, label: `${t.icao} ${t.variant}` }))} />
            </Form.Item>
            <Form.Item name="turn_minutes" label="过站分钟"><InputNumber style={{ width: "100%" }} min={20} /></Form.Item>
          </div>
        </Form>
      </Modal>

      <Modal title="CSV 导入班期" open={importOpen} onCancel={() => setImportOpen(false)}
        onOk={doImport} width={680} okText="开始导入">
        <Alert type="info" showIcon style={{ marginBottom: 10 }}
          message="表头：flight_number,dep,arr,dep_local,days（days 为 0–6，逗号分隔）" />
        <Input.TextArea rows={10} value={csv} onChange={(e) => setCsv(e.target.value)}
          style={{ fontFamily: "Cascadia Code, Consolas, monospace", fontSize: 12 }} />
        {importResult ? (
          <Alert style={{ marginTop: 10 }} type={importResult.errors.length ? "warning" : "success"} showIcon
            message={`成功 ${importResult.imported} 条，失败 ${importResult.errors.length} 条`}
            description={importResult.errors.map((e) => `第 ${e.line} 行：${e.message}`).join("；")} />
        ) : null}
      </Modal>
    </Card>
  );
}
