import { DeleteOutlined, DownloadOutlined, EyeOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import { Button, Card, Input, Popconfirm, Select, Space, Table, Tag, Tooltip, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, download } from "../api";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import type { FlightList, FlightRecord } from "../types";
import { fmtDateTime, fmtDistance, fmtMinutes, ratingLabels, statusLabels } from "../utils";

export function Logs() {
  const { tr } = useI18n();
  const { settings } = useApp();
  const navigate = useNavigate();
  const [data, setData] = useState<FlightRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (p = page, ps = pageSize, q = search, st = status) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: String(ps), offset: String((p - 1) * ps) });
      if (q.trim()) params.set("search", q.trim());
      if (st) params.set("status", st);
      const res = await api<FlightList>(`/local/flights?${params.toString()}`);
      setData(res.items);
      setTotal(res.total);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search, status]);

  useEffect(() => { void load(1, pageSize, search, status); setPage(1); }, [search, status, pageSize]); // eslint-disable-line react-hooks/exhaustive-deps

  const remove = async (id: string) => {
    try {
      await api(`/local/flights/${id}`, { method: "DELETE" });
      message.success(tr("已删除", "Deleted"));
      void load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const columns = [
    {
      title: tr("时间", "Time"), dataIndex: "block_off_utc", width: 150,
      render: (v: string) => <span className="mono">{fmtDateTime(v)}</span>,
    },
    { title: tr("呼号", "Callsign"), dataIndex: "callsign", width: 100, render: (v: string) => v || "—" },
    {
      title: tr("航段", "Leg"), key: "leg", width: 140,
      render: (_: unknown, f: FlightRecord) => (
        <Link to={`/logs/${f.id}`} style={{ fontWeight: 650, letterSpacing: ".02em" }}>
          {f.dep_icao || "????"} → {f.arr_icao || "????"}
        </Link>
      ),
    },
    { title: tr("机型", "Type"), dataIndex: "aircraft_type", width: 90, render: (v: string) => v || "—" },
    { title: tr("时长", "Block"), dataIndex: "block_minutes", width: 90, render: (v: number) => fmtMinutes(v) },
    { title: tr("距离", "Distance"), dataIndex: "distance_nm", width: 100, render: (v: number) => fmtDistance(v, settings.units) },
    {
      title: tr("接地", "Touchdown"), dataIndex: "touchdown_vs_fpm", width: 100,
      render: (v: number) => v != null ? <span className="mono">{Math.round(v)} fpm</span> : "—",
    },
    {
      title: "G", dataIndex: "max_g_landing", width: 70,
      render: (v: number) => v != null ? <span className="mono">{v.toFixed(2)}</span> : "—",
    },
    {
      title: tr("评级", "Rating"), dataIndex: "landing_rating", width: 90,
      render: (v: string) => v ? <Tag color={ratingLabels[v]?.color || "default"}>{tr(ratingLabels[v]?.zh || v, ratingLabels[v]?.en || v)}</Tag> : "—",
    },
    {
      title: tr("状态", "Status"), dataIndex: "status", width: 100,
      render: (v: string) => <Tag color={statusLabels[v]?.color}>{statusLabels[v] ? tr(statusLabels[v].zh, statusLabels[v].en) : v}</Tag>,
    },
    {
      title: "", key: "actions", width: 130, fixed: "right" as const,
      render: (_: unknown, f: FlightRecord) => (
        <Space size={2}>
          <Tooltip title={tr("详情", "Details")}>
            <Button size="small" type="text" icon={<EyeOutlined />} onClick={() => navigate(`/logs/${f.id}`)} />
          </Tooltip>
          <Tooltip title={tr("导出 GPX", "Export GPX")}>
            <Button
              size="small" type="text" icon={<DownloadOutlined />}
              onClick={() => void download(`/local/flights/${f.id}/export?format=gpx`, `${f.id}.gpx`).catch((e: Error) => message.error(e.message))}
            />
          </Tooltip>
          <Popconfirm
            title={tr("删除这条记录？", "Delete this flight?")}
            description={tr("轨迹文件也会被删除。", "Track files will be deleted too.")}
            onConfirm={() => void remove(f.id)}
          >
            <Button size="small" type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("飞行日志", "Logbook")}</h2>
          <p>{tr("AOC 本地记录是权威数据；Volanta 只补充历史", "AOC local records are authoritative; Volanta only supplements history")}</p>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>{tr("刷新", "Refresh")}</Button>
        </Space>
      </div>

      <Card className="panel" variant="borderless" styles={{ body: { padding: 0 } }}>
        <div style={{ padding: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder={tr("搜索呼号 / 机场 / 机型", "Search callsign / airport / type")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: 260 }}
          />
          <Select
            allowClear
            placeholder={tr("状态", "Status")}
            value={status}
            onChange={setStatus}
            style={{ width: 140 }}
            options={Object.entries(statusLabels).map(([value, v]) => ({ value, label: tr(v.zh, v.en) }))}
          />
          <span className="muted" style={{ marginLeft: "auto", alignSelf: "center" }}>
            {tr("共", "Total")} {total} {tr("条", "flights")}
          </span>
        </div>
        <Table
          rowKey="id"
          size="middle"
          loading={loading}
          dataSource={data}
          columns={columns}
          scroll={{ x: 1150 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50],
            onChange: (p, ps) => { setPage(p); setPageSize(ps); void load(p, ps); },
            showTotal: (t) => `${t} ${tr("条记录", "records")}`,
          }}
          locale={{ emptyText: tr("还没有记录", "No flights yet") }}
        />
      </Card>
    </div>
  );
}
