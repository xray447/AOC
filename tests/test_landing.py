from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pytest
from aoc_navdata import NavData
from aoc_core.landing import evaluate

from .conftest import make_points


def test_landing_metrics(nav):
    result = evaluate(make_points(), nav)
    landing = result["landing"]
    assert result["takeoff_index"] == 20
    assert result["landing_index"] == 100
    assert result["dep_icao"] == "ZBAA"
    assert result["arr_icao"] == "ZSSS"
    assert landing["touchdown_vs_fpm"] == -150.0
    assert landing["touchdown_g"] == 1.3
    assert landing["runway_ident"] == "18"
    assert landing["runway_airport"] == "ZSSS"
    assert landing["threshold_distance_m"] is not None
    assert abs(landing["centerline_offset_m"]) < 1.0
    assert landing["landing_rating"] in ("GREAT", "GOOD")
    assert landing["bounce_count"] == 0


def test_no_landing_is_aborted(nav):
    result = evaluate(make_points(takeoff=10, landing=999, total=60), nav)
    assert result["landing_index"] is None
    assert result["landing"]["landing_rating"] == "UNKNOWN"


# --------------------------------------------------------------------------
# §33：幽灵飞机/瞬移（首点是假空中帧）
# --------------------------------------------------------------------------
def _with_ghost_prefix(points: list[dict], seconds: float = 2.0) -> list[dict]:
    """在真实轨迹前插几帧 (0, 90) 的空中幽灵帧（V-1 实测形态）。"""
    ghost = [{
        "t": float(i), "lat": 0.0, "lon": 90.0, "alt_ft": 233.0, "agl_ft": 216.0,
        "gs_kt": 0.0, "vs_fpm": 0.0, "hdg_true": 0.0, "on_ground": False,
        "fuel_kg": 8000.0, "g": 1.0,
    } for i in range(int(seconds) + 1)]
    shifted = [{**p, "t": p["t"] + seconds} for p in points]
    return ghost + shifted


def test_ghost_airborne_prefix_is_trimmed(nav):
    """幽灵空中帧不算起飞：丢掉后从真实地面段重新评估（假起降不再把记录判成完成）。"""
    points = _with_ghost_prefix(make_points())
    result = evaluate(points, nav)
    assert result["takeoff_index"] is not None
    assert result["landing_index"] is not None
    assert result["dep_icao"] == "ZBAA"
    # 里程不该把 (0, 90) → ZBAA 的那一跳算进去
    assert result["distance_nm"] < 700


def test_long_airborne_first_point_still_counts_as_takeoff(nav):
    """真·空中接入（首点在空中且持续够久）仍按首点起飞处理，不丢整段轨迹。"""
    points = make_points(takeoff=0)
    result = evaluate(points, nav)
    assert result["takeoff_index"] == 0
    assert result["landing_index"] is not None


# --------------------------------------------------------------------------
# 跑道内移入口（displaced threshold）
# --------------------------------------------------------------------------
KJFK_LAT, KJFK_LON = 40.6413, -73.7781
# 31L 物理入口、真航向 314°、物理长度 4425 m（14511 ft）
RWY_LAT, RWY_LON = 40.6395, -73.7860
RWY_HDG = 314.0
RWY_LENGTH_FT = 14511.0
OFFSET_FT = 3280.84  # ≈1000 m


def _point_along(dist_m: float) -> tuple[float, float]:
    """从物理入口沿 31L 方向前进 dist_m。"""
    th = math.radians(RWY_HDG)
    dlat = dist_m * math.cos(th) / 111320.0
    dlon = dist_m * math.sin(th) / (111320.0 * math.cos(math.radians(RWY_LAT)))
    return RWY_LAT + dlat, RWY_LON + dlon


def build_kjfk(path: Path, with_offset: bool = True) -> Path:
    con = sqlite3.connect(path)
    offset_col = ", offset_threshold REAL" if with_offset else ""
    con.executescript(
        f"""
        CREATE TABLE airport(
            airport_id INTEGER PRIMARY KEY, ident TEXT, name TEXT, iata TEXT, city TEXT,
            country TEXT, laty REAL, lonx REAL, altitude REAL, transition_altitude REAL,
            longest_runway_length REAL);
        CREATE TABLE runway(
            runway_id INTEGER PRIMARY KEY, airport_id INTEGER, primary_end_id INTEGER,
            secondary_end_id INTEGER, length REAL, has_ils INTEGER);
        CREATE TABLE runway_end(
            runway_end_id INTEGER PRIMARY KEY, name TEXT, heading REAL, laty REAL,
            lonx REAL, altitude REAL{offset_col});
        """
    )
    con.execute("insert into airport values(1,'KJFK','John F Kennedy','JFK','New York','US',?,?,13,18000,?)",
                (KJFK_LAT, KJFK_LON, RWY_LENGTH_FT))
    con.execute("insert into runway values(1,1,1,2,?,1)", (RWY_LENGTH_FT,))
    if with_offset:
        con.execute("insert into runway_end values(1,'31L',?,?,?,13,?)",
                    (RWY_HDG, RWY_LAT, RWY_LON, OFFSET_FT))
        other_lat, other_lon = _point_along(4425.0)
        con.execute("insert into runway_end values(2,'13R',?,?,?,13,0)",
                    ((RWY_HDG + 180) % 360, other_lat, other_lon))
    else:
        con.execute("insert into runway_end values(1,'31L',?,?,?,13)", (RWY_HDG, RWY_LAT, RWY_LON))
        other_lat, other_lon = _point_along(4425.0)
        con.execute("insert into runway_end values(2,'13R',?,?,?,13)",
                    ((RWY_HDG + 180) % 360, other_lat, other_lon))
    con.commit()
    con.close()
    return path


def make_landing_points(td_lat: float, td_lon: float, step_back_m: float = 60.0) -> list[dict]:
    """最后 3 帧在下滑（AGL 10ft），随后接地并在跑道上减速。"""
    th = math.radians(RWY_HDG)
    points: list[dict] = []
    for i in range(3):
        along = -step_back_m * (3 - i)
        lat = td_lat + along * math.cos(th) / 111320.0
        lon = td_lon + along * math.sin(th) / (111320.0 * math.cos(math.radians(td_lat)))
        points.append({
            "t": float(i), "lat": lat, "lon": lon, "alt_ft": 23.0 + i * 3, "agl_ft": 10.0,
            "gs_kt": 140.0, "vs_fpm": -150.0, "hdg_true": RWY_HDG,
            "on_ground": False, "fuel_kg": 3000.0, "g": 1.0,
        })
    lat, lon = td_lat, td_lon
    for i in range(4):
        points.append({
            "t": 3.0 + i, "lat": lat, "lon": lon,
            "alt_ft": 13.0, "agl_ft": 0.0,
            "gs_kt": 130.0 - i * 40, "vs_fpm": -150.0 if i == 0 else 0.0,
            "hdg_true": RWY_HDG, "on_ground": True, "fuel_kg": 3000.0,
            "g": 1.4 if i == 0 else 1.0,
        })
        lat += 70.0 * math.cos(th) / 111320.0
        lon += 70.0 * math.sin(th) / (111320.0 * math.cos(math.radians(lat)))
    return points


def test_displaced_threshold_read_from_navdata(tmp_path: Path):
    nav = NavData(build_kjfk(tmp_path / "kjfk.sqlite"))
    try:
        rwy = next(r for r in nav.runways("KJFK") if r["name"] == "31L")
        assert rwy["displaced_threshold_m"] == pytest.approx(1000.0, abs=1.0)
        # 物理长度仍是跑道全长，不受内移影响
        assert rwy["length_m"] == pytest.approx(4425.0, abs=30.0)
        found = nav.find_runway(RWY_LAT, RWY_LON, RWY_HDG)
        assert found and found["ident"] == "31L"
        assert found["displaced_threshold_m"] == pytest.approx(1000.0, abs=1.0)
    finally:
        nav.close()


def test_missing_offset_column_falls_back_to_zero(tmp_path: Path):
    nav = NavData(build_kjfk(tmp_path / "kjfk_old.sqlite", with_offset=False))
    try:
        rwy = next(r for r in nav.runways("KJFK") if r["name"] == "31L")
        assert rwy["displaced_threshold_m"] == 0.0
        assert rwy["length_m"] == pytest.approx(4425.0, abs=30.0)
    finally:
        nav.close()


def test_threshold_distance_measured_from_displaced_threshold(tmp_path: Path):
    nav = NavData(build_kjfk(tmp_path / "kjfk.sqlite"))
    try:
        td_lat, td_lon = _point_along(1200.0)
        points = make_landing_points(td_lat, td_lon)
        result = evaluate(points, nav)
        landing = result["landing"]
        assert result["arr_icao"] == "KJFK"
        assert landing["runway_ident"] == "31L"
        assert landing["displaced_threshold_m"] == pytest.approx(1000.0, abs=1.0)
        # 接地距物理入口 1200m → 距着陆入口 200m
        assert landing["threshold_distance_m"] == pytest.approx(200.0, abs=40.0)
    finally:
        nav.close()


# --------------------------------------------------------------------------
# §36 场景库跑道几何（游戏内数据优先）
# --------------------------------------------------------------------------
def _with_runway_length_ft(path: Path, length_ft: float) -> Path:
    con = sqlite3.connect(path)
    con.execute("update runway set length=?", (length_ft,))
    con.commit()
    con.close()
    return path


def test_scenery_runway_geometry_preferred(tmp_path: Path):
    main = build_kjfk(tmp_path / "nav.sqlite")
    scen = _with_runway_length_ft(build_kjfk(tmp_path / "scen.sqlite"), 10041.0)
    nav = NavData(main, scenery_path=scen, runway_source="auto")
    try:
        rwy = next(r for r in nav.runways("KJFK") if r["name"] == "31L")
        assert rwy["source"] == "scenery"
        assert rwy["length_m"] == pytest.approx(3060.5, abs=5)   # 游戏内 3060 m
        # 现实 navdata 的对照长度（4425 m）仍可单独取到
        ref = next(r for r in nav.navdata_runways("KJFK") if r["name"] == "31L")
        assert ref["length_m"] == pytest.approx(4425.0, abs=30.0)
        # 最长跑道也换成游戏内数据（影响「跑道够不够长」）
        assert nav.airport("KJFK")["longest_runway_m"] == pytest.approx(3060.5, abs=5)
        found = nav.find_runway(RWY_LAT, RWY_LON, RWY_HDG)
        assert found and found["runway_source"] == "scenery"
        assert found["length_m"] == pytest.approx(3060.5, abs=5)
    finally:
        nav.close()


def test_runway_data_source_navdata_ignores_scenery(tmp_path: Path):
    main = build_kjfk(tmp_path / "nav.sqlite")
    scen = _with_runway_length_ft(build_kjfk(tmp_path / "scen.sqlite"), 10041.0)
    nav = NavData(main, scenery_path=scen, runway_source="navdata")
    try:
        rwy = next(r for r in nav.runways("KJFK") if r["name"] == "31L")
        assert rwy["source"] == "navdata"
        assert rwy["length_m"] == pytest.approx(4425.0, abs=30.0)
    finally:
        nav.close()


def test_landing_metrics_carry_runway_source_and_length(tmp_path: Path):
    main = build_kjfk(tmp_path / "nav.sqlite")
    scen = _with_runway_length_ft(build_kjfk(tmp_path / "scen.sqlite"), 10041.0)
    nav = NavData(main, scenery_path=scen, runway_source="auto")
    try:
        td_lat, td_lon = _point_along(1200.0)
        result = evaluate(make_landing_points(td_lat, td_lon), nav)
        landing = result["landing"]
        assert landing["runway_source"] == "scenery"
        assert landing["runway_length_m"] == pytest.approx(3060.5, abs=5)
    finally:
        nav.close()
