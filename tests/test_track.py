from __future__ import annotations

from aoc_core.track import (
    MODE_RUNWAY,
    SamplingConfig,
    decode_points,
    encode_points,
    fidelity_m,
    runway_window,
    select_saved,
)


def make_two_hour_track() -> list[dict]:
    points = []
    for t in range(0, 7200):
        hdg = 90.0
        # 10 秒转弯，航向 90 → 180（9°/s）
        if 3600 <= t < 3610:
            hdg = 90 + (t - 3600) * 9
        elif t >= 3610:
            hdg = 180.0
        points.append({
            "t": float(t),
            "lat": 40.0 + t * 0.00002,
            "lon": 116.0 + t * 0.00008,
            "alt_ft": 33000.0,
            "agl_ft": 33000.0,
            "gs_kt": 460.0,
            "vs_fpm": 0.0,
            "hdg_true": hdg,
            "on_ground": False,
            "fuel_kg": 5000.0,
            "g": 1.0,
        })
    return points


def make_runway_track(step: float = 0.1) -> list[dict]:
    """10Hz 采样：滑行 → 起飞滑跑 → 离地爬升 → 上升（跑道窗口外）。"""
    points: list[dict] = []
    lat = 40.0
    t = 0.0
    while t < 60.0 - 1e-9:
        if t < 10.0:  # 滑行 10kt
            gs, agl, on_ground, vs = 10.0, 0.0, True, 0.0
        elif t < 40.0:  # 起飞滑跑 10 → 150kt
            gs, agl, on_ground, vs = 10.0 + (t - 10.0) * (140.0 / 30.0), 0.0, True, 0.0
        elif t < 45.0:  # 离地：AGL 0 → 300ft
            gs, agl, on_ground, vs = 150.0, (t - 40.0) * 60.0, False, 2400.0
        else:
            gs, agl, on_ground, vs = 180.0, 300.0 + (t - 45.0) * 200.0, False, 1800.0
        points.append({
            "t": t, "lat": lat, "lon": 116.0,
            "alt_ft": 116.0 + agl, "agl_ft": agl, "gs_kt": gs, "vs_fpm": vs,
            "hdg_true": 0.0, "on_ground": on_ground, "fuel_kg": 5000.0, "g": 1.0,
        })
        lat += gs * 0.514444 * step / 111320.0
        t = round(t + step, 10)
    return points


def test_a21_adaptive_sampling_budget():
    points = make_two_hour_track()
    saved, reasons, segments = select_saved(points, SamplingConfig(), event_times=[3600])
    assert len(saved) / len(points) <= 0.4  # ≥60% 压缩
    gaps = [points[b]["t"] - points[a]["t"] for a, b in zip(saved, saved[1:])]
    assert max(gaps) <= 45.01
    dev = fidelity_m(points, saved)
    assert dev is not None and dev <= 30.0
    assert any(seg["mode"] == "TURN" for seg in segments)
    # 转弯段保存间隔 ≤2s
    turn = next(seg for seg in segments if seg["mode"] == "TURN")
    turn_gaps = [points[b]["t"] - points[a]["t"] for a, b in zip(turn["indices"], turn["indices"][1:])]
    assert turn_gaps and max(turn_gaps) <= 2.01
    blob = encode_points([points[i] for i in saved])
    assert len(blob) <= 500 * 1024
    decoded = decode_points(blob)
    assert len(decoded) == len(saved)
    assert abs(decoded[0]["lat"] - points[saved[0]]["lat"]) < 1e-6


def test_fixed_density_keeps_all():
    points = make_two_hour_track()[:600]
    saved, _reasons, segments = select_saved(points, density="fixed_1hz")
    assert saved == list(range(len(points)))
    assert segments


def test_runway_window_covers_roll_and_low_altitude():
    cfg = SamplingConfig()
    points = make_runway_track()
    window = [runway_window(p, cfg) for p in points]
    assert any(window)
    # 地面 GS >= 40kt / 空中 AGL < 100ft 的点都在窗口内
    for p, inside in zip(points, window):
        expected = (p["gs_kt"] >= 40.0) if p["on_ground"] else (p["agl_ft"] < 100.0)
        assert inside == expected


def test_runway_segment_is_10hz_and_not_thinned():
    points = make_runway_track()
    cfg = SamplingConfig()
    saved, _reasons, segments = select_saved(points, cfg)
    runway_idx = [i for i, p in enumerate(points) if runway_window(p, cfg)]
    assert runway_idx

    # 不抽稀：窗口内的点全部保留（不参与任何削减）
    assert set(runway_idx) <= set(saved)

    runway_segments = [seg for seg in segments if seg["mode"] == MODE_RUNWAY]
    assert runway_segments
    for seg in runway_segments:
        gaps = [points[b]["t"] - points[a]["t"] for a, b in zip(seg["indices"], seg["indices"][1:])]
        assert gaps and max(gaps) <= 0.101

    # 点间距 ≤ 8m
    for a, b in zip(runway_idx, runway_idx[1:]):
        d = (
            (points[b]["lat"] - points[a]["lat"]) * 111320.0,
            (points[b]["lon"] - points[a]["lon"]) * 111320.0,
        )
        assert (d[0] ** 2 + d[1] ** 2) ** 0.5 <= 8.0


def test_bin_v2_keeps_sub_second_timestamps():
    points = make_runway_track()[:100]
    blob = encode_points(points)
    decoded = decode_points(blob)
    assert len(decoded) == len(points)
    assert decoded[1]["t"] - decoded[0]["t"] == 0.1
    assert abs(decoded[-1]["t"] - points[-1]["t"]) < 1e-6
