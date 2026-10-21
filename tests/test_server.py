"""M3 联机模式：账号/权限/CSRF、抽班并发、离线补传、复核、配置版本、审计。"""
from __future__ import annotations

import concurrent.futures
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aoc_server.config import Settings
from aoc_server.main import create_app

ADMIN_PASSWORD = "admin12345"


def make_settings(tmp_path: Path, *, max_failures: int = 100, seed_demo: bool = True) -> Settings:
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text("<!doctype html><div id=\"root\">admin</div>",
                                     encoding="utf-8")
    return Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'server.sqlite').as_posix()}",
        secret="test-secret-" + "x" * 40,
        admin_static_dir=dist,
        bootstrap_password=ADMIN_PASSWORD,
        seed_demo=seed_demo,
        login_max_failures=max_failures,
        login_window_seconds=300,
    )


@pytest.fixture()
def server(tmp_path: Path):
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        yield client


def admin_login(client: TestClient) -> tuple[dict[str, str], str]:
    res = client.post("/api/v1/admin/auth/login",
                      json={"username": "admin", "password": ADMIN_PASSWORD})
    assert res.status_code == 200, res.text
    data = res.json()
    return {"X-CSRF-Token": data["csrf_token"]}, data["csrf_token"]


def create_user(client: TestClient, headers: dict[str, str], username: str,
                password: str = "pilot12345", role: str = "PILOT") -> None:
    res = client.post("/api/v1/admin/users", headers=headers, json={
        "username": username, "password": password, "role": role,
        "display_name": username.title()})
    assert res.status_code == 200, res.text


def pilot_login(client: TestClient, username: str, password: str = "pilot12345") -> dict[str, str]:
    res = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def scheduled_flights(client: TestClient, headers: dict[str, str], limit: int = 10) -> list[dict]:
    res = client.get("/api/v1/flights", params={"status": "SCHEDULED", "limit": limit},
                     headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def draw(client: TestClient, headers: dict[str, str], flight_id: str,
         aircraft_id: str | None = None, key: str | None = None) -> dict:
    body = {"flight_ids": [flight_id], "max_legs": 1}
    if aircraft_id:
        body["aircraft_id"] = aircraft_id
    extra = {"Idempotency-Key": key} if key else {}
    res = client.post("/api/v1/roster/draw", headers={**headers, **extra}, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def ready_flight(client: TestClient, headers: dict[str, str]) -> dict:
    flights = scheduled_flights(client, headers)
    assert flights
    roster = draw(client, headers, flights[0]["id"])
    leg = roster["legs"][0]
    assert client.post(f"/api/v1/flights/{leg['id']}/start", headers=headers).status_code == 200
    return leg


def land(client: TestClient, headers: dict[str, str], leg: dict, **extra) -> dict:
    body = {
        "actual_dep_utc": leg["scheduled_dep_utc"],
        "actual_arr_utc": leg["scheduled_arr_utc"],
        "fuel_used_kg": 3000,
        "landing": {"vs_fpm": -160, "g_force": 1.35, "runway": "18L"},
        **extra,
    }
    res = client.post(f"/api/v1/flights/{leg['id']}/landing", headers=headers, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_health_meta_and_admin_spa(server: TestClient) -> None:
    assert server.get("/health").json()["api_version"] == "v1"
    meta = server.get("/api/v1/meta").json()
    assert "outbox" in meta["features"]
    page = server.get("/admin/economy")
    assert page.status_code == 200 and "root" in page.text
    res = server.get("/api/v1/admin/economy")
    assert res.status_code == 401
    assert res.headers["content-type"].startswith("application/json")


def test_admin_read_endpoints_are_json(server: TestClient) -> None:
    headers, _ = admin_login(server)
    paths = [
        "/api/v1/admin/overview", "/api/v1/admin/company", "/api/v1/admin/economy",
        "/api/v1/admin/policy", "/api/v1/admin/schema", "/api/v1/admin/fleet/types",
        "/api/v1/admin/fleet/aircraft", "/api/v1/admin/network/routes",
        "/api/v1/admin/network/schedules", "/api/v1/admin/network/flights",
        "/api/v1/admin/network/airports", "/api/v1/admin/network/waypoints",
        "/api/v1/admin/ops/flights", "/api/v1/admin/ops/review",
        "/api/v1/admin/ops/locks", "/api/v1/admin/users", "/api/v1/admin/invites",
        "/api/v1/admin/audit", "/api/v1/admin/system",
    ]
    for path in paths:
        res = server.get(path, headers=headers)
        assert res.status_code == 200, (path, res.text)
        assert res.headers["content-type"].startswith("application/json"), path
    csv_res = server.get("/api/v1/admin/audit?format=csv", headers=headers)
    assert csv_res.status_code == 200
    assert csv_res.headers["content-type"].startswith("text/csv")
    # 兼容 03/06 文档中的旧路径
    assert server.get("/api/v1/admin/settings/schema", headers=headers).status_code == 200
    resolved = server.post("/api/v1/admin/settings/settlement-policy/resolve", headers=headers,
                           json={"pilot": {"id": "p1", "username": "pilot"},
                                 "anomalies": [{"kind": "DATA_GAP", "units": 1.2, "value": 12}]})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["evaluation"]["payout_factor"] == pytest.approx(0.94)


def test_admin_csrf_and_pilot_role(server: TestClient) -> None:
    headers, _ = admin_login(server)
    no_csrf = server.post("/api/v1/admin/users", json={
        "username": "nocsrf", "password": "pilot12345"})
    assert no_csrf.status_code == 403
    assert no_csrf.json()["error"]["code"] == "CSRF_INVALID"
    create_user(server, headers, "pilot")
    pilot = pilot_login(server, "pilot")
    server.cookies.clear()
    assert server.get("/api/v1/admin/overview", headers=pilot).status_code == 401
    res = server.post("/api/v1/admin/auth/login",
                      json={"username": "pilot", "password": "pilot12345"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "ADMIN_REQUIRED"


def test_login_rate_limit(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, max_failures=2))
    with TestClient(app) as client:
        for _ in range(2):
            assert client.post("/api/v1/admin/auth/login",
                               json={"username": "admin", "password": "bad"}).status_code == 401
        res = client.post("/api/v1/admin/auth/login",
                          json={"username": "admin", "password": ADMIN_PASSWORD})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "LOGIN_RATE_LIMITED"


def test_draw_idempotent_and_settlement_reconciliation(server: TestClient) -> None:
    admin_headers, _ = admin_login(server)
    create_user(server, admin_headers, "pilot")
    pilot = pilot_login(server, "pilot")
    flights = scheduled_flights(server, pilot)
    roster = draw(server, pilot, flights[0]["id"], key="draw-once")
    repeat = draw(server, pilot, flights[0]["id"], key="draw-once")
    assert repeat["id"] == roster["id"]
    leg = roster["legs"][0]
    sheet = server.get(f"/api/v1/flights/{leg['id']}/loadsheet", headers=pilot).json()["loadsheet"]
    assert sheet["pax_total"] > 0
    assert server.post(f"/api/v1/flights/{leg['id']}/start", headers=pilot).status_code == 200
    track = server.post(f"/api/v1/flights/{leg['id']}/track", headers=pilot,
                        json={"chunks": [{"seq": 1, "points": [{"lat": 40, "lon": 116}]}]})
    assert track.status_code == 200
    result = land(server, pilot, leg)
    settlement = result["settlement"]
    assert settlement["status"] == "SETTLED"
    ledger = server.get("/api/v1/ledger", headers=pilot).json()
    credits = sum(e["amount"] for e in ledger["entries"] if e["direction"] == "CREDIT")
    debits = sum(e["amount"] for e in ledger["entries"] if e["direction"] == "DEBIT")
    assert ledger["balance"] == pytest.approx(5_000_000 + credits - debits, abs=0.02)
    assert server.get("/api/v1/roster/current", headers=pilot).json()["roster"] is None
    # 同一航班不能再抽
    again = server.post("/api/v1/roster/draw", headers=pilot,
                        json={"flight_ids": [flights[0]["id"]]})
    assert again.status_code == 409


def test_concurrent_draws_only_one_winner(server: TestClient) -> None:
    admin_headers, _ = admin_login(server)
    for name in ("pilot_a", "pilot_b"):
        create_user(server, admin_headers, name)
    a = pilot_login(server, "pilot_a")
    b = pilot_login(server, "pilot_b")
    flights = scheduled_flights(server, a, limit=4)
    aircraft_id = server.get("/api/v1/aircraft", headers=a).json()[0]["id"]
    leg_a = flights[0]["id"]
    leg_b = next(f["id"] for f in flights if f["id"] != leg_a and f["dep_icao"] == "ZBAA")

    def attempt(headers: dict[str, str], flight_id: str) -> int:
        return server.post("/api/v1/roster/draw", headers=headers,
                           json={"flight_ids": [flight_id], "max_legs": 1,
                                 "aircraft_id": aircraft_id}).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda args: attempt(*args), [(a, leg_a), (b, leg_b)]))
    assert sorted(results) == [200, 409]
    locks = server.get("/api/v1/admin/ops/locks", headers=admin_headers).json()
    assert len(locks) == 1


def test_offline_batch_outbox_is_idempotent(server: TestClient) -> None:
    admin_headers, _ = admin_login(server)
    create_user(server, admin_headers, "pilot")
    pilot = pilot_login(server, "pilot")
    leg = ready_flight(server, pilot)
    landing = {
        "flight_id": leg["id"], "type": "LANDING",
        "actual_dep_utc": leg["scheduled_dep_utc"],
        "actual_arr_utc": leg["scheduled_arr_utc"], "fuel_used_kg": 2800,
    }
    items = [
        {"id": "start-1", "type": "START", "payload": {"flight_id": leg["id"]}},
        {"id": "track-1", "type": "TRACK",
         "payload": {"flight_id": leg["id"], "chunks": [{"seq": 1, "points": [{"lat": 40}]}]}},
        {"id": "track-2", "type": "TRACK",
         "payload": {"flight_id": leg["id"], "chunks": [{"seq": 1, "points": [{"lat": 40}]}]}},
        {"id": "land-1", "type": "LANDING", "payload": landing},
        {"id": "land-1", "type": "LANDING", "payload": landing},
    ]
    first = server.post("/api/v1/sync/batch", headers=pilot, json={"items": items})
    assert first.status_code == 200, first.text
    results = first.json()["results"]
    assert [r["status"] for r in results] == ["ok", "ok", "ok", "ok", "duplicate"]
    assert results[2]["result"]["duplicates"] == 1
    settlements = server.get("/api/v1/settlements", headers=pilot).json()
    assert len(settlements) == 1
    sync = server.get("/api/v1/sync", headers=pilot, params={"cursor": 0}).json()
    assert sync["events"] and sync["cursor"] > 0
    tail = server.get("/api/v1/sync", headers=pilot,
                      params={"cursor": sync["cursor"]}).json()
    assert tail["events"] == []


def test_held_review_weighted(server: TestClient) -> None:
    admin_headers, csrf = admin_login(server)
    create_user(server, admin_headers, "pilot")
    pilot = pilot_login(server, "pilot")
    leg = ready_flight(server, pilot)
    result = land(server, pilot, leg, anomaly_flags=["FUEL_JUMP"])
    settlement = result["settlement"]
    assert settlement["status"] == "HELD"
    queue = server.get("/api/v1/admin/ops/review", headers=admin_headers).json()
    assert [item["id"] for item in queue] == [settlement["id"]]
    res = server.post(f"/api/v1/admin/ops/review/{settlement['id']}", headers=admin_headers,
                      json={"action": "WEIGHTED", "factor": 0.85, "reason": "油量跳变已人工确认"})
    assert res.status_code == 200, res.text
    reviewed = res.json()
    assert reviewed["status"] == "SETTLED" and reviewed["factor"] == 0.85
    assert reviewed["action"] == "WEIGHTED"
    audits = server.get("/api/v1/admin/audit", headers=admin_headers,
                        params={"action": "SETTLEMENT_REVIEW"}).json()
    assert audits and audits[0]["reason"]


def test_reject_with_cost_mode_none_yields_void(server: TestClient) -> None:
    admin_headers, _ = admin_login(server)
    create_user(server, admin_headers, "pilot")
    policy = server.get("/api/v1/admin/policy", headers=admin_headers).json()
    payload = dict(policy["payload"])
    payload["reject_cost_mode"] = "NONE"
    res = server.put("/api/v1/admin/policy", headers=admin_headers,
                     json={"version": policy["version"], "payload": payload,
                           "reason": "瞬移不承担成本"})
    assert res.status_code == 200, res.text
    pilot = pilot_login(server, "pilot")
    leg = ready_flight(server, pilot)
    settlement = land(server, pilot, leg, anomaly_flags=["TELEPORT"])["settlement"]
    assert settlement["status"] == "VOID"
    assert settlement["factor"] == 0 and settlement["profit"] == 0
    ledger = server.get("/api/v1/ledger", headers=pilot).json()
    assert ledger["entries"] == []


def test_config_version_conflict_and_rollback(server: TestClient) -> None:
    admin_headers, _ = admin_login(server)
    current = server.get("/api/v1/admin/economy", headers=admin_headers).json()
    payload = dict(current["payload"])
    payload["fuel_price"] = 1.10
    first = server.put("/api/v1/admin/economy", headers=admin_headers,
                       json={"version": current["version"], "payload": payload,
                             "reason": "油价上涨"})
    assert first.status_code == 200, first.text
    assert first.json()["version"] == current["version"] + 1
    stale = server.put("/api/v1/admin/economy", headers=admin_headers,
                       json={"version": current["version"], "payload": payload})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CONFIG_VERSION_CONFLICT"
    rollback = server.post("/api/v1/admin/economy/rollback", headers=admin_headers,
                           json={"version": first.json()["version"],
                                 "target_version": current["version"], "reason": "回滚"})
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["payload"]["fuel_price"] == current["payload"]["fuel_price"]
    versions = server.get("/api/v1/admin/economy/versions",
                          headers=admin_headers).json()
    assert [v["version"] for v in versions[:2]] == [rollback.json()["version"],
                                                    first.json()["version"]]
    bad = server.put("/api/v1/admin/economy", headers=admin_headers,
                     json={"version": rollback.json()["version"],
                           "payload": {**payload, "fuel_price": -1}})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "CONFIG_INVALID"


def test_password_reset_revokes_refresh_and_old_password(server: TestClient) -> None:
    headers, _ = admin_login(server)
    create_user(server, headers, "pilot")
    login = server.post("/api/v1/auth/login",
                        json={"username": "pilot", "password": "pilot12345"}).json()
    user = next(row for row in server.get("/api/v1/admin/users", headers=headers).json()
                if row["username"] == "pilot")
    res = server.post(f"/api/v1/admin/users/{user['id']}/reset-password", headers=headers,
                      json={"password": "newpass12345"})
    assert res.status_code == 200
    stale = server.post("/api/v1/auth/refresh",
                        json={"refresh_token": login["refresh_token"]})
    assert stale.status_code == 401
    assert server.post("/api/v1/auth/login", json={
        "username": "pilot", "password": "pilot12345"}).status_code == 401
    assert server.post("/api/v1/auth/login", json={
        "username": "pilot", "password": "newpass12345"}).status_code == 200


def test_concurrent_publish_only_one_commits(server: TestClient) -> None:
    headers, _ = admin_login(server)
    current = server.get("/api/v1/admin/economy", headers=headers).json()
    payloads = [{**current["payload"], "fuel_price": 1.08},
                {**current["payload"], "fuel_price": 1.12}]

    def publish(item: dict) -> int:
        return server.put("/api/v1/admin/economy", headers=headers, json={
            "version": current["version"], "payload": item, "reason": "并发发布测试"}).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, payloads))
    assert sorted(results) == [200, 409]
    latest = server.get("/api/v1/admin/economy", headers=headers).json()
    assert latest["version"] == current["version"] + 1
    assert latest["payload"]["fuel_price"] in {1.08, 1.12}


def test_dispatcher_permissions(server: TestClient) -> None:
    admin_headers, _ = admin_login(server)
    create_user(server, admin_headers, "dispatcher", role="DISPATCHER")
    res = server.post("/api/v1/admin/auth/login",
                      json={"username": "dispatcher", "password": "pilot12345"})
    assert res.status_code == 200
    headers = {"X-CSRF-Token": res.json()["csrf_token"]}
    assert server.get("/api/v1/admin/policy", headers=headers).status_code == 200
    assert server.get("/api/v1/admin/ops/review", headers=headers).status_code == 200
    assert server.get("/api/v1/admin/economy", headers=headers).status_code == 403
    assert server.post("/api/v1/admin/users", headers=headers, json={
        "username": "x", "password": "pilot12345"}).status_code == 403


def test_invite_registration_and_flight_isolation(server: TestClient) -> None:
    admin_headers, _ = admin_login(server)
    invite = server.post("/api/v1/admin/invites", headers=admin_headers,
                         json={"role": "PILOT", "max_uses": 1}).json()
    res = server.post("/api/v1/auth/register", json={
        "invite_code": invite["code"], "username": "invited", "password": "pilot12345"})
    assert res.status_code == 200, res.text
    assert server.post("/api/v1/auth/register", json={
        "invite_code": invite["code"], "username": "invited2", "password": "pilot12345"}
    ).status_code == 400
    invited = pilot_login(server, "invited")
    create_user(server, admin_headers, "other")
    other = pilot_login(server, "other")
    leg = ready_flight(server, invited)
    res = server.post(f"/api/v1/flights/{leg['id']}/start", headers=other)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "NOT_YOUR_FLIGHT"


def test_csv_import_partial_and_balance_adjust(server: TestClient) -> None:
    headers, _ = admin_login(server)
    csv_text = (
        "flight_number,dep,arr,dep_local,days\n"
        "IMP101,ZBAA,ZSSS,07:00,0,1,2\n"
        "IMP102,ZBAA,ZUUU,08:00,0,1\n"
        "IMP103,ZBAA,ZSSS,25:00,0\n"
    )
    res = server.post("/api/v1/admin/network/schedules/import", headers=headers,
                      json={"csv": csv_text})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["imported"] == 2
    assert data["errors"][0]["line"] == 4
    before = server.get("/api/v1/admin/company", headers=headers).json()["balance"]
    assert server.post("/api/v1/admin/company/balance", headers=headers,
                       json={"amount": -1000}).status_code == 400
    res = server.post("/api/v1/admin/company/balance", headers=headers,
                      json={"amount": -1000, "reason": "测试调整"})
    assert res.status_code == 200
    assert res.json()["balance"] == pytest.approx(before - 1000)
    audits = server.get("/api/v1/admin/audit", headers=headers,
                        params={"action": "BALANCE_ADJUST"}).json()
    assert audits[0]["reason"] == "测试调整"


def test_pilot_policy_override_only_affects_that_pilot(server: TestClient) -> None:
    admin_headers, _ = admin_login(server)
    create_user(server, admin_headers, "vip_pilot")
    create_user(server, admin_headers, "normal_pilot")
    users = {row["username"]: row for row in
             server.get("/api/v1/admin/users", headers=admin_headers).json()}
    policy = server.get("/api/v1/admin/policy", headers=admin_headers).json()
    payload = dict(policy["payload"])
    payload["scope_mode"] = "ALLOW_OVERRIDES"
    payload["overrides"] = [{
        "scope_type": "PILOT", "scope_id": users["vip_pilot"]["id"],
        "policy": {"rules": {"DATA_GAP": {"enabled": True, "action": "ACCEPT"}}},
    }]
    res = server.put("/api/v1/admin/policy", headers=admin_headers,
                     json={"version": policy["version"], "payload": payload,
                           "reason": "VIP 飞行员数据缺口豁免"})
    assert res.status_code == 200, res.text
    vip = pilot_login(server, "vip_pilot")
    normal = pilot_login(server, "normal_pilot")
    vip_leg = ready_flight(server, vip)
    normal_leg = ready_flight(server, normal)
    vip_result = land(server, vip, vip_leg, data_gap_seconds=720)
    normal_result = land(server, normal, normal_leg, data_gap_seconds=720)
    assert vip_result["settlement"]["action"] == "ACCEPT"
    assert vip_result["settlement"]["factor"] == 1.0
    assert normal_result["settlement"]["action"] == "WEIGHTED"
    assert normal_result["settlement"]["factor"] == pytest.approx(0.94)


def test_published_fuel_price_applies_to_next_flight(server: TestClient) -> None:
    admin_headers, _ = admin_login(server)
    create_user(server, admin_headers, "pilot")
    current = server.get("/api/v1/admin/economy", headers=admin_headers).json()
    payload = dict(current["payload"])
    payload["fuel_price"] = 1.10
    res = server.put("/api/v1/admin/economy", headers=admin_headers,
                     json={"version": current["version"], "payload": payload,
                           "reason": "油价调整"})
    assert res.status_code == 200, res.text
    pilot = pilot_login(server, "pilot")
    leg = ready_flight(server, pilot)
    settlement = land(server, pilot, leg, fuel_used_kg=3000)["settlement"]
    fuel = [item for item in settlement["cost_items"] if item["type"] == "COST_FUEL"]
    assert fuel and fuel[0]["amount"] == pytest.approx(3300)


def test_admin_created_aircraft_visible_to_player(server: TestClient) -> None:
    admin_headers, _ = admin_login(server)
    types = server.get("/api/v1/admin/fleet/types", headers=admin_headers).json()
    chosen = next(item for item in types if item["icao"] == "A320")
    res = server.post("/api/v1/admin/fleet/aircraft", headers=admin_headers, json={
        "registration": "B-9001", "type_id": chosen["id"], "base_icao": "ZBAA",
        "current_icao": "ZBAA"})
    assert res.status_code == 200, res.text
    create_user(server, admin_headers, "pilot")
    pilot = pilot_login(server, "pilot")
    fleet = server.get("/api/v1/aircraft", headers=pilot).json()
    assert any(row["registration"] == "B-9001" for row in fleet)
    audits = server.get("/api/v1/admin/audit", headers=admin_headers,
                        params={"action": "AIRCRAFT_CREATE"}).json()
    assert audits and audits[0]["entity_id"] == res.json()["id"]


def test_force_release_lock_abandons_flight(server: TestClient) -> None:
    admin_headers, _ = admin_login(server)
    create_user(server, admin_headers, "pilot")
    pilot = pilot_login(server, "pilot")
    leg = ready_flight(server, pilot)
    locks = server.get("/api/v1/admin/ops/locks", headers=admin_headers).json()
    assert len(locks) == 1
    res = server.post(f"/api/v1/admin/ops/locks/{locks[0]['id']}/release", headers=admin_headers,
                      json={"reason": "机组失联"})
    assert res.status_code == 200, res.text
    assert leg["id"] in res.json()["released_flights"]
    detail = server.get(f"/api/v1/flights/{leg['id']}", headers=pilot).json()
    assert detail["flight"]["status"] == "ABANDONED"
    assert server.get("/api/v1/roster/current", headers=pilot).json()["roster"] is None
