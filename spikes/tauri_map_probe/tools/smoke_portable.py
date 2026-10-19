"""便携包冒烟测试：解压 zip → 起本地服务 → 无头 Chrome 打开 → 读 FPS/画布/报错。

    python tools/smoke_portable.py
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP = sorted((ROOT / "out").glob("AOC-Map-Probe-portable-*.zip"))[-1]

def _blank_png() -> bytes:
    """生成 1x1 深色 PNG，用来顶掉 OSM 瓦片请求。"""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x0b\x12\x20", 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


BLANK_PNG = _blank_png()


def free_port(start: int) -> int:
    for port in range(start, start + 30):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("no free port")


def wait_ok(url: str, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def main() -> int:
    if not ZIP.is_file():
        raise SystemExit("先执行 python tools/make_portable.py")

    work = Path(tempfile.mkdtemp(prefix="aoc_portable_"))
    with zipfile.ZipFile(ZIP) as z:
        z.extractall(work)
    pkg = work / "AOC-Map-Probe"
    port = free_port(5211)
    url = f"http://127.0.0.1:{port}/index.html"

    server = subprocess.Popen(
        [sys.executable, "-X", "utf8", "server.py", "--no-browser", "--port", str(port)],
        cwd=pkg,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    facts: dict = {"zip": ZIP.name, "zip_kb": round(ZIP.stat().st_size / 1024, 1), "work": str(work)}
    try:
        facts["server_ok"] = wait_ok(url)
        if not facts["server_ok"]:
            facts["server_log"] = server.stdout.read().decode("utf-8", "replace")[-800:]
            raise SystemExit(json.dumps(facts, ensure_ascii=False, indent=2))

        from playwright.sync_api import sync_playwright

        errors: list[str] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=swiftshader"])
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.on("console", lambda m: errors.append(f"console:{m.type}:{m.text}") if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror:{e}"))
            # 断网场景下也要能回放：OSM 瓦片换成本地 1x1 透明 PNG，避免制造 404 噪声
            page.route(
                re.compile(r"tile\.openstreetmap\.org"),
                lambda r: r.fulfill(status=200, content_type="image/png", body=BLANK_PNG),
            )
            page.goto(url, wait_until="load", timeout=30000)
            page.wait_for_timeout(4000)
            facts["fps_text"] = page.inner_text(".badge")
            facts["canvas"] = page.locator("canvas").count()
            facts["title"] = page.title()
            page.screenshot(path=str(ROOT / "out" / "portable_smoke.png"))
            browser.close()

        fatal = [e for e in errors if e.startswith("pageerror:") or "TypeError" in e or "ReferenceError" in e]
        facts["console_errors"] = errors[:8]
        facts["fatal_errors"] = fatal[:5]
        fps = float(facts["fps_text"].split()[0])
        facts["fps"] = fps
        facts["ok"] = bool(facts["server_ok"] and facts["canvas"] >= 1 and fps >= 30 and not fatal)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    (ROOT / "out" / "portable_smoke.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(facts, ensure_ascii=False, indent=2))
    if zipfile.is_zipfile(ZIP):
        shutil.rmtree(work, ignore_errors=True)
    return 0 if facts.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
