import {
  PlayCircleOutlined, PoweroffOutlined, ReloadOutlined, StopOutlined,
} from "@ant-design/icons";
import {
  Alert, Button, Card, Col, Descriptions, Empty, Modal, Popconfirm, Row, Space, Statistic, Table, Tag, Typography, message,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { SimBriefButton } from "../../components/SimBriefButton";
import { SimlinkNotice } from "../../components/SimlinkNotice";
import { useApp } from "../../context";
import { useI18n } from "../../i18n";
import { fmtBlock, fmtUtc, money, policyAction, settlementStatus } from "../../ops";
import { simlinkState } from "../../simlink";
import type {
  FlightStatus, OpsFreeFlight, OpsLoadSheet, OpsRoster, OpsSettlement, OpsTask,
} from "../../types";
import { fmtHms, fmtSignedKg } from "../../utils";

const LIVE_POLL_MS = 2000;

/** §39 推出定稿来源的界面标签（preflight = 推出前的临时值）。 */
const zfwSourceLabels: Record<string, { zh: string; en: string; color?: string }> = {
  engine: { zh: "发动机启动", en: "engine start", color: "green" },
  gs: { zh: "地速推出", en: "ground speed", color: "blue" },
  start: { zh: "开录首帧", en: "first frame", color: "gold" },
  preflight: { zh: "推出前临时值", en: "provisional", color: "default" },
};

function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

const { Text } = Typography;

interface ActiveResponse {
  task: OpsTask | null;
  roster: OpsRoster | null;
  free_flight: OpsFreeFlight | null;
}

export function OpsExecute({ embedded = false }: { embedded?: boolean }) {
  const { tr } = useI18n();
  const navigate = useNavigate();
  const { refresh, recording } = useApp();
  const sim = simlinkState(recording);
  const [active, setActive] = useState<ActiveResponse | null>(null);
  const [load, setLoad] = useState<OpsLoadSheet | null>(null);
  const [settlement, setSettlement] = useState<OpsSettlement | null>(null);
  const [flightStatus, setFlightStatus] = useState<FlightStatus | null>(null);
  const [busy, setBusy] = useState(false);
  // 推出时 ZFW 仍偏低：只提示一次（按后端给的 seq 去重）
  const zfwWarnSeq = useRef(0);

  const loadAll = useCallback(async () => {
    const res = await api<ActiveResponse>("/local/ops/active");
    setActive(res);
    if (res.task) {
      try {
        setLoad(await api<OpsLoadSheet>(`/local/ops/load-sheets/${res.task.flight_record_id}`));
      } catch {
        setLoad(null);
      }
      try {
        setSettlement(await api<OpsSettlement>(`/local/ops/flights/${res.task.flight_record_id}/settlement`));
      } catch {
        setSettlement(null);
      }
    } else {
      setLoad(null);
      setSettlement(null);
    }
  }, []);

  useEffect(() => { void loadAll().catch((e: Error) => message.error(e.message)); }, [loadAll]);
  useEffect(() => {
    if (recording.active) void loadAll();
  }, [recording.active, loadAll]);

  const startRecording = async (partial = false) => {
    setBusy(true);
    try {
      const res = await api<{ warnings?: string[] }>("/local/recording/start", {
        method: "POST",
        body: JSON.stringify({ partial }),
      });
      (res.warnings || []).forEach((w) => message.warning(w));
      await refresh();
      await loadAll();
      message.success(tr("已开始记录，落地后自动结算", "Recording started; settlement runs after landing"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  /** 开录前的位置/连接检查（§33 位置闸）；ZFW 不再在这里校验（§32 改由推出事件定稿）。 */
  const startWithChecks = async () => {
    // §33 位置闸：距出发机场 >10 NM 不开录；已在空中可改「部分记录」（走复核，D-2）
    if (flightStatus && flightStatus.position_ok === false) {
      if (flightStatus.partial_allowed) {
        const ok = await new Promise<boolean>((resolve) => {
          Modal.confirm({
            title: tr("已在空中", "Already airborne"),
            content: tr(
              "位置闸发现飞机已经在空中：可以按「部分记录」开始。缺地面/起飞段的记录不会自动判完成，落地后进复核队列。",
              "The position gate sees you airborne: start a partial recording. Records missing the ground/takeoff phase are not auto-completed; they go to review after landing.",
            ),
            okText: tr("按部分记录开始", "Start partial recording"),
            cancelText: tr("返回", "Back"),
            onOk: () => resolve(true),
            onCancel: () => resolve(false),
          });
        });
        if (!ok) return;
        await startRecording(true);
        return;
      }
      message.warning(
        tr(
          `尚未进入飞行 / 位置不符：距 ${flightStatus.dep_icao || "出发机场"} ${flightStatus.dep_distance_nm ?? "?"} NM，请先在 MSFS 里于本场进入飞行`,
          `Not in flight / wrong position: ${flightStatus.dep_distance_nm ?? "?"} NM from ${flightStatus.dep_icao || "departure"}. Enter the flight at this airport in MSFS first.`,
        ),
      );
      return;
    }
    // SimLink 在跑但没连上模拟器：这次记录不会有采样点，先确认
    if (sim.level === "no-sim") {
      const proceed = await new Promise<boolean>((resolve) => {
        Modal.confirm({
          title: tr("没连上模拟器", "Simulator not connected"),
          content: tr(
            "SimLink 在运行，但没连上 MSFS：这次记录不会有采样点，落地后也无法结算。仍要开始吗？",
            "SimLink is running but not connected to MSFS: this recording will have no samples and cannot be settled. Start anyway?",
          ),
          okText: tr("仍然开始", "Start anyway"),
          okButtonProps: { danger: true },
          cancelText: tr("返回", "Back"),
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        });
      });
      if (!proceed) return;
    }
    // §32 方案 B：开录不带 ZFW/油量，推出时由 SimLink 定稿（不再弹「偏低」Modal）
    await startRecording();
  };

  const stopRecording = async (abort: boolean) => {
    setBusy(true);
    try {
      const res = await api<{ flight: { id: string } | null }>("/local/recording/stop", {
        method: "POST", body: JSON.stringify({ abort }),
      });
      await refresh();
      await loadAll();
      if (abort) {
        message.info(tr("已中止本次任务", "Task aborted"));
      } else if (res.flight?.id) {
        try {
          const st = await api<OpsSettlement>(`/local/ops/flights/${res.flight.id}/settlement`);
          setSettlement(st);
          message.success(`${tr("已结算", "Settled")} ${money(st.profit)}`);
        } catch {
          message.success(tr("飞行已保存", "Flight saved"));
        }
      }
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const abortTask = async () => {
    setBusy(true);
    try {
      const res = await api<{ aborted: boolean }>("/local/ops/tasks/abort", {
        method: "POST", body: JSON.stringify({ reason: tr("飞行员取消", "cancelled by pilot") }),
      });
      await refresh();
      await loadAll();
      setSettlement(null);
      message.info(res.aborted
        ? tr("已取消本次航班：航段作废、飞机已释放（不结算）",
          "Flight cancelled: leg voided, aircraft released (no settlement)")
        : tr("没有正在执行的任务", "No active task"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const task = active?.task || null;
  const rosterLeg = active?.roster?.legs.find((l) => l.id === task?.roster_leg_id);
  const flightId = task?.flight_record_id;

  // 实时状态：飞行中每 2s 取 SimLink 最新采样（速度/高度/位置/ETE/ETA）
  useEffect(() => {
    if (!flightId) {
      setFlightStatus(null);
      return undefined;
    }
    let alive = true;
    const tick = async () => {
      if (document.hidden) return;   // 页面在后台时不轮询，省 CPU
      try {
        const status = await api<FlightStatus>("/local/ops/flight-status");
        if (alive) setFlightStatus(status);
        if (status.zfw_warning_seq > zfwWarnSeq.current) {
          zfwWarnSeq.current = status.zfw_warning_seq;
          (status.zfw_warnings || []).forEach((w) => message.warning(w));
        }
      } catch {
        if (alive) setFlightStatus(null);
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), LIVE_POLL_MS);
    return () => { alive = false; window.clearInterval(timer); };
  }, [flightId]);

  return (
    <div className={embedded ? "ops-embedded" : "page"}>
      {embedded ? null : (
        <div className="page-head">
          <div>
            <h2>{tr("配载与执行", "Load & execute")}</h2>
            <p>{tr("开始航段时固化配载与规则快照；SimLink 自动记录落地后由 aoc-core 结算。", "Starting a leg freezes the load sheet and rule snapshot; SimLink records the flight and aoc-core settles it after landing.")}</p>
          </div>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void loadAll()}>{tr("刷新", "Refresh")}</Button>
            <Button onClick={() => navigate("/ops/settlements")}>{tr("结算明细", "Settlements")}</Button>
          </Space>
        </div>
      )}

      {!task ? (
        <Card className="panel" variant="borderless">
          <Empty description={tr("没有正在执行的任务", "No active task")}>
            <Space>
              <Button type="primary" onClick={() => navigate("/ops/roster")}>{tr("去抽班", "Draw roster")}</Button>
              <Button onClick={() => navigate("/ops/free")}>{tr("自由飞行", "Free flight")}</Button>
            </Space>
          </Empty>
        </Card>
      ) : (
        <>
          <Card
            className="panel"
            variant="borderless"
            title={tr("当前任务", "Active task")}
            extra={(
              <Popconfirm
                title={tr("取消本次航班？", "Cancel this flight?")}
                description={tr("航段作废、剩余班表一起取消、飞机立即释放，不产生结算；已经开始的任务也会一并清除。",
                  "The leg is voided, the rest of the roster is cancelled, the aircraft is released and nothing is settled.")}
                okText={tr("取消航班", "Cancel flight")}
                okButtonProps={{ danger: true }}
                cancelText={tr("返回", "Back")}
                onConfirm={() => void abortTask()}
              >
                <Button danger icon={<StopOutlined />} loading={busy}>
                  {tr("取消本次航班", "Cancel flight")}
                </Button>
              </Popconfirm>
            )}
          >
            <Descriptions size="small" column={3}>

              <Descriptions.Item label={tr("任务", "Task")}>
                <Tag color={task.kind === "ROSTER" ? "blue" : "cyan"}>{task.kind}</Tag>
                {task.callsign}
              </Descriptions.Item>
              <Descriptions.Item label={tr("航段", "Leg")}>{task.dep_icao} → {task.arr_icao}</Descriptions.Item>
              <Descriptions.Item label={tr("机型", "Type")}>{task.aircraft_type}</Descriptions.Item>
              <Descriptions.Item label={tr("计划起飞", "ETD")}>{fmtUtc(task.scheduled_dep_utc)}</Descriptions.Item>
              <Descriptions.Item label={tr("开始时间", "Started")}>{fmtUtc(task.started_at)}</Descriptions.Item>
              <Descriptions.Item label={tr("航班记录", "Log")}>
                <a onClick={() => navigate(`/logs/${task.flight_record_id}`)}>{task.flight_record_id.slice(0, 8)}</a>
              </Descriptions.Item>
            </Descriptions>
            <Space wrap style={{ marginTop: 8 }}>
              {recording.active && recording.flight_id === task.flight_record_id ? (
                <>
                  <Tag color="processing">
                    {tr("记录中", "Recording")} · {tr("发动机", "Engine")} {fmtHms(recording.engine_seconds)}
                    {" · "}{tr("已飞", "Airborne")} {fmtHms(recording.flight_seconds)} · {recording.phase}
                  </Tag>
                  <Button danger type="primary" icon={<PoweroffOutlined />} loading={busy}
                    onClick={() => void stopRecording(false)}>
                    {tr("结束并结算", "Stop & settle")}
                  </Button>
                  <Text type="secondary">
                    {tr("要放弃本次航班请用右上角「取消本次航班」", "To give up, use “Cancel flight” at the top right")}
                  </Text>
                </>
              ) : (
                <>
                  <SimBriefButton
                    dep={task.dep_icao}
                    arr={task.arr_icao}
                    aircraftType={task.aircraft_type}
                    callsign={task.callsign}
                    opsLeg={{ flightRecordId: task.flight_record_id }}
                  />
                  <Button type="primary" icon={<PlayCircleOutlined />} loading={busy}
                    disabled={flightStatus?.position_ok === false && !flightStatus?.partial_allowed}
                    onClick={() => void startWithChecks()}>
                    {tr("开始记录", "Start recording")}
                  </Button>
                  <Text type={sim.level === "online" ? "secondary" : "warning"}>
                    {sim.level === "online"
                      ? tr("SimLink 已连上模拟器：起飞后也会自动开始", "SimLink is connected: recording also starts automatically after takeoff")
                      : sim.level === "no-sim"
                        ? tr("SimLink 在运行但没连上模拟器：这次记录可能没有采样点",
                          "SimLink runs but the simulator is not connected: this recording may have no samples")
                        : tr("SimLink 未运行：先启动 aoc-simlink 才能采集遥测",
                          "SimLink is not running: start aoc-simlink to capture telemetry")}
                  </Text>
                </>
              )}
            </Space>
            {!recording.active && flightStatus && flightStatus.position_ok === false ? (
              <Alert
                style={{ marginTop: 8 }}
                type="warning"
                showIcon
                message={flightStatus.partial_allowed
                  ? tr("已在空中：可以按部分记录开始（走复核）", "Airborne: start a partial recording (goes to review)")
                  : tr("位置不符，暂时无法开始记录", "Wrong position — recording is blocked for now")}
                description={flightStatus.partial_allowed
                  ? tr("缺地面/起飞段的记录不会自动判完成，落地后进复核队列。",
                    "A record without the ground/takeoff phase is not auto-completed; it goes to review after landing.")
                  : tr(`距 ${flightStatus.dep_icao || "出发机场"} ${flightStatus.dep_distance_nm ?? "?"} NM（需 ≤10 NM 且在地面）：请先在 MSFS 里于本场进入飞行，幽灵机/加载期的位置不会开录。`,
                    `${flightStatus.dep_distance_nm ?? "?"} NM from ${flightStatus.dep_icao || "departure"} (needs ≤10 NM on the ground): enter the flight at this airport in MSFS first.`)}
              />
            ) : null}
          </Card>

          <SimlinkNotice style={{ marginTop: 16 }} />

          <Card
            className="panel"
            variant="borderless"
            style={{ marginTop: 16 }}
            title={tr("实时状态", "Live status")}
            extra={flightStatus?.phase ? <Tag color="processing">{flightStatus.phase}</Tag> : null}
          >
            <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
              <Descriptions.Item label={tr("地速", "GS")}>{num(flightStatus?.gs_kt)} kt</Descriptions.Item>
              <Descriptions.Item label={tr("表速", "IAS")}>{num(flightStatus?.ias_kt)} kt</Descriptions.Item>
              <Descriptions.Item label={tr("高度", "ALT")}>{num(flightStatus?.alt_ft)} ft</Descriptions.Item>
              <Descriptions.Item label="AGL">{num(flightStatus?.agl_ft)} ft</Descriptions.Item>
              <Descriptions.Item label={tr("升降率", "V/S")}>{num(flightStatus?.vs_fpm)} fpm</Descriptions.Item>
              <Descriptions.Item label={tr("位置", "Position")}>
                {flightStatus?.lat != null && flightStatus?.lon != null
                  ? `${flightStatus.lat.toFixed(4)}, ${flightStatus.lon.toFixed(4)}`
                  : "—"}
              </Descriptions.Item>
              <Descriptions.Item label={tr("剩余", "Remaining")}>{num(flightStatus?.remaining_nm)} NM</Descriptions.Item>
              <Descriptions.Item label="ETE / ETA">
                {flightStatus?.ete_min != null ? `${num(flightStatus.ete_min)} min` : "—"}
                {" · "}
                {flightStatus?.eta_utc ? fmtUtc(flightStatus.eta_utc) : "—"}
              </Descriptions.Item>
            </Descriptions>
            {flightStatus && !flightStatus.available ? (
              <Text type="secondary">{tr("没有 SimLink 采样（检查 SimLink 是否在线）",
                "No SimLink samples — check that SimLink is running")}</Text>
            ) : null}
            <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }} style={{ marginTop: 8 }}>
              <Descriptions.Item label={tr("实际 ZFW（推出后定稿）", "Actual ZFW (final at pushback)")}>
                {flightStatus?.actual_zfw_kg != null
                  ? <span className={flightStatus.zfw_state === "short" ? "text-danger" : undefined}>
                      {num(flightStatus.actual_zfw_kg)} kg
                    </span>
                  : "—"}
                {zfwSourceLabels[flightStatus?.zfw_source || ""] ? (
                  <Tag color={zfwSourceLabels[flightStatus?.zfw_source || ""].color} style={{ marginLeft: 6 }}>
                    {tr(zfwSourceLabels[flightStatus?.zfw_source || ""].zh,
                      zfwSourceLabels[flightStatus?.zfw_source || ""].en)}
                  </Tag>
                ) : null}
              </Descriptions.Item>
              <Descriptions.Item label={tr("配载单 ZFW", "Load sheet ZFW")}>
                {num(flightStatus?.planned_zfw_kg ?? load?.zfw_kg)} kg
              </Descriptions.Item>
              <Descriptions.Item label={tr("差异", "Delta")}>
                {/* §40：差异用后端算好的值（±0.5 kg 归零、±1 kg 分档），格式化统一走 fmtSignedKg */}
                {(() => {
                  const planned = flightStatus?.planned_zfw_kg ?? load?.zfw_kg ?? null;
                  const delta = flightStatus?.zfw_delta_kg
                    ?? (flightStatus?.actual_zfw_kg != null && planned != null
                      ? flightStatus.actual_zfw_kg - Number(planned) : null);
                  if (delta == null) return "—";
                  const short = (flightStatus?.zfw_state || (delta < -1 ? "short" : delta > 1 ? "over" : "ok"));
                  return <span className={short === "short" ? "text-danger" : undefined}>{fmtSignedKg(delta)}</span>;
                })()}
              </Descriptions.Item>
              <Descriptions.Item label={tr("实际滑出油量", "Fuel at pushback")}>
                {num(flightStatus?.fuel_at_pushback ?? flightStatus?.fuel_weight_kg)} kg
              </Descriptions.Item>
              <Descriptions.Item label={tr("计划油量", "Planned fuel")}>
                {num(flightStatus?.planned_fuel_kg ?? load?.fuel_kg)} kg
              </Descriptions.Item>
              <Descriptions.Item label={tr("推出时间", "Pushback")}>
                {flightStatus?.fuel_at_pushback != null
                  ? tr("已定稿", "captured")
                  : tr("尚未推出（推出时会再校验）", "not yet — checked again at pushback")}
              </Descriptions.Item>
            </Descriptions>
          </Card>

          {load ? (
            <Row gutter={16} style={{ marginTop: 16 }}>
              <Col xs={24} lg={16}>
                <Card className="panel" variant="borderless" title={tr("配载单（航班开始时固化）", "Load sheet (frozen at start)")}>
                  <Row gutter={16}>
                    <Col span={6}><Statistic title={tr("旅客", "Pax")} value={load.pax_total}
                      suffix={`/ ${load.pax_economy}Y ${load.pax_business}J ${load.pax_first}F`} /></Col>
                    <Col span={6}><Statistic title={tr("货物 / 邮件", "Cargo / mail")}
                      value={Math.round(load.cargo_kg)} suffix={`kg / ${Math.round(load.mail_kg)}kg`} /></Col>
                    <Col span={6}><Statistic title={tr("计划航时", "Block")} value={fmtBlock(load.block_minutes)} /></Col>
                    <Col span={6}><Statistic title={tr("距离", "Distance")} value={Math.round(load.distance_nm || 0)} suffix="NM" /></Col>
                  </Row>
                  <Descriptions size="small" column={3} style={{ marginTop: 12 }}>
                    <Descriptions.Item label="OEW">{Math.round(load.oew_kg || 0).toLocaleString()} kg</Descriptions.Item>
                    <Descriptions.Item label="ZFW">{Math.round(load.zfw_kg || 0).toLocaleString()} kg</Descriptions.Item>
                    <Descriptions.Item label="TOW">{Math.round(load.tow_kg || 0).toLocaleString()} kg</Descriptions.Item>
                    <Descriptions.Item label={tr("燃油", "Fuel")}>{Math.round(load.fuel_kg || 0).toLocaleString()} kg</Descriptions.Item>
                    <Descriptions.Item label={tr("预估收入", "Est. revenue")}>{money(load.estimated_revenue)}</Descriptions.Item>
                    <Descriptions.Item label={tr("预估成本", "Est. cost")}>{money(load.estimated_cost)}</Descriptions.Item>
                  </Descriptions>
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginTop: 8 }}
                    message={tr("预估以结算为准", "Estimates only — settlement is authoritative")}
                    description={tr("最终收入按实际航时、油耗与落地数据重算，并按异常策略折算。",
                      "Final revenue uses actual block time, fuel burn and landing data, then applies the settlement policy.")}
                  />
                </Card>
              </Col>
              <Col xs={24} lg={8}>
                <Card className="panel" variant="borderless" title={tr("班表状态", "Roster status")}>
                  {rosterLeg ? (
                    <Descriptions size="small" column={1}>
                      <Descriptions.Item label={tr("航段", "Leg")}>{rosterLeg.sequence} / {active?.roster?.legs.length}</Descriptions.Item>
                      <Descriptions.Item label={tr("状态", "Status")}>{rosterLeg.status}</Descriptions.Item>
                      <Descriptions.Item label={tr("实际起飞", "Actual off")}>{fmtUtc(rosterLeg.actual_dep_utc)}</Descriptions.Item>
                      <Descriptions.Item label={tr("实际到达", "Actual on")}>{fmtUtc(rosterLeg.actual_arr_utc)}</Descriptions.Item>
                    </Descriptions>
                  ) : (
                    <Text type="secondary">{tr("自由飞行任务", "Free flight task")}</Text>
                  )}
                </Card>
              </Col>
            </Row>
          ) : null}

          {settlement ? (
            <Card className="panel" variant="borderless" style={{ marginTop: 16 }}
              title={tr("结算结果", "Settlement")}
              extra={(
                <Space>
                  <Tag color={policyAction[settlement.policy_action]?.color}>
                    {policyAction[settlement.policy_action] ? tr(policyAction[settlement.policy_action].zh, policyAction[settlement.policy_action].en) : settlement.policy_action}
                  </Tag>
                  <Tag color={settlementStatus[settlement.status]?.color}>
                    {settlementStatus[settlement.status] ? tr(settlementStatus[settlement.status].zh, settlementStatus[settlement.status].en) : settlement.status}
                  </Tag>
                </Space>
              )}>
              <Row gutter={16}>
                <Col span={6}><Statistic title={tr("毛收入", "Gross revenue")} value={money(settlement.revenue_gross)} /></Col>
                <Col span={6}><Statistic title={tr("结算收入", "Settled revenue")} value={money(settlement.revenue_total)} /></Col>
                <Col span={6}><Statistic title={tr("总成本", "Costs")} value={money(settlement.cost_total)} /></Col>
                <Col span={6}><Statistic title={tr("利润", "Profit")} value={money(settlement.profit)}
                  valueStyle={{ color: settlement.profit >= 0 ? "#22c55e" : "#ef4444" }} /></Col>
              </Row>
              <Space style={{ marginTop: 12 }}>
                <Button onClick={() => navigate(`/ops/settlements?focus=${settlement.id}`)}>{tr("查看明细", "Details")}</Button>
                <Button onClick={() => navigate(`/logs/${settlement.flight_record_id}`)}>{tr("回放轨迹", "Replay")}</Button>
              </Space>
            </Card>
          ) : null}
        </>
      )}
    </div>
  );
}
