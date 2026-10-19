import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import type { GeoJSONSource, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import trackData from "./data/track.json";

const points = trackData.points as [number, number][];
const intervalS = trackData.interval_s;
const totalS = (points.length - 1) * intervalS;

const lineFeature = (coords: [number, number][]) => ({
  type: "Feature" as const,
  geometry: { type: "LineString" as const, coordinates: coords },
  properties: {},
});

const pointFeature = (coord: [number, number]) => ({
  type: "Feature" as const,
  geometry: { type: "Point" as const, coordinates: coord },
  properties: {},
});

const style: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap",
    },
    route: { type: "geojson", data: lineFeature(points) },
    progress: { type: "geojson", data: lineFeature([]) },
    cursor: { type: "geojson", data: pointFeature(points[0]) },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#0b1220" } },
    { id: "osm", type: "raster", source: "osm", paint: { "raster-opacity": 0.5, "raster-saturation": -0.7 } },
    { id: "route", type: "line", source: "route",
      paint: { "line-color": "#334155", "line-width": 1.5, "line-dasharray": [2, 3] } },
    { id: "progress", type: "line", source: "progress",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#38bdf8", "line-width": 2.4 } },
    { id: "cursor", type: "circle", source: "cursor",
      paint: { "circle-radius": 5, "circle-color": "#f8fafc",
               "circle-stroke-color": "#0ea5e9", "circle-stroke-width": 2 } },
  ],
};

function fmt(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;
}

function pathNm(coords: [number, number][]): number {
  let d = 0;
  for (let i = 1; i < coords.length; i++) {
    const [lon1, lat1] = coords[i - 1];
    const [lon2, lat2] = coords[i];
    const p1 = (lat1 * Math.PI) / 180;
    const p2 = (lat2 * Math.PI) / 180;
    const dp = p2 - p1;
    const dl = ((lon2 - lon1) * Math.PI) / 180;
    const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    d += 2 * 3440.065 * Math.asin(Math.min(1, Math.sqrt(h)));
  }
  return d;
}

export default function App() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const idxRef = useRef(0);
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(120);
  const [index, setIndex] = useState(0);
  const [fps, setFps] = useState(0);
  const distance = useMemo(() => pathNm(points), []);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style,
      center: points[0],
      zoom: 7,
      attributionControl: false,
    });
    mapRef.current = map;
    map.on("load", () => {
      map.fitBounds([points[0], points[points.length - 1]], { padding: 80, duration: 0 });
      setReady(true);
    });
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!ready) return;
    let raf = 0;
    let last = performance.now();
    let lastUi = last;
    let frames = 0;
    const tick = (now: number) => {
      const dt = Math.min(0.25, (now - last) / 1000);
      last = now;
      if (playing) {
        idxRef.current = Math.min(points.length - 1, idxRef.current + (dt * speed) / intervalS);
      }
      const i = Math.floor(idxRef.current);
      const progress = mapRef.current?.getSource("progress") as GeoJSONSource | undefined;
      progress?.setData(lineFeature(points.slice(0, i + 1)));
      const cursor = mapRef.current?.getSource("cursor") as GeoJSONSource | undefined;
      cursor?.setData(pointFeature(points[i]));
      frames++;
      if (now - lastUi >= 500) {
        setFps((frames * 1000) / (now - lastUi));
        setIndex(i);
        frames = 0;
        lastUi = now;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [ready, playing, speed]);

  const seek = (i: number) => {
    idxRef.current = i;
    setIndex(i);
    const progress = mapRef.current?.getSource("progress") as GeoJSONSource | undefined;
    progress?.setData(lineFeature(points.slice(0, i + 1)));
    const cursor = mapRef.current?.getSource("cursor") as GeoJSONSource | undefined;
    cursor?.setData(pointFeature(points[i]));
  };

  return (
    <>
      <div ref={containerRef} className="map" />
      <div className="panel">
        <div className="row">
          <h1>AOC 轨迹回放 · 10,000 点</h1>
          <span className="badge">{fps.toFixed(0)} FPS</span>
        </div>
        <div className="sub">1 Hz 采样 · 回放倍速 {speed}× · 轨迹 {distance.toFixed(0)} NM</div>
        <div className="row">
          <button onClick={() => setPlaying((p) => !p)}>{playing ? "暂停" : "播放"}</button>
          <input
            type="range"
            min={0}
            max={points.length - 1}
            value={index}
            onChange={(e) => seek(Number(e.target.value))}
          />
        </div>
        <div className="row">
          <span className="mono">{fmt(index * intervalS)} / {fmt(totalS)}</span>
          <span className="mono" style={{ marginLeft: "auto" }}>倍速</span>
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            <option value={10}>10×</option>
            <option value={60}>60×</option>
            <option value={120}>120×</option>
            <option value={240}>240×</option>
          </select>
        </div>
        <div className="row mono">已渲染 {index + 1} / {points.length} 点 · 单条 LineString 增量 setData</div>
      </div>
    </>
  );
}
