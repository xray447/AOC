"""统计（P-09）：小时、距离、机场/国家、机型、月度、落地分布。"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from aoc_navdata import NavData
from aoc_protocol.schemas import MonthlyCount, StatsOut


def compute_stats(flights: list[dict[str, Any]], nav: NavData | None,
                  extra_airports: set[str] | None = None) -> StatsOut:
    out = StatsOut()
    out.flights = len(flights)
    airports: set[str] = set(extra_airports or ())
    countries: set[str] = set()
    types: Counter[str] = Counter()
    ratings: Counter[str] = Counter()
    monthly: dict[str, dict[str, float]] = defaultdict(lambda: {"flights": 0, "minutes": 0.0, "distance": 0.0})
    vs_values: list[float] = []
    max_g: float | None = None

    for f in flights:
        dep, arr = f.get("dep_icao"), f.get("arr_icao")
        if dep:
            airports.add(dep.upper())
        if arr:
            airports.add(arr.upper())
        minutes = f.get("block_minutes") or 0
        distance = f.get("distance_nm") or 0
        out.total_minutes += float(minutes)
        out.total_distance_nm += float(distance)
        if f.get("aircraft_type"):
            types[f["aircraft_type"].upper()] += 1
        if f.get("landing_rating"):
            ratings[f["landing_rating"]] += 1
        if f.get("touchdown_vs_fpm") is not None:
            vs_values.append(float(f["touchdown_vs_fpm"]))
        if f.get("max_g_flight") is not None:
            max_g = max(max_g or 0.0, float(f["max_g_flight"]))
        stamp = (f.get("block_off_utc") or f.get("created_at") or "")[:7]
        if stamp:
            monthly[stamp]["flights"] += 1
            monthly[stamp]["minutes"] += float(minutes)
            monthly[stamp]["distance"] += float(distance)

    if nav is not None:
        for icao in airports:
            info = nav.airport(icao)
            if info and info.get("country"):
                countries.add(info["country"])
    out.airports = len(airports)
    out.countries = len(countries)
    out.aircraft_types = len(types)
    out.avg_landing_vs_fpm = round(sum(vs_values) / len(vs_values), 1) if vs_values else None
    out.max_g_flight = round(max_g, 2) if max_g else None
    out.landing_ratings = dict(ratings)
    out.monthly = [MonthlyCount(month=k, flights=int(v["flights"]),
                                minutes=round(v["minutes"], 1), distance_nm=round(v["distance"], 1))
                   for k, v in sorted(monthly.items())]
    out.top_aircraft = [{"icao": k, "flights": v} for k, v in types.most_common(10)]
    out.distinct_airports = sorted(airports)
    return out
