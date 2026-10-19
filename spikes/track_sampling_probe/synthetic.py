"""合成一段真实量级的飞行轨迹（无模拟器也能回归 V-03）。

按航向/速度积分位置，而不是在折线上插值 —— 这样航向变化率是真实的，
TURN 模式的滞回逻辑才有东西可测。
"""
from __future__ import annotations

import math

from model import Sample


def _gc_point(lat, lon, brg, dist_nm):
    r = 3440.065
    d = dist_nm / r
    p1, l1, b = math.radians(lat), math.radians(lon), math.radians(brg)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def _dist_nm(a, b) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(h)))


def _bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def synth_flight(dep=(35.5533, 139.7811), arr=None,
                 length_nm=780.0, hz=1, cruise_ft=37000.0) -> tuple[list[Sample], list[float]]:
    """滑行 → 起飞 → 爬升 → 巡航（含两次 6°/s 的转弯机动）→ 下降 → 进近 → 着陆滑跑。

    终点若未给出，就按 235° 方向取 length_nm 处，保证航程与时长匹配。
    """
    dt = 1.0 / hz
    if arr is None:
        arr = _gc_point(dep[0], dep[1], 235.0, length_nm)
    d_total = _dist_nm(dep, arr)
    brg0 = _bearing(*dep, *arr)
    wps = [dep]
    for f, off in ((0.3, 14.0), (0.6, -16.0), (0.82, 8.0)):
        lat, lon = _gc_point(dep[0], dep[1], brg0, d_total * f)
        lat, lon = _gc_point(lat, lon, brg0 + 90, off)
        wps.append((lat, lon))
    wps.append(arr)

    taxi_s, climb_s, rollout_s = 360.0, 900.0, 60.0
    # 两次转弯机动的起始时刻（相对起飞后）
    turn_windows = [(20 * 60.0, 12.0), (48 * 60.0, 12.0)]

    samples, events = [], []
    t = 0.0
    lat, lon = dep
    hdg = 90.0
    alt, gs, fuel = 35.0, 12.0, 5200.0
    on_ground, gear, flaps = True, 1, 0
    wpi = 1
    landed = False
    prev_alt = alt
    t_airborne = None
    while t <= 4 * 3600.0:
        if landed:
            gs = max(0.0, gs - 3.0 * dt)
            alt = agl = 35.0
            vs = 0.0
            if gs <= 0.1:
                lat, lon = _gc_point(lat, lon, hdg, gs * dt / 3600.0)
                break
        elif t < taxi_s:
            gs = 12.0
            hdg = (90.0 + 25.0 * math.sin(t / 40.0)) % 360
            alt = agl = 35.0
            vs = 0.0
        else:
            if t_airborne is None:
                t_airborne = t
                on_ground = False
                events.append(t)
            rem = _dist_nm((lat, lon), arr)
            # 航路点推进
            while wpi < len(wps) - 1 and _dist_nm((lat, lon), wps[wpi]) < 8.0:
                wpi += 1
            target = _bearing(lat, lon, wps[wpi][0], wps[wpi][1])
            # 巡航段的两次机动：短时航向偏置，制造 >4°/s 的转弯
            in_turn = any(w0 <= t - t_airborne <= w0 + dur for w0, dur in turn_windows)
            if in_turn:
                target = (target + 70.0) % 360
            rate = 6.0 if in_turn else 3.0
            d = (target - hdg + 180.0) % 360.0 - 180.0
            hdg = (hdg + _clamp(d, -rate * dt, rate * dt)) % 360

            # 高度剖面：爬升 → 巡航 → 3° 下降
            if t < taxi_s + climb_s:
                alt = 35.0 + (cruise_ft - 35.0) * ((t - taxi_s) / climb_s)
                gs = 160.0 + 290.0 * ((t - taxi_s) / climb_s)
                gear, flaps = 0, 0
            elif rem > 130.0:
                alt, gs = cruise_ft, 455.0
                gear, flaps = 0, 0
            elif rem > 15.0:
                alt = min(cruise_ft, 35.0 + rem * 300.0)
                gs = 300.0
                gear, flaps = 1, 1
            else:
                alt = 35.0 + rem * 300.0
                gs = 140.0 + rem * 7.0
                gear, flaps = 1, 2
            if rem < 1.0 and alt < 300.0:
                landed, on_ground = True, True
                events.append(t)
            fuel = max(1800.0, fuel - 3.2 * dt / 60.0)

        if not landed:
            lat, lon = _gc_point(lat, lon, hdg, gs * dt / 3600.0)
        vs = 0.0 if on_ground else (alt - prev_alt) / dt * 60.0
        preview = Sample(t=round(t, 3), lat=lat, lon=lon, alt_ft=alt, agl_ft=max(0.0, alt - 35.0),
                         gs_kt=gs, vs_fpm=vs, hdg_deg=hdg, on_ground=on_ground,
                         fuel_kg=fuel, g_force=1.0, gear=gear, flaps=flaps)
        samples.append(preview)
        if len(samples) > 1:
            p = samples[-2]
            s = samples[-1]
            if (p.gear, p.flaps, p.on_ground) != (s.gear, s.flaps, s.on_ground):
                events.append(t)
        prev_alt = alt
        t += dt

    return samples, sorted(set(events))
