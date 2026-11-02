"""V-2 探针：生成四个 SimBrief 对照链接，用来确认 `manualzfw` 的单位（docs/TODO §31）。

背景：配载单 ZFW 166714 kg → 代码传 `manualzfw=367.542`（按千磅换算），
但 SimBrief 生成后读到的 ZFW 是 195700 kg（差 17%）。四种口径各生成一条链接，
人工打开比对 SimBrief 的 ZFW 字段即可定位是「单位错」还是「参数被忽略」。

用法：
    python tools/v2_simbrief_zfw_links.py [--zfw 166714] [--dep VHHH] [--arr WMKN]
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
for pkg in (ROOT / "packages").glob("*"):
    if (pkg / pkg.name).is_dir():
        sys.path.insert(0, str(pkg))

from aoc_route.simbrief import build_url  # noqa: E402

KG_TO_LB = 2.2046226


def main(argv: list[str]) -> int:
    zfw, dep, arr, aircraft, callsign, reg = 166714.0, "VHHH", "WMKN", "A359", "AOC101", "B-1090"
    i = 1
    while i < len(argv):
        key = argv[i]
        if key in ("--zfw", "--dep", "--arr", "--type", "--callsign", "--reg") and i + 1 < len(argv):
            value = argv[i + 1]
            if key == "--zfw":
                zfw = float(value)
            elif key == "--dep":
                dep = value.upper()
            elif key == "--arr":
                arr = value.upper()
            elif key == "--type":
                aircraft = value.upper()
            elif key == "--callsign":
                callsign = value.upper()
            elif key == "--reg":
                reg = value.upper()
            i += 2
            continue
        i += 1

    base = build_url(dep, arr, aircraft=aircraft, callsign=callsign, zfw_kg=zfw, registration=reg)
    print(f"基准 ZFW {zfw:.0f} kg；当前代码链接：\n  {base}\n")

    def variant(value: str | None, label: str) -> None:
        parts = urlsplit(base)
        query = [(k, v) for k, v in parse_qsl(parts.query) if k != "manualzfw"]
        if value is not None:
            query.append(("manualzfw", value))
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        print(f"{label}\n  {url}\n")

    variant(None, "① 不传 manualzfw（对照：SimBrief 自算值）")
    variant(f"{zfw * KG_TO_LB / 1000:.3f}", "② manualzfw = 千磅（修复前的错误口径）")
    variant(f"{zfw * KG_TO_LB:.0f}", "③ manualzfw = 磅")
    variant(f"{zfw / 1000:.3f}", "④ manualzfw = 吨（2026-11-02 实测确认的正确口径）")
    variant(f"{zfw:.0f}", "⑤ manualzfw = kg")
    print("结论（2026-11-02）：单位是 ton（t = 1000 kg），即第 ④ 条；"
          "千磅口径会被当成 367.542 t（超 MTOW）而被 SimBrief 丢弃、退回自算值。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
