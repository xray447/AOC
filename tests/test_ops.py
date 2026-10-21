"""M2 单机运营模式验收（A-05 ~ A-08、A-14 ~ A-19、A-27 ~ A-29）。"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest

from aoc_core.lock import InstanceLocked, SingleInstance
from aoc_core.paths import AppPaths
from aoc_core.ops.service import OpsError
from aoc_core.service import PersonalService


@pytest.fixture()
def ops(tmp_path: Path, navdata_path: Path):
    service = PersonalService(AppPaths.create(tmp_path / "home"))
    service.update_settings({"navdata_path": str(navdata_path)})
    service.ops.seed_demo()
    return service


def _draw(service: PersonalService, **constraints):
    payload = {"max_legs": 2, "max_block_minutes": 360, "min_turnaround_min": 60,
               "window_hours": 168, "prefer_new_airports": True}
    payload.update(constraints)
    return service.ops.draw(payload)


def _confirm(service: PersonalService, **constraints):
    result = _draw(service, **constraints)
    assert result["candidates"], "演示数据应能抽出候选"
    roster = service.ops.confirm_roster(result["candidates"][0]["candidate_token"], 0)
    return roster, result


def _fly(service: PersonalService, roster_id: str, sequence: int = 1, **overrides):
    started = service.ops.start_leg(roster_id, sequence)
    task = started["task"]
    leg = next(l for l in started["roster"]["legs"] if int(l["sequence"]) == sequence)
    data = {
        "id": task["flight_record_id"], "status": "COMPLETED",
        "dep_icao": leg["dep_icao"], "arr_icao": leg["arr_icao"],
        "distance_nm": 612.4, "block_minutes": 131.2, "fuel_used_kg": 5210,
        "fuel_start_kg": 9000, "fuel_end_kg": 3790,
        "scheduled_dep_utc": task.get("scheduled_dep_utc"),
        "takeoff_utc": task.get("scheduled_dep_utc"),
        "landing_utc": task.get("scheduled_dep_utc"),
        "block_off_utc": task.get("scheduled_dep_utc"),
        "block_on_utc": task.get("scheduled_dep_utc"),
        "validation_status": "VALID",
    }
    data.update(overrides)
    flight = service.db.insert_flight(data)
    settlement = service.ops.on_flight_finalized(flight)
    return flight, settlement, started


def _set_policy(service: PersonalService, note: str = "测试策略调整", **patch) -> None:
    policy = service.ops.settlement_policy()
    rules = dict(policy.get("rules") or {})
    for key, value in (patch.pop("rules", {}) or {}).items():
        rules[key] = {**rules.get(key, {}), **value}
    policy.update(patch)
    policy["rules"] = rules
    service.ops.publish_config(None, policy, note)


def _free_flight(service: PersonalService, registration: str, dep: str, arr: str):
    aircraft = next(a for a in service.ops.list_fleet() if a["registration"] == registration)
    return service.ops.create_free_flight(
        {"aircraft_id": aircraft["id"], "dep_icao": dep, "arr_icao": arr})


# ---------------------------------------------------------------- A-05 / A-06
def test_a05_draw_respects_constraints_and_locks_aircraft(ops: PersonalService):
    result = _draw(ops, max_legs=2, max_block_minutes=360, min_turnaround_min=60)
    assert 1 <= len(result["candidates"]) <= 3
    assert result["constraints"]["max_legs"] == 2
    assert result["constraints"]["min_turnaround_min"] == 60
    for candidate in result["candidates"]:
        assert 1 <= len(candidate["legs"]) <= 2
        assert candidate["total_block_minutes"] <= 360
        legs = candidate["legs"]
        for prev, nxt in zip(legs, legs[1:]):
            turnaround = (nxt["scheduled_dep_utc"], prev["scheduled_arr_utc"])
            from aoc_core.ops.economy import parse_utc
            minutes = (parse_utc(turnaround[0]) - parse_utc(turnaround[1])).total_seconds() / 60
            assert 60 <= minutes <= 360
        assert candidate["reasons"]

    roster, _ = _confirm(ops)
    aircraft = ops.ops.get_aircraft(roster["aircraft_id"])
    assert aircraft["status"] == "HELD"
    assert aircraft["locked"] is True

    # 同一架飞机不会再被抽到
    again = _draw(ops, registration=aircraft["registration"])
    assert all(c["aircraft"]["id"] != aircraft["id"] for c in again["candidates"])


def test_a06_redraw_is_free_and_releases_aircraft(ops: PersonalService):
    roster, _ = _confirm(ops)
    aircraft_id = roster["aircraft_id"]
    result = ops.ops.redraw(roster["id"])
    old = ops.ops.roster(roster["id"])
    assert old["status"] == "CANCELLED"
    assert ops.ops.get_aircraft(aircraft_id)["status"] == "ACTIVE"
    assert result["candidates"]

    # 立即再抽并确认，没有冷却/费用/次数限制
    for _ in range(3):
        again, _ = _confirm(ops)
        assert again["status"] == "LOCKED"
        ops.ops.cancel_roster(again["id"], "测试")
    ledger_before = ops.ops.ledger()
    again, _ = _confirm(ops)
    assert ops.ops.ledger()["items"] == ledger_before["items"]
    assert again["redraw_count"] == 0


# ---------------------------------------------------------------- A-07 / A-08
def test_a07_free_flight_rejects_aircraft_elsewhere(ops: PersonalService):
    aircraft = next(a for a in ops.ops.list_fleet() if a["registration"] == "B-1671")
    assert aircraft["current_airport_icao"] == "ZBAA"
    with pytest.raises(OpsError) as exc:
        ops.ops.create_free_flight({"aircraft_id": aircraft["id"], "dep_icao": "ZSSS", "arr_icao": "ZBAA"})
    assert exc.value.code == "AIRCRAFT_NOT_AT_DEPARTURE"
    assert "需调机" in exc.value.message


def test_a08_complete_ops_flight_settles_ledger(ops: PersonalService):
    balance_before = ops.ops.profile()["balance"]
    roster, _ = _confirm(ops)
    flight, settlement, started = _fly(ops, roster["id"])

    load = ops.ops.load_sheet(flight["id"])
    assert load and load["pax_total"] > 0
    assert settlement["status"] == "SETTLED"
    assert settlement["policy_action"] == "ACCEPT"
    cost_types = {item["type"] for item in settlement["breakdown"]["costs"]}
    assert len(cost_types) >= 6
    assert {"COST_FUEL", "COST_LANDING", "COST_HANDLING", "COST_CREW",
            "COST_MAINTENANCE", "COST_LEASE", "COST_ATC", "COST_INSURANCE"} <= cost_types

    ledger = ops.ops.ledger()
    assert ledger["reconciled"] is True
    assert ledger["balance"] == pytest.approx(balance_before + settlement["profit"], abs=0.05)
    assert ops.ops.settlement_for_flight(flight["id"])["id"] == settlement["id"]

    aircraft = ops.ops.get_aircraft(roster["aircraft_id"])
    assert aircraft["current_airport_icao"] == flight["arr_icao"]
    assert aircraft["status"] == "ACTIVE"
    roster_after = ops.ops.roster(roster["id"])
    assert roster_after["legs"][0]["status"] == "COMPLETED"
    assert ops.ops.active_task() is None


# ---------------------------------------------------------------- A-14 ~ A-19
def test_a14_default_data_gap_weighted_factor(ops: PersonalService):
    roster, _ = _confirm(ops)
    _, settlement, _ = _fly(ops, roster["id"], data_gap_seconds=720, anomaly_flags=["DATA_GAP"])
    assert settlement["policy_action"] == "WEIGHTED"
    assert settlement["payout_factor"] == pytest.approx(0.94, abs=1e-6)
    assert settlement["status"] == "SETTLED"
    detail = settlement["policy_breakdown"]
    assert any(item["kind"] == "DATA_GAP" for item in detail["breakdown"])
    types = [entry["entry_type"] for entry in settlement["ledger"]]
    assert "POLICY_ADJUSTMENT" in types
    assert settlement["revenue_total"] == pytest.approx(
        settlement["revenue_gross"] * 0.94, abs=0.05)


def test_a15_teleport_rejected_with_full_costs(ops: PersonalService):
    roster, _ = _confirm(ops)
    flight, settlement, _ = _fly(ops, roster["id"], anomaly_flags=["TELEPORT"], arr_icao="ZPPP")
    assert settlement["policy_action"] == "REJECT"
    assert settlement["payout_factor"] == 0
    assert settlement["revenue_total"] == 0
    assert settlement["cost_total"] > 0
    types = {item["type"] for item in settlement["breakdown"]["costs"]}
    assert "COST_LEASE" in types and "COST_CREW" in types
    # 飞机位置按实际落地更新（不是计划到达）
    assert ops.ops.get_aircraft(roster["aircraft_id"])["current_airport_icao"] == "ZPPP"
    assert not any(entry["entry_type"].startswith("REVENUE") for entry in settlement["ledger"])


def test_a16_review_holds_then_settles(ops: PersonalService):
    _set_policy(ops, "数据缺口改为复核", rules={"DATA_GAP": {"action": "REVIEW"}})
    roster, _ = _confirm(ops)
    hours_before = ops.ops.get_aircraft(roster["aircraft_id"])["total_hours"]
    flight, settlement, _ = _fly(ops, roster["id"], data_gap_seconds=720, anomaly_flags=["DATA_GAP"])
    assert settlement["status"] == "HELD"
    hours_held = ops.ops.get_aircraft(roster["aircraft_id"])["total_hours"]
    assert hours_held > hours_before
    assert settlement["review_status"] == "PENDING"
    assert settlement["ledger"] == []
    assert any(item["id"] == settlement["id"] for item in ops.ops.review_queue())

    resolved = ops.ops.resolve_review(settlement["id"], "ACCEPT", "人工确认")
    assert resolved["status"] == "SETTLED"
    assert resolved["payout_factor"] == pytest.approx(1.0)
    assert resolved["ledger"]
    assert ops.ops.review_queue() == []
    assert ops.ops.ledger()["reconciled"] is True
    # 复核不应再次累计飞机小时/循环
    assert ops.ops.get_aircraft(roster["aircraft_id"])["total_hours"] == pytest.approx(hours_held)


def test_a17_policy_change_applies_to_next_flight_only(ops: PersonalService):
    roster1, _ = _confirm(ops)
    _, first, _ = _fly(ops, roster1["id"], data_gap_seconds=720, anomaly_flags=["DATA_GAP"])
    assert first["payout_factor"] == pytest.approx(0.94)

    _set_policy(ops, "数据缺口改为拒绝", rules={"DATA_GAP": {"action": "REJECT"}})
    roster2, _ = _confirm(ops)
    _, second, _ = _fly(ops, roster2["id"], data_gap_seconds=720, anomaly_flags=["DATA_GAP"])
    assert second["policy_action"] == "REJECT"
    assert second["payout_factor"] == 0
    # 历史结算不变
    assert ops.ops.settlement(first["id"])["payout_factor"] == pytest.approx(0.94)

    audit = ops.ops.audit_log(20)
    publishes = [row for row in audit
                 if row["action"] == "CONFIG_PUBLISH" and row["entity_id"] == "settlement_policy"]
    assert publishes
    policy_audit = publishes[0]
    assert policy_audit["before"]["rules"]["DATA_GAP"]["action"] == "WEIGHTED"
    assert policy_audit["after"]["rules"]["DATA_GAP"]["action"] == "REJECT"
    assert policy_audit["reason"] == "数据缺口改为拒绝"


def test_a18_reject_cost_mode_none_voids(ops: PersonalService):
    _set_policy(ops, "拒绝时不再扣成本", reject_cost_mode="NONE")
    roster, _ = _confirm(ops)
    _, settlement, _ = _fly(ops, roster["id"], anomaly_flags=["TELEPORT"])
    assert settlement["status"] == "VOID"
    assert settlement["revenue_total"] == 0
    assert settlement["cost_total"] == 0
    assert settlement["ledger"] == []
    assert settlement["breakdown"]["costs"] == []


def test_a19_review_advance_and_adjustment(ops: PersonalService):
    _set_policy(ops, "复核预付 30%", review_advance_ratio=0.3,
                rules={"DATA_GAP": {"action": "REVIEW"}})
    roster, _ = _confirm(ops)
    _, settlement, _ = _fly(ops, roster["id"], data_gap_seconds=720, anomaly_flags=["DATA_GAP"])
    assert settlement["status"] == "HELD"
    assert settlement["advance_amount"] > 0
    types = [entry["entry_type"] for entry in settlement["ledger"]]
    assert "ADVANCE_PAYOUT" in types

    resolved = ops.ops.resolve_review(settlement["id"], "ACCEPT", "复核通过")
    types = [entry["entry_type"] for entry in resolved["ledger"]]
    assert "ADVANCE_PAYOUT" in types
    assert "REVENUE_ADJUSTMENT" in types or "ADVANCE_CLAWBACK" in types
    net = sum(entry["amount"] for entry in resolved["ledger"])
    assert net == pytest.approx(resolved["profit"], abs=0.05)
    assert ops.ops.ledger()["reconciled"] is True


# ---------------------------------------------------------------- A-27 ~ A-29
def test_a27_in_progress_roster_never_expires(ops: PersonalService):
    roster, _ = _confirm(ops)
    assert len(roster["legs"]) == 2
    _, first, _ = _fly(ops, roster["id"], 1)
    assert first["status"] == "SETTLED"
    ops.ops._one("select 1")  # 保持连接
    with ops.ops._tx() as con:
        con.execute("update roster set expires_at='2020-01-01T00:00:00Z', "
                    "window_end_utc='2020-01-01T00:00:00Z' where id=?", (roster["id"],))
    ops.ops._expire_locks()
    current = ops.ops.roster(roster["id"])
    assert current["status"] == "IN_PROGRESS"
    assert current["legs"][0]["status"] == "COMPLETED"

    second_started = ops.ops.start_leg(roster["id"], 2)
    assert second_started["task"]["roster_leg_id"] == current["legs"][1]["id"]
    flight = ops.db.insert_flight({
        "id": second_started["task"]["flight_record_id"], "status": "COMPLETED",
        "dep_icao": current["legs"][1]["dep_icao"], "arr_icao": current["legs"][1]["arr_icao"],
        "distance_nm": 612.4, "block_minutes": 131.2, "fuel_used_kg": 5210,
        "block_on_utc": second_started["task"].get("scheduled_dep_utc"),
        "validation_status": "VALID"})
    ops.ops.on_flight_finalized(flight)
    assert ops.ops.roster(roster["id"])["status"] == "COMPLETED"


def test_a28_cancel_in_progress_roster(ops: PersonalService):
    roster, _ = _confirm(ops)
    no_show_before = ops.ops.profile()["no_show_count"]
    _, first, _ = _fly(ops, roster["id"], 1)
    aircraft_airport = ops.ops.get_aircraft(roster["aircraft_id"])["current_airport_icao"]
    assert aircraft_airport == roster["legs"][0]["arr_icao"]

    cancelled = ops.ops.cancel_roster(roster["id"], "临时有事")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["legs"][0]["status"] == "COMPLETED"
    assert cancelled["legs"][1]["status"] == "CANCELLED"
    assert ops.ops.get_aircraft(roster["aircraft_id"])["current_airport_icao"] == aircraft_airport
    assert ops.ops.profile()["no_show_count"] == no_show_before
    assert ops.ops.settlement(first["id"])["status"] == "SETTLED"
    types = [entry["entry_type"] for entry in ops.ops.ledger()["items"]]
    assert "PENALTY_CANCEL" in types


def test_a29_bizjet_charter(ops: PersonalService):
    bizjet = next(t for t in ops.ops.list_types() if t["icao"] == "A343" and t["variant"] == "BIZJET")
    assert bizjet["allow_scheduled"] is False
    assert bizjet["pax_capacity"] == 36
    assert bizjet["cabin_config_json"]["first"] == 12
    assert bizjet["cabin_config_json"]["business"] == 24
    assert bizjet["cabin_config_json"]["economy"] == 0

    # allow_scheduled=false：普通抽班抽不到
    result = _draw(ops, aircraft_type_id=bizjet["id"], max_legs=1, window_hours=168)
    assert result["candidates"] == []

    free = _free_flight(ops, "B-7788", "ZBAA", "ZSSS")
    started = ops.ops.start_free_flight(free["id"])
    load = started["load_sheet"]
    assert load["pax_total"] <= 36
    assert load["pax_economy"] == 0
    assert load["pax_first"] + load["pax_business"] == load["pax_total"]

    flight = ops.db.insert_flight({
        "id": started["task"]["flight_record_id"], "status": "COMPLETED",
        "dep_icao": "ZBAA", "arr_icao": "ZSSS", "distance_nm": 612.4,
        "block_minutes": 120, "fuel_used_kg": 12000, "validation_status": "VALID"})
    settlement = ops.ops.on_flight_finalized(flight)
    revenue_types = [item["type"] for item in settlement["breakdown"]["revenue"]]
    assert revenue_types == ["REVENUE_CHARTER"]
    charter = settlement["breakdown"]["revenue"][0]["amount"]
    expected = bizjet["charter_rate_per_hour"] * 2.0
    assert charter == pytest.approx(expected, rel=0.12)  # market_factor 0.9–1.1
    assert settlement["revenue_total"] > 0


def test_policy_overrides_by_type_and_aircraft(ops: PersonalService):
    aircraft = next(a for a in ops.ops.list_fleet() if a["type_icao"] == "A320")
    policy = ops.ops.settlement_policy()
    policy.update({
        "scope_mode": "ALLOW_OVERRIDES",
        "rules": {**policy["rules"], "DATA_GAP": {**policy["rules"]["DATA_GAP"], "action": "REVIEW"}},
        "overrides": [
            {"scope_type": "AIRCRAFT_TYPE", "scope_id": "A320",
             "policy": {"rules": {"DATA_GAP": {"action": "ACCEPT"}}}},
            {"scope_type": "AIRCRAFT", "scope_id": aircraft["id"],
             "policy": {"rules": {"DATA_GAP": {"action": "REJECT"}}}},
        ],
    })
    ops.ops.publish_config(None, policy, "覆盖测试")
    resolved = ops.ops.resolve_effective_policy(aircraft["id"])
    # 越具体优先级越高：单机 > 机型 > 公司默认
    assert resolved["policy"]["rules"]["DATA_GAP"]["action"] == "REJECT"
    assert resolved["sources"]["rules.DATA_GAP"] == "AIRCRAFT"

    other = next(a for a in ops.ops.list_fleet() if a["type_icao"] != "A320")
    other_resolved = ops.ops.resolve_effective_policy(other["id"])
    assert other_resolved["policy"]["rules"]["DATA_GAP"]["action"] == "REVIEW"
    assert other_resolved["sources"]["rules.DATA_GAP"] == "COMPANY"


# ---------------------------------------------------------------- 其它
def test_single_instance_lock(tmp_path: Path):
    path = tmp_path / "aoc.lock"
    first = SingleInstance(path)
    first.acquire()
    second = SingleInstance(path)
    with pytest.raises(InstanceLocked):
        second.acquire(retries=1)
    first.release()
    second.acquire(retries=1)
    second.release()


def test_config_version_conflict_and_rollback(ops: PersonalService):
    config = ops.ops.config()
    version = config["version"]
    economy = dict(config["economy"], fuel_price=1.10)
    published = ops.ops.publish_config(economy, None, "燃油价 1.05→1.10", expected_version=version)
    assert published["version"] == version + 1
    assert published["economy"]["fuel_price"] == pytest.approx(1.10)

    with pytest.raises(OpsError) as exc:
        ops.ops.publish_config(dict(economy, fuel_price=1.20), None, "并发发布", expected_version=version)
    assert exc.value.code == "CONFIG_VERSION_CONFLICT"

    rolled = ops.ops.rollback_config(version, "回滚测试")
    assert rolled["economy"]["fuel_price"] == pytest.approx(1.05)
    assert rolled["version"] == version + 2
    preview = ops.ops.preview_config(None, None, ["DATA_GAP"])
    assert preview["economy"]["samples"] == 100
    assert 0 <= preview["policy"]["payout_factor"] <= 1


def test_api_ops_endpoints(app_client):
    client = app_client
    assert client.get("/local/ops/dashboard").status_code == 200
    assert client.post("/local/ops/seed").status_code == 200
    fleet = client.get("/local/ops/fleet").json()["items"]
    assert fleet
    draw = client.post("/local/ops/rosters/draw", json={"max_legs": 1, "window_hours": 168}).json()
    assert draw["candidates"]
    confirm = client.post("/local/ops/rosters/confirm", json={
        "candidate_token": draw["candidates"][0]["candidate_token"], "candidate_index": 0})
    assert confirm.status_code == 200
    roster = confirm.json()
    assert roster["status"] == "LOCKED"
    assert client.get("/local/ops/rosters/current").json()["id"] == roster["id"]

    fleet = client.get("/local/ops/fleet").json()["items"]
    free_aircraft = next(a for a in fleet
                         if a["status"] == "ACTIVE" and a["current_airport_icao"] == "ZBAA")
    bad = client.post("/local/ops/free-flights", json={
        "aircraft_id": free_aircraft["id"], "dep_icao": "ZSSS", "arr_icao": "ZBAA"})
    assert bad.status_code == 422
    assert bad.json()["code"] == "AIRCRAFT_NOT_AT_DEPARTURE"

    config = client.get("/local/ops/config").json()
    assert config["param_schema"]
    ledger = client.get("/local/ops/ledger").json()
    assert ledger["reconciled"] is True
    assert client.get("/local/ops/audit").json()["items"]


def test_expire_locked_roster_charges_no_show(ops: PersonalService):
    roster, _ = _confirm(ops)
    balance_before = ops.ops.profile()["balance"]
    with ops.ops._tx() as con:
        con.execute("update roster set expires_at=? where id=?",
                    ((_now := __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc) - timedelta(hours=1)
                      ).isoformat(timespec="seconds").replace("+00:00", "Z"), roster["id"]))
    ops.ops._expire_locks()
    expired = ops.ops.roster(roster["id"])
    assert expired["status"] == "EXPIRED"
    assert ops.ops.profile()["no_show_count"] == 1
    ledger = ops.ops.ledger()
    assert any(item["entry_type"] == "PENALTY_NO_SHOW" for item in ledger["items"])
    assert ledger["balance"] == pytest.approx(balance_before - 5000, abs=0.05)
    assert ops.ops.get_aircraft(roster["aircraft_id"])["status"] == "ACTIVE"


def test_callsign_prefixes_are_configurable(ops: PersonalService):
    """自由飞呼号前缀与抽班航班号前缀都能改，改完立刻生效。"""
    profile = ops.ops.profile()
    assert profile["callsign_prefix"] == "AUV"
    assert profile["flight_prefix"] == "AOC"

    free = _free_flight(ops, "B-1672", "ZBAA", "ZSSS")
    assert free["callsign"].startswith("AUV")

    roster, _ = _confirm(ops)
    leg = next(l for l in roster["legs"] if l["status"] == "PLANNED")
    assert leg["callsign"].startswith("AOC")

    updated = ops.ops.update_profile({"callsign_prefix": "xyz", "flight_prefix": "au"})
    assert updated["callsign_prefix"] == "XYZ"
    assert updated["flight_prefix"] == "AU"
    assert all(s["flight_number"].startswith("AU") for s in ops.ops.list_schedules())
    again = ops.ops.roster(roster["id"])
    assert all(l["callsign"].startswith("AU") for l in again["legs"] if l["callsign"])
    assert ops.ops.free_flight(free["id"])["callsign"].startswith("XYZ")
    started = ops.ops.start_leg(roster["id"], 1)
    assert started["task"]["callsign"].startswith("AU")


def test_ops_status_reports_idle_ground_and_flight(ops: PersonalService, monkeypatch):
    """顶部状态条：空闲 → 地面等待 → 飞行中。"""
    assert ops.ops_status()["state"] == "IDLE"
    roster, _ = _confirm(ops)
    assert ops.ops_status()["state"] == "GROUND"
    ops.ops.start_leg(roster["id"], 1)
    assert ops.ops_status()["state"] == "GROUND"

    class _Rec:
        active = True
        phase = "CRUISE"

    monkeypatch.setattr(ops.flights, "status", lambda: _Rec())
    status = ops.ops_status()
    assert status["state"] == "FLIGHT"
    assert status["callsign"]


def test_simbrief_preview_carries_frozen_payload(ops: PersonalService):
    """SimBrief 链接带上配载，且开始前预算 == 开始后固化。"""
    roster, _ = _confirm(ops)
    preview = ops.simbrief_for_leg(roster_id=roster["id"], sequence=1)
    payload = preview["payload"]
    assert payload["pax"] > 0
    assert payload["payload_kg"] and payload["payload_kg"] > 0
    assert payload["registration"]
    url = preview["simbrief_url"]
    # 只要一个 kg 的 payload，不预填高度
    assert f"payload={int(round(payload['payload_kg']))}" in url
    assert "reg=" in url and "callsign=" in url
    assert "fl=" not in url
    for legacy in ("pax=", "cargo=", "fuel="):
        assert legacy not in url

    started = ops.ops.start_leg(roster["id"], 1)
    sheet = started["load_sheet"]
    assert payload["pax"] == sheet["pax_total"]
    expected = float(sheet["zfw_kg"]) - float(sheet["oew_kg"])
    assert payload["payload_kg"] == pytest.approx(expected, abs=0.1)

    frozen = ops.simbrief_for_leg(flight_record_id=started["task"]["flight_record_id"])
    assert f"payload={int(round(expected))}" in frozen["simbrief_url"]
    assert frozen["payload"]["registration"] == payload["registration"]
    assert "fl=" not in frozen["simbrief_url"]


def test_abort_task_releases_aircraft_and_cancels_roster(ops: PersonalService):
    """已开始的航班能一键取消：任务清空、飞机释放、班表作废，且不结算。"""
    roster, _ = _confirm(ops)
    started = ops.ops.start_leg(roster["id"], 1)
    assert ops.ops.active_task()["flight_record_id"] == started["task"]["flight_record_id"]

    result = asyncio.run(ops.abort_task("测试取消"))
    assert result["aborted"] is True
    assert ops.ops.active_task() is None
    assert ops.ops.get_aircraft(roster["aircraft_id"])["status"] == "ACTIVE"
    assert ops.ops.roster(roster["id"])["status"] == "CANCELLED"
    assert ops.ops.settlement_for_flight(started["task"]["flight_record_id"]) is None


def test_abort_recording_clears_task(ops: PersonalService):
    """录制中中止也要走运营钩子，否则任务和飞机锁会一直挂着。"""
    roster, _ = _confirm(ops)
    ops.ops.start_leg(roster["id"], 1)
    ops.flights.start()
    assert ops.recording_status()["active"] is True
    ops.flights.stop(abort=True)
    assert ops.ops.active_task() is None
    assert ops.ops.get_aircraft(roster["aircraft_id"])["status"] == "ACTIVE"


def test_finance_summary_totals_and_periods(ops: PersonalService):
    """财务只要总计 + 周期统计，不看账户余额。"""
    summary = ops.ops.finance_summary()
    assert summary["totals"]["flights"] == 0
    assert [p["key"] for p in summary["periods"]] == ["WEEK", "MONTH", "YEAR"]
    assert len(summary["monthly"]) == 6

    roster, _ = _confirm(ops)
    flight, settlement, _ = _fly(ops, roster["id"], 1)
    summary = ops.ops.finance_summary()
    settled = 1 if settlement["status"] == "SETTLED" else 0
    assert summary["totals"]["flights"] == settled
    assert summary["held"] == 1 - settled
    if settled:
        assert summary["totals"]["revenue"] == pytest.approx(
            float(settlement["revenue_total"]), abs=0.05)
        assert summary["totals"]["profit"] == pytest.approx(float(settlement["profit"]), abs=0.05)
        assert summary["periods"][1]["flights"] == 1
        assert summary["monthly"][-1]["flights"] == 1
    assert "balance" not in summary
