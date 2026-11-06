import { DatabaseOutlined, FolderOpenOutlined } from "@ant-design/icons";
import { Alert, Button, Input, Space, Tag, Typography, message } from "antd";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import type { NavdataStatus } from "../types";

const { Text, Paragraph } = Typography;

interface Props {
  /** 输入框上方的说明（首次向导里用；设置页不传）。 */
  description?: ReactNode;
  /** 输入框下方的补充内容（设置页的场景库/SQLite 来源等）。 */
  children?: ReactNode;
  onLoaded?: (status: NavdataStatus) => void;
}

/**
 * IA-10：navdata 选择块（状态 + 路径 + 检测并保存）。
 * 以前首次向导与「设置 → 数据源」各写一遍，文案和错误处理已经开始漂移。
 */
export function NavdataPanel({ description, children, onLoaded }: Props) {
  const { tr } = useI18n();
  const { navdata, settings, refresh } = useApp();
  const [path, setPath] = useState(settings.navdata_path || "");
  const [busy, setBusy] = useState(false);

  // 设置保存/切换库后，输入框跟着最新值走（组件在设置页里是长期挂载的）
  useEffect(() => {
    setPath(settings.navdata_path || "");
  }, [settings.navdata_path]);

  const select = async () => {
    if (!path.trim()) {
      // 空路径 = 清除：仍交给后端判定（与设置页「清除」按钮一致）
      message.info(tr("未填写路径：将清除已保存的 navdata", "Empty path clears the saved navdata"));
    }
    setBusy(true);
    try {
      const status = await api<NavdataStatus>("/local/navdata/select", {
        method: "POST",
        body: JSON.stringify({ path: path.trim() || null }),
      });
      await refresh();
      onLoaded?.(status);
      if (status.available) {
        message.success(tr("navdata 已加载", "navdata loaded"));
      } else {
        message.warning(status.error || tr("未加载", "not loaded"));
      }
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="wizard-navdata">
      {description ? <Paragraph className="muted" style={{ margin: 0 }}>{description}</Paragraph> : null}

      <div className="setting-row">
        <div>
          <div className="label">
            {tr("navdata（Little Navmap / Navigraph SQLite）", "navdata (Little Navmap / Navigraph SQLite)")}
          </div>
          <div className="hint">
            {navdata.available ? `AIRAC ${navdata.airac} · ${navdata.airports} ${tr("机场", "airports")}` : navdata.error}
          </div>
        </div>
        <Tag color={navdata.available ? "blue" : "default"}>
          {navdata.available ? tr("已加载", "loaded") : tr("未加载", "missing")}
        </Tag>
      </div>

      <Input
        value={path}
        onChange={(e) => setPath(e.target.value)}
        placeholder="%APPDATA%\\ABarthel\\little_navmap_db\\little_navmap_navigraph.sqlite"
        prefix={<FolderOpenOutlined />}
        onPressEnter={() => void select()}
      />
      <Space>
        <Button type="primary" icon={<DatabaseOutlined />} loading={busy} onClick={() => void select()}>
          {tr("检测并保存", "Check & save")}
        </Button>
        {navdata.available ? (
          <Text className="muted" style={{ fontSize: 12 }}>AIRAC {navdata.airac}</Text>
        ) : null}
      </Space>

      {!navdata.available && navdata.error ? (
        <Alert type="info" showIcon message={navdata.error} />
      ) : null}

      {children}
    </div>
  );
}
