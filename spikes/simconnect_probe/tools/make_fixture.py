"""生成一段 80s 的进近/着陆回放夹具（RJTT 34R），用于无模拟器时验证 V-02。"""
import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data/final_approach_rjtt34r.jsonl"
THR = (35.53969955444336, 139.80514526367188)
RWY_HDG = 330.0


def gc(lat, lon, brg, dist_nm):
    d = dist_nm / 3440.065
    p1, l1, b = map(math.radians, (lat, lon, brg))
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


rows = []
t = 0.0
for sec in range(80):
    if sec < 70:
        dist = 3.2 * (1 - sec / 70.0)
        alt = 35 + max(0.0, dist * 318)
        lat, lon = gc(THR[0], THR[1], (RWY_HDG + 180) % 360, dist)
        vs = -650.0
        gs = 145.0
        on_ground = False
        g = 1.0
        pitch, aoa = 2.5, 4.5
    elif sec == 70:
        lat, lon = THR
        alt, vs, gs, on_ground, g = 35, -180.0, 140.0, True, 1.45
        pitch, aoa = 1.0, 6.0
    else:
        dist = (sec - 70) * 0.05
        lat, lon = gc(THR[0], THR[1], RWY_HDG, dist)
        alt, vs = 35.0, 0.0
        gs = max(0.0, 140.0 - (sec - 70) * 6.0)
        on_ground = True
        g = 1.0
        pitch, aoa = 0.5, 3.0
    rows.append({
        "t": round(t, 1), "lat": round(lat, 7), "lon": round(lon, 7),
        "alt_ft": round(alt, 1), "agl_ft": round(max(0.0, alt - 35), 1),
        "gs_kt": round(gs, 1), "vs_fpm": round(vs, 1), "hdg_deg": RWY_HDG,
        "on_ground": on_ground, "fuel_kg": round(2600 - sec * 0.4, 1),
        "g_force": round(g, 2), "pitch_deg": pitch, "aoa_deg": aoa,
        "ias_kt": round(gs + 2, 1), "gear": 1, "flaps": 4,
    })
    t += 1.0

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
print("wrote", OUT, len(rows), "samples")
