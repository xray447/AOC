"""纯 SimLink 的 ILS 进近探针：不碰 AOC 数据库，也不需要开始录制。

适用场景：直接在空中出生做一次 ILS 进近，不想让 AOC 产生/修改飞行记录。

做法：
  1. 读 `%LOCALAPPDATA%\\AOC\\simlink-runtime.json` 的 url/token，只调只读接口 `/latest`；
  2. 轮询 `_prevFrame`（SimLink 自身 1 Hz 采样，未录制时也有），按 seq 去重后逐帧存 CSV；
  3. 自动识别「空中 → 接地」，接地后继续采 `--after` 秒；
  4. 用 Little Navmap 的 scenery/navdata 库取目标跑道两端坐标，复算接地点距入口 / 中线偏移，
     并换算成 `RunwayTouchdown` 的像素坐标（与界面同一套画布参数）。

用法：
  python tools/ils_simlink_probe.py --arr KMEM --rwy 36R
  python tools/ils_simlink_probe.py --arr KMEM --rwy 36R --after 90 --out out/ils-kmem

输出（默认 out/ils-simlink-<ICAO>-<RWY>-<时间>/）：
  samples.csv   逐帧原始数据（seq/t/lat/lon/alt/agl/gs/vs/g/俯仰/坡度/起落架/襟翼…）
  summary.txt   接地位置、V/S、G、50 ft 距离、下滑角、图上像素位置
  summary.json  同上，机器可读
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
CANVAS_W, PAD_X, CANVAS_H = 960, 56, 300
LNM_DIR = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "ABarthel" / "little_navmap_db"


def default_home() -> Path:
    return Path(os.environ.get("AOC_HOME")
                or Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "AOC")


class SimLink:
    def __init__(self, url: str, token: str):
        self.url, self.token = url.rstrip("/"), token

    def get(self, path: str) -> dict:
        req = Request(self.url + path, headers={"X-SimLink-Token": self.token})
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def latest(self) -> dict | None:
        return (self.get("/latest") or {}).get("sample")


def read_runtime(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"读不到 {path}；先启动 aoc-simlink（或 --url/--token）") from exc


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def project(runway: dict, lat: float, lon: float) -> tuple[float, float]:
    r_lat = float(runway["lat"])
    dx = (lon - float(runway["lon"])) * 111320 * math.cos(math.radians(r_lat))
    dy = (lat - r_lat) * 110540
    th = math.radians(float(runway["heading"]))
    return dy * math.cos(th) + dx * math.sin(th), dx * math.cos(th) - dy * math.sin(th)


def _to_m(raw, probe_ft: float) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return round(value * 0.3048 if value > probe_ft else value, 1)


def reciprocal(name: str) -> str | None:
    name = (name or "").strip().upper()
    i = 0
    while i < len(name) and name[i].isdigit():
        i += 1
    if i == 0 or not (1 <= int(name[:i]) <= 36):
        return None
    num = int(name[:i])
    suffix = {"L": "R", "R": "L"}.get(name[i:], name[i:])
    return f"{(num + 17) % 36 + 1:02d}{suffix}"


def load_runway(icao: str, ident: str, scenery_db: Path | None, navdata_db: Path | None) -> dict | None:
    """从 LNM 库直接取跑道几何（scenery 优先），用两端连线算真方位。"""
    import sqlite3

    sql = (
        "select re.name, re.heading, re.laty, re.lonx, r.length, r.width "
        "from runway r join runway_end re "
        "on re.runway_end_id in (r.primary_end_id, r.secondary_end_id) "
        "join airport a on a.airport_id = r.airport_id where a.ident = ?"
    )
    target = (ident or "").strip().upper()
    for tag, path in (("scenery", scenery_db or LNM_DIR / "little_navmap_msfs24.sqlite"),
                      ("navdata", navdata_db or LNM_DIR / "little_navmap_navigraph.sqlite")):
        if not path or not Path(path).exists():
            continue
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            rows = con.execute(sql, (icao.upper(),)).fetchall()
            con.close()
        except Exception:  # noqa: BLE001
            continue
        ends: dict[str, dict] = {}
        length_raw = width_raw = None
        for row in rows:
            name = (row["name"] or "").strip().upper()
            if row["laty"] is None or row["lonx"] is None:
                continue
            ends[name] = {"lat": float(row["laty"]), "lon": float(row["lonx"]),
                          "hdg": float(row["heading"] or 0)}
            length_raw = length_raw if length_raw is not None else row["length"]
            width_raw = width_raw if width_raw is not None else row["width"]
        if not ends:
            continue
        picked = ends.get(target) or next((v for k, v in ends.items()
                                           if k.rstrip("LRC") == target.rstrip("LRC")), None)
        if picked is None:
            continue
        other = ends.get(reciprocal(target) or "")
        hdg = picked["hdg"]
        if other:
            geo = bearing(picked["lat"], picked["lon"], other["lat"], other["lon"])
            if abs((geo - hdg + 540) % 360 - 180) <= 15:
                hdg = geo
            else:
                print(f"[warn] {tag} 库 heading {hdg:.1f}° 与两端连线 {geo:.1f}° 差得太多，按连线方向算")
                hdg = geo
        return {
            "icao": icao.upper(), "ident": target, "heading": round(hdg, 3),
            "lat": picked["lat"], "lon": picked["lon"],
            "length_m": _to_m(length_raw, 6000), "width_m": _to_m(width_raw, 100),
            "source": tag,
        }
    return None


def canvas_xy(runway: dict, along: float, lateral: float) -> tuple[float, float, float, float]:
    length = max(float(runway.get("length_m") or 0), 200)
    width = float(runway.get("width_m") or 45)
    xscale = (CANVAS_W - 2 * PAD_X) / length
    max_abs = max(width / 2, abs(lateral), 1)
    latscale = min(3.2, max(0.9, (CANVAS_H / 2 - 80) / max_abs))
    return PAD_X + along * xscale, CANVAS_H / 2 + lateral * latscale, along / length * 100, latscale / xscale


def glide_deg(vs_fpm: float, gs_kt: float) -> float:
    """由垂直速度和地速算下滑角（度，正 = 下降）。1 kt ≈ 101.27 ft/min。"""
    if not gs_kt or gs_kt <= 1:
        return 0.0
    return math.degrees(math.atan2(-vs_fpm, gs_kt * 101.27))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="纯 SimLink 的 ILS 进近探针（不依赖 AOC 记录）")
    parser.add_argument("--arr", required=True, help="到达机场 ICAO，例如 KMEM")
    parser.add_argument("--rwy", required=True, help="跑道号，例如 36R")
    parser.add_argument("--after", type=float, default=60, help="接地后继续采样的秒数（默认 60）")
    parser.add_argument("--timeout", type=float, default=40, help="最长采样分钟（默认 40）")
    parser.add_argument("--interval", type=float, default=0.3, help="轮询 /latest 的间隔秒（默认 0.3）")
    parser.add_argument("--out", default="", help="输出目录")
    parser.add_argument("--url", default="", help="覆盖 simlink-runtime.json 的 url")
    parser.add_argument("--token", default="", help="覆盖 token")
    parser.add_argument("--scenery-db", default="", help="Little Navmap msfs24 库路径")
    parser.add_argument("--navdata-db", default="", help="Little Navmap navigraph 库路径")
    parser.add_argument("--quiet", action="store_true", help="不打印每行进度")
    args = parser.parse_args(argv)

    if args.url and args.token:
        runtime = {"url": args.url, "token": args.token}
    else:
        runtime = read_runtime(default_home() / "simlink-runtime.json")
    link = SimLink(runtime["url"], runtime["token"])
    try:
        link.get("/health")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"连不上 aoc-simlink（{link.url}）：{exc}\n先启动 aoc-simlink") from exc

    runway = load_runway(args.arr, args.rwy,
                         Path(args.scenery_db) if args.scenery_db else None,
                         Path(args.navdata_db) if args.navdata_db else None)
    if runway:
        print(f"跑道 {runway['icao']} {runway['ident']}: {runway['length_m']} m × {runway['width_m']} m  "
              f"hdg {runway['heading']}  ({runway['source']})")
    else:
        print(f"[warn] 找不到 {args.arr} {args.rwy} 的跑道几何：只存原始数据，不算偏移")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = Path(args.out) if args.out else ROOT / "out" / f"ils-simlink-{args.arr.upper()}-{args.rwy.upper()}-{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / "samples.csv"
    print(f"输出目录: {outdir}")

    frames: list[dict] = []
    # 未开始时 Sample.seq 恒为 0（seq 只在 SaveSample 里递增），去重必须用 t/lat/lon
    last_key: tuple | None = None
    touchdown: dict | None = None
    touchdown_at: float | None = None
    airborne_ok = False
    deadline = time.time() + args.timeout * 60
    reason = "timeout"
    last_print = 0.0

    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["idx", "seq", "utc", "t", "mode", "lat", "lon", "alt_ft", "agl_ft", "gs_kt", "ias_kt",
                         "vs_fpm", "hdg_true", "pitch", "bank", "g", "on_ground", "gear", "flaps", "paused"])
        try:
            while time.time() < deadline:
                sample = link.latest()
                if not sample:
                    if not args.quiet and time.time() - last_print >= 3:
                        last_print = time.time()
                        print("  等待 SimLink 帧…（模拟器未连接或 SimConnect 未就绪）")
                    time.sleep(0.5)
                    continue
                key = (sample.get("t"), sample.get("lat"), sample.get("lon"))
                if key != last_key:
                    last_key = key
                    row = {
                        "idx": len(frames) + 1,
                        "seq": int(sample.get("seq") or 0), "utc": datetime.now().isoformat(timespec="seconds"),
                        # 未录制时 seq 恒 0，事件的唯一定位用 idx（见 build_summary）
                        "t": sample.get("t"), "mode": sample.get("mode"),
                        "lat": sample.get("lat"), "lon": sample.get("lon"),
                        "alt_ft": sample.get("alt_ft"), "agl_ft": sample.get("agl_ft"),
                        "gs_kt": sample.get("gs_kt"), "ias_kt": sample.get("ias_kt"),
                        "vs_fpm": sample.get("vs_fpm"), "hdg_true": sample.get("hdg_true"),
                        "pitch": sample.get("pitch_deg"), "bank": sample.get("bank_deg"),
                        "g": sample.get("g"), "on_ground": sample.get("on_ground"),
                        "gear": sample.get("gear"), "flaps": sample.get("flaps"),
                        "paused": sample.get("paused"),
                    }
                    frames.append(row)
                    writer.writerow([
                        row["idx"], row["seq"], row["utc"], row["t"], row["mode"], row["lat"], row["lon"], row["alt_ft"],
                        row["agl_ft"], row["gs_kt"], row["ias_kt"], row["vs_fpm"], row["hdg_true"],
                        row["pitch"], row["bank"], row["g"], row["on_ground"], row["gear"],
                        row["flaps"], row["paused"],
                    ])
                    fh.flush()

                    agl = float(sample.get("agl_ft") or 0)
                    if agl > 60:
                        airborne_ok = True
                    if touchdown is None and airborne_ok and sample.get("on_ground"):
                        touchdown = row
                        touchdown_at = time.time()
                        print(f"  检测到接地：t={row['t']}  alt={row['alt_ft']} ft  "
                              f"vs={row['vs_fpm']} fpm  g={row['g']}")
                    if touchdown is not None and time.time() - (touchdown_at or 0) >= args.after:
                        reason = "touchdown+after"
                        break
                    if not args.quiet and time.time() - last_print >= 2:
                        last_print = time.time()
                        print(f"  [{len(frames):5d}] {str(row['mode'] or '—'):9s} "
                              f"alt={_fmt(row['alt_ft'], 0):>7s} ft  agl={_fmt(row['agl_ft'], 0):>6s} ft  "
                              f"gs={_fmt(row['gs_kt'], 1):>5s} kt  vs={_fmt(row['vs_fpm'], 0):>6s} fpm  "
                              f"g={_fmt(row['g'], 2)}  ground={row['on_ground']}")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            reason = "interrupted"

    summary, facts = build_summary(frames, runway, touchdown, reason, args)
    (outdir / "summary.txt").write_text(summary, encoding="utf-8")
    (outdir / "summary.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(summary)
    print(f"文件已写入 {outdir}")
    return 0


def _fmt(value, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def build_summary(frames: list[dict], runway: dict | None, td: dict | None, reason: str,
                  args) -> tuple[str, dict]:
    lines: list[str] = []
    facts: dict = {"airport": args.arr.upper(), "runway": args.rwy.upper(),
                   "frames": len(frames), "stop_reason": reason, "runway_geometry": runway}
    add = lines.append
    add("=" * 72)
    add("SimLink ILS 探针（不依赖 AOC 记录）")
    add("=" * 72)
    t_first, t_last = (frames[0]["t"], frames[-1]["t"]) if frames else (None, None)
    add(f"帧        : {len(frames)} 帧，t {_fmt(t_first, 1)} → {_fmt(t_last, 1)} s（{reason}）")
    if runway:
        add(f"跑道      : {runway['icao']} {runway['ident']}  {runway['length_m']} m × {runway['width_m']} m"
            f"  hdg {runway['heading']}  ({runway['source']})")
    if not frames:
        add("没有采到任何 SimLink 帧：确认模拟器已进入飞行且 aoc-simlink 连上。")
        return "\n".join(lines) + "\n", facts

    if td is None:
        add("未检测到接地（airborne → on_ground）")
        tail = frames[-5:]
        for row in tail:
            add(f"  末帧 t={_fmt(row['t'], 1)}  alt={_fmt(row['alt_ft'], 0)} ft  agl={_fmt(row['agl_ft'], 0)} ft"
                f"  gs={_fmt(row['gs_kt'], 1)} kt  vs={_fmt(row['vs_fpm'], 0)} fpm  ground={row['on_ground']}")
        return "\n".join(lines) + "\n", facts

    idx = next((i for i, row in enumerate(frames) if row["idx"] == td["idx"]), len(frames) - 1)
    around = frames[max(0, idx - 4): idx + 1]
    vs_median = _median([float(r["vs_fpm"]) for r in around if r.get("vs_fpm") is not None])
    facts.update({"touchdown_t": td.get("t"), "touchdown_lat": td.get("lat"), "touchdown_lon": td.get("lon"),
                  "touchdown_vs_fpm": td.get("vs_fpm"), "touchdown_vs_median": vs_median,
                  "touchdown_g": td.get("g"), "touchdown_gs_kt": td.get("gs_kt")})
    add("")
    add(f"接地帧    : t={_fmt(td['t'], 1)} s  lat={_fmt(td['lat'], 6)} lon={_fmt(td['lon'], 6)}")
    add(f"接地参数  : V/S {_fmt(td['vs_fpm'], 0)} fpm（5 帧中位数 {_fmt(vs_median, 0)}）"
        f"  G {_fmt(td['g'], 2)}  GS {_fmt(td['gs_kt'], 1)} kt"
        f"  俯仰 {_fmt(td['pitch'], 1)}°  坡度 {_fmt(td['bank'], 1)}°")

    if runway and td.get("lat") is not None and td.get("lon") is not None:
        along, lateral = project(runway, float(td["lat"]), float(td["lon"]))
        x, y, pct, exag = canvas_xy(runway, along, lateral)
        add(f"接地点    : 距跑道头 {along:.1f} m（跑道内 {pct:.1f}%）  中线偏移 {lateral:+.1f} m")
        add(f"图上位置  : x={x:.0f} px / {CANVAS_W}  y={y:.0f} px（中线{'+' if y >= CANVAS_H / 2 else '-'}"
            f"{abs(y - CANVAS_H / 2):.0f} px，横向放大 {exag:.1f}×）")
        facts.update({"along_m": round(along, 1), "lateral_m": round(lateral, 1),
                      "along_pct": round(pct, 2), "canvas_x_px": round(x, 1),
                      "canvas_y_px": round(y, 1), "exaggeration": round(exag, 2)})

    approach = [r for r in frames[: idx + 1] if r.get("agl_ft") is not None]
    band = [r for r in approach if float(r["agl_ft"]) <= 1000]
    angles = [glide_deg(float(r["vs_fpm"]), float(r["gs_kt"])) for r in band
              if r.get("vs_fpm") is not None and r.get("gs_kt") is not None]
    if angles:
        add(f"末段下滑  : ≤1000 ft AGL 平均 {sum(angles) / len(angles):.2f}°（{len(angles)} 帧，3° 参考）")
        facts["glide_mean_deg"] = round(sum(angles) / len(angles), 2)
    fifty = next((r for r in approach if float(r.get("agl_ft") or 0) <= 50), None)
    if fifty and runway and fifty.get("lat") is not None:
        a50, _ = project(runway, float(fifty["lat"]), float(fifty["lon"]))
        side = "前" if a50 < 0 else "后"
        add(f"50 ft 点  : 跑道头{side} {abs(a50):.0f} m（理想 ≈前 300 m / 1000 ft）"
            f"  AGL {_fmt(fifty['agl_ft'], 0)} ft  gs {_fmt(fifty['gs_kt'], 1)} kt")
        facts["distance_at_50ft_m"] = round(a50, 0)

    rollout = frames[idx:]
    if len(rollout) > 1:
        dist = sum(haversine_m(float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"]))
                   for a, b in zip(rollout, rollout[1:]))
        gmax = max((float(r["g"]) for r in rollout if r.get("g") is not None), default=None)
        add(f"接地后    : {len(rollout)} 帧 / {_fmt(rollout[-1]['t'] - rollout[0]['t'], 1)} s  "
            f"滑跑 {dist:.0f} m  最大 G {_fmt(gmax, 2)}")
        facts.update({"rollout_m": round(dist, 1), "rollout_g_max": gmax})
    return "\n".join(lines) + "\n", facts


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
