import {
  ApiOutlined,
  AppstoreOutlined,
  AuditOutlined,
  BankOutlined,
  CarOutlined,
  CheckSquareOutlined,
  ClockCircleOutlined,
  CloudServerOutlined,
  CompassOutlined,
  DashboardOutlined,
  GlobalOutlined,
  LineChartOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  ReloadOutlined,
  RocketOutlined,
  SettingOutlined,
  ShopOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Badge, Button, ConfigProvider, Layout, Menu, Space, Spin, Tag, Tooltip,
  theme as antdTheme, type MenuProps,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, initApi } from "./api";
import type { AppContextValue } from "./context";
import { I18nProvider, useI18n } from "./i18n";
import { Onboarding } from "./pages/Onboarding";
import { Dashboard } from "./pages/Dashboard";
import { OpsFinance } from "./pages/ops/OpsFinance";
import { OpsFleet } from "./pages/ops/OpsFleet";
import { OpsFly } from "./pages/ops/OpsFly";
import { OpsHome } from "./pages/ops/OpsHome";
import { OpsNetwork } from "./pages/ops/OpsNetwork";
import { OpsReview } from "./pages/ops/OpsReview";
import { OpsRules } from "./pages/ops/OpsRules";
import { Online } from "./pages/Online";
import { Recommend } from "./pages/Recommend";
import { RoutePlanner } from "./pages/RoutePlanner";
import { Logs } from "./pages/Logs";
import { LogDetail } from "./pages/LogDetail";
import { MapPage } from "./pages/MapPage";
import { Stats } from "./pages/Stats";
import { SettingsPage } from "./pages/Settings";
import { opsStateMeta } from "./ops";
import type { Bootstrap, NavdataStatus, OpsStatus, RecordingStatus, Settings } from "./types";
import { fmtHms } from "./utils";

const { Header, Sider, Content } = Layout;

function useDarkMode(settings: Settings | null): boolean {
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener?.("change", handler);
    return () => mq.removeEventListener?.("change", handler);
  }, []);
  if (!settings) return true;
  if (settings.theme === "dark") return true;
  if (settings.theme === "light") return false;
  return systemDark;
}

function Shell({ bootstrap, settings, navdata, recording, opsStatus, refresh, saveSettings, dark }: AppContextValue) {
  const { tr } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const selected = useMemo(() => {
    if (location.pathname.startsWith("/logs")) return "/logs";
    if (location.pathname.startsWith("/ops")) {
      const path = "/" + location.pathname.split("/").slice(1, 3).join("/");
      // 合并页：子页签路由仍高亮同一个菜单项
      if (["/ops/roster", "/ops/free", "/ops/execute"].includes(path)) return "/ops/fly";
      if (["/ops/settlements", "/ops/ledger"].includes(path)) return "/ops/finance";
      return path;
    }
    return location.pathname;
  }, [location.pathname]);

  const personalItems = [
    { key: "/", icon: <DashboardOutlined />, label: tr("首页", "Home") },
    { key: "/recommend", icon: <CompassOutlined />, label: tr("推荐", "Discover") },
    { key: "/route", icon: <RocketOutlined />, label: tr("航路", "Routes") },
    { key: "/logs", icon: <AppstoreOutlined />, label: tr("日志", "Logbook") },
    { key: "/map", icon: <GlobalOutlined />, label: tr("地图", "Map") },
    { key: "/stats", icon: <LineChartOutlined />, label: tr("统计", "Stats") },
    { key: "/settings", icon: <SettingOutlined />, label: tr("设置", "Settings") },
  ];
  const opsItems = [
    { key: "/ops", icon: <ShopOutlined />, label: tr("运营概览", "Overview") },
    { key: "/ops/fleet", icon: <CarOutlined />, label: tr("机队", "Fleet") },
    { key: "/ops/network", icon: <ThunderboltOutlined />, label: tr("航线与班期", "Network") },
    { key: "/ops/fly", icon: <RocketOutlined />, label: tr("飞行执行", "Fly") },
    { key: "/ops/finance", icon: <BankOutlined />, label: tr("财务", "Finance") },
    { key: "/ops/rules", icon: <AuditOutlined />, label: tr("运营规则", "Rules") },
    { key: "/ops/review", icon: <CheckSquareOutlined />, label: tr("复核队列", "Review") },
    { key: "/ops/online", icon: <CloudServerOutlined />, label: tr("联机模式", "Online") },
  ];
  const items: MenuProps["items"] = [
    { type: "group", key: "g-personal", label: tr("个人模式", "Personal"), children: personalItems },
    { type: "group", key: "g-ops", label: tr("运营模式", "Operations"), children: opsItems },
  ];
  const flatItems = [...personalItems, ...opsItems];
  const statusMeta = opsStateMeta(opsStatus);
  const statusDetail = [
    opsStatus?.callsign,
    opsStatus?.dep_icao && opsStatus?.arr_icao ? `${opsStatus.dep_icao}→${opsStatus.arr_icao}` : null,
  ].filter(Boolean).join(" · ");

  return (
    <Layout className="app-shell">
      <Sider className="app-sider" collapsible collapsed={collapsed} trigger={null} width={216}>
        <div className="brand" onClick={() => navigate("/")}>
          <div className="brand-mark">AOC</div>
          {!collapsed ? (
            <div className="brand-text">
              <strong>{tr("模拟飞行运行中心", "Virtual Operations")}</strong>
              <span>{tr("个人模式", "Personal")} · v{bootstrap.version}</span>
            </div>
          ) : null}
        </div>
        <Menu
          mode="inline"
          theme="dark"
          selectedKeys={[selected]}
          items={items}
          onClick={({ key }) => navigate(key)}
        />
        <div className="sider-footer">
          {!collapsed ? (
            <div className="muted" style={{ fontSize: 11, lineHeight: 1.5 }}>
              {tr("单机运营（M2）数据在本机；「联机模式」可登录公司服务端抽班与同步（M3）。",
                "Single-player data stays local; Online mode connects to a company server (M3).")}
            </div>
          ) : null}
        </div>
      </Sider>
      <Layout>
        <Header className="app-header">
          <Space size={10}>
            <Button
              type="text"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed((v) => !v)}
            />
            <div className="page-title">{flatItems.find((i) => i.key === selected)?.label}</div>
          </Space>
          <Space size={8} wrap>
            <Tooltip title={navdata.available ? `${navdata.airports} ${tr("个机场", "airports")} · AIRAC ${navdata.airac}` : navdata.error}>
              <Tag color={navdata.available ? "blue" : "default"} icon={<ApiOutlined />}>
                {navdata.available ? `AIRAC ${navdata.airac || "—"}` : tr("navdata 未导入", "navdata missing")}
              </Tag>
            </Tooltip>
            <Tag color={recording.simlink_connected ? "green" : "default"}>
              {recording.simlink_connected ? tr("SimLink 已连接", "SimLink online") : tr("SimLink 离线", "SimLink offline")}
            </Tag>
            <Tooltip title={`${tr("当前状态，点击进入对应页面", "Current state — click to open")}${statusDetail ? `（${statusDetail}）` : ""}`}>
              <Button
                size="small"
                type={statusMeta.state === "FLIGHT" ? "primary" : "default"}
                icon={statusMeta.state === "FLIGHT" ? <RocketOutlined />
                  : statusMeta.state === "GROUND" ? <CarOutlined /> : <ClockCircleOutlined />}
                onClick={() => navigate(statusMeta.path)}
              >
                {tr(statusMeta.zh, statusMeta.en)}
                {statusDetail ? ` · ${statusDetail}` : ""}
              </Button>
            </Tooltip>
            {recording.active ? (
              <Link to="/">
                <Badge status="processing" text={`${tr("记录中", "Recording")} · ${tr("发动机", "Engine")} ${fmtHms(recording.engine_seconds)} · ${tr("已飞", "Airborne")} ${fmtHms(recording.flight_seconds)} · ${recording.phase}`} />
              </Link>
            ) : null}
            <Button icon={<ReloadOutlined />} size="small" onClick={() => void refresh()}>
              {tr("刷新", "Refresh")}
            </Button>
          </Space>
        </Header>
        <Content className="app-content">
          <Outlet context={{ bootstrap, settings, navdata, recording, opsStatus, dark, refresh, saveSettings } satisfies AppContextValue} />
        </Content>
      </Layout>
    </Layout>
  );
}

export default function App() {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [navdata, setNavdata] = useState<NavdataStatus | null>(null);
  const [recording, setRecording] = useState<RecordingStatus | null>(null);
  const [opsStatus, setOpsStatus] = useState<OpsStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showWizard, setShowWizard] = useState(false);

  const load = useCallback(async () => {
    const boot = await initApi();
    const [settingsRes, navRes, recRes, statusRes] = await Promise.all([
      api<{ settings: Settings }>("/local/settings"),
      api<NavdataStatus>("/local/navdata/status"),
      api<RecordingStatus>("/local/recording/status"),
      api<OpsStatus>("/local/ops/status").catch(() => null),
    ]);
    setBootstrap(boot);
    setSettings(settingsRes.settings);
    setNavdata(navRes);
    setRecording(recRes);
    setOpsStatus(statusRes);
    if (!settingsRes.settings.onboarded) setShowWizard(true);
  }, []);

  useEffect(() => {
    load().catch((e: Error) => setError(e.message));
  }, [load]);

  useEffect(() => {
    if (!bootstrap) return;
    const timer = window.setInterval(async () => {
      try {
        const [rec, status] = await Promise.all([
          api<RecordingStatus>("/local/recording/status"),
          api<OpsStatus>("/local/ops/status").catch(() => null),
        ]);
        setRecording(rec);
        setOpsStatus(status);
      } catch {
        /* core may be restarting */
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [bootstrap]);

  const refresh = useCallback(async () => {
    const [settingsRes, navRes, recRes, statusRes] = await Promise.all([
      api<{ settings: Settings }>("/local/settings"),
      api<NavdataStatus>("/local/navdata/status"),
      api<RecordingStatus>("/local/recording/status"),
      api<OpsStatus>("/local/ops/status").catch(() => null),
    ]);
    setSettings(settingsRes.settings);
    setNavdata(navRes);
    setRecording(recRes);
    setOpsStatus(statusRes);
  }, []);

  const saveSettings = useCallback(async (patch: Partial<Settings>) => {
    const res = await api<{ settings: Settings }>("/local/settings", {
      method: "PUT",
      body: JSON.stringify(patch),
    });
    setSettings(res.settings);
    try {
      setNavdata(await api<NavdataStatus>("/local/navdata/status"));
    } catch {
      /* ignore */
    }
    return res.settings;
  }, []);

  // 用稳定的 setLang，避免每 2s 轮询导致 I18n context 变化、地图被反复重建
  const changeLang = useCallback((language: Settings["language"]) => {
    void saveSettings({ language });
  }, [saveSettings]);

  const dark = useDarkMode(settings);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
  }, [dark]);

  if (error) {
    return (
      <div className="boot-error">
        <h2>AOC core 未连接</h2>
        <p>{error}</p>
        <p className="muted">请先启动 <code>python apps/aoc-core/main.py --port 8765</code>，或使用便携包 / Tauri 客户端。</p>
        <Button type="primary" onClick={() => window.location.reload()}>重试</Button>
      </div>
    );
  }

  if (!bootstrap || !settings || !navdata || !recording) {
    return <div className="boot-loading"><Spin size="large" /><p>正在加载 AOC…</p></div>;
  }

  return (
    <I18nProvider lang={settings.language} setLang={changeLang}>
      <ConfigProvider
        button={{ autoInsertSpace: false }}
        theme={{
          algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
          token: {
            colorPrimary: "#0ea5e9",
            borderRadius: 9,
            colorBgLayout: dark ? "#070b14" : "#f3f6fa",
            fontFamily: '"Segoe UI", "Microsoft YaHei", system-ui, sans-serif',
          },
          components: {
            Card: { borderRadiusLG: 12 },
            Menu: { itemBorderRadius: 8 },
          },
        }}
      >
        <Routes>
          <Route
            element={
              <Shell
                bootstrap={bootstrap}
                settings={settings}
                navdata={navdata}
                recording={recording}
                opsStatus={opsStatus}
                dark={dark}
                refresh={refresh}
                saveSettings={saveSettings}
              />
            }
          >
            <Route index element={<Dashboard />} />
            <Route path="recommend" element={<Recommend />} />
            <Route path="route" element={<RoutePlanner />} />
            <Route path="logs" element={<Logs />} />
            <Route path="logs/:id" element={<LogDetail />} />
            <Route path="map" element={<MapPage />} />
            <Route path="stats" element={<Stats />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="ops" element={<OpsHome />} />
            <Route path="ops/fleet" element={<OpsFleet />} />
            <Route path="ops/network" element={<OpsNetwork />} />
            <Route path="ops/fly" element={<OpsFly />} />
            <Route path="ops/roster" element={<OpsFly />} />
            <Route path="ops/execute" element={<OpsFly />} />
            <Route path="ops/free" element={<OpsFly />} />
            <Route path="ops/finance" element={<OpsFinance />} />
            <Route path="ops/settlements" element={<OpsFinance />} />
            <Route path="ops/ledger" element={<OpsFinance />} />
            <Route path="ops/rules" element={<OpsRules />} />
            <Route path="ops/review" element={<OpsReview />} />
            <Route path="ops/online" element={<Online />} />
          </Route>
        </Routes>
        <Onboarding
          open={showWizard}
          onClose={() => setShowWizard(false)}
          onDone={async () => {
            await saveSettings({ onboarded: true });
            setShowWizard(false);
          }}
        />
      </ConfigProvider>
    </I18nProvider>
  );
}
