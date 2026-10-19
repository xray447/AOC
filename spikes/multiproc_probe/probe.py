"""V-10 探针：前端 + 后端 + 采集器三进程握手、健康检查、崩溃重启与数据补齐。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
PORT_BE, PORT_WEB = 8011, 8012
BE = f"http://127.0.0.1:{PORT_BE}"
WEB = f"http://127.0.0.1:{PORT_WEB}"
STALE = 1.0
BATCHES = 14
PER_BATCH = 20
PY = [sys.executable, "-X", "utf8"]

client = httpx.Client(timeout=3.0)


def spawn(name: str, args: list[str]) -> subprocess.Popen:
    log = open(OUT / f"{name}.log", "w", encoding="utf-8")
    return subprocess.Popen(
        args, cwd=str(HERE), stdout=log, stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def wait_json(url: str, limit: float = 15.0) -> dict | None:
    end = time.time() + limit
    while time.time() < end:
        try:
            r = client.get(url, timeout=1.0)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(0.15)
    return None


def start_backend() -> subprocess.Popen:
    return spawn("backend", PY + [
        str(HERE / "backend" / "app.py"),
        "--port", str(PORT_BE), "--db", str(OUT / "state.db"), "--stale", str(STALE),
    ])


def start_web() -> subprocess.Popen:
    return spawn("webserve", PY + [
        str(HERE / "webserve.py"), "--port", str(PORT_WEB), "--backend", BE,
    ])


def start_collector(fid: str) -> subprocess.Popen:
    return spawn(f"collector_{fid}", PY + [
        str(HERE / "collector.py"), "--backend", BE, "--fid", fid,
        "--batches", str(BATCHES), "--interval", "0.2",
        "--ack-file", str(OUT / f"ack_{fid}.json"),
    ])


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    checks: dict[str, bool] = {}
    facts: dict[str, object] = {}
    procs: list[subprocess.Popen] = []

    try:
        backend = start_backend()
        web = start_web()
        procs += [backend, web]

        h = wait_json(f"{BE}/health")
        checks["backend_health_ok"] = bool(h and h.get("ok"))
        wait_json(f"{WEB}/health")
        try:
            checks["web_index_ok"] = 'id="root"' in client.get(f"{WEB}/").text
        except Exception:
            checks["web_index_ok"] = False
        proxy = wait_json(f"{WEB}/health")
        checks["web_same_origin_proxy_ok"] = bool(proxy and proxy.get("ok"))
        checks["frontend_sees_backend"] = bool(proxy and proxy.get("db"))

        # --- 阶段 A：采集开始后被强杀 ---
        col = start_collector("V10")
        procs.append(col)
        time.sleep(0.7)
        col.kill()
        col.wait(timeout=10)
        partial = client.get(f"{BE}/api/flights/V10").json()
        facts["batches_before_crash"] = partial["batches"]
        checks["partial_ingest_before_crash"] = 0 < partial["batches"] < BATCHES

        time.sleep(1.6)
        h = client.get(f"{BE}/health").json()
        facts["collector_state_after_crash"] = h["collector"]["state"]
        facts["last_seen_age_s"] = h["collector"]["last_seen_age_s"]
        checks["collector_offline_detected"] = h["collector"]["state"] == "offline"

        # --- 阶段 B：重启采集器，从 ack 续传 ---
        ack_before = json.loads((OUT / "ack_V10.json").read_text(encoding="utf-8"))["acked_seq"]
        col2 = start_collector("V10")
        procs.append(col2)
        rc = col2.wait(timeout=40)
        summary = {}
        try:
            lines = [ln for ln in (OUT / "collector_V10.log").read_text(encoding="utf-8").splitlines() if ln.strip()]
            summary = json.loads(lines[-1])
        except Exception:
            summary = {}
        facts["collector_restart_summary"] = summary
        facts["ack_before_restart"] = ack_before
        checks["collector_restart_exit_ok"] = rc == 0
        checks["collector_resumed_from_ack"] = summary.get("resumed_from") == ack_before and ack_before >= 0

        fl = client.get(f"{BE}/api/flights/V10").json()
        facts["flight_V10"] = fl
        checks["no_gap_after_restart"] = (
            fl["batches"] == BATCHES and fl["points"] == BATCHES * PER_BATCH and fl["contiguous"]
        )
        checks["idempotent_no_double_count"] = fl["points"] == BATCHES * PER_BATCH

        dup = client.post(
            f"{BE}/api/flights/V10/samples",
            json={
                "seq": 0,
                "points": [
                    {"t": round(i * 0.125, 3), "lat": 35.55, "lon": 139.78, "alt": 4000 - i * 3.0}
                    for i in range(PER_BATCH)
                ],
            },
        ).json()
        facts["duplicate_replay"] = dup
        checks["duplicate_batch_deduped"] = dup["accepted"] == 0 and dup["dup"] == 1 and dup["total"] == BATCHES

        # --- 阶段 C：后端崩溃重启，采集器不得退出且能续传 ---
        col3 = start_collector("V10B")
        procs.append(col3)
        time.sleep(0.7)
        backend.kill()
        backend.wait(timeout=10)
        time.sleep(1.2)
        checks["collector_survives_backend_down"] = col3.poll() is None
        down = None
        try:
            client.get(f"{BE}/health", timeout=1.0)
            down = False
        except Exception:
            down = True
        checks["backend_down_confirmed"] = bool(down)

        backend2 = start_backend()
        procs.append(backend2)
        h2 = wait_json(f"{BE}/health", 20.0)
        checks["backend_restarted_ok"] = bool(h2 and h2.get("uptime_s", 99) < 30)
        facts["restart_uptime_s"] = h2.get("uptime_s") if h2 else None

        rc3 = col3.wait(timeout=45)
        fl_b = client.get(f"{BE}/api/flights/V10B").json()
        facts["flight_V10B"] = fl_b
        checks["collector_completed_after_backend_restart"] = rc3 == 0
        checks["second_flight_complete"] = (
            fl_b["batches"] == BATCHES and fl_b["points"] == BATCHES * PER_BATCH and fl_b["contiguous"]
        )

        fl_a = client.get(f"{BE}/api/flights/V10").json()
        checks["data_persisted_across_backend_restart"] = fl_a["batches"] == BATCHES and fl_a["contiguous"]
        checks["web_still_ok_after_backend_restart"] = wait_json(f"{WEB}/health", 5.0) is not None
        checks["sessions_tracked"] = client.get(f"{BE}/health").json()["sessions"] >= 3

        # --- 阶段 D：10 次冷启动（含端口快速复用） ---
        backend2.kill()
        backend2.wait(timeout=10)
        startups: list[dict] = []
        for _ in range(10):
            p = start_backend()
            procs.append(p)
            t0 = time.time()
            h = wait_json(f"{BE}/health", 10.0)
            startups.append({"ok": bool(h), "ready_s": round(time.time() - t0, 3)})
            p.kill()
            p.wait(timeout=10)
        facts["startups"] = startups
        facts["startup_max_s"] = max(s["ready_s"] for s in startups)
        checks["ten_startups_ten_ok"] = all(s["ok"] for s in startups)
        checks["no_port_conflict"] = all(s["ready_s"] < 3.0 for s in startups)

        backend3 = start_backend()
        procs.append(backend3)
        checks["final_backend_recover_ok"] = wait_json(f"{BE}/health", 10.0) is not None

    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
        client.close()

    report = {
        "probe": "V-10 三进程握手与崩溃恢复",
        "checks": checks,
        "facts": facts,
        "all_pass": bool(checks) and all(checks.values()),
        "notes": [
            "后端为独立 uvicorn 进程，SQLite 落盘；杀进程后重启数据仍在。",
            "采集器按 ack 文件续传，重复批次由主键 INSERT OR IGNORE 去重，不产生重复点数。",
            "前端经同源反代访问 /health 与 /api，等价于 Tauri 生产形态（自定义协议/本地端口）。",
            "心跳超时判定 online/offline（1s），生产应放宽到 3~5s 并加序列号单调性校验。",
        ],
    }
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# V-10 三进程探针报告（自动生成）", "", "| 检查项 | 结果 |", "|---|---|"]
    lines += [f"| {k} | {'PASS' if v else 'FAIL'} |" for k, v in checks.items()]
    lines += ["", f"**总结果：{'PASS' if report['all_pass'] else 'FAIL'}**"]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
