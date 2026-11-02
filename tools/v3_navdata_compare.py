"""V-3 / §36 探针：比较「现实 navdata」与「从 MSFS 场景扫出来的库」里的机场跑道。

Little Navmap 可以把 MSFS 场景（BGL）扫成一份 sqlite：
  %APPDATA%/ABarthel/little_navmap_db/little_navmap_msfs24.sqlite
它反映的是**游戏里的**跑道（长度/宽度/航向/入口坐标），而 navigraph 库是现实数据。
两者不一致时，AOC 的接地区视图就会画偏（WMKN：3480 m vs 3060 m）。

用法：
    python tools/v3_navdata_compare.py [ICAO] [--db 路径]...
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE = Path.home() / "AppData" / "Roaming" / "ABarthel" / "little_navmap_db"
DEFAULT_DBS = [
    BASE / "little_navmap_navigraph.sqlite",
    BASE / "little_navmap_msfs24.sqlite",
    BASE / "little_navmap_msfs.sqlite",
]
FT_TO_M = 0.3048


def describe(path: Path, icao: str) -> None:
    if not path.exists():
        print(f"\n== {path.name}：不存在")
        return
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    print(f"\n== {path.name}")
    row = con.execute("select * from airport where ident=?", (icao,)).fetchone()
    if row is None:
        print(f"  没有 {icao}")
        con.close()
        return
    ap = dict(row)
    print(f"  airport id={ap.get('airport_id')} name={ap.get('name')} elev={ap.get('altitude')}")
    for r in con.execute("select * from runway where airport_id=?", (ap["airport_id"],)):
        d = dict(r)
        length_ft = d.get("length")
        length_m = round(length_ft * FT_TO_M, 1) if isinstance(length_ft, (int, float)) else None
        print(f"  runway hdg={d.get('heading')} length={length_ft}ft ({length_m} m) "
              f"width={d.get('width')} primary=({d.get('primary_lonx')}, {d.get('primary_laty')})")
        for end_id in (d.get("primary_end_id"), d.get("secondary_end_id")):
            end = con.execute("select * from runway_end where runway_end_id=?", (end_id,)).fetchone()
            if end:
                e = dict(end)
                print(f"    end {e.get('name')} offset_threshold={e.get('offset_threshold')} "
                      f"hdg={e.get('heading')}")
    con.close()


def main(argv: list[str]) -> int:
    icao = "WMKN"
    dbs = list(DEFAULT_DBS)
    i = 1
    while i < len(argv):
        if argv[i] == "--db" and i + 1 < len(argv):
            dbs = [Path(argv[i + 1])]
            i += 2
            continue
        if not argv[i].startswith("-"):
            icao = argv[i].upper()
        i += 1
    print(f"机场 {icao}")
    for path in dbs:
        describe(path, icao)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
