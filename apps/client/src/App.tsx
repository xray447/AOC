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
import { ErrorBoundary } from "./components/ErrorBoundary";
import type { AppContextValue } from "./context";
import { I18nProvider, useI18n } from "./i18n";
import { confirmLeave } from "./leaveGuard";
import { Onboarding } from "./pages/Onboarding";
import { Dashboard } from "./pages/Dashboard";
import { OpsFinance } from "./pages/ops/OpsFinance";
import { OpsFleet } from "./pages/ops/OpsFleet";
import { OpsFly } from "./pages/ops/OpsFly";
import { OpsHome } from "./pages/ops/OpsHome";
import { OpsNetwork } from "./pages/ops/OpsNetwork";
import { OpsRules } from "./pages/ops/OpsRules";
import { Online } from "./pages/Online";
import { RoutePlan } from "./pages/RoutePlan";
import { Logs } from "./pages/Logs";
import { LogDetail } from "./pages/LogDetail";
import { Stats } from "./pages/Stats";
import { SettingsPage } from "./pages/Settings";
import { loadOnline } from "./online";
import { opsStateMeta } from "./ops";
import { simlinkState } from "./simlink";
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

function Shell({
  bootstrap, settings, navdata, recording, opsStatus, refresh, saveSettings, dark, onlineMode,
  refreshKey, openWizard,
}: AppContextValue) {
  const { tr } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  /** UI-10：有未保存改动时先确认（设置页注册的拦截器）。 */
  const go = useCallback(async (path: string) => {
    if (path === location.pathname) return;
    if (!(await confirmLeave())) return;
    navigate(path);
  }, [location.pathname, navigate]);
  const selected = useMemo(() => {
    // IA-02 / IA-01 / IA-09：合并页的子路由仍高亮同一个菜单项
    if (location.pathname.startsWith("/logs") || location.pathname.startsWith("/map")) return "/logs";
    if (location.pathname.startsWith("/recommend")) return "/route";
    if (location.pathname.startsWith("/ops")) {
      const path = "/" + location.pathname.split("/").slice(1, 3).join("/");
      if (["/ops/roster", "/ops/free", "/ops/execute"].includes(path)) return "/ops/fly";
      if (["/ops/settlements", "/ops/ledger", "/ops/review"].includes(path)) return "/ops/finance";
      return path;
    }
    return location.pathname;
  }, [location.pathname]);

  const personalItems = [
    { key: "/", icon: <DashboardOutlined />, label: tr("首页", "Home") },
    // IA-09：推荐与航路合成一页（先推荐、后规划），两个深链都保留
    { key: "/route", icon: <CompassOutlined />, label: tr("航路规划", "Route planning") },
    // IA-02：地图并进日志页签
    { key: "/logs", icon: <AppstoreOutlined />, label: tr("日志", "Logbook") },
    { key: "/stats", icon: <LineChartOutlined />, label: tr("统计", "Stats") },
    { key: "/settings", icon: <SettingOutlined />, label: tr("设置", "Settings") },
  ];
  const opsItems = [
    { key: "/ops", icon: <ShopOutlined />, label: tr("运营概览", "Overview") },
    { key: "/ops/fleet", icon: <CarOutlined />, label: tr("机队", "Fleet") },
    { key: "/ops/network", icon: <ThunderboltOutlined />, label: tr("航线与班期", "Network") },
    { key: "/ops/fly", icon: <RocketOutlined />, label: tr("飞行执行", "Fly") },
    // IA-01：复核队列并进财务的第三个页签
    { key: "/ops/finance", icon: <BankOutlined />, label: tr("财务", "Finance") },
    { key: "/ops/rules", icon: <AuditOutlined />, label: tr("运营规则", "Rules") },
    { key: "/ops/online", icon: <CloudServerOutlined />, label: tr("联机模式", "Online") },
  ];
  const items: MenuProps["items"] = [
    { type: "group", key: "g-personal", label: tr("个人模式", "Personal"), children: personalItems },
    { type: "group", key: "g-ops", label: tr("运营模式", "Operations"), children: opsItems },
  ];
  const flatItems = [...personalItems, ...opsItems];
  const statusMeta = opsStateMeta(opsStatus);
  const sim = simlinkState(recording);
  const statusDetail = [
    opsStatus?.callsign,
    opsStatus?.dep_icao && opsStatus?.arr_icao ? `${opsStatus.dep_icao}→${opsStatus.arr_icao}` : null,
  ].filter(Boolean).join(" · ");

  return (
    <Layout className="app-shell">
      <Sider className="app-sider" collapsible collapsed={collapsed} trigger={null} width={216}>
        <div className="brand" onClick={() => void go("/")}>
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
          onClick={({ key }) => void go(key)}
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
            <Tooltip title={`${tr(sim.zh, sim.en)}${sim.source ? ` · source=${sim.source}` : ""}`}>
              <Tag color={sim.color}>{tr(sim.zh, sim.en)}</Tag>
            </Tooltip>
            <Tooltip title={`${tr("当前状态，点击进入对应页面", "Current state — click to open")}${statusDetail ? `（${statusDetail}）` : ""}`}>
              <Button
                size="small"
                type={statusMeta.state === "FLIGHT" ? "primary" : "default"}
                icon={statusMeta.state === "FLIGHT" ? <RocketOutlined />
                  : statusMeta.state === "GROUND" ? <CarOutlined /> : <ClockCircleOutlined />}
                onClick={() => void go(statusMeta.path)}
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
          {/* UI-15：任一页面渲染抛错时拦截，避免整窗白屏（换页后自动复位） */}
          <ErrorBoundary resetKey={location.pathname + String(refreshKey)}>
            <Outlet context={{
              bootstrap, settings, navdata, recording, opsStatus, dark,
              refreshKey, refresh, saveSettings, onlineMode, openWizard,
            } satisfies AppContextValue} />
          </ErrorBoundary>
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
  /** UI-08：顶栏「刷新」自增，页面据此重取自己的数据（不再是「只在当前页有效」的两种行为）。 */
  const [refreshKey, setRefreshKey] = useState(0);

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
    // 合并成一条 /local/ui/pulse：少一半请求与后端序列化；页面在后台时暂停轮询。
    // 有任务/录制时 2s（状态条与计时跟手），空闲时 5s（没人看变化，省唤醒）。
    const ACTIVE_MS = 2000;
    const IDLE_MS = 5000;
    const active = { current: false };
    let timer = 0;
    let stopped = false;
    const tick = async () => {
      if (!document.hidden) {
        try {
          const pulse = await api<{ recording: RecordingStatus; ops: OpsStatus | null }>(
            "/local/ui/pulse");
          setRecording(pulse.recording);
          setOpsStatus(pulse.ops);
          active.current = Boolean(pulse.recording?.active)
            || (pulse.ops?.state ?? "IDLE") !== "IDLE";
        } catch {
          /* core may be restarting */
        }
      }
      if (!stopped) {
        timer = window.setTimeout(() => void tick(), active.current ? ACTIVE_MS : IDLE_MS);
      }
    };
    const onVisible = () => {
      if (document.hidden) return;
      window.clearTimeout(timer);
      void tick();
    };
    timer = window.setTimeout(() => void tick(), ACTIVE_MS);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
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
    // UI-08：顶栏刷新同时通知当前页面重取自己的数据
    setRefreshKey((v) => v + 1);
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
  // IA-07：联机模式下客户端三页（航线与班期/机队/运营规则）只读；未联机保持现状。
  // 登录/退出都在 localStorage，App 的轮询会让它在一个周期内同步过来。
  const onlineMode = Boolean(loadOnline());

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
                onlineMode={onlineMode}
                refreshKey={refreshKey}
                refresh={refresh}
                saveSettings={saveSettings}
                openWizard={() => setShowWizard(true)}
              />
            }
          >
            <Route index element={<Dashboard />} />
            {/* IA-09：推荐与航路是同一页，两个深链都保留 */}
            <Route path="recommend" element={<RoutePlan />} />
            <Route path="route" element={<RoutePlan />} />
            <Route path="logs" element={<Logs />} />
            <Route path="logs/:id" element={<LogDetail />} />
            {/* IA-02：`/map` 落到日志页的地图页签（保留 `?focus=` / `?track=`） */}
            <Route path="map" element={<Logs />} />
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
            {/* IA-01：`/ops/review` 深链落在财务的「待复核」页签 */}
            <Route path="ops/review" element={<OpsFinance />} />
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
