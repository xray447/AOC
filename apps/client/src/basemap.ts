import type { StyleSpecification } from "maplibre-gl";

export interface BasemapPreset {
  id: string;
  zh: string;
  en: string;
  /** 栅格瓦片模板；离线底图没有 */
  tiles?: string;
  attribution?: string;
  maxzoom?: number;
  offline?: boolean;
}

/**
 * 可选底图。离线底图不请求任何瓦片，只用内置经纬网（机场线与航段仍由数据层绘制）。
 * OpenStreetMap 官方瓦片仅供个人低流量使用，长期使用建议换 CARTO 或自建。
 */
export const BASEMAPS: BasemapPreset[] = [
  { id: "offline", zh: "离线（内置经纬网）", en: "Offline (built-in grid)", offline: true },
  {
    id: "osm", zh: "OpenStreetMap", en: "OpenStreetMap",
    tiles: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: "© OpenStreetMap contributors", maxzoom: 19,
  },
  {
    id: "carto_light", zh: "CARTO 浅色", en: "CARTO Light",
    tiles: "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    attribution: "© OpenStreetMap © CARTO", maxzoom: 20,
  },
  {
    id: "carto_dark", zh: "CARTO 深色", en: "CARTO Dark",
    tiles: "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    attribution: "© OpenStreetMap © CARTO", maxzoom: 20,
  },
  {
    id: "carto_voyager", zh: "CARTO Voyager", en: "CARTO Voyager",
    tiles: "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
    attribution: "© OpenStreetMap © CARTO", maxzoom: 20,
  },
  {
    id: "esri_satellite", zh: "Esri 卫星影像", en: "Esri satellite",
    tiles: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "© Esri, Maxar, Earthstar Geographics", maxzoom: 18,
  },
  { id: "custom", zh: "自定义瓦片", en: "Custom tiles" },
];

const LEGACY: Record<string, string> = { dark: "carto_dark", light: "carto_light", satellite: "esri_satellite" };

/** 兼容旧设置值（dark/light/satellite）与无效值，最终一定落到一个可用底图。 */
export function resolveBasemap(source?: string | null, customUrl?: string | null): BasemapPreset {
  const id = LEGACY[(source || "").trim()] || (source || "").trim();
  const preset = BASEMAPS.find((b) => b.id === id)
    ?? BASEMAPS.find((b) => b.id === "osm")!;
  if (preset.id !== "custom") return preset;
  const url = (customUrl || "").trim();
  return url ? { ...preset, tiles: url, attribution: "custom" } : BASEMAPS.find((b) => b.id === "osm")!;
}

type GraticuleFeature = {
  type: "Feature";
  geometry: { type: "LineString"; coordinates: [number, number][] };
  properties: { major: boolean };
};

function graticule(step = 10): { type: "FeatureCollection"; features: GraticuleFeature[] } {
  const features: GraticuleFeature[] = [];
  for (let lon = -180; lon <= 180; lon += step) {
    features.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates: [[lon, -85], [lon, 85]] },
      properties: { major: lon === 0 || lon % 30 === 0 },
    });
  }
  for (let lat = -80; lat <= 80; lat += step) {
    features.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates: [[-180, lat], [180, lat]] },
      properties: { major: lat === 0 || lat % 30 === 0 },
    });
  }
  return { type: "FeatureCollection", features };
}

const GRATICULE = graticule();
const BG_DARK = "#0b1220";
const BG_LIGHT = "#eef2f7";

/** 生成底图 style：背景 + （离线经纬网 | 栅格瓦片）。调用方可在此基础上追加自己的 sources/layers。 */
export function basemapStyle(
  dark: boolean,
  source?: string | null,
  customUrl?: string | null,
): StyleSpecification {
  const preset = resolveBasemap(source, customUrl);
  if (preset.offline) {
    return {
      version: 8,
      sources: {
        graticule: { type: "geojson", data: GRATICULE as unknown as GeoJSON.FeatureCollection },
      },
      layers: [
        { id: "bg", type: "background", paint: { "background-color": dark ? BG_DARK : BG_LIGHT } },
        {
          id: "graticule", type: "line", source: "graticule",
          paint: {
            "line-color": dark ? "#1e293b" : "#cbd5e1",
            "line-width": ["case", ["get", "major"], 1, 0.5],
            "line-opacity": 0.9,
          },
        },
      ],
    };
  }
  return {
    version: 8,
    sources: {
      base: {
        type: "raster",
        tiles: [preset.tiles as string],
        tileSize: 256,
        attribution: preset.attribution,
        maxzoom: preset.maxzoom,
      },
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": dark ? BG_DARK : BG_LIGHT } },
      {
        id: "base", type: "raster", source: "base",
        paint: {
          "raster-opacity": dark ? 0.5 : 0.92,
          "raster-saturation": dark ? -0.75 : -0.25,
          "raster-brightness-min": dark ? 0.05 : 0,
          "raster-brightness-max": dark ? 0.55 : 1,
        },
      },
    ],
  };
}
