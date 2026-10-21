import { Alert, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tabs, Tag, message } from "antd";
import { useEffect, useState } from "react";
import { ApiError, api, timeText } from "../api";
import type { User } from "../types";

interface Invite {
  id: string;
  code: string;
  role: string;
  max_uses: number;
  used_count: number;
  expires_at: string | null;
  exhausted: boolean;
}

export function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [error, setError] = useState("");
  const [userOpen, setUserOpen] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [resetTarget, setResetTarget] = useState<User | null>(null);
  const [userForm] = Form.useForm();
  const [inviteForm] = Form.useForm();
  const [resetForm] = Form.useForm();

  const load = async () => {
    try {
      const [userRows, inviteRows] = await Promise.all([
        api<User[]>("/api/v1/admin/users"),
        api<Invite[]>("/api/v1/admin/invites"),
      ]);
      setUsers(userRows);
      setInvites(inviteRows);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败");
    }
  };

  useEffect(() => { void load(); }, []);

  if (error) return <Alert type="error" showIcon message={error} />;

  const createUser = async (values: Record<string, unknown>) => {
    try {
      await api("/api/v1/admin/users", { method: "POST", body: JSON.stringify(values) });
      setUserOpen(false);
      userForm.resetFields();
      message.success("用户已创建");
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "创建失败");
    }
  };

  const patchUser = async (user: User, patch: Record<string, unknown>) => {
    try {
      await api(`/api/v1/admin/users/${user.id}`, {
        method: "PUT", body: JSON.stringify({ ...patch, reason: "管理端调整" }),
      });
      message.success("已更新");
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "更新失败");
    }
  };

  const resetPassword = async (values: { password: string }) => {
    if (!resetTarget) return;
    try {
      await api(`/api/v1/admin/users/${resetTarget.id}/reset-password`, {
        method: "POST", body: JSON.stringify(values),
      });
      setResetTarget(null);
      resetForm.resetFields();
      message.success("密码已重置");
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "重置失败");
    }
  };

  const createInvite = async (values: Record<string, unknown>) => {
    try {
      const row = await api<Invite>("/api/v1/admin/invites", {
        method: "POST", body: JSON.stringify(values),
      });
      setInviteOpen(false);
      inviteForm.resetFields();
      message.success(`邀请码：${row.code}`);
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "创建失败");
    }
  };

  const revoke = async (invite: Invite) => {
    try {
      await api(`/api/v1/admin/invites/${invite.id}`, { method: "DELETE" });
      message.success("邀请码已作废");
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "作废失败");
    }
  };

  return (
    <Card title="用户与邀请码"
      extra={<Space>
        <Button onClick={() => setInviteOpen(true)}>生成邀请码</Button>
        <Button type="primary" onClick={() => setUserOpen(true)}>新建用户</Button>
      </Space>}>
      <Tabs items={[
        {
          key: "users", label: `用户（${users.length}）`,
          children: (
            <Table<User> rowKey="id" size="small" dataSource={users} pagination={{ pageSize: 12 }}
              columns={[
                { title: "用户名", dataIndex: "username", render: (v: string) => <strong>{v}</strong> },
                { title: "显示名", dataIndex: "display_name" },
                { title: "角色", dataIndex: "role", render: (v: string, row) => (
                  <Select size="small" value={v} style={{ width: 130 }}
                    onChange={(role) => patchUser(row, { role })}
                    options={["ADMIN", "DISPATCHER", "PILOT"].map((r) => ({ value: r, label: r }))} />
                ) },
                { title: "状态", dataIndex: "active", render: (v: boolean, row) => (
                  <Switch size="small" checked={v} onChange={(active) => patchUser(row, { active })} />
                ) },
                { title: "最后登录", dataIndex: "last_login_at", render: timeText },
                { title: "", width: 110, render: (_, row) => (
                  <Button size="small" onClick={() => { setResetTarget(row); resetForm.resetFields(); }}>重置密码</Button>
                ) },
              ]} />
          ),
        },
        {
          key: "invites", label: `邀请码（${invites.length}）`,
          children: (
            <Table<Invite> rowKey="id" size="small" dataSource={invites} pagination={false}
              columns={[
                { title: "邀请码", dataIndex: "code", render: (v: string) => <Tag color="blue">{v}</Tag> },
                { title: "角色", dataIndex: "role" },
                { title: "使用", render: (_, row) => `${row.used_count}/${row.max_uses}` },
                { title: "到期", dataIndex: "expires_at", render: timeText },
                { title: "状态", dataIndex: "exhausted", render: (v: boolean) => v ? <Tag>已用完</Tag> : <Tag color="green">可用</Tag> },
                { title: "", width: 90, render: (_, row) => <Button size="small" danger onClick={() => revoke(row)}>作废</Button> },
              ]} />
          ),
        },
      ]} />

      <Modal title="新建用户" open={userOpen} onCancel={() => setUserOpen(false)}
        onOk={() => userForm.submit()}>
        <Form form={userForm} layout="vertical" onFinish={createUser} initialValues={{ role: "PILOT" }}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, min: 3 }]}><Input /></Form.Item>
          <Form.Item name="display_name" label="显示名"><Input /></Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select options={["ADMIN", "DISPATCHER", "PILOT"].map((r) => ({ value: r, label: r }))} />
          </Form.Item>
          <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 8 }]}>
            <Input.Password placeholder="至少 8 位" />
          </Form.Item>
          <Form.Item name="email" label="邮箱（可选）"><Input /></Form.Item>
        </Form>
      </Modal>

      <Modal title={`重置 ${resetTarget?.username || ""} 的密码`} open={!!resetTarget}
        onCancel={() => setResetTarget(null)} onOk={() => resetForm.submit()}>
        <Form form={resetForm} layout="vertical" onFinish={resetPassword}>
          <Form.Item name="password" label="新密码" rules={[{ required: true, min: 8 }]}>
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="生成邀请码" open={inviteOpen} onCancel={() => setInviteOpen(false)}
        onOk={() => inviteForm.submit()}>
        <Form form={inviteForm} layout="vertical" onFinish={createInvite}
          initialValues={{ role: "PILOT", max_uses: 1, expires_in_hours: 168 }}>
          <Form.Item name="role" label="角色">
            <Select options={["ADMIN", "DISPATCHER", "PILOT"].map((r) => ({ value: r, label: r }))} />
          </Form.Item>
          <Form.Item name="max_uses" label="可使用次数"><InputNumber min={1} style={{ width: "100%" }} /></Form.Item>
          <Form.Item name="expires_in_hours" label="有效期（小时）"><InputNumber min={1} style={{ width: "100%" }} /></Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
