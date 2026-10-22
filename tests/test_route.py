from __future__ import annotations

from pathlib import Path

import pytest

from aoc_navdata import NavData
from aoc_route import RouteService, build_pln
from aoc_route.aip import AipProvider, parse_altitude, sync_jp_routes
from aoc_route.graph import GraphProvider, cache_tag


class FakeGraph(GraphProvider):
    def __init__(self, pkl: Path, distance_nm: float, gcd_nm: float):
        super().__init__(pkl=pkl)
        self._plan_distance = distance_nm
        self._plan_gcd = gcd_nm

    @property
    def available(self) -> bool:  # type: ignore[override]
        return True

    def plan(self, dep: str, arr: str, cruise_fl: int = 350, n_variants: int = 1):
        return [{
            "tokens": [dep, "J123", arr],
            "route": f"{dep} J123 {arr}",
            "distance_nm": self._plan_distance,
            "gcd_nm": self._plan_gcd,
            "resolve_ok": True,
            "resolve_error": "",
            "airways": ["J123"],
            "segments": [("J123", dep, arr)],
            "sid": "TEST1A",
            "star": "TEST2B",
        }]


class FoldGraph(FakeGraph):
    """模拟老师口径：tokens 折叠、tokens_full 逐点。"""

    def plan(self, dep: str, arr: str, cruise_fl: int = 350, n_variants: int = 1):
        full = [dep, "J123", "PAMDA", "SASAN", arr]
        return [{
            "tokens": [dep, "J123", arr],
            "tokens_full": full,
            "route": f"{dep} J123 {arr}",
            "distance_nm": self._plan_distance,
            "gcd_nm": self._plan_gcd,
            "resolve_ok": True,
            "resolve_error": "",
            "airways": ["J123"],
            "segments": [("J123", dep, arr)],
            "sid": "TEST1A",
            "star": "TEST2B",
        }]


@pytest.fixture()
def service(navdata_path: Path) -> RouteService:
    return RouteService(navdata_path=navdata_path)


def test_a22_aip_japan(service: RouteService):
    result = service.generate("RJTT", "RJAA", 350, "A320")
    assert result.status == "OK"
    assert result.route_source == "AIP"
    assert result.sid_options and result.sid_options[0].name == "VAMOS4.TATEY"
    assert result.star_options and result.star_options[0].name == "BINKSA"
    assert result.runway_options
    assert result.simbrief_url.startswith("https://dispatch.simbrief.com/")
    assert "route=" in result.simbrief_url
    assert any("fixture" in w for w in result.warnings)


def test_a23_no_high_alt_coverage(service: RouteService):
    result = service.generate("LROP", "LFPG", 350, "A320")
    assert result.status == "REQUIRES_SIMBRIEF"
    assert result.route_source == "NONE"
    assert result.coverage == "NO_HIGH_ALT"
    assert result.route is None
    assert result.simbrief_url
    assert result.requires_simbrief is True
    assert result.coverage_gaps


def test_a24_graph_route(navdata_path: Path, tmp_path: Path):
    pkl = tmp_path / "network.pkl"
    pkl.write_bytes(b"fake")
    empty_aip = tmp_path / "aip.csv"
    empty_aip.write_text("dep,arr,route,min_fl,max_fl,source,airac,sid,star,runway\n", encoding="utf-8")
    service = RouteService(navdata_path=navdata_path, aip_path=empty_aip,
                           graph=FakeGraph(pkl, 620, 610))
    result = service.generate("ZBAA", "ZSSS", 350, "A320")
    assert result.status == "OK"
    assert result.route_source == "GRAPH"
    assert result.altitude_valid is True
    assert result.valid is True
    assert result.distance_nm == 620
    assert result.coverage == "HIGH_ALT_AIRWAY"
    assert "route=" in result.simbrief_url
    assert result.requires_simbrief is False


def test_a24b_graph_uses_folded_tokens(navdata_path: Path, tmp_path: Path):
    """图航路对外用折叠写法（与老师 src.infer.graph_route 一致），导出 .pln 用逐点写法。"""
    pkl = tmp_path / "network.pkl"
    pkl.write_bytes(b"fake")
    empty_aip = tmp_path / "aip.csv"
    empty_aip.write_text("dep,arr,route,min_fl,max_fl,source,airac,sid,star,runway\n", encoding="utf-8")
    service = RouteService(navdata_path=navdata_path, aip_path=empty_aip,
                           graph=FoldGraph(pkl, 620, 610))
    result = service.generate("ZBAA", "ZSSS", 350, "A320")
    assert result.status == "OK" and result.route_source == "GRAPH"
    assert result.tokens == ["ZBAA", "J123", "ZSSS"]
    assert result.tokens_full == ["ZBAA", "J123", "PAMDA", "SASAN", "ZSSS"]
    assert result.route == "ZBAA J123 ZSSS"
    assert "J123" in result.simbrief_url

    nav = NavData(navdata_path)
    try:
        text = build_pln(result, nav)
    finally:
        nav.close()
    assert "PAMDA" in text and "SASAN" in text     # .pln 用逐点写法


def test_a25_detour_rejected(navdata_path: Path, tmp_path: Path):
    pkl = tmp_path / "network.pkl"
    pkl.write_bytes(b"fake")
    empty_aip = tmp_path / "aip.csv"
    empty_aip.write_text("dep,arr,route,min_fl,max_fl,source,airac,sid,star,runway\n", encoding="utf-8")
    service = RouteService(navdata_path=navdata_path, aip_path=empty_aip,
                           graph=FakeGraph(pkl, 1400, 610))
    result = service.generate("ZBAA", "ZSSS", 350, "A320")
    assert result.status == "REQUIRES_SIMBRIEF"
    assert result.route is None
    assert any("绕行" in w for w in result.warnings)
    assert result.simbrief_url


def test_a30_navdata_missing():
    service = RouteService()
    result = service.generate("ZBAA", "ZSSS", 350, "A320")
    assert result.status == "NAVDATA_MISSING"
    assert result.route is None
    assert result.simbrief_url
    assert any("SimBrief" in w for w in result.warnings)


def test_a26_simbrief_without_route(service: RouteService):
    url = service.simbrief("ZBAA", "ZSSS", 350, "A320")
    assert url.startswith("https://dispatch.simbrief.com/")
    assert "orig=ZBAA" in url and "dest=ZSSS" in url
    assert "route=" not in url


def test_simbrief_splits_callsign(service: RouteService):
    """呼号拆成 airline + fltnum（SimBrief 不接受 callsign）。"""
    url = service.simbrief("ZBAA", "ZSSS", 350, "A320", None, "aoc101")
    assert "airline=AOC" in url and "fltnum=101" in url
    assert "type=A320" in url
    assert "callsign=" not in url
    # 不预填高度，高度交给 SimBrief 自己算
    assert "fl=" not in url

    # 没有末尾数字时只传 airline，呼号需在 SimBrief 内手动确认
    plain = service.simbrief("ZBAA", "ZSSS", 350, "A320", None, "AUV")
    assert "airline=AUV" in plain
    assert "fltnum=" not in plain and "callsign=" not in plain


def test_simbrief_uses_manualzfw(service: RouteService):
    """配载改用 ZFW（千磅、3 位小数）；payload/pax/cargo/fuel 都不是 SimBrief 参数。"""
    url = service.simbrief("ZBAA", "ZSSS", 350, "A320", None, "AOC101", 6120, "B-1671")
    assert "manualzfw=13.492" in url      # 6120 kg × 2.2046226 ÷ 1000
    assert "reg=B-1671" in url
    for legacy in ("payload=", "callsign=", "pax=", "cargo=", "fuel=", "fl="):
        assert legacy not in url


def test_coverage_endpoint(service: RouteService):
    ok = service.coverage("ZBAA", "ZSSS", 350)
    assert ok.checked is True
    assert ok.coverage == "HIGH_ALT_AIRWAY"
    bad = service.coverage("LROP", "LFPG", 350)
    assert bad.coverage == "NO_HIGH_ALT"
    assert bad.requires_simbrief is True


def test_validate_tokens(service: RouteService):
    result = service.validate(["ZBAA", "J123", "ZSSS"], 350)
    assert result.valid is True
    assert result.altitude_valid is True
    bad = service.validate(["ZBAA", "DCT"], 350)
    assert bad.valid is True  # token 合法，但没有高度数据


# --------------------------------------------------------------------------
# 日本 AIP（jp-routes 列名）与本地建图
# --------------------------------------------------------------------------
JP_CSV = (
    "DEP,DEST,Time Restriction,Altitude,Aircraft,Route,Remarks\n"
    "RJTT,RJBB,,FL290-FL410,,RJTT OPPAR4 JYOGA Y566 LAXAS Y56 KAGNA DCT YZT "
    "GAKKI Y55 KOHWA Y544 DUBKA DUBKAA RJBB,\n"
)


def test_aip_reads_jp_routes_columns(tmp_path: Path):
    path = tmp_path / "routes.csv"
    path.write_text(JP_CSV, encoding="utf-8")
    aip = AipProvider(path, default_source="jp-routes")
    rows = aip.lookup("RJTT", "RJBB", 350)
    assert rows, "jp-routes 列名应能被识别"
    assert rows[0]["dep"] == "RJTT" and rows[0]["arr"] == "RJBB"
    assert rows[0]["source"] == "jp-routes"
    assert rows[0]["min_fl"] == 290 and rows[0]["max_fl"] == 410
    assert aip.lookup("RJTT", "RJBB", 200) == []      # 低于该航路下限
    assert aip.lookup("RJTT", "RJBB", 430) == []      # 高于上限


def test_aip_sample_is_marked_fixture():
    rows = AipProvider().load()
    assert rows and all("fixture" in r["source"] for r in rows)


def test_parse_altitude_variants():
    assert parse_altitude("FL290-FL410") == (290, 410)
    assert parse_altitude("29000-41000") == (290, 410)
    assert parse_altitude("FL290以上") == (290, 0)
    assert parse_altitude("") == (0, 0)


def test_sync_jp_routes_uses_fresh_cache(tmp_path: Path):
    cache = tmp_path / "aip_routes_jp.csv"
    cache.write_text(JP_CSV, encoding="utf-8")
    # 缓存新鲜时不应发请求（地址故意不可用）
    assert sync_jp_routes(cache, url="http://127.0.0.1:9/never") == cache


def test_graph_cache_tag_changes_with_navdata(tmp_path: Path):
    db = tmp_path / "nav.sqlite"
    db.write_bytes(b"x")
    first = cache_tag(db, "2610")
    assert first.startswith("2610-")
    db.write_bytes(b"y" * 64)                         # 大小变化 = 换库/换版本
    assert cache_tag(db, "2610") != first
    assert cache_tag(db, None).startswith("unknown-")


def test_ensure_graph_without_builder(tmp_path: Path):
    graph = GraphProvider(pre_train_dir=tmp_path / "missing", cache_dir=tmp_path / "cache")
    nav = tmp_path / "nav.sqlite"
    nav.write_bytes(b"x")
    assert graph.ensure(nav, "2610") is False
    assert "建图脚本不存在" in graph.error
