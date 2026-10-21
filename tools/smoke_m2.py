"""M2 端到端冒烟：抽班 → 锁机 → 开始航段 → SimLink demo 飞行 → 自动结算 → 账本对账。

用法：
    python -X utf8 tools/smoke_m2.py

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
    home = Path(tempfile.mkdtemp(prefix="aoc-smoke-m2-"))
    navdata = build_navdata(home / "navdata.sqlite")
    simlink = ROOT / "apps" / "simlink" / "bin" / "Debug" / "net8.0" / "aoc-simlink.exe"
    if not simlink.exists():
        print(f"缺少 SimLink 构建：{simlink}\n先执行 dotnet build apps/simlink")
        return 2
    env = {**os.environ, "AOC_HOME": str(home)}
    print(f"home={home}")
    sl_log = open(home / "simlink-smoke.log", "w", encoding="utf-8")
    sl = None
    core = None
    core_log = None
    try:
        port = free_port()
        token = "smoke-token"
        core_log = open(home / "core-smoke.log", "w", encoding="utf-8")
        core = subprocess.Popen([sys.executable, "-X", "utf8", str(ROOT / "apps" / "aoc-core" / "main.py"),
                                 "--port", str(port), "--token", token, "--home", str(home),
                                 "--static-dir", str(ROOT / "apps" / "client" / "dist")],
                                env=env, stdout=core_log, stderr=subprocess.STDOUT, text=True)
        wait_port(port)
        base = f"http://127.0.0.1:{port}"
        assert get(f"{base}/local/health")["ok"]
        get(f"{base}/local/settings", token, "PUT", {"navdata_path": str(navdata)})
        nav = get(f"{base}/local/navdata/status", token)
        assert nav["available"], nav
        print(f"navdata OK: AIRAC {nav['airac']} / {nav['airports']} airports")

        seed = get(f"{base}/local/ops/seed", token, "POST", {})
        assert seed["seeded"], seed
        print(f"ops seed: aircraft={seed['aircraft']} instances={seed['instances']}")

        draw = get(f"{base}/local/ops/rosters/draw", token, "POST", {
            "base_airport": "ZBAA", "max_legs": 1, "window_hours": 168,
            "max_block_minutes": 480, "min_turnaround_min": 45,
        })
        candidates = draw["candidates"]
        assert candidates, "抽不到候选"
        index = next((i for i, c in enumerate(candidates)
                      if c["legs"][0]["dep"] == "ZBAA" and c["legs"][0]["arr"] == "ZSSS"), 0)
        chosen = candidates[index]
        print(f"candidate: {chosen['aircraft']['registration']} "
              f"{[leg['flight_number'] for leg in chosen['legs']]} score={chosen['score']}")
        roster = get(f"{base}/local/ops/rosters/confirm", token, "POST", {
            "candidate_token": chosen["candidate_token"], "candidate_index": index,
        })
        assert roster["status"] == "LOCKED", roster
        fleet = get(f"{base}/local/ops/fleet", token)["items"]
        aircraft = next(a for a in fleet if a["id"] == roster["aircraft_id"])
        assert aircraft["status"] == "HELD" and aircraft["locked"], aircraft
        assert all(c["aircraft"]["id"] != aircraft["id"]
                   for c in get(f"{base}/local/ops/rosters/draw", token, "POST",
                                {"window_hours": 168, "max_legs": 1})["candidates"])
        print(f"roster LOCKED, aircraft {aircraft['registration']} held and unavailable to other draws")

        started = get(f"{base}/local/ops/rosters/{roster['id']}/legs/1/start", token, "POST")
        task = started["task"]
        load = started["load_sheet"]
        assert load["pax_total"] >= 0
        print(f"leg started: flight_record={task['flight_record_id'][:8]} "
              f"pax={load['pax_total']} est_revenue={load['estimated_revenue']}")

        # 先开始航段再启动 SimLink，确保自动录制的记录能绑定到该任务
        # 2x 加速：仍低于默认策略的「>8x 拒绝」阈值，便于验证正常结算链路
        sl = subprocess.Popen([str(simlink), "--demo", "--demo-speed", "2", "--port", "0",
                               "--home", str(home)], env=env,
                              stdout=sl_log, stderr=subprocess.STDOUT, text=True)
        runtime_file = home / "simlink-runtime.json"
        for _ in range(100):
            if runtime_file.exists():
                break
            time.sleep(0.2)
        sl_runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
        print(f"simlink started at {sl_runtime['url']}")

        deadline = time.time() + 240
        settlement = None
        while time.time() < deadline:
            try:
                settlement = get(f"{base}/local/ops/flights/{task['flight_record_id']}/settlement", token)
                break
            except Exception:  # noqa: BLE001
                rec = get(f"{base}/local/recording/status", token)
                if rec.get("active"):
                    print(f"recording: phase={rec['phase']} samples={rec['samples']}")
                time.sleep(2.0)
        assert settlement, "超时：没有生成结算"
        print(f"settlement: {settlement['status']} action={settlement['policy_action']} "
              f"factor={settlement['payout_factor']} revenue={settlement['revenue_total']} "
              f"cost={settlement['cost_total']} profit={settlement['profit']}")
        assert settlement["status"] in ("SETTLED", "HELD"), settlement
        assert len(settlement["breakdown"]["costs"]) >= 6, settlement["breakdown"]["costs"]
        ledger = get(f"{base}/local/ops/ledger", token)
        assert ledger["reconciled"], ledger
        print(f"ledger reconciled, balance={ledger['balance']} entries={len(ledger['items'])}")

        roster_after = get(f"{base}/local/ops/rosters/{roster['id']}", token)
        assert roster_after["status"] == "COMPLETED", roster_after["status"]
        assert roster_after["legs"][0]["status"] == "COMPLETED"
        fleet = get(f"{base}/local/ops/fleet", token)["items"]
        aircraft = next(a for a in fleet if a["id"] == roster["aircraft_id"])
        assert aircraft["status"] == "ACTIVE", aircraft["status"]
        print(f"roster COMPLETED, aircraft released at {aircraft['current_airport_icao']}")
        print("OK: M2 smoke passed")
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
