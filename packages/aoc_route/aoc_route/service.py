"""航路生成优先链（D-19 / D-23）：

0. navdata 检查         → NAVDATA_MISSING（直接给 SimBrief）
1. AIP 官方航路         → 命中即用（即使覆盖不足，也标 warning）
2. 直飞走廊覆盖检查     → 无高空航路：REQUIRES_SIMBRIEF，默认不调图
3. Pre-train 图航路     → 高度合法、绕行比在阈值内才用
4. simbrief_url 无条件生成（只要有合法 dep/arr）

不伪造航路：任何失败都保留 `simbrief_url` 和可读原因。
"""
from __future__ import annotations

import re
import time
import xml.sax.saxutils as saxutils
from pathlib import Path

from aoc_navdata import NavData, NavDataError, haversine_nm
from aoc_protocol.schemas import (
    CoverageGap,
    CoverageResult,
    CoverageState,
    ProcedureOption,
    RouteAttempt,
    RouteResult,
    RunwayOption,
    ValidateRouteResult,
)

from .aip import AipProvider
from .graph import GraphProvider
from .simbrief import build_url

ICAO_RE = re.compile(r"^[A-Z]{4}$")
AIRWAY_RE = re.compile(r"^[A-Z]{1,2}\d{1,3}[A-Z]?$")
ROUTE_TOKEN_RE = re.compile(r"^[A-Z0-9.]{2,12}$")


def max_detour_ratio(gcd_nm: float) -> float:
    """按航程分档，远程更严（07 §4-1）。"""
    if gcd_nm >= 2000:
        return 1.25
    if gcd_nm >= 1000:
        return 1.45
    return 1.6


class RouteService:
    def __init__(self, navdata_path: str | Path | None = None,
                 navdata: NavData | None = None,
                 aip_path: str | Path | None = None,
                 pre_train_dir: str | Path | None = None,
                 network_pkl: str | Path | None = None,
                 cache_dir: str | Path | None = None,
                 aip_source: str | None = None,
                 graph: GraphProvider | None = None,
                 aip: AipProvider | None = None):
        self._navdata_path = str(navdata_path) if navdata_path else None
        self._nav = navdata
        self._nav_tried = navdata is not None
        self.nav_error = ""
        self.nav_load_ms: float | None = None
        self.cache_dir = str(cache_dir) if cache_dir else None
        self.graph = graph or GraphProvider(pre_train_dir, network_pkl, cache_dir)
        self.aip = aip or AipProvider(aip_path, default_source=aip_source)
        self._cache: dict[tuple, RouteResult] = {}

    # -- navdata ---------------------------------------------------------
    @property
    def nav(self) -> NavData | None:
        if not self._nav_tried:
            self._nav_tried = True
            if not self._navdata_path:
                self.nav_error = "未配置 navdata"
                return None
            t0 = time.perf_counter()
            try:
                self._nav = NavData(self._navdata_path)
            except (NavDataError, Exception) as exc:  # noqa: BLE001
                self.nav_error = f"{type(exc).__name__}: {exc}"
            self.nav_load_ms = round((time.perf_counter() - t0) * 1000, 1)
        return self._nav

    def set_paths(self, navdata_path: str | None = None, aip_path: str | None = None,
                  network_pkl: str | None = None, pre_train_dir: str | None = None,
                  aip_source: str | None = None) -> None:
        if navdata_path != self._navdata_path:
            old = self._nav
            self._nav = None
            self._nav_tried = False
            self._navdata_path = navdata_path
            if old is not None:
                old.close()
        self.aip = AipProvider(aip_path, default_source=aip_source) if aip_path else AipProvider()
        if network_pkl or pre_train_dir:
            self.graph = GraphProvider(pre_train_dir, network_pkl, self.cache_dir)
        self._cache.clear()

    def ensure_graph(self) -> bool:
        """用当前 navdata 建图（命中缓存则直接切换）；失败只记录原因，不抛异常。"""
        nav = self.nav
        if nav is None:
            return False
        path = self._navdata_path or str(nav.path)
        return self.graph.ensure(path, nav.airac)

    def _cache_key(self, dep: str, arr: str, cruise_fl: int, aircraft: str | None) -> tuple:
        return (dep, arr, cruise_fl, aircraft, self.nav.airac if self.nav else None,
                self.aip.version, self.graph.pkl.stat().st_mtime_ns if self.graph.pkl.exists() else 0)

    # -- 公共入口 ---------------------------------------------------------
    def generate(self, dep: str, arr: str, cruise_fl: int = 350,
                 aircraft: str | None = None, force_graph: bool = False) -> RouteResult:
        dep, arr = (dep or "").strip().upper(), (arr or "").strip().upper()
        t0 = time.perf_counter()
        result = RouteResult(
            dep=dep, arr=arr, cruise_fl=cruise_fl,
            simbrief_url=build_url(dep, arr, aircraft),
            requires_simbrief=True,
        )
        if not ICAO_RE.match(dep) or not ICAO_RE.match(arr):
            raise ValueError("机场代码必须是 4 位 ICAO")
        if dep == arr:
            raise ValueError("起降机场不能相同")
        if not 0 < cruise_fl <= 450:
            raise ValueError("巡航高度必须在 FL010–FL450")

        key = self._cache_key(dep, arr, cruise_fl, aircraft)
        cached = self._cache.get(key)
        if cached is not None:
            return cached.model_copy(deep=True)

        nav = self.nav
        if nav is None:
            result.status = "NAVDATA_MISSING"
            result.route_source = "NONE"
            result.coverage = "NO_DATA"
            result.warnings = [
                "未提供或无法读取 navdata（Little Navmap / Navigraph SQLite），已跳过航路生成；"
                "请使用 SimBrief 生成航路，或在设置中导入 navdata",
            ]
            result.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            return result

        result.airac = nav.airac
        result.coverage_version = f"{nav.airac}.1"
        dep_info, arr_info = nav.airport(dep), nav.airport(arr)
        if dep_info is None or arr_info is None:
            missing = dep if dep_info is None else arr
            result.status = "NO_AIRPORT"
            result.warnings = [f"机场 {missing} 不在 navdata 中，无法生成航路；请使用 SimBrief"]
            result.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            return result

        gcd = haversine_nm(dep_info["lat"], dep_info["lon"], arr_info["lat"], arr_info["lon"])
        result.gcd_nm = round(gcd, 1)
        result.runway_options = self._runway_options(nav, dep, arr)

        # 1. AIP
        aip_result = self._try_aip(dep, arr, cruise_fl, result)
        if aip_result is not None:
            self._finish(aip_result, t0)
            self._remember(key, aip_result)
            return aip_result

        # 2. 覆盖检查
        coverage = nav.check_coverage(dep, arr, cruise_fl)
        result.coverage = self._coverage_state(coverage)
        result.coverage_gaps = self._gaps(coverage)
        if coverage.get("checked") and coverage.get("pass") is False:
            max_gap = coverage.get("max_gap_nm") or 0
            result.warnings.append(
                f"直飞走廊约 {max_gap:.0f} NM 无高空航路覆盖（共 {coverage.get('gap_pct')}% 航程），"
                "请使用 SimBrief 生成航路")
            if not force_graph:
                result.status = "REQUIRES_SIMBRIEF"
                result.route_source = "NONE"
                result.attempts.append(RouteAttempt(provider="COVERAGE", status="failed",
                                                    reason="coverage_fail", ms=0.0))
                self._finish(result, t0)
                self._remember(key, result)
                return result
            result.warnings.append("已启用 force_graph：跳过覆盖拦截，仍请自行核对航路")

        # 3. 图航路
        graph_result = self._try_graph(dep, arr, cruise_fl, gcd, result)
        if graph_result is not None:
            self._finish(graph_result, t0)
            self._remember(key, graph_result)
            return graph_result

        result.status = "REQUIRES_SIMBRIEF"
        result.route_source = "NONE"
        if not result.attempts:
            result.attempts.append(RouteAttempt(provider="GRAPH", status="failed",
                                                reason="graph_unavailable", ms=0.0))
        self._finish(result, t0)
        self._remember(key, result)
        return result

    def simbrief(self, dep: str, arr: str, cruise_fl: int = 350,
                 aircraft: str | None = None, route: str | None = None,
                 callsign: str | None = None, payload_kg: float | None = None,
                 registration: str | None = None) -> str:
        """cruise_fl 仅为兼容旧调用保留，链接里不再预填高度。"""
        return build_url((dep or "").strip().upper(), (arr or "").strip().upper(),
                         aircraft, route, callsign, payload_kg, registration)

    def coverage(self, dep: str, arr: str, cruise_fl: int = 350) -> CoverageResult:
        dep, arr = dep.upper().strip(), arr.upper().strip()
        out = CoverageResult()
        nav = self.nav
        if nav is None:
            out.warnings = ["未提供 navdata，无法做覆盖检查"]
            return out
        info = nav.check_coverage(dep, arr, cruise_fl)
        out.checked = bool(info.get("checked"))
        out.gcd_nm = info.get("gcd_nm")
        out.coverage = self._coverage_state(info)
        out.requires_simbrief = out.coverage in ("NO_HIGH_ALT", "OCEANIC", "NO_DATA")
        out.coverage_gaps = self._gaps(info)
        if info.get("checked") and not info.get("pass"):
            out.warnings = [f"直飞走廊存在 {info.get('max_gap_nm')} NM 高空航路缺口，请使用 SimBrief"]
        elif not info.get("checked"):
            out.warnings = [f"覆盖检查跳过：{info.get('reason', 'unknown')}"]
        return out

    def validate(self, tokens: list[str] | str, cruise_fl: int | None = None) -> ValidateRouteResult:
        toks = tokens.split() if isinstance(tokens, str) else list(tokens)
        out = ValidateRouteResult()
        if not toks:
            out.valid = False
            out.warnings = ["航路为空"]
            return out
        unknown = [t for t in toks if not ROUTE_TOKEN_RE.match(t.upper())]
        if unknown:
            out.valid = False
            out.warnings = [f"无法识别的 token: {', '.join(unknown[:5])}"]
            return out
        out.valid = True
        nav = self.nav
        if nav is None:
            out.warnings = ["未提供 navdata，未做高度校验"]
            return out
        segments = self.tokens_to_segments(toks)
        if cruise_fl:
            alt = nav.validate_segments(segments, cruise_fl)
            if alt.get("checked", 0) == 0:
                # 没有航段级高度数据时退化为航路名级校验（仍不伪造“通过”）
                airways = [t for t in toks if AIRWAY_RE.match(t.upper())]
                if airways:
                    alt = nav.validate_altitude(airways, cruise_fl)
            out.altitude_valid = alt["valid"]
            out.violations = alt["violations"]
            out.unknown = alt["unknown"]
            if alt["valid"] is None:
                out.warnings.append("航路高度未校验（找不到对应航段高度数据）")
            elif alt["valid"] is False:
                out.warnings.append("航路高度不覆盖请求巡航高度")
        return out

    # -- providers -------------------------------------------------------
    def _try_aip(self, dep: str, arr: str, cruise_fl: int, result: RouteResult) -> RouteResult | None:
        t0 = time.perf_counter()
        attempt = RouteAttempt(provider="AIP", status="failed")
        try:
            candidates = self.aip.lookup(dep, arr, cruise_fl)
        except Exception as exc:  # noqa: BLE001
            candidates = []
            attempt.reason = f"{type(exc).__name__}: {exc}"
        if not candidates:
            attempt.reason = attempt.reason or "no_match"
            attempt.ms = round((time.perf_counter() - t0) * 1000, 1)
            result.attempts.append(attempt)
            return None

        cand = candidates[0]
        tokens = cand["route"].split()
        if tokens[0].upper() != dep or tokens[-1].upper() != arr:
            attempt.reason = "route_endpoints_mismatch"
            attempt.ms = round((time.perf_counter() - t0) * 1000, 1)
            result.attempts.append(attempt)
            return None

        nav = self.nav
        assert nav is not None
        segments = self.tokens_to_segments(tokens, bounds={dep, arr})
        coverage = nav.check_coverage(dep, arr, cruise_fl)
        altitude = nav.validate_segments(segments, cruise_fl) if segments else {
            "valid": None, "violations": [], "checked": 0, "unknown": 0}
        warnings = list(result.warnings)
        if coverage.get("checked") and coverage.get("pass") is False:
            warnings.append(
                f"AIP 航路已命中，但直飞走廊有 {coverage.get('max_gap_nm')} NM 高空航路缺口；"
                "AIP 优先，请核对放行")
        if altitude["valid"] is False:
            warnings.append(f"AIP 航路高度不覆盖 FL{cruise_fl}")
        elif altitude["valid"] is None:
            warnings.append("AIP 航路高度未校验（缺少航段高度数据）")
        if "fixture" in (cand.get("source") or ""):
            warnings.append("AIP 数据为内置样例（fixture），不是真实 AIP，请以官方资料为准")

        sid_options, star_options = self._procedures(cand, tokens, dep, arr)
        attempt.status = "ok"
        attempt.ms = round((time.perf_counter() - t0) * 1000, 1)
        result.attempts.append(attempt)
        result.status = "OK"
        result.route_source = "AIP"
        result.coverage = "AIP"
        result.altitude_valid = altitude["valid"]
        result.requires_simbrief = False
        result.route = cand["route"]
        result.tokens = tokens
        result.tokens_full = tokens
        result.valid = True
        result.distance_nm = cand.get("distance_nm")
        result.sid_options = sid_options
        result.star_options = star_options
        result.aip_version = self.aip.version
        result.coverage_gaps = self._gaps(coverage)
        result.warnings = warnings
        result.simbrief_url = build_url(dep, arr, None, cand["route"])
        return result

    def _try_graph(self, dep: str, arr: str, cruise_fl: int, gcd: float,
                   result: RouteResult) -> RouteResult | None:
        t0 = time.perf_counter()
        attempt = RouteAttempt(provider="GRAPH", status="failed")
        if not self.graph.available:
            attempt.reason = "graph_unavailable"
            attempt.ms = round((time.perf_counter() - t0) * 1000, 1)
            result.attempts.append(attempt)
            return None
        try:
            plans = self.graph.plan(dep, arr, cruise_fl, 1)
        except Exception as exc:  # noqa: BLE001
            plans = []
            attempt.reason = f"{type(exc).__name__}: {exc}"
        if not plans:
            attempt.reason = attempt.reason or (self.graph.error or "no_plan")
            attempt.ms = round((time.perf_counter() - t0) * 1000, 1)
            result.attempts.append(attempt)
            return None

        nav = self.nav
        assert nav is not None
        ratio_limit = max_detour_ratio(gcd)
        for plan in plans:
            if not plan.get("resolve_ok"):
                attempt.reason = f"resolve_failed: {plan.get('resolve_error')}"
                continue
            dist = float(plan.get("distance_nm") or 0)
            ratio = dist / gcd if gcd > 0 else 1.0
            if ratio > ratio_limit:
                attempt.reason = f"detour_too_large: {ratio:.2f}x > {ratio_limit:.2f}x"
                continue
            segments = plan.get("segments") or self.tokens_to_segments(plan["tokens"], {dep, arr})
            altitude = nav.validate_segments(segments, cruise_fl)
            if altitude["valid"] is False:
                attempt.reason = "altitude_invalid"
                continue
            warnings = list(result.warnings)
            if altitude["valid"] is None:
                warnings.append("图航路高度未校验（边缺少 min/max FL），请核对")
            attempt.status = "ok"
            attempt.ms = round((time.perf_counter() - t0) * 1000, 1)
            result.attempts.append(attempt)
            result.status = "OK"
            result.route_source = "GRAPH"
            result.coverage = result.coverage if result.coverage != "NO_DATA" else "HIGH_ALT_AIRWAY"
            result.altitude_valid = altitude["valid"]
            result.requires_simbrief = False
            result.route = plan["route"]
            # tokens = 折叠写法（显示/SimBrief），tokens_full = 逐点写法（导出 .pln）
            result.tokens = plan.get("tokens") or plan["tokens_full"]
            result.tokens_full = plan.get("tokens_full") or plan["tokens"]
            result.distance_nm = plan.get("distance_nm")
            result.gcd_nm = plan.get("gcd_nm") or result.gcd_nm
            result.valid = True
            result.warnings = warnings
            sid = plan.get("sid")
            star = plan.get("star")
            if sid:
                result.sid_options = [ProcedureOption(name=sid, source="graph")]
            if star:
                result.star_options = [ProcedureOption(name=star, source="graph")]
            result.simbrief_url = build_url(dep, arr, None, plan["route"])
            return result
        attempt.ms = round((time.perf_counter() - t0) * 1000, 1)
        if attempt.reason.startswith("detour_too_large"):
            result.warnings.append(f"图航路绕行 {attempt.reason.split(': ')[-1]}，超过阈值；已转 SimBrief")
        elif attempt.reason == "altitude_invalid":
            result.warnings.append(f"图航路高度不覆盖 FL{cruise_fl}；已转 SimBrief")
        result.attempts.append(attempt)
        return None

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _finish(result: RouteResult, t0: float) -> None:
        result.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        if result.route_source != "NONE" and result.route:
            result.simbrief_url = build_url(result.dep, result.arr, None, result.route)
        elif not result.simbrief_url:
            result.simbrief_url = build_url(result.dep, result.arr)

    def _remember(self, key: tuple, result: RouteResult) -> None:
        if len(self._cache) > 512:
            self._cache.clear()
        self._cache[key] = result.model_copy(deep=True)

    @staticmethod
    def tokens_to_segments(tokens: list[str], bounds: set[str] | None = None) -> list[tuple[str, str, str]]:
        stop = {"DCT"} | {b.upper() for b in (bounds or set())}
        segs: list[tuple[str, str, str]] = []
        for i, tok in enumerate(tokens):
            if not AIRWAY_RE.match(tok):
                continue
            pts: list[str] = []
            j = i + 1
            while j < len(tokens) and not AIRWAY_RE.match(tokens[j]) and tokens[j].upper() not in stop:
                pts.append(tokens[j])
                j += 1
            # 航路串形如 "ZBAA J123 ZSSS"（航路前一点作为段起点）
            if i > 0 and not AIRWAY_RE.match(tokens[i - 1]) and tokens[i - 1].upper() not in stop:
                pts.insert(0, tokens[i - 1])
            segs.extend((tok, a, b) for a, b in zip(pts, pts[1:]))
        return segs

    @staticmethod
    def _coverage_state(info: dict) -> CoverageState:
        if not info.get("checked"):
            return "NO_DATA"
        return "HIGH_ALT_AIRWAY" if info.get("pass") else "NO_HIGH_ALT"

    @staticmethod
    def _gaps(info: dict) -> list[CoverageGap]:
        return [CoverageGap(
            start_nm=g.get("from_nm", 0), end_nm=g.get("to_nm", 0),
            center_lat=g.get("center_lat"), center_lon=g.get("center_lon"),
            length_nm=g.get("length_nm"),
        ) for g in info.get("gaps", [])]

    @staticmethod
    def _runway_options(nav: NavData, dep: str, arr: str) -> list[RunwayOption]:
        out: list[RunwayOption] = []
        for icao in (dep, arr):
            for rwy in nav.runways(icao)[:6]:
                out.append(RunwayOption(
                    airport=icao, ident=rwy.get("name") or "",
                    heading=rwy.get("hdg"), length_m=rwy.get("length_m"), ils=rwy.get("ils"),
                ))
        return out

    @staticmethod
    def _procedures(cand: dict, tokens: list[str], dep: str, arr: str
                    ) -> tuple[list[ProcedureOption], list[ProcedureOption]]:
        sid_options: list[ProcedureOption] = []
        star_options: list[ProcedureOption] = []
        if cand.get("sid"):
            sid_options.append(ProcedureOption(name=cand["sid"], runway=cand.get("runway"),
                                               source=cand.get("source") or "aip"))
        else:
            for tok in tokens[1:3]:
                if "." in tok:
                    sid_options.append(ProcedureOption(name=tok.split(".")[0],
                                                       source=cand.get("source") or "aip"))
                    break
        if cand.get("star"):
            star_options.append(ProcedureOption(name=cand["star"], runway=cand.get("runway"),
                                                source=cand.get("source") or "aip"))
        return sid_options, star_options


# --------------------------------------------------------------------------
# MSFS .pln 导出
# --------------------------------------------------------------------------
def _lla(lat: float, lon: float, alt_ft: float | None) -> str:
    def dm(v: float, is_lat: bool) -> str:
        hemi = ("N" if v >= 0 else "S") if is_lat else ("E" if v >= 0 else "W")
        v = abs(v)
        deg = int(v)
        minutes = (v - deg) * 60
        return f"{hemi}{deg}\u00b0 {minutes:.2f}'"
    alt = int(alt_ft or 0)
    return f'{dm(lat, True)},{dm(lon, False)},{"+" if alt >= 0 else "-"}{abs(alt):06d}'


def build_pln(result: RouteResult, nav: NavData | None) -> str:
    dep, arr = result.dep, result.arr
    dep_info = nav.airport(dep) if nav else None
    arr_info = nav.airport(arr) if nav else None
    if dep_info is None or arr_info is None:
        raise ValueError("导出 .pln 需要 navdata 中的机场坐标")
    # 导出用逐点写法，保证模拟器里每个航路点都在航路上（折叠写法会少中间点）
    tokens = [t for t in (result.tokens_full or result.tokens or []) if t.upper() not in ("DCT",)]
    coords = nav.waypoint_coords(tokens) if nav else {}
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<SimBase.Document Type="AceXML" version="1,0">',
        "  <Descr>AOC flight plan</Descr>",
        "  <FlightPlan.FlightPlan>",
        f"    <Title>{saxutils.escape(dep)} to {saxutils.escape(arr)}</Title>",
        "    <FPType>IFR</FPType>",
        "    <RouteType>HighAlt</RouteType>",
        f"    <CruisingAlt>{int(result.cruise_fl) * 100}</CruisingAlt>",
        f"    <DepartureID>{dep}</DepartureID>",
        f"    <DepartureLLA>{_lla(dep_info['lat'], dep_info['lon'], dep_info['elev_ft'])}</DepartureLLA>",
        f"    <DestinationID>{arr}</DestinationID>",
        f"    <DestinationLLA>{_lla(arr_info['lat'], arr_info['lon'], arr_info['elev_ft'])}</DestinationLLA>",
    ]
    waypoints: list[tuple[str, float, float]] = [(dep, dep_info["lat"], dep_info["lon"])]
    for tok in tokens:
        if tok in (dep, arr):
            continue
        if tok in coords:
            waypoints.append((tok, coords[tok][0], coords[tok][1]))
    waypoints.append((arr, arr_info["lat"], arr_info["lon"]))
    for ident, lat, lon in waypoints:
        kind = "Airport" if ident in (dep, arr) else "Intersection"
        parts.append(f'    <ATCWaypoint id="{saxutils.escape(ident)}">')
        parts.append(f"      <ATCWaypointType>{kind}</ATCWaypointType>")
        parts.append(f"      <WorldPosition>{_lla(lat, lon, 0)}</WorldPosition>")
        parts.append("    </ATCWaypoint>")
    parts += ["  </FlightPlan.FlightPlan>", "</SimBase.Document>", ""]
    return "\n".join(parts)
