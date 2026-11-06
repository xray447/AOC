import { ApiOutlined, FolderOpenOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Space, message } from "antd";
import { useState } from "react";
import { api } from "../api";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import { openLogFolder, simlinkState } from "../simlink";

/**
 * IA-10：SimLink 状态块（三态 + 重新连接 + 日志目录）。
 * 首次向导与设置页共用一份，避免两处对「未连接」的解释不一致。
 */
export function SimlinkPanel({ showActions = true }: { showActions?: boolean }) {
  const { tr } = useI18n();
  const { recording, bootstrap, refresh } = useApp();
  const sim = simlinkState(recording);
  const [busy, setBusy] = useState(false);

  const reconnect = async () => {
    setBusy(true);
    try {
      await api("/local/simlink/reconnect", { method: "POST" });
      await refresh();
      message.success(tr("已请求重新连接，几秒后看状态", "Reconnect requested — check again in a few seconds"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const openLogs = async () => {
    const ok = await openLogFolder();
    if (!ok) message.info(`${tr("日志目录", "Log folder")}: ${bootstrap.logs || `${bootstrap.home}/logs`}`);
  };

  return (
    <div className="wizard-navdata">
      <Alert
        type={sim.level === "online" ? "success" : "warning"}
        showIcon
        message={tr(sim.zh, sim.en)}
        description={(
          <>
            {sim.level === "online"
              ? `${recording.simlink_version || ""}${sim.source ? ` · source=${sim.source}` : ""}`
              : tr("SimLink 是独立进程，负责连接 MSFS 并采集遥测。没有模拟器时可用 demo 源验证全流程。",
                "SimLink is a separate process that connects to MSFS. Without the simulator, use the demo source.")}
            {sim.level === "no-sim" && sim.error ? <div style={{ fontSize: 12, opacity: .8 }}>{sim.error}</div> : null}
          </>
        )}
      />
      {showActions ? (
        <Space wrap size={6}>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => void refresh()}>
            {tr("刷新状态", "Refresh")}
          </Button>
          <Button size="small" icon={<ApiOutlined />} loading={busy}
            disabled={!recording.simlink_connected} onClick={() => void reconnect()}>
            {tr("重新连接", "Reconnect")}
          </Button>
          <Button size="small" icon={<FolderOpenOutlined />} onClick={() => void openLogs()}>
            {tr("日志目录", "Logs")}
          </Button>
        </Space>
      ) : null}
    </div>
  );
}
