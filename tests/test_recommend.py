from __future__ import annotations

from pathlib import Path

from aoc_core.aircraft import AircraftCatalog
from aoc_core.recommend import recommend
from aoc_protocol.schemas import RecommendRequest

ROOT = Path(__file__).resolve().parents[1]


def test_aircraft_categories():
    catalog = AircraftCatalog(ROOT / "data" / "aircraft_types.json")
    items = catalog.list()
    cats = {item["category"] for item in items}
    assert {"ga", "regional", "narrow", "wide"} <= cats
    assert all(item["category"] in {"ga", "regional", "narrow", "wide"} for item in items)
    assert len({item["icao"] for item in items}) == len(items)
    # 未知机型回退 A320，而不是目录第一条（通航）
    assert catalog.get("ZZZZ")["icao"] == "A320"


def test_a01_ninety_minutes(nav):
    result = recommend(RecommendRequest(available_minutes=90, base_icao="ZBAA"),
                       nav, set(), set(), AircraftCatalog())
    assert result.base_icao == "ZBAA"
    assert len(result.candidates) >= 5
    for c in result.candidates:
        assert 75 <= c.block_minutes <= 105
        assert c.visited is False
        assert c.reasons
        assert c.distance_nm > 0
    # 时间越接近 90 分钟分数应更高（至少候选里包含明显合理的机场）
    assert any(c.icao in {"ZHHH", "ZSNJ", "ZLXY", "ZSPD", "ZSSS", "ZSHC"} for c in result.candidates)


def test_visited_airport_excluded(nav):
    result = recommend(RecommendRequest(available_minutes=90, base_icao="ZBAA"),
                       nav, {"ZHHH"}, set(), AircraftCatalog())
    assert all(c.icao != "ZHHH" for c in result.candidates)
    assert result.candidates


def test_no_navdata_degrades():
    result = recommend(RecommendRequest(available_minutes=90, base_icao="ZBAA"),
                       None, set(), set(), AircraftCatalog())
    assert result.candidates == []
    assert result.warnings


def test_new_country_preference(nav):
    result = recommend(RecommendRequest(available_minutes=90, base_icao="ZBAA",
                                        prefer_new_country=True),
                       nav, set(), set(), AircraftCatalog())
    assert any(any("新国家" in r for r in c.reasons) for c in result.candidates)
