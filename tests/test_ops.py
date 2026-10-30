"""M2 单机运营模式验收（A-05 ~ A-08、A-14 ~ A-19、A-27 ~ A-29）。"""
from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aoc_core.lock import InstanceLocked, SingleInstance
from aoc_core.paths import AppPaths
from aoc_core.ops import service as ops_service
from aoc_core.ops.economy import parse_utc
from aoc_core.ops.service import OpsError, candidate_score
from aoc_core.service import PersonalService
from aoc_route.simbrief import split_callsign
from tests.conftest import add_airport_flags


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
    """SimBrief 链接用 ZFW（manualzfw）+ airline/fltnum，且开始前预算 == 开始后固化。"""
    roster, _ = _confirm(ops)
    preview = ops.simbrief_for_leg(roster_id=roster["id"], sequence=1)
    payload = preview["payload"]
    assert payload["pax"] > 0
    assert payload["zfw_kg"] and payload["zfw_kg"] > 0
    assert payload["registration"]
    airline, fltnum = split_callsign(payload["callsign"])
    url = preview["simbrief_url"]
    # 配载用 manualzfw（千磅，3 位小数）；呼号拆成 airline + fltnum；不预填高度
    assert f"manualzfw={payload['zfw_kg'] * 2.2046226 / 1000:.3f}" in url
    assert "reg=" in url
    assert f"airline={airline}" in url and fltnum and f"fltnum={fltnum}" in url
    assert "fl=" not in url
    for legacy in ("payload=", "callsign=", "pax=", "cargo=", "fuel="):
        assert legacy not in url

    started = ops.ops.start_leg(roster["id"], 1)
    sheet = started["load_sheet"]
    assert payload["pax"] == sheet["pax_total"]
    assert payload["zfw_kg"] == pytest.approx(float(sheet["zfw_kg"]), abs=0.1)

    frozen = ops.simbrief_for_leg(flight_record_id=started["task"]["flight_record_id"])
    assert f"manualzfw={float(sheet['zfw_kg']) * 2.2046226 / 1000:.3f}" in frozen["simbrief_url"]
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
    status = ops.recording_status()
    assert status["active"] is True
    # 记录状态只展示计时：字段存在且非负（采样点数不进 UI）
    assert status["engine_seconds"] >= 0
    assert status["flight_seconds"] >= 0
    assert status["engine_estimated"] in (True, False)
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


# ------------------------------------------------------- 自由飞出发机场（C-06）
def test_free_airports_only_lists_airports_with_available_aircraft(ops: PersonalService):
    """出发机场下拉只列有可用飞机的机场，飞机被锁走后该机场消失。"""
    items = ops.ops.free_airports()
    assert items, "演示机队应至少有一个可用机场"
    available = {(a.get("current_airport_icao") or "").upper() for a in ops.ops.free_aircraft()}
    assert {a["icao"] for a in items} == {i for i in available if i}
    assert all(a["aircraft"] >= 1 for a in items)

    target = items[0]["icao"]
    dest = "ZSSS" if target != "ZSSS" else "ZBAA"
    for aircraft in ops.ops.free_aircraft(target):
        ops.ops.create_free_flight(
            {"aircraft_id": aircraft["id"], "dep_icao": target, "arr_icao": dest})
    assert target not in {a["icao"] for a in ops.ops.free_airports()}


def test_free_flight_dep_time_defaults_to_now_plus_50min(ops: PersonalService):
    """缺省计划起飞时间 = 领取时刻 + 50min（不再是领取时刻）。"""
    free = _free_flight(ops, "B-1672", "ZBAA", "ZSSS")
    dep = parse_utc(free["dep_time_utc"])
    minutes = (dep - datetime.now(timezone.utc)).total_seconds() / 60
    assert 45 <= minutes <= 52


# ------------------------------------------------- 推出前 ZFW 校验（C-08）
def test_start_leg_warns_when_actual_zfw_below_load_sheet(ops: PersonalService):
    """实际 ZFW 低于配载单时只提示、不阻断，并把差异写进任务。"""
    roster, _ = _confirm(ops)
    started = ops.ops.start_leg(roster["id"], 1, 1000)
    sheet = started["load_sheet"]
    assert started["warnings"], "低于配载单应给出 warnings"
    assert started["task"]["actual_zfw_kg"] == pytest.approx(1000)
    assert started["task"]["zfw_delta_kg"] == pytest.approx(1000 - float(sheet["zfw_kg"]))
    assert ops.ops.get_aircraft(roster["aircraft_id"])["status"] == "IN_FLIGHT"


def test_start_free_flight_records_actual_zfw(ops: PersonalService):
    free = _free_flight(ops, "B-1672", "ZBAA", "ZSSS")
    started = ops.ops.start_free_flight(free["id"], 1000)
    assert started["warnings"]
    assert started["task"]["actual_zfw_kg"] == pytest.approx(1000)


def test_flight_status_computes_ete_from_latest_sample(ops: PersonalService, monkeypatch):
    """执行页实时状态：ETE = 剩余大圆距离 ÷ 地速；未起飞/地速 < 50kt/无采样时为 null。"""
    sample = {
        "gs_kt": 450, "ias_kt": 260, "alt_ft": 35000, "agl_ft": 34000,
        "lat": 36.0, "lon": 118.0, "vs_fpm": 0, "on_ground": False,
        "total_weight_kg": 62000, "fuel_weight_kg": 7000,
    }

    async def _sample():
        return sample

    monkeypatch.setattr(ops, "latest_sample", _sample)
    status = asyncio.run(ops.ops_flight_status())
    assert status["available"] is True
    assert status["actual_zfw_kg"] == pytest.approx(55000)
    # 没有任务时不知道该飞到哪，不猜剩余距离
    assert status["remaining_nm"] is None and status["ete_min"] is None

    roster, _ = _confirm(ops)
    ops.ops.start_leg(roster["id"], 1)
    status = asyncio.run(ops.ops_flight_status())
    assert status["remaining_nm"] > 0
    assert status["ete_min"] == pytest.approx(status["remaining_nm"] / 450 * 60, rel=0.02)
    assert status["eta_utc"]

    # 地速 < 50kt（滑行/未起飞）：ETE/ETA 为 null，界面显示「—」；剩余距离照给
    slow = {**sample, "gs_kt": 30, "on_ground": True}

    async def _slow():
        return slow

    monkeypatch.setattr(ops, "latest_sample", _slow)
    taxi = asyncio.run(ops.ops_flight_status())
    assert taxi["remaining_nm"] > 0
    assert taxi["ete_min"] is None and taxi["eta_utc"] is None

    async def _none():
        return None

    monkeypatch.setattr(ops, "latest_sample", _none)
    empty = asyncio.run(ops.ops_flight_status())
    assert empty["available"] is False
    assert empty["ete_min"] is None and empty["eta_utc"] is None


def test_recording_start_persists_actual_zfw_and_timers(ops: PersonalService):
    """记录开始时补录实际 ZFW，落进 flight_record；计时字段存在且非负。"""
    roster, _ = _confirm(ops)
    ops.ops.start_leg(roster["id"], 1)
    warnings = ops.ops.set_actual_zfw(5000)
    assert warnings
    ops.flights.start()
    status = ops.recording_status()
    assert status["active"] is True
    assert status["engine_seconds"] >= 0
    assert status["flight_seconds"] >= 0
    assert status["engine_estimated"] in (True, False)
    flight = ops.db.get_flight(status["flight_id"])
    assert flight["actual_zfw_kg"] == pytest.approx(5000)
    assert flight["zfw_delta_kg"] is not None and flight["zfw_delta_kg"] < 0


# ------------------------------------------------------- 抽班：不遵循航线/排除/每程航时
CUSTOM_TYPE = {
    "icao": "XWJ", "variant": "WIDE", "name": "Homebuilt Widebody", "manufacturer": "Homebuilt",
    "role": "AIRLINER", "pax_capacity": 300,
    "cabin_config_json": {"first": 8, "business": 42, "premium_economy": 24, "economy": 226},
    "cargo_capacity_kg": 18000,
    "oew_kg": 150000, "mzfw_kg": 200000, "mlw_kg": 210000, "mtow_kg": 280000,
    "fuel_capacity_kg": 110000, "fuel_burn_kg_h": 6000, "cruise_speed_kt": 470,
    "cruise_fl": 370, "min_runway_m": 2400, "range_nm": 6000,
    "lease_per_hour": 9000, "title_keyword": "Homebuilt Widebody",
}


def test_draw_ignores_routes_when_disabled(ops: PersonalService):
    """关掉「遵循航线」后不依赖航线/班期：用 navdata 机场库生成虚拟航段，确认后能开始。"""
    with ops.ops._tx() as con:
        con.execute("delete from schedule_template")
        con.execute("delete from flight_instance")
        con.execute("delete from ops_route")
    result = _draw(ops, follow_routes=False, max_legs=2)
    assert result["follow_routes"] is False
    assert len(result["candidates"]) == 3, "关掉航线后仍应抽出 3 个候选"
    for candidate in result["candidates"]:
        assert candidate["legs"] and all(leg["virtual"] for leg in candidate["legs"])
        assert candidate["legs"][0]["dep"]  # 首段从飞机当前位置出发
    shapes = {tuple((leg["dep"], leg["arr"]) for leg in c["legs"]) for c in result["candidates"]}
    assert len(shapes) == 3, "三个候选应是不同的机场对"

    roster = ops.ops.confirm_roster(result["candidates"][0]["candidate_token"], 0)
    assert roster["status"] == "LOCKED"
    assert all(leg["callsign"] for leg in roster["legs"])
    started = ops.ops.start_leg(roster["id"], 1)
    assert started["load_sheet"]["distance_nm"] > 0
    # 取消班表时虚拟航段作废，不再回到候选池
    ops.ops.cancel_roster(roster["id"], "测试")
    instances = ops.ops.list_instances(status="CANCELLED", days=30)
    assert any(i["mission_type"] == "FREE" for i in instances)


def test_draw_excludes_airports(ops: PersonalService):
    """排除机场：出发/到达/中转过站都不再出现（遵循航线与不遵循航线都生效）。"""
    result = _draw(ops, follow_routes=True, excluded_airports=["ZSSS"])
    assert result["excluded_airports"] == ["ZSSS"]
    assert result["candidates"]
    for candidate in result["candidates"]:
        for leg in candidate["legs"]:
            assert "ZSSS" not in (leg["dep"], leg["arr"])

    virtual = _draw(ops, follow_routes=False, excluded_airports=["zsss"])
    assert virtual["excluded_airports"] == ["ZSSS"]
    for candidate in virtual["candidates"]:
        for leg in candidate["legs"]:
            assert "ZSSS" not in (leg["dep"], leg["arr"])


def test_draw_respects_per_leg_block_range(ops: PersonalService):
    """每程航时区间：单段 block 必须落在 [min, max]，与「合计」max_block 互不影响。"""
    result = _draw(ops, follow_routes=False, min_leg_block_minutes=60,
                   max_leg_block_minutes=120, max_block_minutes=480)
    assert result["candidates"]
    for candidate in result["candidates"]:
        for leg in candidate["legs"]:
            assert 60 <= leg["block_minutes"] <= 120
    assert result["constraints"]["min_leg_block_minutes"] == 60
    assert result["constraints"]["max_leg_block_minutes"] == 120


def test_draw_min_leg_block_greater_than_max_rejected(ops: PersonalService):
    with pytest.raises(OpsError) as exc:
        _draw(ops, min_leg_block_minutes=300, max_leg_block_minutes=120)
    assert exc.value.code == "PARAM_OUT_OF_RANGE"
    assert exc.value.details.get("key") == "min_leg_block_minutes"


def test_draw_follow_routes_keeps_legacy_behaviour(ops: PersonalService):
    """默认（遵循航线）与旧行为一致：候选全部来自已有航班实例，没有虚拟航段。"""
    result = _draw(ops)
    assert result["follow_routes"] is True
    assert result["candidates"]
    for candidate in result["candidates"]:
        assert all(leg.get("virtual") is False for leg in candidate["legs"])
        assert all(leg["flight_instance_id"] for leg in candidate["legs"])
    assert result["constraints"]["excluded_airports"] == []


# ------------------------------------------------------- 自定义机型模板（P-07/P-10）
def test_custom_aircraft_type_feeds_loadsheet_and_settlement(ops: PersonalService):
    custom = ops.ops.create_type(CUSTOM_TYPE)
    assert custom["source"] == "CUSTOM" and custom["pax_capacity"] == 300
    aircraft = ops.ops.add_aircraft({"registration": "B-CST", "base_airport_icao": "ZBAA",
                                     "type_id": custom["id"]})
    assert aircraft["type_icao"] == "XWJ"

    roster, _ = _confirm(ops, registration="B-CST", aircraft_type_id=custom["id"])
    assert roster["aircraft"]["type"] == "XWJ"
    flight, settlement, started = _fly(ops, roster["id"], 1, fuel_used_kg=5200)
    sheet = started["load_sheet"]
    assert sheet["oew_kg"] == pytest.approx(CUSTOM_TYPE["oew_kg"])
    assert sheet["pax_total"] <= CUSTOM_TYPE["pax_capacity"]
    assert settlement["status"] == "SETTLED"
    fuel = next(i for i in settlement["breakdown"]["costs"] if i["type"] == "COST_FUEL")
    price = ops.ops.economy_params()["fuel_price"]
    assert fuel["amount"] == pytest.approx(round(5200 * price, 2))
    assert ops.ops.load_sheet(flight["id"])["aircraft_type_id"] == custom["id"]


def test_custom_type_rejects_invalid_weights(ops: PersonalService):
    cases = [
        ({"oew_kg": 210000}, "oew_kg"),
        ({"mzfw_kg": 300000}, "mzfw_kg"),
        ({"mlw_kg": 300000}, "mlw_kg"),
        ({"min_runway_m": 9000}, "min_runway_m"),
        ({"cruise_speed_kt": 20}, "cruise_speed_kt"),
        ({"pax_capacity": 100}, "pax_capacity"),
    ]
    for patch, key in cases:
        with pytest.raises(OpsError) as exc:
            ops.ops.create_type({**CUSTOM_TYPE, **patch})
        assert exc.value.code == "PARAM_OUT_OF_RANGE", patch
        assert exc.value.details.get("key") == key, patch


def test_delete_custom_type_blocked_when_in_fleet(ops: PersonalService):
    custom = ops.ops.create_type(CUSTOM_TYPE)
    aircraft = ops.ops.add_aircraft({"registration": "B-CST", "base_airport_icao": "ZBAA",
                                     "type_id": custom["id"]})
    with pytest.raises(OpsError) as exc:
        ops.ops.delete_type(custom["id"])
    assert exc.value.code == "AIRCRAFT_TYPE_IN_USE"
    assert exc.value.details.get("in_fleet") == 1

    with ops.ops._tx() as con:
        con.execute("delete from aircraft where id=?", (aircraft["id"],))
    assert ops.ops.delete_type(custom["id"]) is True
    assert ops.ops.get_type(custom["id"]) is None


def test_builtin_type_copy_to_custom(ops: PersonalService):
    builtin = next(t for t in ops.ops.list_types() if t["source"] == "BUILTIN")
    with pytest.raises(OpsError) as exc:
        ops.ops.update_type(builtin["id"], {"oew_kg": 1000})
    assert exc.value.code == "BUILTIN_TYPE_READONLY"
    with pytest.raises(OpsError) as exc:
        ops.ops.delete_type(builtin["id"])
    assert exc.value.code == "BUILTIN_TYPE_READONLY"

    copy = ops.ops.create_type({**builtin, "variant": "CUSTOM", "name": "Copied"})
    assert copy["source"] == "CUSTOM"
    assert (copy["icao"], copy["variant"]) == (builtin["icao"], "CUSTOM")
    # 复制出来的可以改参数
    edited = ops.ops.update_type(copy["id"], {"fuel_burn_kg_h": 2500})
    assert edited["fuel_burn_kg_h"] == pytest.approx(2500)
    # 内置的那条不受影响
    assert ops.ops.get_type(builtin["id"])["source"] == "BUILTIN"


# --------------------------------------------------------- §23 军用机场
def _flagged_ops(tmp_path: Path, navdata_path: Path, **flags) -> PersonalService:
    """带 is_military / 跑道宽度的 navdata + 演示机队（§23/§26 用例共用）。"""
    add_airport_flags(navdata_path, **flags)
    service = PersonalService(AppPaths.create(tmp_path / "home-flagged"))
    service.update_settings({"navdata_path": str(navdata_path)})
    service.ops.seed_demo()
    return service


def _standard_type(service: PersonalService, icao: str) -> dict:
    return next(t for t in service.ops.list_types()
                if t["icao"] == icao and t["variant"] == "STANDARD")


def _pool(service: PersonalService, icao: str, **constraints) -> list[str]:
    constraints.setdefault("follow_routes", False)
    cfg = service.ops._constraints(constraints)
    pool = service.ops._airport_pool("ZBAA", _standard_type(service, icao), cfg, random.Random(7))
    return [item["icao"] for item in pool]


def test_airport_pool_excludes_military_airports(tmp_path: Path, navdata_path: Path):
    """navdata 标记的军用机场不进候选；关掉开关才回来。出发机场不受影响。"""
    service = _flagged_ops(tmp_path, navdata_path, military=("ZBTJ", "ZBSJ"))
    assert service.nav.airport("ZBTJ")["military"] is True

    pool = _pool(service, "B738")
    assert pool, "民用机场应还在池里"
    assert "ZBTJ" not in pool and "ZBSJ" not in pool
    assert "ZBAA" not in pool  # 出发机场本身不重复出现

    off = _pool(service, "B738", exclude_military=False)
    assert {"ZBTJ", "ZBSJ"} & set(off), "关掉开关后旧行为应恢复"

    # 搜索接口也透出 military 标记（前端「排除军用机场」提示用）
    found = {a.icao: a for a in service.search_airports("Tianjin")}
    assert found["ZBTJ"].military is True


def test_military_falls_back_to_name_keyword(navdata_path: Path):
    """缺 is_military 列时按名称关键词判断，默认仍按民用处理。"""
    import sqlite3

    from aoc_navdata import NavData

    con = sqlite3.connect(navdata_path)
    con.execute("update airport set name='Beale Air Force Base' where ident='RJAA'")
    con.execute("update airport set name='Naval Air Station' where ident='LROP'")
    con.commit()
    con.close()
    nav = NavData(navdata_path)
    try:
        assert nav.airport("RJAA")["military"] is True
        assert nav.airport("LROP")["military"] is True
        assert nav.airport("ZSSS")["military"] is False
    finally:
        nav.close()


# --------------------------------------------------------- §26 翼展 / 跑道宽度
def test_draw_respects_runway_width_for_wingspan(tmp_path: Path, navdata_path: Path):
    """45 m 宽（148 ft）只放行 D 类（52 m）：A330 不行；60 m 放行宽体；开关关掉回旧行为。"""
    service = _flagged_ops(tmp_path, navdata_path,
                           width_ft={"ZSHC": 98.0, "ZSNJ": 148.0, "ZSPD": 197.0})
    assert service.nav.airport("ZSHC")["runway_width_m"] == pytest.approx(29.9, abs=0.1)
    assert service.nav.airport("ZSNJ")["max_wingspan_m"] == 52
    assert service.nav.airport("ZSPD")["max_wingspan_m"] == 80

    wide = _pool(service, "A333")          # 60.3 m
    assert "ZSHC" not in wide              # 30 m → 36 m 上限
    assert "ZSNJ" not in wide              # 45 m → 52 m 上限
    assert "ZSPD" in wide                  # 60 m → 80 m 上限

    narrow = _pool(service, "B738")        # 35.9 m：30 m 宽度刚好放行
    assert "ZSHC" in narrow
    assert "ZSNJ" in narrow

    long_body = _pool(service, "B752")     # 38.0 m：30 m 不行、45 m 可以
    assert "ZSHC" not in long_body
    assert "ZSNJ" in long_body

    off = _pool(service, "A333", consider_wingspan=False)
    assert {"ZSHC", "ZSNJ"} <= set(off), "关掉开关后应回到旧行为"

    # 机型替换同样要过翼展
    inst = {"dep_icao": "ZBAA", "arr_icao": "ZSNJ", "route_id": None}
    assert service.ops._can_operate(inst, _standard_type(service, "A333")) is False
    assert service.ops._can_operate(inst, _standard_type(service, "B738")) is True


def test_missing_width_column_means_no_limit(navdata_path: Path):
    """navdata 没有宽度数据时不做翼展限制（max_wingspan_m = None）。"""
    from aoc_navdata import NavData

    nav = NavData(navdata_path)
    try:
        assert nav.airport("ZSSS")["max_wingspan_m"] is None
        assert nav.max_wingspan_m("ZSSS") is None
    finally:
        nav.close()


def test_aircraft_type_wingspan_defaults_and_validation(ops: PersonalService):
    """机型模板带 wingspan_m：缺省按最短跑道推断，复制为自定义后可改。"""
    narrow = _standard_type(ops, "A320")
    assert narrow["wingspan_m"] == pytest.approx(35.8)
    custom = ops.ops.create_type({**CUSTOM_TYPE, "wingspan_m": 66.0})
    assert custom["wingspan_m"] == pytest.approx(66.0)
    with pytest.raises(OpsError) as exc:
        ops.ops.update_type(custom["id"], {"wingspan_m": 200})
    assert exc.value.code == "PARAM_OUT_OF_RANGE"
    assert exc.value.details.get("key") == "wingspan_m"

    # 留空（0）→ 按 min_runway_m 推保守值
    generated = ops.ops.create_type({k: v for k, v in CUSTOM_TYPE.items()
                                     if k not in ("icao",)} | {"icao": "XW2", "wingspan_m": 0})
    assert generated["wingspan_m"] == pytest.approx(52.0)


# --------------------------------------------------------- §24 候选多样性
def test_candidate_score_no_longer_favours_one_long_loss_leg():
    """478 min 单段亏钱航线不应压过 464 min 三段链（旧口径下的实测现象）。"""
    single = candidate_score(utilization=478 / 480, new_airports=2, profit=-56901,
                             block_minutes=[478], leg_count=1, max_legs=3,
                             random_part=0.5, prefer_new_airports=True)
    multi = candidate_score(utilization=464 / 480, new_airports=3, profit=1000,
                            block_minutes=[140, 150, 174], leg_count=3, max_legs=3,
                            random_part=0.5, prefer_new_airports=True)
    assert multi > single


def test_draw_top3_uses_distinct_aircraft_and_routes(ops: PersonalService):
    """top3 不再出现「同一架飞机 + 同一航线形状」的重复候选（遵循/不遵循航线都算）。"""
    for follow in (True, False):
        result = _draw(ops, follow_routes=follow, max_legs=2)
        candidates = result["candidates"]
        assert candidates
        aircraft_ids = [c["aircraft"]["id"] for c in candidates]
        assert len(aircraft_ids) == len(set(aircraft_ids))
        shapes = [tuple((leg["dep"], leg["arr"]) for leg in c["legs"]) for c in candidates]
        assert len(shapes) == len(set(shapes))
        if not follow:
            deps = {c["legs"][0]["scheduled_dep_utc"] for c in candidates}
            assert len(deps) >= 2, "虚拟航段的首段起飞时刻应错开"


def test_select_top_drops_same_aircraft_and_shape():
    def candidate(aircraft: str, legs: list[tuple[str, str]]) -> dict:
        return {"aircraft": {"id": aircraft},
                "legs": [{"dep": d, "arr": a} for d, a in legs]}

    items = [
        candidate("AC1", [("ZBAA", "ZSSS"), ("ZSSS", "ZBAA")]),
        candidate("AC1", [("ZBAA", "ZLXY")]),
        candidate("AC2", [("ZBAA", "ZSSS"), ("ZSSS", "ZBAA")]),
        candidate("AC3", [("ZBAA", "ZPPP")]),
        candidate("AC4", [("ZBAA", "ZGGG")]),
    ]
    top = ops_service.OpsService._select_top(items, 3)
    assert [c["aircraft"]["id"] for c in top] == ["AC1", "AC3", "AC4"]


# --------------------------------------------------------- §27/§30 自动开录/收尾
def _frame(t: float, *, gs: float = 0.0, on_ground: bool = True,
           parking_brake: bool = False) -> dict:
    return {"t": t, "lat": 31.1979, "lon": 121.3363, "gs_kt": gs,
            "on_ground": on_ground, "parking_brake": parking_brake}


def _record(tmp_path: Path, frames: list[dict]):
    from aoc_core.flights import FlightRecorder

    rec = FlightRecorder("test-flight", "2026-01-01T00:00:00Z", AppPaths.create(tmp_path / "h"))
    for seq, frame in enumerate(frames):
        rec.ingest({**frame, "seq": seq})
    return rec


def test_auto_stop_ignores_transient_low_speed_during_taxi(tmp_path: Path):
    """接地 30s 后 GS 掉到 4kt 又回升到 15kt：不该收尾（旧判据会在这里误停）。"""
    frames = [_frame(t, gs=200, on_ground=False) for t in range(0, 11)]
    frames += [_frame(11, gs=120)]
    frames += [_frame(41, gs=4)]        # 接地满 30s 的瞬时低速
    frames += [_frame(t, gs=15) for t in range(42, 61)]
    rec = _record(tmp_path, frames)
    try:
        assert rec.seen_airborne
        assert rec.should_auto_stop(True, 60) is False
    finally:
        rec.close()


def test_auto_stop_requires_continuous_stop(tmp_path: Path):
    frames = [_frame(t, gs=200, on_ground=False) for t in range(0, 11)]
    frames += [_frame(t, gs=4) for t in range(11, 90)]
    rec = _record(tmp_path, frames)
    try:
        assert rec.should_auto_stop(True, 60) is True
    finally:
        rec.close()


def test_auto_stop_parking_brake_signal(tmp_path: Path):
    frames = [_frame(t, gs=200, on_ground=False) for t in range(0, 11)]
    frames += [_frame(t, gs=12) for t in range(11, 51)]
    frames += [_frame(t, gs=0, parking_brake=True) for t in range(51, 82)]
    rec = _record(tmp_path, frames)
    try:
        assert rec.parking_brake_since == 51
        assert rec.should_auto_stop(True, 60) is True
    finally:
        rec.close()


def test_auto_stop_never_fires_in_flight(tmp_path: Path):
    frames = [_frame(t, gs=0, on_ground=False) for t in range(0, 120)]
    rec = _record(tmp_path, frames)
    try:
        assert rec.should_auto_stop(True, 60) is False
    finally:
        rec.close()


# --------------------------------------------------------- §28 机型按标题识别
def test_recording_detects_aircraft_type_from_title(ops: PersonalService):
    """无任务录制：按 SimLink 的 aircraft_title 匹配内置机型，而不是永远记 A320。"""
    from tests.conftest import make_points

    ops.update_settings({"aircraft_type": "A320"})
    ops.flights.aircraft_title = "Boeing 737-800 PMDG"
    ops.flights.start()
    flight_id = ops.flights.recorder.flight_id
    assert ops.db.get_flight(flight_id)["aircraft_type"] == "B738"

    # 事后改「默认机型」不影响这条记录（评估/统计都读建档时存的机型）
    ops.update_settings({"aircraft_type": "A359"})
    ops.flights.ingest(make_points(step=1.0), auto_ingest=False)
    flight = ops.flights.stop()
    assert flight["aircraft_type"] == "B738"
    assert flight["aircraft_title"] == "Boeing 737-800 PMDG"
    leg = ops.db.list_flown_legs()[0]
    assert leg["aircraft_type"] == "B738"


def test_recording_type_custom_keyword_wins_and_default_falls_back(ops: PersonalService):
    custom = ops.ops.create_type({
        **CUSTOM_TYPE, "icao": "XW4", "title_keyword": "BOEING 737-800 BBJ",
    })
    assert custom["source"] == "CUSTOM"
    matched = ops.ops.match_type_by_title("Boeing 737-800 BBJ Livery")
    assert matched["id"] == custom["id"], "自定义 title_keyword 更长，应优先命中"

    ops.update_settings({"aircraft_type": "A320"})
    ops.flights.aircraft_title = "Some Unknown Kit Plane"
    ops.flights.start()
    assert ops.db.get_flight(ops.flights.recorder.flight_id)["aircraft_type"] == "A320"


# --------------------------------------------------------- §25 随机航班号
class _FixedRandom:
    """替换 random.SystemRandom：按给定顺序返回 3 位数字，用于确定性断言。"""

    def __init__(self, values: list[int]):
        self.values = list(values)

    def randint(self, low: int, high: int) -> int:  # noqa: ARG002
        value = self.values.pop(0) if self.values else 137
        return max(low, min(high, value))


def test_virtual_flight_numbers_are_random_and_unique(ops: PersonalService, monkeypatch):
    monkeypatch.setattr(ops_service.random, "SystemRandom", lambda: _FixedRandom([137, 402, 137]))
    dep = "2026-11-01T08:00:00Z"
    with ops.ops._tx() as con:
        used: set[str] = set()
        first = ops.ops._virtual_flight_number(con, "OVO", dep, used)
        second = ops.ops._virtual_flight_number(con, "OVO", dep, used)
    assert (first, second) == ("OVO137", "OVO402")
    assert first != second  # 同一班表内不复用


def test_virtual_flight_number_skips_existing_and_falls_back(ops: PersonalService, monkeypatch):
    dep = "2026-11-02T08:00:00Z"
    stamp = "2026-11-02T00:00:00Z"
    with ops.ops._tx() as con:
        con.execute(
            "insert into flight_instance(id, flight_number, dep_icao, arr_icao, scheduled_dep_utc, "
            "scheduled_arr_utc, mission_type, status, created_at, updated_at) "
            "values('x1','OVO137','ZBAA','ZSSS',?,?,'FREE','SCHEDULED',?,?)",
            (dep, dep, stamp, stamp))
    monkeypatch.setattr(ops_service.random, "SystemRandom", lambda: _FixedRandom([137, 402]))
    with ops.ops._tx() as con:
        number = ops.ops._virtual_flight_number(con, "OVO", dep)
    assert number == "OVO402", "同号 + 同时刻冲突时换号"

    # 随机 50 次全撞号 + 3 位顺序号用满 → 退回带随机的号（保证唯一性）
    with ops.ops._tx() as con:
        for n in range(1, 1000):
            if n == 137:
                continue   # 上面已经插过
            con.execute(
                "insert into flight_instance(id, flight_number, dep_icao, arr_icao, scheduled_dep_utc, "
                "scheduled_arr_utc, mission_type, status, created_at, updated_at) "
                "values(?,?,'ZBAA','ZSSS',?,?,'FREE','SCHEDULED',?,?)",
                (f"id{n}", f"OVO{n:03d}", dep, dep, stamp, stamp))
    monkeypatch.setattr(ops_service.random, "SystemRandom", lambda: _FixedRandom([137] * 50))
    with ops.ops._tx() as con:
        fallback = ops.ops._virtual_flight_number(con, "OVO", dep)
    assert fallback.startswith("OVO") and len(fallback) > 3
    assert re.fullmatch(r"OVO[A-Z0-9]{3}", fallback)
