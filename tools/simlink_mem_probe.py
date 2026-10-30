"""aoc-simlink 内存探针（TODO 第 8 条 / D-26）。

定时记录 SimLink 的工作集/私有内存 + `/status` 的 samples/events（区分
「基线 / 随录制时长线性增长 / GC 峰值」），输出 CSV 与摘要。

用法（Windows）：
    python tools/simlink_mem_probe.py --minutes 30 --interval 60
    python tools/simlink_mem_probe.py --runtime %LOCALAPPDATA%\\AOC\\simlink-runtime.json \
        --out out/simlink-mem.csv

判据（TODO 第 8 条）：未连接空转 < 60 MB；连上模拟器未录制 < 80 MB；
录制中稳态 < 100 MB 且不随小时线性增长（±10 MB/2h）。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

PS_SCRIPT = (
    "$p = Get-Process -Id __PID__ -ErrorAction Stop; "
    "'{0}|{1}|{2}|{3}' -f $p.CPU, $p.WorkingSet64, $p.PrivateMemorySize64, $p.Threads.Count"
)


def default_home() -> Path:
    return Path(os.environ.get("AOC_HOME")
                or Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "AOC")


def read_runtime(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"读不到 {path}；先启动 aoc-simlink（或用 --url/--token/--pid）") from exc


def sample_process(pid: int) -> tuple[float, float, float, int]:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         PS_SCRIPT.replace("__PID__", str(pid))],
        capture_output=True, text=True, timeout=20, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"PowerShell 读取进程失败：{proc.stderr.strip() or proc.stdout.strip()}")
    parts = proc.stdout.strip().split("|")
    if len(parts) != 4:
        raise SystemExit(f"无法解析进程信息：{proc.stdout!r}")
    return (float(parts[0]), float(parts[1]) / 1024 / 1024,
            float(parts[2]) / 1024 / 1024, int(parts[3]))


def sample_status(url: str, token: str) -> dict:
    try:
        req = Request(f"{url.rstrip('/')}/status", headers={"X-SimLink-Token": token})
        with urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - 探针不因一次失败中断
        return {"error": type(exc).__name__}


def slope_per_hour(points: list[tuple[float, float]]) -> float:
    """最小二乘斜率（MB/小时）。"""
    if len(points) < 2:
        return 0.0
    n = len(points)
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    den = sum((p[0] - mean_x) ** 2 for p in points)
    if den <= 1e-9:
        return 0.0
    num = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points)
    return num / den * 3600.0


def main() -> int:
    parser = argparse.ArgumentParser(description="aoc-simlink 内存采样")
    parser.add_argument("--runtime", default=None, help="simlink-runtime.json 路径")
    parser.add_argument("--home", default=None, help="AOC 数据目录（默认 %%LOCALAPPDATA%%/AOC）")
    parser.add_argument("--url", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--pid", type=int, default=None)
    parser.add_argument("--minutes", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--out", default="out/simlink-mem.csv")
    args = parser.parse_args()

    home = Path(args.home) if args.home else default_home()
    runtime_path = Path(args.runtime) if args.runtime else home / "simlink-runtime.json"
    runtime = read_runtime(runtime_path)
    url = args.url or runtime.get("url")
    token = args.token or runtime.get("token")
    pid = args.pid or runtime.get("pid")
    if not url or not token or not pid:
        raise SystemExit("runtime.json 缺少 url/token/pid；用 --url/--token/--pid 补上")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    interval = max(1.0, args.interval)
    deadline = time.monotonic() + max(1.0, args.minutes * 60)
    started = datetime.now()
    print(f"pid={pid} url={url} interval={interval}s duration={args.minutes}min -> {out}")

    rows: list[dict[str, float]] = []
    ws_points: list[tuple[float, float]] = []
    t0 = time.monotonic()
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time", "elapsed_s", "ws_mb", "pm_mb", "threads", "recording",
                         "sim_connected", "samples", "events", "phase", "reconnect_attempts", "error"])
        while time.monotonic() < deadline:
            _, ws, pm, threads = sample_process(int(pid))
            status = sample_status(url, token)
            elapsed = time.monotonic() - t0
            writer.writerow([
                datetime.now().strftime("%H:%M:%S"), f"{elapsed:.0f}", f"{ws:.1f}", f"{pm:.1f}",
                threads, bool(status.get("recording")), bool(status.get("sim_connected")),
                status.get("samples", ""), status.get("events", ""), status.get("phase", ""),
                status.get("reconnect_attempts", ""), status.get("error") or status.get("last_connect_error") or "",
            ])
            fh.flush()
            rows.append({"ws": ws, "pm": pm, "threads": threads,
                         "recording": bool(status.get("recording")),
                         "sim": bool(status.get("sim_connected"))})
            ws_points.append((elapsed, ws))
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(interval, remaining))

    if not rows:
        print("没有采到样本")
        return 1
    ws = [r["ws"] for r in rows]
    recorded = [r["ws"] for r in rows if r["recording"]]
    connected = [r["ws"] for r in rows if r["sim"]]
    growth = slope_per_hour(ws_points)
    print(f"started {started:%Y-%m-%d %H:%M:%S} · samples={len(rows)}")
    print(f"工作集：峰值 {max(ws):.1f} MB · 平均 {sum(ws) / len(ws):.1f} MB "
          f"· 线性趋势 {growth:+.1f} MB/h")
    if connected:
        print(f"连上模拟器：峰值 {max(connected):.1f} MB · 平均 {sum(connected) / len(connected):.1f} MB")
    if recorded:
        print(f"录制中：峰值 {max(recorded):.1f} MB · 平均 {sum(recorded) / len(recorded):.1f} MB")
    print("判据：未连接 < 60 MB；连上未录制 < 80 MB；录制稳态 < 100 MB 且 |趋势| ≤ 5 MB/h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
