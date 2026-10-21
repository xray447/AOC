import {
  PlayCircleOutlined, PoweroffOutlined, ReloadOutlined, StopOutlined,
} from "@ant-design/icons";
import {
  Alert, Button, Card, Col, Descriptions, Empty, Popconfirm, Row, Space, Statistic, Table, Tag, Typography, message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { SimBriefButton } from "../../components/SimBriefButton";
import { useApp } from "../../context";
import { useI18n } from "../../i18n";
import { fmtBlock, fmtUtc, money, policyAction, settlementStatus } from "../../ops";
import type { OpsFreeFlight, OpsLoadSheet, OpsRoster, OpsSettlement, OpsTask } from "../../types";

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
  const [active, setActive] = useState<ActiveResponse | null>(null);
  const [load, setLoad] = useState<OpsLoadSheet | null>(null);
  const [settlement, setSettlement] = useState<OpsSettlement | null>(null);
  const [busy, setBusy] = useState(false);

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

  const startRecording = async () => {
    setBusy(true);
    try {
      await api("/local/recording/start", { method: "POST" });
      await refresh();
      await loadAll();
      message.success(tr("已开始记录，落地后自动结算", "Recording started; settlement runs after landing"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
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
                  <Tag color="processing">{tr("记录中", "Recording")} · {recording.samples} pts · {recording.phase}</Tag>
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
                  <Button type="primary" icon={<PlayCircleOutlined />} loading={busy} onClick={() => void startRecording()}>
                    {tr("开始记录", "Start recording")}
                  </Button>
                  <Text type="secondary">
                    {recording.simlink_connected
                      ? tr("SimLink 在线：起飞后也会自动开始", "SimLink online: recording also starts automatically after takeoff")
                      : tr("SimLink 离线：先启动 aoc-simlink 才能采集遥测", "SimLink offline: start aoc-simlink to capture telemetry")}
                  </Text>
                </>
              )}
            </Space>
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
