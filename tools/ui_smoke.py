"""浏览器冒烟：启动 aoc-core（静态 SPA）+ Playwright 打开各页面，抓 JS 异常并截图。"""
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

from aoc_core.paths import AppPaths  # noqa: E402
from aoc_core.service import PersonalService  # noqa: E402
from conftest import build_navdata, make_points  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port(port: int, seconds: float = 30) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(port)


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="aoc-ui-"))
    navdata = build_navdata(home / "navdata.sqlite")
    service = PersonalService(AppPaths.create(home))
    service.update_settings({"navdata_path": str(navdata), "home_airport": "ZBAA", "onboarded": True})
    service.flights.start(flight_id="ui-flight", started_at="2026-10-20T00:00:00Z", manual=True)
    service.flights.ingest(make_points())
    service.flights.stop()
    # 再加一条 Volanta 导入航段，验证地图上的橙色实线
    service.sync_volanta(csv_text="Date,Flight Number,Origin,Destination,Aircraft,Registration,Duration\n"
                                  "2026-10-12,JL101,RJTT,RJAA,A320,JA101J,90\n"
                                  "2026-10-13,JL102,RJTT,RJAA,A320,JA101J,90\n"
                                  "2026-10-14,JL103,RJTT,RJAA,A320,JA101J,90\n"
                                  "2026-10-15,JL104,RJTT,RJAA,A320,JA101J,90\n"
                                  "2026-10-16,JL105,RJTT,RJAA,A320,JA101J,90\n"
                                  "2026-10-19,JL106,RJTT,RJAA,A320,JA101J,90\n"
                                  "2026-10-20,JL107,RJAA,RJTT,A320,JA101J,90\n")
    # 带轨迹的导入航班（验证轨迹落库 + 地图轨迹图层）
    service.db.upsert_volanta_flight({
        "source": "VOLANTA", "external_id": "va-track-1", "callsign": "JL108",
        "registration": "JA108J",
        "dep_icao": "RJTT", "arr_icao": "RJAA", "flight_date": "2026-10-25",
        "aircraft_type": "A320", "duration_min": 90, "landing_rate_fpm": -120,
        "raw": {"id": "va-track-1"},
        "track": [[139.78, 35.55], [139.95, 35.62], [140.15, 35.70], [140.39, 35.76]],
    })
    import asyncio
    asyncio.run(service.close())

    port = free_port()
    token = "ui-token"
    log_path = home / "core.log"
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-X", "utf8", str(ROOT / "apps" / "aoc-core" / "main.py"),
                             "--port", str(port), "--token", token, "--home", str(home),
                             "--static-dir", str(ROOT / "apps" / "client" / "dist")],
                            env={**os.environ, "AOC_HOME": str(home)},
                            stdout=log, stderr=subprocess.STDOUT)
    errors: list[str] = []
    try:
        wait_port(port)
        base = f"http://127.0.0.1:{port}"
        req = Request(f"{base}/local/settings", method="GET", headers={"X-AOC-Token": token})
        assert json.loads(urlopen(req, timeout=5).read())["settings"]["onboarded"] is True

        seed_req = Request(f"{base}/local/ops/seed", method="POST", data=b"{}",
                           headers={"X-AOC-Token": token, "Content-Type": "application/json"})
        print("ops seed:", urlopen(seed_req, timeout=30).read().decode()[:200])

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
            page.on("console", lambda msg: errors.append(f"console: {msg.text}") if msg.type == "error" else None)

            page.goto(base, wait_until="networkidle")
            page.wait_for_selector("text=运行概览", timeout=15000)
            assert page.locator("text=数据源").count() > 0
            page.screenshot(path=str(ROOT / "out" / "m1_dashboard.png"), full_page=True)

            page.goto(f"{base}/recommend", wait_until="networkidle")
            page.wait_for_selector("text=去一个没去过的地方")
            page.click("button:has-text('推荐机场')")
            page.wait_for_selector(".airport-card", timeout=15000)

            page.goto(f"{base}/route?dep=ZBAA&arr=ZSSS", wait_until="networkidle")
            page.wait_for_selector("text=航路规划")
            page.click("button:has-text('生成航路')")
            page.wait_for_selector(".route-box", timeout=15000)
            assert "ZBAA" in page.locator(".route-box").inner_text()
            assert "RUM6A" in page.locator(".route-box").inner_text()

            page.goto(f"{base}/logs", wait_until="networkidle")
            page.wait_for_selector("text=飞行日志")
            page.wait_for_selector("text=ZBAA → ZSSS", timeout=10000)

            # 详情页含地图瓦片请求，用 networkidle 容易被外部瓦片拖死
            page.goto(f"{base}/logs/ui-flight", wait_until="domcontentloaded")
            try:
                page.wait_for_selector("text=轨迹回放", timeout=15000)
            except Exception:
                page.screenshot(path=str(ROOT / "out" / "m1_log_detail_fail.png"), full_page=True)
                print("ERRORS:", *errors[:10], sep="\n  ")
                print("BODY:", page.locator("body").inner_text()[:1500])
                raise
            page.locator(".track-controls button").first.click(timeout=10000)
            page.wait_for_timeout(800)
            page.locator(".track-controls button").first.click()
            page.screenshot(path=str(ROOT / "out" / "m1_log_detail.png"), full_page=True)

            page.goto(f"{base}/map", wait_until="domcontentloaded")
            page.wait_for_selector("text=飞行地图")
            page.wait_for_selector(".maplibregl-canvas", timeout=15000)
            page.wait_for_selector("text=航班记录")
            # 地图不应因 2s 轮询被反复重建：给 canvas 打标后等待两个轮询周期仍应存在
            page.evaluate("document.querySelector('.maplibregl-canvas').dataset.probe = 'keep'")
            page.wait_for_timeout(5000)
            assert page.evaluate("document.querySelectorAll('.maplibregl-canvas').length") == 1
            assert page.evaluate("document.querySelector('.maplibregl-canvas').dataset.probe") == "keep", \
                "地图画布在轮询后被重建"
            page.screenshot(path=str(ROOT / "out" / "m1_map.png"), full_page=True)

            # 点击 ZBAA 机场点，校验弹窗为灰底白字（不能白底白字）
            def project(lon: float, lat: float) -> tuple[float, float]:
                # 每次重新取 boundingBox：点按钮可能触发页面滚动，缓存会失效
                box = page.locator(".maplibregl-canvas").bounding_box()
                x, y = page.evaluate(
                    """([lon, lat]) => {
                        const el = document.querySelector('.maplibregl-map');
                        const p = el.__aocMap.project([lon, lat]);
                        return [p.x, p.y];
                    }""",
                    [lon, lat],
                )
                return box["x"] + x, box["y"] + y

            layers_ok = page.evaluate("""() => {
                const m = document.querySelector('.maplibregl-map').__aocMap;
                return {
                    arrow: !!m.getLayer('arrows'),
                    hit: !!m.getLayer('legs-hit'),
                    img: m.getLayoutProperty('arrows', 'icon-image'),
                    layers: m.getStyle().layers.map(l => l.id).join(','),
                };
            }""")
            ok = bool(layers_ok["arrow"]) and bool(layers_ok["hit"]) and layers_ok["img"] == "leg-arrow"
            if not ok:
                print("layers:", layers_ok)
                print("JS errors so far:", *errors[:10], sep="\n  ")
            assert ok, "方向箭头或点击热区未创建"

            # 点击 ZBAA→ZSSS 连线中点：验证加宽的点击热区（细线也能点中）
            ax, ay = project(116.5846, 40.0801)
            bx, by = project(121.3363, 31.1979)
            page.mouse.click((ax + bx) / 2, (ay + by) / 2)
            page.wait_for_selector("text=ZBAA ↔ ZSSS", timeout=8000)
            page.wait_for_timeout(300)
            page.get_by_role("button", name="清除筛选").first.click()
            # 关掉航段弹窗，避免挡住机场点的点击；按钮可能把页面滚走，回到顶部
            page.evaluate("document.querySelectorAll('.maplibregl-popup-close-button').forEach(b => b.click())")
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(300)

            mx, my = project(116.5846, 40.0801)  # ZBAA
            page.mouse.click(mx, my)
            page.wait_for_selector(".maplibregl-popup-content", timeout=8000)
            bg, fg = page.eval_on_selector(
                ".maplibregl-popup-content",
                "el => { const s = getComputedStyle(el); return [s.backgroundColor, s.color]; }")
            assert "30, 41, 59" in bg, f"弹窗背景不是灰底：{bg}"
            assert "248, 250, 252" in fg, f"弹窗文字不是白字：{fg}"
            page.wait_for_timeout(900)
            page.screenshot(path=str(ROOT / "out" / "m1_map_popup.png"), full_page=True)

            # 导入航班表格：列固定为 航班号/日期/航段/时长/接地率，且数据要跟 CSV 一致
            page.get_by_role("button", name="清除筛选").first.click()
            imported_card = page.locator(".ant-card", has_text="导入 / 补录航班")
            page.wait_for_selector("text=导入 / 补录航班")
            headers = [h for h in imported_card.locator(".ant-table-thead th").all_inner_texts() if h]
            assert headers == ["航班号", "日期", "航段", "机型", "时长", "接地率"], headers
            first_row = imported_card.locator("tbody tr", has_text="2026-10-12").first
            first_text = first_row.inner_text()
            assert "JL101" in first_text, first_text
            assert "A320" in first_text and "JA101J" in first_text, first_text
            # 点行加载轨迹（表格行本身就是“看轨迹”入口）
            imported_card.locator("tbody tr", has_text="2026-10-25").first.click()
            page.wait_for_selector("text=轨迹点", timeout=8000)
            page.wait_for_timeout(900)
            page.screenshot(path=str(ROOT / "out" / "m1_map_track.png"), full_page=True)

            # 反向航段：两条线各偏移 6px，应该两个方向都能单独点中
            page.locator(".maplibregl-canvas").scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            page.evaluate("""() => {
                const m = document.querySelector('.maplibregl-map').__aocMap;
                m.jumpTo({ center: [140.08, 35.65], zoom: 8 });
            }""")
            page.wait_for_timeout(900)
            sides = page.evaluate("""() => {
                const m = document.querySelector('.maplibregl-map').__aocMap;
                const a = m.project([139.78, 35.55]);
                const b = m.project([140.39, 35.76]);
                const ux = b.x - a.x, uy = b.y - a.y;
                const len = Math.hypot(ux, uy) || 1;
                const nx = -uy / len * 6, ny = ux / len * 6;
                const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
                return [[mx + nx, my + ny], [mx - nx, my - ny]];
            }""")
            picked = []
            for sx, sy in sides:
                box = page.locator(".maplibregl-canvas").bounding_box()
                page.mouse.click(box["x"] + sx, box["y"] + sy)
                page.wait_for_timeout(400)
                tags = page.locator(".ant-tag", has_text="↔").all_inner_texts()
                picked.append(tags[0] if tags else "")
                page.evaluate("document.querySelectorAll('.maplibregl-popup-close-button').forEach(b => b.click())")
            assert set(picked) == {"RJTT ↔ RJAA", "RJAA ↔ RJTT"}, f"反向航段应能分别选中：{picked}"

            page.goto(f"{base}/stats", wait_until="networkidle")
            page.wait_for_selector("text=统计")
            assert page.locator("text=总飞行").count() > 0

            page.goto(f"{base}/settings", wait_until="networkidle")
            page.wait_for_selector("text=数据源")

            # ---- M2 单机运营模式 ----
            page.goto(f"{base}/ops", wait_until="networkidle")
            page.wait_for_selector("text=运营中心", timeout=15000)
            # 本机档案在顶部（快捷入口已去掉），设置里的示例跟随输入联动
            assert page.locator("text=快捷入口").count() == 0
            assert page.locator("text=本机档案").count() > 0
            page.click("button:has-text('设置')")
            page.wait_for_selector("#callsign_prefix", timeout=10000)
            assert page.locator("text=AUV → AUV123").count() > 0
            assert page.locator("text=AOC → AOC101").count() > 0
            page.fill("#callsign_prefix", "abc")
            page.wait_for_selector("text=ABC → ABC123", timeout=5000)
            page.screenshot(path=str(ROOT / "out" / "m2_ops_home.png"), full_page=True)
            page.click(".ant-modal-close")

            page.goto(f"{base}/ops/fleet", wait_until="networkidle")
            page.wait_for_selector("text=逐机档案", timeout=15000)
            assert page.locator("text=B-1671").count() > 0

            page.goto(f"{base}/ops/network", wait_until="networkidle")
            page.wait_for_selector("text=航线与班期", timeout=15000)
            page.get_by_role("tab", name="班期").click()
            assert page.locator("text=AOC101").count() > 0

            page.goto(f"{base}/ops/roster", wait_until="networkidle")
            page.wait_for_selector("text=抽班条件", timeout=15000)
            page.click("button:has-text('抽班')")
            page.wait_for_selector("text=确认这个班", timeout=20000)
            page.screenshot(path=str(ROOT / "out" / "m2_ops_roster.png"), full_page=True)
            page.locator("button:has-text('确认这个班')").first.click()
            page.wait_for_selector("text=当前班表", timeout=15000)
            # 开始前有 SimBrief 入口（航班号 + 起降机场预填）
            assert page.locator("button:has-text('SimBrief')").count() > 0

            # SimBrief 走系统默认浏览器：拦截 open-external 请求，避免真的弹浏览器
            posted: list[str] = []

            def _stub_external(route):
                posted.append(route.request.post_data or "")
                route.fulfill(json={"ok": True, "url": "stubbed"})

            page.route("**/local/system/open-external", _stub_external)
            page.locator("button:has-text('SimBrief')").first.click()
            page.wait_for_timeout(800)
            assert posted, "SimBrief 未请求 open-external"
            assert "dispatch.simbrief.com" in posted[0]
            assert "orig=ZBAA" in posted[0]
            # 配载只带 kg 的 payload，且不预填高度
            assert "payload=" in posted[0]
            assert "reg=" in posted[0]
            for key in ("pax=", "cargo=", "fuel=", "fl="):
                assert key not in posted[0], key
            page.unroute("**/local/system/open-external")

            # 合并页：抽班 / 自由飞行 / 配载与执行 在同一页的三个页签
            page.goto(f"{base}/ops/fly", wait_until="networkidle")
            page.wait_for_selector("text=飞行执行", timeout=15000)
            for name in ("自由飞行", "配载与执行", "抽班"):
                assert page.get_by_role("tab", name=name).count() > 0, name

            # 顶部状态条：锁定班表 = 地面等待，点击回到对应页面
            page.wait_for_selector(".app-header button:has-text('地面等待')", timeout=15000)
            page.screenshot(path=str(ROOT / "out" / "m2_ops_status.png"), full_page=True)
            page.locator(".app-header button:has-text('地面等待')").first.click()
            page.wait_for_selector("text=抽班条件", timeout=15000)

            page.goto(f"{base}/ops/execute", wait_until="networkidle")
            page.wait_for_selector("text=配载与执行", timeout=15000)
            assert page.get_by_role("tab", name="配载与执行").count() > 0

            page.goto(f"{base}/ops/settlements", wait_until="networkidle")
            page.wait_for_selector("text=结算", timeout=15000)

            page.goto(f"{base}/ops/finance", wait_until="networkidle")
            page.wait_for_selector("text=总计利润", timeout=15000)
            page.wait_for_selector("text=周期统计", timeout=15000)
            page.screenshot(path=str(ROOT / "out" / "m2_ops_finance.png"), full_page=True)

            page.goto(f"{base}/ops/ledger", wait_until="networkidle")
            page.wait_for_selector("text=按类型汇总", timeout=15000)
            assert page.locator("text=账户余额").count() == 0

            page.goto(f"{base}/ops/rules", wait_until="networkidle")
            page.wait_for_selector("text=运营规则", timeout=15000)
            assert page.locator("text=经济参数").count() > 0
            page.screenshot(path=str(ROOT / "out" / "m2_ops_rules.png"), full_page=True)

            page.goto(f"{base}/ops/review", wait_until="networkidle")
            page.wait_for_selector("text=复核队列", timeout=15000)

            page.goto(f"{base}/ops/free", wait_until="networkidle")
            page.wait_for_selector("text=自由飞行", timeout=15000)

            # 已开始的航班可以一键取消：开始本段 → 取消本次航班 → 回到空状态
            page.goto(f"{base}/ops/roster", wait_until="networkidle")
            page.wait_for_selector("text=当前班表", timeout=15000)
            page.locator("button:has-text('开始本段')").first.click()
            page.wait_for_selector("text=当前任务", timeout=20000)
            page.screenshot(path=str(ROOT / "out" / "m2_ops_cancel.png"), full_page=True)
            page.locator("button:has-text('取消本次航班')").first.click()
            page.locator(".ant-popconfirm button:has-text('取消航班')").first.click()
            page.wait_for_selector("text=没有正在执行的任务", timeout=20000)

            browser.close()

        blocked = [e for e in errors if "Failed to load resource" not in e and "net::" not in e]
        print(f"js errors: {len(blocked)}")
        for e in blocked[:20]:
            print(" ", e)
        print(f"home={home}")
        assert not blocked, "存在 JS 异常"
        print("OK: UI smoke passed")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
