"""按可用时间推荐未飞机场（P-03 / A-01）。

候选生成 → 未飞判定 → 航时估算 → 评分 → Top N。
没有 navdata 时明确降级（无法计算距离），不编造机场。
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone

from aoc_navdata import NavData, haversine_nm
from aoc_protocol.schemas import RecommendCandidate, RecommendRequest, RecommendResponse

from .aircraft import AircraftCatalog

TAXI_CLIMB_DESCENT_MIN = 15.0


def _block_minutes(distance_nm: float, cruise_speed_kt: float) -> float:
    return distance_nm / max(80.0, cruise_speed_kt) * 60.0 + TAXI_CLIMB_DESCENT_MIN


def recommend(request: RecommendRequest, nav: NavData | None, visited_arrivals: set[str],
              visited_airports: set[str], aircraft: AircraftCatalog,
              home_airport: str | None = None) -> RecommendResponse:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    base = (request.base_icao or home_airport or "").upper()
    out = RecommendResponse(base_icao=base, generated_at=now)
    if nav is None:
        out.warnings = ["未提供 navdata，无法计算距离与筛选机场；请先在设置中导入 navdata"]
        return out
    base_info = nav.airport(base)
    if base_info is None:
        out.warnings = [f"出发机场 {base or '(空)'} 不在 navdata 中"]
        return out
    ac = aircraft.get(request.aircraft_type)
    speed = float(ac.get("cruise_speed_kt") or 440)
    available = float(request.available_minutes)
    target = max(0.0, (available - TAXI_CLIMB_DESCENT_MIN) / 60.0 * speed)
    if target <= 0:
        out.warnings = ["可用时间太短（至少 30 分钟）"]
        return out

    min_runway = request.min_runway_m or int(ac.get("min_runway_m") or 1200)
    max_range = min(float(ac.get("range_nm") or 3000) * 0.9, target * 1.5)
    if request.max_distance_nm:
        max_range = min(max_range, float(request.max_distance_nm))

    visited_countries = set()
    for icao in visited_airports:
        a = nav.airport(icao)
        if a and a.get("country"):
            visited_countries.add(a["country"])

    rng = random.Random(request.random_seed if request.random_seed is not None
                        else int(datetime.now().timestamp() // 60))
    candidates: list[RecommendCandidate] = []
    considered = 0
    for ident, info in nav.airports.items():
        if ident == base:
            continue
        dist = haversine_nm(base_info["lat"], base_info["lon"], info["lat"], info["lon"])
        if dist < 20 or dist > max_range:
            continue
        if request.only_never_visited and ident in visited_arrivals:
            continue
        block = _block_minutes(dist, speed)
        if not (available * 0.85 <= block <= available * 1.15):
            continue
        runways = nav.runways(ident)
        if not runways:
            continue
        lengths = [r.get("length_m") for r in runways if r.get("length_m")]
        longest = max(lengths) if lengths else None
        if longest is not None and longest < min_runway:
            continue
        considered += 1

        reasons: list[str] = []
        score = 0.45
        if ident not in visited_airports:
            reasons.append("从未到访")
            score += 0.2
        if request.prefer_new_country and info.get("country") and info["country"] not in visited_countries:
            reasons.append(f"新国家/地区：{info['country']}")
            score += 0.1
        closeness = 1.0 - abs(block - available) / max(available, 1.0)
        score += closeness * 0.2
        reasons.append(f"预计航时 {int(block // 60)}h{int(block % 60):02d}m，匹配 {int(available)} 分钟")
        if longest:
            reasons.append(f"最长跑道 {longest:.0f} m")
            if longest >= min_runway + 600:
                score += 0.05
        reasons.append(f"大圆距离 {dist:.0f} NM")
        score += rng.uniform(-0.03, 0.03)
        candidates.append(RecommendCandidate(
            icao=ident, iata=info.get("iata"), name=info.get("name"), city=info.get("city"),
            country=info.get("country"), lat=info["lat"], lon=info["lon"],
            distance_nm=round(dist, 1),
            block_minutes_min=int(math.floor(block * 0.9)),
            block_minutes_max=int(math.ceil(block * 1.1)),
            block_minutes=int(round(block)),
            longest_runway_m=round(longest, 0) if longest else None,
            visited=ident in visited_arrivals,
            reasons=reasons, score=round(min(1.0, score), 3),
        ))
    candidates.sort(key=lambda c: c.score, reverse=True)
    out.candidates = candidates[:request.limit]
    out.candidates_considered = considered
    if len(candidates) < max(5, request.limit):
        out.warnings.append(
            f"仅找到 {len(candidates)} 个满足条件的机场；可放宽时间/距离/跑道条件，或补充 navdata")
    return out
