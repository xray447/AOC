import { AimOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  Alert, Button, Card, Descriptions, Input, Modal, Space, Tag, Typography, message,
} from "antd";
import { useState } from "react";
import { api } from "../api";
import { useI18n } from "../i18n";
import type { FlightStand, FlightStatus, StandNotice } from "../types";
import { fmtUtc } from "../ops";

const { Text } = Typography;

const sourceLabels: Record<string, { zh: string; en: string; color: string }> = {
  scenery: { zh: "游戏内场景库", en: "in-game scenery", color: "green" },
  navdata: { zh: "现实 navdata（无尺寸）", en: "real navdata (no size)", color: "gold" },
  override: { zh: "手工覆盖", en: "manual override", color: "purple" },
  learned: { zh: "历史样本", en: "learned", color: "cyan" },
  none: { zh: "无机位数据", en: "no stand data", color: "default" },
};

const confidenceLabels: Record<string, { zh: string; en: string; color: string }> = {
  high: { zh: "置信度高", en: "high confidence", color: "green" },
  medium: { zh: "置信度中", en: "medium confidence", color: "blue" },
  low: { zh: "置信度低", en: "low confidence", color: "default" },
};

const channelLabels: Record<string, { zh: string; en: string; color: string }> = {
  acars: { zh: "Hoppie ACARS（机内）", en: "Hoppie ACARS (in cockpit)", color: "green" },
  overlay: { zh: "AOC 浮窗 + 系统通知", en: "AOC overlay + system toast", color: "blue" },
  batc: { zh: "BeyondATC 权威", en: "BeyondATC authoritative", color: "orange" },
};

/** docs/12：执行页「到达信息」卡（机位、来源、ETA 置信度、通道与原因码）。 */
export function StandCard({ status, arrIcao, onChanged }: {
  status: FlightStatus | null;
  arrIcao?: string | null;
  onChanged?: () => void;
}) {
  const { tr } = useI18n();
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState<string>("");
  const [open, setOpen] = useState(false);
  const stand: FlightStand | null = status?.stand || null;
  const channel = status?.stand_channel || null;
  const notice: StandNotice | null = status?.notice || null;
  const source = sourceLabels[stand?.source || "none"] || sourceLabels.none;
  const confidence = status?.eta_confidence ? confidenceLabels[status.eta_confidence] : null;

  const post = async (body: Record<string, unknown>) => {
    if (!stand?.flight_record_id && !status) return;
    setBusy(true);
    try {
      const flightId = stand?.flight_record_id;
      if (!flightId) {
        message.warning(tr("还没有航班记录，无法指定机位", "No flight record yet"));
        return;
      }
      await api(`/local/flights/${flightId}/stand`, {
        method: "POST", body: JSON.stringify(body),
      });
      message.success(tr("机位已更新", "Stand updated"));
      onChanged?.();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const recalc = () => void post({ force: true });

  return (
    <Card
      className="panel"
      variant="borderless"
      title={tr("到达信息", "Arrival")}
      extra={(
        <Space size={8}>
          <Button size="small" icon={<ReloadOutlined />} loading={busy} onClick={recalc}>
            {tr("重算机位", "Recompute")}
          </Button>
          <Button size="small" icon={<AimOutlined />} onClick={() => setOpen(true)}>
            {tr("手工指定", "Set manually")}
          </Button>
        </Space>
      )}
    >
      {channel?.channel === "batc" ? (
        <Alert
          type="warning"
          showIcon
          message={tr("由 BeyondATC 分配，请以地面滑行许可为准",
            "Assigned by BeyondATC — follow the ground taxi clearance")}
          description={tr("AOC 不推机位，避免机组同时收到两个不同机位（Q-7）。",
            "AOC stays out of the way so the crew never receives two different stands (Q-7).")}
        />
      ) : (
        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }}>
          <Descriptions.Item label={tr("预计停机位", "Expected stand")}>
            {stand?.stand_ident
              ? <Text strong style={{ fontSize: 20 }}>{stand.stand_ident}</Text>
              : <Text type="secondary">{tr("该机场没有停机位数据", "No stand data for this airport")}</Text>}
            {stand?.has_jetway ? <Tag color="green" style={{ marginLeft: 8 }}>{tr("廊桥", "Jetway")}</Tag> : null}
            {stand?.terminal_source === "rule"
              ? <Tag color="blue" style={{ marginLeft: 6 }}>{tr("按承运人规则", "carrier rule")}</Tag>
              : null}
          </Descriptions.Item>
          <Descriptions.Item label={tr("来源", "Source")}>
            <Tag color={source.color}>{tr(source.zh, source.en)}</Tag>
            {stand?.stand_type ? <Tag>{stand.stand_type}</Tag> : null}
            {stand?.radius_m ? <Tag>{Math.round(stand.radius_m)} m</Tag> : null}
          </Descriptions.Item>
          <Descriptions.Item label={tr("到达机场", "Arrival")}>
            {stand?.airport_icao || arrIcao || "—"}
          </Descriptions.Item>
          <Descriptions.Item label={tr("修正 ETA", "Refined ETA")}>
            {status?.eta_refined_min != null
              ? `${Math.round(status.eta_refined_min)} min · ${fmtUtc(status.eta_refined_utc)}`
              : "—"}
            {confidence ? <Tag color={confidence.color} style={{ marginLeft: 6 }}>
              {tr(confidence.zh, confidence.en)}
            </Tag> : null}
          </Descriptions.Item>
          <Descriptions.Item label={tr("剩余距离", "Remaining")}>
            {status?.remaining_nm != null ? `${Math.round(status.remaining_nm)} NM` : "—"}
          </Descriptions.Item>
          <Descriptions.Item label={tr("投递通道", "Channel")}>
            {channel ? (
              <Tag color={(channelLabels[channel.channel] || {}).color}>
                {channelLabels[channel.channel]
                  ? tr(channelLabels[channel.channel].zh, channelLabels[channel.channel].en)
                  : channel.channel}
              </Tag>
            ) : "—"}
          </Descriptions.Item>
        </Descriptions>
      )}

      {channel?.reason_text ? (
        <Alert
          style={{ marginTop: 8 }}
          type={channel.reason === "BATC_AUTHORITATIVE" ? "warning" : "info"}
          showIcon
          message={channel.reason_text}
          description={tr("降级原因码会同时写进通知 payload，复盘时可查。",
            "The reason code is stored with the notice payload for later review.")}
        />
      ) : null}

      {notice ? (
        <Alert
          style={{ marginTop: 8 }}
          type={notice.kind === "STAND_CHANGED" ? "warning" : "success"}
          showIcon
          message={notice.title}
          description={(
            <Space direction="vertical" size={2}>
              <span>{notice.body}</span>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {notice.created_at}
                {notice.payload?.acars?.verdict
                  ? ` · ACARS ${notice.payload.acars.verdict}`
                  : ""}
              </Text>
            </Space>
          )}
        />
      ) : (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {tr("到达前（默认 30 min / 150 NM）只提醒一次；机位定稿后不再因 ETA 抖动改口。",
            "One reminder before arrival (30 min / 150 NM by default); the stand is frozen once assigned.")}
        </Text>
      )}

      <Modal
        title={tr("手工指定机位", "Set stand manually")}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => {
          setOpen(false);
          void post({ stand_ident: manual.trim().toUpperCase(), force: true });
        }}
        okText={tr("保存", "Save")}
        cancelText={tr("取消", "Cancel")}
      >
        <Input
          value={manual}
          onChange={(e) => setManual(e.target.value)}
          placeholder={tr("机位编号，如 532 / 212R", "Stand ident, e.g. 532 / 212R")}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          {tr("只改 AOC 侧信息，模拟器里飞机停在哪仍由你决定。",
            "This only changes the AOC information; parking the aircraft is still up to you.")}
        </Text>
      </Modal>
    </Card>
  );
}
