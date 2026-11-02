"""V-4 探针：统计「合计航时下限（默认 上限 −25%）」加上后会不会常态 0 候选（docs/TODO §34）。

做法：复制一份 aoc.db 到 out/_v4.db（只读语义，绝不改原库），用真实机队 + 真实班期实例
跑 `_build_chains` / `_virtual_chains`，对每条链算合计 block，按不同的 `max_block_minutes`
统计「达标链 / 低于下限的链 / 一架飞机都没有达标链」的数量。

用法：
    python tools/v4_draw_probe.py [--limits 480,360,240] [--virtual]
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for pkg in (ROOT / "packages").glob("*"):
    if (pkg / pkg.name).is_dir():
        sys.path.insert(0, str(pkg))

from aoc_core.aircraft import AircraftCatalog  # noqa: E402
from aoc_core.db import Database  # noqa: E402
from aoc_core.ops.service import OpsService, _iso, _now  # noqa: E402
from aoc_navdata import NavData  # noqa: E402

HOME = Path.home() / "AppData" / "Local" / "AOC"
COPY = ROOT / "out" / "_v4.db"


def settings() -> dict:
    import sqlite3
    con = sqlite3.connect(f"file:{HOME / 'aoc.db'}?mode=ro", uri=True)
    row = con.execute("select value_json from app_setting where key='settings'").fetchone()
    con.close()
    return json.loads(row[0]) if row else {}


def prepare_db() -> Path:
    for suffix in ("", "-wal", "-shm"):
        src = HOME / f"aoc.db{suffix}"
        if src.exists():
            shutil.copy2(src, COPY.with_name(COPY.name + suffix))
    return COPY


class Paths:
    """最小化的 AppPaths 替身：只要 db 路径指到副本。"""

    def __init__(self, db_path: Path):
        self.db = db_path
        self.home = db_path.parent
        self.tracks = db_path.parent / "tracks"
        self.logs = db_path.parent / "logs"


def main(argv: list[str]) -> int:
    limits = [480, 360, 240]
    for arg in argv[1:]:
        if arg.startswith("--limits="):
            limits = [int(x) for x in arg.split("=", 1)[1].split(",") if x.strip()]
    virtual = "--virtual" in argv

    cfg = settings()
    nav_path = cfg.get("navdata_path")
    nav = NavData(nav_path) if nav_path and Path(nav_path).exists() else None
    print(f"navdata: {nav_path}  ({'已加载' if nav else '不可用'})")

    db_copy = prepare_db()
    db = Database(Paths(db_copy))
    catalog = AircraftCatalog(ROOT / "data" / "aircraft_types.json")
    ops = OpsService(db, lambda: nav, catalog)
    types = ops._type_map()
    now = _now()
    fleet = [a for a in ops.list_fleet() if a["status"] == "ACTIVE" and not a.get("locked")]
    print(f"可用飞机 {len(fleet)} 架\n")

    for limit in limits:
        # §34 落地后 `_build_chains` 会按下限过滤：探针要统计原始分布，显式关掉下限
        constraints = ops._constraints({"max_block_minutes": limit, "follow_routes": not virtual,
                                        "min_total_block_minutes": 0})
        total_min = max(30, round(limit * 0.75))
        window_end = now + timedelta(hours=constraints["window_hours"])
        excluded = set(constraints["excluded_airports"])
        by_dep: dict[str, list[dict]] = {}
        if constraints["follow_routes"]:
            instances = ops._available_instances(
                _iso(now - timedelta(minutes=15)), _iso(window_end), excluded)
            instances = [i for i in instances if (i.get("mission_type") or "SCHEDULED") != "CHARTER"]
            for item in instances:
                by_dep.setdefault(item["dep_icao"].upper(), []).append(item)
            for items in by_dep.values():
                items.sort(key=lambda x: x["scheduled_dep_utc"])
        pool_cache: dict = {}
        chains_all = in_range = below = 0
        no_hit: list[str] = []
        for ac in fleet:
            ac_type = types.get(ac["type_id"]) or {}
            chains = (ops._build_chains(ac, ac_type, by_dep, constraints, now, window_end, excluded)
                      if constraints["follow_routes"]
                      else ops._virtual_chains(ac, ac_type, constraints, now, window_end, pool_cache))
            if not chains:
                continue
            hit = False
            for chain in chains:
                total = sum(ops._instance_block(inst, ac_type) for inst in chain)
                chains_all += 1
                if total < total_min:
                    below += 1
                elif total <= limit:
                    in_range += 1
                    hit = True
            if not hit:
                no_hit.append(ac.get("registration") or ac.get("id", "")[:8])
        mode = "虚拟航段" if virtual else "遵循航线"
        print(f"合计上限 {limit} min → 下限 {total_min} min（{mode}）")
        print(f"  链 {chains_all} 条：达标 {in_range} / 低于下限 {below}"
              f"（下限过滤掉 {below / chains_all * 100:.0f}%）" if chains_all else "  没有链")
        print(f"  没有达标链的飞机：{len(no_hit)} 架 {no_hit[:6]}")
        print(f"  → {'全灭风险：需要「放宽一次」兜底' if in_range == 0 else 'OK'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
