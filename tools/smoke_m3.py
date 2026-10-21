"""M3 冒烟：真实 HTTP 起服务端 → 管理员建号 → 两位飞行员抽班 → 落地结算 → 复核 → 同步。

用法：
    python -X utf8 tools/smoke_m3.py
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

import httpx

ROOT = Path(__file__).resolve().parents[1]
ADMIN = "admin"
ADMIN_PASSWORD = "aoc-smoke-admin"
PILOT_PASSWORD = "pilot12345"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_health(base: str, timeout: float = 40.0) -> dict:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            res = httpx.get(f"{base}/health", timeout=2.0)
            if res.status_code == 200:
                return res.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(0.4)
    raise RuntimeError(f"服务端未就绪：{last}")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ok  {message}")


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="aoc-m3-smoke-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "AOC_DATABASE_URL": f"sqlite+pysqlite:///{(home / 'smoke.sqlite').as_posix()}",
        "AOC_SECRET": "smoke-secret-" + "x" * 40,
        "AOC_BOOTSTRAP_PASSWORD": ADMIN_PASSWORD,
        "AOC_SEED_DEMO": "1",
        "AOC_ADMIN_STATIC_DIR": str(ROOT / "apps" / "admin-web" / "dist"),
        "PYTHONUTF8": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "apps" / "server" / "main.py"),
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    try:
        health = wait_health(base)
        print(f"aoc-server {health['version']} @ {base}")
        admin = httpx.Client(base_url=base, timeout=20.0)
        res = admin.post("/api/v1/admin/auth/login",
                         json={"username": ADMIN, "password": ADMIN_PASSWORD})
        check(res.status_code == 200, "管理员登录")
        admin.headers["X-CSRF-Token"] = res.json()["csrf_token"]
        for name in ("smoke1", "smoke2"):
            res = admin.post("/api/v1/admin/users", json={
                "username": name, "password": PILOT_PASSWORD, "role": "PILOT"})
            check(res.status_code == 200, f"创建飞行员 {name}")

        pilot = httpx.Client(base_url=base, timeout=20.0)
        res = pilot.post("/api/v1/auth/login",
                         json={"username": "smoke1", "password": PILOT_PASSWORD})
        check(res.status_code == 200, "飞行员登录")
        pilot.headers["Authorization"] = f"Bearer {res.json()['access_token']}"
        flights = pilot.get("/api/v1/flights", params={"status": "SCHEDULED", "limit": 10}).json()
        check(len(flights) >= 1, f"服务端航班 {len(flights)} 班")
        target = flights[0]
        roster = pilot.post("/api/v1/roster/draw",
                            json={"flight_ids": [target["id"]], "max_legs": 1},
                            headers={"Idempotency-Key": f"smoke-{target['id']}"}).json()
        leg = roster["legs"][0]
        check(leg["status"] == "HELD", "抽班成功并加锁")
        sheet = pilot.get(f"/api/v1/flights/{leg['id']}/loadsheet").json()["loadsheet"]
        check(sheet["pax_total"] > 0, f"配载 {sheet['pax_total']} 人")
        check(pilot.post(f"/api/v1/flights/{leg['id']}/start").status_code == 200, "开始航段")
        check(pilot.post(f"/api/v1/flights/{leg['id']}/track", json={
            "chunks": [{"seq": 1, "points": [{"lat": 40.0, "lon": 116.5}]}]}).status_code == 200,
              "上传轨迹块")
        landed = pilot.post(f"/api/v1/flights/{leg['id']}/landing", json={
            "actual_dep_utc": leg["scheduled_dep_utc"],
            "actual_arr_utc": leg["scheduled_arr_utc"],
            "fuel_used_kg": 3000,
            "landing": {"vs_fpm": -170, "g_force": 1.32},
            "data_gap_seconds": 720,
        }).json()
        settlement = landed["settlement"]
        check(settlement["status"] == "SETTLED" and settlement["factor"] < 1.0,
              f"落地自动结算 factor={settlement['factor']}")
        ledger = pilot.get("/api/v1/ledger").json()
        credits = sum(e["amount"] for e in ledger["entries"] if e["direction"] == "CREDIT")
        debits = sum(e["amount"] for e in ledger["entries"] if e["direction"] == "DEBIT")
        check(abs(ledger["balance"] - (5_000_000 + credits - debits)) < 0.05, "账本对账 0 差异")

        # 第二位飞行员：抽班 → 管理员强制释放
        res = pilot.post("/api/v1/auth/login",
                         json={"username": "smoke2", "password": PILOT_PASSWORD})
        pilot2 = httpx.Client(base_url=base, timeout=20.0,
                              headers={"Authorization": f"Bearer {res.json()['access_token']}"})
        flights2 = pilot2.get("/api/v1/flights",
                              params={"status": "SCHEDULED", "limit": 10}).json()
        roster2 = pilot2.post("/api/v1/roster/draw",
                              json={"flight_ids": [flights2[0]["id"]], "max_legs": 1}).json()
        locks = admin.get("/api/v1/admin/ops/locks").json()
        check(len(locks) >= 1, "飞机锁可见")
        released = admin.post(f"/api/v1/admin/ops/locks/{roster2['lock']['id']}/release",
                              json={"reason": "smoke 强制释放"}).json()
        check(roster2["legs"][0]["id"] in released["released_flights"], "强制释放锁")

        # 复核：异常标记让结算 HELD → ACCEPT
        res = pilot2.post("/api/v1/roster/draw",
                          json={"flight_ids": [flights2[1]["id"]], "max_legs": 1})
        if res.status_code == 200:
            leg2 = res.json()["legs"][0]
            pilot2.post(f"/api/v1/flights/{leg2['id']}/start")
            held = pilot2.post(f"/api/v1/flights/{leg2['id']}/landing", json={
                "actual_dep_utc": leg2["scheduled_dep_utc"],
                "actual_arr_utc": leg2["scheduled_arr_utc"],
                "anomaly_flags": ["FUEL_JUMP"],
            }).json()["settlement"]
            check(held["status"] == "HELD", "异常结算进入 HELD")
            reviewed = admin.post(f"/api/v1/admin/ops/review/{held['id']}", json={
                "action": "WEIGHTED", "factor": 0.9, "reason": "smoke 复核"}).json()
            check(reviewed["status"] == "SETTLED", "复核后写账本")

        sync = pilot.get("/api/v1/sync", params={"cursor": 0}).json()
        check(sync["cursor"] > 0 and len(sync["events"]) > 0, "增量同步有事件")
        audit = admin.get("/api/v1/admin/audit", params={"limit": 200}).json()
        check(any(item["action"] == "SETTLEMENT_REVIEW" for item in audit), "复核写入审计")
        page = httpx.get(f"{base}/admin", timeout=10.0)
        check(page.status_code == 200 and "root" in page.text, "管理端 SPA 可加载")
        print(json.dumps({"balance": ledger["balance"], "cursor": sync["cursor"],
                          "audit": len(audit)}, ensure_ascii=False))
        print("M3 SMOKE PASS")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
