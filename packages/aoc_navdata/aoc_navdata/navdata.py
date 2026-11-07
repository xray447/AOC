"""navdata 读取、机场/跑道查询与高空航路覆盖索引。

兼容 Little Navmap / Navigraph SQLite 的常见表结构；对可选列做存在性检查，
因此不同版本（或测试用最小 fixture）都不会因为缺列直接崩掉。
"""
from __future__ import annotations

import math
import re
import sqlite3
import statistics
import threading
from pathlib import Path
from typing import Iterable

import numpy as np

CELL_DEG = 2.0
DEFAULT_RADIUS_NM = 100.0
COVERAGE_STEP_NM = 50.0
COVERAGE_END_MARGIN_NM = 50.0
MIN_CHECK_NM = 200.0
MAX_GAP_NM = 200.0
MAX_GAP_PCT = 20.0
FT_PER_M = 3.280839895
# navdata 没有 is_military 列时的军用机场兜底关键词（见 docs/TODO §23）
MILITARY_NAME_PATTERNS = (
    r"\bAIR\s*FORCE\b", r"\bAFB\b", r"\bAAF\b", r"\bNAVAL\b", r"\bARMY\b",
    r"\bMILITARY\b", r"\bAIRBASE\b", r"\bAB\b",
)
# 跑道宽度 → 可接受的最大翼展（米）。45–60 m 是 4D/4E 冲突区，只能保守按 D（52 m）
WINGSPAN_BY_WIDTH = ((45.0, 36), (60.0, 52), (float("inf"), 80))
# 机位（docs/12 §4.1）：`radius_m` 的口径统一成「这个位能停多宽的翼展（米）」，
# 判定用 `${radius_m} * STAND_RADIUS_FACTOR >= wingspan`。现实 navdata 的编号本身就是
# 翼展口径，所以系数 1.0；MSFS 场景库要折算，见 MSFS_STAND_RADIUS_SCALE。
# 若将来 V-7 探针发现口径变化，只改这两个常量，不要散落在各处。
STAND_RADIUS_FACTOR = 1.0
# Little Navmap 从 MSFS 场景库扫出的 `parking.radius` **不是米**：实测 RJGG 18 号位
# （真实 93 m）= 152、KSFO GG9（真实 66 m）= 108，比值 152/93≈1.634、108/66≈1.636，
# 与 1/0.6096≈1.640 一致（差异来自库值取整）。即：库值是「模拟器内部半径的英尺数」，
# 而模拟器 radius ≈ 该位允许翼展的一半 —— 两个 0.5 叠起来正好是英尺→米的倒数一半：
# 0.3048 m/ft × 2 = 0.6096。折算后 RJGG 18 = 92.7 m（≈93）、KSFO GG9 = 65.8 m（≈66）。
MSFS_STAND_RADIUS_SCALE = 2.0 / FT_PER_M
# Little Navmap 的 `parking.name` 里，单字母 'G'（廊桥位）与 'P'（停机坪/远机位）是
# **全局类别识别符**（全库 'P' 26.7 万行、'G' 9.1 千行），不是机位编号的一部分 ——
# 展示与比较都去掉它们（`G18` → `18`）；`GA/GB/NP/...` 这类子区字母、现实库里
# 完整的 `P212R` 这类 name 都保持原样。
GLOBAL_STAND_PREFIXES = ("G", "P")
# 到机位的真实样本与场景库编号的匹配半径（米，docs/12 S4）
STAND_SAMPLE_MATCH_M = 80.0


class NavDataError(RuntimeError):
    pass


def _military_flag(raw: object, name: object) -> bool:
    """军用机场判定：`is_military` 有值就照它，缺列/空值时退回名称关键词。"""
    try:
        if raw is not None:
            return bool(int(float(str(raw))))
    except (TypeError, ValueError):
        pass
    text = str(name or "").upper()
    return any(re.search(pattern, text) for pattern in MILITARY_NAME_PATTERNS)


def max_wingspan_for_width(width_m: float | None) -> int | None:
    """按跑道宽度推可接受的最大翼展（米）；宽度缺失时返回 None（不限制）。"""
    if width_m is None:
        return None
    for limit, wingspan in WINGSPAN_BY_WIDTH:
        if width_m < limit:
            return wingspan
    return 80


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(h)))


def intermediate(lat1: float, lon1: float, lat2: float, lon2: float, f: float) -> tuple[float, float]:
    """大圆插值，f∈[0,1]。"""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    d = 2 * math.asin(min(1.0, math.sqrt(
        math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2)))
    if d < 1e-12:
        return lat1, lon1
    a = math.sin((1 - f) * d) / math.sin(d)
    b = math.sin(f * d) / math.sin(d)
    x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
    y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
    z = a * math.sin(p1) + b * math.sin(p2)
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))


class CoverageIndex:
    """高空航段空间网格索引（只统计 J/B 且上限 >= 18000ft 的边）。"""

    def __init__(self, db_path: Path):
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "select from_lonx, from_laty, to_lonx, to_laty, minimum_altitude, maximum_altitude "
                "from airway where airway_type in ('J','B') and maximum_altitude >= 18000 "
                "and from_lonx is not null and to_lonx is not null"
            ).fetchall()
        finally:
            con.close()
        if not rows:
            self.n_edges = 0
            self.grid: dict[tuple[int, int], list[int]] = {}
            self.lat1 = self.lon1 = self.lat2 = self.lon2 = np.zeros(0)
            self.min_alt = self.max_alt = np.zeros(0)
            return
        a = np.array(rows, dtype=np.float64)
        self.lat1, self.lon1 = a[:, 1], a[:, 0]
        self.lat2, self.lon2 = a[:, 3], a[:, 2]
        self.min_alt, self.max_alt = a[:, 4], a[:, 5]
        self.n_edges = len(a)
        self.grid: dict[tuple[int, int], list[int]] = {}
        for i in range(self.n_edges):
            la0, la1 = sorted((self.lat1[i], self.lat2[i]))
            lo0, lo1 = sorted((self.lon1[i], self.lon2[i]))
            for cy in range(int(math.floor(la0 / CELL_DEG)), int(math.floor(la1 / CELL_DEG)) + 1):
                for cx in range(int(math.floor(lo0 / CELL_DEG)), int(math.floor(lo1 / CELL_DEG)) + 1):
                    self.grid.setdefault((cy, cx), []).append(i)

    def _candidates(self, lat: float, lon: float) -> np.ndarray:
        if not self.n_edges:
            return np.zeros(0, dtype=np.int64)
        r_lat = DEFAULT_RADIUS_NM / 60.0
        r_lon = DEFAULT_RADIUS_NM / (60.0 * max(0.15, math.cos(math.radians(lat))))
        out: list[int] = []
        for cy in range(int(math.floor((lat - r_lat) / CELL_DEG)),
                        int(math.floor((lat + r_lat) / CELL_DEG)) + 1):
            for cx in range(int(math.floor((lon - r_lon) / CELL_DEG)),
                            int(math.floor((lon + r_lon) / CELL_DEG)) + 1):
                out.extend(self.grid.get((cy, cx), ()))
        return np.unique(out) if out else np.zeros(0, dtype=np.int64)

    def covered(self, lat: float, lon: float, alt_ft: float) -> bool:
        idx = self._candidates(lat, lon)
        if idx.size == 0:
            return False
        ok = (self.min_alt[idx] <= alt_ft) & (self.max_alt[idx] >= alt_ft)
        idx = idx[ok]
        if idx.size == 0:
            return False
        kx = math.cos(math.radians(lat)) * 60.0
        ax = (self.lon1[idx] - lon) * kx
        ay = (self.lat1[idx] - lat) * 60.0
        bx = (self.lon2[idx] - lon) * kx
        by = (self.lat2[idx] - lat) * 60.0
        dx, dy = bx - ax, by - ay
        den = dx * dx + dy * dy
        t = np.where(den > 1e-12, np.clip(-(ax * dx + ay * dy) / np.maximum(den, 1e-12), 0.0, 1.0), 0.0)
        dist = np.hypot(ax + dx * t, ay + dy * t)
        return bool((dist <= DEFAULT_RADIUS_NM).any())


class NavData:
    def __init__(self, path: str | Path, scenery_path: str | Path | None = None,
                 runway_source: str = "auto", stand_radius_scale: float = 1.0):
        self.path = Path(path)
        # 机位半径的单位折算（docs/12 §4.1）：现实库 1.0，MSFS 场景库 MSFS_STAND_RADIUS_SCALE
        self._stand_radius_scale = float(stand_radius_scale or 1.0)
        # 跑道几何的第二数据源（§36 / D-7）：Little Navmap 从 MSFS 场景扫出的库
        # （little_navmap_msfs24.sqlite）。命中优先用游戏内数据，缺失回落现实 navdata。
        self.runway_source = (runway_source or "auto").lower()
        self.scenery_path: Path | None = None
        self._scenery: NavData | None = None
        if not self.path.exists():
            raise NavDataError(f"navdata 不存在: {self.path}")
        try:
            self._con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
            self._con.row_factory = sqlite3.Row
            self._load_airports()
        except sqlite3.Error as exc:
            raise NavDataError(f"navdata 无法读取: {exc}") from exc
        self._lock = threading.RLock()
        # 跑道按机场懒加载：全库 1.7 万座机场的跑道端一次性塞进 dict 要几十 MB，
        # 而启动阶段真正用到的只有"最长跑道"（筛选/推荐）。这里先做单位校准 +
        # 最长跑道回填，具体跑道端等查询时再按机场取（见 runways()）。
        self._runways: dict[str, list[dict]] = {}
        self._runway_cache: dict[str, int] = {}
        self._runway_sql: str | None = None
        self._runway_sql_checked = False
        self._runway_count_cache: int | None = None
        # §36 兜底 C（1.4）：手工覆盖的跑道几何，由 aoc-core 从本地库注入
        self._runway_overrides: dict[str, dict[str, dict]] = {}
        # docs/12：停机位（parking 表）按机场懒加载 + 缓存；手工覆盖同理
        self._stands: dict[str, list[dict]] = {}
        self._stand_sql: str | None = None
        self._stand_sql_checked = False
        self._stand_overrides: dict[str, dict[str, dict]] = {}
        # 覆盖生效前机场表里的原值（删除覆盖时还原）
        self._override_backup: dict[str, dict] = {}
        self._prime_runway_units()
        self._prime_runway_widths()
        self.airac, self.navdata_version = self._load_meta()
        self._coverage: CoverageIndex | None = None
        self._limits: dict[str, tuple[float, float] | None] = {}
        self._wp_ident: dict[int, str | None] = {}
        self._seg_limits: dict[tuple[str, str, str], list[tuple[float, float]]] = {}
        self._name_rows: dict[str, list[tuple[int, int, float, float]]] = {}
        self._lat_arr = np.array([a["lat"] for a in self.airports.values()], dtype=float)
        self._lon_arr = np.array([a["lon"] for a in self.airports.values()], dtype=float)
        self._ident_arr = list(self.airports.keys())
        if scenery_path:
            candidate = Path(scenery_path)
            if candidate.exists() and candidate.resolve() != self.path.resolve():
                self.scenery_path = candidate
                try:
                    # 场景库的 parking.radius 是 MSFS 内部值（英尺半径），读出来先折算成翼展口径
                    self._scenery = NavData(candidate, None, "navdata",
                                            stand_radius_scale=MSFS_STAND_RADIUS_SCALE)
                except NavDataError:
                    self._scenery = None

    # -- 加载 -------------------------------------------------------------
    def _columns(self, table: str) -> set[str]:
        try:
            return {r[1] for r in self._con.execute(f"pragma table_info({table})")}
        except sqlite3.Error:
            return set()

    def _load_airports(self) -> None:
        cols = self._columns("airport")
        if not {"ident", "laty", "lonx"} <= cols:
            raise NavDataError("navdata 缺少 airport(ident/laty/lonx)")
        self._airport_cols = cols
        optional = [c for c in (
            "name", "iata", "city", "country", "iso_country", "longest_runway_length",
            "longest_runway_width", "is_military",
            "altitude", "transition_altitude", "has_procedures",
        ) if c in cols]
        sql = "select ident, laty, lonx" + ("".join(f", {c}" for c in optional)) + " from airport where ident is not null"
        self.airports: dict[str, dict] = {}
        for r in self._con.execute(sql):
            ident = (r["ident"] or "").strip().upper()
            if len(ident) != 4:
                continue
            row = dict(r)
            self.airports[ident] = {
                "ident": ident,
                "name": row.get("name"),
                "iata": (row.get("iata") or None),
                "city": row.get("city"),
                "country": row.get("country") or row.get("iso_country"),
                "lat": row["laty"],
                "lon": row["lonx"],
                "elev_ft": row.get("altitude"),
                "transition_alt_ft": row.get("transition_altitude"),
                # 原始值单位随数据源变化，由 _prime_runway_units 统一成米/英尺
                "longest_runway_raw": row.get("longest_runway_length"),
                "longest_runway_m": None,
                "longest_runway_ft": None,
                # 跑道宽度 → 翼展上限；缺列/缺数据时为 None（不限制），详见 _prime_runway_widths
                "runway_width_raw": row.get("longest_runway_width"),
                "runway_width_m": None,
                "max_wingspan_m": None,
                # 军用机场：优先 is_military 列，缺列时退化为名称关键词
                "military": _military_flag(row.get("is_military"), row.get("name")),
                "has_procedures": bool(row.get("has_procedures")) if "has_procedures" in row else None,
            }

    def _runway_query(self) -> str | None:
        """按机场取跑道端的 SQL（列名随数据源变化，只探测一次）。"""
        if self._runway_sql_checked:
            return self._runway_sql
        self._runway_sql_checked = True
        rcols = self._columns("runway")
        ecols = self._columns("runway_end")
        if not {"airport_id", "primary_end_id", "secondary_end_id"} <= rcols or not {"runway_end_id"} <= ecols:
            return None
        length_expr = "r.length" if "length" in rcols else "null"
        ils_expr = "r.has_ils" if "has_ils" in rcols else ("r.ils" if "ils" in rcols else "null")
        # 内移入口（displaced threshold）：Little Navmap 的 runway_end.offset_threshold（英尺）
        offset_expr = "re.offset_threshold" if "offset_threshold" in ecols else "null"
        # 跑道宽度（单位同长度字段，Little Navmap / Navigraph 用英尺）
        width_expr = "r.width" if "width" in rcols else "null"
        self._runway_sql = (
            "select a.ident as airport, re.name as name, re.heading as heading, re.laty as lat, "
            f"re.lonx as lon, re.altitude as elev, {length_expr} as length, {ils_expr} as ils, "
            f"{offset_expr} as offset_threshold, {width_expr} as width "
            "from runway r join runway_end re "
            "on re.runway_end_id in (r.primary_end_id, r.secondary_end_id) "
            "join airport a on a.airport_id = r.airport_id where a.ident = ?"
        )
        return self._runway_sql

    def _load_runways_for(self, ident: str) -> list[dict]:
        """单机场跑道端（懒加载 + 缓存），顺带把该机场最长跑道精确化。"""
        key = (ident or "").strip().upper()
        if not key:
            return []
        with self._lock:
            cached = self._runways.get(key)
            if cached is not None:
                return cached
            ends: list[dict] = []
            sql = self._runway_query()
            if sql:
                try:
                    rows = self._con.execute(sql, (key,)).fetchall()
                except sqlite3.Error:
                    rows = []
                for row in rows:
                    ends.append({
                        "name": (row["name"] or "").upper(),
                        "hdg": row["heading"],
                        "lat": row["lat"],
                        "lon": row["lon"],
                        "elev_ft": row["elev"],
                        "length_raw": row["length"],
                        "offset_threshold_raw": row["offset_threshold"],
                        "width_raw": row["width"],
                        "ils": bool(row["ils"]) if row["ils"] is not None else None,
                    })
                # 跑道长度：优先 runway.length，否则由反向跑道端反推；内移入口/宽度按同一单位口径换算
                for end in ends:
                    end["length_m"] = self._runway_length_m(end, ends)
                    end["displaced_threshold_m"] = self._displaced_threshold_m(end, ends)
                    end["width_m"] = self._runway_width_m(end, ends)
            self._runways[key] = ends
            derived = max((e["length_m"] for e in ends if e.get("length_m")), default=None)
            info = self.airports.get(key)
            if info is not None and derived:
                info["longest_runway_m"] = round(derived, 1)
                info["longest_runway_ft"] = round(derived * FT_PER_M, 1)
            widths = [e["width_m"] for e in ends if e.get("width_m")]
            if info is not None and widths:
                # 同一机场跑道宽度可能不统一（如 ZGGG 60/45 m）：翼展上限取最宽的那条
                info["runway_width_m"] = round(max(widths), 1)
                info["max_wingspan_m"] = max_wingspan_for_width(info["runway_width_m"])
            return ends

    def _raw_length_is_feet(self, end: dict, ends: list[dict]) -> bool | None:
        """用两端坐标反推的几何长度判断该库的长度类字段是英尺还是米。"""
        geo = self._runway_geo_length_m(end, ends)
        raw = end.get("length_raw")
        if not raw or not geo or not (300.0 < geo < 20000.0):
            return None
        ratio = float(raw) / geo
        if 2.5 <= ratio <= 4.5:
            return True
        if 0.8 <= ratio <= 1.25:
            return False
        return None

    def _runway_length_m(self, end: dict, ends: list[dict]) -> float | None:
        geo = self._runway_geo_length_m(end, ends)
        raw = end.get("length_raw")
        if raw:
            value = float(raw)
            # runway.length 的单位因数据源而异（Little Navmap/Navigraph 用英尺）。
            # 用两端坐标反推的几何长度做比例校准，避免按绝对值猜单位：
            # 短跑道（如 1200 m = 3937 ft）会被"大于 5000 才当英尺"的阈值误判成 3937 m。
            feet = self._raw_length_is_feet(end, ends)
            if feet is True:
                return round(value / FT_PER_M, 1)
            if feet is False:
                return round(value, 1)
            # 没有可用几何参照时的兜底：米制跑道极少超过 6000 m
            return round(value / FT_PER_M, 1) if value > 5000 else round(value, 1)
        return round(geo, 1) if geo else None

    def _displaced_threshold_m(self, end: dict, ends: list[dict]) -> float:
        """内移入口（米）。缺失列 / 0 / 无法解析时按 0，旧库不受影响。"""
        raw = end.get("offset_threshold_raw")
        try:
            value = float(raw or 0)
        except (TypeError, ValueError):
            return 0.0
        if value <= 0:
            return 0.0
        feet = self._raw_length_is_feet(end, ends)
        if feet is None:
            feet = value > 500  # 内移入口极少超过 500m
        return round(value / FT_PER_M if feet else value, 1)

    def _runway_width_m(self, end: dict, ends: list[dict]) -> float | None:
        """跑道宽度（米）。缺失列 / 0 / 明显越界一律返回 None（前端用 45 m 兜底）。"""
        try:
            value = float(end.get("width_raw") or 0)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        feet = self._raw_length_is_feet(end, ends)
        if feet is None:
            feet = value > 80  # 60 m 以上的"宽度"只可能是英尺（45 m ≈ 148 ft）
        width = value / FT_PER_M if feet else value
        return round(width, 1) if 15.0 <= width <= 80.0 else None

    def _runway_geo_length_m(self, end: dict, ends: list[dict]) -> float | None:
        recip = reciprocal_name(end["name"])
        if not recip:
            return None
        other = next((e for e in ends if e["name"] == recip), None)
        if not other or end["lat"] is None or other["lat"] is None:
            return None
        if end["lon"] is None or other["lon"] is None:
            return None
        return haversine_nm(end["lat"], end["lon"], other["lat"], other["lon"]) * 1852

    def _sample_length_scale(self, sample: int = 200) -> float | None:
        """抽样估算 ``longest_runway_length`` 与几何长度的比例（≈3.28=英尺，≈1=米）。

        只读 ``sample`` 座机场的跑道端，代替原来"全库跑道表一次读完再算"的做法。
        """
        idents = [i for i, a in self.airports.items() if a.get("longest_runway_raw")]
        if not idents:
            return None
        step = max(1, len(idents) // max(1, sample))
        ratios: list[float] = []
        for ident in idents[::step][:sample]:
            ends = self._load_runways_for(ident)
            lengths = [e["length_m"] for e in ends if e.get("length_m")]
            if not lengths:
                continue
            try:
                raw = float((self.airports.get(ident) or {}).get("longest_runway_raw") or 0)
            except (TypeError, ValueError):
                continue
            meters = max(lengths)
            if raw > 0 and meters > 300:
                ratios.append(raw / meters)
        return statistics.median(ratios) if ratios else None

    def _prime_runway_units(self) -> None:
        """校准长度单位并回填每座机场的最长跑道（米/英尺）。

        ``airport.longest_runway_length`` 的单位随数据源变化（Little Navmap / Navigraph
        用英尺，自建库可能用米）。用抽样机场的比例判断单位；具体机场被查询时，
        ``_load_runways_for()`` 会用真实跑道端把最长跑道改精确。
        """
        scale = self._sample_length_scale()
        use_feet: bool | None = None
        if scale is not None:
            if 2.5 <= scale <= 4.5:
                use_feet = True
            elif 0.8 <= scale <= 1.25:
                use_feet = False
        for a in self.airports.values():
            raw = a.get("longest_runway_raw")
            meters = None
            try:
                value = float(raw or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                feet = use_feet if use_feet is not None else value > 5000
                meters = value / FT_PER_M if feet else value
            a["longest_runway_m"] = round(meters, 1) if meters else None
            a["longest_runway_ft"] = round(meters * FT_PER_M, 1) if meters else None

    def _width_m(self, raw: object, feet: bool | None) -> float | None:
        """跑道宽度原始值 → 米；单位不明时按「>80 必是英尺」兜底。越界一律 None。"""
        try:
            value = float(raw or 0)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        if feet is None:
            feet = value > 80
        width = value / FT_PER_M if feet else value
        return round(width, 1) if 15.0 <= width <= 80.0 else None

    def _prime_runway_widths(self) -> None:
        """回填每座机场的跑道宽度与翼展上限（docs/TODO §26）。

        宽度只用来给翼展上界，不能据此定飞行区等级：45 m 既可能是 4D 也可能是 4E，
        所以 45–60 m 区间保守按 52 m（D）处理。优先读 `airport.longest_runway_width`
        （一列一次读完）；缺列时对 runway 表做一次 `max(width)` 分组，避免逐机场懒加载。
        """
        feet = self._length_unit_is_feet()
        widths: dict[str, float] = {}
        if "longest_runway_width" in getattr(self, "_airport_cols", set()):
            for ident, info in self.airports.items():
                width = self._width_m(info.get("runway_width_raw"), feet)
                if width is not None:
                    widths[ident] = width
        elif "width" in self._columns("runway"):
            try:
                rows = self._con.execute(
                    "select a.ident as ident, max(r.width) as width from runway r "
                    "join airport a on a.airport_id = r.airport_id "
                    "where a.ident is not null and r.width is not null group by a.ident").fetchall()
            except sqlite3.Error:
                rows = []
            for ident, raw in rows:
                width = self._width_m(raw, feet)
                if width is not None and ident:
                    widths[str(ident).upper()] = width
        for ident, width in widths.items():
            info = self.airports.get(ident)
            if info is None:
                continue
            info["runway_width_m"] = width
            info["max_wingspan_m"] = max_wingspan_for_width(width)

    def _length_unit_is_feet(self) -> bool | None:
        """该库的长度/宽度类字段是否以英尺存储（用几何长度抽样校准）。"""
        scale = self._sample_length_scale(sample=60)
        if scale is None:
            return None
        if 2.5 <= scale <= 4.5:
            return True
        if 0.8 <= scale <= 1.25:
            return False
        return None

    def max_wingspan_m(self, ident: str | None) -> int | None:
        """机场可接受的最大翼展（米）；None = 无宽度数据，不做限制。"""
        info = self.airport(ident)
        if not info:
            return None
        if info.get("max_wingspan_m") is None and info.get("runway_width_m") is None:
            # 宽度列存在但该机场为空：读一次跑道端（有 width_m 就精确化，没有仍为 None）
            self.runways(info["ident"])
        return info.get("max_wingspan_m")

    def _load_meta(self) -> tuple[str, str]:
        try:
            row = self._con.execute("select * from metadata limit 1").fetchone()
        except sqlite3.Error:
            row = None
        if row is None:
            return "unknown", ""
        data = dict(row)
        airac = ""
        for key in ("airac", "AiracCycle", "airac_cycle", "cycle"):
            if key in data and data[key]:
                airac = str(data[key])
                break
        if not airac:
            vals = list(data.values())
            airac = str(vals[4]) if len(vals) > 4 and vals[4] else "unknown"
        version = ""
        for key in ("navdata_version", "version", "build"):
            if key in data and data[key]:
                version = str(data[key])
                break
        return airac, version

    def close(self) -> None:
        if self._scenery is not None:
            self._scenery.close()
            self._scenery = None
        try:
            self._con.close()
        except Exception:  # noqa: BLE001
            pass

    # -- 基础查询 ---------------------------------------------------------
    def airport(self, ident: str | None) -> dict | None:
        return self.airports.get((ident or "").upper())

    def runways(self, ident: str | None) -> list[dict]:
        """跑道端几何：`auto`/`scenery` 时先查游戏场景库，缺失回落现实 navdata。

        §36 兜底 C（1.4）：手工覆盖表优先于这两个数据源（`source=override`）。
        """
        key = (ident or "").strip().upper()
        if self._scenery is not None and self.runway_source != "navdata":
            rows = self._scenery.runways(key)
            if rows:
                info = self.airports.get(key)
                derived = max((r.get("length_m") or 0) for r in rows) or None
                if info is not None and derived:
                    # 跑道长度改用游戏内数据：「跑道够不够长」与 §26 的翼展推断都随之更新
                    info["longest_runway_m"] = round(float(derived), 1)
                    info["longest_runway_ft"] = round(float(derived) * FT_PER_M, 1)
                    info["runway_source"] = "scenery"
                return self._with_overrides(key, [{**r, "source": "scenery"} for r in rows])
        return self._with_overrides(
            key, [{**r, "source": "navdata"} for r in self._load_runways_for(key)])

    def set_runway_overrides(self, overrides: dict | None) -> None:
        """手工跑道覆盖（§36 兜底 C）：`{ICAO: {IDENT: {length_m,width_m,threshold_lat,threshold_lon,hdg}}}`。

        只对「场景库扫不到 / 玩家装了 add-on 机场」有用；命中后 `find_runway()` 优先读它。
        """
        cleaned: dict[str, dict[str, dict]] = {}
        for icao, items in (overrides or {}).items():
            key = str(icao or "").strip().upper()
            if len(key) != 4 or not isinstance(items, dict):
                continue
            for ident, data in items.items():
                name = str(ident or "").strip().upper()
                if not name or not isinstance(data, dict):
                    continue
                cleaned.setdefault(key, {})[name] = dict(data)
        # 先把上一轮覆盖改过的机场字段还原（删除覆盖/切换 navdata 时不留脏值）
        for icao, backup in self._override_backup.items():
            info = self.airports.get(icao)
            if info is None:
                continue
            for field, value in backup.items():
                if value is None:
                    info.pop(field, None)
                else:
                    info[field] = value
        self._override_backup = {}
        self._runway_overrides = cleaned
        # 覆盖会改长度/宽度：把受影响机场的最长跑道与翼展上限同步回机场表
        for icao in cleaned:
            info = self.airports.get(icao)
            if info is not None:
                self._override_backup[icao] = {
                    field: info.get(field) for field in (
                        "longest_runway_m", "longest_runway_ft", "runway_width_m",
                        "max_wingspan_m", "runway_source")}
            self.runways(icao)

    def runway_overrides(self) -> dict[str, dict[str, dict]]:
        return {icao: {ident: dict(data) for ident, data in items.items()}
                for icao, items in self._runway_overrides.items()}

    def _with_overrides(self, key: str, rows: list[dict]) -> list[dict]:
        overrides = self._runway_overrides.get(key)
        if not overrides:
            return rows
        out: list[dict] = []
        matched: set[str] = set()
        for row in rows:
            name = str(row.get("name") or "").strip().upper()
            data = overrides.get(name)
            if data is None:
                out.append(row)
                continue
            matched.add(name)
            out.append(self._merge_override(row, data))
        for name, data in overrides.items():
            if name not in matched:
                out.append(self._merge_override({"name": name, "ils": None}, data))
        self._refresh_airport_geometry(key, out)
        return out

    @staticmethod
    def _merge_override(row: dict, data: dict) -> dict:
        merged = {**row, "source": "override"}
        try:
            if data.get("length_m"):
                merged["length_m"] = round(float(data["length_m"]), 1)
            if data.get("width_m"):
                merged["width_m"] = round(float(data["width_m"]), 1)
            if data.get("threshold_lat") is not None and data.get("threshold_lon") is not None:
                merged["lat"] = float(data["threshold_lat"])
                merged["lon"] = float(data["threshold_lon"])
            if data.get("hdg") is not None:
                merged["hdg"] = float(data["hdg"]) % 360.0
        except (TypeError, ValueError):
            return {**row}
        return merged

    def _refresh_airport_geometry(self, key: str, rows: list[dict]) -> None:
        info = self.airports.get(key)
        if info is None:
            return
        lengths = [float(r["length_m"]) for r in rows if r.get("length_m")]
        if lengths:
            info["longest_runway_m"] = round(max(lengths), 1)
            info["longest_runway_ft"] = round(max(lengths) * FT_PER_M, 1)
        widths = [float(r["width_m"]) for r in rows if r.get("width_m")]
        if widths:
            info["runway_width_m"] = round(max(widths), 1)
            info["max_wingspan_m"] = max_wingspan_for_width(max(widths))
        info["runway_source"] = "override"

    def scenery_available(self) -> bool:
        return self._scenery is not None

    def navdata_runways(self, ident: str | None) -> list[dict]:
        """现实 navdata 的跑道几何（用于「游戏内 / 现实」对照展示）。"""
        return [{**r, "source": "navdata"} for r in self._load_runways_for((ident or "").upper())]

    # -- 停机位（docs/12 §3 / §4）-----------------------------------------
    def _stand_query(self) -> str | None:
        """按机场取停机位的 SQL（列名随 Little Navmap 版本变化，只探测一次）。"""
        if self._stand_sql_checked:
            return self._stand_sql
        self._stand_sql_checked = True
        cols = self._columns("parking")
        if not {"airport_id", "laty", "lonx"} <= cols:
            return None

        def col(name: str, *aliases: str) -> str:
            for candidate in (name, *aliases):
                if candidate in cols:
                    return f"p.{candidate} as {name}"
            return f"null as {name}"

        self._stand_sql = (
            "select "
            + col("parking_id")
            + ", " + (col("name", "parking_name")) + ", " + col("number", "parking_number")
            + ", " + col("suffix") + ", " + col("type") + ", " + col("radius")
            + ", " + col("heading") + ", " + col("has_jetway", "jetway")
            + ", " + col("airline_codes") + ", p.laty as lat, p.lonx as lon "
            "from parking p join airport a on a.airport_id = p.airport_id where a.ident = ?"
        )
        return self._stand_sql

    def _stand_row(self, row) -> dict:
        name = (row["name"] or "").strip().upper()
        suffix = (row["suffix"] or "").strip().upper()
        try:
            number = int(row["number"])
        except (TypeError, ValueError):
            number = None
        if number is not None and number < 0:
            number = None
        # 'G'/'P' 是 LNM 的全局类别标记（G=廊桥位、P=停机坪，全库 27 万行），不是编号本身
        prefix = "" if (name in GLOBAL_STAND_PREFIXES and number is not None) else name
        ident = f"{prefix}{number if number is not None else ''}{suffix}"
        if not ident:
            ident = f"#{row['parking_id']}" if row["parking_id"] is not None else (name or "STAND")
        jetway = row["has_jetway"]
        radius = row["radius"]
        return {
            "ident": ident, "name": name or None, "number": number, "suffix": suffix or None,
            "type": (row["type"] or "").strip().upper() or None,
            "lat": row["lat"], "lon": row["lon"], "heading": row["heading"],
            "radius_m": (round(float(radius) * self._stand_radius_scale, 1)
                         if isinstance(radius, (int, float)) else None),
            "has_jetway": (bool(jetway) if jetway is not None else None),
            "airline_codes": row["airline_codes"],
            "parking_id": row["parking_id"],
        }

    def _load_stands_for(self, ident: str) -> list[dict]:
        """单机场停机位（懒加载 + 缓存）。没有 parking 表 / 机场不存在时返回空列表。"""
        key = (ident or "").strip().upper()
        if not key:
            return []
        with self._lock:
            cached = self._stands.get(key)
            if cached is not None:
                return cached
            rows: list[dict] = []
            sql = self._stand_query()
            if sql:
                try:
                    fetched = self._con.execute(sql, (key,)).fetchall()
                except sqlite3.Error:
                    fetched = []
                seen: set[str] = set()
                for row in fetched:
                    stand = self._stand_row(row)
                    if stand["lat"] is None or stand["lon"] is None:
                        continue
                    # 现实 navdata 的 `number` 常为 -1，编号来自 `name`，重名时补 parking_id 保证唯一
                    if stand["ident"] in seen:
                        stand["ident"] = f"{stand['ident']}#{stand['parking_id']}"
                    seen.add(stand["ident"])
                    rows.append(stand)
            self._stands[key] = rows
            return rows

    def stands(self, ident: str | None) -> list[dict]:
        """机场停机位：`auto`/`scenery` 先查游戏场景库，缺失回落现实 navdata。

        与 `runways()` 完全同构（docs/12 §3）；手工覆盖（`airport_stand_override`）优先，
        覆盖项以 `source=override` 合并进结果。
        """
        key = (ident or "").strip().upper()
        if not key:
            return []
        if self._scenery is not None and self.runway_source != "navdata":
            rows = self._scenery.stands(key)
            if rows:
                return self._with_stand_overrides(
                    key, [{**r, "source": "scenery"} for r in rows])
        return self._with_stand_overrides(
            key, [{**r, "source": "navdata"} for r in self._load_stands_for(key)])

    def nearest_stand(self, ident: str | None, lat: float, lon: float,
                      max_m: float = STAND_SAMPLE_MATCH_M) -> dict | None:
        """最近的机位（docs/12 S4：落地/收尾时校验场景库编号）。"""
        best = None
        best_m = float(max_m)
        for stand in self.stands(ident):
            if stand["lat"] is None or stand["lon"] is None:
                continue
            meters = haversine_nm(lat, lon, stand["lat"], stand["lon"]) * 1852.0
            if meters <= best_m:
                best_m = meters
                best = {**stand, "distance_m": round(meters, 1)}
        return best

    def set_stand_overrides(self, overrides: dict | None) -> None:
        """手工机位覆盖（docs/12 S3）：`{ICAO: {IDENT: {lat, lon, heading, radius_m, ...}}}`。"""
        cleaned: dict[str, dict[str, dict]] = {}
        for icao, items in (overrides or {}).items():
            key = str(icao or "").strip().upper()
            if len(key) != 4 or not isinstance(items, dict):
                continue
            for ident, data in items.items():
                name = str(ident or "").strip().upper()
                if not name or not isinstance(data, dict):
                    continue
                if data.get("lat") is None or data.get("lon") is None:
                    continue
                cleaned.setdefault(key, {})[name] = dict(data)
        self._stand_overrides = cleaned

    def stand_overrides(self) -> dict[str, dict[str, dict]]:
        return {icao: {ident: dict(data) for ident, data in items.items()}
                for icao, items in self._stand_overrides.items()}

    def _with_stand_overrides(self, key: str, rows: list[dict]) -> list[dict]:
        overrides = self._stand_overrides.get(key)
        if not overrides:
            return rows
        out: list[dict] = []
        matched: set[str] = set()
        for row in rows:
            data = overrides.get(str(row.get("ident") or "").upper())
            if data is None:
                out.append(row)
                continue
            matched.add(str(row["ident"]).upper())
            out.append(_merge_stand_override(row, data))
        for ident, data in overrides.items():
            if ident not in matched:
                out.append(_merge_stand_override({"ident": ident}, data))
        return out

    def search_airports(self, query: str, limit: int = 20) -> list[dict]:
        q = (query or "").strip().upper()
        if not q:
            return []
        out = []
        for a in self.airports.values():
            hay = " ".join(str(a.get(k) or "") for k in ("ident", "iata", "name", "city")).upper()
            if q in hay:
                out.append(a)
                if len(out) >= limit:
                    break
        return out

    def waypoint_coords(self, idents: Iterable[str]) -> dict[str, tuple[float, float]]:
        """批量取航路点坐标（用于 .pln 导出）；缺失的 ident 不返回。"""
        wanted = [i.upper() for i in idents if i and i.upper() != "DCT"]
        if not wanted:
            return {}
        out: dict[str, tuple[float, float]] = {}
        for start in range(0, len(wanted), 200):
            chunk = wanted[start:start + 200]
            marks = ",".join("?" * len(chunk))
            try:
                rows = self._con.execute(
                    f"select ident, laty, lonx from waypoint where ident in ({marks}) "
                    "and laty is not null and lonx is not null", chunk).fetchall()
            except sqlite3.Error:
                return out
            for r in rows:
                out[(r[0] or "").upper()] = (float(r[1]), float(r[2]))
        return out

    def near_airports(self, lat: float, lon: float, radius_nm: float) -> list[tuple[dict, float]]:
        if not len(self._lat_arr):
            return []
        dlat = radius_nm / 60.0
        dlon = radius_nm / (60.0 * max(0.15, math.cos(math.radians(lat))))
        mask = (np.abs(self._lat_arr - lat) <= dlat) & (np.abs(self._lon_arr - lon) <= dlon)
        idx = np.nonzero(mask)[0]
        out = []
        for i in idx:
            a = self.airports[self._ident_arr[int(i)]]
            d = haversine_nm(lat, lon, a["lat"], a["lon"])
            if d <= radius_nm:
                out.append((a, d))
        out.sort(key=lambda x: x[1])
        return out

    def nearest_airport(self, lat: float, lon: float, max_nm: float = 10.0) -> tuple[dict | None, float | None]:
        near = self.near_airports(lat, lon, max_nm)
        return (near[0][0], near[0][1]) if near else (None, None)

    def find_runway(self, lat: float, lon: float, heading: float,
                    max_nm: float = 5.0, max_hdg_diff: float = 30.0) -> dict | None:
        """找附近且航向对齐的跑道，返回投影结果（含距入口/中线偏差）。"""
        best = None
        for a, _ in self.near_airports(lat, lon, max_nm):
            for rwy in self.runways(a["ident"]):
                if rwy["lat"] is None or rwy["lon"] is None or rwy["hdg"] is None:
                    continue
                dist = haversine_nm(lat, lon, rwy["lat"], rwy["lon"])
                if dist > max_nm:
                    continue
                diff = abs((heading - float(rwy["hdg"]) + 540) % 360 - 180)
                if diff > max_hdg_diff:
                    continue
                fix = project_on_runway(rwy, lat, lon)
                cand = {
                    "airport": a["ident"], "ident": rwy["name"], "heading": float(rwy["hdg"]),
                    "distance_nm": round(dist, 3), "heading_diff_deg": round(diff, 1),
                    "along_m": round(fix[0], 1), "lateral_m": round(fix[1], 1),
                    "length_m": rwy.get("length_m"), "ils": rwy.get("ils"),
                    "width_m": rwy.get("width_m"),
                    # 沿跑道方向从物理入口量起；着陆入口 = 物理入口 + 内移
                    "displaced_threshold_m": rwy.get("displaced_threshold_m") or 0.0,
                    # §36：几何来源（scenery = 游戏内数据 / navdata = 现实库）
                    "runway_source": rwy.get("source") or "navdata",
                }
                score = diff + dist * 5
                if best is None or score < best["_score"]:
                    cand["_score"] = score
                    best = cand
        if best:
            best.pop("_score", None)
        return best

    # -- 高度校验 ---------------------------------------------------------
    def airway_limits(self, name: str) -> tuple[float, float] | None:
        key = name.upper()
        if key not in self._limits:
            row = self._con.execute(
                "select max(minimum_altitude), min(maximum_altitude) from airway where airway_name=?",
                (name,)).fetchone()
            lim = None
            if row and row[0] is not None and row[1] is not None and row[0] <= row[1]:
                lim = (float(row[0]), float(row[1]))
            self._limits[key] = lim
        return self._limits[key]

    def _waypoint_ident(self, waypoint_id: int) -> str | None:
        if waypoint_id not in self._wp_ident:
            row = self._con.execute(
                "select ident from waypoint where waypoint_id=?", (waypoint_id,)).fetchone()
            self._wp_ident[waypoint_id] = row[0] if row else None
        return self._wp_ident[waypoint_id]

    def segment_limits(self, name: str, from_ident: str, to_ident: str) -> list[tuple[float, float]]:
        key = (name.upper(), from_ident.upper(), to_ident.upper())
        if key in self._seg_limits:
            return self._seg_limits[key]
        if name.upper() not in self._name_rows:
            try:
                self._name_rows[name.upper()] = self._con.execute(
                    "select from_waypoint_id, to_waypoint_id, minimum_altitude, maximum_altitude "
                    "from airway where airway_name=?", (name,)).fetchall()
            except sqlite3.Error:
                self._name_rows[name.upper()] = []
        out = []
        for fid, tid, lo, hi in self._name_rows[name.upper()]:
            a, b = self._waypoint_ident(fid), self._waypoint_ident(tid)
            if a is None or b is None:
                continue
            if {a.upper(), b.upper()} == {from_ident.upper(), to_ident.upper()}:
                out.append((float(lo), float(hi)))
        self._seg_limits[key] = out
        return out

    def validate_segments(self, segments: Iterable[tuple[str, str, str]] | None, cruise_fl: int) -> dict:
        segs = list(segments or [])
        if not segs:
            return {"valid": None, "violations": [], "checked": 0, "unknown": 0}
        alt = cruise_fl * 100
        bad, checked, unknown = [], 0, 0
        for name, a, b in segs:
            if not name or name.upper() == "DCT":
                continue
            lims = self.segment_limits(name, a, b)
            if not lims:
                unknown += 1
                continue
            checked += 1
            if not any(lo <= alt <= hi for lo, hi in lims):
                bad.append({"airway": name, "from": a, "to": b,
                            "min_ft": min(lo for lo, _ in lims),
                            "max_ft": max(hi for _, hi in lims)})
        valid = None if checked == 0 else not bad
        return {"valid": valid, "violations": bad, "checked": checked, "unknown": unknown}

    def validate_altitude(self, airways: Iterable[str], cruise_fl: int) -> dict:
        alt = cruise_fl * 100
        bad, checked, unknown = [], 0, 0
        for name in dict.fromkeys(a for a in airways if a and a.upper() != "DCT"):
            lim = self.airway_limits(name)
            if lim is None:
                unknown += 1
                continue
            checked += 1
            if alt < lim[0] or alt > lim[1]:
                bad.append({"airway": name, "min_ft": lim[0], "max_ft": lim[1]})
        valid = None if checked == 0 else not bad
        return {"valid": valid, "violations": bad, "checked": checked, "unknown": unknown}

    # -- 覆盖 -------------------------------------------------------------
    @property
    def coverage(self) -> CoverageIndex:
        if self._coverage is None:
            self._coverage = CoverageIndex(self.path)
        return self._coverage

    def check_coverage(self, dep: str, arr: str, cruise_fl: int) -> dict:
        a, b = self.airport(dep), self.airport(arr)
        if not a or not b:
            return {"checked": False, "reason": "airport_not_in_navdata", "pass": None}
        gcd = haversine_nm(a["lat"], a["lon"], b["lat"], b["lon"])
        if gcd < MIN_CHECK_NM:
            return {"checked": False, "reason": "route_too_short", "gcd_nm": round(gcd, 1), "pass": None}
        alt = cruise_fl * 100
        dists = np.arange(COVERAGE_END_MARGIN_NM, gcd - COVERAGE_END_MARGIN_NM + 1e-6, COVERAGE_STEP_NM)
        uncovered = []
        for d in dists:
            lat, lon = intermediate(a["lat"], a["lon"], b["lat"], b["lon"], float(d / gcd))
            if not self.coverage.covered(lat, lon, alt):
                uncovered.append(float(d))
        gaps = []
        for d in uncovered:
            if gaps and d - gaps[-1][1] <= COVERAGE_STEP_NM + 1e-6:
                gaps[-1][1] = d
            else:
                gaps.append([d, d])
        gap_list = []
        for g in gaps:
            mid = (g[0] + g[1]) / 2.0
            clat, clon = intermediate(a["lat"], a["lon"], b["lat"], b["lon"], mid / gcd)
            gap_list.append({
                "from_nm": round(g[0], 0), "to_nm": round(g[1], 0),
                "length_nm": round(g[1] - g[0] + COVERAGE_STEP_NM, 0),
                "center_lat": round(clat, 4), "center_lon": round(clon, 4),
            })
        max_gap = max((g["length_nm"] for g in gap_list), default=0.0)
        gap_pct = 100.0 * len(uncovered) / max(1, len(dists))
        return {
            "checked": True,
            "gcd_nm": round(gcd, 1),
            "samples": len(dists),
            "uncovered_samples": len(uncovered),
            "max_gap_nm": max_gap,
            "gap_pct": round(gap_pct, 1),
            "gaps": gap_list,
            "pass": max_gap <= MAX_GAP_NM and gap_pct <= MAX_GAP_PCT,
        }

    # -- 状态 -------------------------------------------------------------
    def counts(self) -> dict:
        def one(sql: str) -> int:
            try:
                return int(self._con.execute(sql).fetchone()[0] or 0)
            except sqlite3.Error:
                return 0
        return {
            "airports": len(self.airports),
            "runways": self._runway_count(),
            "airways": one("select count(*) from airway"),
        }

    def _runway_count(self) -> int:
        """跑道端总数（懒加载后不能再数内存里的 dict，用 SQL 数一次并缓存）。"""
        if self._runway_count_cache is not None:
            return self._runway_count_cache
        sql = self._runway_query()
        count = 0
        if sql:
            try:
                count = int(self._con.execute(
                    "select count(*) from runway r join runway_end re "
                    "on re.runway_end_id in (r.primary_end_id, r.secondary_end_id) "
                    "join airport a on a.airport_id = r.airport_id where a.ident is not null"
                ).fetchone()[0] or 0)
            except sqlite3.Error:
                count = 0
        self._runway_count_cache = count
        return count


def _merge_stand_override(row: dict, data: dict) -> dict:
    """把一条手工机位覆盖叠到场景库/现实库的机位上（覆盖优先，非法值忽略）。"""
    merged = {**row, "source": "override"}
    try:
        merged["lat"] = float(data["lat"])
        merged["lon"] = float(data["lon"])
    except (KeyError, TypeError, ValueError):
        return {**row}
    try:
        if data.get("heading") is not None:
            merged["heading"] = float(data["heading"]) % 360.0
        if data.get("radius_m") is not None:
            merged["radius_m"] = round(float(data["radius_m"]), 1)
        if data.get("has_jetway") is not None:
            merged["has_jetway"] = bool(data["has_jetway"])
        if data.get("stand_type"):
            merged["type"] = str(data["stand_type"]).strip().upper()
    except (TypeError, ValueError):
        pass
    merged.setdefault("ident", str(data.get("ident") or "").upper())
    merged.setdefault("name", None)
    merged.setdefault("number", None)
    merged.setdefault("suffix", None)
    merged.setdefault("type", None)
    merged.setdefault("radius_m", None)
    merged.setdefault("has_jetway", None)
    merged.setdefault("note", data.get("note"))
    return merged


def reciprocal_name(name: str) -> str | None:
    name = (name or "").strip().upper()
    i = 0
    while i < len(name) and name[i].isdigit():
        i += 1
    if i == 0 or not name[:i].isdigit() or not (1 <= int(name[:i]) <= 36):
        return None
    suffix = name[i:]
    num = int(name[:i])
    recip = (num + 17) % 36 + 1
    recip_suffix = {"L": "R", "R": "L"}.get(suffix, suffix)
    return f"{recip:02d}{recip_suffix}"


def project_on_runway(runway: dict, lat: float, lon: float) -> tuple[float, float]:
    """返回 (沿跑道方向距入口的米数, 相对中心线横向偏差米，右偏为正)。"""
    m_per_deg_lat = 110540.0
    m_per_deg_lon = 111320.0
    dx = (lon - runway["lon"]) * m_per_deg_lon * math.cos(math.radians(runway["lat"]))
    dy = (lat - runway["lat"]) * m_per_deg_lat
    th = math.radians(float(runway["hdg"]))
    along = dy * math.cos(th) + dx * math.sin(th)
    lateral = dx * math.cos(th) - dy * math.sin(th)
    return along, lateral
