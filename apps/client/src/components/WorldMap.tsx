import maplibregl from "maplibre-gl";
import type { ExpressionSpecification, FilterSpecification, GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef } from "react";
import { basemapStyle } from "../basemap";
import type { MapData } from "../types";
import { useI18n } from "../i18n";
import { escapeHtml, splitAntimeridian, type LonLat } from "../utils";

/**
 * 实线线宽：随班次按平方根增长（多的永远比少的粗），并封顶 5px。
 * 1 班 ≈ 1.9px、3 班 ≈ 2.5px、5 班 ≈ 2.9px、10 班 ≈ 3.7px、22 班以上封顶 5px。
 * 斜率不能太小：导入几十班和只飞过一两班的航段要一眼看出差别。
 */
const LEG_WIDTH: ExpressionSpecification = [
  "min",
  5,
  ["+", 1, ["*", 0.85, ["sqrt", ["get", "count"]]]],
] as unknown as ExpressionSpecification;

/** 反向航段（A→B 与 B→A 同时存在）的侧向偏移像素，避免两条线互相盖住。 */
const LEG_OFFSET_PX = 6;

/** 经纬度 → Web Mercator 世界坐标（x、y 都在 0~1，y 向南为正），与地图投影一致。 */
function mercX(lon: number): number {
  return (lon + 180) / 360;
}

function mercY(lat: number): number {
  // 墨卡托在两极发散，先按 Web Mercator 的极限纬度截断
  const clamped = Math.max(-85.0511, Math.min(85.0511, lat));
  const rad = (clamped * Math.PI) / 180;
  return 0.5 - Math.log(Math.tan(Math.PI / 4 + rad / 2)) / (2 * Math.PI);
}

/** 世界坐标 → 经纬度（经度归一到 -180~180）。 */
function unmercX(x: number): number {
  return ((((x * 360 - 180) % 360) + 540) % 360) - 180;
}

function unmercY(y: number): number {
  return (Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180) / Math.PI;
}

/**
 * 箭头在墨卡托世界坐标中的位置。
 * 地图上的航段是按投影后的直线画的，箭头也必须按同一条直线插值，否则长航段/高纬度会明显偏出线外。
 * nx/ny 是航段的单位法向（前进方向右侧），offset 是需要跟随 line-offset 侧移的像素数。
 */
interface ArrowSpec {
  x: number;
  y: number;
  nx: number;
  ny: number;
  offset: number;
  rotate: number;
  color: string;
}

interface Props {
  data: MapData;
  dark?: boolean;
  focus?: string | null;
  /** 底图 id（设置里的 map_style），custom 时用 tilesUrl */
  basemap?: string | null;
  tilesUrl?: string | null;
  onSelectAirport?: (icao: string) => void;
  onSelectLeg?: (dep: string, arr: string) => void;
  /** 选中的导入航班轨迹（[[lon, lat], ...]） */
  track?: LonLat[] | null;
}

export function WorldMap({ data, dark = true, focus, basemap, tilesUrl, onSelectAirport, onSelectLeg, track }: Props) {
  const { tr } = useI18n();
  // 弹窗文案用的是 ref，避免 tr 变化导致整张地图重建
  const trRef = useRef(tr);
  trRef.current = tr;
  const selectAirportRef = useRef(onSelectAirport);
  selectAirportRef.current = onSelectAirport;
  const selectLegRef = useRef(onSelectLeg);
  selectLegRef.current = onSelectLeg;
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  const points = useMemo(() => {
    // 机场弹窗需要的出发/到达次数与连接机场数：按航段聚合到机场
    const departures = new Map<string, number>();
    const arrivals = new Map<string, number>();
    const neighbors = new Map<string, Set<string>>();
    const link = (from: string, to: string) => {
      const set = neighbors.get(from) ?? new Set<string>();
      set.add(to);
      neighbors.set(from, set);
    };
    for (const leg of data.legs) {
      departures.set(leg.dep, (departures.get(leg.dep) ?? 0) + leg.count);
      arrivals.set(leg.arr, (arrivals.get(leg.arr) ?? 0) + leg.count);
      link(leg.dep, leg.arr);
      link(leg.arr, leg.dep);
    }
    const features = data.airports
      .filter((a) => a.lat != null && a.lon != null)
      .map((a) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [a.lon as number, a.lat as number] },
        properties: {
          icao: a.icao,
          country: a.country || "",
          name: a.name || "",
          iata: a.iata || "",
          city: a.city || "",
          elev_ft: a.elev_ft ?? null,
          departures: departures.get(a.icao) ?? 0,
          arrivals: arrivals.get(a.icao) ?? 0,
          connections: neighbors.get(a.icao)?.size ?? 0,
        },
      }));
    return { type: "FeatureCollection" as const, features };
  }, [data]);

  const trackLine = useMemo(() => {
    const segments = track && track.length >= 2 ? splitAntimeridian(track) : [];
    return {
      type: "FeatureCollection" as const,
      features: segments.length
        ? [{
            type: "Feature" as const,
            geometry: { type: "MultiLineString" as const, coordinates: segments },
            properties: {},
          }]
        : [],
    };
  }, [track]);

  const { lines, importedLines, arrowSpecs } = useMemo(() => {
    type LineFeature = {
      type: "Feature";
      geometry: { type: "MultiLineString"; coordinates: LonLat[][] };
      properties: { count: number; dep: string; arr: string; reverse: boolean; dir: number };
    };
    const byIcao = new Map(data.airports.map((a) => [a.icao, a]));
    // 同一对机场已有反向航班时，两条线各自偏移几像素，避免互相盖住
    const directed = new Set(data.legs.map((l) => `${l.dep}|${l.arr}`));
    const recorded: LineFeature[] = [];
    const imported: LineFeature[] = [];
    const specs: ArrowSpec[] = [];
    for (const leg of data.legs) {
      const a = byIcao.get(leg.dep);
      const b = byIcao.get(leg.arr);
      if (!a || !b || a.lat == null || a.lon == null || b.lat == null || b.lon == null) continue;
      // 跨 ±180° 的航段（如跨太平洋）切成两段，避免绕地球画一整圈
      const segments = splitAntimeridian([[a.lon, a.lat], [b.lon, b.lat]]);
      if (!segments.length) continue;
      const reverse = directed.has(`${leg.arr}|${leg.dep}`);
      const dir = leg.dep < leg.arr ? 1 : -1;
      const feature: LineFeature = {
        type: "Feature",
        geometry: { type: "MultiLineString", coordinates: segments },
        properties: { count: leg.count, dep: leg.dep, arr: leg.arr, reverse, dir },
      };
      const isAoc = (leg.sources ?? ["AOC"]).includes("AOC");
      if (isAoc) recorded.push(feature);
      else imported.push(feature);

      // 方向箭头：在墨卡托平面上插值取点（与地图实际绘制航段的直线一致），位置按方向错开
      const color = isAoc ? "#22d3ee" : "#f59e0b";
      const fractions = dir === 1 ? [0.32, 0.64] : [0.46, 0.78];
      let xa = mercX(a.lon);
      let xb = mercX(b.lon);
      // 反经线航段：终点经度展开到起点附近，走较短的经向路径
      if (xb - xa > 0.5) xb -= 1;
      else if (xb - xa < -0.5) xb += 1;
      const ya = mercY(a.lat);
      const yb = mercY(b.lat);
      const dx = xb - xa;
      const dy = yb - ya;
      const len = Math.hypot(dx, dy) || 1;
      // 屏幕坐标 y 向南，方位角 0=正北、顺时针
      const rotate = (Math.atan2(dx, -dy) * 180) / Math.PI;
      // line-offset 正值把反向航段推到前进方向的右侧，箭头跟着侧移才能压在线上
      const nx = -dy / len;
      const ny = dx / len;
      for (const f of fractions) {
        specs.push({
          x: xa + dx * f,
          y: ya + dy * f,
          nx, ny,
          offset: reverse ? LEG_OFFSET_PX : 0,
          rotate, color,
        });
      }
    }
    return {
      lines: { type: "FeatureCollection" as const, features: recorded },
      importedLines: { type: "FeatureCollection" as const, features: imported },
      arrowSpecs: specs,
    };
  }, [data]);

  const arrowSpecsRef = useRef<ArrowSpec[]>([]);
  arrowSpecsRef.current = arrowSpecs;

  /**
   * 生成箭头图层的数据。line-offset 以屏幕像素为单位，缩放后折算到世界坐标的长度会变，
   * 所以侧移量按当前缩放实时换算，箭头才能一直落在偏移后的线上。
   */
  const buildArrows = (zoom: number) => {
    const worldPx = 512 * 2 ** zoom;
    const features = arrowSpecsRef.current.map((s) => {
      const k = s.offset / worldPx;
      return {
        type: "Feature" as const,
        geometry: {
          type: "Point" as const,
          coordinates: [unmercX(s.x + s.nx * k), unmercY(s.y + s.ny * k)] as [number, number],
        },
        properties: { rotate: s.rotate, color: s.color },
      };
    });
    return { type: "FeatureCollection" as const, features };
  };

  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: basemapStyle(dark, basemap, tilesUrl),
      center: [110, 32],
      zoom: 2.4,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    let cancelArrowRefresh: (() => void) | null = null;
    // 调试/自动化用：把实例挂到容器元素上，便于断言图层与坐标投影
    (container.current as unknown as { __aocMap?: maplibregl.Map }).__aocMap = map;
    // 用 style.load（样式解析完成）而不是 load：底图瓦片不可达时 load 可能永远不触发，
    // 会让所有数据图层都加不上
    map.on("style.load", () => {
      map.addSource("airports", { type: "geojson", data: points });
      map.addSource("legs", { type: "geojson", data: lines });
      map.addSource("imported-legs", { type: "geojson", data: importedLines });
      map.addSource("volanta-track", { type: "geojson", data: trackLine });
      // 全部实线：线宽随班次增长（1 班细，20 班明显粗）
      map.addLayer({
        id: "legs", type: "line", source: "legs",
        filter: ["!=", ["get", "reverse"], true],
        paint: {
          "line-color": "#22d3ee", "line-width": LEG_WIDTH,
          "line-opacity": 0.6,
        },
      });
      map.addLayer({
        id: "legs-pair", type: "line", source: "legs",
        filter: ["==", ["get", "reverse"], true],
        paint: {
          "line-color": "#22d3ee", "line-width": LEG_WIDTH,
          "line-opacity": 0.6, "line-offset": LEG_OFFSET_PX,
        },
      });
      map.addLayer({
        id: "imported-legs", type: "line", source: "imported-legs",
        filter: ["!=", ["get", "reverse"], true],
        paint: {
          "line-color": "#f59e0b", "line-width": LEG_WIDTH,
          "line-opacity": 0.55,
        },
      });
      map.addLayer({
        id: "imported-legs-pair", type: "line", source: "imported-legs",
        filter: ["==", ["get", "reverse"], true],
        paint: {
          "line-color": "#f59e0b", "line-width": LEG_WIDTH,
          "line-opacity": 0.55, "line-offset": LEG_OFFSET_PX,
        },
      });
      // 透明点击热区：细线也能点中；反向航段跟随各自偏移，两个方向不会互相抢点击
      const hitLayers: [string, string, FilterSpecification, number][] = [
        ["legs-hit", "legs", ["!=", ["get", "reverse"], true], 0],
        ["legs-pair-hit", "legs", ["==", ["get", "reverse"], true], LEG_OFFSET_PX],
        ["imported-legs-hit", "imported-legs", ["!=", ["get", "reverse"], true], 0],
        ["imported-legs-pair-hit", "imported-legs", ["==", ["get", "reverse"], true], LEG_OFFSET_PX],
      ];
      for (const [id, source, filter, offset] of hitLayers) {
        map.addLayer({
          id, type: "line", source, filter,
          paint: {
            "line-color": "#000000", "line-width": 10, "line-opacity": 0,
            ...(offset ? { "line-offset": offset } : {}),
          },
        });
      }

      // 方向箭头：canvas 生成图标，按每条航段的方位角旋转（0=正北，顺时针），与航线方向一致
      if (!map.hasImage("leg-arrow")) {
        const size = 24;
        const canvas = document.createElement("canvas");
        canvas.width = size;
        canvas.height = size;
        const ctx = canvas.getContext("2d");
        if (ctx) {
          ctx.clearRect(0, 0, size, size);
          ctx.fillStyle = "#ffffff";
          ctx.beginPath();
          ctx.moveTo(size / 2, 1);
          ctx.lineTo(size - 3, size - 3);
          ctx.lineTo(size / 2, size - 8);
          ctx.lineTo(3, size - 3);
          ctx.closePath();
          ctx.fill();
          map.addImage("leg-arrow", ctx.getImageData(0, 0, size, size), { sdf: true });
        }
      }
      map.addSource("arrows", { type: "geojson", data: buildArrows(map.getZoom()) });
      map.addLayer({
        id: "arrows", type: "symbol", source: "arrows",
        layout: {
          "icon-image": "leg-arrow",
          "icon-size": 0.5,
          "icon-rotate": ["get", "rotate"],
          "icon-rotation-alignment": "viewport",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
        paint: { "icon-color": ["get", "color"], "icon-opacity": 0.95 },
      });
      // line-offset 以屏幕像素计，缩放后折算成世界坐标的长度会变，箭头位置跟着重算
      let arrowFrame = 0;
      const refreshArrows = () => {
        if (arrowFrame) return;
        arrowFrame = requestAnimationFrame(() => {
          arrowFrame = 0;
          (map.getSource("arrows") as GeoJSONSource | undefined)?.setData(buildArrows(map.getZoom()));
        });
      };
      map.on("zoom", refreshArrows);
      cancelArrowRefresh = () => {
        if (arrowFrame) cancelAnimationFrame(arrowFrame);
        arrowFrame = 0;
      };

      map.addLayer({
        id: "volanta-track", type: "line", source: "volanta-track",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#a855f7", "line-width": 2.2, "line-opacity": 0.9 },
      });
      map.addLayer({
        id: "airports", type: "circle", source: "airports",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 2.4, 5, 5],
          "circle-color": "#f8fafc", "circle-stroke-color": "#0ea5e9", "circle-stroke-width": 1.4,
        },
      });
      const hitLayerIds = hitLayers.map(([id]) => id);

      /**
       * 命中哪条航段：queryRenderedFeatures 返回的是未偏移的几何，
       * 反向航段两个方向会同时被命中。这里按「点击点到各自偏移后线」的距离取最近的那条。
       */
      const nearestLeg = (point: maplibregl.Point) => {
        const feats = map.queryRenderedFeatures(point, { layers: hitLayerIds });
        let best: (typeof feats)[number] | null = null;
        let bestDist = Infinity;
        for (const f of feats) {
          const props = f.properties as { reverse?: boolean };
          const offset = props.reverse ? LEG_OFFSET_PX : 0;
          const g = f.geometry as unknown as { type: string; coordinates: unknown };
          const segments: [number, number][][] = g.type === "MultiLineString"
            ? (g.coordinates as [number, number][][])
            : [g.coordinates as [number, number][]];
          let dist = Infinity;
          for (const seg of segments) {
            for (let i = 1; i < seg.length; i += 1) {
              const a = map.project(seg[i - 1]);
              const b = map.project(seg[i]);
              const dx = b.x - a.x;
              const dy = b.y - a.y;
              const len = Math.hypot(dx, dy) || 1;
              const signed = (dx * (point.y - a.y) - dy * (point.x - a.x)) / len;
              // line-offset 正值把线推到前进方向右侧，屏幕坐标 y 向下时右侧对应 signed 为正
              dist = Math.min(dist, Math.abs(signed - offset));
            }
          }
          if (dist < bestDist) {
            bestDist = dist;
            best = f;
          }
        }
        return best;
      };

      const showLeg = (f: maplibregl.MapGeoJSONFeature, lngLat: maplibregl.LngLat) => {
        const props = f.properties as { dep: string; arr: string; count: number };
        const source = f.layer.id.includes("imported") ? "Volanta / imported" : "AOC";
        const tr = trRef.current;
        new maplibregl.Popup({ closeButton: true, maxWidth: "260px" })
          .setLngLat(lngLat)
          .setHTML(`<div style="font-weight:600">${escapeHtml(props.dep)} → ${escapeHtml(props.arr)}</div>`
            + `<div style="color:#94a3b8">${props.count} ${tr("班", "legs")} · ${escapeHtml(source)}</div>`
            + `<div style="color:#475569;margin-top:2px">${tr("已按此航段筛选", "Filtered by this leg")}</div>`
            + `<a href="/route?dep=${encodeURIComponent(props.dep)}&arr=${encodeURIComponent(props.arr)}" style="display:inline-block;margin-top:4px;color:#38bdf8">${tr("查看航路", "Plan route")} →</a>`)
          .addTo(map);
        selectLegRef.current?.(props.dep, props.arr);
      };
      map.on("click", "airports", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const p = f.properties as {
          icao: string; country: string; name: string; iata: string; city: string;
          elev_ft: number | null; departures: number; arrivals: number; connections: number;
        };
        const tr = trRef.current;
        const place = [p.city, p.country].filter(Boolean).map(escapeHtml).join(", ");
        const html = [
          `<div style="font-weight:600">${escapeHtml(p.icao)}${p.iata ? ` · ${escapeHtml(p.iata)}` : ""}</div>`,
          p.name ? `<div style="margin-top:2px">${escapeHtml(p.name)}</div>` : "",
          place ? `<div style="color:#94a3b8">${place}</div>` : "",
          p.elev_ft != null ? `<div style="color:#94a3b8">${Math.round(p.elev_ft)} ft</div>` : "",
          `<div style="color:#475569;margin-top:2px">${tr("出发", "Dep")} ${p.departures} · ${tr("到达", "Arr")} ${p.arrivals}</div>`,
          `<div style="color:#94a3b8">${tr("地点", "Places")} ${p.connections} · ${tr("班次", "Flights")} ${p.departures + p.arrivals}</div>`,
          `<div style="color:#475569;margin-top:2px">${tr("已按此机场筛选，点击地图空白处取消", "Filtered by this airport; click empty map to clear")}</div>`,
          `<a href="/route?dep=${encodeURIComponent(p.icao)}" style="display:inline-block;margin-top:4px;color:#38bdf8">${tr("生成航路", "Plan route")} →</a>`,
        ];
        new maplibregl.Popup({ closeButton: true, maxWidth: "280px" })
          .setLngLat((f.geometry as unknown as { coordinates: [number, number] }).coordinates)
          .setHTML(html.filter(Boolean).join(""))
          .addTo(map);
        selectAirportRef.current?.(p.icao);
      });
      map.on("click", (e) => {
        // 机场圆点优先；其次按偏移后的距离选最近航段；都没有则清除筛选
        if (map.queryRenderedFeatures(e.point, { layers: ["airports"] }).length) return;
        const f = nearestLeg(e.point);
        if (f) {
          showLeg(f, e.lngLat);
          return;
        }
        selectAirportRef.current?.("");
      });
      map.on("mousemove", (e) => {
        const over = map.queryRenderedFeatures(e.point, { layers: ["airports"] }).length > 0
          || nearestLeg(e.point) !== null;
        map.getCanvas().style.cursor = over ? "pointer" : "";
      });
    });
    return () => {
      cancelArrowRefresh?.();
      map.remove();
      mapRef.current = null;
      if (container.current) {
        delete (container.current as unknown as { __aocMap?: maplibregl.Map }).__aocMap;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dark, basemap, tilesUrl]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      (map.getSource("airports") as GeoJSONSource | undefined)?.setData(points);
      (map.getSource("legs") as GeoJSONSource | undefined)?.setData(lines);
      (map.getSource("imported-legs") as GeoJSONSource | undefined)?.setData(importedLines);
      (map.getSource("volanta-track") as GeoJSONSource | undefined)?.setData(trackLine);
      (map.getSource("arrows") as GeoJSONSource | undefined)?.setData(buildArrows(map.getZoom()));
    };
    if (map.getSource("airports")) apply();
    else map.once("style.load", apply);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, lines, importedLines, trackLine, arrowSpecs]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !track || track.length < 2) return;
    const lons = track.map((p) => p[0]);
    const lats = track.map((p) => p[1]);
    const wrapped = Math.max(...lons) - Math.min(...lons) > 180
      ? lons.map((lon) => (lon < 0 ? lon + 360 : lon))
      : lons;
    map.fitBounds([[Math.min(...wrapped), Math.min(...lats)], [Math.max(...wrapped), Math.max(...lats)]],
      { padding: 60, duration: 600, maxZoom: 10 });
  }, [track]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !focus) return;
    const airport = data.airports.find((a) => a.icao === focus);
    if (airport?.lat != null && airport.lon != null) {
      map.flyTo({ center: [airport.lon, airport.lat], zoom: 6, duration: 700 });
    }
  }, [focus, data]);

  return <div ref={container} style={{ width: "100%", height: "100%", borderRadius: 12, overflow: "hidden" }} />;
}
