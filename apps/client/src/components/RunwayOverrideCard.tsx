import { DeleteOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  Button, Card, Empty, Form, Input, InputNumber, Popconfirm, Space, Table, Tag, message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useI18n } from "../i18n";

interface OverrideValues {
  icao: string;
  ident: string;
  length_m?: number | null;
  width_m?: number | null;
  threshold_lat?: number | null;
  threshold_lon?: number | null;
  hdg?: number | null;
}

interface OverrideRow extends OverrideValues {
  updated_at?: string | null;
}

/**
 * §36 兜底 C（1.4）：手工跑道覆盖表。
 *
 * 只对「场景库扫不到 / 玩家装了 add-on 机场」有用：写入后 `find_runway()` 优先读它
 * （`source=override`），接地区视图、跑道够不够长与翼展推断都随之更新。
 */
export function RunwayOverrideCard() {
  const { tr } = useI18n();
  const [items, setItems] = useState<OverrideRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm<OverrideValues>();

  const load = useCallback(async () => {
    const res = await api<{ items: Record<string, Record<string, Omit<OverrideRow, "icao" | "ident">>> }>(
      "/local/navdata/runway-overrides");
    const rows: OverrideRow[] = [];
    for (const [icao, idents] of Object.entries(res.items || {})) {
      for (const [ident, data] of Object.entries(idents || {})) rows.push({ icao, ident, ...data });
    }
    rows.sort((a, b) => `${a.icao}${a.ident}`.localeCompare(`${b.icao}${b.ident}`));
    setItems(rows);
  }, []);

  useEffect(() => { void load().catch((e: Error) => message.error(e.message)); }, [load]);

  const save = async () => {
    const values = await form.validateFields();
    setBusy(true);
    try {
      const code = values.icao.trim().toUpperCase();
      const ident = values.ident.trim().toUpperCase();
      await api(`/local/navdata/runway-overrides/${encodeURIComponent(code)}/${encodeURIComponent(ident)}`, {
        method: "PUT",
        body: JSON.stringify({
          length_m: values.length_m, width_m: values.width_m,
          threshold_lat: values.threshold_lat, threshold_lon: values.threshold_lon,
          hdg: values.hdg,
        }),
      });
      form.resetFields();
      await load();
      message.success(tr("跑道覆盖已保存：接地区与跑道校验优先用它",
        "Runway override saved; touchdown view and runway checks use it first"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row: OverrideRow) => {
    try {
      await api(`/local/navdata/runway-overrides/${encodeURIComponent(row.icao)}/${encodeURIComponent(row.ident)}`,
        { method: "DELETE" });
      await load();
      message.success(tr("已删除覆盖，回到场景库/navdata", "Override removed; scenery/navdata applies again"));
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  return (
    <Card
      className="panel"
      variant="borderless"
      title={tr("修正跑道数据（手工覆盖）", "Runway data overrides")}
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>{tr("刷新", "Refresh")}</Button>}
    >
      <Form form={form} layout="vertical">
        <Space size={10} wrap style={{ display: "flex" }}>
          <Form.Item name="icao" label={tr("机场", "Airport")} rules={[{ required: true, len: 4 }]} style={{ width: 110 }}>
            <Input maxLength={4} placeholder="WMKN" />
          </Form.Item>
          <Form.Item name="ident" label={tr("跑道号", "Runway")} rules={[{ required: true }]} style={{ width: 100 }}>
            <Input maxLength={4} placeholder="01" />
          </Form.Item>
          <Form.Item name="length_m" label={tr("长度 m", "Length m")} style={{ width: 120 }}>
            <InputNumber min={300} max={6000} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="width_m" label={tr("宽度 m", "Width m")} style={{ width: 110 }}>
            <InputNumber min={15} max={100} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="hdg" label={tr("真航向", "True hdg")} style={{ width: 110 }}>
            <InputNumber min={0} max={360} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="threshold_lat" label={tr("入口纬度", "Threshold lat")} style={{ width: 130 }}>
            <InputNumber min={-90} max={90} step={0.0001} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="threshold_lon" label={tr("入口经度", "Threshold lon")} style={{ width: 130 }}>
            <InputNumber min={-180} max={180} step={0.0001} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item label=" ">
            <Button type="primary" icon={<PlusOutlined />} loading={busy} onClick={() => void save()}>
              {tr("保存覆盖", "Save override")}
            </Button>
          </Form.Item>
        </Space>
      </Form>

      {items.length ? (
        <Table
          rowKey={(row) => `${row.icao}/${row.ident}`}
          size="small"
          pagination={false}
          dataSource={items}
          columns={[
            { title: tr("机场", "Airport"), dataIndex: "icao", width: 80, render: (v: string) => <Tag>{v}</Tag> },
            { title: tr("跑道", "Runway"), dataIndex: "ident", width: 70 },
            { title: tr("长度", "Length"), dataIndex: "length_m", width: 90, render: (v: number | null) => (v ? `${Math.round(v)} m` : "—") },
            { title: tr("宽度", "Width"), dataIndex: "width_m", width: 90, render: (v: number | null) => (v ? `${v} m` : "—") },
            { title: tr("真航向", "Hdg"), dataIndex: "hdg", width: 80, render: (v: number | null) => (v != null ? `${Math.round(v)}°` : "—") },
            {
              title: tr("入口", "Threshold"), key: "thr",
              render: (_: unknown, row: OverrideRow) => (row.threshold_lat != null && row.threshold_lon != null
                ? `${Number(row.threshold_lat).toFixed(4)}, ${Number(row.threshold_lon).toFixed(4)}`
                : "—"),
            },
            {
              title: "", key: "del", width: 60,
              render: (_: unknown, row: OverrideRow) => (
                <Popconfirm title={tr("删除这条覆盖？", "Delete this override?")} onConfirm={() => void remove(row)}>
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ),
            },
          ]}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={tr("还没有手工覆盖：场景库/navdata 优先", "No overrides yet — scenery/navdata applies")} />
      )}
    </Card>
  );
}
