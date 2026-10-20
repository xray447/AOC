import { CheckCircleOutlined, FolderOpenOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Input, Modal, Space, Steps, Tag, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { api } from "../api";
import { VolantaImport } from "../components/VolantaImport";
import { useI18n } from "../i18n";
import type { NavdataStatus } from "../types";

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
  onDone: () => Promise<void>;
}

export function Onboarding({ open, onClose, onDone }: Props) {
  const { tr } = useI18n();
  const [step, setStep] = useState(0);
  const [path, setPath] = useState("");
  const [navdata, setNavdata] = useState<NavdataStatus | null>(null);
  const [simlink, setSimlink] = useState<{ connected: boolean; configured: boolean; version?: string; error?: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    api<NavdataStatus>("/local/navdata/status").then(setNavdata).catch(() => undefined);
    api<{ connected: boolean; configured: boolean }>("/local/simlink/status").then(setSimlink).catch(() => undefined);
  }, [open]);

  const checkNavdata = async () => {
    if (!path.trim()) {
      message.warning(tr("请填写 SQLite 文件路径", "Please enter the SQLite file path"));
      return;
    }
    setBusy(true);
    try {
      const status = await api<NavdataStatus>("/local/navdata/select", {
        method: "POST",
        body: JSON.stringify({ path: path.trim() }),
      });
      setNavdata(status);
      message.success(tr("navdata 已加载", "navdata loaded"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const refreshSimlink = async () => {
    try {
      setSimlink(await api("/local/simlink/status"));
    } catch {
      setSimlink({ connected: false, configured: false });
    }
  };

  return (
    <Modal
      open={open}
      width={640}
      onCancel={onClose}
      maskClosable={false}
      closable={false}
      title={tr("首次运行向导", "First-run setup")}
      footer={
        <Space>
          <Button onClick={onClose}>{tr("稍后设置", "Later")}</Button>
          {step > 0 ? <Button onClick={() => setStep((s) => s - 1)}>{tr("上一步", "Back")}</Button> : null}
          {step < 3 ? (
            <Button type="primary" onClick={() => setStep((s) => s + 1)}>{tr("下一步", "Next")}</Button>
          ) : (
            <Button type="primary" onClick={() => void onDone()}>{tr("开始使用", "Start")}</Button>
          )}
        </Space>
      }
    >
      <Steps
        size="small"
        current={step}
        style={{ marginBottom: 18 }}
        items={[
          { title: tr("导航数据", "navdata") },
          { title: "SimLink" },
          { title: tr("Volanta（可选）", "Volanta (optional)") },
          { title: tr("完成", "Finish") },
        ]}
      />
      {step === 0 ? (
        <div className="wizard-navdata">
          <Paragraph className="muted" style={{ margin: 0 }}>
            {tr(
              "AOC 不随包分发导航数据。请选择本机 Little Navmap / Navigraph 的 SQLite（AIRAC 版本会自动识别）；不提供也能记录飞行，但航路生成会直接给 SimBrief。",
              "AOC does not bundle navdata. Point to your Little Navmap / Navigraph SQLite (AIRAC is detected). Without it you can still record flights, but route generation falls back to SimBrief.",
            )}
          </Paragraph>
          <Input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="%APPDATA%\\ABarthel\\little_navmap_db\\little_navmap_navigraph.sqlite"
            prefix={<FolderOpenOutlined />}
            onPressEnter={() => void checkNavdata()}
          />
          <Space>
            <Button type="primary" loading={busy} onClick={() => void checkNavdata()}>
              {tr("检测并保存", "Check & save")}
            </Button>
            {navdata?.available ? (
              <Tag color="green" icon={<CheckCircleOutlined />}>
                AIRAC {navdata.airac} · {navdata.airports} {tr("机场", "airports")}
              </Tag>
            ) : null}
          </Space>
          {navdata && !navdata.available ? (
            <Alert type="info" showIcon message={navdata.error || tr("未导入 navdata", "navdata missing")} />
          ) : null}
          <Text className="muted" style={{ fontSize: 12 }}>
            {tr("也可以稍后在「设置 → 数据源」中导入。", "You can also import it later in Settings → Data sources.")}
          </Text>
        </div>
      ) : null}
      {step === 1 ? (
        <div className="wizard-navdata">
          <Paragraph className="muted" style={{ margin: 0 }}>
            {tr(
              "SimLink 是独立进程，负责连接 MSFS 并采集遥测。没有模拟器时可用 demo 源验证全流程。",
              "SimLink is a separate process that connects to MSFS. Without the simulator, use the demo source to verify the flow.",
            )}
          </Paragraph>
          <Alert
            type={simlink?.connected ? "success" : "warning"}
            showIcon
            message={simlink?.connected
              ? tr("SimLink 已连接", "SimLink connected")
              : tr("SimLink 未连接", "SimLink offline")}
            description={simlink?.connected
              ? `${tr("版本", "Version")} ${simlink.version || "—"}`
              : <code>aoc-simlink.exe --demo --port 0</code>}
          />
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void refreshSimlink()}>{tr("刷新状态", "Refresh")}</Button>
            <Text className="muted" style={{ fontSize: 12 }}>
              {tr("Tauri 客户端会自动拉起 SimLink；浏览器模式需手动启动。", "The Tauri client starts SimLink automatically; browser mode needs a manual launch.")}
            </Text>
          </Space>
        </div>
      ) : null}
      {step === 2 ? (
        <div className="wizard-navdata">
          <VolantaImport csvRows={3} />
          <Text className="muted" style={{ fontSize: 12 }}>
            {tr(
              "跳过也没关系：随时可在「设置 → 数据源 → Volanta 同步」里导入历史航段。",
              "Safe to skip: import historical legs anytime in Settings → Data sources → Volanta sync.",
            )}
          </Text>
        </div>
      ) : null}
      {step === 3 ? (
        <div className="wizard-navdata">
          <Alert
            type="success"
            showIcon
            message={tr("准备就绪", "Ready")}
            description={tr(
              "下一步：在首页开始记录（或让 SimLink 自动起飞检测），落地后会自动生成飞行日志、轨迹与落地评估。",
              "Next: start recording on Home (or let SimLink auto-detect takeoff). Landing creates the logbook entry, track and landing report.",
            )}
          />
          <div className="source-grid">
            <div className="source-card">
              <div className="source-title">{tr("导航数据", "navdata")}<Tag color={navdata?.available ? "blue" : "default"}>{navdata?.available ? navdata.airac : "—"}</Tag></div>
              <div className="source-value">{navdata?.available ? navdata.path : tr("未导入，航路走 SimBrief", "Not imported; routes use SimBrief")}</div>
            </div>
            <div className="source-card">
              <div className="source-title">{tr("遥测", "Telemetry")}<Tag color={simlink?.connected ? "green" : "default"}>{simlink?.connected ? "SimLink" : "offline"}</Tag></div>
              <div className="source-value">{tr("可在设置中查看状态与采样密度", "Check status and sampling density in Settings")}</div>
            </div>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
