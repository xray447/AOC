import { Alert, Button, Modal, Space, Steps, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { NavdataPanel } from "../components/NavdataPanel";
import { SimlinkPanel } from "../components/SimlinkPanel";
import { VolantaImport } from "../components/VolantaImport";
import { useI18n } from "../i18n";

const { Text } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
  onDone: () => Promise<void>;
}

/**
 * 首次运行向导（IA-10）：只做「步骤编排」，navdata 与 SimLink 两个块与设置页共用，
 * 避免同一块面板在两处各写一遍、文案与错误处理漂移。
 */
export function Onboarding({ open, onClose, onDone }: Props) {
  const { tr } = useI18n();
  const [step, setStep] = useState(0);

  // 从设置页「重新运行向导」再打开时，回到第一步
  useEffect(() => {
    if (open) setStep(0);
  }, [open]);

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
        <NavdataPanel
          description={tr(
            "AOC 不随包分发导航数据。请选择本机 Navigraph 的 Little Navmap 的 SQLite（AIRAC 版本会自动识别），如果没有，请自行获得，只需要navigraph的数据库就行，不需要安装Little Navmap；不提供也能记录飞行，但航路生成会直接给 SimBrief。",
            "AOC does not bundle navdata. Point to your Little Navmap / Navigraph SQLite (AIRAC is detected). Without it you can still record flights, but route generation falls back to SimBrief.",
          )}
        />
      ) : null}
      {step === 1 ? <SimlinkPanel showActions={false} /> : null}
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
          <Tag color="blue">
            {tr("向导随时可在「设置 → 数据源」重新运行", "Re-run this wizard anytime from Settings → Data sources")}
          </Tag>
        </div>
      ) : null}
    </Modal>
  );
}
