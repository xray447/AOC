"""自适应采样 + BIN_V1/BIN_V2 分段落盘 + 回放解码（P-05 / A-21）。

输入是采样点（dict，跑道窗口内 10Hz、其余 1Hz）；输出是按段
（STRAIGHT/TURN/CLIMB_DESCENT/APPROACH/RUNWAY/TAXI）组织的 gzip 文件与元数据。
转弯/进近/跑道不抽稀（跑道段 0.1s 一点），直行最多 20s 一点，任何模式最大间隔
45s；事件前后 2s 强制保存。

BIN_V2 把时间增量从「整秒 1 字节」改成「十分之一秒 2 字节」，否则 0.1s 采样
的时间戳会全部退化成 0；BIN_V1 仍可解码（旧记录）。
"""
from __future__ import annotations

import gzip
import hashlib
import math
import statistics
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

MODE_STRAIGHT = "STRAIGHT"
MODE_TURN = "TURN"
MODE_CLIMB = "CLIMB_DESCENT"
MODE_APPROACH = "APPROACH"
MODE_RUNWAY = "RUNWAY"
MODE_TAXI = "TAXI"
MODE_EVENT = "EVENT"

ENCODING_V1 = "BIN_V1"
ENCODING_V2 = "BIN_V2"

# BIN_V1：dt 为整秒（1 字节）；BIN_V2：dt 为 0.1s（2 字节），跑道段采样需要
_POINT_V1 = struct.Struct("<BiiiHHhHh")
_POINT_V2 = struct.Struct("<HiiiHHhHh")
_ENCODINGS = {
    ENCODING_V1: (_POINT_V1, 1.0),
    ENCODING_V2: (_POINT_V2, 10.0),
}
_POINT = _POINT_V2


@dataclass
class SamplingConfig:
    turn_enter_dps: float = 4.0
    turn_exit_dps: float = 1.5
    turn_exit_hold_s: float = 4.0
    climb_vs_fpm: float = 1000.0
    taxi_gs_kt: float = 40.0
    approach_agl_ft: float = 3000.0
    # 跑道窗口：地面 GS >= 40kt 的滑跑，或离地/接地 100ft 以内
    runway_gs_kt: float = 40.0
    runway_agl_ft: float = 100.0
    max_gap_s: float = 45.0
    force_hdg_deg: float = 3.0
    force_alt_ft: float = 300.0
    force_dist_nm: float = 2.0
    force_vs_fpm: float = 800.0
    event_pad_s: float = 2.0
    segment_max_s: float = 60.0
    interval_s: dict = field(default_factory=lambda: {
        MODE_STRAIGHT: 20.0, MODE_TURN: 2.0, MODE_CLIMB: 5.0,
        MODE_APPROACH: 1.0, MODE_RUNWAY: 0.1, MODE_TAXI: 10.0,
    })


def _hdg(p: dict) -> float:
    return float(p.get("hdg_true", p.get("hdg_deg", 0.0)) or 0.0)


def _t(p: dict) -> float:
    return float(p.get("t", 0.0) or 0.0)


def ang_diff(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def dist_nm(a: dict, b: dict) -> float:
    mlat = math.radians((float(a["lat"]) + float(b["lat"])) / 2.0)
    dx = math.radians(float(b["lon"]) - float(a["lon"])) * math.cos(mlat) * 6371000.0
    dy = math.radians(float(b["lat"]) - float(a["lat"])) * 6371000.0
    return math.hypot(dx, dy) / 1852.0


def runway_window(point: dict, cfg: SamplingConfig | None = None) -> bool:
    """跑道窗口（P-05/P-06）：起飞滑跑至离地、落地至 GS < 40kt。

    与 SimLink `Engine.SaveSample` 同口径：地面上 GS >= 40kt，或空中 AGL < 100ft。
    SimLink 无导航库，用这个近似代替「距机场 < 5NM」。
    """
    cfg = cfg or SamplingConfig()
    agl = float(point.get("agl_ft") or 0.0)
    gs = float(point.get("gs_kt") or 0.0)
    if bool(point.get("on_ground")):
        return gs >= cfg.runway_gs_kt
    return agl < cfg.runway_agl_ft


def detect_mode(point: dict, prev_mode: str, turn_rate: float, cfg: SamplingConfig,
                turn_below_since: float | None) -> tuple[str, float | None]:
    agl = float(point.get("agl_ft") or 0.0)
    vs = float(point.get("vs_fpm") or 0.0)
    on_ground = bool(point.get("on_ground"))
    gs = float(point.get("gs_kt") or 0.0)
    if runway_window(point, cfg):
        return MODE_RUNWAY, None
    if not on_ground and agl < cfg.approach_agl_ft and vs < 0:
        return MODE_APPROACH, None
    if turn_rate > cfg.turn_enter_dps:
        return MODE_TURN, None
    if prev_mode == MODE_TURN:
        if abs(turn_rate) < cfg.turn_exit_dps:
            if turn_below_since is None:
                return MODE_TURN, _t(point)
            if _t(point) - turn_below_since < cfg.turn_exit_hold_s:
                return MODE_TURN, turn_below_since
        else:
            return MODE_TURN, None
        turn_below_since = None
    if on_ground:
        return (MODE_TAXI if gs < cfg.taxi_gs_kt else MODE_STRAIGHT), turn_below_since
    if abs(vs) > cfg.climb_vs_fpm:
        return MODE_CLIMB, turn_below_since
    return MODE_STRAIGHT, turn_below_since


def select_saved(points: list[dict], cfg: SamplingConfig | None = None,
                 event_times: Iterable[float] | None = None,
                 density: str = "adaptive") -> tuple[list[int], list[str], list[dict]]:
    """返回 (保存点下标, 每点原因, 段列表)。段按模式 + 60s 切分。"""
    cfg = cfg or SamplingConfig()
    if not points:
        return [], [], []
    if density in ("fixed_1hz", "fixed_2hz"):
        saved = list(range(len(points)))
        reasons = ["fixed"] * len(points)
        return saved, reasons, _segments(points, saved, [MODE_STRAIGHT] * len(saved), cfg)

    event_window: set[int] = set()
    for et in event_times or []:
        for d in range(-int(cfg.event_pad_s), int(cfg.event_pad_s) + 1):
            event_window.add(round(et + d))

    saved: list[int] = []
    reasons: list[str] = []
    modes: list[str] = []
    last_saved: dict | None = None
    prev: dict | None = None
    mode = MODE_RUNWAY if runway_window(points[0], cfg) else MODE_TAXI
    turn_below_since: float | None = None

    def mark(i: int, why: str, m: str) -> None:
        if saved and saved[-1] == i:
            reasons[-1] = f"{reasons[-1]},{why}"
            return
        saved.append(i)
        reasons.append(why)
        modes.append(m)

    for i, p in enumerate(points):
        if i == 0:
            mark(0, "first", mode)
            last_saved = prev = p
            continue
        dt = max(1e-6, _t(p) - _t(prev))
        rate = abs(ang_diff(_hdg(p), _hdg(prev))) / dt
        new_mode, turn_below_since = detect_mode(p, mode, rate, cfg, turn_below_since)
        if new_mode != mode:
            mark(i, f"mode:{mode}->{new_mode}", new_mode)
            mode = new_mode
            last_saved = prev = p
            continue
        if mode == MODE_RUNWAY:
            # 跑道段不抽稀（SimLink 已按 0.1s 采样）：接地区要画连续滑跑线
            mark(i, "runway", mode)
            last_saved = prev = p
            continue
        if i in event_window:
            mark(i, "event", mode)
            last_saved = prev = p
            continue
        force = None
        if last_saved is not None:
            if abs(ang_diff(_hdg(p), _hdg(last_saved))) >= cfg.force_hdg_deg:
                force = "hdg"
            elif abs(float(p.get("alt_ft") or 0) - float(last_saved.get("alt_ft") or 0)) >= cfg.force_alt_ft:
                force = "alt"
            elif dist_nm(last_saved, p) >= cfg.force_dist_nm:
                force = "dist"
            elif abs(float(p.get("vs_fpm") or 0) - float(last_saved.get("vs_fpm") or 0)) >= cfg.force_vs_fpm:
                force = "vs"
            elif _t(p) - _t(last_saved) >= cfg.max_gap_s:
                force = "max_gap"
            elif _t(p) - _t(last_saved) >= cfg.interval_s.get(mode, 20.0):
                force = f"interval:{mode}"
        if force:
            mark(i, force, mode)
            last_saved = p
        prev = p

    if saved[-1] != len(points) - 1:
        mark(len(points) - 1, "last", mode)
    return saved, reasons, _segments(points, saved, modes, cfg)


def _segments(points: list[dict], saved: list[int], modes: list[str],
              cfg: SamplingConfig) -> list[dict]:
    out: list[dict] = []
    current: dict | None = None
    for idx, mode in zip(saved, modes):
        t = _t(points[idx])
        if (current is None or current["mode"] != mode
                or t - current["start_t"] > cfg.segment_max_s):
            current = {"mode": mode, "indices": [idx], "start_t": t, "end_t": t}
            out.append(current)
        else:
            current["indices"].append(idx)
            current["end_t"] = t
    for seq, seg in enumerate(out):
        seg["seq"] = seq
    return out


# --------------------------------------------------------------------------
# BIN_V1 / BIN_V2
# --------------------------------------------------------------------------
def encode_points(points: list[dict], encoding: str = ENCODING_V2) -> bytes:
    if not points:
        return b""
    packer, ticks_per_s = _ENCODINGS.get(encoding, _ENCODINGS[ENCODING_V2])
    dt_max = 255 if packer is _POINT_V1 else 65535
    buf = bytearray()
    prev_t = _t(points[0])
    for k, p in enumerate(points):
        dt = 0 if k == 0 else max(0, min(dt_max, int(round((_t(p) - prev_t) * ticks_per_s))))
        prev_t = _t(p)
        buf += packer.pack(
            dt,
            int(round(float(p["lat"]) * 1e7)),
            int(round(float(p["lon"]) * 1e7)),
            int(round(float(p.get("alt_ft") or 0))),
            max(0, min(65535, int(round(float(p.get("gs_kt") or 0) * 10)))),
            max(0, min(65535, int(round((_hdg(p) % 360) * 10)))),
            max(-32768, min(32767, int(round(float(p.get("vs_fpm") or 0))))),
            max(0, min(65535, int(round(float(p.get("fuel_kg") or 0))))),
            max(-32768, min(32767, int(round(float(p.get("g") or 0) * 1000)))),
        )
    return gzip.compress(bytes(buf), mtime=0, compresslevel=9)


def decode_points(blob: bytes, t0: float = 0.0, encoding: str = ENCODING_V2) -> list[dict]:
    packer, ticks_per_s = _ENCODINGS.get(encoding, _ENCODINGS[ENCODING_V2])
    raw = gzip.decompress(blob) if blob[:2] == b"\x1f\x8b" else blob
    out, t = [], t0
    for off in range(0, len(raw) - packer.size + 1, packer.size):
        dt, lat, lon, alt, gs, hdg, vs, fuel, g = packer.unpack_from(raw, off)
        t += dt / ticks_per_s
        out.append({
            "t": t, "lat": lat / 1e7, "lon": lon / 1e7, "alt_ft": float(alt),
            "gs_kt": gs / 10.0, "hdg_true": hdg / 10.0, "vs_fpm": float(vs),
            "fuel_kg": float(fuel), "g": g / 1000.0,
        })
    return out


def write_chunks(points: list[dict], saved: list[int], segments: list[dict],
                 flight_dir: Path, paths=None, encoding: str = ENCODING_V2) -> list[dict]:
    flight_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[dict] = []
    for seg in segments:
        pts = [points[i] for i in seg["indices"]]
        if not pts:
            continue
        blob = encode_points(pts, encoding)
        name = f"{seg['seq']:03d}-{seg['mode']}.bin.gz"
        target = flight_dir / name
        target.write_bytes(blob)
        payload_path = paths.relative(target) if paths is not None else str(target)
        dts = [(_t(b) - _t(a)) for a, b in zip(pts, pts[1:]) if _t(b) > _t(a)]
        chunks.append({
            "seq": seg["seq"], "mode": seg["mode"],
            "start_t_offset_ms": int(round(_t(pts[0]) * 1000)),
            "end_t_offset_ms": int(round(_t(pts[-1]) * 1000)),
            "sample_interval_ms": int(statistics.median(dts) * 1000) if dts else 1000,
            "encoding": encoding, "point_count": len(pts),
            "payload_path": payload_path, "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        })
    return chunks


def decode_chunks(chunks: list[dict], paths) -> tuple[list[dict], list[dict]]:
    points: list[dict] = []
    segments: list[dict] = []
    for chunk in sorted(chunks, key=lambda c: c["seq"]):
        path = paths.resolve(chunk["payload_path"])
        if not path.exists():
            continue
        encoding = chunk.get("encoding") or ENCODING_V1
        try:
            pts = decode_points(path.read_bytes(), t0=chunk["start_t_offset_ms"] / 1000.0,
                                encoding=encoding)
        except (OSError, struct.error, gzip.BadGzipFile):
            continue
        for p in pts:
            p["mode"] = chunk["mode"]
        points.extend(pts)
        segments.append({
            "seq": chunk["seq"], "mode": chunk["mode"],
            "start_t": chunk["start_t_offset_ms"] / 1000.0,
            "end_t": chunk["end_t_offset_ms"] / 1000.0,
            "points": chunk["point_count"], "bytes": chunk.get("bytes"),
        })
    return points, segments


def _point_segment_m(lat: float, lon: float, a: dict, b: dict) -> float:
    mlat = math.radians((float(a["lat"]) + float(b["lat"])) / 2.0)
    kx = math.cos(mlat) * 6371000.0
    px, py = math.radians(lon - float(a["lon"])) * kx, math.radians(lat - float(a["lat"])) * 6371000.0
    vx = math.radians(float(b["lon"]) - float(a["lon"])) * kx
    vy = math.radians(float(b["lat"]) - float(a["lat"])) * 6371000.0
    den = vx * vx + vy * vy
    t = 0.0 if den <= 1e-12 else max(0.0, min(1.0, (px * vx + py * vy) / den))
    return math.hypot(px - vx * t, py - vy * t)


def fidelity_m(points: list[dict], saved: list[int]) -> float | None:
    if len(saved) < 2:
        return None
    pts = [points[i] for i in saved]
    devs: list[float] = []
    j = 0
    for i in range(saved[0], saved[-1] + 1):
        p = points[i]
        while j + 2 < len(pts) and _t(p) > _t(pts[j + 1]):
            j += 1
        if j + 1 >= len(pts):
            break
        devs.append(_point_segment_m(float(p["lat"]), float(p["lon"]), pts[j], pts[j + 1]))
    return round(max(devs), 2) if devs else None
