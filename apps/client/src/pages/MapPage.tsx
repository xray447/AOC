import { GlobalOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Select, Space, Table, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { WorldMap } from "../components/WorldMap";
import { useApp } from "../context";
import { useI18n } from "../i18n";
import type { ImportedFlight, MapData } from "../types";
import { fmtDateTime, ratingLabels, type LonLat } from "../utils";

const { Text } = Typography;

type Filter =
  | { kind: "airport"; value: string }
  | { kind: "leg"; dep: string; arr: string };

export function MapPage() {
  const { tr } = useI18n();
  const { dark, navdata, settings } = useApp();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [data, setData] = useState<MapData | null>(null);
  const [year, setYear] = useState<number | undefined>();
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<Filter | null>(null);
  const [track, setTrack] = useState<{ id: string; points: LonLat[] } | null>(null);
  const [trackBusy, setTrackBusy] = useState(false);

  const load = useCallback(async (y?: number) => {
    setLoading(true);
    try {
      setData(await api<MapData>(`/local/map${y ? `?year=${y}` : ""}`));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(year); }, [year, load]);

  const selectAirport = useCallback((icao: string) => {
    setFilter(icao ? { kind: "airport", value: icao } : null);
  }, []);

  const selectLeg = useCallback((dep: string, arr: string) => {
    setFilter({ kind: "leg", dep, arr });
  }, []);

  const openTrack = useCallback(async (flight: ImportedFlight) => {
    if (track?.id === flight.id) {
      setTrack(null);
      return;
    }
    if (!flight.point_count) {
      message.info(tr("该航班没有保存到轨迹（接口未返回坐标）", "No track stored for this flight"));
      return;
    }
    setTrackBusy(true);
    try {
      const detail = await api<{ id: string; track: LonLat[] | null }>(`/local/volanta/flights/${flight.id}`);
      if (detail.track && detail.track.length >= 2) setTrack({ id: detail.id, points: detail.track });
      else message.info(tr("该航班没有保存到轨迹", "No track stored for this flight"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setTrackBusy(false);
    }
  }, [track?.id, tr]);

  const importedFlights = useMemo(() => {
    const list = data?.imported_flights ?? [];
    if (!filter) return list;
    return list.filter((f) => {
      const dep = f.dep_icao ?? "";
      const arr = f.arr_icao ?? "";
      if (filter.kind === "airport") return dep === filter.value || arr === filter.value;
      return (dep === filter.dep && arr === filter.arr) || (dep === filter.arr && arr === filter.dep);
    });
  }, [data, filter]);

  // 筛选后的视图：只保留命中机场/航段，航班列表同步收窄
  const view = useMemo<MapData | null>(() => {
    if (!data) return null;
    if (!filter) return data;
    const keep = new Set<string>();
    const legs = data.legs.filter((leg) => {
      const hit = filter.kind === "airport"
        ? leg.dep === filter.value || leg.arr === filter.value
        : (leg.dep === filter.dep && leg.arr === filter.arr)
          || (leg.dep === filter.arr && leg.arr === filter.dep);
      if (hit) {
        keep.add(leg.dep);
        keep.add(leg.arr);
      }
      return hit;
    });
    if (filter.kind === "airport") keep.add(filter.value);
    const flights = filter.kind === "airport"
      ? data.flights.filter((f) => f.dep_icao === filter.value || f.arr_icao === filter.value)
      : data.flights.filter((f) => keep.has(f.dep_icao ?? "") && keep.has(f.arr_icao ?? ""));
    return {
      ...data,
      airports: data.airports.filter((a) => keep.has(a.icao)),
      legs,
      flights,
    };
  }, [data, filter]);

  const importedLegs = view ? view.legs.filter((l) => !(l.sources ?? ["AOC"]).includes("AOC")).length : 0;
  const focus = filter?.kind === "airport" ? filter.value : params.get("focus");
  const filteredEmpty = Boolean(filter && view && view.legs.length === 0);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{tr("飞行地图", "Flight map")}</h2>
          <p>{tr(
            "青色为 AOC 记录，橙色为 Volanta / 手动导入，箭头表示飞行方向，班次越多线越粗（有线宽上限）；点击机场或航段即可筛选，点击空白处取消",
            "Cyan lines are AOC records; amber lines are Volanta / manual imports; arrows show direction and more flights means a thicker line (capped). Click an airport or leg to filter; click empty map to clear.",
          )}</p>
        </div>
        <Space>
          <Select
            allowClear
            placeholder={tr("年份", "Year")}
            style={{ width: 110 }}
            value={year}
            onChange={setYear}
            options={Array.from({ length: 6 }, (_, i) => new Date().getFullYear() - i).map((y) => ({ value: y, label: String(y) }))}
          />
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load(year)}>{tr("刷新", "Refresh")}</Button>
        </Space>
      </div>

      {!navdata.available ? (
        <Alert type="info" showIcon message={tr("未导入 navdata：只能显示ICAO列表，地图上无坐标点", "navdata missing: only ICAO codes can be shown, not coordinates")} />
      ) : null}

      <Card
        className="panel"
        variant="borderless"
        styles={{ body: { padding: 8 } }}
        title={
          <Space wrap>
            <GlobalOutlined />
            <span>{tr("已飞网络", "Flown network")}</span>
            {view ? <Tag>{view.airports.length} {tr("机场", "airports")}</Tag> : null}
            {view ? <Tag>{view.legs.reduce((n, l) => n + l.count, 0)} {tr("航段", "legs")}</Tag> : null}
            {importedLegs > 0 ? <Tag color="gold">{importedLegs} {tr("导入航段", "imported")}</Tag> : null}
            {filter ? (
              <Tag color="cyan" closable onClose={() => setFilter(null)}>
                {filter.kind === "airport"
                  ? `${tr("机场", "Airport")} ${filter.value}`
                  : `${filter.dep} ↔ ${filter.arr}`}
              </Tag>
            ) : null}
          </Space>
        }
      >
        <div style={{ height: "calc(100vh - 250px)", minHeight: 480 }}>
          {view ? (
            <WorldMap
              data={view}
              dark={dark}
              focus={focus}
              basemap={settings.map_style}
              tilesUrl={settings.tiles_url}
              onSelectAirport={selectAirport}
              onSelectLeg={selectLeg}
              track={track?.points ?? null}
            />
          ) : (
            <div className="empty-hint">{tr("加载中…", "Loading…")}</div>
          )}
        </div>
      </Card>

      {filteredEmpty ? (
        <Alert
          type="warning"
          showIcon
          message={tr("该筛选下没有航段", "No legs match this filter")}
          action={<Button size="small" onClick={() => setFilter(null)}>{tr("清除筛选", "Clear filter")}</Button>}
        />
      ) : null}

      <Card
        className="panel"
        variant="borderless"
        title={
          <Space>
            <span>{tr("航班记录", "Flights")}</span>
            {view ? <Tag>{view.flights.length}</Tag> : null}
          </Space>
        }
        extra={filter ? <Button size="small" onClick={() => setFilter(null)}>{tr("清除筛选", "Clear filter")}</Button> : null}
      >
        <Table
          size="small"
          rowKey="id"
          dataSource={view?.flights ?? []}
          pagination={{ pageSize: 8, hideOnSinglePage: true }}
          onRow={(row) => ({ onClick: () => navigate(`/logs/${row.id}`), style: { cursor: "pointer" } })}
          locale={{
            emptyText: filter
              ? tr("没有符合条件的本地飞行记录（导入航班见下方）", "No local flight records match (see imported flights below)")
              : tr("暂无可展示的飞行", "No flights yet"),
          }}
          columns={[
            {
              title: tr("时间", "Time"),
              dataIndex: "block_off_utc",
              width: 160,
              render: (v: string | undefined) => fmtDateTime(v),
            },
            {
              title: tr("航段", "Leg"),
              render: (_: unknown, row) => (
                <Space size={4}>
                  <Tag>{row.dep_icao || "????"}</Tag>
                  <span className="muted">→</span>
                  <Tag>{row.arr_icao || "????"}</Tag>
                </Space>
              ),
            },
            { title: tr("机型", "Aircraft"), dataIndex: "aircraft_type", width: 100 },
            {
              title: tr("落地", "Landing"),
              dataIndex: "landing_rating",
              width: 100,
              render: (v: string | undefined) => {
                const meta = v ? ratingLabels[v] : null;
                return <Tag color={meta?.color}>{meta ? tr(meta.zh, meta.en) : (v || "—")}</Tag>;
              },
            },
            {
              title: "",
              width: 80,
              render: (_: unknown, row) => (
                <Button size="small" type="link" onClick={(e) => { e.stopPropagation(); navigate(`/logs/${row.id}`); }}>
                  {tr("查看", "Open")}
                </Button>
              ),
            },
          ]}
        />
      </Card>

      <Card
        className="panel"
        variant="borderless"
        title={
          <Space>
            <span>{tr("导入 / 补录航班", "Imported / manual flights")}</span>
            <Tag>{importedFlights.length}</Tag>
          </Space>
        }
        extra={track ? (
          <Space>
            <Tag color="purple">{track.points.length} {tr("轨迹点", "points")}</Tag>
            <Button size="small" onClick={() => setTrack(null)}>{tr("隐藏轨迹", "Hide track")}</Button>
          </Space>
        ) : null}
      >
        <Table
          size="small"
          rowKey="id"
          loading={trackBusy}
          dataSource={importedFlights}
          pagination={{ pageSize: 12, showSizeChanger: true, pageSizeOptions: [12, 24, 48, 96], showTotal: (n) => `${n} ${tr("条", "rows")}` }}
          locale={{
            emptyText: tr("暂无导入航班明细（CSV/接口导入后会保存在本地）", "No imported flights stored yet"),
          }}
          onRow={(row) => ({ onClick: () => void openTrack(row), style: { cursor: "pointer" } })}
          columns={[
            {
              title: tr("航班号", "Flight"),
              dataIndex: "callsign",
              width: 110,
              render: (v: string | null | undefined) => (v ? <span className="mono">{v}</span> : "—"),
            },
            { title: tr("日期", "Date"), dataIndex: "flight_date", width: 120, render: (v: string | null | undefined) => v || "—" },
            {
              title: tr("航段", "Leg"),
              render: (_: unknown, row) => (
                <Space size={4}>
                  <Tag>{row.dep_icao || "????"}</Tag>
                  <span className="muted">→</span>
                  <Tag>{row.arr_icao || "????"}</Tag>
                </Space>
              ),
            },
            {
              title: tr("机型", "Aircraft"),
              width: 150,
              render: (_: unknown, row) => {
                const type = row.aircraft_type || "";
                const reg = row.registration || "";
                if (!type && !reg) return "—";
                return (
                  <span>
                    {type || "—"}
                    {reg ? <span className="muted"> · {reg}</span> : null}
                  </span>
                );
              },
            },
            { title: tr("时长", "Duration"), dataIndex: "duration_min", width: 100, render: (v: number | null | undefined) => (v ? `${v} min` : "—") },
            {
              title: tr("接地率", "Landing"),
              dataIndex: "landing_rate_fpm",
              width: 110,
              render: (v: number | null | undefined) => (v != null ? `${Math.round(v)} fpm` : "—"),
            },
          ]}
        />
      </Card>

      {data && data.airports.length === 0 ? (
        <Card className="panel" variant="borderless">
          <Text className="muted">{tr("还没有已飞机场。完成一次飞行或导入 Volanta CSV 后会出现在这里。", "No airports yet. Complete a flight or import a Volanta CSV.")}</Text>
        </Card>
      ) : null}
    </div>
  );
}
