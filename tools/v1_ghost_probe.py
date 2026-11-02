"""V-1 探针：验证 MSFS「幽灵飞机 / 瞬移」对采样的污染（docs/TODO §33 / §36 前置验证）。

用法：
    python tools/v1_ghost_probe.py live --minutes 8            # 实时轮询 /latest，落 CSV
    python tools/v1_ghost_probe.py analyze <samples.jsonl>     # 分析一次 SimLink 录制产物

live 每 0.5s 取一帧（SimLink 的 /latest 就是最后一帧原始采样），同时每 2s 取一次
/status 记录 recording / engine_seconds / phase；发现「推算速度 > 900 kt」的跳变时
立刻在 stdout 打印一行，便于实时观察。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

HOME = Path.home() / "AppData" / "Local" / "AOC"
RUNTIME = HOME / "simlink-runtime.json"
OUT_DIR = Path(__file__).resolve().parent.parent / "out"
JUMP_KT = 900.0


def load_runtime() -> tuple[str, str]:
    data = json.loads(RUNTIME.read_text(encoding="utf-8"))
    return data["url"].rstrip("/"), data["token"]


def get(url: str, token: str, path: str) -> dict:
    req = Request(url + path, headers={"X-SimLink-Token": token})
    with urlopen(req, timeout=5) as resp:  # noqa: S310 - 固定回环地址
        return json.loads(resp.read().decode("utf-8"))


def dist_nm(a: dict, b: dict) -> float:
    lat1, lon1 = float(a.get("lat") or 0), float(a.get("lon") or 0)
    lat2, lon2 = float(b.get("lat") or 0), float(b.get("lon") or 0)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(h)))


def implied_kt(a: dict, b: dict) -> float | None:
    dt = float(b.get("t") or 0) - float(a.get("t") or 0)
    if dt <= 0:
        return None
    return dist_nm(a, b) / (dt / 3600.0)


def describe(s: dict) -> str:
    return (
        f"t={float(s.get('t') or 0):.1f} lat={float(s.get('lat') or 0):.5f} "
        f"lon={float(s.get('lon') or 0):.5f} gnd={s.get('on_ground')} "
        f"alt={float(s.get('alt_ft') or 0):.0f}ft gs={float(s.get('gs_kt') or 0):.1f}kt "
        f"pb={s.get('parking_brake')}"
    )


def live(minutes: float, interval: float) -> int:
    url, token = load_runtime()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"v1_probe_{stamp}.csv"
    fields = [
        "wall_utc", "t", "lat", "lon", "on_ground", "alt_ft", "agl_ft", "gs_kt", "ias_kt",
        "vs_fpm", "parking_brake", "eng_rpm", "eng_n1", "fuel_kg", "total_weight_kg",
        "phase", "recording", "engine_seconds", "recording_id",
    ]
    prev: dict | None = None
    status: dict = {}
    deadline = time.monotonic() + minutes * 60
    rows = 0
    print(f"[probe] {url} -> {out}  ({minutes} min, {interval}s)", flush=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        tick = 0
        while time.monotonic() < deadline:
            try:
                sample = get(url, token, "/latest").get("sample") or {}
            except Exception as exc:  # noqa: BLE001
                print(f"[probe] /latest 失败: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(interval)
                continue
            if not sample:
                time.sleep(interval)
                continue
            if tick % 4 == 0:
                try:
                    status = get(url, token, "/status")
                except Exception:  # noqa: BLE001
                    status = {}
            tick += 1
            row = {
                "wall_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                **{k: sample.get(k) for k in fields[1:15]},
                "eng_rpm": ";".join(str(round(v, 0)) for v in (sample.get("eng_rpm") or [])),
                "eng_n1": ";".join(str(round(v, 1)) for v in (sample.get("eng_n1") or [])),
                "phase": status.get("phase"),
                "recording": status.get("recording"),
                "engine_seconds": status.get("engine_seconds"),
                "recording_id": status.get("recording_id"),
            }
            writer.writerow(row)
            rows += 1
            if prev is not None and float(sample.get("t") or 0) != float(prev.get("t") or 0):
                kt = implied_kt(prev, sample)
                if kt is not None and kt > JUMP_KT:
                    print(
                        f"[JUMP] {kt:,.0f} kt  ({dist_nm(prev, sample):,.1f} NM)\n"
                        f"   前: {describe(prev)}\n   后: {describe(sample)}",
                        flush=True,
                    )
                if bool(prev.get("on_ground")) != bool(sample.get("on_ground")):
                    print(
                        f"[GROUND] on_ground {prev.get('on_ground')} -> {sample.get('on_ground')}\n"
                        f"   前: {describe(prev)}\n   后: {describe(sample)}",
                        flush=True,
                    )
            prev = sample
            fh.flush()
            time.sleep(interval)
    print(f"[probe] done: {rows} rows -> {out}", flush=True)
    return 0


def analyze(path: str) -> int:
    samples: list[dict] = []
    if path.lower().endswith(".csv"):
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                row["on_ground"] = str(row.get("on_ground")).lower() == "true"
                samples.append(row)
    else:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    samples.append(json.loads(line))
    if not samples:
        print("空文件")
        return 1
    print(f"样本 {len(samples)} 条：")
    print(f"  首帧: {describe(samples[0])}")
    print(f"  末帧: {describe(samples[-1])}")
    airborne = [s for s in samples if not s.get("on_ground")]
    print(f"  空中帧 {len(airborne)} 条（首条 {describe(airborne[0]) if airborne else '—'}）")
    jumps = 0
    for a, b in zip(samples, samples[1:]):
        kt = implied_kt(a, b)
        if kt is not None and kt > JUMP_KT:
            jumps += 1
            print(f"  [JUMP] {kt:,.0f} kt ({dist_nm(a, b):,.1f} NM)\n    前: {describe(a)}\n    后: {describe(b)}")
    print(f"  跳变 {jumps} 处；轨迹总里程 {sum(dist_nm(a, b) for a, b in zip(samples, samples[1:])):,.1f} NM")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_live = sub.add_parser("live")
    p_live.add_argument("--minutes", type=float, default=8.0)
    p_live.add_argument("--interval", type=float, default=0.5)
    p_an = sub.add_parser("analyze")
    p_an.add_argument("path")
    args = ap.parse_args(argv)
    if args.cmd == "live":
        return live(args.minutes, args.interval)
    return analyze(args.path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
