"""V-5 探针：验证「推出判定 = 地面 GS >= 5kt 持续 3s」在真实录制里是否可用（docs/TODO §32 方案 B）。

对每段 SimLink 录制（simlink-queue/<id>/samples.jsonl）检查：
  1. 首次「地面 + GS >= 5kt」的时刻，以及连续保持是否 >= 3s（判据能不能触发）
  2. 该点之前是否已经离地（`seen_airborne`）——空中接入不能当推出
  3. 开录时是否已经在动（晚接入：首帧 GS >= 5kt）→ 需要兜底
  4. 触发点附近 ZFW（total − fuel）的稳定性：中位数 5 帧 / 相邻跳变 >10% 是否可行

用法：
    python tools/v5_pushback_probe.py [queue_dir]
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HOME = Path.home() / "AppData" / "Local" / "AOC"
DEFAULT_QUEUE = HOME / "simlink-queue"
GS_PUSHBACK_KT = 5.0
HOLD_S = 3.0
STABLE_WINDOW_S = 15.0


def load(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def zfw(sample: dict) -> float | None:
    total, fuel = sample.get("total_weight_kg"), sample.get("fuel_weight_kg")
    if isinstance(total, (int, float)) and isinstance(fuel, (int, float)):
        return float(total) - float(fuel)
    return None


def main(argv: list[str]) -> int:
    queue = Path(argv[1]) if len(argv) > 1 else DEFAULT_QUEUE
    files = sorted(queue.glob("*/samples.jsonl"))
    if not files:
        print(f"没有录制产物：{queue}")
        return 1
    print(f"{len(files)} 段录制；判据：地面 GS >= {GS_PUSHBACK_KT}kt 连续 >= {HOLD_S}s\n")
    trigger = late = airborne_only = 0
    for path in files:
        samples = load(path)
        if len(samples) < 5:
            continue
        first = samples[0]
        first_gs = float(first.get("gs_kt") or 0)
        t0 = float(first.get("t") or 0)
        # 真实起飞 = 连续空中 >= 60s（幽灵瞬移只会产出几秒的「假空中」）
        real_takeoff = None
        run_start = None
        for s in samples:
            if s.get("on_ground"):
                if run_start is not None:
                    if float(s.get("t") or 0) - run_start >= 60.0:
                        real_takeoff = run_start
                        break
                    run_start = None
            else:
                run_start = float(s.get("t") or 0) if run_start is None else run_start
        hit = None
        for i, s in enumerate(samples):
            t = float(s.get("t") or 0)
            if real_takeoff is not None and t >= real_takeoff:
                break
            if not s.get("on_ground") or float(s.get("gs_kt") or 0) < GS_PUSHBACK_KT:
                continue
            # 模拟 C#：从候选帧起表，找到第一个 t - since >= HOLD 的帧，中间必须一直满足条件
            j = i
            while j < len(samples) and float(samples[j].get("t") or 0) - t < HOLD_S:
                j += 1
            if j >= len(samples):
                continue
            window = samples[i:j + 1]
            held = all(x.get("on_ground") and float(x.get("gs_kt") or 0) >= GS_PUSHBACK_KT
                       for x in window)
            if held:
                hit = i
                break
        tag = [f"起飞 t={real_takeoff:.0f}s" if real_takeoff is not None else "无真实起飞"]
        if hit is None:
            if not first.get("on_ground"):
                tag.append("空中接入（无推出）")
                airborne_only += 1
            elif first_gs >= GS_PUSHBACK_KT:
                tag.append("地面晚接入 → 需兜底取首帧")
                late += 1
            else:
                tag.append("不触发")
        else:
            trigger += 1
            s = samples[hit]
            z = zfw(s)
            near = [zfw(x) for x in samples[hit:]
                    if float(x.get("t") or 0) <= float(s.get("t") or 0) + STABLE_WINDOW_S]
            near = [v for v in near if v is not None]
            spread = ""
            if z and len(near) >= 2:
                lo, hi = min(near), max(near)
                med = statistics.median(near)
                spread = (f"ZFW 中位 {med:,.0f}kg / 窗口 {STABLE_WINDOW_S:.0f}s 波动 "
                          f"{(hi - lo):,.0f}kg ({(hi - lo) / med * 100:.2f}%)")
            tag.append(f"触发 t={float(s.get('t') or 0):.1f}s" + (f"；{spread}" if spread else ""))
        print(f"{path.parent.name[:8]}  {len(samples):4d} 帧 / "
              f"{float(samples[-1].get('t') or 0) - t0:6.0f}s  首帧 GS={first_gs:5.1f}kt "
              f"gnd={first.get('on_ground')}  → {'; '.join(tag)}")
    print(f"\n可触发推出：{trigger}/{len(files)}；空中接入 {airborne_only}；地面晚接入 {late}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
