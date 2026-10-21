import {
  CloudServerOutlined,
  DisconnectOutlined,
  ReloadOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import {
  Alert, Button, Card, Descriptions, Empty, Form, Input, Space, Table, Tag, message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import {
  OnlineError, loadOnline, loginOnline, logoutOnline, onlineCurrentRoster, onlineDraw,
  onlineFlights, onlineHealth, onlineRequest, onlineSync, onlineCursor, saveOnline,
  setOnlineCursor,
  type OnlineFlight, type OnlineRoster, type OnlineState,
} from "../online";
import { useI18n } from "../i18n";

interface SyncEvent {
  id: number;
  kind: string;
  entity: string | null;
  entity_id: string | null;
  created_at: string;
}

export function Online() {
  const { tr } = useI18n();
  const [state, setState] = useState<OnlineState | null>(() => loadOnline());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [health, setHealth] = useState<{ status: string; version: string } | null>(null);
  const [flights, setFlights] = useState<OnlineFlight[]>([]);
  const [roster, setRoster] = useState<OnlineRoster | null>(null);
  const [events, setEvents] = useState<SyncEvent[]>([]);
  const [lastSync, setLastSync] = useState<string>("");
  const [form] = Form.useForm();

  const refresh = useCallback(async (current: OnlineState) => {
    setBusy(true);
    setError("");
    try {
      const [flightsData, rosterData] = await Promise.all([
        onlineFlights(current),
        onlineCurrentRoster(current),
      ]);
      setFlights(flightsData);
      setRoster(rosterData);
      const sync = await onlineSync(current, onlineCursor());
      setOnlineCursor(sync.cursor);
      setLastSync(sync.server_time);
      setEvents((prev) => [...sync.events.slice(-20), ...prev].slice(0, 40));
      try {
        setHealth(await onlineHealth(current.server));
      } catch {
        setHealth(null);
      }
    } catch (err) {
      setError(err instanceof OnlineError ? err.message : "联机服务不可用");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (state) void refresh(state);
  }, [state, refresh]);

  const doLogin = async (values: { server: string; username: string; password: string }) => {
    setBusy(true);
    setError("");
    try {
      const next = await loginOnline(values.server.trim(), values.username.trim(), values.password);
      saveOnline(next);
      setState(next);
      message.success(`${next.company.name} · ${next.user.display_name}`);
    } catch (err) {
      setError(err instanceof OnlineError ? err.message : "登录失败");
    } finally {
      setBusy(false);
    }
  };

  const draw = async (flight: OnlineFlight) => {
    if (!state) return;
    setBusy(true);
    setError("");
    try {
      const next = await onlineDraw(state, flight.id);
      setRoster(next);
      message.success(tr(`已抽中 ${flight.flight_number}`, `Drawn ${flight.flight_number}`));
      await refresh(state);
    } catch (err) {
      setError(err instanceof OnlineError ? err.message : "抽班失败");
    } finally {
      setBusy(false);
    }
  };

  const sync = async () => {
    if (!state) return;
    try {
      const result = await onlineSync(state, onlineCursor());
      setOnlineCursor(result.cursor);
      setLastSync(result.server_time);
      setEvents((prev) => [...result.events.slice(-20), ...prev].slice(0, 40));
      message.success(tr(`同步 ${result.events.length} 条事件`, `Synced ${result.events.length} events`));
    } catch (err) {
      setError(err instanceof OnlineError ? err.message : "同步失败");
    }
  };

  const heartbeat = async () => {
    if (!state || !roster) return;
    const lock = (roster as unknown as { lock?: { id: string } }).lock;
    if (!lock) {
      message.info(tr("当前任务没有活动锁", "No active lock"));
      return;
    }
    try {
      await onlineRequest(state, `/api/v1/locks/${lock.id}/heartbeat`, { method: "POST" });
      message.success(tr("锁心跳已续期", "Lock heartbeat refreshed"));
    } catch (err) {
      message.error(err instanceof OnlineError ? err.message : "心跳失败");
    }
  };

  const quit = async () => {
    if (!state) return;
    await logoutOnline(state);
    setState(null);
    setFlights([]);
    setRoster(null);
    setEvents([]);
    setHealth(null);
    message.success(tr("已退出联机模式", "Signed out"));
  };

  if (!state) {
    return (
      <div style={{ maxWidth: 560, margin: "0 auto" }}>
        <Card title={<Space><CloudServerOutlined />{tr("登录联机模式", "Sign in to online mode")}</Space>}>
          <Alert type="info" showIcon style={{ marginBottom: 16 }}
            message={tr("联机模式由公司服务端托管机队、班期、抽班与结算；个人模式与本机数据不受影响。",
              "Online mode is server-authoritative for fleet, schedule, roster and settlement.")} />
          {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}
          <Form form={form} layout="vertical" onFinish={doLogin}
            initialValues={{ server: "http://127.0.0.1:8080" }}>
            <Form.Item name="server" label={tr("服务端地址", "Server URL")} rules={[{ required: true }]}>
              <Input placeholder="http://127.0.0.1:8080" />
            </Form.Item>
            <Form.Item name="username" label={tr("用户名", "Username")} rules={[{ required: true }]}>
              <Input autoComplete="username" />
            </Form.Item>
            <Form.Item name="password" label={tr("密码", "Password")} rules={[{ required: true }]}>
              <Input.Password autoComplete="current-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={busy}>
              {tr("登录", "Sign in")}
            </Button>
          </Form>
          <div className="muted" style={{ marginTop: 12, fontSize: 12 }}>
            {tr("管理员在网页管理端创建账号或生成邀请码；飞行员在此登录。",
              "Admins create accounts in the web console; pilots sign in here.")}
          </div>
        </Card>
      </div>
    );
  }

  return (
    <Space direction="vertical" size={14} style={{ width: "100%" }}>
      {error ? <Alert type="error" showIcon message={error} closable onClose={() => setError("")} /> : null}
      <Card
        title={<Space><CloudServerOutlined />{state.company.name}
          <Tag color={health ? "green" : "default"}>{health ? `v${health.version}` : tr("离线", "offline")}</Tag>
        </Space>}
        extra={<Space>
          <Button icon={<SyncOutlined />} onClick={sync}>{tr("同步", "Sync")}</Button>
          <Button icon={<ReloadOutlined />} loading={busy} onClick={() => refresh(state)}>
            {tr("刷新", "Refresh")}
          </Button>
          <Button danger icon={<DisconnectOutlined />} onClick={quit}>{tr("退出", "Sign out")}</Button>
        </Space>}>
        <Descriptions size="small" column={4}>
          <Descriptions.Item label={tr("账号", "User")}>{state.user.display_name}</Descriptions.Item>
          <Descriptions.Item label={tr("角色", "Role")}><Tag>{state.user.role}</Tag></Descriptions.Item>
          <Descriptions.Item label={tr("公司余额", "Balance")}>
            {state.company.currency} {state.company.balance.toFixed(2)}
          </Descriptions.Item>
          <Descriptions.Item label={tr("上次同步", "Last sync")}>{lastSync || "—"}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title={tr("当前联机任务", "Current online roster")}
        extra={roster ? <Button size="small" onClick={heartbeat}>{tr("续期锁", "Heartbeat")}</Button> : null}>
        {!roster ? <Empty description={tr("未抽班", "No active roster")} /> : (
          <>
            <Descriptions size="small" column={3} style={{ marginBottom: 10 }}>
              <Descriptions.Item label={tr("飞机", "Aircraft")}>
                {roster.aircraft ? `${roster.aircraft.registration} (${roster.aircraft.type?.icao || "—"})` : "—"}
              </Descriptions.Item>
              <Descriptions.Item label={tr("状态", "Status")}><Tag color="blue">{roster.status}</Tag></Descriptions.Item>
              <Descriptions.Item label={tr("锁到期", "Lock expires")}>{roster.expires_at}</Descriptions.Item>
            </Descriptions>
            <Table size="small" rowKey="id" pagination={false} dataSource={roster.legs}
              columns={[
                { title: "#", dataIndex: "sequence", width: 50 },
                { title: tr("航班", "Flight"), dataIndex: "flight_number" },
                { title: tr("航段", "Route"), render: (_: unknown, row: OnlineFlight) => `${row.dep_icao} → ${row.arr_icao}` },
                { title: tr("计划起飞", "ETD"), dataIndex: "scheduled_dep_utc" },
                { title: tr("状态", "Status"), render: (_: unknown, row: OnlineFlight & { leg_status?: string }) => <Tag>{row.leg_status || "HELD"}</Tag> },
              ]} />
          </>
        )}
      </Card>

      <Card title={tr("可抽航班（服务端）", "Available flights (server)")}
        extra={<span className="muted" style={{ fontSize: 12 }}>
          {tr("抽班以服务端为准；同一飞机并发只有一个人成功。", "Server-authoritative roster; one winner per aircraft.")}
        </span>}>
        <Table size="small" rowKey="id" dataSource={flights} pagination={{ pageSize: 8 }}
          columns={[
            { title: tr("航班", "Flight"), dataIndex: "flight_number" },
            { title: tr("航段", "Route"), render: (_: unknown, row: OnlineFlight) => `${row.dep_icao} → ${row.arr_icao}` },
            { title: tr("距离", "Distance"), dataIndex: "distance_nm", render: (v: number) => `${Math.round(v)} NM` },
            { title: tr("计划起飞", "ETD"), dataIndex: "scheduled_dep_utc" },
            { title: "", width: 110, render: (_: unknown, row: OnlineFlight) => (
              <Button size="small" type="primary" disabled={!!roster || busy} onClick={() => draw(row)}>
                {tr("抽中", "Draw")}
              </Button>
            ) },
          ]} />
      </Card>

      <Card title={tr("同步事件", "Sync events")} extra={<span className="muted">cursor {onlineCursor()}</span>}>
        {events.length === 0 ? <Empty description={tr("暂无事件", "No events")} /> : (
          <Table size="small" rowKey="id" pagination={false} dataSource={events}
            columns={[
              { title: "#", dataIndex: "id", width: 70 },
              { title: tr("类型", "Kind"), dataIndex: "kind", render: (v: string) => <Tag>{v}</Tag> },
              { title: tr("对象", "Entity"), render: (_: unknown, row: SyncEvent) => `${row.entity || ""} ${row.entity_id || ""}` },
              { title: tr("时间", "Time"), dataIndex: "created_at" },
            ]} />
        )}
      </Card>
    </Space>
  );
}
