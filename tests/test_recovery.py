from __future__ import annotations

from pathlib import Path

from aoc_core.paths import AppPaths
from aoc_core.service import PersonalService

from .conftest import make_points


def test_a02_auto_start_and_stop(app_client, navdata_path):
    app_client.put("/local/settings", json={"navdata_path": str(navdata_path)})
    service = app_client.app.state.service
    # SimLink 自动开始：客户端只给 recording_id，记录器自行建立
    service.flights.ingest(make_points(total=135), recording_id="auto-flight",
                           recording_started_at="2026-10-20T01:00:00Z")
    flight = service.db.get_flight("auto-flight")
    assert flight is not None
    # §30：接地后只静止约 25s，未达到连续静止 hold（60s）→ 不应提前收尾
    assert flight["status"] == "RECORDING"
    service.flights.ingest([p for p in make_points(total=175) if p["t"] > 135])
    flight = service.db.get_flight("auto-flight")
    assert flight["status"] == "COMPLETED"
    assert flight["block_off_utc"]
    assert flight["takeoff_utc"] and flight["landing_utc"]
    assert flight["touchdown_lat"] is not None and flight["touchdown_lon"] is not None
    assert flight["runway_ident"] == "18"
    assert flight["max_g_flight"] is not None
    assert flight["distance_nm"] > 0
    track = service.get_track("auto-flight")
    assert track["total_points"] > 0
    assert service.flights.recorder is None


def test_a03_crash_resume(tmp_path: Path, navdata_path: Path):
    paths = AppPaths.create(tmp_path / "resume-home")
    first = PersonalService(paths)
    first.update_settings({"navdata_path": str(navdata_path)})
    first.flights.start("resume-flight", "2026-10-20T02:00:00Z", manual=True)
    first.flights.ingest(make_points()[:51])
    first.flights._save_persisted()
    first.flights.recorder.close()  # 模拟进程被杀：不 finalize

    second = PersonalService(paths)
    assert second.flights.recorder is not None
    assert len(second.flights.recorder.samples) >= 51
    assert second.flights.status().active is True

    second.flights.stop()
    record = second.db.get_flight("resume-flight")
    assert record is not None
    assert record["status"] == "ABORTED"  # 没有落地，但轨迹与起飞信息保留
    assert record["takeoff_utc"]
    track = second.get_track("resume-flight")
    assert track["total_points"] > 0
