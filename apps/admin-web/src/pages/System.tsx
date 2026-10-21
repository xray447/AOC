import { Alert, Card, Col, Descriptions, Row, Tag } from "antd";
import { useEffect, useState } from "react";
import { ApiError, api, timeText } from "../api";

interface SystemData {
  server: { version: string; api_version: string; started_at: string | null; database: string };
  company: { name: string; icao: string; currency: string; balance: number };
  config: { economy_version: number; policy_version: number };
  counts: Record<string, number>;
  admin_static_dir: string;
  server_time: string;
}

export function SystemPage() {
  const [data, setData] = useState<SystemData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<SystemData>("/api/v1/admin/system")
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "加载失败"));
  }, []);

  if (error) return <Alert type="error" showIcon message={error} />;
  if (!data) return <Card loading />;

  return (
    <Row gutter={[14, 14]}>
      <Col xs={24} lg={12}>
        <Card title="服务">
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="版本">{data.server.version}</Descriptions.Item>
            <Descriptions.Item label="API"><Tag color="blue">{data.server.api_version}</Tag></Descriptions.Item>
            <Descriptions.Item label="数据库">{data.server.database}</Descriptions.Item>
            <Descriptions.Item label="启动时间">{timeText(data.server.started_at)}</Descriptions.Item>
            <Descriptions.Item label="服务器时间">{timeText(data.server_time)}</Descriptions.Item>
            <Descriptions.Item label="管理端静态目录">{data.admin_static_dir}</Descriptions.Item>
          </Descriptions>
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card title="公司与配置">
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="公司">{data.company.name}（{data.company.icao}）</Descriptions.Item>
            <Descriptions.Item label="余额">{data.company.currency} {data.company.balance.toFixed(2)}</Descriptions.Item>
            <Descriptions.Item label="经济参数版本">v{data.config.economy_version}</Descriptions.Item>
            <Descriptions.Item label="结算策略版本">v{data.config.policy_version}</Descriptions.Item>
          </Descriptions>
        </Card>
        <Card title="数据量" style={{ marginTop: 14 }}>
          <div className="admin-kv">
            {Object.entries(data.counts).map(([key, value]) => (
              <div key={key}><span>{key}</span><strong>{value}</strong></div>
            ))}
          </div>
        </Card>
      </Col>
    </Row>
  );
}
