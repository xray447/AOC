"""navdata 读取 + 高空航路覆盖索引（V-05 / V-06）。

覆盖判定按 docs/02-系统架构.md §3.3：
* 沿大圆每 50NM 取点，忽略首末 50NM；
* 点周围 100NM 内有任意高空航段（J/B，且巡航高度落在 [min,max] 内）即算覆盖；
* 连续未覆盖 >200NM，或未覆盖占比 >20%，判 FAIL；
* 航程 <200NM 不检查（返回 unchecked）。

索引直接建在 little_navmap_navigraph.sqlite 的 airway 表（自带 from/to 坐标），
不依赖 Pre-train 的图产物。
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import numpy as np

CELL_DEG = 2.0
DEFAULT_RADIUS_NM = 100.0
COVERAGE_STEP_NM = 50.0
COVERAGE_END_MARGIN_NM = 50.0
MIN_CHECK_NM = 200.0
MAX_GAP_NM = 200.0
MAX_GAP_PCT = 20.0


def _haversine_nm(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(h)))


def _intermediate(lat1, lon1, lat2, lon2, f):
    """大圆插值。"""
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
    """高空航段的空间网格索引。"""

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

    def _candidates(self, lat, lon):
        r_lat = DEFAULT_RADIUS_NM / 60.0
        r_lon = DEFAULT_RADIUS_NM / (60.0 * max(0.15, math.cos(math.radians(lat))))
        out = []
        for cy in range(int(math.floor((lat - r_lat) / CELL_DEG)),
                        int(math.floor((lat + r_lat) / CELL_DEG)) + 1):
            for cx in range(int(math.floor((lon - r_lon) / CELL_DEG)),
                            int(math.floor((lon + r_lon) / CELL_DEG)) + 1):
                out.extend(self.grid.get((cy, cx), ()))
        return np.unique(out) if out else np.zeros(0, dtype=np.int64)

    def covered(self, lat, lon, alt_ft) -> bool:
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
            raise FileNotFoundError(self.path)
        con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        self._con = con
        self.airports = {
            r["ident"].upper(): {
                "ident": r["ident"].upper(), "name": r["name"], "lat": r["laty"], "lon": r["lonx"],
                "elev_ft": r["altitude"], "transition_alt_ft": r["transition_altitude"],
                "longest_runway_ft": r["longest_runway_length"],
            }
            for r in con.execute(
                "select ident, name, laty, lonx, altitude, transition_altitude, longest_runway_length "
                "from airport where ident is not null")
        }
        self._runways: dict[str, list[dict]] = {}
        for row in con.execute(
            "select a.ident, re.name, re.heading, re.laty, re.lonx, re.altitude "
            "from runway r join runway_end re "
            "on re.runway_end_id in (r.primary_end_id, r.secondary_end_id) "
            "join airport a on a.airport_id = r.airport_id where a.ident is not null"
        ):
            self._runways.setdefault(row["ident"].upper(), []).append({
                "name": row["name"], "hdg": row["heading"],
                "lat": row["laty"], "lon": row["lonx"], "elev_ft": row["altitude"],
            })
        meta = con.execute("select * from metadata limit 1").fetchone()
        self.airac = meta[4] if meta and len(meta) > 4 else "unknown"
        self.navdata_version = meta[5] if meta and len(meta) > 5 else ""
        self._coverage: CoverageIndex | None = None
        self._limits: dict[str, tuple[float, float] | None] = {}
        self._wp_ident: dict[int, str | None] = {}
        self._seg_limits: dict[tuple[str, str, str], list[tuple[float, float]]] = {}
        self._name_rows: dict[str, list[tuple[int, int, float, float]]] = {}

    def close(self):
        try:
            self._con.close()
        except Exception:  # noqa: BLE001
            pass

    # -- 基础查询 ---------------------------------------------------------
    def airport(self, ident: str) -> dict | None:
        return self.airports.get(ident.upper())

    def runways(self, ident: str) -> list[dict]:
        return self._runways.get(ident.upper(), [])

    def airway_limits(self, name: str):
        """航路可用的高度区间（所有分段的并集外包）。"""
        key = name.upper()
        if key not in self._limits:
            row = self._con.execute(
                "select max(minimum_altitude), min(maximum_altitude) from airway where airway_name=?",
                (name,)).fetchone()
            lim = None
            if row and row[0] is not None and row[1] is not None and row[0] <= row[1]:
                # 库里存在 min>max 的脏区间（如 Y803），视为未知而不是伪造范围
                lim = (row[0], row[1])
            self._limits[key] = lim
        return self._limits[key]

    def _waypoint_ident(self, waypoint_id: int) -> str | None:
        if waypoint_id not in self._wp_ident:
            row = self._con.execute(
                "select ident from waypoint where waypoint_id=?", (waypoint_id,)).fetchone()
            self._wp_ident[waypoint_id] = row[0] if row else None
        return self._wp_ident[waypoint_id]

    def segment_limits(self, name: str, from_ident: str, to_ident: str) -> list[tuple[float, float]]:
        """按「航路名 + 两端点 ident」取该航段的高度限制（航路名全球重名，不能只按名字查）。"""
        key = (name.upper(), from_ident.upper(), to_ident.upper())
        if key in self._seg_limits:
            return self._seg_limits[key]
        if name.upper() not in self._name_rows:
            self._name_rows[name.upper()] = self._con.execute(
                "select from_waypoint_id, to_waypoint_id, minimum_altitude, maximum_altitude "
                "from airway where airway_name=?", (name,)).fetchall()
        out = []
        for fid, tid, lo, hi in self._name_rows[name.upper()]:
            a, b = self._waypoint_ident(fid), self._waypoint_ident(tid)
            if a is None or b is None:
                continue
            if {a.upper(), b.upper()} == {from_ident.upper(), to_ident.upper()}:
                out.append((lo, hi))
        self._seg_limits[key] = out
        return out

    def validate_segments(self, segments: list[tuple[str, str, str]] | None, cruise_fl: int) -> dict:
        """逐航段校验高度。segments = [(airway, from_ident, to_ident), ...]。"""
        if not segments:
            return {"valid": None, "violations": [], "checked": 0, "unknown": 0}
        alt = cruise_fl * 100
        bad, checked, unknown = [], 0, 0
        for name, a, b in segments:
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
        # 没有任何航段查到高度限制时，不给"通过"，避免空校验冒充有效
        valid = None if checked == 0 else not bad
        return {"valid": valid, "violations": bad, "checked": checked, "unknown": unknown}

    def validate_altitude(self, airways: list[str], cruise_fl: int) -> dict:
        """名字级粗校验，仅在没有航段信息时兜底。"""
        alt = cruise_fl * 100
        bad = []
        checked = unknown = 0
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
        gcd = _haversine_nm(a["lat"], a["lon"], b["lat"], b["lon"])
        if gcd < MIN_CHECK_NM:
            return {"checked": False, "reason": "route_too_short", "gcd_nm": round(gcd, 1), "pass": None}
        alt = cruise_fl * 100
        dists = np.arange(COVERAGE_END_MARGIN_NM, gcd - COVERAGE_END_MARGIN_NM + 1e-6, COVERAGE_STEP_NM)
        uncovered = []
        for d in dists:
            lat, lon = _intermediate(a["lat"], a["lon"], b["lat"], b["lon"], float(d / gcd))
            if not self.coverage.covered(lat, lon, alt):
                uncovered.append(float(d))
        gaps = []
        for d in uncovered:
            if gaps and d - gaps[-1][1] <= COVERAGE_STEP_NM + 1e-6:
                gaps[-1][1] = d
            else:
                gaps.append([d, d])
        gap_list = [{"from_nm": round(g[0], 0), "to_nm": round(g[1], 0),
                     "length_nm": round(g[1] - g[0] + COVERAGE_STEP_NM, 0)} for g in gaps]
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
