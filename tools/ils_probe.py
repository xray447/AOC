"""ILS 进近探针：抓一次落地前后的实时采样 + 飞行记录 + 轨迹，落地后自动算核对结果。

用途：验证「接地区」指标（距入口 / 中线偏移）在图上到底落在哪儿（TODO §41）。

做法：
  1. 连本地 aoc-core（`%LOCALAPPDATA%\\AOC\\runtime.json` 里的 url/token）；
  2. 每 `--interval` 秒采样 `/local/recording/status` 的最近一帧，写 samples.csv；
  3. 记录结束（status != RECORDING）、超时或 Ctrl+C 之后，抓 `/local/flights/{id}`、
     `/local/flights/{id}/track`，并另存服务端生成的 `report.html`；
  4. 用目标跑道的几何复算接地点 along/lateral，换算成 `RunwayTouchdown` 的像素坐标，
     写 summary.txt / summary.json。

用法：
  python tools/ils_probe.py --arr KMEM --rwy 36R                   # 等录制开始，落地后自动收
  python tools/ils_probe.py --arr KMEM --rwy 36R --flight-id <id>  # 抓指定记录
  python tools/ils_probe.py --arr KAMA --rwy 22 --flight-id <id> --no-wait

说明：只调只读接口，不改库；Ctrl+C 会先把已有采样落盘再抓一次数据。
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
# 与 apps/client/src/components/RunwayTouchdown.tsx 保持同一套画布参数
CANVAS_W, PAD_X, CANVAS_H = 960, 56, 300


def default_home() -> Path:
    return Path(os.environ.get("AOC_HOME")
                or Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "AOC")


def read_runtime(home: Path) -> dict:
    try:
        return json.loads((home / "runtime.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"读不到 {home / 'runtime.json'}；先启动 AOC 客户端") from exc


class Client:
    def __init__(self, url: str, token: str):
        self.url, self.token = url.rstrip("/"), token

    def get(self, path: str) -> dict:
        req = Request(self.url + path, headers={"X-AOC-Token": self.token})
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_text(self, path: str) -> str:
        req = Request(self.url + path, headers={"X-AOC-Token": self.token})
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")


def list_flights(client: Client, limit: int = 10) -> list[dict]:
    try:
        return (client.get(f"/local/flights?limit={limit}") or {}).get("items") or []
    except Exception:  # noqa: BLE001
        return []


def pick_runway(runways: list[dict], ident: str) -> dict | None:
    if not runways:
        return None
    target = (ident or "").strip().upper()
    for rwy in runways:
        if str(rwy.get("ident") or "").strip().upper() == target:
            return rwy
    for rwy in runways:  # 36R 退化成 36 / 找不到时取最长
        if str(rwy.get("ident") or "").strip().upper().rstrip("LRC") == target.rstrip("LRC"):
            return rwy
    return max(runways, key=lambda r: float(r.get("length_m") or 0))


def project(runway: dict, lat: float, lon: float) -> tuple[float, float]:
    """与后端 `project_on_runway` 同口径：沿跑道方向米数 + 横向偏移（右偏为正）。"""
    r_lat = float(runway["lat"])
    dx = (lon - float(runway["lon"])) * 111320 * math.cos(math.radians(r_lat))
    dy = (lat - r_lat) * 110540
    th = math.radians(float(runway["heading"]))
    return dy * math.cos(th) + dx * math.sin(th), dx * math.cos(th) - dy * math.sin(th)


def canvas_xy(runway: dict, along: float, lateral: float) -> tuple[float, float, float, float]:
    """换算成 RunwayTouchdown 的像素坐标（x, y, 跑道内百分比, 横向放大倍数）。"""
    length = max(float(runway.get("length_m") or 0), 200)
    width = float(runway.get("width_m") or 45)
    xscale = (CANVAS_W - 2 * PAD_X) / length
    max_abs = max(width / 2, abs(lateral), 1)
    latscale = min(3.2, max(0.9, (CANVAS_H / 2 - 80) / max_abs))
    return (PAD_X + along * xscale,
            CANVAS_H / 2 + lateral * latscale,
            along / length * 100,
            latscale / xscale)


def sample_loop(client: Client, args, samples_path: Path) -> tuple[str | None, str, int]:
    """采样到记录结束；返回 (flight_id, 结束原因, 采样帧数)。"""
    fid = (args.flight_id or "").strip() or None
    if fid and args.no_wait:
        samples_path.write_text("utc,phase,lat,lon,alt_ft,agl_ft,gs_kt,on_ground\n", encoding="utf-8-sig")
        return fid, "skip", 0
    deadline = time.time() + args.timeout * 60
    wait_started = time.time()
    wait_until = wait_started + args.wait_start * 60
    last_status, last_print, last_hint = 0.0, 0.0, 0.0
    reason = "timeout"
    rows = 0
    with samples_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["utc", "phase", "lat", "lon", "alt_ft", "agl_ft", "gs_kt", "on_ground",
                         "samples", "engine_s", "zfw_at_pushback", "fuel_at_pushback"])
        try:
            while time.time() < deadline:
                st = client.get("/local/recording/status")
                if not st.get("active"):
                    if fid:
                        reason = "record-finished"
                        break
                    if time.time() > wait_until:
                        reason = "no-recording"
                        break
                    if not args.quiet and time.time() - last_hint >= 10:
                        last_hint = time.time()
                        waited = int(time.time() - wait_started)
                        print(f"  等待录制开始… active=false  sim_connected={st.get('sim_connected')}  "
                              f"已等 {waited}s / {int(args.wait_start * 60)}s")
                        if st.get("sim_connected") is False:
                            print("     （SimLink 未连接：先启动 MSFS 并让 AOC 连上，否则不会自动开录）")
                    time.sleep(2)
                    continue
                fid = fid or st.get("flight_id")
                sim = st.get("simlink_last") or {}
                writer.writerow([
                    datetime.now().isoformat(timespec="seconds"),
                    sim.get("phase"), sim.get("lat"), sim.get("lon"),
                    sim.get("alt_ft"), sim.get("agl_ft"), sim.get("gs_kt"), sim.get("on_ground"),
                    sim.get("samples"), sim.get("engine_seconds"),
                    sim.get("zfw_at_pushback"), sim.get("fuel_at_pushback"),
                ])
                fh.flush()
                rows += 1
                if not args.quiet and time.time() - last_print >= 5:
                    last_print = time.time()
                    print(f"  [{rows:5d}] {str(sim.get('phase') or '—'):9s} "
                          f"alt={_fmt(sim.get('alt_ft'), 0):>7s} ft  agl={_fmt(sim.get('agl_ft'), 0):>6s} ft  "
                          f"gs={_fmt(sim.get('gs_kt'), 1):>5s} kt  ground={sim.get('on_ground')}")
                if time.time() - last_status >= 3:
                    last_status = time.time()
                    try:
                        status = (client.get(f"/local/flights/{fid}").get("status") or "RECORDING")
                    except Exception:  # noqa: BLE001
                        status = "RECORDING"
                    if status != "RECORDING":
                        reason = f"status={status}"
                        break
                time.sleep(args.interval)
        except KeyboardInterrupt:
            reason = "interrupted"
    return fid, reason, rows


def _fmt(value, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def build_summary(flight: dict, track: dict, airport: dict | None, runway: dict | None,
                  rows: int, reason: str) -> tuple[str, dict]:
    lines: list[str] = []
    facts: dict = {"flight_id": flight.get("id"), "stop_reason": reason, "samples": rows}

    def add(text: str = "") -> None:
        lines.append(text)

    add("=" * 72)
    add("ILS / 落地探针结果")
    add("=" * 72)
    add(f"记录      : {flight.get('id')}  状态 {flight.get('status')}  模式 {flight.get('mode')}")
    add(f"航段      : {flight.get('dep_icao') or '—'} → {flight.get('arr_icao') or '—'}  "
        f"跑道 {flight.get('runway_ident') or '—'}")
    add(f"时刻      : 滑出 {flight.get('block_off_utc') or '—'}  起飞 {flight.get('takeoff_utc') or '—'}  "
        f"落地 {flight.get('landing_utc') or '—'}  到位 {flight.get('block_on_utc') or '—'}")
    add(f"采样      : {rows} 帧（{reason}）")

    if runway:
        add("")
        add(f"跑道几何  : {airport.get('icao') if airport else ''} {runway.get('ident')}  "
            f"{_fmt(runway.get('length_m'), 1)} m × {_fmt(runway.get('width_m'), 1)} m  "
            f"hdg {_fmt(runway.get('heading'), 2)}  source {runway.get('source') or 'navdata'}"
            + (f"  内移 {_fmt(runway.get('displaced_threshold_m'), 1)} m"
               if float(runway.get("displaced_threshold_m") or 0) > 0 else ""))

    add("")
    add("落地指标  : V/S " + _fmt(flight.get("touchdown_vs_fpm"), 0) + " fpm"
        f"  G {_fmt(flight.get('touchdown_g'), 2)}"
        f"  峰值 G {_fmt(flight.get('max_g_landing'), 2)}"
        f"  弹跳 {flight.get('bounce_count') if flight.get('bounce_count') is not None else '—'}"
        f"  评级 {flight.get('landing_rating') or '—'}")
    add(f"记录值    : 距入口 {_fmt(flight.get('threshold_distance_m'), 1)} m"
        f"  中线偏移 {_fmt(flight.get('centerline_offset_m'), 1)} m"
        f"  滑跑 {_fmt(flight.get('landing_distance_m'), 0)} m"
        f"  跑道长 {_fmt(flight.get('runway_length_m'), 1)} m"
        f" ({flight.get('runway_source') or '—'})")

    td_lat, td_lon = flight.get("touchdown_lat"), flight.get("touchdown_lon")
    if runway and td_lat is not None and td_lon is not None:
        along, lateral = project(runway, float(td_lat), float(td_lon))
        displaced = float(runway.get("displaced_threshold_m") or 0)
        along -= displaced
        x, y, pct, exag = canvas_xy(runway, along + displaced, lateral)
        dy_px = y - CANVAS_H / 2
        add(f"复算值    : 距入口 {along:.1f} m  中线偏移 {lateral:+.1f} m")
        add(f"图上位置  : x={x:.0f} px / {CANVAS_W}（跑道内 {pct:.1f}%）"
            f"  y={y:.0f} px（中线{'+' if dy_px >= 0 else '-'}{abs(dy_px):.0f} px，横向放大 {exag:.1f}×）")
        if flight.get("threshold_distance_m") is not None:
            d_along = along - float(flight["threshold_distance_m"])
            d_lat = lateral - float(flight.get("centerline_offset_m") or 0)
            add(f"一致性    : Δ沿跑道 {d_along:+.1f} m  Δ横向 {d_lat:+.1f} m"
                + ("（口径一致）" if abs(d_along) < 0.5 and abs(d_lat) < 0.5 else "（注意：前后端口径可能不同）"))
        facts.update({"along_m": round(along, 1), "lateral_m": round(lateral, 1),
                      "canvas_x_px": round(x, 1), "canvas_y_px": round(y, 1),
                      "along_pct": round(pct, 2), "exaggeration": round(exag, 2)})

    pts = track.get("points") or []
    if pts:
        vs = [float(p["vs_fpm"]) for p in pts
              if p.get("vs_fpm") is not None and p.get("alt_ft") is not None]
        agl_band = [float(p["vs_fpm"]) for p in pts
                    if p.get("vs_fpm") is not None and airport and p.get("alt_ft") is not None
                    and 0 <= float(p["alt_ft"]) - float(airport.get("elev_ft") or 0) <= 500]
        add("")
        if vs:
            add(f"轨迹      : {len(pts)} 点，末点 t={pts[-1].get('t')} s；垂直速度均值 {sum(vs) / len(vs):.0f} fpm")
        else:
            add(f"轨迹      : {len(pts)} 点")
        if agl_band:
            add(f"末段(≤500ft AGL): 平均 V/S {sum(agl_band) / len(agl_band):.0f} fpm，"
                f"最低 {min(agl_band):.0f} / 最高 {max(agl_band):.0f} fpm")
        facts.update({"track_points": len(pts),
                      "vs_mean_fpm": round(sum(vs) / len(vs), 1) if vs else None,
                      "vs_500ft_mean_fpm": round(sum(agl_band) / len(agl_band), 1) if agl_band else None})

    events = track.get("events") or []
    if events:
        add("")
        add(f"事件      : {len(events)} 条")
        for ev in events[:20]:
            detail = ev.get("payload")
            t_ms = ev.get("t_offset_ms")
            t_txt = f"t+{float(t_ms) / 1000:.1f}s" if t_ms is not None else "—"
            add(f"  - {str(ev.get('type')):18s} @ {t_txt:>10s}"
                f"  {json.dumps(detail, ensure_ascii=False)[:160] if detail else ''}")
    facts["events"] = [ev.get("type") for ev in events]
    facts["status"] = flight.get("status")
    facts["arr_icao"] = flight.get("arr_icao")
    facts["runway_ident"] = flight.get("runway_ident")
    facts["threshold_distance_m"] = flight.get("threshold_distance_m")
    facts["centerline_offset_m"] = flight.get("centerline_offset_m")
    facts["touchdown_vs_fpm"] = flight.get("touchdown_vs_fpm")
    facts["touchdown_g"] = flight.get("touchdown_g")
    return "\n".join(lines) + "\n", facts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抓一次 ILS 进近/落地的 AOC 数据与结果")
    parser.add_argument("--arr", default="", help="到达机场 ICAO，例如 KMEM（--list 时可不填）")
    parser.add_argument("--rwy", default="", help="跑道号，例如 36R（--list 时可不填）")
    parser.add_argument("--flight-id", default="",
                        help="直接抓指定记录（默认等/跟当前录制；latest = 最近一条）")
    parser.add_argument("--no-wait", action="store_true", help="给了 --flight-id 时不再采样等待")
    parser.add_argument("--list", action="store_true", help="只列最近 10 条记录后退出")
    parser.add_argument("--interval", type=float, default=1.0, help="采样间隔秒（默认 1.0）")
    parser.add_argument("--timeout", type=float, default=90, help="最长等待分钟（默认 90）")
    parser.add_argument("--wait-start", type=float, default=20, help="等录制开始的最长分钟（默认 20）")
    parser.add_argument("--out", default="", help="输出目录（默认 out/ils-probe-<ICAO>-<RWY>-<时间>）")
    parser.add_argument("--url", default="", help="覆盖 runtime.json 的 core url")
    parser.add_argument("--token", default="", help="覆盖 runtime.json 的 token")
    parser.add_argument("--quiet", action="store_true", help="不打印采样进度")
    args = parser.parse_args(argv)

    home = default_home()
    runtime = {} if (args.url and args.token) else read_runtime(home)
    client = Client(args.url or runtime["url"], args.token or runtime["token"])
    try:
        client.get("/healthz")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"连不上 aoc-core（{client.url}）：{exc}\n"
            f"先启动 AOC 客户端；端口/token 取自 {home / 'runtime.json'}")

    if args.list:
        items = list_flights(client, 10)
        if not items:
            print("没有飞行记录")
            return 0
        print(f"{'id':38s} {'status':10s} {'arr':5s} {'rwy':4s} {'landing_utc':22s} {'thr_m':>7s} {'lat_m':>6s}")
        for item in items:
            print(f"{str(item.get('id')):38s} {str(item.get('status')):10s} "
                  f"{str(item.get('arr_icao') or '—'):5s} {str(item.get('runway_ident') or '—'):4s} "
                  f"{str(item.get('landing_utc') or '—'):22s} "
                  f"{_fmt(item.get('threshold_distance_m'), 1):>7s} {_fmt(item.get('centerline_offset_m'), 1):>6s}")
        return 0

    if not args.arr or not args.rwy:
        parser.error("--arr 和 --rwy 必填（--list 除外）")

    if (args.flight_id or "").strip().lower() == "latest":
        items = list_flights(client, 1)
        if not items:
            raise SystemExit("没有找到任何记录")
        args.flight_id = str(items[0]["id"])
        print(f"用最近一条记录: {args.flight_id}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = Path(args.out) if args.out else ROOT / "out" / f"ils-probe-{args.arr.upper()}-{args.rwy.upper()}-{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)

    airport = None
    try:
        airport = client.get(f"/local/airports/{args.arr.upper()}")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 取机场 {args.arr} 失败：{exc}")
    runway = pick_runway((airport or {}).get("runways") or [], args.rwy)
    if runway is None:
        print(f"[warn] {args.arr} 没有可用跑道数据，图上位置将跳过")
    else:
        print(f"跑道 {args.arr.upper()} {runway.get('ident')}: "
              f"{runway.get('length_m')} m × {runway.get('width_m')} m, "
              f"hdg {runway.get('heading')}, source {runway.get('source')}")

    print(f"输出目录: {outdir}")
    fid, reason, rows = sample_loop(client, args, outdir / "samples.csv")
    if not fid:
        print(f"没有拿到飞行记录（{reason}）")
        items = list_flights(client, 1)
        if items:
            fid = str(items[0]["id"])
            reason = f"{reason}→fallback:latest"
            print(f"改为抓最近一条记录 {fid}（指定记录用 --list / --flight-id）")
        else:
            (outdir / "summary.txt").write_text(
                f"没有拿到飞行记录：{reason}\n"
                "说明：脚本期间没有处于录制中的记录（active=false），也没有历史记录可回退。\n"
                "先确认 AOC 客户端在运行、SimLink 已连接、录制已开始。\n", encoding="utf-8")
            return 1

    print(f"记录 {fid} 结束（{reason}），抓取数据…")
    flight: dict = {}
    track: dict = {}
    try:
        flight = client.get(f"/local/flights/{fid}")
        (outdir / "flight.json").write_text(
            json.dumps(flight, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 取 flight 失败：{exc}")
    try:
        track = client.get(f"/local/flights/{fid}/track")
        (outdir / "track.json").write_text(
            json.dumps(track, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 取 track 失败：{exc}")
    try:
        (outdir / "report.html").write_text(
            client.get_text(f"/local/flights/{fid}/export?format=html"), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 导出 report.html 失败：{exc}")

    summary, facts = build_summary(flight, track, airport, runway, rows, reason)
    if not flight:
        summary += "\n（flight 数据缺失，只有 samples.csv）\n"
    (outdir / "summary.txt").write_text(summary, encoding="utf-8")
    (outdir / "summary.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print()
    print(summary)
    print(f"文件已写入 {outdir}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
