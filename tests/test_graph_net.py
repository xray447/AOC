"""内置航路图内核（`aoc_route.net`）：建图 / Dijkstra 求解 / 缓存与 pkl 兼容回归。

不依赖仓库外的 `Pre-train`：用最小 Little Navmap 导航库（两个机场 + 一条航路）现场建图，
守住 CI 上"没有 Pre-train/src 也能出图航路"这条路径。
"""
from __future__ import annotations

import io
import pickle
import sqlite3
from pathlib import Path

from aoc_route.graph import GraphProvider, cache_tag
from aoc_route.net import geo
from aoc_route.net.network import Network, _CompatUnpickler

# 机场间距 ~250 NM（超过 direct_dct_max_nm=120，必须走航路）；两个航路点各自贴近一端机场，
# 且到对面机场都超过 link_radius_nm=150，于是唯一可行解就是 AAAA -> W1 -Y1-> W3 -> BBBB
WAYPOINTS = [("W1", 31.20, 121.30), ("W3", 33.30, 124.20)]
AIRPORTS = [("AAAA", 31.00, 121.00), ("BBBB", 33.50, 124.50)]

_SCHEMA = """
CREATE TABLE waypoint(waypoint_id INTEGER PRIMARY KEY, ident TEXT, region TEXT, type TEXT,
    nav_id INTEGER, num_victor_airway INTEGER, num_jet_airway INTEGER, lonx REAL, laty REAL);
CREATE TABLE airway(airway_id INTEGER, airway_name TEXT, airway_type TEXT, route_type TEXT,
    airway_fragment_no INTEGER, sequence_no INTEGER, from_waypoint_id INTEGER,
    to_waypoint_id INTEGER, direction TEXT, minimum_altitude INTEGER, maximum_altitude INTEGER);
CREATE TABLE airport(airport_id INTEGER PRIMARY KEY, ident TEXT, name TEXT, region TEXT,
    country TEXT, lonx REAL, laty REAL, longest_runway_length INTEGER, num_approach INTEGER,
    num_runway_hard INTEGER);
CREATE TABLE runway_end(runway_end_id INTEGER PRIMARY KEY, lonx REAL, laty REAL);
CREATE TABLE approach(approach_id INTEGER PRIMARY KEY, airport_ident TEXT, type TEXT,
    arinc_name TEXT, runway_name TEXT, suffix TEXT, fix_ident TEXT, runway_end_id INTEGER);
CREATE TABLE approach_leg(approach_leg_id INTEGER PRIMARY KEY, approach_id INTEGER,
    fix_ident TEXT, fix_laty REAL, fix_lonx REAL, is_missed INTEGER);
CREATE TABLE transition(transition_id INTEGER PRIMARY KEY, approach_id INTEGER, fix_ident TEXT);
CREATE TABLE transition_leg(transition_leg_id INTEGER PRIMARY KEY, transition_id INTEGER,
    fix_ident TEXT, fix_laty REAL, fix_lonx REAL);
"""


def _make_navdata(path: Path) -> Path:
    """最小导航库：两个机场靠 DCT 接入一条 Y1 航路（W1 -> W2 -> W3）。"""
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO waypoint(waypoint_id, ident, region, type, lonx, laty) VALUES (?,?,?,?,?,?)",
        [(i + 1, ident, "Z", "WN", lon, lat) for i, (ident, lat, lon) in enumerate(WAYPOINTS)],
    )
    conn.executemany(
        "INSERT INTO airway(airway_id, airway_name, airway_type, route_type, airway_fragment_no,"
        " sequence_no, from_waypoint_id, to_waypoint_id, direction, minimum_altitude,"
        " maximum_altitude) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(1, "Y1", "B", "R", 1, 1, 1, 2, "N", 0, 60000)],
    )
    conn.executemany(
        "INSERT INTO airport(airport_id, ident, name, region, country, lonx, laty,"
        " longest_runway_length, num_approach, num_runway_hard) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(i + 1, ident, ident, "Z", "CN", lon, lat, 12000, 1, 1)
         for i, (ident, lat, lon) in enumerate(AIRPORTS)],
    )
    conn.commit()
    conn.close()
    return path


def test_build_and_solve_without_pre_train(tmp_path: Path):
    nav = _make_navdata(tmp_path / "nav.sqlite")
    net = Network.build(verbose=False, db_path=str(nav))

    assert {"AAAA", "BBBB"} <= set(net.airports)
    plans = net.plan("AAAA", "BBBB", n_variants=1)
    assert plans, "内置建图应能求出 AAAA->BBBB"
    tokens = plans[0]["tokens"]
    assert tokens[0] == "AAAA" and tokens[-1] == "BBBB"
    assert "W1" in tokens and "W3" in tokens
    assert plans[0]["distance_nm"] > 0


def test_pkl_roundtrip_keeps_planning(tmp_path: Path):
    nav = _make_navdata(tmp_path / "nav.sqlite")
    net = Network.build(verbose=False, db_path=str(nav))
    pkl = tmp_path / "network.pkl"
    net.save(pkl)

    loaded = Network.load(pkl)
    plans = loaded.plan("AAAA", "BBBB", n_variants=1)
    assert plans and plans[0]["tokens"][0] == "AAAA"


def test_graph_provider_builds_and_plans(tmp_path: Path):
    nav = _make_navdata(tmp_path / "nav.sqlite")
    cache = tmp_path / "cache"
    graph = GraphProvider(cache_dir=cache)

    assert graph.available is False
    assert graph.ensure(nav, "2610") is True, graph.error
    assert graph.available is True
    assert graph.network_source.endswith("network.py")

    plans = graph.plan("AAAA", "BBBB")
    assert plans and plans[0]["resolve_ok"], plans
    assert plans[0]["segments"], "航路段应能还原成 (航路名, 起点, 终点)"


def test_corrupt_cache_is_rebuilt(tmp_path: Path):
    nav = _make_navdata(tmp_path / "nav.sqlite")
    cache = tmp_path / "cache"
    cache.mkdir()
    target = cache / f"network-{cache_tag(nav, '2610')}.pkl"
    target.write_bytes(b"not a pickle")

    graph = GraphProvider(cache_dir=cache)
    assert graph.ensure(nav, "2610") is True, graph.error
    assert Network.load(target).plan("AAAA", "BBBB", n_variants=1)


def test_legacy_pkl_module_path_is_remapped():
    """Pre-train 时期存的 pkl 里类路径是 `src.geo.GridIndex`，读的时候要能落到内置包。"""
    index = geo.GridIndex([("W1", 31.1, 121.1)])
    legacy = pickle.dumps({"node_index": index}, protocol=0)
    legacy = legacy.replace(b"aoc_route.net.geo", b"src.geo")
    assert b"src.geo" in legacy

    state = _CompatUnpickler(io.BytesIO(legacy)).load()
    assert isinstance(state["node_index"], geo.GridIndex)
