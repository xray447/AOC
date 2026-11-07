"""V-7 探针（docs/12 §12）：核对两个 navdata 里的 `parking` 表能不能用来选机位。

回答四个问题（对应 §4.1 的硬约束假设）：
1. `pragma table_info(parking)`：列名是否随 AIRAC / 场景版本变化（缺列要能降级）；
2. 各类型（GS/GM/GH/GE …）的 `radius` 分位是否与「radius ≥ 翼展」一致；
3. 抽 3 个机位的经纬度/朝向是否落在停机坪（人工对着卫星图核）；
4. `airline_codes` 的实际填充率（若全空，§4.2 的航司软加分就该删 —— 已删，改用 §4.5 规则）。

用法：
    python tools/v7_stand_probe.py                 # 默认 EGLL / ZBAA / KJFK / RJTT
    python tools/v7_stand_probe.py ZSSS RJTT --db D:\\lnm\\little_navmap_msfs24.sqlite
    python tools/v7_stand_probe.py ZSSS --pick A320 B77W A388   # 顺带跑一遍选位
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = Path.home() / "AppData" / "Roaming" / "ABarthel" / "little_navmap_db"
DEFAULT_DBS = [
    BASE / "little_navmap_msfs24.sqlite",
    BASE / "little_navmap_navigraph.sqlite",
]
DEFAULT_AIRPORTS = ("EGLL", "ZBAA", "KJFK", "RJTT")
STAND_TYPES = ("GS", "GM", "GH", "GE", "RC", "RMC", "RMCB", "RGAS", "RGAM", "RGAL", "DGA")
# 翼展（米）：B738 / B77W / A388，用于核对「选出来的位能不能停下」
WINGSPANS = {"A20N": 35.8, "A320": 35.8, "A321": 35.8, "B738": 35.8,
             "B77W": 64.8, "A388": 79.8}


def percentiles(values: list[float]) -> str:
    if not values:
        return "—"
    values = sorted(values)
    picks = [0, 10, 50, 90, 100]
    parts = []
    for p in picks:
        index = min(len(values) - 1, max(0, round((p / 100) * (len(values) - 1))))
        parts.append(f"p{p}={values[index]:.0f}")
    return " ".join(parts)


def describe(path: Path, airports: list[str]) -> None:
    if not path.exists():
        print(f"\n== {path.name}：不存在")
        return
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    print(f"\n== {path.name}")
    cols = [r[1] for r in con.execute("pragma table_info(parking)")]
    if not cols:
        print("  没有 parking 表（该库不能提供机位）")
        con.close()
        return
    print(f"  parking 列：{', '.join(cols)}")
    missing = [c for c in ("type", "radius", "has_jetway", "suffix", "number", "airline_codes")
               if c not in cols]
    print(f"  缺列（实现里按 None 降级）：{', '.join(missing) or '无'}")
    total = con.execute("select count(*) from parking").fetchone()[0]
    covered = con.execute(
        "select count(distinct airport_id) from parking").fetchone()[0]
    airports_total = con.execute("select count(*) from airport").fetchone()[0]
    print(f"  机位数 {total:,} · 含机位机场 {covered:,} / {airports_total:,}")
    if "airline_codes" in cols:
        filled = con.execute(
            "select count(*) from parking where airline_codes is not null and airline_codes<>''"
        ).fetchone()[0]
        print(f"  airline_codes 非空 {filled:,}（{100.0 * filled / max(1, total):.2f}%）")

    for icao in airports:
        row = con.execute("select airport_id, name from airport where ident=?", (icao,)).fetchone()
        if row is None:
            print(f"  {icao}: 不在 navdata")
            continue
        rows = con.execute(
            "select type, radius, has_jetway, name, number, suffix, laty, lonx, heading "
            "from parking where airport_id=?", (row["airport_id"],)).fetchall()
        print(f"\n  -- {icao} {row['name'] or ''}：{len(rows)} 个机位")
        if not rows:
            continue
        by_type: dict[str, list[float]] = {}
        jetways = 0
        areas: dict[str, int] = {}
        for item in rows:
            kind = (item["type"] or "?").upper()
            by_type.setdefault(kind, [])
            radius = item["radius"]
            if isinstance(radius, (int, float)):
                by_type[kind].append(float(radius))
            if item["has_jetway"]:
                jetways += 1
            areas[(item["name"] or "?")] = areas.get((item["name"] or "?"), 0) + 1
        for kind in STAND_TYPES:
            if kind in by_type:
                print(f"     {kind:5} {len(by_type[kind]):4} 个  radius {percentiles(by_type[kind])}")
        others = sorted(set(by_type) - set(STAND_TYPES))
        if others:
            print(f"     其它类型：{', '.join(f'{k}×{len(by_type[k])}' for k in others)}")
        print(f"     带廊桥 {jetways} · 区域字母 {', '.join(f'{k}={v}' for k, v in sorted(areas.items())[:8])}")
        for item in rows[:3]:
            ident = f"{item['name'] or ''}{item['number'] if item['number'] is not None else ''}{item['suffix'] or ''}"
            print(f"     样本 {ident or '(无名)':8} {item['laty']:.5f},{item['lonx']:.5f} "
                  f"hdg={item['heading']} r={item['radius']} jetway={item['has_jetway']}")
    con.close()


def pick(airports: list[str], types: list[str], db: Path) -> None:
    """用真实库跑一遍选位（需要仓库包路径）。"""
    for pkg in ("aoc_navdata", "aoc_core", "aoc_protocol", "aoc_route", "aoc_integrations"):
        path = str(ROOT / "packages" / pkg)
        if path not in sys.path:
            sys.path.insert(0, path)
    from aoc_core.ops import stands as stand_rules
    from aoc_navdata import NavData
    from aoc_navdata.navdata import MSFS_STAND_RADIUS_SCALE

    # MSFS 库的 radius 是模拟器内部值（英尺半径），按 §49 折算成「允许翼展」再比
    scale = MSFS_STAND_RADIUS_SCALE if "msfs" in db.name.lower() else 1.0
    nav = NavData(db, stand_radius_scale=scale)
    for icao in airports:
        stands = nav.stands(icao)
        print(f"\n== {icao}：{len(stands)} 个机位（NavData）")
        for kind in types:
            kind = kind.upper()
            if kind in WINGSPANS:
                wingspan = WINGSPANS[kind]
            else:
                try:
                    wingspan = float(kind)
                except ValueError:
                    print(f"  跳过 {kind}（不认识，也未给翼展）")
                    continue
            # §49 起选位是「满足硬约束后随机」，所以多跑几次看候选规模而不是看单次结果
            idents = set()
            picked = {}
            for _ in range(30):
                picked = stand_rules.pick_for_flight(
                    stands, wingspan_m=wingspan, role="AIRLINER")
                idents.add((picked.get("stand") or {}).get("ident"))
            print(f"  {wingspan:5.1f} m → 候选 {picked.get('candidates')} 个，"
                  f"30 次抽到 {len(idents)} 个不同机位：{', '.join(sorted(map(str, idents))[:8])}"
                  f"{'  ⚠ ' + '；'.join(picked.get('warnings') or []) if picked.get('warnings') else ''}")
    nav.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="V-7：Little Navmap parking 表探针")
    parser.add_argument("airports", nargs="*", default=list(DEFAULT_AIRPORTS))
    parser.add_argument("--db", action="append", default=[], help="额外/指定的 navdata 路径")
    parser.add_argument("--pick", nargs="*", default=[], metavar="TYPE",
                        help="顺带跑选位（A320 / B77W / A388 或直接给翼展米数）")
    args = parser.parse_args(argv)

    dbs = [Path(p) for p in args.db] or DEFAULT_DBS
    for path in dbs:
        describe(path, [a.upper() for a in args.airports])
    if args.pick:
        pick([a.upper() for a in args.airports], args.pick, dbs[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
