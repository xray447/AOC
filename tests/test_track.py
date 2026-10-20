from __future__ import annotations

from aoc_core.track import (
    SamplingConfig,
    decode_points,
    encode_points,
    fidelity_m,
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
