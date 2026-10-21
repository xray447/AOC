import { Alert, Button, Card, Col, Descriptions, Drawer, InputNumber, Modal, Row, Space, Table, Tag, Input, message } from "antd";
import { useEffect, useMemo, useState } from "react";
import { ApiError, api, money, timeText } from "../api";
import type { ParamSpec, SettingResponse } from "../types";

interface PreviewResult {
  samples: number;
  avg_profit: number;
  median_profit: number;
  avg_load_factor: number;
  loss_ratio: number;
  bankruptcy_probability: number;
}

interface VersionRow {
  version: number;
  reason: string | null;
  created_by: string | null;
  created_at: string;
}

export function EconomyPage() {
  const [data, setData] = useState<SettingResponse | null>(null);
  const [payload, setPayload] = useState<Record<string, unknown>>({});
  const [version, setVersion] = useState(0);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const result = await api<SettingResponse>("/api/v1/admin/economy");
      setData(result);
      setPayload({ ...result.defaults, ...result.payload });
      setVersion(result.version);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败");
    }
  };

  useEffect(() => { void load(); }, []);

  const groups = useMemo(() => {
    const map = new Map<string, ParamSpec[]>();
    for (const item of data?.schema || []) {
      const list = map.get(item.group) || [];
      list.push(item);
      map.set(item.group, list);
    }
    return Array.from(map.entries());
  }, [data]);

  if (error) return <Alert type="error" showIcon message={error} />;
  if (!data) return <Card loading />;

  const setValue = (key: string, value: number | null) => {
    setPayload((prev) => ({ ...prev, [key]: value ?? 0 }));
  };

  const runPreview = async () => {
    try {
      const result = await api<PreviewResult>("/api/v1/admin/economy/preview", {
        method: "POST", body: JSON.stringify({ payload, samples: 100 }),
      });
      setPreview(result);
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "预览失败");
    }
  };

  const publish = async () => {
    if (!reason.trim()) {
      message.warning("请填写发布原因");
      return;
    }
    setBusy(true);
    try {
      const result = await api<{ version: number; payload: Record<string, unknown> }>(
        "/api/v1/admin/economy", {
          method: "PUT",
          body: JSON.stringify({ version, payload, reason }),
        });
      setVersion(result.version);
      setPayload(result.payload);
      setPublishOpen(false);
      setReason("");
      message.success(`已发布 v${result.version}，下一班生效`);
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "CONFIG_VERSION_CONFLICT") {
        message.error(`${err.message}；请刷新后合并`);
      } else {
        message.error(err instanceof ApiError ? err.message : "发布失败");
      }
    } finally {
      setBusy(false);
    }
  };

  const openVersions = async () => {
    try {
      setVersions(await api<VersionRow[]>("/api/v1/admin/economy/versions"));
      setVersionsOpen(true);
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "加载版本失败");
    }
  };

  const rollback = async (target: number) => {
    try {
      const result = await api<{ version: number; payload: Record<string, unknown> }>(
        "/api/v1/admin/economy/rollback", {
          method: "POST",
          body: JSON.stringify({ version, target_version: target, reason: `回滚到 v${target}` }),
        });
      setVersion(result.version);
      setPayload(result.payload);
      setVersionsOpen(false);
      message.success(`已回滚并发布 v${result.version}`);
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "回滚失败");
    }
  };

  return (
    <Card title={<span>经济参数 <Tag color="blue">v{version}</Tag></span>}
      extra={<Space>
        <Button onClick={runPreview}>预览影响</Button>
        <Button onClick={openVersions}>版本历史</Button>
        <Button type="primary" onClick={() => setPublishOpen(true)}>发布</Button>
      </Space>}>
      <Alert type="info" showIcon style={{ marginBottom: 14 }}
        message="草稿只在当前页面内存中；发布后下一班航班读取新版本，已开始航班使用快照。" />
      <Descriptions size="small" column={3} style={{ marginBottom: 14 }}>
        <Descriptions.Item label="当前版本">v{data.version}</Descriptions.Item>
        <Descriptions.Item label="最后修改">{data.updated_by || "—"}</Descriptions.Item>
        <Descriptions.Item label="时间">{timeText(data.updated_at)}</Descriptions.Item>
      </Descriptions>
      {groups.map(([group, items]) => (
        <Card key={group} type="inner" title={group} style={{ marginBottom: 12 }}>
          <Row gutter={[16, 14]}>
            {items.map((item) => (
              <Col xs={24} sm={12} lg={8} xl={6} key={item.key}>
                <div className="admin-param">
                  <label>
                    <span>{item.label}</span>
                    <span>{item.unit}</span>
                  </label>
                  <InputNumber min={item.min} max={item.max} step={item.step}
                    style={{ width: "100%" }}
                    value={Number(payload[item.key] ?? 0)}
                    onChange={(value) => setValue(item.key, value)} />
                  <div className="admin-hint">范围 {item.min}–{item.max} · 默认 {String(data.defaults[item.key] ?? "—")}</div>
                </div>
              </Col>
            ))}
          </Row>
        </Card>
      ))}

      <Modal title="预览影响（100 班合成）" open={!!preview} onCancel={() => setPreview(null)}
        footer={<Button onClick={() => setPreview(null)}>关闭</Button>}>
        {preview ? (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="样本">{preview.samples}</Descriptions.Item>
            <Descriptions.Item label="平均利润">{money(preview.avg_profit)}</Descriptions.Item>
            <Descriptions.Item label="中位利润">{money(preview.median_profit)}</Descriptions.Item>
            <Descriptions.Item label="平均载客率">{(preview.avg_load_factor * 100).toFixed(1)}%</Descriptions.Item>
            <Descriptions.Item label="亏损比例">{(preview.loss_ratio * 100).toFixed(1)}%</Descriptions.Item>
            <Descriptions.Item label="破产概率">{(preview.bankruptcy_probability * 100).toFixed(1)}%</Descriptions.Item>
          </Descriptions>
        ) : null}
      </Modal>

      <Modal title="发布经济参数" open={publishOpen} onCancel={() => setPublishOpen(false)}
        onOk={publish} confirmLoading={busy} okText="校验并发布">
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="发布后会写入新版本与审计；并发修改会收到 409 版本冲突。" />
        <Input.TextArea rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder="发布原因（必填，写入审计）" />
      </Modal>

      <Drawer title="版本历史" width={620} open={versionsOpen} onClose={() => setVersionsOpen(false)}>
        <Table<VersionRow> size="small" rowKey="version" dataSource={versions}
          pagination={false}
          columns={[
            { title: "版本", dataIndex: "version", render: (v: number) => `v${v}` },
            { title: "原因", dataIndex: "reason", render: (v: string | null) => v || "—" },
            { title: "操作人", dataIndex: "created_by", render: (v: string | null) => v || "—" },
            { title: "时间", dataIndex: "created_at", render: timeText },
            {
              title: "", width: 90, render: (_, row) => (
                <Button size="small" disabled={row.version === version}
                  onClick={() => rollback(row.version)}>回滚</Button>
              ),
            },
          ]} />
      </Drawer>
    </Card>
  );
}
