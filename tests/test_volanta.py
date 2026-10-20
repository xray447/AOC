from __future__ import annotations

from aoc_integrations.volanta import extract_track, parse_api_flights, parse_api_payload, parse_csv

CSV = """Date,Origin,Destination,Aircraft,Duration,LandingRate
2026-10-18,RJTT,RJAA,A320,1:15,-120
2026-10-19,ZBAA,ZSSS,A333,145,-210
2026-10-19,BAD,ZSSS,A320,60,-100
"""


def test_parse_csv():
    legs = parse_csv(CSV)
    assert len(legs) == 2
    assert legs[0]["dep_icao"] == "RJTT"
    assert legs[0]["arr_icao"] == "RJAA"
    assert legs[0]["duration_min"] == 75
    assert legs[1]["duration_min"] == 145
    assert legs[1]["aircraft_type"] == "A333"
    assert legs[0]["source"] == "VOLANTA"


def test_parse_csv_keeps_callsign_and_fields():
    """航班号（CSV 里的 Flight Number / Callsign）要能解析出来，其余字段不受影响。"""
    csv = ("Date,Flight Number,Origin,Destination,Aircraft,Duration,Landing Rate\n"
           "2026-10-18,CA1234,RJTT,RJAA,A320,1:15,-120\n"
           "2026-10-19,,ZBAA,ZSSS,A333,145,-210\n")
    legs = parse_csv(csv)
    assert legs[0]["callsign"] == "CA1234"
    assert legs[0]["flight_date"] == "2026-10-18"
    assert legs[0]["duration_min"] == 75
    assert legs[0]["landing_rate_fpm"] == -120
    assert legs[1]["callsign"] is None, "没有航班号时留空，不要编造"


def test_parse_api_payload():
    payload = {"flights": [
        {"flight": {"originIcao": "RJTT", "destinationIcao": "RJAA"}},
        {"flight": {"origin": {"icaoCode": "ZBAA"}, "destination": {"icaoCode": "ZSSS"}}},
        {"flight": {"originIcao": "BAD", "destinationIcao": "RJTT"}},
    ]}
    legs = parse_api_payload(payload)
    assert [(x["dep_icao"], x["arr_icao"]) for x in legs] == [("RJTT", "RJAA"), ("ZBAA", "ZSSS")]


# 真实 /api/v1/Flights 的单条记录（节选）：机型是 aircraftIcao，`aircraft` 是嵌套对象
REAL_FLIGHT = {
    "id": "004432dd-826c-4377-a1e6-7f79b80c3149",
    "callsign": "GNXWB",
    "flightNumber": None,
    "originIcao": "RJGG",
    "destinationIcao": "RJOO",
    "offBlocksTime": "2025-03-02T12:50:53.824",
    "onBlocksTime": "2025-03-02T13:32:35.837",
    "realBlockTime": 2502.013,
    "realFlightTime": 1857.0,
    "aircraftIcao": "A359",
    "aircraftRegistration": "B-323H",
    "aircraftTitle": "Airbus A350-900 Japan Airlines (JA02XJ)",
    "aircraft": {"id": "cac3fafd", "registration": "B-323H", "aircraftTypeIcao": "A359"},
    "landingRate": -181.143765,
}


def test_parse_api_flight_real_fields():
    """真实接口的字段名：日期取推出时刻、时长是秒、机型取 aircraftIcao、注册号单独存。"""
    legs = parse_api_flights({"flights": [{"flight": REAL_FLIGHT}]})
    assert len(legs) == 1
    leg = legs[0]
    assert leg["callsign"] == "GNXWB"
    assert leg["flight_date"] == "2025-03-02"
    assert leg["duration_min"] == 42, "2502 秒应换算成 42 分钟"
    assert leg["aircraft_type"] == "A359", "不能把嵌套的 aircraft 对象当成机型"
    assert leg["registration"] == "B-323H"
    assert leg["landing_rate_fpm"] == -181.143765


def test_livery_name_is_not_a_registration():
    """aircraftRegistration 有时是涂装名：不能当成注册号显示。"""
    raw = {**REAL_FLIGHT, "aircraftRegistration": "Airbus House Livery"}
    legs = parse_api_flights({"flights": [{"flight": raw}]})
    assert legs[0]["registration"] is None


def test_parse_api_flights_keeps_track_and_raw():
    payload = {"flights": [{"flight": {
        "id": "abc", "originIcao": "RJTT", "destinationIcao": "RJAA",
        "track": [{"lat": 35.5, "lon": 139.7}, {"lat": 35.7, "lon": 140.3}],
    }}]}
    flights = parse_api_flights(payload)
    assert len(flights) == 1
    assert flights[0]["track"] == [[139.7, 35.5], [140.3, 35.7]]
    assert flights[0]["raw"]


def test_extract_track_from_latlon_pairs():
    assert extract_track({"positions": [[35.5, 139.7], [35.7, 140.3]]}) == \
        [[139.7, 35.5], [140.3, 35.7]]
    assert extract_track({"foo": "bar"}) is None


def test_sync_stores_full_flights_without_clearing(app_client):
    csv = ("Date,Origin,Destination,Aircraft,Duration\n"
           "2026-10-12,RJTT,RJAA,A320,90\n"
           "2026-10-13,RJTT,RJAA,A320,90\n")
    first = app_client.post("/local/volanta/sync", json={"csv_text": csv}).json()
    assert first["flights_stored"] == 2
    # 重复导入不应删除或清空已有记录
    second = app_client.post("/local/volanta/sync", json={"csv_text": csv}).json()
    assert second["flights_stored"] == 0
    items = app_client.get("/local/volanta/flights").json()["items"]
    assert len(items) == 2
    detail = app_client.get(f"/local/volanta/flights/{items[0]['id']}").json()
    assert detail["raw"], "原始数据必须保留"
    assert detail["dep_icao"] and detail["arr_icao"]


def test_imported_flight_fields_roundtrip(app_client):
    """导入后，航班号/日期/航段/时长/接地率要与 CSV 里的一致（地图页表格用的就是这些字段）。"""
    csv = ("Date,Flight Number,Origin,Destination,Aircraft,Duration,Landing Rate\n"
           "2026-10-18,CA1234,RJTT,RJAA,A320,1:15,-120\n")
    app_client.post("/local/volanta/sync", json={"csv_text": csv})
    items = app_client.get("/local/volanta/flights").json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["callsign"] == "CA1234"
    assert row["flight_date"] == "2026-10-18"
    assert (row["dep_icao"], row["arr_icao"]) == ("RJTT", "RJAA")
    assert row["duration_min"] == 75
    assert row["landing_rate_fpm"] == -120


def test_map_includes_imported_legs(app_client):
    app_client.post("/local/volanta/sync", json={"csv_text": CSV})
    legs = {(l["dep"], l["arr"]): l for l in app_client.get("/local/map").json()["legs"]}
    assert legs[("RJTT", "RJAA")]["sources"] == ["CSV"]
    assert legs[("ZBAA", "ZSSS")]["sources"] == ["CSV"]

    filtered = app_client.get("/local/map?year=2025").json()["legs"]
    assert filtered == []


def test_sync_volanta_token_stores_track(tmp_path, monkeypatch):
    """API 导入时保存完整原始 JSON 与轨迹（用假 payload 代替真实接口）。"""
    import asyncio

    from aoc_core.paths import AppPaths
    from aoc_core.service import PersonalService
    from aoc_integrations import volanta as volanta_mod

    payload = {"flights": [{"flight": {
        "id": "f1", "originIcao": "RJTT", "destinationIcao": "RJAA",
        "track": [{"lat": 35.5, "lon": 139.7}, {"lat": 35.7, "lon": 140.3}],
    }}]}
    monkeypatch.setattr(volanta_mod.VolantaClient, "fetch_raw", lambda self: {
        "ok": True, "payload": payload,
        "flights": volanta_mod.parse_api_flights(payload),
        "diagnostic": "", "warnings": [],
    })
    svc = PersonalService(AppPaths.create(tmp_path / "home"))
    try:
        result = svc.sync_volanta(token="dummy")
        assert result.flights_stored == 1
        assert result.tracks_stored == 1
        rows = svc.volanta_flights()
        assert len(rows) == 1
        assert rows[0]["point_count"] == 2
        detail = svc.volanta_flight(rows[0]["id"])
        assert detail["track"] == [[139.7, 35.5], [140.3, 35.7]]
        assert detail["raw"]["flight"]["id"] == "f1"
    finally:
        asyncio.run(svc.close())


def test_map_count_uses_max_of_local_and_imported(tmp_path):
    """本地有 1 班、导入 5 班时，线宽按 5 班算（不能因为本地有记录就压成 1）。"""
    import asyncio

    from aoc_core.paths import AppPaths
    from aoc_core.service import PersonalService

    svc = PersonalService(AppPaths.create(tmp_path / "home"))
    try:
        svc.db.insert_flight({"id": "local-1", "status": "COMPLETED",
                              "dep_icao": "ZBAA", "arr_icao": "ZSSS"})
        rows = "".join(f"2026-10-{d:02d},ZBAA,ZSSS,A320,90\n" for d in range(12, 17))
        svc.sync_volanta(csv_text="Date,Origin,Destination,Aircraft,Duration\n" + rows)
        legs = {(l["dep"], l["arr"]): l for l in svc.map_data()["legs"]}
        assert legs[("ZBAA", "ZSSS")]["count"] == 5
        assert "AOC" in legs[("ZBAA", "ZSSS")]["sources"]
    finally:
        asyncio.run(svc.close())


def test_backfill_imported_flights_from_legs(tmp_path):
    """旧版本只写了 flown_leg：启动时应补进 volanta_flight，且不把 AOC 自己的记录混进去。"""
    import asyncio

    from aoc_core.paths import AppPaths
    from aoc_core.service import PersonalService

    svc = PersonalService(AppPaths.create(tmp_path / "home"))
    try:
        svc.db.add_flown_leg({"source": "CSV", "dep_icao": "RJTT", "arr_icao": "RJAA",
                              "flight_date": "2026-10-12", "aircraft_type": "A320", "duration_min": 90})
        svc.db.add_flown_leg({"source": "AOC", "dep_icao": "ZBAA", "arr_icao": "ZSSS",
                              "flight_date": "2026-10-20", "aircraft_type": "A320"})
        svc.db._backfill_volanta_flights()
        items = svc.volanta_flights()
        assert [(i["dep_icao"], i["arr_icao"]) for i in items] == [("RJTT", "RJAA")]
        assert items[0]["point_count"] == 0
        # 幂等：再跑一次不会重复
        svc.db._backfill_volanta_flights()
        assert len(svc.volanta_flights()) == 1
    finally:
        asyncio.run(svc.close())


def test_repair_imported_flights_fills_missing_fields(tmp_path):
    """老数据的航班号/日期/时长/机型要么为空要么是错的：启动时应从原始数据补全。"""
    import asyncio

    from aoc_core.paths import AppPaths
    from aoc_core.service import PersonalService

    paths = AppPaths.create(tmp_path / "home")
    svc = PersonalService(paths)
    svc.db.upsert_volanta_flight({
        "source": "VOLANTA", "external_id": "old-1",
        "dep_icao": "RJGG", "arr_icao": "RJOO",
        "aircraft_type": "{'ID': '",  # 旧解析器把嵌套对象当成了机型
        "landing_rate_fpm": -181.143765,
        "raw": {"flight": REAL_FLIGHT},
    })
    svc.db.setting_set("imported_flight_repair", 0)  # 模拟升级后首次启动
    asyncio.run(svc.close())

    repaired = PersonalService(paths)
    try:
        rows = repaired.volanta_flights()
        assert len(rows) == 1
        row = rows[0]
        assert row["callsign"] == "GNXWB"
        assert row["registration"] == "B-323H"
        assert row["flight_date"] == "2025-03-02"
        assert row["duration_min"] == 42
        assert row["aircraft_type"] == "A359"
        # 幂等：再跑一次不会有任何改动
        assert repaired._repair_imported_flights() == 0
    finally:
        asyncio.run(repaired.close())


def test_old_db_gets_callsign_column(tmp_path):
    """老库的 volanta_flight 没有 callsign 列：启动后应自动补列，已有数据不丢。"""
    import asyncio
    import sqlite3

    from aoc_core.paths import AppPaths
    from aoc_core.service import PersonalService

    paths = AppPaths.create(tmp_path / "home")
    con = sqlite3.connect(paths.db)
    con.execute(
        "create table volanta_flight (id TEXT PRIMARY KEY, source TEXT NOT NULL, external_id TEXT, "
        "dep_icao TEXT, arr_icao TEXT, flight_date TEXT, aircraft_type TEXT, duration_min INTEGER, "
        "landing_rate_fpm REAL, point_count INTEGER NOT NULL DEFAULT 0, track_json TEXT, "
        "raw_json TEXT NOT NULL, imported_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    con.execute(
        "insert into volanta_flight(id, source, dep_icao, arr_icao, flight_date, duration_min, "
        "raw_json, imported_at, updated_at) "
        "values('old-1','CSV','RJTT','RJAA','2026-10-12',90,'{}','2026-10-12T00:00:00Z',"
        "'2026-10-12T00:00:00Z')")
    con.commit()
    con.close()

    svc = PersonalService(paths)
    try:
        items = svc.volanta_flights()
        assert len(items) == 1, "补列不能丢历史数据"
        assert items[0]["callsign"] is None
        # 再导入一条带航班号的：新列可写
        svc.sync_volanta(csv_text="Date,Flight Number,Origin,Destination,Duration\n"
                                  "2026-10-18,NH933,RJTT,RJAA,90\n")
        rows = {r["callsign"]: r for r in svc.volanta_flights()}
        assert rows["NH933"]["dep_icao"] == "RJTT"
    finally:
        asyncio.run(svc.close())


def test_map_counts_multiple_imports(app_client):
    """同一航段导入多次时，地图线宽依据的次数应累加（不是固定 1）。"""
    rows = "".join(f"2026-10-{d:02d},RJTT,RJAA,A320\n" for d in range(12, 15))
    app_client.post("/local/volanta/sync", json={"csv_text": "Date,Origin,Destination,Aircraft\n" + rows})
    legs = {(l["dep"], l["arr"]): l for l in app_client.get("/local/map").json()["legs"]}
    assert legs[("RJTT", "RJAA")]["count"] == 3
    assert legs[("RJTT", "RJAA")]["sources"] == ["CSV"]


def test_volanta_sync_api(app_client):
    first = app_client.post("/local/volanta/sync", json={"csv_text": CSV}).json()
    assert first["legs_found"] == 2
    assert first["legs_imported"] == 2
    assert first["source"] == "CSV"

    second = app_client.post("/local/volanta/sync", json={"csv_text": CSV}).json()
    assert second["legs_imported"] == 0

    legs = app_client.get("/local/flown-legs").json()["items"]
    assert len(legs) == 2
    assert app_client.get("/local/volanta/status").json()["flown_legs"] == 2

    manual = app_client.post("/local/flown-legs", json={
        "dep_icao": "EGLL", "arr_icao": "KJFK", "source": "MANUAL",
    }).json()
    assert manual["ok"] is True
    duplicate = app_client.post("/local/flown-legs", json={
        "dep_icao": "EGLL", "arr_icao": "KJFK", "source": "MANUAL",
    }).json()
    assert duplicate["ok"] is False
