import { DeleteOutlined, DownloadOutlined, EyeOutlined, GlobalOutlined, ReloadOutlined, SearchOutlined, UnorderedListOutlined } from "@ant-design/icons";
import { Button, Card, Input, Popconfirm, Select, Space, Table, Tabs, Tag, Tooltip, message } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api, download } from "../api";
import { LoadError } from "../components/LoadError";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import type { FlightList, FlightRecord, ImportedFlight } from "../types";
import { fmtDateTime, fmtDistance, fmtMinutes, ratingLabels, statusLabels } from "../utils";
import { MapPage } from "./MapPage";

type Source = "aoc" | "imported";

/**
 * 日志页（IA-02 / D-11）：列表与地图合成一页，导入航班并入列表的「来源」筛选。
 * `/logs` 默认列表、`/map` 默认地图；两个路由都保留（深链 `?focus=` / `?track=` 照旧）。
 */
export function Logs() {
  const { tr } = useI18n();
  const { settings } = useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const [data, setData] = useState<FlightRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  // UI-14：输入框即时显示，请求走 300ms 防抖（以前每敲一个字就发一次请求）
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string | undefined>();
  const [source, setSource] = useState<Source>("aoc");
  const [imported, setImported] = useState<ImportedFlight[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { refreshKey } = useApp();

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const tabFromQuery = params.get("tab");
  const tab = tabFromQuery === "map" || tabFromQuery === "list"
    ? tabFromQuery
    : (location.pathname.startsWith("/map") ? "map" : "list");

  const load = useCallback(async (p: number, ps: number, q: string, st?: string) => {
    setLoading(true);
    try {
      const query = new URLSearchParams({ limit: String(ps), offset: String((p - 1) * ps) });
      if (q.trim()) query.set("search", q.trim());
      if (st) query.set("status", st);
      const res = await api<FlightList>(`/local/flights?${query.toString()}`);
      setData(res.items);
      setTotal(res.total);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadImported = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api<{ items: ImportedFlight[] }>("/local/volanta/flights");
      setImported(res.items);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  // `page` 不进依赖：翻页由 pagination.onChange 自己取数，避免「翻页两次请求」
  useEffect(() => {
    if (source === "imported") void loadImported();
    else { setPage(1); void load(1, pageSize, search, status); }
  }, [search, status, pageSize, source, refreshKey, load, loadImported]);

  const remove = async (id: string) => {
    try {
      await api(`/local/flights/${id}`, { method: "DELETE" });
      message.success(tr("已删除", "Deleted"));
      void load(page, pageSize, search, status);
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const importedRows = useMemo(() => {
    // 导入航班在本地过滤，不受 300ms 防抖影响
    const q = searchInput.trim().toUpperCase();
    if (!q) return imported;
    return imported.filter((row) => [row.callsign, row.dep_icao, row.arr_icao, row.aircraft_type,
      row.registration].some((value) => (value || "").toUpperCase().includes(q)));
  }, [imported, search]);

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
          {f.dep_icao || "—"} → {f.arr_icao || "—"}
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

  const importedColumns = [
    {
      title: tr("航班号", "Flight"), dataIndex: "callsign", width: 120,
      render: (v: string | null | undefined) => (v ? <span className="mono">{v}</span> : "—"),
    },
    {
      title: tr("日期", "Date"), dataIndex: "flight_date", width: 120,
      render: (v: string | null | undefined) => v || "—",
    },
    {
      title: tr("航段", "Leg"), key: "leg", width: 150,
      render: (_: unknown, row: ImportedFlight) => (
        <Space size={4}>
          <Tag>{row.dep_icao || "—"}</Tag>
          <span className="muted">→</span>
          <Tag>{row.arr_icao || "—"}</Tag>
        </Space>
      ),
    },
    {
      title: tr("机型", "Aircraft"), key: "type", width: 160,
      render: (_: unknown, row: ImportedFlight) => (
        <span>{row.aircraft_type || "—"}{row.registration ? <span className="muted"> · {row.registration}</span> : null}</span>
      ),
    },
    {
      title: tr("时长", "Duration"), dataIndex: "duration_min", width: 100,
      render: (v: number | null | undefined) => (v ? `${v} min` : "—"),
    },
    {
      title: tr("接地率", "Landing"), dataIndex: "landing_rate_fpm", width: 110,
      render: (v: number | null | undefined) => (v != null ? `${Math.round(v)} fpm` : "—"),
    },
    {
      title: "", key: "act", width: 110,
      render: (_: unknown, row: ImportedFlight) => (
        <Button size="small" type="link" disabled={!row.point_count}
          onClick={(e) => { e.stopPropagation(); navigate(`/map?track=${encodeURIComponent(row.id)}`); }}>
          {tr("看轨迹", "Track")}
        </Button>
      ),
    },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("飞行日志", "Logbook")}</h2>
          <p>{tr("AOC 本地记录是权威数据；导入航班可在「来源」里查看，地图是同一页的另一个页签",
            "AOC records are authoritative; imported flights show under Source, and the map is a tab of this page")}</p>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />}
            onClick={() => (source === "imported" ? void loadImported() : void load(page, pageSize, search, status))}>
            {tr("刷新", "Refresh")}
          </Button>
        </Space>
      </div>

      {error ? (
        <LoadError message={error} onRetry={() => (source === "imported"
          ? void loadImported() : void load(page, pageSize, search, status))} />
      ) : null}

      <Tabs
        activeKey={tab}
        onChange={(key) => navigate(key === "map" ? "/map" : "/logs")}
        items={[
          { key: "list", label: <span><UnorderedListOutlined /> {tr("列表", "List")}</span> },
          { key: "map", label: <span><GlobalOutlined /> {tr("地图", "Map")}</span> },
        ]}
      />

      {tab === "map" ? (
        <MapPage embedded focusTrackId={params.get("track")} />
      ) : (
        <Card className="panel" variant="borderless" styles={{ body: { padding: 0 } }}>
          <div style={{ padding: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder={tr("搜索呼号 / 机场 / 机型", "Search callsign / airport / type")}
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              style={{ width: 260 }}
            />
            <Select
              value={source}
              onChange={(v) => setSource(v as Source)}
              style={{ width: 140 }}
              options={[
                { value: "aoc", label: tr("来源：AOC", "Source: AOC") },
                { value: "imported", label: tr("来源：导入", "Source: imported") },
              ]}
            />
            {source === "aoc" ? (
              <Select
                allowClear
                placeholder={tr("状态", "Status")}
                value={status}
                onChange={setStatus}
                style={{ width: 140 }}
                options={Object.entries(statusLabels).map(([value, v]) => ({ value, label: tr(v.zh, v.en) }))}
              />
            ) : null}
            <span className="muted" style={{ marginLeft: "auto", alignSelf: "center" }}>
              {tr("共", "Total")} {source === "aoc" ? total : importedRows.length} {tr("条", "flights")}
            </span>
          </div>
          {source === "aoc" ? (
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
                onChange: (p, ps) => {
                  // 只在这里取数：`page`/`pageSize` 都不在 effect 依赖里，避免同一次操作发两次请求
                  setPage(p);
                  setPageSize(ps);
                  void load(p, ps, search, status);
                },
                showTotal: (t) => `${t} ${tr("条记录", "records")}`,
              }}
              locale={{ emptyText: tr("还没有记录", "No flights yet") }}
            />
          ) : (
            <Table
              rowKey="id"
              size="middle"
              loading={loading}
              dataSource={importedRows}
              columns={importedColumns}
              pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50] }}
              onRow={(row) => ({
                onClick: () => navigate(`/map?track=${encodeURIComponent(row.id)}`),
                style: { cursor: row.point_count ? "pointer" : "default" },
              })}
              locale={{
                emptyText: tr("还没有导入航班（在设置里导入 Volanta CSV / 同步后可在此查看）",
                  "No imported flights yet (import a Volanta CSV in Settings)"),
              }}
            />
          )}
        </Card>
      )}
    </div>
  );
}
