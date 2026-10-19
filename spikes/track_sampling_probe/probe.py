"""V-03 探针入口：2h / 3h 合成轨迹 → 自适应落盘 → 保真度与体积报告。"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

from binfmt import decode_points, encode_points, fidelity, write_segments
from model import Mode
from sampler import AdaptiveSampler, SamplingConfig
from synthetic import synth_flight

OUT = Path(__file__).resolve().parent / "out"
RAW_HZ = 1


def run_case(name: str, length_nm: float, budget_kb: int) -> dict:
    samples, events = synth_flight(length_nm=length_nm, hz=RAW_HZ)
    cfg = SamplingConfig()
    saved, reasons, segments = AdaptiveSampler(cfg).run(samples, events)

    track_dir = OUT / name
    if track_dir.exists():
        for f in track_dir.glob("*.bin.gz"):
            f.unlink()
    manifest = write_segments(samples, segments, track_dir)
    track_bytes = sum(m["bytes"] for m in manifest)
    manifest_bytes = len(json.dumps(manifest, ensure_ascii=False).encode("utf-8"))

    saved_idx = [i for i, _ in saved]
    fid = fidelity(samples, saved_idx)
    gap = AdaptiveSampler.max_gap(samples, saved)
    total_s = samples[-1].t

    # 固定 1Hz BIN_V1 作为对照
    baseline_bytes = len(encode_points(samples))
    # 量化误差：解码一段与原始保存点比较
    qerr_m = 0.0
    if segments and segments[0]["indices"]:
        seg = segments[0]["indices"]
        blob = encode_points([samples[i] for i in seg])
        dec = decode_points(blob, t0=samples[seg[0]].t)
        for orig, d in zip([samples[i] for i in seg], dec):
            mlat = math.radians(orig.lat)
            dx = math.radians(d.lon - orig.lon) * math.cos(mlat) * 6371000.0
            dy = math.radians(d.lat - orig.lat) * 6371000.0
            qerr_m = max(qerr_m, math.hypot(dx, dy))

    mode_counts = Counter(m for _, m in saved)
    result = {
        "case": name,
        "duration_min": round(total_s / 60.0, 1),
        "raw_points": len(samples),
        "saved_points": len(saved),
        "reduction_pct": round(100.0 * (1 - len(saved) / len(samples)), 2),
        "segments": len(segments),
        "modes": dict(mode_counts),
        "save_reasons": dict(Counter(r for rs in reasons.values() for r in rs)),
        "max_gap_s": round(gap, 1),
        "fidelity": fid,
        "quantization_error_m": round(qerr_m, 2),
        "file_bytes": track_bytes,
        "manifest_bytes": manifest_bytes,
        "file_kb": round((track_bytes + manifest_bytes) / 1024.0, 1),
        "baseline_1hz_kb": round(baseline_bytes / 1024.0, 1),
        "budget_kb": budget_kb,
        "checks": {
            "reduction_ge_60pct": result_reduction_ok(saved, samples),
            "max_gap_le_45s": gap <= 45.0,
            "deviation_le_30m": fid["max_m"] <= 30.0,
            "size_within_budget": (track_bytes + manifest_bytes) / 1024.0 <= budget_kb,
        },
        "manifest": manifest,
    }
    return result


def result_reduction_ok(saved, samples) -> bool:
    return len(saved) / max(1, len(samples)) <= 0.40


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = [run_case("track_2h", 780.0, 500), run_case("track_3h", 1250.0, 750)]
    report = {"probe": "V-03 track sampling", "raw_hz": RAW_HZ,
              "config": "STRAIGHT 20s / TURN 2s / CLIMB_DESCENT 5s / APPROACH 1s / TAXI 10s, max gap 45s",
              "cases": cases}
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# V-03 轨迹自适应采样报告（自动生成）", "",
             "| 用例 | 时长 | 原始点 | 落盘点 | 压缩率 | 最大间隔 | 偏差 max/p95 | BIN_V1 体积 | 预算 | 结论 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    all_ok = True
    for c in cases:
        ok = all(c["checks"].values())
        all_ok &= ok
        lines.append(
            f"| {c['case']} | {c['duration_min']}min | {c['raw_points']} | {c['saved_points']} | "
            f"{c['reduction_pct']}% | {c['max_gap_s']}s | {c['fidelity']['max_m']:.1f}/{c['fidelity']['p95_m']:.1f}m | "
            f"{c['file_kb']}KB | {c['budget_kb']}KB | {'PASS' if ok else 'FAIL'} |"
        )
    lines += ["", "## 细节", ""]
    for c in cases:
        lines.append(f"### {c['case']}")
        lines.append(f"- 模式分布（落盘点）：{c['modes']}")
        lines.append(f"- 保存理由：{c['save_reasons']}")
        lines.append(f"- 固定 1Hz 对照：{c['baseline_1hz_kb']}KB（自适应 {c['file_kb']}KB）")
        lines.append(f"- 量化误差（经纬度）：{c['quantization_error_m']}m")
        lines.append(f"- 分段：{c['segments']} 段")
        lines.append(f"- 检查项：{c['checks']}")
        lines.append("")
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
