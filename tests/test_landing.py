from __future__ import annotations

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
