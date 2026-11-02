"""落地评估（P-06）：最大 G、接地 VS、接地点、跑道、弹跳、滑跑距离、评级。

数据来源优先级：SimConnect `PLANE TOUCHDOWN *`（若 SimLink 提供）→ on-ground 首帧 + VS/G
帧级采样。个人模式只记录、不惩罚。
"""
from __future__ import annotations

from typing import Any

from aoc_navdata import NavData, haversine_nm

DEFAULT_THRESHOLDS = {
    "vs_great": -100.0,
    "vs_good": -300.0,
    "vs_hard": -600.0,
    "g_great": 1.5,
    "g_good": 1.8,
    "g_hard": 2.2,
}
RATING_ORDER = ["GREAT", "GOOD", "HARD", "SEVERE"]
# 起飞门槛（§33）：首点在空中且「持续 ≥60s 或爬升 ≥500ft」才算起飞
FAKE_AIRBORNE_MIN_S = 60.0
FAKE_CLIMB_MIN_FT = 500.0


def _t(p: dict) -> float:
    return float(p.get("t", 0.0) or 0.0)


def _on_ground(p: dict) -> bool:
    return bool(p.get("on_ground"))


def _g(p: dict) -> float:
    return float(p.get("g") or p.get("g_force") or 0.0)


def _vs(p: dict) -> float:
    return float(p.get("vs_fpm") or 0.0)


def _gs(p: dict) -> float:
    return float(p.get("gs_kt") or 0.0)


def _rating(vs: float | None, g: float | None, thresholds: dict) -> str:
    vs_bad = 0
    if vs is not None:
        vs_abs = abs(vs)
        if vs_abs > abs(thresholds.get("vs_hard", -600)):
            vs_bad = 3
        elif vs_abs > abs(thresholds.get("vs_good", -300)):
            vs_bad = 2
        elif vs_abs > abs(thresholds.get("vs_great", -100)):
            vs_bad = 1
    g_bad = 0
    if g is not None:
        if g > thresholds.get("g_hard", 2.2):
            g_bad = 3
        elif g > thresholds.get("g_good", 1.8):
            g_bad = 2
        elif g > thresholds.get("g_great", 1.5):
            g_bad = 1
    return RATING_ORDER[max(vs_bad, g_bad)]


def _nearest_airport(nav: NavData | None, lat: float | None, lon: float | None,
                     max_nm: float = 15.0) -> str | None:
    if nav is None or lat is None or lon is None:
        return None
    airport, _ = nav.nearest_airport(lat, lon, max_nm)
    return airport["ident"] if airport else None


def _sustained_airborne(points: list[dict], start: int) -> bool:
    """首点在空中是否「真的起飞了」（§33 第 4 道闸）。

    V-1 实测幽灵帧只持续 **≈1.9s**、AGL 233ft；真起飞会持续 ≥60s 或爬升 ≥500ft。
    """
    t0 = _t(points[start])
    alt0 = float(points[start].get("alt_ft") or 0.0)
    peak, end = alt0, t0
    for p in points[start:]:
        if _on_ground(p):
            break
        end, peak = _t(p), max(peak, float(p.get("alt_ft") or 0.0))
    return (end - t0) >= FAKE_AIRBORNE_MIN_S or (peak - alt0) >= FAKE_CLIMB_MIN_FT


def evaluate(points: list[dict], nav: NavData | None = None,
             thresholds: dict | None = None, aircraft: str | None = None,
             partial: bool = False, _allow_trim: bool = True,
             fuel_start_kg: float | None = None) -> dict[str, Any]:
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    out: dict[str, Any] = {
        "takeoff_index": None, "landing_index": None,
        "dep_icao": None, "arr_icao": None,
        "distance_nm": 0.0, "data_gap_seconds": 0.0,
        "landing": {}, "events": [],
    }
    if not points:
        return out
    points = sorted(points, key=_t)
    # §33 / V-1：开头若是幽灵/加载期空中帧（首点在空中、且不满足「真起飞」门槛），
    # 先丢掉首个地面点之前的部分再评估，否则里程会把 (0, 90) → 机场的那一跳算进去
    if _allow_trim and not partial and not _on_ground(points[0]) \
            and not _sustained_airborne(points, 0):
        first_ground = next((i for i, p in enumerate(points) if _on_ground(p)), None)
        if first_ground is not None and 0 < first_ground < len(points) - 1:
            trimmed = evaluate(points[first_ground:], nav, thresholds, aircraft,
                               partial=partial, _allow_trim=False,
                               fuel_start_kg=fuel_start_kg)
            if trimmed.get("takeoff_index") is not None:
                return trimmed
    out["distance_nm"] = round(sum(
        haversine_nm(float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"]))
        for a, b in zip(points, points[1:])), 1)
    out["data_gap_seconds"] = round(sum(
        max(0.0, _t(b) - _t(a) - 5.0) for a, b in zip(points, points[1:])), 1)

    # 起飞：第一次从地面变为空中
    takeoff = None
    for i in range(1, len(points)):
        if _on_ground(points[i - 1]) and not _on_ground(points[i]):
            takeoff = i
            break
    if takeoff is None and not _on_ground(points[0]):
        # 首点就在空中：空中接入（D-2 partial）或截断后仍无起飞（纯落地段）都按 0 记
        takeoff = 0
    out["takeoff_index"] = takeoff

    landing = None
    if takeoff is not None:
        for i in range(takeoff + 1, len(points)):
            if _on_ground(points[i]):
                # 需要前一点仍在空中，避免滑行阶段误判
                landing = i
                break
    out["landing_index"] = landing

    # 机场
    if takeoff is not None:
        out["dep_icao"] = _nearest_airport(nav, points[max(0, takeoff - 1)].get("lat"),
                                           points[max(0, takeoff - 1)].get("lon"))
    last = points[-1]
    if landing is not None:
        td = points[landing]
        out["arr_icao"] = _nearest_airport(nav, td.get("lat"), td.get("lon"))
    elif out["dep_icao"] is None:
        out["arr_icao"] = _nearest_airport(nav, last.get("lat"), last.get("lon"))

    metrics: dict[str, Any] = {}
    if landing is not None:
        td = points[landing]
        td_t = _t(td)
        window = [p for p in points if td_t - 10.0 <= _t(p) <= td_t + 5.0]
        max_g_landing = max((_g(p) for p in window), default=None)
        max_g_flight = max((_g(p) for p in points if 0.1 < _g(p) < 5.0), default=None)
        touchdown_g = _g(td)
        touchdown_vs = td.get("touchdown_vs_fpm")
        if touchdown_vs is None:
            touchdown_vs = _vs(td)

        runway = None
        if nav is not None and td.get("lat") is not None:
            runway = nav.find_runway(float(td["lat"]), float(td["lon"]),
                                     float(td.get("hdg_true", td.get("hdg_deg", 0.0)) or 0.0))
        bounce = 0
        for i in range(landing + 1, len(points)):
            if _t(points[i]) - td_t > 60:
                break
            if _on_ground(points[i - 1]) and not _on_ground(points[i]):
                bounce += 1
        landing_distance = None
        for i in range(landing, len(points)):
            if _on_ground(points[i]) and _gs(points[i]) < 5.0:
                landing_distance = sum(
                    haversine_nm(float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"]))
                    for a, b in zip(points[landing:i + 1], points[landing + 1:i + 2])) * 1852
                break

        # 着陆入口 = 物理入口 + 内移（displaced threshold）；距入口距离从着陆入口起算
        displaced = float(runway.get("displaced_threshold_m") or 0.0) if runway else 0.0
        metrics = {
            "touchdown_vs_fpm": round(float(touchdown_vs), 1) if touchdown_vs is not None else None,
            "touchdown_g": round(touchdown_g, 2) if touchdown_g else None,
            "max_g_landing": round(max_g_landing, 2) if max_g_landing else None,
            "max_g_flight": round(max_g_flight, 2) if max_g_flight else None,
            "touchdown_lat": float(td["lat"]),
            "touchdown_lon": float(td["lon"]),
            "runway_ident": runway["ident"] if runway else None,
            "runway_airport": runway["airport"] if runway else None,
            # §36：长度/来源跟着实际用的数据源（scenery = 游戏内，navdata = 现实库）
            "runway_length_m": runway.get("length_m") if runway else None,
            "runway_source": runway.get("runway_source") if runway else None,
            "threshold_distance_m": round(runway["along_m"] - displaced, 1) if runway else None,
            "displaced_threshold_m": round(displaced, 1) if runway else None,
            "centerline_offset_m": runway["lateral_m"] if runway else None,
            "bounce_count": bounce,
            "landing_distance_m": round(landing_distance, 0) if landing_distance else None,
            "landing_rating": _rating(
                float(touchdown_vs) if touchdown_vs is not None else None,
                max_g_landing or touchdown_g, thresholds),
        }
        if runway:
            out["arr_icao"] = runway["airport"]
        if metrics["landing_rating"] == "SEVERE":
            out["events"].append({"type": "hard_landing", "payload": metrics})
    else:
        metrics = {
            "max_g_flight": round(max((_g(p) for p in points if 0.1 < _g(p) < 5.0), default=0.0), 2) or None,
            "landing_rating": "UNKNOWN",
        }
    out["landing"] = metrics
    out["max_g_flight"] = metrics.get("max_g_flight")
    # §32：起始油量优先取推出定稿值（缺失时回落首帧，demo/replay 源走这条）
    out["fuel_start_kg"] = fuel_start_kg if fuel_start_kg is not None else points[0].get("fuel_kg")
    out["fuel_end_kg"] = points[-1].get("fuel_kg")
    out["block_off_t"] = _t(points[0])
    out["block_on_t"] = _t(points[-1])
    out["takeoff_t"] = _t(points[takeoff]) if takeoff is not None else None
    out["landing_t"] = _t(points[landing]) if landing is not None else None
    return out


def rating_thresholds(settings: dict | None = None) -> dict:
    custom = (settings or {}).get("landing_thresholds") or {}
    return {**DEFAULT_THRESHOLDS, **custom}
