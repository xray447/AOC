import { PlayCircleOutlined, ReloadOutlined, ThunderboltOutlined } from "@ant-design/icons";
import {
  Alert, Button, Card, Col, Descriptions, Divider, Empty, Form, InputNumber, Popconfirm, Progress,
  Row, Select, Space, Switch, Table, Tag, Typography, message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { AirportSelect } from "../../components/AirportSelect";
import { SimBriefButton } from "../../components/SimBriefButton";
import { useI18n } from "../../i18n";
import { fmtBlock, fmtUtc, legStatus, money, rosterStatus } from "../../ops";
import type { OpsAircraftType, OpsCandidate, OpsDrawResult, OpsRoster } from "../../types";

const { Text } = Typography;

const DEFAULTS = {
  window_hours: 24,
  max_legs: 3,
  max_block_minutes: 480,
  min_turnaround_min: 45,
  max_turnaround_min: 360,
  prefer_new_airports: true,
  aircraft_type_id: undefined as string | undefined,
  base_airport: undefined as string | undefined,
};

export function OpsRosterPage({ embedded = false }: { embedded?: boolean }) {
  const { tr } = useI18n();
  const navigate = useNavigate();
  const [roster, setRoster] = useState<OpsRoster | null>(null);
  const [draw, setDraw] = useState<OpsDrawResult | null>(null);
  const [types, setTypes] = useState<OpsAircraftType[]>([]);
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm<typeof DEFAULTS>();

  const load = useCallback(async () => {
    const [r, t] = await Promise.all([
      api<OpsRoster>("/local/ops/rosters/current"),
      api<{ items: OpsAircraftType[] }>("/local/ops/aircraft-types"),
    ]);
    setRoster(r && r.id ? r : null);
    setTypes(t.items.filter((x) => x.allow_scheduled));
  }, []);

  useEffect(() => { void load().catch((e: Error) => message.error(e.message)); }, [load]);

  const runDraw = async (redraw = false) => {
    const values = await form.validateFields();
    setBusy(true);
    try {
      const path = redraw && roster ? `/local/ops/rosters/${roster.id}/redraw` : "/local/ops/rosters/draw";
      const result = await api<OpsDrawResult>(path, {
        method: "POST",
        body: redraw ? undefined : JSON.stringify(values),
      });
      setDraw(result);
      await load();
      if (!result.candidates.length) {
        message.warning(tr("没有满足条件的候选，试试放宽航段数/窗口或调整过站时间",
          "No candidates — relax legs, window or turnaround limits"));
      }
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (candidate: OpsCandidate, index: number) => {
    setBusy(true);
    try {
      const created = await api<OpsRoster>("/local/ops/rosters/confirm", {
        method: "POST",
        body: JSON.stringify({ candidate_token: candidate.candidate_token, candidate_index: index }),
      });
      setDraw(null);
      setRoster(created);
      message.success(tr("班表已锁定，飞机已占用", "Roster locked and aircraft held"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const startLeg = async (sequence: number) => {
    if (!roster) return;
    setBusy(true);
    try {
      await api(`/local/ops/rosters/${roster.id}/legs/${sequence}/start`, { method: "POST" });
      message.success(tr("航段已开始，配载已固化", "Leg started, load sheet frozen"));
      navigate("/ops/execute");
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!roster) return;
    setBusy(true);
    try {
      await api(`/local/ops/rosters/${roster.id}/cancel`, {
        method: "POST", body: JSON.stringify({ reason: "本机取消" }),
      });
      await load();
      message.success(tr("班表已取消", "Roster cancelled"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const nextLeg = roster?.legs.find((l) => l.status === "PLANNED");
  const completed = roster ? roster.legs.filter((l) => l.status === "COMPLETED").length : 0;

  return (
    <div className={embedded ? "ops-embedded" : "page"}>
      {embedded ? null : (
        <div className="page-head">
          <div>
            <h2>{tr("抽班与执行", "Draw & fly")}</h2>
            <p>{tr("硬约束：飞机当前位置 = 首段出发、航段连续、机型匹配；软约束可随时调整。", "Hard constraints: aircraft position = first departure, leg continuity, type match. Soft constraints are yours to tune.")}</p>
          </div>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void load()}>{tr("刷新", "Refresh")}</Button>
            {roster?.status === "LOCKED" ? (
              <Button loading={busy} onClick={() => void runDraw(true)}>{tr("重抽", "Redraw")}</Button>
            ) : null}
          </Space>
        </div>
      )}

      {roster ? (
        <Card
          className="panel"
          variant="borderless"
          title={
            <Space>
              {tr("当前班表", "Current roster")}
              <Tag color={rosterStatus[roster.status]?.color}>
                {rosterStatus[roster.status] ? tr(rosterStatus[roster.status].zh, rosterStatus[roster.status].en) : roster.status}
              </Tag>
            </Space>
          }
          extra={(
            <Space>
              {roster.status === "LOCKED" || roster.status === "IN_PROGRESS" ? (
                <Popconfirm
                  title={tr("取消班表会释放飞机，首段后取消收 $5,000", "Cancel releases the aircraft; after first leg a $5,000 fee applies")}
                  onConfirm={() => void cancel()}
                >
                  <Button danger size="small">{tr("取消班表", "Cancel roster")}</Button>
                </Popconfirm>
              ) : null}
            </Space>
          )}
        >
          <Descriptions size="small" column={3}>
            <Descriptions.Item label={tr("飞机", "Aircraft")}>
              {roster.aircraft.registration} · {roster.aircraft.type}
              {roster.aircraft.variant && roster.aircraft.variant !== "STANDARD" ? ` ${roster.aircraft.variant}` : ""}
            </Descriptions.Item>
            <Descriptions.Item label={tr("当前位置", "Position")}>{roster.aircraft.current_airport_icao || "—"}</Descriptions.Item>
            <Descriptions.Item label={tr("进度", "Progress")}>
              {completed}/{roster.legs.length}
            </Descriptions.Item>
            <Descriptions.Item label={tr("窗口", "Window")} span={2}>
              {fmtUtc(roster.locked_at)} → {fmtUtc(roster.expires_at)}
            </Descriptions.Item>
            <Descriptions.Item label={tr("约束", "Constraints")}>
              {tr("最多", "max")} {String(roster.constraints.max_legs ?? "—")} {tr("段 · 总航时", "legs · block")} {String(roster.constraints.max_block_minutes ?? "—")}min
            </Descriptions.Item>
          </Descriptions>
          <Progress percent={Math.round((completed / Math.max(1, roster.legs.length)) * 100)} size="small" />
          <Table
            rowKey="id"
            size="small"
            style={{ marginTop: 12 }}
            pagination={false}
            dataSource={roster.legs}
            columns={[
              { title: "#", dataIndex: "sequence", width: 42 },
              {
                title: tr("航班", "Flight"), key: "callsign", width: 100,
                render: (_: unknown, l) => <strong className="mono">{l.callsign || "—"}</strong>,
              },
              {
                title: tr("航段", "Leg"), key: "leg",
                render: (_: unknown, l) => `${l.dep_icao || "—"} → ${l.arr_icao || "—"}`,
              },
              { title: tr("计划起飞 (UTC)", "ETD"), dataIndex: "planned_dep_utc", render: (v: string) => <span className="mono">{fmtUtc(v)}</span> },
              { title: tr("计划到达", "ETA"), dataIndex: "planned_arr_utc", render: (v: string) => <span className="mono">{fmtUtc(v)}</span> },
              {
                title: tr("状态", "Status"), dataIndex: "status", width: 100,
                render: (v: string) => <Tag color={legStatus[v]?.color}>{legStatus[v] ? tr(legStatus[v].zh, legStatus[v].en) : v}</Tag>,
              },
              {
                title: "", key: "act", width: 230,
                render: (_: unknown, l) => (
                  l.status === "PLANNED" && nextLeg?.id === l.id ? (
                    <Space size={6}>
                      <SimBriefButton
                        size="small"
                        dep={l.dep_icao}
                        arr={l.arr_icao}
                        aircraftType={roster.aircraft.type}
                        callsign={l.callsign}
                        opsLeg={{ rosterId: roster.id, sequence: l.sequence }}
                      />
                      <Button size="small" type="primary" icon={<PlayCircleOutlined />} loading={busy}
                        onClick={() => void startLeg(l.sequence)}>
                        {tr("开始本段", "Start leg")}
                      </Button>
                    </Space>
                  ) : null
                ),
              },
            ]}
          />
          {roster.status === "IN_PROGRESS" && nextLeg ? (
            <Alert
              style={{ marginTop: 12 }}
              type="info"
              showIcon
              message={tr("班表不会自动过期", "Rosters never expire after the first leg")}
              description={tr("等多久都可以继续下一段：只要还有未完成航段，班表保持执行中。", "Take as long as you like — the roster stays in progress until all legs are done or you cancel.")}
            />
          ) : null}
        </Card>
      ) : null}

      <Row gutter={16} style={{ marginTop: roster ? 16 : 0 }}>
        <Col xs={24} lg={9}>
          <Card className="panel" variant="borderless" title={tr("抽班条件（软约束）", "Draw constraints (soft)")}>
            <Form form={form} layout="vertical" initialValues={DEFAULTS}>
              <Row gutter={12}>
                <Col span={12}>
                  <Form.Item name="aircraft_type_id" label={tr("机型", "Aircraft type")}>
                    <Select allowClear placeholder={tr("任意", "Any")} options={types.map((t) => ({
                      value: t.id, label: `${t.icao}${t.variant !== "STANDARD" ? ` ${t.variant}` : ""}`,
                    }))} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="base_airport" label={tr("基地/出发机场", "Base / departure")}>
                    <AirportSelect allowClear placeholder={tr("任意", "Any")} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="window_hours" label={tr("窗口（小时）", "Window (h)")}>
                    <InputNumber min={1} max={168} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="max_legs" label={tr("最大航段数", "Max legs")}>
                    <InputNumber min={1} max={8} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="max_block_minutes" label={tr("总飞行时间（min）", "Total block (min)")}>
                    <InputNumber min={30} max={1440} step={30} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="min_turnaround_min" label={tr("最小过站（min）", "Min turnaround")}>
                    <InputNumber min={15} max={240} step={5} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="max_turnaround_min" label={tr("最大过站（min）", "Max turnaround")}>
                    <InputNumber min={30} max={1440} step={15} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="prefer_new_airports" label={tr("优先未飞机场", "Prefer new airports")} valuePropName="checked">
                    <Switch />
                  </Form.Item>
                </Col>
              </Row>
              <Button type="primary" block icon={<ThunderboltOutlined />} loading={busy} onClick={() => void runDraw(false)}>
                {roster && roster.status === "LOCKED" ? tr("先取消/重抽再抽新班", "Redraw current roster") : tr("抽班", "Draw")}
              </Button>
              <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                {tr("重抽无冷却/费用/次数限制；首段开始后不可重抽。", "Redraws are free and unlimited before the first leg; locked once the first leg starts.")}
              </div>
            </Form>
          </Card>
        </Col>
        <Col xs={24} lg={15}>
          <Card className="panel" variant="borderless" title={tr("候选", "Candidates")}
            extra={draw ? <Text type="secondary">{tr("共评估", "considered")} {draw.considered}</Text> : null}>
            {draw?.candidates.length ? (
              <Space direction="vertical" size={12} style={{ width: "100%" }}>
                {draw.candidates.map((candidate, index) => (
                  <Card key={`${candidate.aircraft.id}-${index}`} size="small" className="panel"
                    title={(
                      <Space wrap>
                        <strong>{candidate.aircraft.registration}</strong>
                        <span className="muted">{candidate.aircraft.type}
                          {candidate.aircraft.variant !== "STANDARD" ? ` ${candidate.aircraft.variant}` : ""}</span>
                        <Tag color="blue">{candidate.legs.length} {tr("段", "legs")}</Tag>
                        <Tag>{fmtBlock(candidate.total_block_minutes)}</Tag>
                        <Tag>{Math.round(candidate.total_distance_nm)} NM</Tag>
                      </Space>
                    )}
                    extra={(
                      <Space size={6}>
                        <SimBriefButton
                          size="small"
                          dep={candidate.legs[0]?.dep}
                          arr={candidate.legs[0]?.arr}
                          aircraftType={candidate.aircraft.type}
                          callsign={candidate.legs[0]?.callsign}
                        />
                        <Button type="primary" size="small" loading={busy} onClick={() => void confirm(candidate, index)}>
                          {tr("确认这个班", "Take it")}
                        </Button>
                      </Space>
                    )}>
                    <Table
                      rowKey="flight_instance_id"
                      size="small"
                      pagination={false}
                      dataSource={candidate.legs}
                      columns={[
                        {
                          title: tr("航班", "Flight"), key: "callsign", width: 100,
                          render: (_: unknown, l) => <span className="mono">{l.callsign || l.flight_number}</span>,
                        },
                        { title: tr("航段", "Leg"), key: "leg", render: (_: unknown, l) => `${l.dep} → ${l.arr}` },
                        { title: tr("起飞 (UTC)", "ETD"), dataIndex: "scheduled_dep_utc", render: (v: string) => <span className="mono">{fmtUtc(v)}</span> },
                        { title: tr("航时", "Block"), dataIndex: "block_minutes", width: 80, render: (v: number) => fmtBlock(v) },
                      ]}
                    />
                    <Divider style={{ margin: "8px 0" }} />
                    <Space wrap size={16}>
                      <Text>{tr("预计收入", "Revenue")} <strong>{money(candidate.estimated_revenue)}</strong></Text>
                      <Text>{tr("预计利润", "Profit")} <Text type={candidate.estimated_profit >= 0 ? "success" : "danger"}>{money(candidate.estimated_profit)}</Text></Text>
                      <Text type="secondary">{tr("评分", "Score")} {candidate.score.toFixed(3)}</Text>
                    </Space>
                    <div style={{ marginTop: 6 }}>
                      {candidate.reasons.map((reason) => <Tag key={reason} color="geekblue">{reason}</Tag>)}
                    </div>
                  </Card>
                ))}
              </Space>
            ) : (
              <Empty description={tr("设置条件后点「抽班」", "Set constraints and draw")} />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
