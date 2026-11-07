import { BellOutlined, SendOutlined } from "@ant-design/icons";
import {
  Alert, Button, Card, Input, InputNumber, Select, Space, Switch, Table, Tag, Typography, message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useI18n } from "../i18n";
import type { Settings, StandChannel } from "../types";

const { Text } = Typography;

interface HoppieStatus {
  configured: boolean;
  masked: string;
  enabled: boolean;
  from: string;
  callsign?: string | null;
  channel: StandChannel;
}

const MATRIX = [
  { type: "iniBuilds A350", local: "—", hoppie: "已实测（2026-11-06）", state: "可用" },
  { type: "Fenix A320", local: "不做（Q-11）", hoppie: "DCDU / RECEIVED MESSAGES", state: "待实测" },
  { type: "FlyByWire A32NX", local: "—", hoppie: "ACARS / TELEX", state: "待实测" },
  { type: "PMDG 737/777/747", local: "—", hoppie: "ACARS", state: "待实测" },
  { type: "其他 / 默认", local: "—", hoppie: "—", state: "走浮窗" },
];

/** docs/12：到达提醒设置（阈值、通道、Hoppie logon、机型矩阵、当前生效通道）。 */
export function StandNoticeCard({ draft, patch }: {
  draft: Settings;
  patch: (p: Partial<Settings>) => void;
}) {
  const { tr } = useI18n();
  const [status, setStatus] = useState<HoppieStatus | null>(null);
  const [logon, setLogon] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await api<HoppieStatus>("/local/hoppie/status"));
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const saveLogon = async () => {
    setBusy(true);
    try {
      await api("/local/hoppie/logon", {
        method: "POST", body: JSON.stringify({ logon: logon.trim() }),
      });
      setLogon("");
      message.success(tr("logon code 已保存（加密，只在本机库）",
        "logon code saved (encrypted, local DB only)"));
      await load();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const sendTest = async () => {
    setBusy(true);
    try {
      const res = await api<{ verdict: string; ok?: boolean; error?: string | null }>(
        "/local/hoppie/test", { method: "POST", body: JSON.stringify({}) });
      if (res.ok ?? ["OK", "UNKNOWN"].includes(res.verdict)) {
        message.success(
          tr(`已交网络（${res.verdict}）——Hoppie 没有回执，要去机上确认`,
            `Handed to the network (${res.verdict}) — Hoppie has no ACK; confirm in the cockpit`));
      } else {
        message.warning(
          tr(`没有发出（${res.verdict}）${res.error ? `：${res.error}` : ""}`,
            `Not sent (${res.verdict})${res.error ? `: ${res.error}` : ""}`));
      }
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const channel = status?.channel;
  const channelText = channel?.channel === "acars"
    ? tr("Hoppie ACARS（机内）", "Hoppie ACARS (in cockpit)")
    : channel?.channel === "batc"
      ? tr("BeyondATC 权威（AOC 不推机位）", "BeyondATC authoritative")
      : tr("AOC 浮窗 + 系统通知", "AOC overlay + system toast");

  return (
    <Card
      className="panel"
      variant="borderless"
      title={<Space><BellOutlined />{tr("到达提醒", "Arrival reminder")}</Space>}
      extra={<Tag color={draft.stand_notice ? "green" : "default"}>
        {draft.stand_notice ? tr("已开启", "on") : tr("已关闭", "off")}
      </Tag>}
    >
      <Space direction="vertical" size={10} style={{ width: "100%" }}>
        <div className="setting-row">
          <div>
            <div className="label">{tr("到达前提醒预计停机位", "Remind me of the stand")}</div>
            <div className="hint">
              {tr("飞机在 MSFS 里全屏飞时页面不可见，提醒由 aoc-core 判定、常驻进程投递",
                "The page is hidden while flying full-screen: aoc-core decides, the resident shell delivers")}
            </div>
          </div>
          <Switch checked={draft.stand_notice} onChange={(v) => patch({ stand_notice: v })} />
        </div>

        <div className="setting-row">
          <div>
            <div className="label">{tr("提前量", "Lead time")}</div>
            <div className="hint">{tr("ETA ≤ N 分钟 或 距到达 ≤ N NM 先到者触发",
              "Triggers when ETA ≤ N min or distance ≤ N NM, whichever comes first")}</div>
          </div>
          <Space size={8}>
            <InputNumber value={draft.stand_lead_minutes} min={10} max={60} step={5}
              addonAfter={tr("分钟", "min")}
              onChange={(v) => patch({ stand_lead_minutes: Number(v) || 30 })} />
            <InputNumber value={draft.stand_lead_nm} min={60} max={300} step={10}
              addonAfter="NM"
              onChange={(v) => patch({ stand_lead_nm: Number(v) || 150 })} />
          </Space>
        </div>

        <div className="setting-row">
          <div>
            <div className="label">{tr("投递通道", "Channel")}</div>
            <div className="hint">{tr("Q-6：有 Hoppie 时「ACARS + 客户端」双发，机上和浮窗各一份",
              "Q-6: with Hoppie, ACARS and the client both fire")}</div>
          </div>
          <Select
            value={draft.stand_notice_channel}
            onChange={(v) => patch({ stand_notice_channel: v })}
            style={{ width: 200 }}
            options={[
              { value: "both", label: tr("ACARS + 客户端（推荐）", "ACARS + client") },
              { value: "acars", label: tr("只走 ACARS", "ACARS only") },
              { value: "system", label: tr("只走系统通知", "System toast only") },
              { value: "inapp", label: tr("只走应用内", "In-app only") },
            ]}
          />
        </div>

        <div className="setting-row">
          <div>
            <div className="label">{tr("按翼展筛选机位", "Filter stands by wingspan")}</div>
            <div className="hint">{tr("现实 navdata 没有尺寸数据时会自动跳过判断",
              "Skipped automatically when the navdata has no size data")}</div>
          </div>
          <Switch checked={draft.stand_size_filter}
            onChange={(v) => patch({ stand_size_filter: v })} />
        </div>

        <div className="setting-row">
          <div>
            <div className="label">{tr("置顶浮窗镜像", "Mirror in the always-on-top overlay")}</div>
            <div className="hint">{tr("独占全屏下会被模拟器盖住，此时靠系统通知兜底",
              "Exclusive fullscreen covers it; the system toast is the fallback")}</div>
          </div>
          <Switch checked={draft.stand_show_overlay}
            onChange={(v) => patch({ stand_show_overlay: v })} />
        </div>

        <Alert
          type={channel?.reason ? "warning" : "info"}
          showIcon
          message={`${tr("当前生效通道", "Active channel")}：${channelText}`}
          description={channel?.reason_text
            || tr("通道随「是否配了 Hoppie / 是否在跑 BeyondATC / 机型是否支持」自动切换。",
              "The channel follows Hoppie configuration, BeyondATC presence and aircraft support.")}
        />

        <div className="setting-row">
          <div>
            <div className="label">{tr("Hoppie telex 直投", "Hoppie telex")}</div>
            <div className="hint">
              {status?.configured
                ? tr(`已配置 logon：${status.masked}`, `logon configured: ${status.masked}`)
                : tr("未配置：提醒只走浮窗/系统通知（原因码 HOPPIE_NOT_CONFIGURED）",
                  "Not configured: overlay/system toast only (HOPPIE_NOT_CONFIGURED)")}
            </div>
          </div>
          <Switch checked={draft.hoppie_enabled} onChange={(v) => patch({ hoppie_enabled: v })} />
        </div>

        {draft.hoppie_enabled ? (
          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <Space wrap>
              <Input.Password
                value={logon}
                onChange={(e) => setLogon(e.target.value)}
                placeholder={tr("个人/公司站点 logon code", "personal or company logon code")}
                style={{ width: 260 }}
              />
              <Button loading={busy} onClick={() => void saveLogon()} disabled={!logon.trim()}>
                {tr("保存 logon", "Save logon")}
              </Button>
              <Button icon={<SendOutlined />} loading={busy} onClick={() => void sendTest()}
                disabled={!status?.configured}>
                {tr("发测试报文", "Send test")}
              </Button>
            </Space>
            <Space wrap>
              <Input value={draft.hoppie_from} style={{ width: 160 }}
                addonBefore={tr("发报方", "From")}
                onChange={(e) => patch({ hoppie_from: e.target.value.toUpperCase() })} />
              <Input value={draft.hoppie_callsign || ""} style={{ width: 180 }}
                addonBefore={tr("呼号", "Callsign")}
                placeholder={tr("留空用航班呼号", "empty = flight callsign")}
                onChange={(e) => patch({ hoppie_callsign: e.target.value || null })} />
            </Space>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {tr("呼号必须与机上 FLT NO / Hoppie ID 完全一致，否则报文会静默躺 24 h；「已交网络」不等于「机组已读」。",
                "The callsign must match the cockpit FLT NO / Hoppie ID exactly, otherwise the message silently expires in 24 h. Handed-to-network ≠ read.")}
            </Text>
          </Space>
        ) : null}

        <Table
          size="small"
          rowKey="type"
          pagination={false}
          dataSource={MATRIX}
          columns={[
            { title: tr("机型", "Aircraft"), dataIndex: "type" },
            { title: tr("本地 ATIS 端点", "Local ATIS"), dataIndex: "local", width: 130 },
            { title: "Hoppie", dataIndex: "hoppie" },
            {
              title: tr("状态", "State"),
              dataIndex: "state",
              width: 90,
              render: (state: string) => (
                <Tag color={state === "可用" ? "green" : state === "待实测" ? "gold" : "default"}>
                  {tr(state, state === "可用" ? "ready" : state === "待实测" ? "to test" : "overlay")}
                </Tag>
              ),
            },
          ]}
        />
      </Space>
    </Card>
  );
}
