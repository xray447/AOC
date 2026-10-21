import { ExportOutlined } from "@ant-design/icons";
import { Button, Tooltip, message, type ButtonProps } from "antd";
import { useState } from "react";
import { api, openExternal } from "../api";
import { useI18n } from "../i18n";

export interface SimBriefLeg {
  rosterId?: string;
  sequence?: number;
  freeId?: string;
  flightRecordId?: string;
}

interface Props {
  dep?: string | null;
  arr?: string | null;
  aircraftType?: string | null;
  callsign?: string | null;
  /** 运营模式：带上航段标识，后端会补上配载（kg payload）与注册号。 */
  opsLeg?: SimBriefLeg;
  size?: ButtonProps["size"];
  block?: boolean;
  label?: string;
}

/** 按当前航段预填 SimBrief（起降、机型、呼号、配载），用系统默认浏览器打开。 */
export function SimBriefButton({
  dep, arr, aircraftType, callsign, opsLeg, size, block, label,
}: Props) {
  const { tr } = useI18n();
  const [busy, setBusy] = useState(false);
  const opsQuery = legQuery(opsLeg);
  const ready = Boolean(dep && arr) || Boolean(opsQuery);

  const open = async () => {
    setBusy(true);
    try {
      let url = "";
      if (opsQuery) {
        const res = await api<{ simbrief_url: string }>(`/local/ops/legs/simbrief?${opsQuery}`);
        url = res.simbrief_url;
      } else if (dep && arr) {
        const query = new URLSearchParams({ dep, arr });
        if (aircraftType) query.set("aircraft_type", aircraftType);
        if (callsign) query.set("callsign", callsign);
        const res = await api<{ simbrief_url: string }>(`/local/routes/simbrief?${query.toString()}`);
        url = res.simbrief_url;
      }
      if (url) {
        await openExternal(url);
      } else {
        message.warning(tr("无法生成 SimBrief 链接", "Cannot build a SimBrief link"));
      }
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Tooltip title={tr("按当前航段预填 SimBrief（起降、机型、呼号、配载）",
      "Prefill SimBrief with this leg (airports, type, callsign, payload)")}>
      <Button
        size={size}
        block={block}
        icon={<ExportOutlined />}
        loading={busy}
        disabled={!ready}
        onClick={() => void open()}
      >
        {label ?? "SimBrief"}
      </Button>
    </Tooltip>
  );
}

function legQuery(leg?: SimBriefLeg): string {
  if (!leg) return "";
  const query = new URLSearchParams();
  if (leg.flightRecordId) {
    query.set("flight_record_id", leg.flightRecordId);
  } else if (leg.freeId) {
    query.set("free_id", leg.freeId);
  } else if (leg.rosterId) {
    query.set("roster_id", leg.rosterId);
    if (leg.sequence) query.set("sequence", String(leg.sequence));
  }
  return query.toString();
}
