import {
  AuditOutlined,
  BankOutlined,
  CarOutlined,
  DashboardOutlined,
  GlobalOutlined,
  LogoutOutlined,
  SettingOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  UserOutlined,
  WalletOutlined,
} from "@ant-design/icons";
import { Button, Dropdown, Layout, Menu, Spin, Tag, Typography } from "antd";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, setCsrf } from "./api";
import type { AuthState } from "./types";
import { AuditPage } from "./pages/Audit";
import { CompanyPage } from "./pages/Company";
import { EconomyPage } from "./pages/Economy";
import { FleetPage } from "./pages/Fleet";
import { LoginPage } from "./pages/Login";
import { NetworkPage } from "./pages/Network";
import { OpsPage } from "./pages/Ops";
import { OverviewPage } from "./pages/Overview";
import { PolicyPage } from "./pages/Policy";
import { SystemPage } from "./pages/System";
import { UsersPage } from "./pages/Users";
import { money } from "./api";

const { Header, Sider, Content } = Layout;

interface AuthContextValue {
  auth: AuthState | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside provider");
  return ctx;
}

const MENU = [
  { key: "/", icon: <DashboardOutlined />, label: "概览", roles: ["ADMIN", "DISPATCHER"] },
  { key: "/company", icon: <BankOutlined />, label: "公司档案", roles: ["ADMIN", "DISPATCHER"] },
  { key: "/economy", icon: <WalletOutlined />, label: "经济参数", roles: ["ADMIN"] },
  { key: "/policy", icon: <AuditOutlined />, label: "结算策略", roles: ["ADMIN", "DISPATCHER"] },
  { key: "/fleet", icon: <CarOutlined />, label: "机队", roles: ["ADMIN", "DISPATCHER"] },
  { key: "/network", icon: <ThunderboltOutlined />, label: "航线与班期", roles: ["ADMIN", "DISPATCHER"] },
  { key: "/ops", icon: <GlobalOutlined />, label: "运行监控", roles: ["ADMIN", "DISPATCHER"] },
  { key: "/users", icon: <TeamOutlined />, label: "用户与邀请码", roles: ["ADMIN"] },
  { key: "/audit", icon: <AuditOutlined />, label: "审计", roles: ["ADMIN", "DISPATCHER"] },
  { key: "/system", icon: <SettingOutlined />, label: "系统", roles: ["ADMIN", "DISPATCHER"] },
];

function Shell() {
  const { auth, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const items = useMemo(
    () => MENU.filter((item) => auth && item.roles.includes(auth.user.role))
      .map(({ key, icon, label }) => ({ key, icon, label })),
    [auth],
  );
  if (!auth) return null;
  return (
    <Layout className="admin-shell">
      <Sider width={210} className="admin-sider">
        <div className="admin-brand" onClick={() => navigate("/")}>
          <span className="admin-logo">AOC</span>
          <div>
            <strong>运行管理端</strong>
            <small>{auth.company.name}</small>
          </div>
        </div>
        <Menu mode="inline" theme="dark" selectedKeys={[location.pathname]} items={items}
          onClick={({ key }) => navigate(key)} />
        <div className="admin-sider-foot">
          <div>余额</div>
          <strong>{money(auth.company.balance, auth.company.currency)}</strong>
        </div>
      </Sider>
      <Layout>
        <Header className="admin-header">
          <Typography.Title level={5} style={{ margin: 0 }}>
            {MENU.find((item) => item.key === location.pathname)?.label || "管理端"}
          </Typography.Title>
          <div className="admin-header-right">
            <Tag color="blue">{auth.company.icao}</Tag>
            <Tag>{auth.user.role}</Tag>
            <Dropdown menu={{
              items: [{ key: "logout", icon: <LogoutOutlined />, label: "退出登录" }],
              onClick: () => logout(),
            }}>
              <Button type="text" icon={<UserOutlined />}>{auth.user.display_name}</Button>
            </Dropdown>
          </div>
        </Header>
        <Content className="admin-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

function Protected() {
  const { auth, loading } = useAuth();
  if (loading) {
    return <div className="admin-center"><Spin size="large" /></div>;
  }
  if (!auth) return <Navigate to="/login" replace />;
  return <Shell />;
}

export function App() {
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const me = await api<AuthState>("/api/v1/admin/auth/me");
      setCsrf(me.csrf_token);
      setAuth(me);
    } catch {
      setAuth(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const onUnauthorized = () => setAuth(null);
    window.addEventListener("aoc:unauthorized", onUnauthorized);
    return () => window.removeEventListener("aoc:unauthorized", onUnauthorized);
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const data = await api<AuthState>("/api/v1/admin/auth/login", {
      method: "POST", body: JSON.stringify({ username, password }),
    });
    setCsrf(data.csrf_token);
    setAuth(data);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/api/v1/admin/auth/logout", { method: "POST" });
    } finally {
      setCsrf("");
      setAuth(null);
    }
  }, []);

  return (
    <AuthContext.Provider value={{ auth, loading, login, logout, refresh }}>
      <BrowserRouter basename="/admin">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<Protected />}>
            <Route index element={<OverviewPage />} />
            <Route path="company" element={<CompanyPage />} />
            <Route path="economy" element={<EconomyPage />} />
            <Route path="policy" element={<PolicyPage />} />
            <Route path="fleet" element={<FleetPage />} />
            <Route path="network" element={<NetworkPage />} />
            <Route path="ops" element={<OpsPage />} />
            <Route path="users" element={<UsersPage />} />
            <Route path="audit" element={<AuditPage />} />
            <Route path="system" element={<SystemPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthContext.Provider>
  );
}
