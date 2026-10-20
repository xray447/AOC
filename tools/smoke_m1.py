"""M1 端到端冒烟：SimLink demo → aoc-core 自动记录 → 飞行日志/轨迹/导出。

用法：
    python -X utf8 tools/smoke_m1.py

不依赖 MSFS：SimLink 用 --demo 合成一次 ZBAA→ZSSS 飞行。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "packages" / "aoc_protocol"), str(ROOT / "packages" / "aoc_navdata"),
                str(ROOT / "packages" / "aoc_core"), str(ROOT / "packages" / "aoc_route"),
                str(ROOT / "packages" / "aoc_integrations"), str(ROOT / "tests")]

from conftest import build_navdata  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str, token: str | None = None, method: str = "GET", body: dict | None = None,
        timeout: float = 5.0) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-AOC-Token"] = token
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def wait_port(port: int, seconds: float = 30) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"port {port} not ready")


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="aoc-smoke-"))
    navdata = build_navdata(home / "navdata.sqlite")
    simlink = ROOT / "apps" / "simlink" / "bin" / "Debug" / "net8.0" / "aoc-simlink.exe"
    if not simlink.exists():
        print(f"缺少 SimLink 构建：{simlink}\n先执行 dotnet build apps/simlink")
        return 2
    env = {**os.environ, "AOC_HOME": str(home)}
    print(f"home={home}")
    sl_log = open(home / "simlink-smoke.log", "w", encoding="utf-8")
    sl = subprocess.Popen([str(simlink), "--demo", "--demo-speed", "12", "--port", "0",
                           "--home", str(home)], env=env,
                          stdout=sl_log, stderr=subprocess.STDOUT, text=True)
    core = None
    core_log = None
    try:
        runtime_file = home / "simlink-runtime.json"
        for _ in range(100):
            if runtime_file.exists():
                break
            time.sleep(0.2)
        sl_runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
        print(f"simlink={sl_runtime['url']}")

        port = free_port()
        token = "smoke-token"
        core_log = open(home / "core-smoke.log", "w", encoding="utf-8")
        core = subprocess.Popen([sys.executable, "-X", "utf8", str(ROOT / "apps" / "aoc-core" / "main.py"),
                                 "--port", str(port), "--token", token, "--home", str(home),
                                 "--static-dir", str(ROOT / "apps" / "client" / "dist"),
                                 "--simlink-url", sl_runtime["url"], "--simlink-token", sl_runtime["token"]],
                                env=env, stdout=core_log, stderr=subprocess.STDOUT, text=True)
        wait_port(port)
        base = f"http://127.0.0.1:{port}"
        health = get(f"{base}/local/health")
        assert health["ok"], health
        get(f"{base}/local/settings", token, "PUT", {"navdata_path": str(navdata)})
        nav = get(f"{base}/local/navdata/status", token)
        assert nav["available"], nav
        print(f"navdata OK: AIRAC {nav['airac']} / {nav['airports']} airports")

        deadline = time.time() + 90
        flight = None
        while time.time() < deadline:
            rec = get(f"{base}/local/recording/status", token)
            if rec.get("active"):
                print(f"recording: phase={rec['phase']} samples={rec['samples']}")
            flights = get(f"{base}/local/flights?limit=5", token)
            completed = [f for f in flights["items"] if f["status"] != "RECORDING"]
            if completed:
                flight = completed[0]
                break
            time.sleep(1.0)
        assert flight, "超时：没有生成飞行记录"
        print(f"flight: {flight['id']} {flight['dep_icao']}->{flight['arr_icao']} "
              f"status={flight['status']} vs={flight['touchdown_vs_fpm']} rwy={flight['runway_ident']} "
              f"points={flight['track_points']}")
        assert flight["status"] == "COMPLETED", flight
        assert flight["track_points"] > 0
        track = get(f"{base}/local/flights/{flight['id']}/track", token)
        assert track["points"], track
        gpx = urlopen(Request(f"{base}/local/flights/{flight['id']}/export?format=gpx",
                              headers={"X-AOC-Token": token}), timeout=10).read().decode()
        assert "<gpx" in gpx and "<trkpt" in gpx
        stats = get(f"{base}/local/stats", token)
        assert stats["flights"] == 1, stats
        html = urlopen(f"{base}/", timeout=5).read().decode()
        assert '<div id="root">' in html
        print(f"track points={track['total_points']} bytes={flight['track_bytes']} "
              f"fidelity={flight['track_fidelity_m']}m")
        print("OK: M1 smoke passed")
        return 0
    finally:
        for proc in (core, sl):
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        for handle in (core_log, sl_log):
            if handle:
                handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
