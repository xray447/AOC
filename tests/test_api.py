from __future__ import annotations

import asyncio

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

    # 航路引擎诊断：AIP 来源与图状态都能读到（单测里不联网、不建图）
    engine = app_client.get("/local/routes/engine").json()
    assert "graph_available" in engine and "aip_path" in engine
    assert engine["aip_rows"] >= 1


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
    # 单文件 HTML 报告（§29）：内联 SVG、无脚本、无外链
    report = app_client.get("/local/flights/test-flight/export?format=html")
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/html")
    for marker in ("LANDING REPORT", "<svg", "ALT PROFILE", "VERTICAL SPEED",
                   "G FORCE", "TD DEV", "接地区", "V/S"):
        assert marker in report.text, marker
    assert "<script" not in report.text
    assert "http" not in report.text

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


def test_ops_finance_summary_and_task_abort(app_client):
    summary = app_client.get("/local/ops/finance/summary").json()
    assert summary["totals"]["flights"] == 0
    assert [p["key"] for p in summary["periods"]] == ["WEEK", "MONTH", "YEAR"]
    assert "balance" not in summary

    # 没有任务时取消是幂等的；缺参数时明确报错
    assert app_client.post("/local/ops/tasks/abort", json={}).json()["aborted"] is False
    assert app_client.get("/local/ops/legs/simbrief").status_code == 422


def test_ops_flight_status_and_free_airports(app_client):
    """执行页实时状态与出发机场下拉：无 SimLink 时字段齐全（值为 null），机场只列有机队的。"""
    status = app_client.get("/local/ops/flight-status").json()
    assert status["available"] is False
    for key in ("gs_kt", "ias_kt", "alt_ft", "agl_ft", "lat", "lon", "vs_fpm", "phase",
                "remaining_nm", "ete_min", "eta_utc", "actual_zfw_kg"):
        assert key in status
    airports = app_client.get("/local/ops/free-flights/airports").json()["items"]
    assert isinstance(airports, list)


def test_cli_probe_survives_missing_streams(monkeypatch):
    """`--noconsole` 冻结版 sys.stdout/stderr 为 None：`--version`/`--help` 必须正常退出。

    否则 PyInstaller 会弹模态对话框，无桌面的 CI 上 aoc-core.exe --help 一直挂到超时。
    """
    import main

    monkeypatch.setattr(main.sys, "stdout", None)
    monkeypatch.setattr(main.sys, "__stdout__", None)
    for argv in (["aoc-core", "--version"], ["aoc-core", "--help"]):
        monkeypatch.setattr(main.sys, "argv", argv)
        assert main.main() == 0


def test_open_external_uses_default_browser(app_client, monkeypatch):
    """SimBrief 等外链交给系统默认浏览器打开，且只允许 http/https。"""
    import main

    opened: list[str] = []
    monkeypatch.setattr(main.webbrowser, "open", lambda url: opened.append(url) or True)

    url = "https://dispatch.simbrief.com/options/custom?orig=ZBAA&dest=ZSSS"
    res = app_client.post("/local/system/open-external", json={"url": url})
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert opened == [url]

    bad = app_client.post("/local/system/open-external", json={"url": "file:///C:/Windows"})
    assert bad.status_code == 400
    assert opened == [url]


# ---------------------------------------------------------------- SimLink 三态 / 轮询
def test_health_reports_simlink_disconnected(app_client):
    """SimLink 没起时 health/recording 都带三态字段，前端才能区分「没起」与「没连上模拟器」。"""
    health = app_client.get("/local/health").json()
    assert health["simlink_connected"] is False
    recording = health["recording"]
    assert recording["sim_connected"] is False
    assert "simlink_source" in recording and "last_connect_error" in recording


def test_recording_start_warns_without_sim_connection(app_client):
    """SimLink 起了但没连上 MSFS：开始记录返回 warnings（不阻断），并透传原始错误。"""
    service = app_client.app.state.service

    class FakeSimLink:
        def __init__(self) -> None:
            self.actions: list[str] = []

        async def command(self, action: str, **_kwargs):
            self.actions.append(action)
            return {"recording_id": "fake-rec",
                    "recording_started_at": "2026-10-24T00:00:00Z"}

        async def status(self):
            return {"source": "simconnect", "sim_connected": False, "version": "0.1.0",
                    "reconnect_attempts": 3,
                    "last_connect_error": "COMException: 0x80004005"}

    service.set_simlink("http://127.0.0.1:1", "token")
    service._simlink_client = FakeSimLink()
    asyncio.run(service.poll_simlink_once())
    assert service.flights.simlink_connected is True
    assert service.flights.sim_connected is False

    res = app_client.post("/local/recording/start", json={})
    assert res.status_code == 200
    warnings = res.json()["warnings"]
    assert warnings and "没连上模拟器" in warnings[0]
    assert "COMException" in warnings[0]
    assert service.recording_status()["simlink_source"] == "simconnect"
    service.flights.stop(abort=True)


def test_simlink_client_reuses_connection(app_client):
    """同一事件循环复用一条 httpx 客户端（D-27 残留）。

    每次新建 `httpx.AsyncClient` 在 Windows 上要重建 SSL 上下文（实测约 0.5s/次），
    轮询按请求建客户端会变成 2s 一次的 CPU 尖峰。
    """
    from aoc_core.simlink import SimLinkClient

    client = SimLinkClient("http://127.0.0.1:1", "token")

    async def reuse() -> bool:
        first = client._client()
        second = client._client()
        await client.aclose()
        return first is second and first.is_closed

    assert asyncio.run(reuse()) is True


def test_poll_interval_backs_off_when_sim_not_connected(app_client):
    """未连模拟器时轮询退到 5s；连上/录制中才 1s；没有 SimLink 15s。"""
    service = app_client.app.state.service
    assert service._poll_interval(True) == service.POLL_IDLE_S
    service.set_simlink("http://127.0.0.1:1", "token")
    service.flights.sim_connected = False
    assert service._poll_interval(True) == service.POLL_SLOW_S
    assert service._poll_interval(True) == service.POLL_SLOW_S
    service.flights.sim_connected = True
    assert service._poll_interval(True) == service.POLL_FAST_S
    service.flights.sim_connected = False
    assert service._poll_interval(False) == service.POLL_SLOW_S  # 首次失败 5s
    assert service._poll_interval(False) == 2 * service.POLL_SLOW_S  # 连续失败翻倍


def test_ui_pulse_and_simlink_reconnect(app_client, monkeypatch):
    """前端 2s 轮询走 pulse；没有 SimLink 时 reconnect 明确 503；日志目录可打开。"""
    pulse = app_client.get("/local/ui/pulse").json()
    assert "recording" in pulse and "ops" in pulse
    assert pulse["ops"]["state"] in ("IDLE", "GROUND", "FLIGHT")
    assert app_client.post("/local/simlink/reconnect").status_code == 503

    import os

    opened: list[str] = []
    monkeypatch.setattr(os, "startfile", lambda path: opened.append(path), raising=False)
    res = app_client.post("/local/system/open-logs").json()
    assert res["ok"] is True
    assert res["path"].endswith("logs")
    assert opened == [res["path"]]


def test_settlement_detail_flattens_flight_fields(app_client, navdata_path):
    """结算详情与列表同名字段：Drawer 标题不再出现「— ????→????」。"""
    app_client.put("/local/settings", json={"navdata_path": str(navdata_path)})
    service = app_client.app.state.service
    service.ops.seed_demo()
    result = service.ops.draw({"max_legs": 1, "max_block_minutes": 480, "window_hours": 168,
                               "min_turnaround_min": 45, "max_turnaround_min": 360})
    roster = service.ops.confirm_roster(result["candidates"][0]["candidate_token"], 0)
    started = service.ops.start_leg(roster["id"], 1)
    task = started["task"]
    flight = service.db.insert_flight({
        "id": task["flight_record_id"], "status": "COMPLETED",
        "callsign": task["callsign"],
        "dep_icao": task["dep_icao"], "arr_icao": task["arr_icao"],
        "distance_nm": 612.4, "block_minutes": 131.2, "fuel_used_kg": 5210,
        "scheduled_dep_utc": task.get("scheduled_dep_utc"),
        "takeoff_utc": task["started_at"], "landing_utc": task["started_at"],
        "block_off_utc": task["started_at"], "block_on_utc": task["started_at"],
    })
    service.ops.on_flight_finalized(flight)

    listing = app_client.get("/local/ops/settlements").json()["items"][0]
    detail = app_client.get(f"/local/ops/settlements/{listing['id']}").json()
    for key in ("callsign", "dep_icao", "arr_icao"):
        assert detail[key]
        assert detail[key] == listing[key]
    assert "????" not in f"{detail['callsign']} {detail['dep_icao']} {detail['arr_icao']}"
    # 详情页仍在用的嵌套对象保留
    assert detail["flight"]["id"] == listing["flight_record_id"]
