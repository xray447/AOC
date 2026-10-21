import { ReloadOutlined, RollbackOutlined, SaveOutlined, ThunderboltOutlined } from "@ant-design/icons";
import {
  Alert, Button, Card, Col, Divider, Form, Input, InputNumber, Modal, Row, Select, Space, Switch,
  Table, Tabs, Tag, Typography, message,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { useI18n } from "../../i18n";
import { anomalyLabel, fmtUtc, money } from "../../ops";
import type { OpsAudit, OpsConfig, OpsPolicy } from "../../types";

const { Text } = Typography;

const ACTIONS = [
  { value: "ACCEPT", label: "ACCEPT（正常结算）" },
  { value: "WEIGHTED", label: "WEIGHTED（按比例折算）" },
  { value: "REVIEW", label: "REVIEW（进入复核队列）" },
  { value: "REJECT", label: "REJECT（拒绝，收入 0）" },
];

interface Preview {
  economy: {
    samples: number; avg_profit: number; median_profit: number;
    avg_load_factor: number; loss_ratio: number; bankruptcy_probability: number;
  };
  policy?: { payout_factor: number; action: string; breakdown: { kind: string; action: string; penalty: number }[] };
}

export function OpsRules() {
  const { tr } = useI18n();
  const [config, setConfig] = useState<OpsConfig | null>(null);
  const [amounts, setAmounts] = useState<Record<string, number>>({});
  const [policy, setPolicy] = useState<OpsPolicy | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [audit, setAudit] = useState<OpsAudit[]>([]);
  const [overridesText, setOverridesText] = useState("[]");
  const [publishOpen, setPublishOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [cfg, aud] = await Promise.all([
      api<OpsConfig>("/local/ops/config"),
      api<{ items: OpsAudit[] }>("/local/ops/audit?limit=50"),
    ]);
    setConfig(cfg);
    const next: Record<string, number> = {};
    for (const item of cfg.param_schema) next[item.key] = Number(cfg.economy[item.key] ?? 0);
    setAmounts(next);
    setPolicy(cfg.policy);
    setOverridesText(JSON.stringify(cfg.policy.overrides || [], null, 2));
    setAudit(aud.items);
  }, []);

  useEffect(() => { void load().catch((e: Error) => message.error(e.message)); }, [load]);

  const groups = useMemo(() => {
    const out: Record<string, OpsConfig["param_schema"]> = {};
    for (const item of config?.param_schema || []) {
      (out[item.group] = out[item.group] || []).push(item);
    }
    return out;
  }, [config]);

  const economyPayload = () => ({ ...(config?.economy || {}), ...amounts });

  const runPreview = async () => {
    setBusy(true);
    try {
      setPreview(await api<Preview>("/local/ops/config/preview", {
        method: "POST",
        body: JSON.stringify({ economy: economyPayload(), policy }),
      }));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    if (note.trim().length < 2) {
      message.warning(tr("请填写变更原因（至少 2 个字）", "Reason required (2+ chars)"));
      return;
    }
    setBusy(true);
    try {
      const updated = await api<OpsConfig>("/local/ops/config/publish", {
        method: "POST",
        body: JSON.stringify({
          economy: economyPayload(), policy, note: note.trim(),
          expected_version: config?.version,
        }),
      });
      setConfig(updated);
      setPolicy(updated.policy);
      setPublishOpen(false);
      setNote("");
      setPreview(null);
      message.success(`${tr("已发布", "Published")} v${updated.version}`);
      await load();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const rollback = async (version: number) => {
    try {
      const updated = await api<OpsConfig>("/local/ops/config/rollback", {
        method: "POST",
        body: JSON.stringify({ version, note: `回滚到 v${version}` }),
      });
      setConfig(updated);
      setPolicy(updated.policy);
      setOverridesText(JSON.stringify(updated.policy.overrides || [], null, 2));
      message.success(`${tr("已回滚", "Rolled back")} v${updated.version}`);
      await load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const setRule = (kind: string, patch: Record<string, unknown>) => {
    if (!policy) return;
    setPolicy({
      ...policy,
      rules: { ...policy.rules, [kind]: { ...(policy.rules[kind] || {}), ...patch } },
    });
  };

  if (!config || !policy) return <div className="page"><Card loading /></div>;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("运营规则", "Operating rules")}</h2>
          <p>{tr("草稿 → 预览 → 发布 → 版本/回滚；已开始的航班用开始时快照，历史结算不变。", "Draft → preview → publish → versions/rollback. Flights in progress keep their start snapshot; history never changes.")}</p>
        </div>
        <Space wrap>
          <Tag color="blue">v{config.version}</Tag>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>{tr("刷新", "Refresh")}</Button>
          <Button icon={<ThunderboltOutlined />} loading={busy} onClick={() => void runPreview()}>{tr("预览", "Preview")}</Button>
          <Button type="primary" icon={<SaveOutlined />} onClick={() => setPublishOpen(true)}>{tr("发布", "Publish")}</Button>
        </Space>
      </div>

      <Tabs
        items={[
          {
            key: "economy",
            label: tr("经济参数", "Economy"),
            children: (
              <Card className="panel" variant="borderless">
                <Form layout="vertical">
                  {Object.entries(groups).map(([group, items]) => (
                    <div key={group}>
                      <Divider orientation="left" plain>{group}</Divider>
                      <Row gutter={12}>
                        {items.map((item) => (
                          <Col xs={12} md={8} lg={6} key={item.key}>
                            <Form.Item label={`${item.label}${item.unit ? `（${item.unit}）` : ""}`}>
                              <InputNumber
                                min={item.min}
                                max={item.max}
                                step={item.step}
                                value={amounts[item.key]}
                                onChange={(v) => setAmounts((prev) => ({ ...prev, [item.key]: Number(v ?? 0) }))}
                                style={{ width: "100%" }}
                              />
                            </Form.Item>
                          </Col>
                        ))}
                      </Row>
                    </div>
                  ))}
                </Form>
                <Alert type="info" showIcon
                  message={tr("默认值来自 docs/04 §7；修改只影响之后开始的航班。", "Defaults come from docs/04 §7; changes affect flights started afterwards.")} />
              </Card>
            ),
          },
          {
            key: "policy",
            label: tr("异常与结算策略", "Settlement policy"),
            children: (
              <Card className="panel" variant="borderless">
                <Row gutter={12}>
                  <Col xs={12} lg={6}>
                    <Form.Item label={tr("作用范围", "Scope")}>
                      <Select value={policy.scope_mode} options={[
                        { value: "COMPANY_ONLY", label: "COMPANY_ONLY（仅本机默认）" },
                        { value: "ALLOW_OVERRIDES", label: "ALLOW_OVERRIDES（允许机型/单机覆盖）" },
                      ]} onChange={(v) => setPolicy({ ...policy, scope_mode: v })} />
                    </Form.Item>
                  </Col>
                  <Col xs={12} lg={6}>
                    <Form.Item label={tr("未列异常默认动作", "Default action")}>
                      <Select value={policy.default_action} options={ACTIONS}
                        onChange={(v) => setPolicy({ ...policy, default_action: v })} />
                    </Form.Item>
                  </Col>
                  <Col xs={12} lg={6}>
                    <Form.Item label={tr("REJECT 成本模式", "Reject cost mode")}>
                      <Select value={policy.reject_cost_mode} options={[
                        { value: "FULL", label: "FULL（成本照扣）" },
                        { value: "DIRECT_ONLY", label: "DIRECT_ONLY（只扣直接成本）" },
                        { value: "NONE", label: "NONE（不扣，结算 VOID）" },
                      ]} onChange={(v) => setPolicy({ ...policy, reject_cost_mode: v })} />
                    </Form.Item>
                  </Col>
                  <Col xs={12} lg={3}>
                    <Form.Item label={tr("复核预付比例", "Advance ratio")}>
                      <InputNumber min={0} max={0.5} step={0.05} value={policy.review_advance_ratio}
                        onChange={(v) => setPolicy({ ...policy, review_advance_ratio: Number(v ?? 0) })}
                        style={{ width: "100%" }} />
                    </Form.Item>
                  </Col>
                  <Col xs={12} lg={3}>
                    <Form.Item label={tr("最低系数", "Min factor")}>
                      <InputNumber min={0} max={1} step={0.05} value={policy.min_payout_factor}
                        onChange={(v) => setPolicy({ ...policy, min_payout_factor: Number(v ?? 0) })}
                        style={{ width: "100%" }} />
                    </Form.Item>
                  </Col>
                </Row>

                <Table
                  rowKey="kind"
                  size="small"
                  pagination={false}
                  dataSource={Object.entries(policy.rules).map(([kind, rule]) => ({ kind, rule }))}
                  columns={[
                    {
                      title: tr("异常", "Anomaly"), dataIndex: "kind",
                      render: (v: string) => (anomalyLabel[v] ? tr(anomalyLabel[v].zh, anomalyLabel[v].en) : v),
                    },
                    {
                      title: tr("启用", "Enabled"), key: "enabled", width: 70,
                      render: (_: unknown, row: { kind: string; rule: Record<string, unknown> }) => (
                        <Switch size="small" checked={row.rule.enabled !== false}
                          onChange={(v) => setRule(row.kind, { enabled: v })} />
                      ),
                    },
                    {
                      title: tr("动作", "Action"), key: "action", width: 220,
                      render: (_: unknown, row: { kind: string; rule: Record<string, unknown> }) => (
                        <Select size="small" value={String(row.rule.action || "REVIEW")} options={ACTIONS}
                          style={{ width: "100%" }}
                          onChange={(v) => setRule(row.kind, { action: v })} />
                      ),
                    },
                    {
                      title: tr("参数", "Parameters"), key: "params",
                      render: (_: unknown, row: { kind: string; rule: Record<string, unknown> }) => {
                        const numeric = Object.entries(row.rule).filter(([key, v]) => typeof v === "number" && key !== "enabled");
                        if (!numeric.length) {
                          return <Text type="secondary">{row.kind === "SIM_RATE"
                            ? tr("按档位：2–4x −20%，4–8x −50%，>8x 拒绝", "Tiers: 2–4x −20%, 4–8x −50%, >8x reject")
                            : "—"}</Text>;
                        }
                        return (
                          <Space wrap size={6}>
                            {numeric.map(([key, value]) => (
                              <span key={key} style={{ fontSize: 12 }}>
                                {key}
                                <InputNumber size="small" style={{ width: 90, marginLeft: 4 }}
                                  step={key.includes("ratio") || key.includes("penalty") ? 0.01 : 0.05}
                                  value={Number(value)}
                                  onChange={(v) => setRule(row.kind, { [key]: Number(v ?? 0) })} />
                              </span>
                            ))}
                          </Space>
                        );
                      },
                    },
                  ]}
                />
                <Divider orientation="left" plain>{tr("覆盖条目（高级，JSON）", "Overrides (advanced JSON)")}</Divider>
                <Input.TextArea
                  rows={4}
                  spellCheck={false}
                  value={overridesText}
                  onChange={(e) => {
                    setOverridesText(e.target.value);
                    try {
                      const parsed = JSON.parse(e.target.value || "[]");
                      if (Array.isArray(parsed)) setPolicy({ ...policy, overrides: parsed });
                    } catch {
                      /* 保留草稿，发布时以最后一次合法 JSON 为准 */
                    }
                  }}
                />
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  {tr("形如 [{\"scope_type\":\"AIRCRAFT_TYPE\",\"scope_id\":\"A320\",\"policy\":{\"rules\":{\"DATA_GAP\":{\"action\":\"REJECT\"}}}}]；scope_mode=COMPANY_ONLY 时忽略。",
                    "e.g. [{\"scope_type\":\"AIRCRAFT_TYPE\",\"scope_id\":\"A320\",\"policy\":{\"rules\":{\"DATA_GAP\":{\"action\":\"REJECT\"}}}}]; ignored when scope_mode=COMPANY_ONLY.")}
                </div>
                <Alert style={{ marginTop: 12 }} type="warning" showIcon
                  message={tr("覆盖优先级（ALLOW_OVERRIDES 时）：机型 < 单机；M2 无飞行员覆盖",
                    "Override precedence (ALLOW_OVERRIDES): type < aircraft; no pilot overrides in M2")}
                  description={tr("默认策略覆盖数据缺口、加速、暂停、瞬移、油量跳变等；覆盖只写要改的字段（深合并）。",
                    "Defaults cover data gaps, sim rate, pause, teleport, fuel jumps, etc. Overrides only need the fields you change (deep merge).")} />
              </Card>
            ),
          },
          {
            key: "versions",
            label: tr("版本与审计", "Versions & audit"),
            children: (
              <Row gutter={16}>
                <Col xs={24} lg={12}>
                  <Card className="panel" variant="borderless" title={tr("配置版本", "Config versions")}
                    styles={{ body: { padding: 0 } }}>
                    <Table
                      rowKey="id"
                      size="small"
                      pagination={false}
                      dataSource={config.versions}
                      columns={[
                        { title: "v", dataIndex: "version", width: 60 },
                        { title: tr("原因", "Note"), dataIndex: "note" },
                        { title: tr("时间", "Time"), dataIndex: "created_at", width: 130, render: (v: string) => <span className="mono">{fmtUtc(v)}</span> },
                        {
                          title: "", key: "act", width: 90,
                          render: (_: unknown, row: { version: number }) => (
                            row.version === config.version ? <Tag color="green">{tr("当前", "current")}</Tag> : (
                              <Button size="small" type="text" icon={<RollbackOutlined />} onClick={() => void rollback(row.version)}>
                                {tr("回滚", "Rollback")}
                              </Button>
                            )
                          ),
                        },
                      ]}
                    />
                  </Card>
                </Col>
                <Col xs={24} lg={12}>
                  <Card className="panel" variant="borderless" title={tr("审计日志", "Audit log")}
                    styles={{ body: { padding: 0 } }}>
                    <Table
                      rowKey="id"
                      size="small"
                      pagination={{ pageSize: 10, showSizeChanger: false }}
                      dataSource={audit}
                      columns={[
                        { title: tr("动作", "Action"), dataIndex: "action", width: 130 },
                        { title: tr("对象", "Entity"), key: "e", render: (_: unknown, r: OpsAudit) => `${r.entity_type}${r.entity_id ? ` · ${r.entity_id.slice(0, 8)}` : ""}` },
                        { title: tr("原因", "Reason"), dataIndex: "reason" },
                        { title: tr("时间", "Time"), dataIndex: "created_at", width: 120, render: (v: string) => <span className="mono">{fmtUtc(v)}</span> },
                      ]}
                    />
                  </Card>
                </Col>
              </Row>
            ),
          },
        ]}
      />

      {preview ? (
        <Card className="panel" variant="borderless" style={{ marginTop: 16 }}
          title={tr("预览：100 班合成数据", "Preview: 100 synthetic flights")}
          extra={<Button size="small" onClick={() => setPreview(null)}>{tr("关闭", "Close")}</Button>}>
          <Row gutter={16}>
            <Col span={4}><div className="muted">{tr("平均利润", "Avg profit")}</div><strong>{money(preview.economy.avg_profit)}</strong></Col>
            <Col span={4}><div className="muted">{tr("中位利润", "Median")}</div><strong>{money(preview.economy.median_profit)}</strong></Col>
            <Col span={4}><div className="muted">{tr("平均载客率", "Load factor")}</div><strong>{(preview.economy.avg_load_factor * 100).toFixed(1)}%</strong></Col>
            <Col span={4}><div className="muted">{tr("亏损比例", "Loss ratio")}</div><strong>{(preview.economy.loss_ratio * 100).toFixed(0)}%</strong></Col>
            <Col span={4}><div className="muted">{tr("破产概率", "Bankruptcy risk")}</div><strong>{(preview.economy.bankruptcy_probability * 100).toFixed(0)}%</strong></Col>
            {preview.policy ? (
              <Col span={4}>
                <div className="muted">{tr("策略系数", "Policy factor")}</div>
                <strong>×{preview.policy.payout_factor.toFixed(2)} · {preview.policy.action}</strong>
              </Col>
            ) : null}
          </Row>
        </Card>
      ) : null}

      <Modal
        open={publishOpen}
        title={tr("发布配置", "Publish configuration")}
        onCancel={() => setPublishOpen(false)}
        onOk={() => void publish()}
        confirmLoading={busy}
        okText={tr("发布并生效", "Publish")}
      >
        <p>{tr("发布后对之后开始的航班生效；历史结算不变，并写入审计（before/after）。",
          "Applies to flights started after publishing; history is untouched and audit keeps before/after.")}</p>
        <Input.TextArea rows={3} value={note} onChange={(e) => setNote(e.target.value)}
          placeholder={tr("变更原因（至少 2 个字）", "Reason (2+ chars)")} />
        <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          {tr("当前版本", "Current version")} v{config.version}
        </div>
      </Modal>
    </div>
  );
}
