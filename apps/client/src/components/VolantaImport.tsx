import { CloudSyncOutlined, ImportOutlined } from "@ant-design/icons";
import { Alert, Button, Divider, Input, Space, Typography, message } from "antd";
import { useState } from "react";
import { api } from "../api";
import { useI18n } from "../i18n";

const { Paragraph, Text } = Typography;

export interface VolantaSyncResult {
  ok: boolean;
  source: string;
  legs_found: number;
  legs_imported: number;
  flights_stored?: number;
  tracks_stored?: number;
  diagnostic: string;
  warnings: string[];
}

interface Props {
  onImported?: () => void | Promise<void>;
  csvRows?: number;
}

/**
 * Volanta 历史航段导入：首次向导与设置页共用同一套说明与入口。
 * Volanta 只做「已飞机场」补全，AOC 本地日志仍是权威记录（D-05）。
 */
export function VolantaImport({ onImported, csvRows = 3 }: Props) {
  const { tr } = useI18n();
  const [token, setToken] = useState("");
  const [csvText, setCsvText] = useState("");
  const [busy, setBusy] = useState<"token" | "csv" | null>(null);
  const [result, setResult] = useState<VolantaSyncResult | null>(null);

  const sync = async (mode: "token" | "csv") => {
    if (mode === "token" && !token.trim()) {
      message.warning(tr("请先粘贴 Volanta 会话 token", "Paste a Volanta session token first"));
      return;
    }
    if (mode === "csv" && !csvText.trim()) {
      message.warning(tr("请先粘贴 Volanta 导出的 CSV 内容", "Paste the exported Volanta CSV first"));
      return;
    }
    setBusy(mode);
    try {
      const body = mode === "csv" ? { csv_text: csvText } : { token: token.trim() };
      const res = await api<VolantaSyncResult>("/local/volanta/sync", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setResult(res);
      await onImported?.();
      if (res.legs_imported > 0) message.success(`${tr("已导入", "Imported")} ${res.legs_imported}`);
      else message.info(res.diagnostic || tr("没有新增记录", "Nothing new"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <Paragraph className="muted" style={{ margin: 0, fontSize: 12 }}>
        {tr(
          "Volanta 是第三方飞行记录服务。导入会把航班明细（起降、时间、机型、时长、接地率）、原始 JSON 与轨迹一并保存在本地，只增不删，不会清空已有数据；CSV 导出的数据不含轨迹。AOC 自己的飞行日志仍是权威记录，这一步可跳过。",
          "Volanta is a third-party logbook. Import stores each flight (dep/arr, date, aircraft, duration, landing rate), its raw JSON and track locally. Import only adds or updates, never wipes existing data; CSV exports have no track. AOC's own logbook stays authoritative and this step is optional.",
        )}
      </Paragraph>

      <div className="setting-row">
        <div>
          <div className="label">{tr("方式一：会话 token", "Option 1: session token")}</div>
          <div className="hint">
            {tr(
              "浏览器登录 fly.volanta.app 后按 F12，在 Network 请求头或 Application 存储里复制会话 token；只用于本次请求，不落盘。",
              "Log in to fly.volanta.app, press F12, copy the session token from a request header or Application storage. Used for this request only, never stored.",
            )}
          </div>
        </div>
      </div>
      <Input.Password
        value={token}
        onChange={(e) => setToken(e.target.value)}
        placeholder={tr("粘贴浏览器会话 token", "Paste browser session token")}
      />
      <Space wrap>
        <Button icon={<CloudSyncOutlined />} loading={busy === "token"} onClick={() => void sync("token")}>
          {tr("通过 token 导入历史", "Import with token")}
        </Button>
      </Space>

      <Divider style={{ margin: "4px 0" }}>{tr("或", "or")}</Divider>

      <div className="setting-row">
        <div>
          <div className="label">{tr("方式二：CSV 导出", "Option 2: CSV export")}</div>
          <div className="hint">
            {tr(
              "在 Volanta 网页导出飞行记录 CSV 后整段粘贴。必须能识别起降机场（origin / destination 或 ICAO 四位码）；日期、机型、时长、接地率为可选，识别不了的字段留空。",
              "Export your Volanta flight list to CSV and paste it here. Origin/destination (or 4-letter ICAO) must be present; date, aircraft, duration and landing rate are optional and left blank when unreadable.",
            )}
          </div>
        </div>
      </div>
      <Input.TextArea
        value={csvText}
        onChange={(e) => setCsvText(e.target.value)}
        rows={csvRows}
        placeholder={tr("粘贴 Volanta 导出的 CSV 内容", "Paste exported Volanta CSV")}
      />
      <Space wrap>
        <Button icon={<ImportOutlined />} loading={busy === "csv"} onClick={() => void sync("csv")}>
          {tr("导入 CSV", "Import CSV")}
        </Button>
      </Space>

      {result ? (
        <Alert
          type={result.ok ? "success" : "warning"}
          showIcon
          message={`${tr("解析", "Parsed")} ${result.legs_found} · ${tr("新增航段", "new legs")} ${result.legs_imported}`
            + ` · ${tr("保存航班", "flights")} ${result.flights_stored ?? 0}`
            + ` · ${tr("含轨迹", "with tracks")} ${result.tracks_stored ?? 0}`}
          description={[result.diagnostic, ...(result.warnings || [])].filter(Boolean).join(" · ")}
        />
      ) : null}
      <Text className="muted" style={{ fontSize: 11 }}>
        {tr(
          "Volanta 没有公开 API，token 方式为尽力而为：接口变动或登录失效会失败，改用 CSV 即可；失败不影响记录与航路。",
          "Volanta has no public API, so the token path is best-effort: it breaks when the API or session changes — fall back to CSV. Failures never block recording or routing.",
        )}
      </Text>
    </>
  );
}
