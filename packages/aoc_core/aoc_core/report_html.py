"""单文件 HTML 落地报告（版式对齐 `spikes/simconnect_probe/out2_report/report.html`）。

内联 CSS + SVG、零外部依赖、不含脚本：可以直接发给别人或存档离线查看。
前端 `components/LandingReport.tsx` 是同一个版式的 React 版，导出与界面观感一致。
"""
from __future__ import annotations

import html
from datetime import datetime
from typing import Any

C_ALT = "#3ddc97"
C_VS = "#5b9dff"
C_G = "#ffb547"

CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#080b10;color:#e6edf6;
     font:13px/1.45 "Segoe UI",system-ui,-apple-system,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:20px 18px 40px}
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;
      border-bottom:1px solid #1c2532;padding-bottom:14px;margin-bottom:18px}
.kicker{font-size:10px;letter-spacing:2px;color:#5f7387}
.title{font-size:22px;font-weight:600;letter-spacing:.5px}
.meta{text-align:right;color:#7d8ea6;font-size:11px;line-height:1.6}
.tdhead{display:flex;align-items:center;gap:8px;font-size:12px;color:#9fb0c6;margin:6px 0 10px}
.dot{width:7px;height:7px;border-radius:50%;background:#3ddc97;box-shadow:0 0 8px #3ddc97}
.muted{color:#6b7c93}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:18px}
.card{background:#0e131a;border:1px solid #1b2431;border-radius:8px;padding:9px 11px}
.label{font-size:10px;letter-spacing:1px;color:#6b7c93;text-transform:uppercase}
.value{font:600 20px/1.2 Consolas,"SF Mono",monospace;color:#e6edf6;margin-top:2px}
.unit{font-size:10px;color:#7d8ea6;margin-left:4px;font-weight:400}
.sub{font-size:10px;color:#6b7c93;margin-top:2px}
.chart{background:#0e131a;border:1px solid #1b2431;border-radius:8px;padding:10px 12px;margin-bottom:12px}
.chart-title{font-size:10px;letter-spacing:1.4px;color:#8fa3ba;margin-bottom:4px}
.chart svg{display:block;width:100%;height:200px}
.empty{color:#6b7c93;padding:18px 4px}
.foot{color:#6b7c93;font-size:11px;margin-top:14px}
"""


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _num(value: Any, digits: int = 0) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if digits <= 0:
        return f"{number:.0f}"
    return f"{number:.{digits}f}"


def _seconds_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (b - a).total_seconds()


def _card(label: str, value: Any, unit: str = "", sub: str | None = None) -> str:
    unit_html = f'<span class="unit">{_esc(unit)}</span>' if unit else ""
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return (f'<div class="card"><div class="label">{_esc(label)}</div>'
            f'<div class="value">{value}{unit_html}</div>{sub_html}</div>')


def _percentile(values: list[float], ratio: float) -> float:
    index = max(0, min(len(values) - 1, int(len(values) * ratio)))
    return values[index]


def _chart(title: str, unit: str, points: list[dict[str, Any]],
           selector, marker_t: float | None, color: str) -> str:
    width, height, pad_l, pad_r, pad_t, pad_b = 1040, 200, 52, 14, 14, 22
    head = (f'<div class="chart"><div class="chart-title">{_esc(title)}'
            f'<span class="muted"> · {_esc(unit)}</span></div>')
    series = [(float(p.get("t") or 0), selector(p)) for p in points]
    series = [(t, v) for t, v in series if v is not None]
    if len(series) < 2:
        return head + '<div class="empty">样本不足，无法绘图</div></div>'

    t0, t1 = series[0][0], series[-1][0]
    values = sorted(v for _, v in series)
    y_min = _percentile(values, 0.02)
    y_max = _percentile(values, 0.98)
    if y_max - y_min < 1e-6:
        y_min -= 1.0
        y_max += 1.0
    pad = (y_max - y_min) * 0.08
    y_min -= pad
    y_max += pad
    span = y_max - y_min
    digits = 0 if span >= 20 else 1 if span >= 2 else 2

    def sx(t: float) -> float:
        return pad_l + (t - t0) / max(1e-6, t1 - t0) * (width - pad_l - pad_r)

    def sy(v: float) -> float:
        y = height - pad_b - (v - y_min) / (y_max - y_min) * (height - pad_t - pad_b)
        return min(height - pad_b, max(pad_t, y))

    out = [head, f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">']
    for i in range(5):
        value = y_min + (y_max - y_min) * i / 4
        y = sy(value)
        out.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
                   'stroke="#1d2634" stroke-width="1"/>')
        out.append(f'<text x="{pad_l - 6}" y="{y + 3.5:.1f}" fill="#6b7c93" font-size="10" '
                   f'text-anchor="end">{_num(value, digits)}</text>')
    for i in range(5):
        t = t0 + (t1 - t0) * i / 4
        out.append(f'<text x="{sx(t):.1f}" y="{height - 6}" fill="#6b7c93" font-size="10" '
                   f'text-anchor="middle">{_num(t)}s</text>')
    polyline = " ".join(f"{sx(t):.1f},{sy(v):.1f}" for t, v in series)
    out.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.6" '
               f'stroke-linejoin="round" stroke-linecap="round" points="{polyline}"/>')
    if marker_t is not None and t0 <= marker_t <= t1:
        x = sx(marker_t)
        out.append(f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{height - pad_b}" '
                   'stroke="#ffb547" stroke-width="1" stroke-dasharray="3 3"/>')
        out.append(f'<text x="{x + 4:.1f}" y="{pad_t + 10}" fill="#ffb547" font-size="10">TD</text>')
    out.append("</svg>")
    out.append(f'<div class="sub">{len(series)} 点 · {_num(t1 - t0)}s</div></div>')
    return "".join(out)


def _runway_panel(flight: dict[str, Any], runway: dict[str, Any] | None,
                  marker_t: float | None) -> str:
    length = float((runway or {}).get("length_m") or 0)
    along = flight.get("threshold_distance_m")
    if length <= 0 or along is None:
        return ""
    width, height, pad_l, pad_r = 1040, 150, 26, 26
    strip_y, strip_h = 34, 40
    x0, x1 = pad_l, width - pad_r
    center = strip_y + strip_h / 2

    def px(meters: float) -> float:
        return x0 + min(max(meters, 0.0), length) / length * (x1 - x0)

    out = [f'<div class="chart"><div class="chart-title">RUNWAY TOUCHDOWN ZONE'
           f'<span class="muted"> · {_esc(flight.get("arr_icao") or "-")}/'
           f'{_esc(flight.get("runway_ident") or "-")} · 全长 {_num(length)} m</span></div>',
           f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">',
           f'<rect x="{x0}" y="{strip_y}" width="{x1 - x0}" height="{strip_h}" fill="#111923" '
           'stroke="#243141" stroke-width="1"/>',
           f'<line x1="{x0 + 10}" y1="{center}" x2="{x1 - 10}" y2="{center}" '
           'stroke="#3b4b5e" stroke-width="1.5" stroke-dasharray="12 10"/>']
    for i in range(4):
        out.append(f'<rect x="{x0 + 4}" y="{strip_y + 5 + i * 9}" width="12" height="5" fill="#8fa3ba"/>')
    for mark in (300, 600, 900):
        if mark > length:
            continue
        x = px(mark)
        for b in range(3 if mark == 300 else 2 if mark == 600 else 1):
            out.append(f'<rect x="{x + b * 9:.1f}" y="{center - 13}" width="5" height="26" fill="#54657a"/>')
        out.append(f'<text x="{x:.1f}" y="{strip_y - 6}" fill="#5f7387" font-size="9">{mark}m</text>')
    td_x = px(float(along))
    out.append(f'<line x1="{td_x:.1f}" y1="{strip_y - 8}" x2="{td_x:.1f}" y2="{strip_y + strip_h + 8}" '
               'stroke="#ffb547" stroke-width="2"/>')
    out.append(f'<circle cx="{td_x:.1f}" cy="{strip_y + strip_h + 14}" r="3.5" fill="#fa541c"/>')
    out.append(f'<text x="{td_x:.1f}" y="{strip_y + strip_h + 30}" fill="#ffb547" font-size="10" '
               f'text-anchor="middle">TD {_num(along)}m</text>')
    out.append(f'<text x="{x0}" y="{strip_y + strip_h + 22}" fill="#6b7c93" font-size="10">入口 0</text>')
    out.append(f'<text x="{x1}" y="{strip_y + strip_h + 22}" fill="#6b7c93" font-size="10" '
               f'text-anchor="end">{_num(length)}m</text>')
    if marker_t is not None:
        out.append(f'<text x="{x0}" y="{strip_y - 6}" fill="#6b7c93" font-size="9">'
                   f'touchdown t={_num(marker_t)}s</text>')
    out.append("</svg></div>")
    return "".join(out)


def build_report_html(*, flight: dict[str, Any], points: list[dict[str, Any]],
                      events: list[dict[str, Any]] | None = None,
                      runway: dict[str, Any] | None = None,
                      arr_elev_ft: float | None = None,
                      source: str | None = None) -> str:
    """渲染单文件落地报告（内联 CSS/SVG，无脚本、无外链）。"""
    events = events or []
    landing_t = _seconds_between(flight.get("block_off_utc"), flight.get("landing_utc"))
    marker_t = landing_t
    duration = landing_t if landing_t is not None else (
        float(points[-1].get("t") or 0) if points else None)
    title = (flight.get("aircraft_title") or flight.get("aircraft_type") or "机型未记录")
    elev = float(arr_elev_ft or 0)

    parts = [
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>AOC 落地报告</title><style>", CSS, "</style></head><body><div class=\"wrap\">",
        '<div class="head"><div><div class="kicker">LANDING REPORT</div>',
        f'<div class="title">{_esc(title)}</div></div><div class="meta">',
        f'时长 {_num(duration)}s · 样本 {len(points)}<br>',
        f'{_esc(source or flight.get("mode") or "AOC")} · '
        f'{_esc(flight.get("dep_icao") or "????")} → {_esc(flight.get("arr_icao") or "????")}'
        "</div></div>",
    ]

    has_landing = landing_t is not None and flight.get("touchdown_lat") is not None
    if not has_landing:
        parts.append('<div class="empty">未检测到落地（轨迹里没有空中→地面的跳变）</div>')
    else:
        dev = flight.get("centerline_offset_m")
        dev_text = ""
        if dev is not None:
            dev_text = f' · 中心线 {abs(float(dev)):.0f} m {"右" if float(dev) >= 0 else "左"}'
        thr = flight.get("threshold_distance_m")
        parts.append(
            '<div class="tdhead"><span class="dot"></span>落地 '
            f'{_esc(flight.get("arr_icao") or "????")}/{_esc(flight.get("runway_ident") or "—")}'
            f' @ t={_num(landing_t)}s<span class="muted">'
            + (f" · 距着陆入口 {_num(thr)} m" if thr is not None else "")
            + dev_text + "</span></div>"
        )

        length = float((runway or {}).get("length_m") or 0)
        remaining = None
        if length > 0 and thr is not None:
            remaining = max(0.0, length - float(thr))
        max_g_landing = flight.get("max_g_landing")
        touchdown_g = flight.get("touchdown_g")
        g_sub = "触地帧"
        if max_g_landing is not None and touchdown_g is not None:
            g_sub = f"峰值 {_num(max_g_landing, 2)} / 触地帧 {_num(touchdown_g, 2)}"
        parts.append('<div class="grid">')
        parts.append(_card("V/S", _num(flight.get("touchdown_vs_fpm")), "fpm"))
        parts.append(_card("G-FORCE", _num(max_g_landing if max_g_landing is not None else touchdown_g, 2),
                           "g", g_sub))
        parts.append(_card("RUNWAY", _esc(flight.get("runway_ident") or "—"), "",
                           _esc(flight.get("arr_icao") or "—")))
        parts.append(_card("接地区", _num(thr), "m",
                           f"剩余 {_num(remaining)} m" if remaining is not None else "距入口"))
        parts.append(_card("TD DEV", f"{abs(float(dev)):.1f}" if dev is not None else "—",
                           "m 右" if dev is not None and float(dev) >= 0 else "m 左",
                           "中心线横向偏差"))
        parts.append(_card("弹跳", _num(flight.get("bounce_count")), ""))
        parts.append(_card("滑跑距离", _num(flight.get("landing_distance_m")), "m"))
        parts.append(_card("全程最大 G", _num(flight.get("max_g_flight"), 2), "g"))
        parts.append("</div>")

    def alt(point: dict[str, Any]) -> float | None:
        value = point.get("alt_ft")
        return None if value is None else float(value) - elev

    def vs(point: dict[str, Any]) -> float | None:
        value = point.get("vs_fpm")
        return None if value is None else float(value)

    def gforce(point: dict[str, Any]) -> float | None:
        value = point.get("g")
        return None if value is None else float(value)

    parts.append(_chart("ALT PROFILE", "ft", points, alt, marker_t, C_ALT))
    parts.append(_chart("VERTICAL SPEED", "fpm", points, vs, marker_t, C_VS))
    g_values = [abs(float(p.get("g") or 0)) for p in points]
    if any(v > 0.01 for v in g_values):
        parts.append(_chart("G FORCE", "g", points, gforce, marker_t, C_G))
    else:
        parts.append('<div class="chart"><div class="chart-title">G FORCE'
                     '<span class="muted"> · g</span></div>'
                     '<div class="empty">样本不足（旧 BIN_V1 或 demo 源没有 G）</div></div>')

    parts.append(_runway_panel(flight, runway, marker_t))
    parts.append(
        f'<div class="foot">{len(points)} 个轨迹点 · {len(events)} 个事件；'
        "曲线为逐样本折线（未做等距重采样），落地竖线为 touchdown 时刻。</div>"
    )
    parts.append("</div></body></html>")
    return "".join(parts)
