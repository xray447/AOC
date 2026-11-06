import { PlayCircleOutlined, ReloadOutlined, ThunderboltOutlined } from "@ant-design/icons";
import {
  Alert, Button, Card, Col, Descriptions, Divider, Empty, Form, InputNumber, Modal, Popconfirm,
  Progress, Row, Select, Space, Switch, Table, Tag, Typography, message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type ApiError } from "../../api";
import { AirportMultiSelect } from "../../components/AirportMultiSelect";
import { AirportSelect } from "../../components/AirportSelect";
import { SimBriefButton } from "../../components/SimBriefButton";
import { useApp } from "../../context";
import { useI18n } from "../../i18n";
import { fmtBlock, fmtUtc, legStatus, money, rosterStatus } from "../../ops";
import type { OpsAircraftType, OpsCandidate, OpsDrawResult, OpsRoster } from "../../types";

const { Text } = Typography;

const DEFAULTS = {
  window_hours: 24,
  max_legs: 3,
  // 合计航时（整条班表）与每程航时区间是两个维度，表单里分开标注
  max_block_minutes: 480,
  // 合计航时下限（§34）：留空按「上限 −25%」推导（480 → 360）
  min_total_block_minutes: undefined as number | undefined,
  min_leg_block_minutes: 30,
  max_leg_block_minutes: 480,
  min_turnaround_min: 45,
  max_turnaround_min: 360,
  prefer_new_airports: true,
  follow_routes: true,
  // 默认排除军用机场、按跑道宽度校验翼展（关掉回到旧行为）
  exclude_military: true,
  consider_wingspan: true,
  excluded_airports: [] as string[],
  aircraft_type_id: undefined as string | undefined,
  base_airport: undefined as string | undefined,
};

export function OpsRosterPage({ embedded = false }: { embedded?: boolean }) {
  const { tr } = useI18n();
  const navigate = useNavigate();
  const { recording, refreshKey } = useApp();
  const [roster, setRoster] = useState<OpsRoster | null>(null);
  const [draw, setDraw] = useState<OpsDrawResult | null>(null);
  const [types, setTypes] = useState<OpsAircraftType[]>([]);
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm<typeof DEFAULTS>();
  // 合计航时下限的默认值跟着上限走（留空 = 上限 −25%），表单里实时提示
  const maxBlockWatch = Form.useWatch("max_block_minutes", form) ?? DEFAULTS.max_block_minutes;
  const minTotalDefault = Math.max(30, Math.round(Number(maxBlockWatch) * 0.75));

  const load = useCallback(async () => {
    const [r, t] = await Promise.all([
      api<OpsRoster>("/local/ops/rosters/current"),
      api<{ items: OpsAircraftType[] }>("/local/ops/aircraft-types"),
    ]);
    setRoster(r && r.id ? r : null);
    setTypes(t.items.filter((x) => x.allow_scheduled));
  }, []);

  useEffect(() => { void load().catch((e: Error) => message.error(e.message)); }, [load, refreshKey]);

  /** UI-01 / D-10：抽班只生成候选（不落库/不锁机），确认前可以一直重抽。 */
  const runDraw = async () => {
    const values = await form.validateFields();
    setBusy(true);
    try {
      const result = await api<OpsDrawResult>("/local/ops/rosters/draw", {
        method: "POST",
        body: JSON.stringify(values),
      });
      setDraw(result);
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

  /** 排除机场快捷填充：最近 20 条日志里出现过的机场（只取 ICAO，去重后最多 12 个）。 */
  const fillRecentAirports = async () => {
    try {
      const res = await api<{ items: { dep_icao?: string | null; arr_icao?: string | null }[] }>(
        "/local/flights?limit=20");
      const recent = Array.from(new Set(res.items
        .flatMap((f) => [f.dep_icao, f.arr_icao])
        .filter((v): v is string => Boolean(v))));
      const current = (form.getFieldValue("excluded_airports") as string[] | undefined) || [];
      form.setFieldValue("excluded_airports",
        Array.from(new Set([...current, ...recent])).slice(0, 12));
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const confirm = async (candidate: OpsCandidate, index: number, replace = false) => {
    setBusy(true);
    try {
      const created = await api<OpsRoster>("/local/ops/rosters/confirm", {
        method: "POST",
        body: JSON.stringify({
          candidate_token: candidate.candidate_token, candidate_index: index, replace,
        }),
      });
      setDraw(null);
      setRoster(created);
      message.success(tr("班表已锁定，飞机已占用", "Roster locked and aircraft held"));
    } catch (e) {
      const err = e as ApiError;
      // UI-01：已有 LOCKED/IN_PROGRESS 班表 → 引导「重抽（替换）」或先取消；IN_PROGRESS 不能替换
      if (err.code === "ROSTER_EXISTS") {
        const status = String(err.details?.status || "");
        const oldId = String(err.details?.roster_id || "");
        if (!replace && status === "LOCKED") {
          Modal.confirm({
            title: tr("已有一张未开始的班表", "There is already a locked roster"),
            content: tr(
              "确认新班表会替换掉当前这张（首段还没开始，不收取消费也不记失约）。",
              "Taking this one replaces the current roster (no leg started yet, so no cancel fee or no-show).",
            ),
            okText: tr("替换并确认", "Replace & take it"),
            cancelText: tr("返回", "Back"),
            onOk: () => confirm(candidate, index, true),
          });
        } else {
          Modal.error({
            title: tr("不能替换当前班表", "This roster cannot be replaced"),
            content: status === "IN_PROGRESS"
              ? tr(`班表 ${oldId.slice(0, 8)} 首段已开始：请先飞完或「取消班表」。`,
                `Roster ${oldId.slice(0, 8)} already started: finish it or cancel it first.`)
              : err.message,
          });
        }
      } else {
        message.error(err.message);
      }
    } finally {
      setBusy(false);
    }
  };

  const startLeg = async (sequence: number) => {
    if (!roster) return;
    // §41：SimLink 自动开录可能已经建了一条无主记录，开始本段会把它改绑过来 —— 先说清楚
    if (recording.active) {
      const ok = await new Promise<boolean>((resolve) => {
        Modal.confirm({
          title: tr("已经在录制中", "A recording is already running"),
          content: tr(
            "检测到 SimLink 已在录制（自动开录）。开始本段后，这条记录会改绑到本航段，"
            + "包含起飞前已录制的部分；若这条记录属于别的任务，请先结束它。",
            "SimLink is already recording (auto start). Starting the leg will bind that recording "
            + "to this leg, including the part recorded before you started it. If it belongs to "
            + "another task, stop it first."),
          okText: tr("改绑并开始本段", "Bind & start leg"),
          cancelText: tr("返回", "Back"),
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        });
      });
      if (!ok) return;
    }
    setBusy(true);
    try {
      const res = await api<{ warnings?: string[] }>(
        `/local/ops/rosters/${roster.id}/legs/${sequence}/start`, { method: "POST" });
      (res.warnings || []).forEach((w) => message.warning(w));
      message.success(tr("航段已开始，配载已固化", "Leg started, load sheet frozen"));
      navigate("/ops/execute");
    } catch (e) {
      const err = e as { code?: string; message: string };
      if (err.code === "AIRCRAFT_NOT_AT_DEPARTURE") {
        // §35：位置不符只提示不过瘾，直接给「快速调机」入口
        Modal.confirm({
          title: tr("飞机不在出发机场", "Aircraft is not at the departure airport"),
          content: err.message,
          okText: tr("去快速调机", "Fast ferry"),
          cancelText: tr("返回", "Back"),
          onOk: () => navigate("/ops/fleet"),
        });
      } else {
        message.error(err.message);
      }
    } finally {
      setBusy(false);
    }
  };

  /** 本段作废重飞（§33 / D-3）：误判成「已完成」的航段退回未开始，并冲销结算/账本/位置。 */
  const voidLeg = async (sequence: number) => {
    if (!roster) return;
    setBusy(true);
    try {
      await api(`/local/ops/rosters/${roster.id}/legs/${sequence}/void`, {
        method: "POST", body: JSON.stringify({ reason: "本段作废重飞" }),
      });
      await load();
      message.success(tr("本段已作废，可重新开始这一段的记录", "Leg voided — you can start it again"));
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
  // UI-01 / D-10：抽班只生成候选，确认前一直可重抽；拦截在「确认」。
  // 首段已开始（IN_PROGRESS）时重抽没有意义，按钮文案改成提示先飞完或取消。
  const rosterActive = Boolean(roster && (roster.status === "LOCKED" || roster.status === "IN_PROGRESS"));
  const canRedraw = roster?.status === "LOCKED";

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
            {/* UI-01：抽班只生成候选，确认前可以一直重抽（拦截在「确认」） */}
            <Button loading={busy} disabled={roster?.status === "IN_PROGRESS"} onClick={() => void runDraw()}>
              {canRedraw ? tr("重抽（替换当前班表）", "Redraw (replaces current)") : tr("抽班", "Draw")}
            </Button>
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
              {tr("最多", "max")} {String(roster.constraints.max_legs ?? "—")}
              {tr(" 段 · 每程 ", " legs · per leg ")}
              {String(roster.constraints.min_leg_block_minutes ?? "—")}–{String(roster.constraints.max_leg_block_minutes ?? "—")}min
              {tr(" · 合计 ", " · total ")}
              {String((roster.constraints as Record<string, unknown>).min_total_block_minutes
                ?? Math.max(30, Math.round(Number(roster.constraints.max_block_minutes ?? 480) * 0.75)))}
              –{String(roster.constraints.max_block_minutes ?? "—")}min
              {roster.constraints.follow_routes === false ? tr(" · 任意机场对", " · any airport pair") : ""}
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
                  ) : l.status === "COMPLETED" || l.status === "IN_PROGRESS" ? (
                    <Popconfirm
                      title={tr("本段作废重飞？", "Void this leg and re-fly it?")}
                      description={tr("退回未开始，并冲销该段的结算、账本与机队位置（幽灵机/假起降误判时用）。",
                        "Returns the leg to planned and reverses its settlement, ledger entries and aircraft position.")}
                      okText={tr("作废重飞", "Void & re-fly")}
                      okButtonProps={{ danger: true }}
                      cancelText={tr("返回", "Back")}
                      onConfirm={() => void voidLeg(l.sequence)}
                    >
                      <Button size="small" danger loading={busy}>
                        {tr("本段作废重飞", "Void & re-fly")}
                      </Button>
                    </Popconfirm>
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
                  <Form.Item name="max_block_minutes" label={tr("合计飞行时间（min）", "Total block (min)")}>
                    <InputNumber min={30} max={1440} step={30} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    name="min_total_block_minutes"
                    label={tr("最少合计航时（min）", "Min total block (min)")}
                    dependencies={["max_block_minutes"]}
                    extra={(
                      <span className="muted" style={{ fontSize: 12 }}>
                        {tr(`可接受 ${minTotalDefault}–${Number(maxBlockWatch)} min`,
                          `Accept ${minTotalDefault}–${Number(maxBlockWatch)} min`)}
                      </span>
                    )}
                    rules={[({ getFieldValue }) => ({
                      validator: (_rule, value) => {
                        const max = Number(getFieldValue("max_block_minutes") ?? DEFAULTS.max_block_minutes);
                        if (value == null || (Number(value) >= 30 && Number(value) <= max)) {
                          return Promise.resolve();
                        }
                        return Promise.reject(new Error(tr(
                          `需在 30–${max} min 之间（不能超过合计上限）`,
                          `Must be 30–${max} min (not above the total cap)`)));
                      },
                    })]}
                  >
                    <InputNumber min={30} max={1440} step={30} style={{ width: "100%" }}
                      placeholder={tr(`留空 = ${minTotalDefault}`, `blank = ${minTotalDefault}`)} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    name="min_leg_block_minutes"
                    label={tr("每程最短航时（min）", "Min per-leg block")}
                    dependencies={["max_leg_block_minutes"]}
                    rules={[({ getFieldValue }) => ({
                      validator: (_rule, value) => {
                        const max = getFieldValue("max_leg_block_minutes");
                        if (value == null || max == null || Number(value) <= Number(max)) {
                          return Promise.resolve();
                        }
                        return Promise.reject(new Error(tr(
                          "不能大于每程最长航时", "Must not exceed max per-leg block")));
                      },
                    })]}
                  >
                    <InputNumber min={5} max={1440} step={5} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    name="max_leg_block_minutes"
                    label={tr("每程最长航时（min）", "Max per-leg block")}
                    dependencies={["min_leg_block_minutes"]}
                    rules={[({ getFieldValue }) => ({
                      validator: (_rule, value) => {
                        const min = getFieldValue("min_leg_block_minutes");
                        if (value == null || min == null || Number(value) >= Number(min)) {
                          return Promise.resolve();
                        }
                        return Promise.reject(new Error(tr(
                          "不能小于每程最短航时", "Must not be below min per-leg block")));
                      },
                    })]}
                  >
                    <InputNumber min={10} max={1440} step={30} style={{ width: "100%" }} />
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
                  <Form.Item name="follow_routes" valuePropName="checked"
                    label={tr("遵循航线", "Follow routes")}
                    tooltip={tr("关掉后不依赖航线/班期，用 navdata 机场库任意组合起降",
                      "Turn off to ignore routes/schedules and pair any navdata airports")}>
                    <Switch />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="prefer_new_airports" label={tr("优先未飞机场", "Prefer new airports")} valuePropName="checked">
                    <Switch />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="exclude_military" valuePropName="checked"
                    label={tr("不含军用机场", "Exclude military")}
                    tooltip={tr("navdata 标记的军用机场不进候选（出发机场不受影响）",
                      "Military airports from navdata are skipped (departure airport is unaffected)")}>
                    <Switch />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="consider_wingspan" valuePropName="checked"
                    label={tr("考虑跑道宽度（翼展）", "Check wingspan")}
                    tooltip={tr("按跑道宽度推断翼展上限（45 m → 52 m），近似值，未含 AIP 飞行区等级",
                      "Wingspan limit is inferred from runway width (45 m → 52 m); approximate, no AIP code letter")}>
                    <Switch />
                  </Form.Item>
                </Col>
                <Col span={24}>
                  <Form.Item
                    name="excluded_airports"
                    label={tr("排除机场", "Excluded airports")}
                    extra={(
                      <span className="muted" style={{ fontSize: 12 }}>
                        {tr("出发/到达/中转过站都算；留空表示不排除。",
                          "Departure, arrival and intermediate stops all count; empty = no exclusions.")}
                        <Button type="link" size="small" onClick={() => void fillRecentAirports()}>
                          {tr("填入最近去过", "Fill recent")}
                        </Button>
                      </span>
                    )}
                  >
                    <AirportMultiSelect placeholder={tr("输入 ICAO 或机场名搜索", "Search ICAO or airport")} />
                  </Form.Item>
                </Col>
              </Row>
              {/* UI-01 / D-10：抽班只生成候选，确认前可以一直重抽；首段开始后不能再抽 */}
              <Button type="primary" block icon={<ThunderboltOutlined />} loading={busy}
                disabled={roster?.status === "IN_PROGRESS"}
                onClick={() => void runDraw()}>
                {roster?.status === "IN_PROGRESS"
                  ? tr("班表执行中：先飞完或取消", "Roster in progress — finish or cancel it")
                  : canRedraw
                    ? tr("重抽（替换当前班表）", "Redraw (replaces the current roster)")
                    : tr("抽班", "Draw")}
              </Button>
              <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                {roster?.status === "IN_PROGRESS"
                  ? tr("首段已经开始：确认新班表会被拒绝，先飞完或「取消班表」。",
                    "The first leg has started: confirming a new roster is rejected — finish it or cancel it.")
                  : canRedraw
                    ? tr("重抽无冷却/费用/次数限制；点「确认」时才会替换当前这张班表。",
                      "Redraws are free and unlimited; the current roster is only replaced when you confirm.")
                    : tr("抽班只生成候选：确认前可以一直重抽，确认时才锁飞机。",
                      "Drawing only generates candidates — redraw freely until you confirm; the aircraft is held at confirm.")}
              </div>
            </Form>
          </Card>
        </Col>
        <Col xs={24} lg={15}>
          <Card className="panel" variant="borderless" title={tr("候选", "Candidates")}
            extra={draw ? (
              <Space size={8}>
                {draw.excluded_airports?.length ? (
                  <Tag color="volcano">
                    {tr("已排除", "Excluded")} {draw.excluded_airports.length} {tr("个机场", "airports")}
                  </Tag>
                ) : null}
                {draw.follow_routes === false ? <Tag color="cyan">{tr("任意机场对", "Any airport pair")}</Tag> : null}
                <Text type="secondary">{tr("共评估", "considered")} {draw.considered}</Text>
              </Space>
            ) : null}>
            {draw?.warnings?.length ? (
              <Alert style={{ marginBottom: 12 }} type="warning" showIcon
                message={tr("约束已放宽", "Constraints relaxed")}
                description={draw.warnings.join("；")} />
            ) : null}
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
                        {candidate.legs.some((l) => l.virtual) ? (
                          <Tag color="cyan">{tr("虚拟航段", "Virtual leg")}</Tag>
                        ) : null}
                        {typeof candidate.legs[0]?.max_wingspan_m === "number" ? (
                          <Tag color="purple">
                            {tr("翼展上限", "Wingspan max")} {candidate.legs[0].max_wingspan_m} m
                          </Tag>
                        ) : null}
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
              <Empty description={draw?.reason || tr("设置条件后点「抽班」", "Set constraints and draw")} />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
