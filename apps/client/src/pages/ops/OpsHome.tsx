import {
  ArrowRightOutlined,
  CarOutlined,
  ProfileOutlined,
  ReloadOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Alert, Button, Card, Descriptions, Empty, Form, Input, Modal, Space, Table, Tag, Typography, message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api";
import { MetricCard } from "../../components/MetricCard";
import { useApp } from "../../context";
import { useI18n } from "../../i18n";
import {
  fmtUtc, money, opsStateMeta, policyAction, rosterStatus, settlementStatus, settlementTitle,
} from "../../ops";
import type { OpsDashboard, OpsProfile, OpsSettlement } from "../../types";

const { Text } = Typography;

/** 前缀示例：按输入实时联动（大写、字母数字、最多 4 位），与后端 _clean_prefix 一致。 */
function prefixPair(value: unknown, digits: string, fallback: string): { prefix: string; sample: string } {
  const cleaned = String(value ?? "").replace(/[^A-Za-z0-9]/g, "").toUpperCase().slice(0, 4);
  const prefix = cleaned || fallback;
  return { prefix, sample: `${prefix}${digits}` };
}

export function OpsHome() {
  const { tr } = useI18n();
  const navigate = useNavigate();
  const { opsStatus } = useApp();
  const statusMeta = opsStateMeta(opsStatus);
  const [data, setData] = useState<OpsDashboard | null>(null);
  const [settlements, setSettlements] = useState<OpsSettlement[]>([]);
  const [profileOpen, setProfileOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm<OpsProfile>();
  const callsignPrefix = Form.useWatch("callsign_prefix", form) as string | undefined;
  const flightPrefix = Form.useWatch("flight_prefix", form) as string | undefined;
  // 弹窗里的示例跟着输入实时变化（清空则回退到默认 AUV / AOC）
  const liveCallsign = prefixPair(callsignPrefix, "123", "AUV");
  const liveFlight = prefixPair(flightPrefix, "101", "AOC");

  const load = useCallback(async () => {
    const [dash, st] = await Promise.all([
      api<OpsDashboard>("/local/ops/dashboard"),
      api<{ items: OpsSettlement[] }>("/local/ops/settlements?limit=6"),
    ]);
    setData(dash);
    setSettlements(st.items);
  }, []);

  useEffect(() => { void load().catch((e: Error) => message.error(e.message)); }, [load]);

  const seed = async () => {
    setBusy(true);
    try {
      await api("/local/ops/seed", { method: "POST" });
      await load();
      message.success(tr("演示机队与班期已生成", "Demo fleet and schedules created"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const openProfile = (profile: OpsProfile) => {
    form.setFieldsValue(profile);
    setProfileOpen(true);
  };

  const saveProfile = async () => {
    const values = await form.validateFields();
    try {
      await api("/local/ops/profile", { method: "PUT", body: JSON.stringify(values) });
      setProfileOpen(false);
      await load();
      message.success(tr("本机档案已保存", "Profile saved"));
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  if (!data) return <div className="page"><Card loading /></div>;
  const profile = data.profile;
  const roster = data.active_roster;
  const callsignSample = prefixPair(profile.callsign_prefix, "123", "AUV");
  const flightSample = prefixPair(profile.flight_prefix, "101", "AOC");

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("运营中心", "Operations")}</h2>
          <p>{tr("单机运营模式：机队、班表、配载、结算与账本都在本机完成，无需联网。", "Single-player operations: fleet, rosters, load sheets, settlement and ledger stay local — no server, no login.")}</p>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>{tr("刷新", "Refresh")}</Button>
      </div>

      <Card
        className="panel"
        variant="borderless"
        size="small"
        title={(
          <Space>
            <ProfileOutlined />
            {tr("本机档案", "Profile")}
            <span className="muted" style={{ fontWeight: 400 }}>{profile.name}</span>
          </Space>
        )}
        extra={(
          <Button icon={<SettingOutlined />} onClick={() => openProfile(profile)}>
            {tr("设置", "Settings")}
          </Button>
        )}
      >
        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }}>
          <Descriptions.Item label={tr("ICAO 代码", "ICAO code")}>
            <span className="mono">{profile.icao_code || "—"}</span>
          </Descriptions.Item>
          <Descriptions.Item label={tr("基地机场", "Base")}>
            <span className="mono">{profile.base_airport_icao || "—"}</span>
          </Descriptions.Item>
          <Descriptions.Item label={tr("货币", "Currency")}>{profile.currency}</Descriptions.Item>
          <Descriptions.Item label={tr("自由飞呼号前缀", "Free-flight callsign prefix")}>
            <span className="mono">
              {callsignSample.prefix} → {callsignSample.sample}
            </span>
          </Descriptions.Item>
          <Descriptions.Item label={tr("抽班航班号前缀", "Scheduled flight prefix")}>
            <span className="mono">
              {flightSample.prefix} → {flightSample.sample}
            </span>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {data.fleet.total === 0 ? (
        <Alert
          type="info"
          showIcon
          message={tr("还没有飞机", "No aircraft yet")}
          description={tr("先建一架飞机与航线/班期，或在演示数据上快速体验。", "Add an aircraft plus routes/schedules, or start from demo data.")}
          action={<Button type="primary" loading={busy} onClick={() => void seed()}>{tr("生成演示数据", "Load demo")}</Button>}
        />
      ) : null}

      <div className="metric-grid">
        <Card
          size="small"
          variant="borderless"
          className="metric-card"
          style={{ cursor: "pointer" }}
          onClick={() => navigate(statusMeta.path)}
        >
          <div className="muted">{tr("当前状态", "Current state")}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
            <Tag color={statusMeta.color} style={{ margin: 0 }}>
              {tr(statusMeta.zh, statusMeta.en)}
            </Tag>
            <span className="mono">{opsStatus?.callsign || ""}</span>
          </div>
          <div className="metric-extra">
            {opsStatus?.dep_icao && opsStatus?.arr_icao
              ? `${opsStatus.dep_icao} → ${opsStatus.arr_icao} · `
              : ""}
            {tr("点击进入", "Click to open")}
          </div>
        </Card>
        <MetricCard title={tr("账户余额", "Balance")} value={money(profile.balance, profile.currency)} />
        <MetricCard title={tr("今日利润", "Today profit")} value={money(data.today.profit)}
          color={data.today.profit >= 0 ? "#22c55e" : "#ef4444"}
          extra={`${data.today.settlements} ${tr("个结算", "settlements")}`} />
        <MetricCard title={tr("机队", "Fleet")} value={data.fleet.total}
          extra={`${data.fleet.active} ${tr("可用", "active")} · ${data.fleet.held + data.fleet.in_flight} ${tr("占用", "busy")}`} />
        <MetricCard title={tr("待复核", "Review")} value={data.review_count}
          color={data.review_count ? "#f59e0b" : undefined}
          extra={<Link to="/ops/review">{tr("复核队列", "Review queue")}</Link>} />
        <MetricCard title={tr("可抽航班", "Scheduled")} value={data.scheduled_instances}
          extra={`${tr("配置版本", "config")} v${data.config_version}`} />
        <MetricCard title={tr("失约", "No-show")} value={data.no_show_count} />
      </div>

      <Card
        className="panel"
        variant="borderless"
        title={roster ? tr("当前班表", "Current roster") : tr("当前任务", "Active task")}
        extra={<Link to="/ops/roster">{tr("抽班 / 执行", "Draw & fly")} <ArrowRightOutlined /></Link>}
      >
        {roster ? (
          <>
            <Descriptions size="small" column={2}>
              <Descriptions.Item label={tr("飞机", "Aircraft")}>{roster.aircraft.registration} · {roster.aircraft.type}</Descriptions.Item>
              <Descriptions.Item label={tr("状态", "Status")}>
                <Tag color={rosterStatus[roster.status]?.color}>
                  {rosterStatus[roster.status] ? tr(rosterStatus[roster.status].zh, rosterStatus[roster.status].en) : roster.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label={tr("窗口", "Window")} span={2}>
                {fmtUtc(roster.window_start_utc)} → {fmtUtc(roster.window_end_utc)}
              </Descriptions.Item>
            </Descriptions>
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={roster.legs}
              columns={[
                { title: "#", dataIndex: "sequence", width: 42 },
                { title: tr("航班", "Flight"), key: "f", render: (_: unknown, l) => `${l.dep_icao ?? "—"} → ${l.arr_icao ?? "—"}` },
                { title: tr("计划起飞", "ETD"), dataIndex: "planned_dep_utc", render: (v: string) => <span className="mono">{fmtUtc(v)}</span> },
                { title: tr("状态", "Status"), dataIndex: "status", width: 90, render: (v: string) => <Tag>{v}</Tag> },
              ]}
            />
            <Space style={{ marginTop: 12 }}>
              <Button type="primary" onClick={() => navigate("/ops/roster")}>{tr("去执行", "Open roster")}</Button>
              <Button onClick={() => navigate("/ops/execute")}>{tr("配载与记录", "Load sheet")}</Button>
            </Space>
          </>
        ) : data.active_free_flight ? (
          <>
            <Descriptions size="small" column={2}>
              <Descriptions.Item label={tr("自由飞", "Free flight")}>
                {data.active_free_flight.dep_icao} → {data.active_free_flight.arr_icao}
              </Descriptions.Item>
              <Descriptions.Item label={tr("飞机", "Aircraft")}>
                {data.active_free_flight.aircraft?.registration || "—"}
              </Descriptions.Item>
              <Descriptions.Item label={tr("锁到期", "Lock expires")} span={2}>
                {fmtUtc(data.active_free_flight.lock_expires_at)}
              </Descriptions.Item>
            </Descriptions>
            <Space>
              <Button type="primary" onClick={() => navigate("/ops/free")}>{tr("继续自由飞", "Continue")}</Button>
              <Button onClick={() => navigate("/ops/execute")}>{tr("配载与记录", "Load sheet")}</Button>
            </Space>
          </>
        ) : (
          <Empty description={tr("没有进行中的班表或自由飞", "No active roster or free flight")}>
            <Space>
              <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => navigate("/ops/roster")}>
                {tr("抽一个班表", "Draw a roster")}
              </Button>
              <Button icon={<CarOutlined />} onClick={() => navigate("/ops/free")}>{tr("自由飞行", "Free flight")}</Button>
            </Space>
          </Empty>
        )}
      </Card>

      <Card
        className="panel"
        variant="borderless"
        title={tr("最近结算", "Recent settlements")}
        extra={<Link to="/ops/settlements">{tr("全部", "All")} <ArrowRightOutlined /></Link>}
        styles={{ body: { padding: 0 } }}
      >
        {settlements.length ? (
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={settlements}
            columns={[
              { title: tr("航班", "Flight"), key: "t", render: (_: unknown, r: OpsSettlement) => <Link to={`/ops/settlements?focus=${r.id}`}>{settlementTitle(r)}</Link> },
              { title: tr("结算时间", "Settled"), dataIndex: "computed_at", render: (v: string) => <span className="mono">{fmtUtc(v)}</span> },
              { title: tr("收入", "Revenue"), dataIndex: "revenue_total", render: (v: number) => money(v) },
              { title: tr("成本", "Cost"), dataIndex: "cost_total", render: (v: number) => money(v) },
              {
                title: tr("利润", "Profit"), dataIndex: "profit",
                render: (v: number) => <Text type={v >= 0 ? "success" : "danger"}>{money(v)}</Text>,
              },
              {
                title: tr("策略", "Policy"), dataIndex: "policy_action",
                render: (v: string) => <Tag color={policyAction[v]?.color}>{policyAction[v] ? tr(policyAction[v].zh, policyAction[v].en) : v}</Tag>,
              },
              {
                title: tr("状态", "Status"), dataIndex: "status",
                render: (v: string) => <Tag color={settlementStatus[v]?.color}>{settlementStatus[v] ? tr(settlementStatus[v].zh, settlementStatus[v].en) : v}</Tag>,
              },
            ]}
          />
        ) : (
          <Empty style={{ padding: 24 }} description={tr("还没有结算记录", "No settlements yet")} />
        )}
      </Card>

      <Modal
        open={profileOpen}
        title={tr("本机档案", "Local profile")}
        onCancel={() => setProfileOpen(false)}
        onOk={() => void saveProfile()}
        okText={tr("保存", "Save")}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label={tr("航司名称", "Airline name")} rules={[{ required: true }]}>
            <Input maxLength={40} />
          </Form.Item>
          <Form.Item name="icao_code" label={tr("ICAO 代码", "ICAO code")}><Input maxLength={4} /></Form.Item>
          <Form.Item
            name="callsign_prefix"
            label={tr("自由飞呼号前缀", "Free-flight callsign prefix")}
            extra={tr(
              `自由飞行用：${liveCallsign.prefix} → ${liveCallsign.sample}`,
              `Free flights use: ${liveCallsign.prefix} → ${liveCallsign.sample}`,
            )}
          >
            <Input maxLength={4} placeholder="AUV" />
          </Form.Item>
          <Form.Item
            name="flight_prefix"
            label={tr("抽班航班号前缀", "Scheduled flight-number prefix")}
            extra={tr(
              `抽班用：${liveFlight.prefix} → ${liveFlight.sample}；保存后同步改写班期与未开始的航班`,
              `Rosters use: ${liveFlight.prefix} → ${liveFlight.sample}; saving also renumbers schedules and open instances`,
            )}
          >
            <Input maxLength={4} placeholder="AOC" />
          </Form.Item>
          <Form.Item name="base_airport_icao" label={tr("基地机场", "Base airport")}><Input maxLength={4} placeholder="ZBAA" /></Form.Item>
          <Form.Item name="currency" label={tr("货币", "Currency")}><Input disabled /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
