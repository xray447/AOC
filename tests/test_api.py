from __future__ import annotations

from .conftest import make_points


def test_health_and_bootstrap_without_token(app_client):
    assert app_client.get("/local/health").status_code == 200
    boot = app_client.get("/local/bootstrap").json()
    assert boot["token"] == "test-token"
    assert boot["url"].startswith("http://127.0.0.1")


def test_token_required(app_client):
    res = app_client.get("/local/flights", headers={"X-AOC-Token": "wrong"})
    assert res.status_code == 401
    assert res.json()["code"] == "AUTH_INVALID"


def test_settings_and_navdata(app_client, navdata_path):
    settings = app_client.get("/local/settings").json()["settings"]
    assert settings["language"] == "zh"
    res = app_client.put("/local/settings", json={
        "navdata_path": str(navdata_path), "home_airport": "ZBAA", "onboarded": True,
    })
    assert res.status_code == 200
    assert res.json()["settings"]["navdata_path"] == str(navdata_path)
    status = app_client.get("/local/navdata/status").json()
    assert status["available"] is True
    assert status["airac"] == "2609"


def test_recommend_and_routes(app_client, navdata_path):
    app_client.put("/local/settings", json={"navdata_path": str(navdata_path), "home_airport": "ZBAA"})
    rec = app_client.post("/local/recommend", json={
        "available_minutes": 90, "base_icao": "ZBAA", "limit": 8,
    }).json()
    assert len(rec["candidates"]) >= 5

    aip = app_client.post("/local/routes/generate", json={
        "dep": "RJTT", "arr": "RJAA", "cruise_fl": 350,
    }).json()
    assert aip["route_source"] == "AIP"
    assert aip["simbrief_url"]

    # A-04：ZBAA→ZSSS 返回航路串、里程、SID/STAR、SimBrief 预填
    cn = app_client.post("/local/routes/generate", json={
        "dep": "ZBAA", "arr": "ZSSS", "cruise_fl": 350,
    }).json()
    assert cn["status"] == "OK"
    assert cn["route"].startswith("ZBAA ") and cn["route"].endswith(" ZSSS")
    assert cn["distance_nm"] == 562
    assert cn["sid_options"] and cn["star_options"]
    assert cn["altitude_valid"] is True
    assert "route=" in cn["simbrief_url"]

    pln = app_client.post("/local/routes/export?format=pln", json={
        "dep": "ZBAA", "arr": "ZSSS", "cruise_fl": 350,
    })
    assert pln.status_code == 200
    assert "<SimBase.Document" in pln.text
    assert "ZBAA" in pln.text and "ZSSS" in pln.text

    missing = app_client.post("/local/routes/generate", json={
        "dep": "LROP", "arr": "LFPG", "cruise_fl": 350,
    }).json()
    assert missing["status"] == "REQUIRES_SIMBRIEF"
    assert missing["simbrief_url"]

    simbrief = app_client.get("/local/routes/simbrief?dep=ZBAA&arr=ZSSS").json()
    assert "orig=ZBAA" in simbrief["simbrief_url"]

    coverage = app_client.post("/local/routes/coverage", json={
        "dep": "ZBAA", "arr": "ZSSS", "cruise_fl": 350,
    }).json()
    assert coverage["coverage"] == "HIGH_ALT_AIRWAY"


def test_flight_lifecycle(app_client, navdata_path):
    app_client.put("/local/settings", json={"navdata_path": str(navdata_path)})
    service = app_client.app.state.service
    service.flights.start(flight_id="test-flight", started_at="2026-10-20T00:00:00Z", manual=True)
    service.flights.ingest(make_points())
    flight = service.flights.stop()
    assert flight is not None
    assert flight["status"] == "COMPLETED"
    assert flight["dep_icao"] == "ZBAA"
    assert flight["arr_icao"] == "ZSSS"
    assert flight["runway_ident"] == "18"
    assert flight["track_points"] > 0
    assert flight["track_bytes"] > 0
    assert flight["landing_rating"] in ("GREAT", "GOOD")

    detail = app_client.get("/local/flights/test-flight").json()
    assert detail["status"] == "COMPLETED"
    track = app_client.get("/local/flights/test-flight/track").json()
    assert track["total_points"] > 0
    assert track["points"][0]["lat"]
    assert track["events"]

    gpx = app_client.get("/local/flights/test-flight/export?format=gpx")
    assert gpx.status_code == 200
    assert "<gpx" in gpx.text
    csv = app_client.get("/local/flights/test-flight/export?format=csv")
    assert "lat" in csv.text

    stats = app_client.get("/local/stats").json()
    assert stats["flights"] == 1
    assert "ZSSS" in stats["distinct_airports"]

    legs = app_client.get("/local/flown-legs").json()["items"]
    assert any(leg["dep_icao"] == "ZBAA" and leg["arr_icao"] == "ZSSS" for leg in legs)

    listing = app_client.get("/local/flights?limit=10").json()
    assert listing["total"] == 1

    assert app_client.delete("/local/flights/test-flight").json()["ok"] is True


def test_record_requires_simlink(app_client):
    res = app_client.post("/local/recording/start")
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "SIMLINK_UNAVAILABLE"
