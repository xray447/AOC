"""V-04 Volanta 已飞航线探针。

只做三件事，全部只读：
1. 复用 japan-flight-dispatcher 的会话诊断，判断本机能否拿到登录令牌；
2. 用固定 fixture 验证 /api/v1/Flights 响应 → 起降对计数的解析；
3. 用固定 fixture 验证官方 CSV 导出的兜底解析。
不调用真实 API、不落盘、不打印任何令牌。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "japan-flight-dispatcher"))

from dispatcher import volanta  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    diagnosis = volanta.diagnose_volanta_session()

    flights = {"flights": [
        {"flight": {"originIcao": "RJTT", "destinationIcao": "RJAA"}},
        {"flight": {"originIcao": "RJTT", "destinationIcao": "RJAA"}},
        {"flight": {"origin": {"icaoCode": "RJAA"}, "destination": {"icaoCode": "RJCC"}}},
        {"flight": {"originIcao": "BAD", "destinationIcao": "RJTT"}},
    ]}
    counts = volanta._counts_from_flights_obj(flights)
    csv_counts = volanta._load_volanta_csv(HERE / "data" / "volanta_flights_sample.csv")

    checks = {
        "api_counts_ok": counts.get(("RJTT", "RJAA")) == 2 and counts.get(("RJAA", "RJCC")) == 1
        and len(counts) == 2,
        "csv_counts_ok": csv_counts.get(("RJTT", "RJAA")) == 2 and csv_counts.get(("RJCC", "RJTT")) == 1,
        "diagnosis_is_known": diagnosis in {
            "token_ok", "no_dirs", "no_volanta", "logged_out", "orbx_expired", "unreadable"},
    }
    report = {
        "probe": "V-04 Volanta flown routes",
        "diagnosis": diagnosis,
        "diagnosis_message": volanta._DIAG_MSGS.get(diagnosis),
        "network_api_called": False,
        "api_fixture_counts": {f"{d}|{a}": n for (d, a), n in counts.items()},
        "csv_fixture_counts": {f"{d}|{a}": n for (d, a), n in csv_counts.items()},
        "checks": checks,
        "notes": [
            "会话诊断只读浏览器 localStorage，token 既未打印也未用于联网。",
            "真实 /api/v1/Flights 调用需要有效令牌 + 外网，M0 环境不具备，故未执行。",
        ],
    }
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
