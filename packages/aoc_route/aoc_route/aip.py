"""AIP 官方航路提供者。

数据来源（按优先级）：

1. 设置里的 `aip_path`（用户自备 CSV）；
2. `data/aip_routes.csv`（项目自备真实数据）；
3. 自动同步的日本 AIP（`jp-routes`，缓存到 `%LOCALAPPDATA%/AOC/cache/aip_routes_jp.csv`）；
4. 内置样例 `data/aip_routes_sample.csv`（仅验证优先级，带 `fixture` 标记）。

列名兼容两套写法：

* AOC 原生：`dep,arr,route,min_fl,max_fl,source,airac,sid,star,runway,distance_nm`
* 日本 jp-routes：`DEP,DEST,Time Restriction,Altitude,Aircraft,Route,Remarks`
  （见 japan-flight-dispatcher/PRD.md；`Altitude` 会尽量解析成 min/max FL）
"""
from __future__ import annotations

import csv
import re
import time
import urllib.request
from pathlib import Path

def _resolve_root() -> Path:
    """仓库布局 / PyInstaller onedir 都能定位 `data`（D-30）。"""
    import os
    import sys

    env = os.environ.get("AOC_ROOT")
    if env and Path(env).is_dir():
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", str(Path(sys.executable).parent)))
    return Path(__file__).resolve().parents[3]


ROOT = _resolve_root()
DEFAULT_FIXTURE = ROOT / "data" / "aip_routes.csv"
SAMPLE_FIXTURE = ROOT / "data" / "aip_routes_sample.csv"

# 日本 AIP 推荐航路（311 个 RJ/RO 机场对），由 jp-routes 维护
JP_ROUTES_URL = "https://jp-routes.vercel.app/public/routes.csv"
JP_ROUTES_TTL_DAYS = 28

# 列名别名：统一小写、去空格后匹配，兼容 AOC / jp-routes / 常见变体
_ALIASES = {
    "dep": ("dep", "adep", "origin", "from"),
    "arr": ("arr", "adest", "dest", "destination", "to"),
    "route": ("route", "routing", "route_string"),
    "min_fl": ("min_fl", "fl_min", "minflightlevel"),
    "max_fl": ("max_fl", "fl_max", "maxflightlevel"),
    "source": ("source", "src"),
    "airac": ("airac", "cycle"),
    "sid": ("sid", "departure"),
    "star": ("star", "arrival"),
    "runway": ("runway", "rwy"),
    "distance_nm": ("distance_nm", "distance", "dist_nm"),
    "altitude": ("altitude", "fl", "flight_level", "levels"),
}

_NUM_RE = re.compile(r"\d+")


def default_aip_path() -> Path:
    return DEFAULT_FIXTURE if DEFAULT_FIXTURE.exists() else SAMPLE_FIXTURE


def _norm_keys(row: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        k = str(key).strip().lower().replace(" ", "_")
        out.setdefault(k, (value or "").strip() if isinstance(value, str) else value)
    return out


def _pick(row: dict, field: str) -> str:
    for alias in _ALIASES[field]:
        value = row.get(alias)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _to_fl(raw: str) -> int:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    if value > 600:                      # 29000 → FL290
        value = value / 100.0
    return int(round(value))


def parse_altitude(text: str) -> tuple[int, int]:
    """把 jp-routes 的 `Altitude` 列解析成 (min_fl, max_fl)。

    支持 `FL290-FL410` / `290-410` / `29000-41000` / `FL290以上` 等写法；
    只有一个数值时视为下限，上限留空（0 = 不限）；解析不了返回 (0, 0)。
    """
    nums = [int(n) for n in _NUM_RE.findall(text or "")]
    fls = sorted({_to_fl(str(n)) for n in nums if 0 < _to_fl(str(n)) <= 450})
    if not fls:
        return 0, 0
    if len(fls) == 1:
        return fls[0], 0
    return fls[0], fls[-1]


def sync_jp_routes(cache_path: str | Path, url: str = JP_ROUTES_URL,
                   ttl_days: float = JP_ROUTES_TTL_DAYS,
                   timeout: float = 5.0) -> Path | None:
    """把日本 AIP 航路同步到本地缓存（网络优先，失败回退旧缓存）。

    返回可用缓存路径；既无网络又无缓存时返回 `None`。缓存未过期时直接返回，
    不会发起请求（所以启动时调用是廉价的）。
    """
    cache = Path(cache_path)
    if cache.exists() and ttl_days > 0:
        age = time.time() - cache.stat().st_mtime
        if age < ttl_days * 86400:
            return cache
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AOC"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8-sig")
    except Exception:  # noqa: BLE001
        return cache if cache.exists() else None

    head = text.splitlines()[0].lower() if text.strip() else ""
    if "dep" not in head or "des" not in head:
        # 拿到的不是航路 CSV（代理页/错误页），保留旧缓存
        return cache if cache.exists() else None

    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(cache.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(cache)
    return cache


class AipProvider:
    def __init__(self, path: str | Path | None = None, url: str | None = None,
                 default_source: str | None = None):
        self.path = Path(path) if path else default_aip_path()
        self.url = url
        self.default_source = default_source
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

    def _default_source(self) -> str:
        if self.default_source:
            return self.default_source
        return "fixture" if "sample" in self.path.name else "file"

    def load(self) -> list[dict]:
        if self._rows is not None:
            return self._rows
        rows: list[dict] = []
        if not self.path.exists():
            self.status = "missing"
            self._rows = []
            return self._rows
        source_default = self._default_source()
        with self.path.open("r", encoding="utf-8-sig", newline="") as f:
            for raw in csv.DictReader(f):
                row = _norm_keys(raw)
                route = " ".join(_pick(row, "route").split())
                if not route:
                    continue
                dep = _pick(row, "dep").upper()
                arr = _pick(row, "arr").upper()
                if len(dep) != 4 or len(arr) != 4 or dep == arr:
                    continue
                min_fl = _to_fl(_pick(row, "min_fl"))
                max_fl = _to_fl(_pick(row, "max_fl"))
                if not min_fl and not max_fl:
                    min_fl, max_fl = parse_altitude(_pick(row, "altitude"))
                distance = _pick(row, "distance_nm")
                try:
                    distance_nm = float(distance) if distance else None
                except ValueError:
                    distance_nm = None
                rows.append({
                    "dep": dep,
                    "arr": arr,
                    "route": route,
                    "min_fl": min_fl,
                    "max_fl": max_fl,
                    "source": _pick(row, "source") or source_default,
                    "airac": _pick(row, "airac"),
                    "sid": _pick(row, "sid") or None,
                    "star": _pick(row, "star") or None,
                    "runway": _pick(row, "runway") or None,
                    "distance_nm": distance_nm,
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
