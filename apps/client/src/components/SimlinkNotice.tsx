import { FolderOpenOutlined } from "@ant-design/icons";
import { Alert, Button, Space, Typography, message } from "antd";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import { openLogFolder, simlinkState } from "../simlink";

const { Text } = Typography;

/**
 * 「SimLink 在运行，但没连上模拟器」时的排查提示（首页、执行页共用）。
 * 连上了 / SimLink 没起时都不渲染（前者不需要提示，后者是另一条建议）。
 */
export function SimlinkNotice({ style }: { style?: React.CSSProperties }) {
  const { tr } = useI18n();
  const { recording, bootstrap } = useApp();
  const state = simlinkState(recording);
  if (state.level !== "no-sim") return null;

  const logsPath = bootstrap?.logs || `${bootstrap?.home || ""}/logs`;
  return (
    <Alert
      type="warning"
      showIcon
      style={style}
      message={tr("SimLink 在运行，但没连上模拟器", "SimLink is running but the simulator is not connected")}
      description={(
        <Space direction="vertical" size={4} style={{ width: "100%" }}>
          <span>
            {tr(
              "1) 启动 MSFS 2020/2024 并进到座舱；2) SimLink 每 5s 自动重连（也可在设置页点「重新连接」）；3) 仍不行看日志里的 “source start failed”。",
              "1) Start MSFS 2020/2024 and get into the cockpit; 2) SimLink retries every 5s (or press Reconnect in Settings); 3) If it still fails, look for “source start failed” in the log.",
            )}
          </span>
          <Space wrap size={8}>
            <Button
              size="small"
              icon={<FolderOpenOutlined />}
              onClick={() => {
                void openLogFolder().then((ok) => {
                  if (!ok) message.info(`${tr("日志目录", "Log folder")}: ${logsPath}`);
                });
              }}
            >
              {tr("打开日志目录", "Open log folder")}
            </Button>
            <Text className="muted" style={{ fontSize: 12 }}>{logsPath}</Text>
          </Space>
          {state.error ? (
            <Text type="secondary" style={{ fontSize: 12 }}>{state.error}</Text>
          ) : null}
        </Space>
      )}
    />
  );
}
