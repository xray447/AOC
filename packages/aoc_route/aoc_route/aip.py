"""AIP 官方航路提供者。

MVP 随包只带 fixture（明确标注 source/aip_version），生产由用户/项目提供
`data/aip_routes.csv` 或设置里的路径；也可通过 `refresh(url)` 拉线上 CSV。
"""
from __future__ import annotations

import csv
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURE = ROOT / "data" / "aip_routes.csv"
SAMPLE_FIXTURE = ROOT / "data" / "aip_routes_sample.csv"


def default_aip_path() -> Path:
    return DEFAULT_FIXTURE if DEFAULT_FIXTURE.exists() else SAMPLE_FIXTURE


class AipProvider:
    def __init__(self, path: str | Path | None = None, url: str | None = None):
        self.path = Path(path) if path else default_aip_path()
        self.url = url
        self._rows: list[dict] | None = None
        self.status = "not_loaded"
        self.last_error = ""
        self.fetched_at: str | None = None

    def refresh(self, timeout: float = 10.0) -> bool:
        if not self.url:
            self.status = "offline_fixture"
            return False
        try:
            with urllib.request.urlopen(self.url, timeout=timeout) as resp:
                text = resp.read().decode("utf-8-sig")
            path = self.path.with_suffix(".live.csv")
            path.write_text(text, encoding="utf-8")
            self.path = path
            self._rows = None
            self.status = "live"
            self.fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return True
        except Exception as exc:  # noqa: BLE001
            self.status = "offline_fixture"
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

    def load(self) -> list[dict]:
        if self._rows is not None:
            return self._rows
        rows: list[dict] = []
        if not self.path.exists():
            self.status = "missing"
            self._rows = []
            return self._rows
        with self.path.open("r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                route = (r.get("route") or "").strip()
                if not route:
                    continue
                rows.append({
                    "dep": (r.get("dep") or "").strip().upper(),
                    "arr": (r.get("arr") or "").strip().upper(),
                    "route": " ".join(route.split()),
                    "min_fl": int(float(r.get("min_fl") or 0)),
                    "max_fl": int(float(r.get("max_fl") or 0)),
                    "source": (r.get("source") or "fixture").strip(),
                    "airac": (r.get("airac") or "").strip(),
                    "sid": (r.get("sid") or "").strip() or None,
                    "star": (r.get("star") or "").strip() or None,
                    "runway": (r.get("runway") or "").strip() or None,
                    "distance_nm": float(r["distance_nm"]) if (r.get("distance_nm") or "").strip() else None,
                })
        self._rows = rows
        if self.status == "not_loaded":
            self.status = "offline_fixture" if "sample" in self.path.name else "file"
        return self._rows

    @property
    def version(self) -> str | None:
        rows = self.load()
        if not rows:
            return None
        airacs = sorted({r["airac"] for r in rows if r["airac"]})
        return f"aip-{airacs[-1]}" if airacs else self.status

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
        # 候选按航路长度（token 数）从短到长；MVP 取首条
        out.sort(key=lambda r: len(r["route"].split()))
        return out
