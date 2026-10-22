"""navdata 读取、机场/跑道查询与高空航路覆盖索引。

兼容 Little Navmap / Navigraph SQLite 的常见表结构；对可选列做存在性检查，
因此不同版本（或测试用最小 fixture）都不会因为缺列直接崩掉。
"""
from __future__ import annotations

import math
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


class NavDataError(RuntimeError):
    pass


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
    def __init__(self, path: str | Path):
        self.path = Path(path)
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
        self._prime_runway_units()
        self.airac, self.navdata_version = self._load_meta()
        self._coverage: CoverageIndex | None = None
        self._limits: dict[str, tuple[float, float] | None] = {}
        self._wp_ident: dict[int, str | None] = {}
        self._seg_limits: dict[tuple[str, str, str], list[tuple[float, float]]] = {}
        self._name_rows: dict[str, list[tuple[int, int, float, float]]] = {}
        self._lat_arr = np.array([a["lat"] for a in self.airports.values()], dtype=float)
        self._lon_arr = np.array([a["lon"] for a in self.airports.values()], dtype=float)
        self._ident_arr = list(self.airports.keys())

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
        optional = [c for c in (
            "name", "iata", "city", "country", "iso_country", "longest_runway_length",
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
        self._runway_sql = (
            "select a.ident as airport, re.name as name, re.heading as heading, re.laty as lat, "
            f"re.lonx as lon, re.altitude as elev, {length_expr} as length, {ils_expr} as ils, "
            f"{offset_expr} as offset_threshold "
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
                        "ils": bool(row["ils"]) if row["ils"] is not None else None,
                    })
                # 跑道长度：优先 runway.length，否则由反向跑道端反推；内移入口按同一单位口径换算
                for end in ends:
                    end["length_m"] = self._runway_length_m(end, ends)
                    end["displaced_threshold_m"] = self._displaced_threshold_m(end, ends)
            self._runways[key] = ends
            derived = max((e["length_m"] for e in ends if e.get("length_m")), default=None)
            info = self.airports.get(key)
            if info is not None and derived:
                info["longest_runway_m"] = round(derived, 1)
                info["longest_runway_ft"] = round(derived * FT_PER_M, 1)
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
        try:
            self._con.close()
        except Exception:  # noqa: BLE001
            pass

    # -- 基础查询 ---------------------------------------------------------
    def airport(self, ident: str | None) -> dict | None:
        return self.airports.get((ident or "").upper())

    def runways(self, ident: str | None) -> list[dict]:
        return self._load_runways_for((ident or "").upper())

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
                    # 沿跑道方向从物理入口量起；着陆入口 = 物理入口 + 内移
                    "displaced_threshold_m": rwy.get("displaced_threshold_m") or 0.0,
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
