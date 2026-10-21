import { CarOutlined, PlayCircleOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  Alert, Button, Card, Col, Descriptions, Empty, Form, Popconfirm, Row, Select, Space, Table, Tag, message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { AirportSelect } from "../../components/AirportSelect";
import { SimBriefButton } from "../../components/SimBriefButton";
import { useI18n } from "../../i18n";
import { aircraftStatus, fmtUtc } from "../../ops";
import type { OpsAircraft, OpsFreeFlight, OpsProfile } from "../../types";

interface FreeForm {
  dep_icao: string;
  arr_icao: string;
  aircraft_id?: string;
}

export function OpsFreeFlightPage({ embedded = false }: { embedded?: boolean }) {
  const { tr } = useI18n();
  const navigate = useNavigate();
  const [aircraft, setAircraft] = useState<OpsAircraft[]>([]);
  const [current, setCurrent] = useState<OpsFreeFlight | null>(null);
  const [profile, setProfile] = useState<OpsProfile | null>(null);
  const [dep, setDep] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm<FreeForm>();

  const loadAircraft = useCallback(async (airport: string) => {
    const res = await api<{ items: OpsAircraft[] }>(
      `/local/ops/free-flights/aircraft${airport ? `?dep=${encodeURIComponent(airport)}` : ""}`);
    setAircraft(res.items);
  }, []);

  const load = useCallback(async () => {
    const [p, cur] = await Promise.all([
      api<OpsProfile>("/local/ops/profile"),
      api<OpsFreeFlight>("/local/ops/free-flights/current"),
    ]);
    setProfile(p);
    setCurrent(cur && cur.id ? cur : null);
    const start = dep || p.base_airport_icao || "";
    if (!dep) {
      setDep(start);
      form.setFieldValue("dep_icao", start);
    }
    await loadAircraft(start);
  }, [dep, form, loadAircraft]);

  useEffect(() => { void load().catch((e: Error) => message.error(e.message)); }, [load]);

  const changeDep = async (value: string) => {
    setDep(value);
    form.setFieldsValue({ dep_icao: value, aircraft_id: undefined });
    try {
      await loadAircraft(value);
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const create = async () => {
    const values = await form.validateFields();
    if (!values.aircraft_id) {
      message.warning(tr("请选择一架位于出发机场的飞机", "Pick an aircraft located at the departure airport"));
      return;
    }
    setBusy(true);
    try {
      await api("/local/ops/free-flights", { method: "POST", body: JSON.stringify(values) });
      await load();
      message.success(tr("已锁定飞机（30 分钟）", "Aircraft locked for 30 minutes"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (!current) return;
    setBusy(true);
    try {
      await api(`/local/ops/free-flights/${current.id}/start`, { method: "POST" });
      message.success(tr("任务已开始，配载已固化", "Task started, load sheet frozen"));
      navigate("/ops/execute");
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!current) return;
    try {
      await api(`/local/ops/free-flights/${current.id}/cancel`, { method: "POST" });
      await load();
      message.success(tr("已释放", "Released"));
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const heartbeat = async () => {
    if (!current) return;
    try {
      await api(`/local/ops/free-flights/${current.id}/heartbeat`, { method: "POST" });
      await load();
      message.success(tr("锁已续期 30 分钟", "Lock renewed"));
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  return (
    <div className={embedded ? "ops-embedded" : "page"}>
      {embedded ? null : (
        <div className="page-head">
          <div>
            <h2>{tr("自由飞行", "Free flight")}</h2>
            <p>{tr("不抽班表，直接从飞机当前机场起飞；必须满足位置、航程与跑道约束。", "Skip the roster: depart from the aircraft's current airport, subject to position, range and runway limits.")}</p>
          </div>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>{tr("刷新", "Refresh")}</Button>
        </div>
      )}

      {current ? (
        <Card className="panel" variant="borderless" title={tr("当前自由飞任务", "Active free flight")}
          extra={<Tag color="cyan">{current.status}</Tag>}>
          <Descriptions size="small" column={3}>
            <Descriptions.Item label={tr("呼号", "Callsign")}>
              <span className="mono">{current.callsign || "—"}</span>
            </Descriptions.Item>
            <Descriptions.Item label={tr("飞机", "Aircraft")}>{current.aircraft?.registration || "—"} · {current.aircraft?.type_icao || ""}</Descriptions.Item>
            <Descriptions.Item label={tr("航段", "Leg")}>{current.dep_icao} → {current.arr_icao}</Descriptions.Item>
            <Descriptions.Item label={tr("锁到期", "Lock expires")}>{fmtUtc(current.lock_expires_at)}</Descriptions.Item>
          </Descriptions>
          <Space style={{ marginTop: 8 }} wrap>
            <SimBriefButton
              dep={current.dep_icao}
              arr={current.arr_icao}
              aircraftType={current.aircraft?.type_icao}
              callsign={current.callsign}
              opsLeg={{ freeId: current.id }}
            />
            <Button type="primary" icon={<PlayCircleOutlined />} loading={busy} onClick={() => void start()}>
              {tr("开始飞行", "Start")}
            </Button>
            {current.status === "LOCKED" ? (
              <>
                <Button onClick={() => void heartbeat()}>{tr("续期锁", "Renew lock")}</Button>
                <Popconfirm title={tr("释放飞机？", "Release the aircraft?")} onConfirm={() => void cancel()}>
                  <Button danger>{tr("取消任务", "Cancel")}</Button>
                </Popconfirm>
              </>
            ) : null}
          </Space>
        </Card>
      ) : (
        <Row gutter={16}>
          <Col xs={24} lg={10}>
            <Card className="panel" variant="borderless" title={tr("领取飞机", "Claim aircraft")}>
              <Form form={form} layout="vertical" initialValues={{ dep_icao: profile?.base_airport_icao || "" }}>
                <Form.Item name="dep_icao" label={tr("出发机场（= 飞机当前位置）", "Departure (= aircraft position)")} rules={[{ required: true }]}>
                  <AirportSelect onChange={(v) => void changeDep(v)} placeholder="ZBAA" />
                </Form.Item>
                <Form.Item name="aircraft_id" label={tr("飞机", "Aircraft")}>
                  <Select
                    placeholder={aircraft.length ? tr("选择飞机", "Select") : tr("该机场没有可用飞机", "No aircraft at this airport")}
                    options={aircraft.map((a) => ({
                      value: a.id,
                      label: `${a.registration} · ${a.type_icao || ""}${a.type_variant && a.type_variant !== "STANDARD" ? ` ${a.type_variant}` : ""} · ${a.type_role || ""}`,
                    }))}
                  />
                </Form.Item>
                <Form.Item name="arr_icao" label={tr("到达机场", "Arrival")} rules={[{ required: true }]}>
                  <AirportSelect placeholder="ZSSS" />
                </Form.Item>
                <Button type="primary" block icon={<CarOutlined />} loading={busy} onClick={() => void create()}>
                  {tr("锁定飞机（30 分钟）", "Lock aircraft (30 min)")}
                </Button>
              </Form>
              <Alert
                style={{ marginTop: 12 }}
                type="info"
                showIcon
                message={tr("飞机必须在出发机场", "Aircraft must be at the departure airport")}
                description={tr("不在本场的飞机需先调机；航程按机型的 90% 计算。", "Aircraft elsewhere must be ferried first; range is capped at 90% of the type's range.")}
              />
            </Card>
          </Col>
          <Col xs={24} lg={14}>
            <Card className="panel" variant="borderless" title={`${tr("可用飞机", "Available aircraft")} · ${dep || "—"}`}
              styles={{ body: { padding: 0 } }}>
              {aircraft.length ? (
                <Table
                  rowKey="id"
                  size="small"
                  pagination={false}
                  dataSource={aircraft}
                  columns={[
                    { title: tr("注册号", "Registration"), dataIndex: "registration", width: 110, render: (v: string) => <strong>{v}</strong> },
                    { title: tr("机型", "Type"), key: "type", render: (_: unknown, r: OpsAircraft) => `${r.type_icao || ""}${r.type_variant && r.type_variant !== "STANDARD" ? ` ${r.type_variant}` : ""}` },
                    { title: tr("角色", "Role"), dataIndex: "type_role", width: 90 },
                    { title: tr("座位", "Seats"), dataIndex: "pax_capacity", width: 70 },
                    {
                      title: tr("状态", "Status"), dataIndex: "status", width: 90,
                      render: (v: string) => <Tag color={aircraftStatus[v]?.color}>{v}</Tag>,
                    },
                  ]}
                />
              ) : (
                <Empty style={{ padding: 24 }} description={tr("该机场没有可用飞机（检查机队或先调机）", "No available aircraft here")} />
              )}
            </Card>
          </Col>
        </Row>
      )}
    </div>
  );
}
