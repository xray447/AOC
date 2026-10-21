import { Alert, Button, Card, Input, Space, Table, Tag, message } from "antd";
import { useEffect, useState } from "react";
import { ApiError, api, timeText } from "../api";
import type { AuditEntry } from "../types";

export function AuditPage() {
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const query = new URLSearchParams({ limit: "300" });
      if (action) query.set("action", action);
      if (actor) query.set("actor", actor);
      setRows(await api<AuditEntry[]>(`/api/v1/admin/audit?${query.toString()}`));
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败");
    }
  };

  useEffect(() => { void load(); }, []);

  const exportCsv = async () => {
    try {
      const res = await fetch("/api/v1/admin/audit?format=csv&limit=1000", { credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "audit.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      message.error("导出失败");
    }
  };

  if (error) return <Alert type="error" showIcon message={error} />;

  return (
    <Card title="审计日志" extra={<Button onClick={exportCsv}>导出 CSV</Button>}>
      <Space style={{ marginBottom: 12 }}>
        <Input placeholder="动作筛选" value={action} onChange={(e) => setAction(e.target.value)} allowClear />
        <Input placeholder="操作人" value={actor} onChange={(e) => setActor(e.target.value)} allowClear />
        <Button type="primary" onClick={load}>查询</Button>
        <span className="admin-hint">审计只读，保留 90 天（可由运维调整）。</span>
      </Space>
      <Table<AuditEntry> rowKey="id" size="small" dataSource={rows} pagination={{ pageSize: 20 }}
        expandable={{
          expandedRowRender: (row) => (
            <div className="admin-json">{JSON.stringify({ before: row.before, after: row.after }, null, 2)}</div>
          ),
        }}
        columns={[
          { title: "时间", dataIndex: "created_at", render: timeText, width: 175 },
          { title: "操作人", dataIndex: "actor_name", render: (v: string | null) => v || "系统" },
          { title: "动作", dataIndex: "action", render: (v: string) => <Tag color="blue">{v}</Tag> },
          { title: "对象", render: (_, row) => `${row.entity || ""} ${row.entity_id || ""}` },
          { title: "结果", dataIndex: "result", render: (v: string) => <Tag color={v === "OK" ? "green" : "red"}>{v}</Tag> },
          { title: "原因", dataIndex: "reason", render: (v: string | null) => v || "—" },
          { title: "IP", dataIndex: "ip", render: (v: string | null) => v || "—" },
        ]} />
    </Card>
  );
}
