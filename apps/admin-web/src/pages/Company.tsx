import { Alert, Button, Card, Descriptions, Form, Input, InputNumber, Modal, Space, message } from "antd";
import { useEffect, useState } from "react";
import { ApiError, api, money } from "../api";
import { useAuth } from "../App";
import type { Company } from "../types";

export function CompanyPage() {
  const { auth } = useAuth();
  const [company, setCompany] = useState<Company | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [balanceOpen, setBalanceOpen] = useState(false);
  const [form] = Form.useForm();
  const [balanceForm] = Form.useForm();

  const load = async () => {
    try {
      const data = await api<Company>("/api/v1/admin/company");
      setCompany(data);
      form.setFieldsValue(data);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败");
    }
  };

  useEffect(() => { void load(); }, []);

  if (error) return <Alert type="error" showIcon message={error} />;
  if (!company) return <Card loading />;
  const readonly = auth?.user.role !== "ADMIN";

  const save = async (values: Record<string, unknown>) => {
    setSaving(true);
    try {
      const data = await api<Company>("/api/v1/admin/company", {
        method: "PUT", body: JSON.stringify({ ...values, reason: "管理端修改公司档案" }),
      });
      setCompany(data);
      message.success("公司档案已保存");
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const adjust = async (values: { amount: number; reason: string }) => {
    try {
      const data = await api<Company>("/api/v1/admin/company/balance", {
        method: "POST", body: JSON.stringify(values),
      });
      setCompany(data);
      setBalanceOpen(false);
      balanceForm.resetFields();
      message.success("资金已调整");
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "调整失败");
    }
  };

  return (
    <Card title="公司档案" extra={!readonly ? (
      <Space>
        <Button onClick={() => setBalanceOpen(true)}>调整资金</Button>
        <Button type="primary" loading={saving} onClick={() => form.submit()}>保存</Button>
      </Space>
    ) : <span className="admin-hint">签派只读</span>}>
      <Descriptions column={3} size="small" style={{ marginBottom: 18 }}>
        <Descriptions.Item label="当前余额">{money(company.balance, company.currency)}</Descriptions.Item>
        <Descriptions.Item label="初始资金">{money(company.initial_balance, company.currency)}</Descriptions.Item>
        <Descriptions.Item label="货币">{company.currency}（创建后只读）</Descriptions.Item>
      </Descriptions>
      <Form form={form} layout="vertical" onFinish={save} disabled={readonly}>
        <div className="admin-param-grid">
          <Form.Item name="name" label="公司名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="callsign_prefix" label="呼号前缀" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="base_icao" label="基地机场" rules={[{ required: true }]}>
            <Input maxLength={4} />
          </Form.Item>
          <Form.Item name="timezone" label="时区显示">
            <Input placeholder="UTC" />
          </Form.Item>
          <Form.Item name="icao" label="ICAO（只读）">
            <Input disabled />
          </Form.Item>
        </div>
        <Form.Item name="description" label="公司简介">
          <Input.TextArea rows={3} />
        </Form.Item>
      </Form>
      <div className="admin-hint">基地变更只影响新抽班/新航班，不搬运已有飞机；ICAO 与货币创建后只读。</div>

      <Modal title="调整公司资金" open={balanceOpen} onCancel={() => setBalanceOpen(false)}
        onOk={() => balanceForm.submit()} okText="确认调整">
        <Alert type="warning" showIcon message="必须填写原因，操作会写入审计与账本。" style={{ marginBottom: 12 }} />
        <Form form={balanceForm} layout="vertical" onFinish={adjust}>
          <Form.Item name="amount" label="金额（负数表示扣减）" rules={[{ required: true }]}>
            <InputNumber style={{ width: "100%" }} step={1000} />
          </Form.Item>
          <Form.Item name="reason" label="原因" rules={[{ required: true }]}>
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
