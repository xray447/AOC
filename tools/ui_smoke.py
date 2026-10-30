"""浏览器冒烟：启动 aoc-core（静态 SPA）+ Playwright 打开各页面，抓 JS 异常并截图。

用 `AOC_NO_NET=1` 关掉日本 AIP 在线同步：否则同步后的 jp-routes 缓存会盖掉
仓库自带的 AIP 样例，ZBAA→ZSSS 变成「无本地航路」，断言随网络时好时坏。
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
    # 运营数据 + 一条完整结算：财务 →「结算」抽屉标题不再出现「— ????→????」
    service.ops.seed_demo()
    draw = service.ops.draw({"max_legs": 1, "max_block_minutes": 480, "window_hours": 168,
                             "min_turnaround_min": 45, "max_turnaround_min": 360})
    settled_roster = service.ops.confirm_roster(draw["candidates"][0]["candidate_token"], 0)
    task = service.ops.start_leg(settled_roster["id"], 1)["task"]
    settled_flight = service.db.insert_flight({
        "id": task["flight_record_id"], "status": "COMPLETED", "callsign": task["callsign"],
        "dep_icao": task["dep_icao"], "arr_icao": task["arr_icao"],
        "distance_nm": 612.4, "block_minutes": 131.2, "fuel_used_kg": 5210,
        "scheduled_dep_utc": task.get("scheduled_dep_utc"),
        "takeoff_utc": task["started_at"], "landing_utc": task["started_at"],
        "block_off_utc": task["started_at"], "block_on_utc": task["started_at"],
    })
    service.ops.on_flight_finalized(settled_flight)
    # 自定义机型模板：机队页「机型模板」抽屉里应能看到「自定义」
    service.ops.create_type({
        "icao": "XWJ", "variant": "WIDE", "name": "Homebuilt Widebody",
        "manufacturer": "Homebuilt", "role": "AIRLINER", "pax_capacity": 300,
        "cabin_config_json": {"first": 8, "business": 42, "premium_economy": 24, "economy": 226},
        "oew_kg": 150000, "mzfw_kg": 200000, "mlw_kg": 210000, "mtow_kg": 280000,
        "fuel_capacity_kg": 110000, "fuel_burn_kg_h": 6000, "cruise_speed_kt": 470,
        "cruise_fl": 370, "min_runway_m": 2400, "range_nm": 6000, "lease_per_hour": 9000,
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
                            env={**os.environ, "AOC_HOME": str(home), "AOC_NO_NET": "1"},
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

        # 自定义机型模板：接口必须标 CUSTOM（界面上按 ICAO 排序，可能被翻页挡住）
        types_req = Request(f"{base}/local/ops/aircraft-types", headers={"X-AOC-Token": token})
        type_items = json.loads(urlopen(types_req, timeout=10).read())["items"]
        assert any(t.get("source") == "CUSTOM" for t in type_items), "自定义机型模板未生效"
        assert all(t.get("source") in ("BUILTIN", "CUSTOM") for t in type_items)

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
            # 落地报告（§29）：报告头 + 卡片 + 三张曲线（含折线与 TD 竖线）
            page.wait_for_selector("text=LANDING REPORT", timeout=10000)
            report = page.locator("[data-testid='landing-report']").first
            report_text = report.inner_text()
            for needle in ("V/S", "G-FORCE", "接地区", "TD DEV",
                           "ALT PROFILE", "VERTICAL SPEED", "G FORCE"):
                assert needle in report_text, f"落地报告缺少「{needle}」"
            assert report.locator("polyline").count() >= 2, "曲线应为折线"
            assert report.locator("svg text:text-is('TD')").count() >= 1, "曲线缺少 TD 竖线"
            page.locator(".track-controls button").first.click(timeout=10000)
            page.wait_for_timeout(800)
            page.locator(".track-controls button").first.click()
            # 跑道接地区俯视图要有跑道标志：编号、每 300 m 刻度、100 m 比例尺
            runway_svg = page.eval_on_selector(
                "svg[aria-label='Runway touchdown view']", "el => el.textContent || ''")
            for needle in ("18", "300 m", "100 m"):
                assert needle in runway_svg, f"跑道图缺少「{needle}」：{runway_svg[:200]}"
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
            # §27/§28/§30：录制策略的说明与选项
            assert page.locator("text=录制按 SimLink 的机型标题自动识别").count() > 0
            assert page.locator("text=连续静止或停机刹车保持").count() > 0
            assert page.locator("text=发动机启动").count() > 0

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
            # 机型模板抽屉：内置只读说明 + 新增按钮（自定义机型靠接口断言，列表可能翻页）
            page.click("button:has-text('机型模板')")
            page.wait_for_selector("text=内置模板只读", timeout=10000)
            assert page.locator("button:has-text('新增机型')").count() > 0
            page.screenshot(path=str(ROOT / "out" / "m2_ops_types.png"), full_page=True)
            page.locator(".ant-drawer-close").first.click()
            page.wait_for_timeout(300)

            page.goto(f"{base}/ops/network", wait_until="networkidle")
            page.wait_for_selector("text=航线与班期", timeout=15000)
            page.get_by_role("tab", name="班期").click()
            assert page.locator("text=AOC101").count() > 0

            page.goto(f"{base}/ops/roster", wait_until="networkidle")
            page.wait_for_selector("text=抽班条件", timeout=15000)
            # §23/§26：默认排除军用机场、按跑道宽度校验翼展
            assert page.locator("text=不含军用机场").count() > 0
            assert page.locator("text=考虑跑道宽度（翼展）").count() > 0
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
            # 配载用 manualzfw（千磅）；呼号拆 airline + fltnum；不预填高度
            assert "manualzfw=" in posted[0]
            assert "airline=" in posted[0] and "fltnum=" in posted[0]
            assert "reg=" in posted[0]
            for key in ("payload=", "callsign=", "pax=", "cargo=", "fuel=", "fl="):
                assert key not in posted[0], key
            page.unroute("**/local/system/open-external")

            # 合并页：抽班 / 自由飞行 / 配载与执行 在同一页的三个页签
            page.goto(f"{base}/ops/fly", wait_until="networkidle")
            page.wait_for_selector("text=飞行执行", timeout=15000)
            for name in ("自由飞行", "配载与执行", "抽班"):
                assert page.get_by_role("tab", name=name).count() > 0, name

            # 顶部状态条：锁定班表 = 地面等待，点击直接进「配载与执行」页签
            page.wait_for_selector(".app-header button:has-text('地面等待')", timeout=15000)
            page.screenshot(path=str(ROOT / "out" / "m2_ops_status.png"), full_page=True)
            page.locator(".app-header button:has-text('地面等待')").first.click()
            page.wait_for_url("**/ops/execute", timeout=15000)
            page.wait_for_selector(".ant-tabs-tab-active:has-text('配载与执行')", timeout=15000)
            # 三个页签手工切换后 URL 与高亮一致
            page.get_by_role("tab", name="抽班").click()
            page.wait_for_url("**/ops/roster", timeout=10000)
            page.wait_for_selector(".ant-tabs-tab-active:has-text('抽班')", timeout=10000)
            page.get_by_role("tab", name="自由飞行").click()
            page.wait_for_url("**/ops/free", timeout=10000)
            page.wait_for_selector(".ant-tabs-tab-active:has-text('自由飞行')", timeout=10000)
            # 深链 ?tab=execute 也能直接落到「配载与执行」
            page.goto(f"{base}/ops/fly?tab=execute", wait_until="networkidle")
            page.wait_for_selector(".ant-tabs-tab-active:has-text('配载与执行')", timeout=15000)

            page.goto(f"{base}/ops/execute", wait_until="networkidle")
            page.wait_for_selector("text=配载与执行", timeout=15000)
            assert page.get_by_role("tab", name="配载与执行").count() > 0

            page.goto(f"{base}/ops/settlements", wait_until="networkidle")
            page.wait_for_selector("text=结算", timeout=15000)
            # 结算详情标题：显示「呼号 DEP→ARR」，不再是「— ????→????」
            # 财务页顶部还有「周期统计」「近 6 个月」两张表，必须点在结算页签的表格上
            settle_pane = page.locator(".ant-tabs-tabpane-active").last
            settle_pane.locator("tbody tr.ant-table-row").first.click()
            page.wait_for_selector(".ant-drawer-title", timeout=15000)
            drawer_title = page.locator(".ant-drawer-title").first.inner_text()
            assert "????" not in drawer_title, drawer_title
            assert "AOC" in drawer_title and "→" in drawer_title, drawer_title
            page.locator(".ant-drawer-close").first.click()
            page.wait_for_timeout(300)

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
