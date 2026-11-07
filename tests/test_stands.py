"""docs/12 验收：机位读取、选位、航站楼规则、ETA 与通知（A-33 ~ A-50 的自动化部分）。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from aoc_core.ops import stands as stand_rules
from aoc_core.paths import AppPaths
from aoc_core.service import PersonalService
from aoc_navdata import NavData
from aoc_navdata.navdata import MSFS_STAND_RADIUS_SCALE

from tests.conftest import build_navdata


@pytest.fixture()
def service(tmp_path: Path, navdata_path: Path):
    svc = PersonalService(AppPaths.create(tmp_path / "home"))
    svc.update_settings({"navdata_path": str(navdata_path)})
    svc.ops.seed_demo()
    return svc


def _terminals(service: PersonalService, icao: str):
    return service.ops.terminal_context(icao)


# ---------------------------------------------------------------- 机位读取 ----
def test_navdata_reads_parking(nav):
    stands = nav.stands("ZSSS")
    idents = {s["ident"] for s in stands}
    # parking.name 的 'G' 是全局类别标记，不参与编号（G101 → 101）
    assert {"101", "201", "501", "601"} <= idents
    assert all(s["source"] == "navdata" for s in stands)
    fuel = next(s for s in stands if s["type"] == "FUEL")
    assert fuel["ident"] == "1"
    # 尺寸/廊桥字段可用
    heavy = next(s for s in stands if s["ident"] == "501")
    assert heavy["radius_m"] == 95.0 and heavy["has_jetway"] is True
    # nearest_stand 用坐标找最近位（S4 校验用）
    nearest = nav.nearest_stand("ZSSS", heavy["lat"], heavy["lon"], max_m=50)
    assert nearest and nearest["ident"] == "501"


def test_stands_degrade_when_columns_missing(tmp_path: Path):
    """老库/异种库缺 has_jetway / suffix / radius：降级成 None，不报错。"""
    path = build_navdata(tmp_path / "navdata.sqlite")
    con = sqlite3.connect(path)
    con.execute("alter table parking drop column has_jetway")
    con.execute("alter table parking drop column suffix")
    con.execute("alter table parking drop column radius")
    con.commit()
    con.close()
    nav = NavData(path)
    stands = nav.stands("ZBAA")
    assert stands
    sample = stands[0]
    assert sample["has_jetway"] is None
    assert sample["suffix"] is None
    assert sample["radius_m"] is None
    nav.close()


def test_number_only_navdata_still_picks(tmp_path: Path):
    """Q-5：现实 navdata 只有编号（无类型/尺寸）时照常给编号，不把机场判成「没有机位」。"""
    path = build_navdata(tmp_path / "navdata.sqlite")
    con = sqlite3.connect(path)
    con.execute("update parking set type=null, radius=null, has_jetway=null")
    con.commit()
    con.close()
    nav = NavData(path)
    stands = nav.stands("ZBAA")
    assert stands and all(s["type"] is None and s["radius_m"] is None for s in stands)
    picked = stand_rules.pick_for_flight(stands, wingspan_m=64.8, role="AIRLINER")
    assert picked["stand"] is not None
    assert picked["stand"]["size_unknown"] is True
    nav.close()


def test_msfs_scenery_radius_is_converted(navdata_path: Path, tmp_path: Path):
    """V-7 复现：MSFS 场景库的 `parking.radius` 是英尺半径，折 0.6096 后才是允许翼展。"""
    scenery = build_navdata(tmp_path / "scenery.sqlite")
    nav = NavData(navdata_path, scenery_path=scenery, runway_source="scenery")
    stands = {s["ident"]: s for s in nav.stands("ZSSS")}
    assert stands["501"]["source"] == "scenery"
    # 夹具里 GH 位写 95（模拟器值）→ 95 × 0.6096 ≈ 57.9 m
    assert stands["501"]["radius_m"] == pytest.approx(95.0 * MSFS_STAND_RADIUS_SCALE, rel=1e-3)
    nav.close()
    # 现实 navdata 的同一张表不折算（口径本来就是 1:1）
    real_nav = NavData(navdata_path)
    plain = {s["ident"]: s for s in real_nav.stands("ZSSS")}
    assert plain["501"]["radius_m"] == 95.0
    real_nav.close()


def test_stand_override_wins(service: PersonalService):
    override = service.set_stand_override(
        "ZBAA", "101", {"lat": 40.10, "lon": 116.70, "radius_m": 88, "has_jetway": False,
                        "stand_type": "GH", "note": "add-on 机场"})
    assert override["ok"] is True
    stand = next(s for s in service.nav.stands("ZBAA") if s["ident"] == "101")
    assert stand["source"] == "override"
    assert stand["radius_m"] == 88.0 and stand["has_jetway"] is False
    assert stand["lat"] == pytest.approx(40.10)
    service.delete_stand_override("ZBAA", "101")
    stand = next(s for s in service.nav.stands("ZBAA") if s["ident"] == "101")
    assert stand["source"] == "navdata"


# ------------------------------------------------------------------ 选位 ----
def test_filter_excludes_fuel_and_respects_wingspan(nav):
    stands = nav.stands("ZSSS")
    candidates, _warnings = stand_rules.filter_candidates(
        stands, role="AIRLINER", wingspan_m=64.8)
    kinds = {c["type"] for c in candidates}
    assert "FUEL" not in kinds and "RMC" not in kinds
    assert candidates and all(c["radius_m"] >= 64.8 for c in candidates)
    # 客机有廊桥位时只用廊桥池
    preferred = stand_rules.jetway_preferred(candidates, "AIRLINER")
    assert all(p["has_jetway"] for p in preferred)


def test_pick_is_random_within_rules(nav):
    """§4.2 拍板：满足硬约束后随机挑，不再按打分取第一。"""
    stands = nav.stands("ZSSS")
    candidates, _warnings = stand_rules.filter_candidates(
        stands, role="AIRLINER", wingspan_m=35.8)
    allowed = {s["ident"] for s in stand_rules.jetway_preferred(candidates, "AIRLINER")}
    picks = [stand_rules.pick_for_flight(stands, wingspan_m=35.8, role="AIRLINER")
             for _ in range(40)]
    chosen = {p["stand"]["ident"] for p in picks}
    assert chosen <= allowed and chosen
    assert all(p["stand"]["has_jetway"] for p in picks)
    # 候选 15 个：40 次全中同一个位可以忽略 → 证明不是「固定取第一个」
    assert len(chosen) > 1
    assert picks[0]["stand"]["score"] is None
    assert picks[0]["stand"]["score_breakdown"]["random"] is True


def test_size_only_filters_not_prefers(nav):
    """尺寸只做硬约束：GM(65) 与 GH(95) 都会出现，不再偏好更大的位。"""
    stands = nav.stands("ZSSS")
    idents = {stand_rules.pick_for_flight(stands, wingspan_m=35.8,
                                         role="AIRLINER")["stand"]["ident"]
              for _ in range(60)}
    assert any(i.startswith("1") or i.startswith("2") for i in idents)
    assert any(i.startswith("5") for i in idents)


def test_explicit_matcher_accepts_legacy_prefix():
    """老配置里写成 `G601` 也要能命中 `601`（G/P 是全局标记，不参与编号）。"""
    stand = {"ident": "601", "type": "GM", "radius_m": 65.0}
    assert stand_rules.matcher_hits(stand, {"type": "explicit", "idents": ["G601"]})
    assert stand_rules.matcher_hits(stand, {"type": "explicit", "idents": ["601"]})
    assert not stand_rules.matcher_hits(stand, {"type": "explicit", "idents": ["602"]})


def test_terminal_rules_zsss(service: PersonalService):
    """A-42 / A-43：春秋落 T1（1xx/3xx/5xx），虚构航司不进 T1。"""
    service.ops.set_terminal("ZSSS", "T1", {"matchers": [
        {"type": "number_range", "ranges": [[100, 199], [300, 399], [500, 599]]}]})
    service.ops.set_terminal_rule({"icao": "ZSSS", "terminal": "T1", "scope": "DOMESTIC",
                                   "airlines": ["9C", "HBH", "CXA"]})
    terminals, rules = _terminals(service, "ZSSS")
    stands = service.nav.stands("ZSSS")

    def pick(carriers):
        return stand_rules.pick_for_flight(
            stands, wingspan_m=35.8, role="AIRLINER",
            terminals=terminals, rules=rules, carriers=carriers, scope="DOMESTIC")

    spring = pick(["9C"])
    assert spring["terminal"] == "T1"
    assert spring["stand"]["number"] in range(100, 200) or spring["stand"]["number"] in range(500, 506)
    # 不在任何规则里的虚构航司：只用未被声明的机位（2xx / 6xx），不进 T1
    virtual = pick(["AOC"])
    assert virtual["terminal"] is None
    assert 200 <= virtual["stand"]["number"] <= 205


def test_terminal_requires_matching_stands(service: PersonalService):
    with pytest.raises(Exception) as exc:
        service.ops.set_terminal("ZSSS", "T9", {"matchers": [
            {"type": "number_range", "ranges": [[9000, 9100]]}]})
    assert "没有命中" in str(exc.value)


def test_terminal_over_filter_falls_back(service: PersonalService):
    """A-44：规则把某个航站楼全圈走后仍要给出机位（回退 + warnings，不静默）。"""
    service.ops.set_terminal("ZSSS", "ALL", {"matchers": [
        {"type": "number_range", "ranges": [[100, 199], [200, 299], [300, 399],
                                            [400, 499], [500, 599], [600, 699]]}]})
    service.ops.set_terminal_rule({"icao": "ZSSS", "terminal": "ALL", "scope": "DOMESTIC",
                                   "airlines": ["9C"]})
    terminals, rules = _terminals(service, "ZSSS")
    picked = stand_rules.pick_for_flight(
        service.nav.stands("ZSSS"), wingspan_m=35.8, role="AIRLINER",
        terminals=terminals, rules=rules, carriers=["AOC"], scope="DOMESTIC")
    assert picked["stand"] is not None
    assert picked["warnings"]


# ------------------------------------------------------------------- ETA ----
def test_eta_refined_three_bands():
    cruise, confidence = stand_rules.eta_refined(300, 450)
    assert cruise == pytest.approx(40.0) and confidence == "low"
    mid, _ = stand_rules.eta_refined(40, 300)
    assert mid == pytest.approx((20 / 300) * 60 + 20 / 250 * 60, rel=1e-3)
    short, confidence = stand_rules.eta_refined(10, 140, phase="APPROACH")
    assert short == pytest.approx(10 / 180 * 60 + 3, abs=0.05)
    assert confidence == "high"
    # 绕行系数只在 1.0–1.3 之间生效
    assert stand_rules.eta_refined(300, 450, detour=1.2)[0] == pytest.approx(48.0)
    assert stand_rules.eta_refined(300, 450, detour=2.0)[0] == pytest.approx(40.0)


# --------------------------------------------------------------- 机位/通知 ----
def _flight(service: PersonalService, arr: str = "ZSSS", callsign: str = "AOC101",
            flight_id: str = "flight-stand") -> dict:
    return service.db.insert_flight({
        "id": flight_id, "status": "RECORDING", "dep_icao": "ZBAA", "arr_icao": arr,
        "callsign": callsign, "aircraft_type": "A320",
    })


def test_stand_is_proposed_before_notice(service: PersonalService):
    """P0 判据：执行页先看到机位（PROPOSED），T-30 才发通知（不提前打扰）。"""
    _flight(service, flight_id="flight-pre")
    stand = service.ops.ensure_flight_stand("flight-pre", eta_min=90.0, remaining_nm=400.0)
    assert stand["status"] == "PROPOSED"
    assert stand["stand_ident"]
    assert service.ops.list_notices(include_acked=True) == []
    # 再算一次仍是同一个位（定稿，不因调用次数漂移）
    again = service.ops.ensure_flight_stand("flight-pre", eta_min=70.0, remaining_nm=300.0)
    assert again["stand_ident"] == stand["stand_ident"]


def test_recompute_stand_with_existing_row(service: PersonalService):
    """重算机位：已有 flight_stand 行时不能再 500（`sqlite3.Row` 没有 `.get`）。"""
    _flight(service, flight_id="flight-recalc")
    first = service.ops.ensure_flight_stand("flight-recalc", eta_min=30, remaining_nm=100)
    assert first["stand_ident"]
    # 手工指定（第二次写库：走 `before` 分支）；旧写法 `G101` 要能命中 `101`
    manual = service.ops.set_flight_stand("flight-recalc", "G101", force=True)
    assert manual["stand_ident"] == "101" and manual["status"] == "CHANGED"
    # 重算（第三次写库：同上）
    again = service.ops.set_flight_stand("flight-recalc", "", force=True)
    assert again["stand_ident"] and again["status"] == "CHANGED"
    assert not again["stand_ident"].startswith(("G", "P"))
    actions = [row["action"] for row in service.ops._rows(
        "select action from ops_audit where entity_id='flight-recalc'")]
    assert actions.count("STAND_ASSIGN") >= 2


def test_stand_notice_is_idempotent(service: PersonalService):
    """A-33 / A-35：一次飞行只发一条；机位定稿后状态变 NOTIFIED。"""
    _flight(service)
    notice = service.ops.ensure_stand_notice(
        "flight-stand", eta_min=25.0, remaining_nm=120.0,
        eta_utc="2026-11-07T10:30:00Z", trigger="distance")
    assert notice and notice["kind"] == "STAND_ETA"
    assert "预计停机位" in notice["title"]
    stand = service.ops.flight_stand("flight-stand")
    assert stand and stand["stand_ident"]
    assert stand["status"] == "NOTIFIED"
    # 第二次调用不再产生通知（flight_record_id + kind 幂等）
    again = service.ops.ensure_stand_notice(
        "flight-stand", eta_min=20.0, remaining_nm=90.0, trigger="eta")
    assert again is None
    queued = service.ops.list_notices()
    assert [n["kind"] for n in queued] == ["STAND_ETA"]
    # ack 之后默认不再返回，但 include_acked 仍能回看
    service.ops.ack_notice(queued[0]["id"], "ui")
    assert service.ops.list_notices() == []
    assert service.ops.list_notices(include_acked=True)


def test_no_stand_data_does_not_invent_ident(service: PersonalService):
    """A-34：无机位数据时只发「预计到达」，不编造编号。"""
    _flight(service, arr="ZZZZ", flight_id="flight-nostand")
    notice = service.ops.ensure_stand_notice(
        "flight-nostand", eta_min=12.0, remaining_nm=40.0,
        eta_utc="2026-11-07T11:00:00Z", trigger="distance")
    assert notice and notice["kind"] == "ETA_ONLY"
    assert "没有停机位数据" in notice["body"]
    stand = service.ops.flight_stand("flight-nostand")
    assert stand["stand_ident"] is None and stand["source"] == "none"


def test_stand_sample_confirms_or_flags_mismatch(service: PersonalService):
    """S4：收尾样本能回填实际机位；与计划不一致时留审计。"""
    _flight(service, flight_id="flight-sample")
    service.ops.ensure_flight_stand("flight-sample", eta_min=20, remaining_nm=80)
    stand = service.ops.flight_stand("flight-sample")
    matched = service.nav.nearest_stand("ZSSS", stand["lat"], stand["lon"], max_m=5.0)
    assert matched
    sample = service.ops.record_stand_sample("flight-sample", stand["lat"], stand["lon"])
    assert sample["stand_ident"] == stand["stand_ident"]
    assert service.ops.flight_stand("flight-sample")["status"] == "CONFIRMED"
    other = next(s for s in service.nav.stands("ZSSS") if s["ident"] != stand["stand_ident"])
    service.ops.record_stand_sample("flight-sample", other["lat"], other["lon"])
    audit = [row for row in service.ops._rows(
        "select action from ops_audit where entity_id='flight-sample'")
        if row["action"] == "STAND_MISMATCH"]
    assert audit


def test_stand_channel_reason_codes(service: PersonalService):
    """A-50：说不清为什么走浮窗就不许降级。"""
    report = service.stand_channel("ZSSS")
    assert report["channel"] in ("overlay", "acars", "batc")
    if report["channel"] == "overlay":
        assert report["reason"] and report["reason_text"]


def test_hoppie_logon_roundtrip(service: PersonalService):
    """logon 只存本机库（DPAPI/base64），不返回明文。"""
    saved = service.ops.set_hoppie_logon("gTESTLOGON0123456789")
    assert saved["configured"] and "gTESTLOGON0123456789" != saved["masked"]
    assert service.ops.hoppie_logon() == "gTESTLOGON0123456789"
    service.ops.set_hoppie_logon("")
    assert service.ops.hoppie_logon() == ""


# ------------------------------------------------------------------- API ----
def test_scenery_library_preferred(app_client, navdata_path: Path, tmp_path: Path,
                                   monkeypatch: pytest.MonkeyPatch):
    """S1 优先于 S2：配了场景库就用游戏内机位（source=scenery），并可按「游戏内」覆盖尺寸。"""
    scenery = build_navdata(tmp_path / "scenery.sqlite")
    con = sqlite3.connect(scenery)
    con.execute("update parking set radius=88 where airport_id="
                "(select airport_id from airport where ident='ZSSS') and number=101")
    con.commit()
    con.close()
    monkeypatch.delenv("AOC_NO_SCENERY", raising=False)
    monkeypatch.setenv("AOC_SCENERY_NAVDATA", str(scenery))
    app_client.put("/local/settings", json={"navdata_path": str(navdata_path)})
    detail = app_client.get("/local/airports/ZSSS").json()
    assert detail["stand_source"] == "scenery"
    stand = next(s for s in detail["stands"] if s["ident"] == "101")
    # 场景库的 radius 是 MSFS 内部值（英尺半径），读出来要折算成「允许翼展」口径
    assert stand["radius_m"] == pytest.approx(88.0 * MSFS_STAND_RADIUS_SCALE, rel=1e-3)


def test_stand_api_endpoints(app_client, navdata_path: Path):
    app_client.put("/local/settings", json={"navdata_path": str(navdata_path)})
    detail = app_client.get("/local/airports/ZSSS").json()
    assert detail["stand_count"] > 0
    assert detail["stand_source"] == "navdata"
    assert any(s["ident"] == "101" for s in detail["stands"])

    saved = app_client.put("/local/airports/ZSSS/terminals/T1",
                          json={"matchers": [{"type": "number_range", "ranges": [[100, 199]]}]})
    assert saved.status_code == 200 and saved.json()["matched"] == 5
    rule = app_client.post("/local/terminal-rules", json={
        "icao": "ZSSS", "terminal": "T1", "scope": "DOMESTIC", "airlines": ["9C"]})
    assert rule.status_code == 200
    rule_id = rule.json()["rules"][0]["id"]
    assert app_client.get("/local/terminal-rules?icao=ZSSS").json()["items"][0]["airlines"] == ["9C"]
    assert app_client.delete(f"/local/terminal-rules/{rule_id}").status_code == 200
    assert app_client.delete("/local/airports/ZSSS/terminals/T1").status_code == 200

    # 手工机位覆盖 + 到达提醒通道
    override = app_client.put("/local/navdata/stand-overrides/ZSSS/777",
                              json={"lat": 31.1985, "lon": 121.337, "radius_m": 80})
    assert override.status_code == 200
    assert app_client.get("/local/navdata/stand-overrides").json()["items"]["ZSSS"]["777"]
    assert app_client.get("/local/stand/channel").status_code == 200
    assert app_client.delete("/local/navdata/stand-overrides/ZSSS/777").status_code == 200

    # Hoppie logon 只存加密值，接口回打码；未配置时通道有原因码
    hoppie = app_client.get("/local/hoppie/status").json()
    assert hoppie["configured"] is False
    assert hoppie["channel"]["reason"] in ("HOPPIE_NOT_CONFIGURED", "NO_STAND_DATA")
    saved = app_client.post("/local/hoppie/logon", json={"logon": "gTESTLOGON0123456789"}).json()
    assert saved["configured"] is True
    assert "gTESTLOGON0123456789" not in saved["masked"]
    assert app_client.post("/local/hoppie/logon", json={"logon": ""}).json()["configured"] is False


def test_notification_queue_endpoints(app_client, navdata_path: Path):
    app_client.put("/local/settings", json={"navdata_path": str(navdata_path)})
    service = app_client.app.state.service
    service.ops.seed_demo()
    service.db.insert_flight({
        "id": "flight-notify", "status": "RECORDING", "dep_icao": "ZBAA", "arr_icao": "ZSSS",
        "callsign": "AOC101", "aircraft_type": "A320"})
    service.ops.ensure_stand_notice("flight-notify", eta_min=20, remaining_nm=90,
                                    eta_utc="2026-11-07T12:00:00Z", trigger="distance")
    queue = app_client.get("/local/notifications").json()
    assert queue["items"] and queue["cursor"] > 0
    notice_id = queue["items"][0]["id"]
    assert app_client.get(
        f"/local/notifications?since={queue['cursor']}").json()["items"] == []
    assert app_client.post(f"/local/notifications/{notice_id}/ack",
                           json={"by": "tauri"}).json()["acked"] is True
    assert app_client.get("/local/notifications").json()["items"] == []
