"""aoc-core CPU 探针（TODO 第 9 条 / D-27）。

按固定间隔读 `aoc-core` 的累计 CPU 时间（Get-Process.CPU）与工作集，换算成
「单核百分比」，输出 CSV + 摘要，便于优化前后对比。

用法（Windows）：
    python tools/core_cpu_probe.py --minutes 5
    python tools/core_cpu_probe.py --pid 1234 --interval 2 --out out/core-cpu.csv

口径：`cpu_cores_pct = ΔCPU秒 / Δ墙钟秒 × 100`，即「单核百分比」；
任务管理器的占比是「单核百分比 / 逻辑核数」。
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

PS_SCRIPT = (
    "$p = Get-Process -Id __PID__ -ErrorAction Stop; "
    "'{0}|{1}|{2}|{3}' -f $p.CPU, $p.WorkingSet64, $p.PrivateMemorySize64, $p.Threads.Count"
)


def default_home() -> Path:
    return Path(os.environ.get("AOC_HOME")
                or Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "AOC")


def resolve_pid(pid: int | None, home: Path) -> int:
    if pid:
        return pid
    runtime = home / "runtime.json"
    try:
        return int(json.loads(runtime.read_text(encoding="utf-8"))["pid"])
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"读不到 {runtime} 的 pid；用 --pid 指定 aoc-core 进程") from exc


def sample(pid: int) -> tuple[float, float, float, int]:
    """返回 (CPU 累计秒, 工作集 MB, 私有内存 MB, 线程数)。"""
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


def main() -> int:
    parser = argparse.ArgumentParser(description="aoc-core CPU/内存采样（单核百分比）")
    parser.add_argument("--pid", type=int, default=None, help="aoc-core 进程号（默认读 runtime.json）")
    parser.add_argument("--home", default=None, help="AOC 数据目录（默认 %%LOCALAPPDATA%%/AOC）")
    parser.add_argument("--minutes", type=float, default=5.0, help="采样时长（分钟）")
    parser.add_argument("--interval", type=float, default=5.0, help="采样间隔（秒）")
    parser.add_argument("--out", default="out/core-cpu.csv", help="CSV 输出路径")
    args = parser.parse_args()

    home = Path(args.home) if args.home else default_home()
    pid = resolve_pid(args.pid, home)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(1.0, args.minutes * 60)
    interval = max(1.0, args.interval)

    cpu, _ws, _pm, _threads = sample(pid)
    t0 = time.monotonic()
    prev_cpu, prev_t = cpu, t0
    rows: list[dict[str, float]] = []
    started = datetime.now()
    print(f"pid={pid} interval={interval}s duration={args.minutes}min -> {out}")

    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time", "elapsed_s", "cpu_cores_pct", "ws_mb", "pm_mb", "threads"])
        while time.monotonic() < deadline:
            time.sleep(interval)
            try:
                cpu, ws, pm, threads = sample(pid)
            except SystemExit as exc:
                print(f"采样终止：{exc}")
                break
            now = time.monotonic()
            dt = max(1e-6, now - prev_t)
            cores = max(0.0, (cpu - prev_cpu) / dt * 100.0)
            prev_cpu, prev_t = cpu, now
            elapsed = now - t0
            writer.writerow([datetime.now().strftime("%H:%M:%S"), f"{elapsed:.1f}",
                             f"{cores:.3f}", f"{ws:.1f}", f"{pm:.1f}", threads])
            fh.flush()
            rows.append({"cores": cores, "ws": ws, "pm": pm, "threads": threads})

    if not rows:
        print("没有采到样本")
        return 1
    cores = [r["cores"] for r in rows]
    ws = [r["ws"] for r in rows]
    avg = sum(cores) / len(cores)
    peak = max(cores)
    print(f"started {started:%Y-%m-%d %H:%M:%S} · samples={len(rows)}")
    print(f"CPU（单核%）：平均 {avg:.3f}% · 峰值 {peak:.3f}%")
    print(f"工作集：平均 {sum(ws) / len(ws):.1f} MB · 峰值 {max(ws):.1f} MB · 线程 {rows[-1]['threads']}")
    print("判据（TODO 第 9 条）：空闲 5min 平均 < 0.3%（单核）；录制中平均 < 1.5%、峰值 < 5%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
