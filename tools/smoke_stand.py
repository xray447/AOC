"""到达提醒的本地冒烟（docs/12）：选位 → 通知 → 通道 → 报文，全程不联网。

用的是**本机真实 navdata / 场景库**（默认路径同 AOC），临时 home 目录，跑完即删，
不会碰你的正式库。适合改完 §48 相关代码后自检。

用法：
    python -X utf8 tools/smoke_stand.py                 # 默认 ZBAA → ZSSS
    python -X utf8 tools/smoke_stand.py --arr RJTT --dep ZBAA --type A359
    python -X utf8 tools/smoke_stand.py --navdata D:\\lnm\\little_navmap_msfs24.sqlite
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for pkg in ("aoc_protocol", "aoc_core", "aoc_navdata", "aoc_route", "aoc_integrations"):
    path = str(ROOT / "packages" / pkg)
    if path not in sys.path:
        sys.path.insert(0, path)

from aoc_core.paths import AppPaths
from aoc_core.service import PersonalService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="到达提醒冒烟（docs/12 §48）")
    parser.add_argument("--dep", default="ZBAA")
    parser.add_argument("--arr", default="ZSSS")
    parser.add_argument("--type", default="A320", help="机型 ICAO（A320 / A359 / B77W …）")
    parser.add_argument("--callsign", default="AOC101")
    parser.add_argument("--navdata", help="navdata 路径（默认按 AOC 的自动探测）")
    parser.add_argument("--scenery", help="场景库路径（默认按 AOC 的自动探测）")
    parser.add_argument("--lead-nm", type=float, default=150.0)
    args = parser.parse_args(argv)

    home = Path(tempfile.mkdtemp(prefix="aoc-smoke-stand-"))
    service = None
    try:
        service = PersonalService(AppPaths.create(home))
        patch: dict[str, object] = {"stand_notice": True}
        if args.navdata:
            patch["navdata_path"] = args.navdata
        if args.scenery:
            patch["scenery_navdata_path"] = args.scenery
        service.update_settings(patch)
        nav = service.nav
        if nav is None:
            print("没有可用 navdata：用 --navdata 指定，或先在设置页选好")
            return 2
        service.ops.seed_demo()

        stands = nav.stands(args.arr)
        print(f"navdata   : {nav.path}  AIRAC {nav.airac}")
        print(f"场景库    : {nav.scenery_path or '（未配置）'}")
        print(f"{args.arr} 机位: {len(stands)} 个"
              f"  来源={(stands[0]['source'] if stands else 'none')}")
        types: dict[str, int] = {}
        for stand in stands:
            types[str(stand.get("type") or "?")] = types.get(str(stand.get("type") or "?"), 0) + 1
        if types:
            print("  类型分布: " + ", ".join(f"{k}×{v}" for k, v in sorted(types.items())))
        terminals, rules = service.ops.terminal_context(args.arr)
        print(f"  航站楼规则: {len(terminals)} 台 / {len(rules)} 条")

        service.db.insert_flight({
            "id": "smoke-stand", "status": "RECORDING", "dep_icao": args.dep,
            "arr_icao": args.arr, "callsign": args.callsign, "aircraft_type": args.type})
        notice = service.ops.ensure_stand_notice(
            "smoke-stand", eta_min=20.0, remaining_nm=args.lead_nm,
            eta_utc="2026-11-07T12:00:00Z", trigger="distance")
        stand = service.ops.flight_stand("smoke-stand") or {}
        print(f"\n机位      : {stand.get('stand_ident') or '（无）'}"
              f"  source={stand.get('source')}  status={stand.get('status')}")
        print(f"  选位明细: {stand.get('score')}")
        if notice:
            print(f"通知      : [{notice['kind']}] {notice['title']}")
            print(f"            {notice['body']}")
            print(f"  报文    : {notice['payload'].get('packet')}")
        else:
            print("通知      : 没有新建（幂等命中或没有到达机场）")
        channel = service.stand_channel(args.arr)
        print(f"通道      : {channel['channel']}"
              f"  reason={channel.get('reason') or '-'}  {channel.get('reason_text') or ''}")
        print(f"生效设置  : 提前 {service.settings['stand_lead_minutes']} min / "
              f"{service.settings['stand_lead_nm']} NM · "
              f"通道 {service.settings['stand_notice_channel']} · "
              f"尺寸筛选 {service.settings['stand_size_filter']}")
        return 0
    finally:
        if service is not None:
            service.db.close()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
