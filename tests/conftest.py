from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aoc_navdata import NavData

@pytest.fixture(autouse=True)
def _offline_side_effects(monkeypatch: pytest.MonkeyPatch):
    """单测不联网、不建图：AIP 同步与本地建图的开关都在环境变量里。"""
    monkeypatch.setenv("AOC_NO_NET", "1")
    monkeypatch.setenv("AOC_NO_GRAPH_BUILD", "1")


AIRPORTS = [
    # ident, lat, lon, elev, country, name
    ("ZBAA", 40.0801, 116.5846, 116, "CN", "Beijing Capital"),
    ("ZSSS", 31.1979, 121.3363, 10, "CN", "Shanghai Hongqiao"),
    ("RJTT", 35.5533, 139.7812, 21, "JP", "Tokyo Haneda"),
    ("RJAA", 35.7647, 140.3864, 141, "JP", "Narita"),
    ("LROP", 44.5722, 26.1022, 314, "RO", "Bucharest Otopeni"),
    ("LFPG", 49.0097, 2.5479, 392, "FR", "Paris CDG"),
    ("EGLL", 51.4700, -0.4543, 83, "GB", "London Heathrow"),
    ("KJFK", 40.6413, -73.7781, 13, "US", "New York JFK"),
    ("ZLXY", 34.4471, 108.7516, 1572, "CN", "Xi'an"),
    ("ZHHH", 30.7838, 114.2081, 113, "CN", "Wuhan"),
    ("ZSNJ", 31.7420, 118.8622, 49, "CN", "Nanjing"),
    ("ZSHC", 30.2295, 120.4344, 23, "CN", "Hangzhou"),
    ("ZSPD", 31.1434, 121.8052, 13, "CN", "Shanghai Pudong"),
    ("ZSCN", 28.8650, 115.9000, 143, "CN", "Nanchang"),
    ("ZBTJ", 39.1244, 117.3462, 10, "CN", "Tianjin"),
    ("ZBSJ", 38.2807, 114.6963, 233, "CN", "Shijiazhuang"),
    ("ZBYN", 37.7469, 112.6284, 2570, "CN", "Taiyuan"),
    ("ZUUU", 30.5785, 103.9471, 1625, "CN", "Chengdu"),
    ("ZPPP", 25.1019, 102.9292, 6903, "CN", "Kunming"),
    ("ZJHK", 19.9349, 110.4589, 75, "CN", "Haikou"),
    ("ZGHA", 28.1892, 113.2196, 217, "CN", "Changsha"),
]


def build_navdata(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE airport(
            airport_id INTEGER PRIMARY KEY, ident TEXT, name TEXT, iata TEXT, city TEXT,
            country TEXT, laty REAL, lonx REAL, altitude REAL, transition_altitude REAL,
            longest_runway_length REAL);
        CREATE TABLE runway(
            runway_id INTEGER PRIMARY KEY, airport_id INTEGER, primary_end_id INTEGER,
            secondary_end_id INTEGER, length REAL, has_ils INTEGER);
        CREATE TABLE runway_end(
            runway_end_id INTEGER PRIMARY KEY, name TEXT, heading REAL, laty REAL,
            lonx REAL, altitude REAL);
        CREATE TABLE waypoint(waypoint_id INTEGER PRIMARY KEY, ident TEXT, laty REAL, lonx REAL);
        CREATE TABLE airway(
            airway_id INTEGER PRIMARY KEY, airway_name TEXT, airway_type TEXT,
            from_waypoint_id INTEGER, to_waypoint_id INTEGER,
            minimum_altitude REAL, maximum_altitude REAL,
            from_lonx REAL, from_laty REAL, to_lonx REAL, to_laty REAL);
        CREATE TABLE metadata(airac TEXT, version TEXT, build TEXT, created TEXT, extra TEXT);
        """
    )
    for i, (ident, lat, lon, elev, country, name) in enumerate(AIRPORTS, start=1):
        con.execute(
            "insert into airport values(?,?,?,?,?,?,?,?,?,?,?)",
            (i, ident, name, None, None, country, lat, lon, elev, 18000, 12000))
        end_id = i * 10 + 1
        con.execute("insert into runway values(?,?,?,?,?,?)", (i, i, end_id, None, 12000, 1))
        con.execute("insert into runway_end values(?,?,?,?,?,?)",
                    (end_id, "18", 180.0, lat, lon, elev))
    # ZBAA/ZSSS waypoints + 一条覆盖中国东部的高空航路
    con.execute("insert into waypoint values(1001,'ZBAA',40.0801,116.5846)")
    con.execute("insert into waypoint values(1002,'ZSSS',31.1979,121.3363)")
    con.execute("insert into waypoint values(1003,'PAMDA',36.0,118.5)")
    con.execute("insert into waypoint values(1004,'SASAN',33.0,120.5)")
    con.execute(
        "insert into airway values(1,'J123','J',1001,1002,20000,41000,116.5846,40.0801,121.3363,31.1979)")
    con.execute(
        "insert into airway values(2,'G212','A',1003,1004,20000,41000,118.5,36.0,120.5,33.0)")
    con.execute("insert into metadata values('2609','test-fixture','1','2026-10-20','')")
    con.commit()
    con.close()
    return path


def add_airport_flags(path: Path, *, military: tuple[str, ...] = (),
                      width_ft: dict[str, float] | None = None) -> Path:
    """给 fixture 库补 `is_military` / `longest_runway_width` / `runway.width`（§23/§26）。"""
    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("pragma table_info(airport)")}
    if "is_military" not in cols:
        con.execute("alter table airport add column is_military INTEGER DEFAULT 0")
    if "longest_runway_width" not in cols:
        con.execute("alter table airport add column longest_runway_width REAL")
    rcols = {r[1] for r in con.execute("pragma table_info(runway)")}
    if "width" not in rcols:
        con.execute("alter table runway add column width REAL")
    for ident in military:
        con.execute("update airport set is_military=1 where ident=?", (ident,))
    for ident, width in (width_ft or {}).items():
        con.execute("update airport set longest_runway_width=? where ident=?", (width, ident))
        con.execute(
            "update runway set width=? where airport_id=(select airport_id from airport where ident=?)",
            (width, ident))
    con.commit()
    con.close()
    return path


@pytest.fixture()
def navdata_path(tmp_path: Path) -> Path:
    return build_navdata(tmp_path / "navdata.sqlite")


@pytest.fixture()
def nav(navdata_path: Path):
    data = NavData(navdata_path)
    yield data
    data.close()


@pytest.fixture()
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AOC_HOME", str(tmp_path / "home"))
    from main import CoreConfig, create_app

    app = create_app(CoreConfig(home=tmp_path / "home", port=0, token="test-token",
                                static_dir=tmp_path / "dist"))
    with TestClient(app) as client:
        client.headers.update({"X-AOC-Token": "test-token"})
        yield client


def make_points(takeoff: float = 20, landing: float = 100, total: float = 115,
                step: float = 1.0) -> list[dict]:
    """ZBAA → ZSSS 的简化 1Hz 采样（地面→起飞→巡航→落地→滑跑）。"""
    points = []
    t = 0.0
    while t <= total + 1e-9:
        if t < takeoff:
            lat, lon, alt, agl, gs, vs, on_ground = 40.0801, 116.5846, 116, 0, 15, 0, True
        elif t < landing:
            k = (t - takeoff) / (landing - takeoff)
            lat = 40.0801 + (31.1979 - 40.0801) * k
            lon = 116.5846 + (121.3363 - 116.5846) * k
            if k < 0.15:
                alt, vs, gs = 116 + (20000 - 116) * (k / 0.15), 2400, 200
            elif k < 0.75:
                alt, vs, gs = 35000, 0, 450
            elif k < 0.92:
                alt, vs, gs = 35000 + (3000 - 35000) * ((k - 0.75) / 0.17), -1700, 280
            else:
                alt, vs, gs = 3000 + (10 - 3000) * ((k - 0.92) / 0.08), -150, 140
            agl, on_ground = max(0, alt - 10), False
        else:
            lat, lon, alt, agl = 31.1979, 121.3363, 10, 0
            gs = max(0, 130 - (t - landing) * 14)
            vs = -150 if abs(t - landing) < 0.5 else 0
            on_ground = True
        points.append({
            "t": t, "lat": lat, "lon": lon, "alt_ft": alt, "agl_ft": agl,
            "gs_kt": gs, "vs_fpm": vs, "hdg_true": 180,
            "on_ground": on_ground, "fuel_kg": max(1000, 8000 - t * 20),
            "g": 1.3 if abs(t - landing) < 0.5 else 1.0,
            "ias_kt": gs * 0.9, "sim_rate": 1.0, "paused": False,
        })
        t += step
    return points
