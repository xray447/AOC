import {
  ApiOutlined,
  AppstoreOutlined,
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
} from "@ant-design/icons";
import { Badge, Button, ConfigProvider, Layout, Menu, Space, Spin, Tag, Tooltip, theme as antdTheme } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, initApi } from "./api";
import type { AppContextValue } from "./context";
import { I18nProvider, useI18n } from "./i18n";
import { Onboarding } from "./pages/Onboarding";
import { Dashboard } from "./pages/Dashboard";
import { Recommend } from "./pages/Recommend";
import { RoutePlanner } from "./pages/RoutePlanner";
import { Logs } from "./pages/Logs";
import { LogDetail } from "./pages/LogDetail";
import { MapPage } from "./pages/MapPage";
import { Stats } from "./pages/Stats";
import { SettingsPage } from "./pages/Settings";
import type { Bootstrap, NavdataStatus, RecordingStatus, Settings } from "./types";

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

function Shell({ bootstrap, settings, navdata, recording, refresh, saveSettings, dark }: AppContextValue) {
  const { tr } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const selected = useMemo(() => {
    if (location.pathname.startsWith("/logs")) return "/logs";
    if (location.pathname.startsWith("/admin")) return "/admin";
    return location.pathname;
  }, [location.pathname]);

  const items = [
    { key: "/", icon: <DashboardOutlined />, label: tr("首页", "Home") },
    { key: "/recommend", icon: <CompassOutlined />, label: tr("推荐", "Discover") },
    { key: "/route", icon: <RocketOutlined />, label: tr("航路", "Routes") },
    { key: "/logs", icon: <AppstoreOutlined />, label: tr("日志", "Logbook") },
    { key: "/map", icon: <GlobalOutlined />, label: tr("地图", "Map") },
    { key: "/stats", icon: <LineChartOutlined />, label: tr("统计", "Stats") },
    { key: "/settings", icon: <SettingOutlined />, label: tr("设置", "Settings") },
  ];

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
          <Tooltip title={tr("公司模式（M2）", "Company mode (M2)")}>
            <Menu
              mode="inline"
              theme="dark"
              selectable={false}
              items={[{ key: "company", icon: <CloudServerOutlined />, label: tr("公司模式（未开放）", "Company (soon)"), disabled: true }]}
            />
          </Tooltip>
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
            <div className="page-title">{items.find((i) => i.key === selected)?.label}</div>
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
            {recording.active ? (
              <Link to="/">
                <Badge status="processing" text={`${tr("记录中", "Recording")} · ${recording.samples} pts · ${recording.phase}`} />
              </Link>
            ) : null}
            <Button icon={<ReloadOutlined />} size="small" onClick={() => void refresh()}>
              {tr("刷新", "Refresh")}
            </Button>
          </Space>
        </Header>
        <Content className="app-content">
          <Outlet context={{ bootstrap, settings, navdata, recording, dark, refresh, saveSettings } satisfies AppContextValue} />
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
  const [error, setError] = useState<string | null>(null);
  const [showWizard, setShowWizard] = useState(false);

  const load = useCallback(async () => {
    const boot = await initApi();
    const [settingsRes, navRes, recRes] = await Promise.all([
      api<{ settings: Settings }>("/local/settings"),
      api<NavdataStatus>("/local/navdata/status"),
      api<RecordingStatus>("/local/recording/status"),
    ]);
    setBootstrap(boot);
    setSettings(settingsRes.settings);
    setNavdata(navRes);
    setRecording(recRes);
    if (!settingsRes.settings.onboarded) setShowWizard(true);
  }, []);

  useEffect(() => {
    load().catch((e: Error) => setError(e.message));
  }, [load]);

  useEffect(() => {
    if (!bootstrap) return;
    const timer = window.setInterval(async () => {
      try {
        const rec = await api<RecordingStatus>("/local/recording/status");
        setRecording(rec);
      } catch {
        /* core may be restarting */
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [bootstrap]);

  const refresh = useCallback(async () => {
    const [settingsRes, navRes, recRes] = await Promise.all([
      api<{ settings: Settings }>("/local/settings"),
      api<NavdataStatus>("/local/navdata/status"),
      api<RecordingStatus>("/local/recording/status"),
    ]);
    setSettings(settingsRes.settings);
    setNavdata(navRes);
    setRecording(recRes);
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
