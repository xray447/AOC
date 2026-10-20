import { Button, Empty, Select, Slider, Space, Tag, Tooltip } from "antd";
import maplibregl from "maplibre-gl";
import type { GeoJSONSource, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { basemapStyle } from "../basemap";
import { useI18n } from "../i18n";
import type { FlightEvent, TrackPoint } from "../types";
import { splitAntimeridian, type LonLat } from "../utils";

interface Props {
  points: TrackPoint[];
  events?: FlightEvent[];
  dark?: boolean;
  height?: number;
  tilesUrl?: string | null;
  basemap?: string | null;
}

function routeFeature(points: TrackPoint[]) {
  return {
    type: "Feature" as const,
    geometry: {
      type: "MultiLineString" as const,
      // 跨 ±180° 的轨迹切成两段，避免回放时线条绕地球一圈
      coordinates: splitAntimeridian(points.map((p): LonLat => [p.lon, p.lat])),
    },
    properties: {},
  };
}

function pointFeature(p: TrackPoint) {
  return {
    type: "Feature" as const,
    geometry: { type: "Point" as const, coordinates: [p.lon, p.lat] },
    properties: {},
  };
}

function buildStyle(dark: boolean, basemap?: string | null, tilesUrl?: string | null): StyleSpecification {
  const base = basemapStyle(dark, basemap, tilesUrl);
  return {
    version: 8,
    sources: {
      ...base.sources,
      track: { type: "geojson", data: routeFeature([]) },
      progress: { type: "geojson", data: routeFeature([]) },
      cursor: { type: "geojson", data: pointFeature({ t: 0, lat: 0, lon: 0 }) },
    },
    layers: [
      ...base.layers,
      { id: "track", type: "line", source: "track",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": dark ? "#3b4a63" : "#9aa8bc", "line-width": 1.6, "line-dasharray": [2, 3] } },
      { id: "progress", type: "line", source: "progress",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#22d3ee", "line-width": 2.6 } },
      { id: "cursor", type: "circle", source: "cursor",
        paint: { "circle-radius": 5.5, "circle-color": "#f8fafc",
                 "circle-stroke-color": "#0ea5e9", "circle-stroke-width": 2 } },
    ],
  };
}

function fmtClock(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;
}

export function TrackMap({ points, events = [], dark = true, height = 420, tilesUrl, basemap }: Props) {
  const { tr } = useI18n();
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(30);
  const [currentT, setCurrentT] = useState(0);
  const currentRef = useRef(0);

  const start = points.length ? points[0].t : 0;
  const end = points.length ? points[points.length - 1].t : 0;
  const total = Math.max(1, end - start);

  const chart = useMemo(() => {
    if (!points.length) return null;
    const n = points.length;
    const step = Math.max(1, Math.floor(n / 700));
    const sampled = points.filter((_, i) => i % step === 0 || i === n - 1);
    const alts = points.map((p) => p.alt_ft ?? 0);
    const maxAlt = Math.max(1, ...alts);
    const gss = points.map((p) => p.gs_kt ?? 0);
    const maxGs = Math.max(1, ...gss);
    const W = 800, H = 110;
    const x = (t: number) => ((t - start) / total) * W;
    const altPath = sampled.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t).toFixed(1)},${(H - 8 - ((p.alt_ft ?? 0) / maxAlt) * (H - 26)).toFixed(1)}`).join(" ");
    const gsPath = sampled.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t).toFixed(1)},${(H - 8 - ((p.gs_kt ?? 0) / maxGs) * (H - 26)).toFixed(1)}`).join(" ");
    return { altPath, gsPath, maxAlt, maxGs, W, H, x };
  }, [points, start, total]);

  const indexAt = (t: number): number => {
    if (!points.length) return 0;
    let lo = 0, hi = points.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (points[mid].t <= t) lo = mid; else hi = mid - 1;
    }
    return lo;
  };

  const applyProgress = (t: number) => {
    const map = mapRef.current;
    if (!map || !ready || !points.length) return;
    const index = indexAt(t);
    const progress = map.getSource("progress") as GeoJSONSource | undefined;
    progress?.setData(routeFeature(points.slice(0, index + 1)));
    const cursor = map.getSource("cursor") as GeoJSONSource | undefined;
    cursor?.setData(pointFeature(points[index]));
  };

  useEffect(() => {
    if (!container.current || !points.length) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: buildStyle(dark, basemap, tilesUrl),
      center: [points[0].lon, points[0].lat],
      zoom: 5,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    // 底图不可达时 load 不触发，用 style.load 才能保证轨迹能画出来
    map.on("style.load", () => {
      setReady(true);
      const lons = points.map((p) => p.lon), lats = points.map((p) => p.lat);
      // 跨 ±180° 时把负经度平移到 180 之后，否则边界会横跨整个地球、缩放失真
      const wrapped = Math.max(...lons) - Math.min(...lons) > 180
        ? lons.map((lon) => (lon < 0 ? lon + 360 : lon))
        : lons;
      map.fitBounds([[Math.min(...wrapped), Math.min(...lats)], [Math.max(...wrapped), Math.max(...lats)]],
        { padding: 60, duration: 0, maxZoom: 9 });
      const track = map.getSource("track") as GeoJSONSource | undefined;
      track?.setData(routeFeature(points));
      applyProgress(start);
    });
    return () => {
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, dark, tilesUrl, basemap]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !points.length) return;
    const track = map.getSource("track") as GeoJSONSource | undefined;
    track?.setData(routeFeature(points));
    applyProgress(currentRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, points]);

  useEffect(() => {
    currentRef.current = currentT;
    applyProgress(currentT);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentT, ready]);

  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.5, (now - last) / 1000);
      last = now;
      currentRef.current = Math.min(end, currentRef.current + dt * speed);
      setCurrentT(currentRef.current);
      if (currentRef.current >= end) setPlaying(false);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, end]);

  if (!points.length) {
    return <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Empty description={tr("没有轨迹数据", "No track data")} />
    </div>;
  }

  const index = indexAt(currentT);
  const p = points[index];
  const eventList = events.slice(0, 6);

  return (
    <div className="track-replay">
      <div ref={container} className="track-map" style={{ height }} />
      <div className="track-chart">
        {chart ? (
          <svg viewBox={`0 0 ${chart.W} ${chart.H}`} preserveAspectRatio="none" className="chart-svg">
            <path d={chart.altPath} fill="none" stroke="#38bdf8" strokeWidth="1.6" />
            <path d={chart.gsPath} fill="none" stroke="#f59e0b" strokeWidth="1.2" opacity="0.85" />
            <line x1={chart.x(currentT)} x2={chart.x(currentT)} y1="0" y2={chart.H} stroke="#e2e8f0" strokeWidth="1" strokeDasharray="3 3" />
          </svg>
        ) : null}
        <div className="chart-legend">
          <Tag color="blue">{tr("高度", "Altitude")} {Math.round(p.alt_ft ?? 0)} ft</Tag>
          <Tag color="gold">{tr("地速", "GS")} {Math.round(p.gs_kt ?? 0)} kt</Tag>
          <Tag color="cyan">{tr("垂直速度", "V/S")} {Math.round(p.vs_fpm ?? 0)} fpm</Tag>
          <Tag>{tr("过载", "G")} {(p.g ?? 0).toFixed(2)}</Tag>
        </div>
      </div>
      <div className="track-controls">
        <Space wrap>
          <Button type={playing ? "default" : "primary"} onClick={() => setPlaying((v) => !v)}>
            {playing ? tr("暂停", "Pause") : tr("播放", "Play")}
          </Button>
          <Select
            size="small"
            value={speed}
            onChange={setSpeed}
            options={[1, 4, 16, 60, 240].map((v) => ({ value: v, label: `${v}×` }))}
            style={{ width: 86 }}
          />
          <span className="mono">{fmtClock(currentT - start)} / {fmtClock(total)}</span>
          <span className="muted">{tr("轨迹点", "Points")} {points.length}</span>
          <Tooltip title={tr("拖动定位", "Seek")}>
            <Slider
              style={{ width: 220, margin: 0 }}
              min={start}
              max={end}
              step={0.5}
              value={currentT}
              onChange={(v) => { setCurrentT(v); currentRef.current = v; }}
            />
          </Tooltip>
        </Space>
        {eventList.length ? (
          <Space size={4} wrap style={{ marginTop: 6 }}>
            {eventList.map((e, i) => {
              const t = e.t_offset_ms / 1000;
              return <Tag key={i} style={{ cursor: "pointer" }} onClick={() => { setCurrentT(t); currentRef.current = t; }}>
                {e.type} {fmtClock(t)}
              </Tag>;
            })}
          </Space>
        ) : null}
      </div>
    </div>
  );
}
