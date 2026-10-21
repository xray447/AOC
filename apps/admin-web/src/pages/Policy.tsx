import { Alert, Button, Card, Col, Descriptions, Drawer, Input, InputNumber, Modal, Row, Select, Space, Table, Tag, message } from "antd";
import { useEffect, useState } from "react";
import { ApiError, api, timeText } from "../api";
import { useAuth } from "../App";
import type { SettingResponse } from "../types";

interface PolicyRule {
  enabled?: boolean;
  action?: string;
  [key: string]: unknown;
}

interface PolicyPayload {
  scope_mode?: string;
  default_action?: string;
  reject_cost_mode?: string;
  review_advance_ratio?: number;
  review_sla_hours?: number;
  min_payout_factor?: number;
  rules?: Record<string, PolicyRule>;
  overrides?: unknown[];
  [key: string]: unknown;
}

interface PreviewResult {
  evaluation: { payout_factor: number; action: string; review_required: boolean; breakdown: unknown[] };
  sources: Record<string, string>;
  effective: Record<string, unknown>;
}

export function PolicyPage() {
  const { auth } = useAuth();
  const [data, setData] = useState<SettingResponse | null>(null);
  const [payload, setPayload] = useState<PolicyPayload>({});
  const [version, setVersion] = useState(0);
  const [rulesText, setRulesText] = useState("{}");
  const [anomaliesText, setAnomaliesText] = useState(
    JSON.stringify([{ kind: "DATA_GAP", units: 1.2, value: 12 }], null, 2));
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [versions, setVersions] = useState<Array<{ version: number; reason: string | null; created_at: string }>>([]);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const result = await api<SettingResponse>("/api/v1/admin/policy");
      const body = result.payload as PolicyPayload;
      setData(result);
      setPayload(body);
      setVersion(result.version);
      setRulesText(JSON.stringify(body.rules || {}, null, 2));
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败");
    }
  };

  useEffect(() => { void load(); }, []);

  if (error) return <Alert type="error" showIcon message={error} />;
  if (!data) return <Card loading />;
  const readonly = auth?.user.role !== "ADMIN";

  const buildPayload = (): PolicyPayload => {
    const rules = JSON.parse(rulesText) as Record<string, PolicyRule>;
    return {
      ...payload, scope_mode: payload.scope_mode, default_action: payload.default_action,
      reject_cost_mode: payload.reject_cost_mode,
      review_advance_ratio: payload.review_advance_ratio,
      review_sla_hours: payload.review_sla_hours,
      min_payout_factor: payload.min_payout_factor,
      rules,
      overrides: payload.overrides || [],
    };
  };

  const update = (patch: Partial<PolicyPayload>) => setPayload((prev) => ({ ...prev, ...patch }));

  const runPreview = async () => {
    try {
      const anomalies = JSON.parse(anomaliesText);
      const result = await api<PreviewResult>("/api/v1/admin/policy/preview", {
        method: "POST", body: JSON.stringify({ payload: buildPayload(), anomalies }),
      });
      setPreview(result);
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "预览失败（检查 JSON 格式）");
    }
  };

  const publish = async () => {
    if (!reason.trim()) {
      message.warning("请填写发布原因");
      return;
    }
    setBusy(true);
    try {
      const result = await api<{ version: number }>("/api/v1/admin/policy", {
        method: "PUT",
        body: JSON.stringify({ version, payload: buildPayload(), reason }),
      });
      setVersion(result.version);
      setPublishOpen(false);
      setReason("");
      message.success(`策略已发布 v${result.version}`);
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "发布失败");
    } finally {
      setBusy(false);
    }
  };

  const openVersions = async () => {
    setVersions(await api("/api/v1/admin/policy/versions"));
    setVersionsOpen(true);
  };

  const rollback = async (target: number) => {
    try {
      await api("/api/v1/admin/policy/rollback", {
        method: "POST",
        body: JSON.stringify({ version, target_version: target, reason: `回滚到 v${target}` }),
      });
      setVersionsOpen(false);
      message.success("已回滚");
      await load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "回滚失败");
    }
  };

  const rules = payload.rules || {};
  return (
    <Card title={<span>异常与结算策略 <Tag color="blue">v{version}</Tag></span>}
      extra={<Space>
        <Button onClick={runPreview}>预览异常</Button>
        <Button onClick={openVersions}>版本历史</Button>
        {!readonly ? <Button type="primary" onClick={() => setPublishOpen(true)}>发布</Button> : null}
      </Space>}>
      <Alert type="info" showIcon style={{ marginBottom: 14 }}
        message="只影响后续航班；已开始航班使用开始时的策略快照。发布/回滚写审计。" />
      <Row gutter={[16, 12]}>
        <Col xs={24} md={8}>
          <div className="admin-param">
            <label><span>作用范围</span><span>scope_mode</span></label>
            <Select style={{ width: "100%" }} value={payload.scope_mode || "COMPANY_ONLY"} disabled={readonly}
              onChange={(value) => update({ scope_mode: value })}
              options={[
                { value: "COMPANY_ONLY", label: "COMPANY_ONLY（仅公司）" },
                { value: "ALLOW_OVERRIDES", label: "ALLOW_OVERRIDES（允许覆盖）" },
              ]} />
          </div>
        </Col>
        <Col xs={24} md={8}>
          <div className="admin-param">
            <label><span>默认动作</span><span>default_action</span></label>
            <Select style={{ width: "100%" }} value={payload.default_action || "REVIEW"} disabled={readonly}
              onChange={(value) => update({ default_action: value })}
              options={["ACCEPT", "WEIGHTED", "REVIEW", "REJECT"].map((v) => ({ value: v, label: v }))} />
          </div>
        </Col>
        <Col xs={24} md={8}>
          <div className="admin-param">
            <label><span>驳回成本模式</span><span>reject_cost_mode</span></label>
            <Select style={{ width: "100%" }} value={payload.reject_cost_mode || "FULL"} disabled={readonly}
              onChange={(value) => update({ reject_cost_mode: value })}
              options={["FULL", "DIRECT_ONLY", "NONE"].map((v) => ({ value: v, label: v }))} />
          </div>
        </Col>
        <Col xs={24} md={8}>
          <div className="admin-param">
            <label><span>复核预付款比例</span><span>0–0.5</span></label>
            <InputNumber style={{ width: "100%" }} min={0} max={0.5} step={0.05}
              value={Number(payload.review_advance_ratio ?? 0)} disabled={readonly}
              onChange={(value) => update({ review_advance_ratio: value ?? 0 })} />
          </div>
        </Col>
        <Col xs={24} md={8}>
          <div className="admin-param">
            <label><span>复核 SLA（小时）</span><span>review_sla_hours</span></label>
            <InputNumber style={{ width: "100%" }} min={1} max={168}
              value={Number(payload.review_sla_hours ?? 24)} disabled={readonly}
              onChange={(value) => update({ review_sla_hours: value ?? 24 })} />
          </div>
        </Col>
        <Col xs={24} md={8}>
          <div className="admin-param">
            <label><span>最低赔付因子</span><span>min_payout_factor</span></label>
            <InputNumber style={{ width: "100%" }} min={0} max={1} step={0.01}
              value={Number(payload.min_payout_factor ?? 0.4)} disabled={readonly}
              onChange={(value) => update({ min_payout_factor: value ?? 0.4 })} />
          </div>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} xl={14}>
          <Card type="inner" title="异常规则（JSON）" size="small">
            <Input.TextArea rows={16} value={rulesText} disabled={readonly}
              onChange={(e) => setRulesText(e.target.value)}
              style={{ fontFamily: "Cascadia Code, Consolas, monospace", fontSize: 12 }} />
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card type="inner" title="异常组合预览" size="small">
            <Input.TextArea rows={7} value={anomaliesText}
              onChange={(e) => setAnomaliesText(e.target.value)}
              style={{ fontFamily: "Cascadia Code, Consolas, monospace", fontSize: 12 }} />
            <div className="admin-hint" style={{ margin: "8px 0" }}>
              例如数据缺口 12min：units=1.2；时间加速 4x：kind=SIM_RATE,units=4。
            </div>
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="生效因子">
                {preview ? preview.evaluation.payout_factor.toFixed(3) : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="动作">
                {preview ? <Tag>{preview.evaluation.action}</Tag> : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="需复核">{preview ? (preview.evaluation.review_required ? "是" : "否") : "—"}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24}>
          <Card type="inner" title="规则摘要" size="small">
            <Table size="small" rowKey="kind" pagination={false}
              dataSource={Object.entries(rules).map(([kind, rule]) => ({ kind, ...rule }))}
              columns={[
                { title: "异常", dataIndex: "kind" },
                { title: "启用", dataIndex: "enabled", render: (v: boolean | undefined) => (v === false ? "否" : "是") },
                { title: "动作", dataIndex: "action", render: (v: string | undefined) => v || "默认" },
                { title: "参数", render: (_, row) => (
                  <span className="admin-hint">{JSON.stringify(Object.fromEntries(
                    Object.entries(row).filter(([k]) => !["kind", "enabled", "action"].includes(k))))}</span>
                ) },
              ]} />
          </Card>
        </Col>
      </Row>

      <Modal title="发布结算策略" open={publishOpen} onCancel={() => setPublishOpen(false)}
        onOk={publish} confirmLoading={busy} okText="校验并发布">
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="历史结算不受影响；版本冲突会返回 409。" />
        <Input.TextArea rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder="发布原因（必填）" />
      </Modal>

      <Drawer title="策略版本" width={560} open={versionsOpen} onClose={() => setVersionsOpen(false)}>
        <Table size="small" rowKey="version" dataSource={versions} pagination={false}
          columns={[
            { title: "版本", dataIndex: "version", render: (v: number) => `v${v}` },
            { title: "原因", dataIndex: "reason", render: (v: string | null) => v || "—" },
            { title: "时间", dataIndex: "created_at", render: timeText },
            { title: "", width: 80, render: (_, row) => (
              <Button size="small" disabled={row.version === version} onClick={() => rollback(row.version)}>回滚</Button>
            ) },
          ]} />
      </Drawer>
    </Card>
  );
}
