"""生成 10,000 点 / 1Hz 的回放轨迹（RJTT → RJAA 绕飞航线）。"""
import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "data" / "track.json"


def gc(lat, lon, brg, dist_nm):
    d = dist_nm / 3440.065
    p1, l1, b = map(math.radians, (lat, lon, brg))
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


N = 10000
lat, lon = 35.5533, 139.7811
hdg = 118.0
pts = []
for i in range(N):
    # 缓慢转弯 + 巡航段小幅度蛇形，保证 10k 点不是一条直线
    hdg += 0.35 * math.sin(i / 900.0) + 0.02
    lat, lon = gc(lat, lon, hdg, 0.12)
    pts.append([round(lon, 6), round(lat, 6)])

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps({"interval_s": 1, "points": pts}, separators=(",", ":")), encoding="utf-8")
print("wrote", OUT, len(pts), "points", OUT.stat().st_size, "bytes")
