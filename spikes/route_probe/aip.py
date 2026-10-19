"""AIP 航路提供者（jp-routes 形态）。

线上取数用 ``refresh()``；M0 环境无外网，探针用仓库内的 fixture 跑通管线，
返回值里保留 ``source`` 字段，避免把 fixture 当真实 AIP 数据使用。
"""
from __future__ import annotations

import csv
import time
import urllib.request
from pathlib import Path

DEFAULT_FIXTURE = Path(__file__).resolve().parent / "data" / "aip_routes_sample.csv"


class AipProvider:
    def __init__(self, fixture: str | Path | None = None, url: str | None = None):
        self.fixture = Path(fixture) if fixture else DEFAULT_FIXTURE
        self.url = url
        self._rows: list[dict] | None = None
        self.status = "not_loaded"
        self.last_error = ""
        self.fetched_at = None

    def refresh(self, timeout: float = 10.0) -> bool:
        """优先拉线上 CSV；失败时保留本地 fixture 并记录原因。"""
        if not self.url:
            self.status = "offline_fixture"
            return False
        try:
            with urllib.request.urlopen(self.url, timeout=timeout) as resp:
                text = resp.read().decode("utf-8-sig")
            path = self.fixture.with_suffix(".live.csv")
            path.write_text(text, encoding="utf-8")
            self.fixture = path
            self._rows = None
            self.status = "live"
            self.fetched_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            return True
        except Exception as exc:  # noqa: BLE001 - 探针需要把失败原因带回报告
            self.status = "offline_fixture"
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

    def load(self) -> list[dict]:
        if self._rows is None:
            rows = []
            with self.fixture.open("r", encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    route = (r.get("route") or "").strip()
                    if not route:
                        continue
                    rows.append({
                        "dep": (r.get("dep") or "").strip().upper(),
                        "arr": (r.get("arr") or "").strip().upper(),
                        "route": route,
                        "min_fl": int(float(r.get("min_fl") or 0)),
                        "max_fl": int(float(r.get("max_fl") or 0)),
                        "source": (r.get("source") or "fixture").strip(),
                        "airac": (r.get("airac") or "").strip(),
                    })
            self._rows = rows
            if self.status == "not_loaded":
                self.status = "offline_fixture"
        return self._rows

    def lookup(self, dep: str, arr: str, cruise_fl: int) -> list[dict]:
        dep, arr = dep.upper(), arr.upper()
        out = []
        for r in self.load():
            if r["dep"] != dep or r["arr"] != arr:
                continue
            if r["min_fl"] and cruise_fl < r["min_fl"]:
                continue
            if r["max_fl"] and cruise_fl > r["max_fl"]:
                continue
            out.append(r)
        return out
