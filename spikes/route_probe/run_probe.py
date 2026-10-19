"""V-05 / V-06 探针：四个典型场景 + 断言 + 报告。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from service import RouteService

OUT = Path(__file__).resolve().parent / "out"


def run_case(name: str, svc: RouteService, dep: str, arr: str, fl: int = 350,
             force: str | None = None, expect: str = "AIP", strict: bool = True) -> dict:
    r = svc.generate(dep, arr, fl, force=force)
    r["case"] = name
    r["expect"] = expect
    r["strict"] = strict
    print(f"[{name}] status={r['status']} provider={r['provider']} "
          f"conf={r['confidence']} ms={r['elapsed_ms']} navdata={r['navdata_checked']}")
    if r["route"]:
        print("   ", r["route"][:160])
    for a in r["attempts"]:
        print(f"    - {a['provider']}: {a['status']} {a['reason']} ({a['ms']}ms)")
    return r


def assert_case(c: dict) -> list[str]:
    errs = []
    name = c["case"]
    if c["status"] == "deferred":
        if c["expect"] != "SIMBRIEF":
            errs.append(f"{name}: 期望 {c['expect']}，实际 deferred")
        if "dispatch.simbrief.com" not in (c["external_url"] or ""):
            errs.append(f"{name}: SimBrief 链接缺失")
        if c["route"]:
            errs.append(f"{name}: SimBrief 分支不应编造航路")
        return errs
    if c["status"] != "ok":
        return [f"{name}: status={c['status']} warnings={c['warnings']}"]
    if c["provider"] != c["expect"]:
        errs.append(f"{name}: provider={c['provider']} 期望 {c['expect']}")
    if c["tokens"] and (c["tokens"][0].upper() != c["dep"] or c["tokens"][-1].upper() != c["arr"]):
        errs.append(f"{name}: 航路首末点与起降机场不一致")
    if c["navdata_checked"]:
        cov = c.get("coverage", {})
        if cov.get("pass") is False:
            errs.append(f"{name}: 覆盖检查失败却返回 ok")
        alt = c.get("altitude", {})
        if alt.get("valid") is False:
            errs.append(f"{name}: 高度检查失败却返回 ok")
    return errs


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    svc = RouteService()
    svc_nav_off = RouteService(navdata_path="")

    cases = [
        run_case("AIP_RJTT_RJAA", svc, "RJTT", "RJAA", 350, expect="AIP"),
        run_case("GRAPH_ZBAA_ZSSS", svc, "ZBAA", "ZSSS", 350, expect="GRAPH"),
        run_case("SIMBRIEF_LROP_LFPG", svc, "LROP", "LFPG", 350, force="simbrief", expect="SIMBRIEF"),
        run_case("CROSS_EGLL_KJFK", svc, "EGLL", "KJFK", 350, expect="SIMBRIEF", strict=False),
        run_case("NO_NAVDATA_RJTT_RJAA", svc_nav_off, "RJTT", "RJAA", 350, force="aip", expect="AIP"),
    ]

    errs = []
    deviations = []
    for c in cases:
        case_errs = assert_case(c)
        if "dispatch.simbrief.com" not in (c.get("external_url") or ""):
            case_errs.append(f"{c['case']}: simbrief_url 为空")
        if c.get("strict", True):
            errs.extend(case_errs)
        else:
            deviations.extend(case_errs)

    # AIP 同名航路强校验：fixture 里的 Y803 必须原样出现在航路串里
    aip = cases[0]
    if aip["route"] and "Y803" not in aip["tokens"]:
        errs.append("AIP_RJTT_RJAA: 航路串未保留 AIP 同名航路 Y803")

    # 逐航段高度校验必须真的命中数据，否则等于没校验
    graph_case = next(c for c in cases if c["case"] == "GRAPH_ZBAA_ZSSS")
    if graph_case["altitude"].get("checked", 0) < 1:
        errs.append("GRAPH_ZBAA_ZSSS: 逐航段高度校验未命中任何航段")

    report = {
        "probe": "V-05/V-06 route provider chain",
        "navdata": {
            "loaded": svc.nav is not None,
            "airac": svc.nav.airac if svc.nav else None,
            "load_ms": svc.nav_load_ms,
            "error": svc.nav_error,
        },
        "graph": {
            "available": svc.graph.available,
            "load_ms": svc.graph.load_ms,
            "error": svc.graph.error,
        },
        "aip": {"status": svc.aip.status, "error": svc.aip.last_error,
                "fixture": str(svc.aip.fixture)},
        "cases": cases,
        "errors": errs,
        "deviations": deviations,
        "fidelity_notes": [
            "M0 环境无外网，AIP 使用 fixture（source=fixture-jp-routes），仅验证管线与校验，不代表真实 AIP 数据。",
            "network.pkl 的边没有 min/max FL，本探针改为按航路串还原航段、用 navdata 的 (航路, 两端 ident) 反查高度限制。",
            "AIP 样本航路以 DCT 连接、Y803 只有一个端点，因此该用例高度校验记为未知，不代表校验失效。",
            "navdata 的 airway 表存在 min>max 脏区间（如 Y803 为 250..245），已按未知处理，不用它做名字级校验。",
        ],
    }
    (OUT / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# V-05 / V-06 航路优先级探针报告（自动生成）", "",
             f"- navdata：{'OK' if svc.nav else 'UNAVAILABLE'} / AIRAC {report['navdata']['airac']} / "
             f"load {report['navdata']['load_ms']}ms",
             f"- graph：{'OK' if svc.graph.available else 'UNAVAILABLE'} / load {svc.graph.load_ms}ms",
             f"- AIP：{svc.aip.status} / {svc.aip.last_error or '无错误'}",
             "", "| 用例 | 期望 | 实际 provider | 状态 | 置信度 | 覆盖 | 高度 | 耗时 | 备注 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for c in cases:
        cov = c.get("coverage", {})
        alt = c.get("altitude", {})
        cov_s = ("PASS" if cov.get("pass") else "FAIL") if cov.get("checked") else "未检查"
        alt_s = ("PASS" if alt.get("valid") else "FAIL") if alt.get("valid") is not None else "未检查"
        note = ",".join(c["warnings"]) or "-"
        lines.append(f"| {c['case']} | {c['expect']} | {c['provider']} | {c['status']} | "
                     f"{c['confidence']} | {cov_s} | {alt_s} | {c['elapsed_ms']}ms | {note} |")
    lines += ["", "## 断言", ""]
    lines += [f"- FAIL: {e}" for e in errs] or ["- 全部通过"]
    if deviations:
        lines += ["", "## 与路线图预期的差异（记录，不影响断言）", ""]
        lines += [f"- {d}" for d in deviations]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
