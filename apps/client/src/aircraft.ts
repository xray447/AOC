import type { AircraftType } from "./types";

export interface AircraftCategory {
  id: string;
  zh: string;
  en: string;
}

/** 机型按四类归组：通航 / 支线 / 窄体 / 宽体（M2 公司机型模板沿用同一分组）。 */
export const AIRCRAFT_CATEGORIES: AircraftCategory[] = [
  { id: "ga", zh: "通航", en: "General aviation" },
  { id: "regional", zh: "支线", en: "Regional" },
  { id: "narrow", zh: "窄体", en: "Narrow-body" },
  { id: "wide", zh: "宽体", en: "Wide-body" },
];

/** 旧数据里的 category 别名（如 turboprop）归入最接近的组。 */
const ALIASES: Record<string, string> = { turboprop: "ga", bizjet: "ga", jet: "narrow" };

export function normalizeCategory(category?: string | null): string {
  const key = (category || "").trim().toLowerCase();
  return ALIASES[key] || key;
}

export interface AircraftOption {
  value: string;
  label: string;
}

export interface AircraftGroup {
  label: string;
  options: AircraftOption[];
}

/**
 * 生成 antd Select 的分组选项：四类在前，未知分类归入「其他」。
 * withName 为 true 时显示 `ICAO · 名称`，否则只显示 ICAO（用于较窄的列）。
 */
export function aircraftGroups(
  types: AircraftType[],
  tr: (zh: string, en: string) => string,
  { withName = false }: { withName?: boolean } = {},
): AircraftGroup[] {
  const groups = new Map<string, AircraftOption[]>();
  for (const t of types) {
    const key = normalizeCategory(t.category) || "other";
    const label = withName ? `${t.icao} · ${t.name}` : t.icao;
    const list = groups.get(key) ?? [];
    list.push({ value: t.icao, label });
    groups.set(key, list);
  }
  const out: AircraftGroup[] = [];
  for (const category of AIRCRAFT_CATEGORIES) {
    const options = groups.get(category.id);
    if (options?.length) {
      out.push({ label: tr(category.zh, category.en), options: options.sort((a, b) => a.value.localeCompare(b.value)) });
    }
    groups.delete(category.id);
  }
  const rest = [...groups.entries()].flatMap(([, options]) => options);
  if (rest.length) {
    out.push({ label: tr("其他", "Other"), options: rest.sort((a, b) => a.value.localeCompare(b.value)) });
  }
  return out;
}

/** 取机型所属分类的中英文名，用于标签展示。 */
export function categoryLabel(category: string | null | undefined, tr: (zh: string, en: string) => string): string {
  const key = normalizeCategory(category);
  const found = AIRCRAFT_CATEGORIES.find((c) => c.id === key);
  return found ? tr(found.zh, found.en) : tr("其他", "Other");
}
