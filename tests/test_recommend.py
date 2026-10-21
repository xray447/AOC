from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from aoc_core.aircraft import AircraftCatalog
from aoc_core.recommend import recommend
from aoc_navdata import NavData
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


def _short_runway_db(path: Path, stored_length: float) -> Path:
    """一条 1200 m 跑道，两端沿经线相距 1200 m；stored_length 模拟不同来源的存储单位。"""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE airport(
            airport_id INTEGER PRIMARY KEY, ident TEXT, laty REAL, lonx REAL,
            longest_runway_length REAL);
        CREATE TABLE runway(
            runway_id INTEGER PRIMARY KEY, airport_id INTEGER, primary_end_id INTEGER,
            secondary_end_id INTEGER, length REAL);
        CREATE TABLE runway_end(
            runway_end_id INTEGER PRIMARY KEY, name TEXT, heading REAL, laty REAL,
            lonx REAL, altitude REAL);
        """
    )
    lat1, lon = 35.5, 134.78
    lat2 = lat1 + 1200.0 / 111320.0
    con.execute("insert into airport values(1,'RJBT',35.51,134.78,?)", (stored_length,))
    con.execute("insert into runway values(1,1,11,12,?)", (stored_length,))
    con.execute("insert into runway_end values(11,'01',3.0,?,?,580)", (lat1, lon))
    con.execute("insert into runway_end values(12,'19',183.0,?,?,580)", (lat2, lon))
    con.commit()
    con.close()
    return path


@pytest.mark.parametrize("stored_length", [3937.0, 1200.0])
def test_short_runway_length_unit(tmp_path: Path, stored_length: float):
    # RJBT 真实 1200 m：Little Navmap 存英尺 3937，不能被当成 3937 m
    data = NavData(_short_runway_db(tmp_path / "navdata.sqlite", stored_length))
    try:
        assert data.runways("RJBT")[0]["length_m"] == pytest.approx(1200, abs=30)
        assert data.airport("RJBT")["longest_runway_m"] == pytest.approx(1200, abs=30)
        assert data.airport("RJBT")["longest_runway_ft"] == pytest.approx(3937, abs=100)
    finally:
        data.close()


def test_new_country_preference(nav):
    result = recommend(RecommendRequest(available_minutes=90, base_icao="ZBAA",
                                        prefer_new_country=True),
                       nav, set(), set(), AircraftCatalog())
    assert any(any("新国家" in r for r in c.reasons) for c in result.candidates)
