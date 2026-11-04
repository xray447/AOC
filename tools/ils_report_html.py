"""把 `tools/ils_simlink_probe.py` 的输出目录渲染成单文件 HTML 报告（离线可看）。

用法：
  python tools/ils_report_html.py                      # 取 out/ 下最新一次 ils-simlink-*
  python tools/ils_report_html.py out/ils-simlink-KMEM-36R-20261104-214833

输出：<目录>/report.html（内联 CSS/SVG，无外部依赖）
"""
from __future__ import annotations

import csv
import html
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
C_BG, C_CARD, C_LINE, C_TEXT, C_MUTED = "#0b1017", "#121a24", "#1d2836", "#dbe6f3", "#8ea3bb"
C_BLUE, C_RED, C_GREEN, C_AMBER = "#4a9eff", "#ff7043", "#35c46b", "#ffb020"


def _num(value, default=None):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def latest_dir() -> Path:
    candidates = sorted((d for d in (ROOT / "out").glob("ils-simlink-*") if (d / "summary.json").exists()),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise SystemExit("out/ 下没有 ils-simlink-* 结果目录；先跑 tools/ils_simlink_probe.py")
    return candidates[0]


def load(target: Path) -> tuple[dict, list[dict]]:
    summary = json.loads((target / "summary.json").read_text(encoding="utf-8"))
    frames: list[dict] = []
    with (target / "samples.csv").open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            pt = {
                "idx": int(_num(row.get("idx"), 0) or 0),
                "t": _num(row.get("t")),
                "lat": _num(row.get("lat")),
                "lon": _num(row.get("lon")),
                "alt": _num(row.get("alt_ft")),
                "agl": _num(row.get("agl_ft")),
                "gs": _num(row.get("gs_kt")),
                "ias": _num(row.get("ias_kt")),
                "vs": _num(row.get("vs_fpm")),
                "g": _num(row.get("g")),
                "pitch": _num(row.get("pitch")),
                "bank": _num(row.get("bank")),
                "on_ground": str(row.get("on_ground", "")).lower() in ("true", "1"),
                "mode": row.get("mode") or "",
            }
            if pt["lat"] is not None and pt["lon"] is not None:
                frames.append(pt)
    return summary, frames


def project(runway: dict, lat: float, lon: float) -> tuple[float, float]:
    r_lat = float(runway["lat"])
    dx = (lon - float(runway["lon"])) * 111320 * math.cos(math.radians(r_lat))
    dy = (lat - r_lat) * 110540
    th = math.radians(float(runway["heading"]))
    return dy * math.cos(th) + dx * math.sin(th), dx * math.cos(th) - dy * math.sin(th)


def attach_geometry(frames: list[dict], runway: dict | None) -> None:
    for pt in frames:
        if runway:
            along, lateral = project(runway, pt["lat"], pt["lon"])
            pt["along"], pt["lateral"] = along, lateral
        else:
            pt["along"], pt["lateral"] = None, None


def esc(text) -> str:
    return html.escape(str(text))


def card(label: str, value: str, unit: str = "", sub: str = "", color: str = C_TEXT) -> str:
    return (f'<div class="card"><div class="card-label">{esc(label)}</div>'
            f'<div class="card-value" style="color:{color}">{esc(value)}'
            f'<span class="card-unit">{esc(unit)}</span></div>'
            f'<div class="card-sub">{esc(sub)}</div></div>')


def svg_runway(frames: list[dict], summary: dict, runway: dict) -> str:
    length = float(runway["length_m"])
    width = float(runway["width_m"])
    pre = 420.0  # 跑道头前的显示余量（50 ft 点常落在这一侧）
    W, H = 1020, 300
    pad_l, pad_r, pad_t, pad_b = 48, 48, 40, 54
    x0 = -pre
    xscale = (W - pad_l - pad_r) / (length - x0)
    center_y = pad_t + (H - pad_t - pad_b) / 2

    track = [p for p in frames if p.get("along") is not None]
    max_lat = max([width / 2] + [abs(p["lateral"]) for p in track], default=width / 2)
    latscale = min(3.2, max(1.0, (H - pad_t - pad_b) / 2 - 46) / max(max_lat, 1))

    def X(along: float) -> float:
        return pad_l + (along - x0) * xscale

    def Y(lateral: float) -> float:
        return center_y + lateral * latscale

    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="runway touchdown">']
    # 跑道轮廓
    parts.append(f'<rect x="{X(0):.1f}" y="{Y(-width / 2):.1f}" width="{X(length) - X(0):.1f}" '
                 f'height="{Y(width / 2) - Y(-width / 2):.1f}" fill="rgba(255,255,255,0.05)" '
                 f'stroke="rgba(180,205,235,0.45)" stroke-width="1.5"/>')
    parts.append(f'<line x1="{X(0):.1f}" y1="{center_y:.1f}" x2="{X(length):.1f}" y2="{center_y:.1f}" '
                 f'stroke="rgba(180,205,235,0.35)" stroke-dasharray="10 8"/>')
    # 每 300 m 刻度
    tick = 0.0
    while tick <= length + 0.1:
        parts.append(f'<line x1="{X(tick):.1f}" y1="{Y(width / 2):.1f}" x2="{X(tick):.1f}" '
                     f'y2="{Y(width / 2) + 5:.1f}" stroke="rgba(180,205,235,0.5)"/>')
        parts.append(f'<text x="{X(tick):.1f}" y="{Y(width / 2) + 19:.1f}" font-size="10" '
                     f'fill="{C_MUTED}" text-anchor="middle">{int(tick)} m</text>')
        tick += 300
    # 接地后轨迹
    td = summary.get("touchdown_t")
    if td is not None:
        post = [p for p in frames if p["t"] is not None and p["t"] >= td - 0.01]
        if len(post) >= 2:
            d = " ".join(f'{"M" if i == 0 else "L"}{X(p["along"]):.1f},{Y(p["lateral"]):.1f}'
                         for i, p in enumerate(post))
            parts.append(f'<path d="{d}" fill="none" stroke="{C_BLUE}" stroke-width="2.2" stroke-opacity="0.9"/>')
    # 50 ft 点：接地前最后一段「从 >50 ft 降到 ≤50 ft」的那一帧（不是接地帧本身）
    idx_td = next((i for i, p in enumerate(frames) if td is not None and p["t"] is not None and p["t"] >= td), None)
    fifty = None
    if idx_td is not None:
        for i in range(idx_td, -1, -1):
            if frames[i]["agl"] is not None and frames[i]["agl"] > 50:
                fifty = frames[min(i + 1, len(frames) - 1)]
                break
    if fifty and fifty.get("along") is not None:
        fx, fy = X(fifty["along"]), center_y
        parts.append(f'<circle cx="{fx:.1f}" cy="{fy:.1f}" r="4" fill="{C_GREEN}"/>')
        parts.append(f'<text x="{fx:.1f}" y="{fy - 14:.1f}" font-size="11" fill="{C_GREEN}" '
                     f'text-anchor="middle">50 ft · 跑道头前 {abs(fifty["along"]):.0f} m</text>')
    # 接地点
    along, lateral = summary.get("along_m"), summary.get("lateral_m")
    if along is not None and lateral is not None:
        tx, ty = X(along), Y(lateral)
        parts.append(f'<line x1="{tx:.1f}" y1="{center_y:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" '
                     f'stroke="{C_RED}" stroke-width="1.4" stroke-dasharray="4 3"/>')
        parts.append(f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="6" fill="{C_RED}"/>')
        parts.append(f'<text x="{tx + 10:.1f}" y="{ty + 4:.1f}" font-size="12" fill="{C_RED}">'
                     f'接地点 {along:.0f} m / 偏移 {lateral:+.1f} m</text>')
    parts.append(f'<text x="{X(0):.1f}" y="{H - 10}" font-size="11" fill="{C_MUTED}">'
                 f'{esc(runway["ident"])} 入口 · 全长 {length:.0f} m · 宽 {width:.1f} m · '
                 f'横向放大 {latscale / xscale:.1f}×</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_profile(frames: list[dict], summary: dict, runway: dict) -> str:
    pts = [p for p in frames if p.get("along") is not None and p.get("agl") is not None
           and p["agl"] >= 0 and p.get("t") is not None]
    td = summary.get("touchdown_t")
    if td is not None:
        pts = [p for p in pts if p["t"] <= td + 5]
    if len(pts) < 2:
        return '<p class="muted">剖面数据不足</p>'
    W, H = 1020, 320
    pad_l, pad_r, pad_t, pad_b = 58, 26, 26, 44
    xs = [p["along"] for p in pts]
    x_min = min(min(xs) - 200, -300)
    x_max = max(max(xs) + 200, 300)
    y_max = max(200.0, max(p["agl"] for p in pts) * 1.1)

    def X(v: float) -> float:
        return pad_l + (v - x_min) / (x_max - x_min) * (W - pad_l - pad_r)

    def Y(v: float) -> float:
        return H - pad_b - v / y_max * (H - pad_t - pad_b)

    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="approach profile">']
    # 网格
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        value = y_max * frac
        parts.append(f'<line x1="{pad_l}" y1="{Y(value):.1f}" x2="{W - pad_r}" y2="{Y(value):.1f}" '
                     f'stroke="{C_LINE}" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{Y(value) + 4:.1f}" font-size="10" fill="{C_MUTED}" '
                     f'text-anchor="end">{value:.0f} ft</text>')
    # 3° 参考线（跑道头前 300 m 处 50 ft；从 AGL=0 的截点画到跑道头）
    tan3 = math.tan(math.radians(3))
    ref_x0 = max(x_min, -300 - 50 / tan3)
    parts.append(f'<line x1="{X(ref_x0):.1f}" y1="{Y(50 + (ref_x0 + 300) * tan3):.1f}" '
                 f'x2="{X(0):.1f}" y2="{Y(50 + 300 * tan3):.1f}" stroke="{C_AMBER}" '
                 f'stroke-width="1.4" stroke-dasharray="7 6" stroke-opacity="0.85"/>')
    parts.append(f'<text x="{X(-260):.1f}" y="{Y(90):.1f}" font-size="11" fill="{C_AMBER}">3° 下滑道</text>')
    # 跑道头竖线
    parts.append(f'<line x1="{X(0):.1f}" y1="{pad_t}" x2="{X(0):.1f}" y2="{H - pad_b}" '
                 f'stroke="rgba(180,205,235,0.5)" stroke-dasharray="5 5"/>')
    parts.append(f'<text x="{X(0) + 6:.1f}" y="{pad_t + 12}" font-size="10" fill="{C_MUTED}">跑道头</text>')
    # 轨迹
    d = " ".join(f'{"M" if i == 0 else "L"}{X(p["along"]):.1f},{Y(p["agl"]):.1f}'
                 for i, p in enumerate(pts))
    parts.append(f'<path d="{d}" fill="none" stroke="{C_BLUE}" stroke-width="2.4"/>')
    # x 轴刻度
    step = 500
    start = math.ceil(x_min / step) * step
    for tick in range(int(start), int(x_max) + 1, step):
        parts.append(f'<line x1="{X(tick):.1f}" y1="{H - pad_b}" x2="{X(tick):.1f}" y2="{H - pad_b + 5}" '
                     f'stroke="{C_MUTED}"/>')
        parts.append(f'<text x="{X(tick):.1f}" y="{H - pad_b + 18}" font-size="10" fill="{C_MUTED}" '
                     f'text-anchor="middle">{tick} m</text>')
    parts.append(f'<text x="{W / 2:.1f}" y="{H - 6}" font-size="11" fill="{C_MUTED}" '
                 f'text-anchor="middle">距跑道头（负值 = 跑道头之前）</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_vs(frames: list[dict], summary: dict) -> str:
    pts = [p for p in frames if p.get("vs") is not None and p.get("t") is not None]
    if len(pts) < 2:
        return '<p class="muted">V/S 数据不足</p>'
    W, H = 1020, 240
    pad_l, pad_r, pad_t, pad_b = 58, 26, 22, 40
    t_min, t_max = pts[0]["t"], pts[-1]["t"]
    vs_min = min(-200.0, min(p["vs"] for p in pts) * 1.1)
    vs_max = max(200.0, max(p["vs"] for p in pts) * 1.1)

    def X(v: float) -> float:
        return pad_l + (v - t_min) / max(t_max - t_min, 1) * (W - pad_l - pad_r)

    def Y(v: float) -> float:
        return pad_t + (vs_max - v) / (vs_max - vs_min) * (H - pad_t - pad_b)

    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="vertical speed">']
    parts.append(f'<line x1="{pad_l}" y1="{Y(0):.1f}" x2="{W - pad_r}" y2="{Y(0):.1f}" stroke="{C_LINE}"/>')
    for value in (vs_max, vs_max / 2, 0, vs_min / 2, vs_min):
        parts.append(f'<text x="{pad_l - 8}" y="{Y(value) + 4:.1f}" font-size="10" fill="{C_MUTED}" '
                     f'text-anchor="end">{value:.0f}</text>')
    td = summary.get("touchdown_t")
    if td is not None and t_min <= td <= t_max:
        parts.append(f'<line x1="{X(td):.1f}" y1="{pad_t}" x2="{X(td):.1f}" y2="{H - pad_b}" '
                     f'stroke="{C_RED}" stroke-dasharray="5 4" stroke-opacity="0.8"/>')
        parts.append(f'<text x="{X(td) + 6:.1f}" y="{pad_t + 12}" font-size="10" fill="{C_RED}">接地</text>')
    d = " ".join(f'{"M" if i == 0 else "L"}{X(p["t"]):.1f},{Y(p["vs"]):.1f}' for i, p in enumerate(pts))
    parts.append(f'<path d="{d}" fill="none" stroke="{C_GREEN}" stroke-width="2"/>')
    for tick in range(int(t_min) // 10 * 10, int(t_max) + 1, 10):
        parts.append(f'<text x="{X(tick):.1f}" y="{H - pad_b + 16}" font-size="10" fill="{C_MUTED}" '
                     f'text-anchor="middle">{tick}s</text>')
    parts.append("</svg>")
    return "".join(parts)


def build(target: Path) -> Path:
    summary, frames = load(target)
    runway = summary.get("runway_geometry")
    attach_geometry(frames, runway)

    name = f'{summary.get("airport") or "—"} {summary.get("runway") or "—"}'
    along, lateral = summary.get("along_m"), summary.get("lateral_m")
    vs = summary.get("touchdown_vs_fpm")
    vs_med = summary.get("touchdown_vs_median")
    glide = summary.get("glide_mean_deg")
    d50 = summary.get("distance_at_50ft_m")
    fifty_txt = "—" if d50 is None else (f"前 {abs(d50):.0f}" if d50 < 0 else f"后 {d50:.0f}")
    stop = summary.get("stop_reason") or "—"
    stop_note = {"interrupted": "采样被 Ctrl+C 中断，滑跑数据不完整",
                 "touchdown+after": "接地后采满 --after 秒自动收尾",
                 "timeout": "等满 --timeout 后收尾"}.get(stop, stop)

    cards = [
        card("接地点 · 距跑道头", f"{along:.1f}" if along is not None else "—", " m",
             f"跑道内 {summary.get('along_pct', 0):.1f}%" if along is not None else "", C_RED),
        card("中线偏移", f"{lateral:+.1f}" if lateral is not None else "—", " m",
             "正 = 右偏，负 = 左偏", C_BLUE),
        card("接地 V/S", f"{vs:.0f}" if vs is not None else "—", " fpm",
             f"5 帧中位数 {vs_med:.0f} fpm" if vs_med is not None else "", C_TEXT),
        card("接地 G", f'{summary.get("touchdown_g", 0):.2f}', " g",
             f'GS {summary.get("touchdown_gs_kt", 0):.1f} kt', C_TEXT),
        card("末段下滑角", f"{glide:.2f}" if glide is not None else "—", " °",
             "参考 3.00°", C_AMBER),
        card("50 ft 点", fifty_txt, " m", "距跑道头（理想 ≈ 前 300 m）",
             C_GREEN if d50 is not None and abs(abs(d50) - 300) <= 120 else C_TEXT),
        card("接地后滑跑", f'{summary.get("rollout_m", 0):.0f}' if summary.get("rollout_m") else "—", " m",
             f'最大 G {summary.get("rollout_g_max", 0):.2f}' if summary.get("rollout_g_max") else "", C_TEXT),
        card("采样", f'{summary.get("frames", 0)}', " 帧", stop_note, C_MUTED),
    ]

    # 关键帧表（接地前 30 s + 接地后，每 5 s 抽一行）
    td = summary.get("touchdown_t")
    rows = []
    if td is not None:
        picked = [p for p in frames if p.get("t") is not None and p["t"] >= td - 30]
        last_t = None
        for pt in picked:
            if last_t is None or pt["t"] - last_t >= 5:
                last_t = pt["t"]
                rows.append(
                    f'<tr><td>{pt["t"]:.1f}</td>'
                    f'<td>{pt["along"]:.0f}</td>'
                    f'<td>{pt["lateral"]:+.1f}</td>'
                    f'<td>{pt["agl"]:.0f}</td>'
                    f'<td>{pt["gs"]:.1f}</td>'
                    f'<td>{pt["vs"]:.0f}</td>'
                    f'<td>{pt["g"]:.2f}</td>'
                    f'<td>{"地面" if pt["on_ground"] else "空中"}</td></tr>')

    style = f"""
    :root {{ color-scheme: dark; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; padding:32px 20px 64px; background:{C_BG}; color:{C_TEXT};
            font-family: system-ui, "Segoe UI", "Microsoft YaHei", sans-serif; }}
    .wrap {{ max-width:1080px; margin:0 auto; }}
    h1 {{ font-size:22px; margin:0 0 4px; letter-spacing:0.5px; }}
    .sub {{ color:{C_MUTED}; font-size:13px; margin-bottom:22px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin-bottom:22px; }}
    .card {{ background:{C_CARD}; border:1px solid {C_LINE}; border-radius:10px; padding:12px 14px; }}
    .card-label {{ font-size:11px; letter-spacing:1.2px; color:{C_MUTED}; text-transform:uppercase; }}
    .card-value {{ font-size:24px; font-weight:700; margin-top:6px; }}
    .card-unit {{ font-size:13px; font-weight:500; color:{C_MUTED}; }}
    .card-sub {{ font-size:11px; color:{C_MUTED}; margin-top:5px; }}
    section {{ background:{C_CARD}; border:1px solid {C_LINE}; border-radius:12px; padding:14px 16px 8px; margin-bottom:16px; }}
    section h2 {{ font-size:12px; letter-spacing:1.4px; color:{C_MUTED}; font-weight:600; margin:0 0 10px; text-transform:uppercase; }}
    table {{ width:100%; border-collapse:collapse; font-size:12px; }}
    th {{ text-align:right; color:{C_MUTED}; font-weight:500; padding:6px 8px; border-bottom:1px solid {C_LINE}; }}
    td {{ text-align:right; padding:5px 8px; border-bottom:1px solid rgba(29,40,54,0.6); }}
    th:first-child, td:first-child {{ text-align:left; }}
    .muted {{ color:{C_MUTED}; font-size:12px; }}
    .files {{ font-size:12px; color:{C_MUTED}; line-height:1.7; }}
    code {{ background:#0d141d; padding:1px 5px; border-radius:4px; }}
    """

    body = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(name)} ILS 落地报告</title><style>{style}</style></head>
<body><div class="wrap">
<h1>{esc(name)} · ILS 落地报告</h1>
<div class="sub">SimLink 直采（不依赖 AOC 记录）· 数据目录 <code>{esc(target.name)}</code> · {esc(stop_note)}</div>
<div class="cards">{''.join(cards)}</div>
<section><h2>接地区俯视图</h2>
{svg_runway(frames, summary, runway) if runway else '<p class="muted">缺少跑道几何</p>'}
</section>
<section><h2>进近剖面（AGL vs 距跑道头）</h2>
{svg_profile(frames, summary, runway) if runway else '<p class="muted">缺少跑道几何</p>'}
</section>
<section><h2>垂直速度</h2>
{svg_vs(frames, summary)}
</section>
<section><h2>关键帧（接地前 30 s 起，每 5 s）</h2>
<table><thead><tr><th>t (s)</th><th>距跑道头 (m)</th><th>横偏 (m)</th><th>AGL (ft)</th>
<th>GS (kt)</th><th>V/S (fpm)</th><th>G</th><th>状态</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="8" class="muted">无数据</td></tr>'}</tbody></table>
<div class="files" style="padding:10px 0">同目录文件：<code>samples.csv</code>（逐帧原始数据）·
<code>summary.txt</code> / <code>summary.json</code>（结论）</div>
</section>
</div></body></html>
"""
    out = target / "report.html"
    out.write_text(body, encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else latest_dir()
    if not target.is_dir():
        raise SystemExit(f"目录不存在：{target}")
    out = build(target)
    print(f"已生成 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
