"""预计停机位：航站楼/承运人归属与确定性选位（docs/12 §4）。

本模块只做纯计算（不碰数据库、不碰时间），输入来自：
- `aoc_navdata.NavData.stands()`（场景库 / 现实库 / 手工覆盖）；
- `OpsService` 里的 `airport_terminal` / `terminal_rule`（机场事实 + 承运人规则）。

口径（与文档一一对应）：
* §4.1 硬约束：用途池、尺寸、无效位、航站楼归属；
* §4.2 选位：满足硬约束后**随机**（不再打分；联机模式的占用校验见 §4.4，暂未实作）；
* §4.5 判定顺序：国内国际 → 承运人集合 → 命中规则 → 未命中排他已声明 → 空则回退。
"""
from __future__ import annotations

import json
import random
from collections.abc import Iterable
from typing import Any

from aoc_navdata import haversine_nm
from aoc_navdata.navdata import GLOBAL_STAND_PREFIXES, STAND_RADIUS_FACTOR


def strip_global_prefix(text: str | None) -> str:
    """去掉 `G`/`P` 这类全局类别前缀（只在后面紧跟数字时），便于按编号比较。"""
    value = str(text or "").strip().upper()
    if len(value) > 1 and value[0] in GLOBAL_STAND_PREFIXES and value[1].isdigit():
        return value[1:]
    return value

# §4.1 用途池：(首选, 不足时的退让池)。RGA* = Ramp GA，RC/RMC/RMCB = 货/军用货
PAX_TYPES = ("GS", "GM", "GH", "GE")
CARGO_TYPES = ("RC", "RMC", "RMCB")
BIZJET_TYPES = ("RGAS", "RGAM", "RGAL", "DGA", "GS")
# 永远不选的类型：加油位、车辆位、未知
INVALID_TYPES = ("FUEL", "UNKN", "VEHICLE", "UNKNOWN", "")

SCOPES = ("DOMESTIC", "INTERNATIONAL", "BOTH")
MATCHER_TYPES = ("number_range", "area_prefix", "radius", "explicit")


def role_pool(role: str | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """机型用途 → (首选机位类型, 退让池)。"""
    key = (role or "AIRLINER").strip().upper()
    if key == "CARGO":
        return CARGO_TYPES, ("GH", "RGAL")
    if key in ("BIZJET", "VIP"):
        return BIZJET_TYPES, ("GM", "GH")
    # AIRLINER / COMBI / 未知一律按客机处理（保守）
    return PAX_TYPES, ("RGAL",)


def is_cargo(role: str | None) -> bool:
    return (role or "").strip().upper() == "CARGO"


def stand_fits_size(stand: dict, wingspan_m: float | None) -> bool | None:
    """尺寸硬约束。返回 None = 没有尺寸数据（不做判断，标 size_unknown）。"""
    radius = stand.get("radius_m")
    if radius is None or not wingspan_m:
        return None
    return float(radius) * STAND_RADIUS_FACTOR >= float(wingspan_m)


def filter_candidates(stands: Iterable[dict], *, role: str | None,
                      wingspan_m: float | None, size_filter: bool = True,
                      military: bool = False) -> tuple[list[dict], list[str]]:
    """§4.1 的硬约束：用途池 + 尺寸 + 无效位 + 军用互斥。"""
    primary, fallback = role_pool(role)
    warnings: list[str] = []
    pool = set(primary)
    usable: list[dict] = []
    for stand in stands:
        kind = (stand.get("type") or "").strip().upper()
        if kind in INVALID_TYPES:
            continue
        if military and kind in ("RMC", "RMCB"):
            # 军用货位不进民用机场的候选
            continue
        if not military and kind in ("RMC", "RMCB") and not is_cargo(role):
            continue
        if kind in pool:
            usable.append(stand)
    if not usable:
        warnings.append("主要机位类型不足，已放宽到备选类型")
        pool = set(primary) | set(fallback)
        for stand in stands:
            kind = (stand.get("type") or "").strip().upper()
            if kind in INVALID_TYPES or kind not in pool:
                continue
            usable.append(stand)
    if not usable:
        # 现实 navdata 只有编号（type/radius 为空）：Q-5 的口径是「照常显示编号、标无尺寸数据」，
        # 所以这里跳过用途池，别把整座机场判成「没有停机位」。
        unknown = [s for s in stands if not str(s.get("type") or "").strip()]
        if unknown:
            warnings.append("该数据源只有机位编号（无类型/尺寸），已跳过类型筛选")
            return [{**s, "size_unknown": True} for s in unknown], warnings
        return [], warnings
    if not size_filter:
        return usable, warnings
    sized: list[dict] = []
    for stand in usable:
        fits = stand_fits_size(stand, wingspan_m)
        if fits is False:
            continue
        sized.append({**stand, "size_unknown": fits is None})
    if not sized:
        warnings.append("按翼展筛不出可用机位，已放宽尺寸限制")
        return [{**s, "size_unknown": stand_fits_size(s, wingspan_m) is None} for s in usable], warnings
    return sized, warnings


def jetway_preferred(stands: list[dict], role: str | None) -> list[dict]:
    """客机有廊桥位时只用廊桥位（§4.1 用途）；货机不做此过滤。"""
    if is_cargo(role):
        return stands
    with_jetway = [s for s in stands if s.get("has_jetway")]
    return with_jetway or stands


# ---------------------------------------------------------------- 航站楼 ----
def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def matcher_hits(stand: dict, matcher: dict) -> bool:
    """单个 matcher 是否命中该机位；无法解析的 matcher 视为不命中。"""
    if not isinstance(matcher, dict):
        return False
    kind = str(matcher.get("type") or "").strip().lower()
    if kind == "number_range":
        number = stand.get("number")
        if number is None:
            return False
        for item in matcher.get("ranges") or []:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            low, high = _as_float(item[0]), _as_float(item[1])
            if low is None or high is None:
                continue
            if low <= float(number) <= high:
                return True
        return False
    if kind == "area_prefix":
        name = str(stand.get("name") or "").strip().upper()
        prefixes = [str(p).strip().upper() for p in (matcher.get("prefixes") or []) if str(p).strip()]
        return bool(name) and any(name.startswith(p) for p in prefixes)
    if kind == "radius":
        lat, lon = _as_float(matcher.get("lat")), _as_float(matcher.get("lon"))
        r_m = _as_float(matcher.get("r_m"))
        if lat is None or lon is None or r_m is None:
            return False
        if stand.get("lat") is None or stand.get("lon") is None:
            return False
        return haversine_nm(lat, lon, float(stand["lat"]), float(stand["lon"])) * 1852.0 <= r_m
    if kind == "explicit":
        # 老配置里可能还写着 `G601`，编号里已不含全局前缀 → 两边都归一后再比
        idents = {strip_global_prefix(i) for i in (matcher.get("idents") or []) if str(i).strip()}
        return strip_global_prefix(stand.get("ident")) in idents
    return False


def terminal_match(stands: list[dict], matchers: Any) -> list[dict]:
    """一台航站楼圈定的机位（多个 matcher 之间是「或」）。"""
    items = matchers
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except json.JSONDecodeError:
            items = []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or not items:
        return []
    return [s for s in stands
            if any(matcher_hits(s, m) for m in items if isinstance(m, dict))]


def terminal_of_stand(stand: dict, terminals: list[dict]) -> str | None:
    """该机位落在哪个已声明的航站楼（先声明的赢，保证确定性）。"""
    ident = str(stand.get("ident") or "").upper()
    for terminal in terminals:
        idents: dict[str, dict] = terminal.get("_stands_by_ident") or {}
        if ident in idents:
            return str(terminal.get("terminal") or "")
    return None


def resolve_terminal(terminals: list[dict], rules: list[dict], *, carriers: Iterable[str],
                     scope: str) -> dict:
    """§4.5 判定顺序 3–5：命中哪台航站楼、哪些已被别的承运人声明。

    返回 `{"terminal": str|None, "source": "rule"|"none", "claimed": set[str]}`。
    """
    names = {str(t.get("terminal") or "").upper() for t in terminals}
    carrier_set = {str(c).strip().upper() for c in carriers if str(c).strip()}
    active = [r for r in rules if r.get("enabled", True) and str(r.get("terminal") or "").upper() in names]
    claimed = {str(r["terminal"]).upper() for r in active
               if [a for a in (r.get("airlines") or []) if str(a).strip()]}
    hits: list[dict] = []
    for rule in active:
        rule_scope = str(rule.get("scope") or "BOTH").upper()
        if rule_scope not in ("BOTH", scope):
            continue
        airlines = {str(a).strip().upper() for a in (rule.get("airlines") or []) if str(a).strip()}
        if airlines and not (airlines & carrier_set):
            continue
        hits.append(rule)
    if not hits:
        return {"terminal": None, "source": "none", "claimed": claimed}
    hits.sort(key=lambda r: (-int(r.get("priority") or 0),
                             0 if str(r.get("scope") or "BOTH").upper() == scope else 1,
                             str(r.get("terminal") or "")))
    return {"terminal": str(hits[0]["terminal"]).upper(), "source": "rule", "claimed": claimed}


def apply_terminal(stands: list[dict], terminals: list[dict], *, carriers: Iterable[str],
                   scope: str, rules: list[dict]) -> tuple[list[dict], dict]:
    """把机位按航站楼规则过滤。返回 (候选, 判定信息)，判定信息进 `score_json`/界面提示。"""
    if not terminals:
        return stands, {"terminal": None, "terminal_source": "none", "claimed": [],
                        "warnings": []}
    prepared: list[dict] = []
    for terminal in terminals:
        rows = terminal_match(stands, terminal.get("matchers"))
        prepared.append({**terminal, "_stands_by_ident": {str(r["ident"]).upper(): r for r in rows}})
    decision = resolve_terminal(prepared, rules, carriers=carriers, scope=scope)
    info: dict[str, Any] = {
        "terminal": decision["terminal"], "terminal_source": decision["source"],
        "scope": scope, "carriers": sorted({str(c).strip().upper() for c in carriers if str(c).strip()}),
        "claimed": sorted(decision["claimed"]), "warnings": [],
    }
    if decision["terminal"]:
        chosen = prepared[[str(t["terminal"]).upper() for t in prepared].index(decision["terminal"])]
        pool = list((chosen.get("_stands_by_ident") or {}).values())
        if pool:
            return pool, info
        info["warnings"].append("承运人规则命中的航站楼没有可用机位，已忽略航站楼限制")
        return stands, info
    # 没有任何规则命中：只用「未被任何承运人声明」的机位（§4.5 第 4 条）
    if decision["claimed"]:
        pool = [s for s in stands if terminal_of_stand(s, prepared) not in decision["claimed"]]
        if pool:
            return pool, info
        info["warnings"].append("未声明的机位为空，已忽略航站楼限制")
    return stands, info


# ------------------------------------------------------------------ 选位 ----
# 满足硬约束后等概率随机（§4.2 拍板：不再打分）。联机模式要在此基础上再排掉「被占用」
# 的机位（§4.4），占用的判定留给 P3，这里只保留本地随机。
_RNG = random.SystemRandom()


def pick_for_flight(stands: list[dict], *, wingspan_m: float | None,
                    role: str | None, size_filter: bool = True, military: bool = False,
                    terminals: list[dict] | None = None, rules: list[dict] | None = None,
                    carriers: Iterable[str] = (), scope: str = "DOMESTIC") -> dict:
    """完整选位：硬约束 → 廊桥 → 航站楼 → 剩下的候选里随机挑一个。"""
    warnings: list[str] = []
    candidates, pool_warnings = filter_candidates(
        stands, role=role, wingspan_m=wingspan_m, size_filter=size_filter, military=military)
    warnings.extend(pool_warnings)
    if not candidates:
        return {"stand": None, "candidates": 0, "warnings": warnings, "terminal": None}
    preferred = jetway_preferred(candidates, role)
    if len(preferred) < len(candidates):
        warnings.append("已优先使用带廊桥的机位")
    terminal_info: dict[str, Any] = {"terminal": None, "terminal_source": "none", "warnings": []}
    if terminals:
        preferred, terminal_info = apply_terminal(
            preferred, terminals, carriers=carriers, scope=scope, rules=rules or [])
        warnings.extend(terminal_info.get("warnings") or [])
    if not preferred:
        return {"stand": None, "candidates": 0, "warnings": warnings,
                "terminal": terminal_info.get("terminal")}
    chosen = {**_RNG.choice(preferred),
              # 保留 `score`/`score_breakdown` 字段（落库 schema 与前端类型没变），
              # 值改成「随机」标记，方便复盘时区分于旧的打分明细
              "score": None,
              "score_breakdown": {"random": True, "candidates": len(preferred)}}
    chosen["terminal"] = terminal_info.get("terminal")
    chosen["terminal_source"] = terminal_info.get("terminal_source") or "none"
    chosen["terminal_scope"] = terminal_info.get("scope")
    return {"stand": chosen, "candidates": len(preferred),
            "warnings": warnings, "terminal": terminal_info.get("terminal")}


def eta_refined(remaining_nm: float, gs_kt: float | None, *, detour: float = 1.0,
                phase: str | None = None) -> tuple[float, str]:
    """§5.2 三档分段 ETA（只用现成数据）：返回 (分钟, 置信度)。

    巡航段用当前地速；20–60 NM 起按 250 kt 折算最后 20 NM；<20 NM 按 180 kt + 3 min
    进近时间。`detour` 是航路绕行系数（route / great-circle，1.0–1.3 才用）。
    """
    rem = max(0.0, float(remaining_nm))
    gs = float(gs_kt) if gs_kt and gs_kt > 0 else None
    if rem <= 20.0:
        ete = rem / 180.0 * 60.0 + 3.0
        confidence = "high"
    elif rem <= 60.0:
        ete = (max(0.0, rem - 20.0) / (gs or 250.0)) * 60.0 + 20.0 / 250.0 * 60.0
        confidence = "medium"
    else:
        ete = (rem / (gs or 420.0)) * 60.0
        confidence = "low"
    if gs is None:
        confidence = "low"
    factor = float(detour) if 1.0 <= float(detour) <= 1.3 else 1.0
    ete *= factor
    phase_key = (phase or "").upper()
    if phase_key in ("APPROACH", "LANDING"):
        confidence = "high"
    elif phase_key == "DESCENT" and confidence == "low":
        confidence = "medium"
    return round(ete, 1), confidence


def eta_confidence_label(confidence: str | None) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(str(confidence or "").lower(), "低")

