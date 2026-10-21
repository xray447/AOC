import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { Alert, Button, Form, Input } from "antd";
import { useState } from "react";
import { Navigate } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../App";

export function LoginPage() {
  const { auth, login, loading } = useAuth();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (!loading && auth) return <Navigate to="/" replace />;

  const submit = async (values: { username: string; password: string }) => {
    setBusy(true);
    setError("");
    try {
      await login(values.username, values.password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登录失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="admin-login">
      <div className="admin-login-card">
        <div className="admin-login-brand">
          <span className="admin-logo">AOC</span>
          <div>
            <h2>运行管理端</h2>
            <p>联机模式 · 管理员与签派登录</p>
          </div>
        </div>
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 14 }} /> : null}
        <Form layout="vertical" onFinish={submit} initialValues={{ username: "admin" }}>
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
            <Input prefix={<UserOutlined />} autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true }]}>
            <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={busy}>登录</Button>
        </Form>
        <div className="admin-hint" style={{ marginTop: 16 }}>
          会话使用 HttpOnly Cookie，写操作需要 CSRF；飞行员账号无法登录本页。
        </div>
      </div>
    </div>
  );
}
