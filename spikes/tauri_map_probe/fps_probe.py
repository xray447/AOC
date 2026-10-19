"""V-07 补充探针：无头 Chrome 实测 1 万点 LineString 增量回放的帧率与 setData 开销。

依赖本机已安装的 Chrome（channel="chrome"），不下载额外浏览器；SwiftShader 软渲染，
因此帧率是下限，真实独显/核显环境应更高。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DIST = HERE / "dist"
PORT = 5185
URL = f"http://127.0.0.1:{PORT}/"

MEASURE_JS = """
() => new Promise((resolve) => {
  let frames = 0;
  const t0 = performance.now();
  const tick = () => {
    frames++;
    if (performance.now() - t0 < 5000) requestAnimationFrame(tick);
    else resolve({ frames, ms: performance.now() - t0 });
  };
  requestAnimationFrame(tick);
})
"""

FULL_SETDATA_JS = """
() => new Promise((resolve) => {
  const el = document.querySelector('input[type=range]');
  const t0 = performance.now();
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(el, '9999');
  el.dispatchEvent(new Event('input', { bubbles: true }));
  requestAnimationFrame(() => requestAnimationFrame(() => resolve(performance.now() - t0)));
})
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not (DIST / "index.html").exists():
        print("dist 不存在，请先 npm run build", file=sys.stderr)
        return 2

    server = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "http.server", str(PORT), "--directory", str(DIST)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)
    checks: dict[str, bool] = {}
    facts: dict[str, object] = {}
    errors: list[str] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel="chrome",
                headless=True,
                args=[
                    "--enable-unsafe-swiftshader",
                    "--use-angle=swiftshader",
                    "--disable-dev-shm-usage",
                ],
            )
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(URL, wait_until="domcontentloaded", timeout=30000)

            page.wait_for_selector("canvas.maplibregl-canvas", timeout=30000)
            page.wait_for_timeout(2500)  # 等 map load + 首屏绘制

            counters = page.evaluate("""() => {
              const c = document.querySelector('canvas.maplibregl-canvas');
              return { hasWebgl: !!(c && (c.getContext('webgl2') || c.getContext('webgl'))),
                       text: document.body.innerText.slice(0, 200) };
            }""")
            facts["webgl_ok"] = counters["hasWebgl"]
            facts["initial_text"] = counters.get("text", "").replace("\n", " | ")
            checks["webgl_context_ok"] = bool(counters["hasWebgl"])

            sample = page.evaluate(MEASURE_JS)
            fps = round(sample["frames"] / (sample["ms"] / 1000), 1)
            facts["fps_5s"] = fps
            facts["frames_in_5s"] = sample["frames"]
            facts["badge_text"] = page.locator(".badge").inner_text()
            facts["timeline_text"] = page.locator(".panel .mono").last.inner_text()
            checks["fps_measured"] = fps > 0

            latency = page.evaluate(FULL_SETDATA_JS)
            facts["seek_full_10k_ms"] = round(latency, 1)
            page.wait_for_timeout(600)
            facts["text_after_seek"] = page.locator(".panel .mono").last.inner_text()
            checks["full_10k_setdata_ok"] = "10000" in page.locator(".panel .mono").last.inner_text()
            checks["no_page_error"] = not errors

            facts["page_errors"] = errors[:5]
            browser.close()
    finally:
        server.kill()

    # SwiftShader 软渲染下限；硬件 GPU 环境预期更高
    checks["fps_ge_15_software"] = facts.get("fps_5s", 0) >= 15
    checks["seek_latency_lt_500ms"] = facts.get("seek_full_10k_ms", 9999) < 500

    report = {
        "probe": "V-07 MapLibre 1 万点增量回放（无头 Chrome / SwiftShader）",
        "checks": checks,
        "facts": facts,
        "all_pass": all(checks.values()),
        "notes": [
            "无头 Chrome 使用 SwiftShader 软件光栅化，帧率为保守下限。",
            "OSM 瓦片被拦截以避免外网依赖；线条与图层渲染不受影响。",
            "seek 测试即一次性 setData 10,000 点，测到两帧后的耗时（含 React 状态更新）。",
        ],
    }
    (OUT / "fps_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# V-07 前端回放性能报告（自动生成）", "",
             f"- 5s 平均帧率：{facts.get('fps_5s')} FPS（SwiftShader）",
             f"- 全量 10k 点 setData + 两帧：{facts.get('seek_full_10k_ms')} ms",
             f"- 页面内嵌角标：{facts.get('badge_text')}",
             "", "| 检查项 | 结果 |", "|---|---|"]
    lines += [f"| {k} | {'PASS' if v else 'FAIL'} |" for k, v in checks.items()]
    lines += ["", f"**总结果：{'PASS' if report['all_pass'] else 'FAIL'}**"]
    (OUT / "fps_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
