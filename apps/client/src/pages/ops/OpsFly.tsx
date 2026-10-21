import { ReloadOutlined } from "@ant-design/icons";
import { Button, Space, Tabs } from "antd";
import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useI18n } from "../../i18n";
import { OpsExecute } from "./OpsExecute";
import { OpsFreeFlightPage } from "./OpsFreeFlight";
import { OpsRosterPage } from "./OpsRoster";

type FlyTab = "roster" | "free" | "execute";

const TAB_PATH: Record<FlyTab, string> = {
  roster: "/ops/roster",
  free: "/ops/free",
  execute: "/ops/execute",
};

/** 抽班、自由飞行、配载与执行合并为一页（三个页签），旧路由继续可用。 */
export function OpsFly() {
  const { tr } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const [refreshKey, setRefreshKey] = useState(0);

  const tab = useMemo<FlyTab>(() => {
    const found = (Object.keys(TAB_PATH) as FlyTab[]).find((key) => TAB_PATH[key] === location.pathname);
    return found ?? "roster";
  }, [location.pathname]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("飞行执行", "Fly")}</h2>
          <p>{tr("抽班 → 配载 → 记录 → 结算：同一页完成一次完整航班。",
            "Draw a roster, load, record and settle — one page for the whole flight.")}</p>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => setRefreshKey((v) => v + 1)}>
            {tr("刷新", "Refresh")}
          </Button>
        </Space>
      </div>

      <Tabs
        activeKey={tab}
        onChange={(key) => navigate(TAB_PATH[key as FlyTab])}
        items={[
          {
            key: "roster",
            label: tr("抽班", "Roster"),
            children: <div key={`roster-${refreshKey}`}><OpsRosterPage embedded /></div>,
          },
          {
            key: "free",
            label: tr("自由飞行", "Free flight"),
            children: <div key={`free-${refreshKey}`}><OpsFreeFlightPage embedded /></div>,
          },
          {
            key: "execute",
            label: tr("配载与执行", "Load & execute"),
            children: <div key={`execute-${refreshKey}`}><OpsExecute embedded /></div>,
          },
        ]}
      />
    </div>
  );
}
