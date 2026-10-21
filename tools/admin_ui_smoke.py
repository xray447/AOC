"""管理端 UI 冒烟：起 aoc-server → Playwright 登录 → 遍历管理端页面并抓 JS 异常。

前置：`cd apps/admin-web && npm run build`
用法：python -X utf8 tools/admin_ui_smoke.py
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ADMIN_PASSWORD = "aoc-ui-admin"
PAGES = [
    ("/admin", "公司余额"),
    ("/admin/company", "公司档案"),
    ("/admin/economy", "经济参数"),
    ("/admin/policy", "异常与结算策略"),
    ("/admin/fleet", "机型模板"),
    ("/admin/network", "航线与班期"),
    ("/admin/ops", "运行监控"),
    ("/admin/users", "用户与邀请码"),
    ("/admin/audit", "审计日志"),
    ("/admin/system", "服务"),
]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_health(base: str, seconds: float = 40.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/health", timeout=2.0).status_code == 200:
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
    raise TimeoutError("aoc-server 未就绪")


def main() -> int:
    dist = ROOT / "apps" / "admin-web" / "dist" / "index.html"
    if not dist.is_file():
        raise SystemExit("请先构建管理端：cd apps/admin-web && npm run build")
    home = Path(tempfile.mkdtemp(prefix="aoc-admin-ui-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "AOC_DATABASE_URL": f"sqlite+pysqlite:///{(home / 'ui.sqlite').as_posix()}",
        "AOC_SECRET": "ui-secret-" + "x" * 40,
        "AOC_BOOTSTRAP_PASSWORD": ADMIN_PASSWORD,
        "AOC_SEED_DEMO": "1",
        "AOC_ADMIN_STATIC_DIR": str(ROOT / "apps" / "admin-web" / "dist"),
    }
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "apps" / "server" / "main.py"),
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    errors: list[str] = []
    try:
        wait_health(base)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
            page.on("console", lambda msg: errors.append(f"console: {msg.text}")
                    if msg.type == "error" else None)
            page.goto(f"{base}/admin/login", wait_until="networkidle")
            page.fill("#username", "admin")
            page.fill("#password", ADMIN_PASSWORD)
            page.click("button[type=submit]")
            page.wait_for_selector("text=公司余额", timeout=20000)
            # 登录页加载时 /admin/auth/me 的 401 是预期行为（未登录探测），登录成功后清空。
            errors.clear()
            print("  ok  管理端登录")
            for path, marker in PAGES:
                page.goto(f"{base}{path}", wait_until="networkidle")
                page.wait_for_selector(f"text={marker}", timeout=15000)
                print(f"  ok  {path} ({marker})")
            browser.close()
        if errors:
            print("\n".join(errors))
            raise AssertionError(f"管理端出现 {len(errors)} 条 JS 异常")
        print(f"ADMIN UI SMOKE PASS（{len(PAGES)} 个页面，js errors: 0）")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
