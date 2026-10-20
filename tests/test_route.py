from __future__ import annotations

from pathlib import Path

import pytest

from aoc_route import RouteService
from aoc_route.graph import GraphProvider


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
