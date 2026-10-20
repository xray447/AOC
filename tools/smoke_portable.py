"""便携 ZIP 冒烟：解压 → start.bat（demo SimLink）→ 校验 API/静态页/一次自动记录。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "packages" / "aoc_navdata"),
                str(ROOT / "packages" / "aoc_core"), str(ROOT / "packages" / "aoc_protocol")]
from conftest import build_navdata  # noqa: E402


def get(url: str, token: str | None = None, method: str = "GET", body: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-AOC-Token"] = token
    req = Request(url, data=json.dumps(body).encode() if body is not None else None,
                  headers=headers, method=method)
    with urlopen(req, timeout=5) as resp:
        return json.loads(resp.read() or b"{}")


def main() -> int:
    zip_path = next((ROOT / "out").glob("AOC-portable-*-win64.zip"), None)
    if zip_path is None:
        print("找不到便携 zip，先运行 python tools/make_portable.py")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="aoc-portable-"))
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmp)
    root = tmp  # zip 内是 app/apps/data/packages 的根层
    aoc_home = tmp / "aoc-home"
    aoc_home.mkdir()
    navdata = build_navdata(aoc_home / "navdata.sqlite")
    env = {**os.environ, "AOC_HOME": str(aoc_home), "AOC_SIMLINK_ARGS": "--demo --demo-speed 12",
           "AOC_NO_BROWSER": "1"}
    log = open(tmp / "start.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-X", "utf8", str(root / "start.py")], cwd=root, env=env,
                            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        runtime_file = aoc_home / "runtime.json"
        for _ in range(150):
            if runtime_file.exists():
                break
            time.sleep(0.2)
        runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
        base, token = runtime["url"], runtime["token"]
        print(f"portable core: {base}")

        for _ in range(50):
            try:
                health = get(f"{base}/local/health")
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise TimeoutError("core 未启动")
        assert health["ok"]
        get(f"{base}/local/settings", token, "PUT", {"navdata_path": str(navdata), "onboarded": True})
        html = urlopen(f"{base}/", timeout=5).read().decode()
        assert '<div id="root">' in html

        flight = None
        deadline = time.time() + 70
        while time.time() < deadline:
            items = get(f"{base}/local/flights?limit=5", token)["items"]
            done = [f for f in items if f["status"] != "RECORDING"]
            if done:
                flight = done[0]
                break
            time.sleep(1)
        assert flight, "便携包 demo 未生成飞行记录"
        assert flight["status"] == "COMPLETED", flight
        assert flight["track_points"] > 0
        assert flight["dep_icao"] == "ZBAA" and flight["arr_icao"] == "ZSSS", flight
        print(f"portable flight: {flight['dep_icao']}->{flight['arr_icao']} "
              f"points={flight['track_points']} rwy={flight['runway_ident']} vs={flight['touchdown_vs_fpm']}")
        print(f"zip={zip_path.name} size={zip_path.stat().st_size / 1024 / 1024:.1f} MB")
        print("OK: portable smoke passed")
        return 0
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
