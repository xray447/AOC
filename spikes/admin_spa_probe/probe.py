"""V-09 探针：登录、CSRF、角色隔离、分组表单读写、SPA 静态页。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app import DEFAULT_PROFILE, app  # noqa: E402

OUT = HERE / "out"
PROFILE = {
    "min_fl": 300, "max_fl": 400,
    "route_provider_order": ["AIP", "SIMBRIEF", "GRAPH"],
    "coverage_ignore_below_nm": 250,
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}

    with TestClient(app, base_url="http://test") as c:
        r = c.get("/api/session")
        results["anonymous_401"] = r.status_code == 401

        r = c.post("/api/login", json={"username": "admin", "password": "wrong"})
        results["bad_password_401"] = r.status_code == 401

        r = c.post("/api/login", json={"username": "pilot", "password": "pilot123"})
        pilot_login = r.status_code == 200
        csrf_pilot = r.json().get("csrf", "") if pilot_login else ""
        results["pilot_login_ok"] = pilot_login and r.json().get("role") == "pilot"
        set_cookie = r.headers.get("set-cookie", "")
        results["session_cookie_httponly"] = "aoc_session=" in set_cookie and "HttpOnly" in set_cookie

        r = c.get("/api/network-profile")
        results["pilot_can_read_profile"] = r.status_code == 200
        r = c.put("/api/network-profile", json=PROFILE, headers={"x-csrf-token": csrf_pilot})
        results["pilot_write_403"] = r.status_code == 403
        c.post("/api/logout")

        t0 = time.perf_counter()
        r = c.post("/api/login", json={"username": "admin", "password": "admin123"})
        login_ms = round((time.perf_counter() - t0) * 1000, 2)
        csrf = r.json().get("csrf", "")
        results["admin_login_ok"] = r.status_code == 200 and r.json().get("role") == "admin"

        r = c.put("/api/network-profile", json=PROFILE)
        results["write_without_csrf_403"] = r.status_code == 403

        r = c.put("/api/network-profile", json=PROFILE, headers={"x-csrf-token": "forged"})
        results["write_forged_csrf_403"] = r.status_code == 403

        r = c.put("/api/network-profile", json=PROFILE, headers={"x-csrf-token": csrf})
        results["admin_write_ok"] = r.status_code == 200 and r.json().get("max_fl") == 400

        r = c.get("/api/network-profile")
        stored = r.json()
        results["write_persisted"] = stored["min_fl"] == 300 and stored["updated_by"] == "admin"

        r = c.put("/api/network-profile",
                  json={**PROFILE, "min_fl": 420, "max_fl": 410},
                  headers={"x-csrf-token": csrf})
        results["invalid_range_422"] = r.status_code == 422

        r = c.post("/api/network-profile/reset", headers={"x-csrf-token": csrf})
        results["reset_ok"] = r.status_code == 200 and r.json()["min_fl"] == DEFAULT_PROFILE["min_fl"]
        results["reset_persisted"] = c.get("/api/network-profile").json()["max_fl"] == DEFAULT_PROFILE["max_fl"]

        r = c.post("/api/logout")
        results["logout_invalidates"] = c.get("/api/network-profile").status_code == 401

        r = c.get("/")
        results["spa_index_ok"] = r.status_code == 200 and 'id="root"' in r.text

    report = {
        "probe": "V-09 admin SPA",
        "checks": results,
        "login_ms": login_ms,
        "all_pass": all(results.values()),
        "notes": [
            "密码用 PBKDF2 演示存储，生产需换 Argon2 并接真实用户表。",
            "Session 为服务端内存表，重启即失效；正式实现按架构文档走 SQLite。",
            "CSRF 使用双提交 Cookie + 自定义头，写接口缺一即 403。",
        ],
    }
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# V-09 管理端探针报告（自动生成）", "", f"- 登录耗时：{login_ms}ms", "",
             "| 检查项 | 结果 |", "|---|---|"]
    lines += [f"| {k} | {'PASS' if v else 'FAIL'} |" for k, v in results.items()]
    lines += ["", f"**总结果：{'PASS' if report['all_pass'] else 'FAIL'}**"]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
