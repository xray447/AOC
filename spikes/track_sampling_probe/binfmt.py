"""BIN_V1 编码/解码与保真度统计（V-03）。"""
from __future__ import annotations

import gzip
import math
import struct
from pathlib import Path

from model import Sample

_POINT = struct.Struct("<BiiiHHhHh")  # 23 字节/点：dt + lat/lon/alt + gs/hdg/vs/fuel/G


def encode_points(points: list[Sample]) -> bytes:
    if not points:
        return b""
    buf = bytearray()
    prev_t = points[0].t
    for k, p in enumerate(points):
        dt = 0 if k == 0 else max(0, min(255, int(round(p.t - prev_t))))
        prev_t = p.t
        buf += _POINT.pack(
            dt,
            int(round(p.lat * 1e7)),
            int(round(p.lon * 1e7)),
            int(round(p.alt_ft)),
            max(0, min(65535, int(round(p.gs_kt * 10)))),
            max(0, min(65535, int(round((p.hdg_deg % 360) * 10)))),
            max(-32768, min(32767, int(round(p.vs_fpm)))),
            max(0, min(65535, int(round(p.fuel_kg)))),
            max(-32768, min(32767, int(round(p.g_force * 1000)))),
        )
    return gzip.compress(bytes(buf), mtime=0, compresslevel=9)


def decode_points(blob: bytes, t0: float = 0.0) -> list[Sample]:
    raw = gzip.decompress(blob) if blob[:2] == b"\x1f\x8b" else blob
    out, t = [], t0
    for off in range(0, len(raw) - _POINT.size + 1, _POINT.size):
        dt, lat, lon, alt, gs, hdg, vs, fuel, g = _POINT.unpack_from(raw, off)
        t += dt
        out.append(Sample(t=t, lat=lat / 1e7, lon=lon / 1e7, alt_ft=alt, agl_ft=0.0,
                          gs_kt=gs / 10.0, vs_fpm=vs, hdg_deg=hdg / 10.0,
                          on_ground=False, fuel_kg=fuel, g_force=g / 1000.0))
    return out


def write_segments(samples: list[Sample], segments: list[dict], out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, seg in enumerate(segments):
        pts = [samples[j] for j in seg["indices"]]
        blob = encode_points(pts)
        name = f"{i:03d}-{seg['mode']}.bin.gz"
        (out_dir / name).write_bytes(blob)
        manifest.append({"file": name, "mode": seg["mode"],
                         "start_t": round(seg["start_t"], 1), "end_t": round(seg["end_t"], 1),
                         "points": len(pts), "bytes": len(blob)})
    return manifest


def _point_seg_m(lat, lon, alat, alon, blat, blon) -> float:
    """点到线段距离（米），等距圆柱投影；只用于 30NM 内的偏差统计。"""
    mlat = math.radians((alat + blat) / 2.0)
    kx = math.cos(mlat) * 6371000.0
    px, py = math.radians(lon - alon) * kx, math.radians(lat - alat) * 6371000.0
    vx = math.radians(blon - alon) * kx
    vy = math.radians(blat - alat) * 6371000.0
    denom = vx * vx + vy * vy
    t = 0.0 if denom <= 1e-12 else max(0.0, min(1.0, (px * vx + py * vy) / denom))
    return math.hypot(px - vx * t, py - vy * t)


def fidelity(samples: list[Sample], saved_idx: list[int]) -> dict:
    """每个 1Hz 原始点 → 保存点折线的最近距离。"""
    pts = [samples[i] for i in saved_idx]
    devs = []
    j = 0
    for i in range(saved_idx[0], saved_idx[-1] + 1):
        s = samples[i]
        while j + 2 < len(pts) and s.t > pts[j + 1].t:
            j += 1
        if j + 1 >= len(pts):
            break
        a, b = pts[j], pts[j + 1]
        devs.append(_point_seg_m(s.lat, s.lon, a.lat, a.lon, b.lat, b.lon))
    devs.sort()
    n = len(devs)

    def pct(p):
        return devs[min(n - 1, int(round(p / 100.0 * (n - 1))))] if n else 0.0

    return {"n": n, "max_m": round(devs[-1], 2) if n else 0.0,
            "p95_m": round(pct(95), 2),
            "mean_m": round(sum(devs) / n, 2) if n else 0.0}
