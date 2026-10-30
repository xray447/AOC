import type { OpsAircraftType, OpsSettlement, OpsStatus } from "./types";

export interface OpsStateMeta {
  state: OpsStatus["state"];
  zh: string;
  en: string;
  color: string;
  path: string;
}

/** 当前状态 → 文案、颜色与跳转目标（空闲 / 地面等待 / 飞行中）。 */
export function opsStateMeta(status: OpsStatus | null | undefined): OpsStateMeta {
  const state = status?.state ?? "IDLE";
  const path = opsStatePath(status);
  if (state === "FLIGHT") {
    return { state, zh: "飞行中", en: "In flight", color: "blue", path };
  }
  if (state === "GROUND") {
    return { state, zh: "地面等待", en: "On ground", color: "gold", path };
  }
  return { state, zh: "空闲", en: "Idle", color: "default", path };
}

/**
 * 顶部状态按钮的落点：按钮上既然显示着航班信息（呼号 / 起降），
 * 就应该直接进「配载与执行」；只有完全没有航班信息时才回「抽班」。
 */
function opsStatePath(status: OpsStatus | null | undefined): string {
  if (!status) return "/ops/roster";
  if (status.state === "FLIGHT") return "/ops/execute";
  if (status.state === "GROUND" && status.task_kind) return "/ops/execute";
  const hasFlight = Boolean(status.callsign || (status.dep_icao && status.arr_icao));
  return hasFlight ? "/ops/execute" : "/ops/roster";
}

export function money(value: number | null | undefined, currency = "USD"): string {
  const n = Number(value ?? 0);
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}${currency && currency !== "USD" ? ` ${currency}` : ""}`;
}

export function moneyShort(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toFixed(0);
}

export function fmtUtc(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

export function fmtUtcFull(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

export function fmtBlock(minutes: number | null | undefined): string {
  const total = Math.round(Number(minutes ?? 0));
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h ? `${h}h${m.toString().padStart(2, "0")}` : `${m}min`;
}

export function hoursFromMinutes(minutes: number | null | undefined): number {
  return Math.round((Number(minutes ?? 0) / 60) * 100) / 100;
}

export const aircraftStatus: Record<string, { zh: string; en: string; color: string }> = {
  ACTIVE: { zh: "可用", en: "Active", color: "green" },
  HELD: { zh: "已锁定", en: "Held", color: "gold" },
  IN_FLIGHT: { zh: "飞行中", en: "In flight", color: "blue" },
  MAINTENANCE: { zh: "维护", en: "Maintenance", color: "orange" },
  RETIRED: { zh: "退役", en: "Retired", color: "default" },
};

export const rosterStatus: Record<string, { zh: string; en: string; color: string }> = {
  LOCKED: { zh: "待开始", en: "Locked", color: "gold" },
  IN_PROGRESS: { zh: "执行中", en: "In progress", color: "blue" },
  COMPLETED: { zh: "已完成", en: "Completed", color: "green" },
  CANCELLED: { zh: "已取消", en: "Cancelled", color: "default" },
  EXPIRED: { zh: "已过期", en: "Expired", color: "red" },
};

export const legStatus: Record<string, { zh: string; en: string; color: string }> = {
  PLANNED: { zh: "计划", en: "Planned", color: "default" },
  IN_PROGRESS: { zh: "执行中", en: "In progress", color: "blue" },
  COMPLETED: { zh: "已完成", en: "Completed", color: "green" },
  CANCELLED: { zh: "已取消", en: "Cancelled", color: "default" },
};

export const settlementStatus: Record<string, { zh: string; en: string; color: string }> = {
  PENDING: { zh: "待结算", en: "Pending", color: "default" },
  HELD: { zh: "待复核", en: "Held", color: "orange" },
  SETTLED: { zh: "已结算", en: "Settled", color: "green" },
  VOID: { zh: "无效", en: "Void", color: "red" },
};

export const policyAction: Record<string, { zh: string; en: string; color: string }> = {
  ACCEPT: { zh: "正常结算", en: "Accept", color: "green" },
  WEIGHTED: { zh: "折算", en: "Weighted", color: "gold" },
  REVIEW: { zh: "复核", en: "Review", color: "orange" },
  REJECT: { zh: "拒绝", en: "Reject", color: "red" },
};

export const entryLabel: Record<string, { zh: string; en: string }> = {
  CAPITAL: { zh: "初始资金", en: "Capital" },
  REVENUE_PAX: { zh: "旅客收入", en: "Pax revenue" },
  REVENUE_PAX_BUSINESS: { zh: "商务舱收入", en: "Business revenue" },
  REVENUE_PAX_FIRST: { zh: "头等舱收入", en: "First revenue" },
  REVENUE_CARGO: { zh: "货物收入", en: "Cargo" },
  REVENUE_MAIL: { zh: "邮件收入", en: "Mail" },
  REVENUE_ANCILLARY: { zh: "附加服务", en: "Ancillary" },
  REVENUE_CHARTER: { zh: "包机费", en: "Charter" },
  REVENUE_INSURANCE: { zh: "保险赔付", en: "Insurance" },
  POLICY_ADJUSTMENT: { zh: "策略折算", en: "Policy adjustment" },
  REVENUE_ADJUSTMENT: { zh: "结算差额", en: "Adjustment" },
  ADVANCE_PAYOUT: { zh: "复核预付款", en: "Advance payout" },
  ADVANCE_CLAWBACK: { zh: "预付款回冲", en: "Advance clawback" },
  COST_FUEL: { zh: "燃油", en: "Fuel" },
  COST_LANDING: { zh: "起降费", en: "Landing" },
  COST_HANDLING: { zh: "地面服务", en: "Handling" },
  COST_CREW: { zh: "机组", en: "Crew" },
  COST_MAINTENANCE: { zh: "维护", en: "Maintenance" },
  COST_LEASE: { zh: "租赁/折旧", en: "Lease" },
  COST_PARKING: { zh: "停机", en: "Parking" },
  COST_ATC: { zh: "空管", en: "ATC" },
  COST_INSURANCE: { zh: "保险", en: "Insurance" },
  COST_REPAIR: { zh: "事故修理", en: "Repair" },
  PENALTY_CANCEL: { zh: "取消费", en: "Cancel fee" },
  PENALTY_NO_SHOW: { zh: "失约费", en: "No-show fee" },
  PENALTY_DIVERSION: { zh: "备降罚金", en: "Diversion" },
};

export const anomalyLabel: Record<string, { zh: string; en: string }> = {
  DATA_GAP: { zh: "数据缺口", en: "Data gap" },
  SIM_RATE: { zh: "时间加速", en: "Sim rate" },
  PAUSE: { zh: "暂停", en: "Pause" },
  TELEPORT: { zh: "瞬移", en: "Teleport" },
  FUEL_JUMP: { zh: "油量跳变", en: "Fuel jump" },
  TRACK_DISTANCE: { zh: "轨迹距离异常", en: "Track distance" },
  MISSING_TRACK: { zh: "轨迹缺失", en: "Missing track" },
  REVIEW: { zh: "复核", en: "Review" },
};

export function typeLabel(type: OpsAircraftType): string {
  const variant = type.variant && type.variant !== "STANDARD" ? ` ${type.variant}` : "";
  const role = type.role === "BIZJET" ? "公务机" : type.role === "VIP" ? "VIP" : "";
  return `${type.icao}${variant} · ${type.name || ""}${role ? `（${role}）` : ""}`;
}

/**
 * 结算一行的标题：列表接口平铺了呼号/起降，详情接口历史上只嵌套 `flight`，
 * 这里两处都兼容，缺字段时逐级退化（不再出现 `????`）。
 */
export function settlementTitle(row: OpsSettlement): string {
  const flight: Partial<OpsSettlement> = row.flight || {};
  const callsign = row.callsign || flight.callsign || "";
  const dep = row.dep_icao || flight.dep_icao || "";
  const arr = row.arr_icao || flight.arr_icao || "";
  const route = dep && arr ? `${dep}→${arr}` : (dep || arr);
  if (callsign && route) return `${callsign} ${route}`;
  if (route) return route;
  if (callsign) return callsign;
  return "未知航班";
}

