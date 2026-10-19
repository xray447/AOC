"""航路生成优先链：AIP → GRAPH → SIMBRIEF（V-05 / V-06）。

设计目标不是"一定能出航路"，而是"任何一步失败都能说清为什么、下一步是什么"。
返回结构对齐 docs/02-系统架构.md §9.4 的 route 对象，便于后续搬进 aoc_core。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from aip import AipProvider
from graph import GraphProvider
from navdata import NavData
from simbrief import build_url

ICAO_RE = re.compile(r"^[A-Z]{4}$")
# 航路命名（Y803 / W40 / A593 / UN741 / Q41 …）；SID/STAR 形如 ELKU2G、VAMOS4.TATEY 不匹配
AIRWAY_RE = re.compile(r"^[A-Z]{1,2}\d{1,3}[A-Z]?$")
# 航路长度 / 大圆距离上限：超过说明图求解绕行，宁可交给 SimBrief
MAX_DETOUR_RATIO = 1.6
DEFAULT_NAVDATA = Path(__file__).resolve().parents[2] / "Pre-train" / "dataset" / "little_navmap_navigraph.sqlite"


class RouteService:
    def __init__(self, navdata_path: str | Path | None = None,
                 pre_train_dir: str | Path | None = None,
                 aip_path: str | Path | None = None,
                 enable_graph: bool = True):
        # 传空串 = 显式关闭 navdata（V-05 的降级用例）
        self._navdata_arg = DEFAULT_NAVDATA if navdata_path is None else navdata_path
        self.pre_train_dir = pre_train_dir
        self.enable_graph = enable_graph
        self.graph = GraphProvider(pre_train_dir)
        self.aip = AipProvider(aip_path)
        self._nav: NavData | None = None
        self._nav_tried = False
        self.nav_error = ""
        self.nav_load_ms = None

    # -- navdata ---------------------------------------------------------
    @property
    def nav(self) -> NavData | None:
        if not self._nav_tried:
            self._nav_tried = True
            if self._navdata_arg:
                t0 = time.perf_counter()
                try:
                    self._nav = NavData(self._navdata_arg)
                except Exception as exc:  # noqa: BLE001
                    self.nav_error = f"{type(exc).__name__}: {exc}"
                self.nav_load_ms = round((time.perf_counter() - t0) * 1000, 1)
        return self._nav

    @staticmethod
    def _segments_from_tokens(tokens: list[str], bounds: set[str] | None = None
                              ) -> list[tuple[str, str, str]]:
        """从航路串还原 (航路, 起点, 终点) 序列；不依赖 network.pkl 的边命名。"""
        stop = {"DCT"} | {b.upper() for b in (bounds or set())}
        segs: list[tuple[str, str, str]] = []
        for i, tok in enumerate(tokens):
            if not AIRWAY_RE.match(tok):
                continue
            pts: list[str] = []
            j = i + 1
            while (j < len(tokens) and not AIRWAY_RE.match(tokens[j])
                   and tokens[j].upper() not in stop):
                pts.append(tokens[j])
                j += 1
            segs.extend((tok, a, b) for a, b in zip(pts, pts[1:]))
        return segs

    def _eligible_airways(self, tokens: list[str], graph_airways: list[str] | None) -> list[str]:
        if graph_airways:
            return graph_airways
        nav = self.nav
        if nav is None:
            return []
        return [t for t in tokens if t.upper() != "DCT" and nav.airway_limits(t) is not None]

    # -- checks ----------------------------------------------------------
    def _checks(self, dep: str, arr: str, cruise_fl: int, tokens: list[str],
                graph_airways: list[str] | None,
                segments: list[tuple[str, str, str]] | None = None) -> tuple[dict, list[str]]:
        nav = self.nav
        warnings = []
        if nav is None:
            return ({
                "navdata_checked": False, "coverage": {"checked": False, "reason": "navdata_disabled"},
                "altitude": {"valid": None, "violations": []},
            }, ["navdata_unavailable"])
        airways = self._eligible_airways(tokens, graph_airways)
        coverage = nav.check_coverage(dep, arr, cruise_fl)
        segs = self._segments_from_tokens(tokens, {dep, arr}) or list(segments or [])
        if segs:
            altitude = nav.validate_segments(segs, cruise_fl)
        else:
            altitude = nav.validate_altitude(airways, cruise_fl) if airways else {"valid": None, "violations": []}
        if not coverage.get("checked"):
            warnings.append(f"coverage_{coverage.get('reason')}")
        elif not coverage["pass"]:
            warnings.append("coverage_fail")
        if altitude["valid"] is False:
            warnings.append("altitude_invalid")
        elif altitude["valid"] is None and altitude.get("unknown"):
            warnings.append("altitude_unverified")
        return ({"navdata_checked": True, "coverage": coverage, "altitude": altitude}, warnings)

    @staticmethod
    def _base(dep, arr, cruise_fl):
        return {
            "dep": dep, "arr": arr, "cruise_fl": cruise_fl,
            "status": "failed", "provider": None, "route": None, "tokens": [],
            "distance_nm": None, "gcd_nm": None, "confidence": None,
            "requires_online": False, "external_url": None,
            "navdata_checked": False, "airac": None,
            "warnings": [], "attempts": [], "elapsed_ms": 0.0,
        }

    # -- 主入口 ----------------------------------------------------------
    def generate(self, dep: str, arr: str, cruise_fl: int = 350,
                 force: str | None = None, n_variants: int = 1) -> dict:
        dep, arr = dep.upper().strip(), arr.upper().strip()
        t0 = time.perf_counter()
        result = self._base(dep, arr, cruise_fl)
        if self.nav:
            result["airac"] = self.nav.airac

        error = None
        if not ICAO_RE.match(dep) or not ICAO_RE.match(arr):
            error = "机场代码必须是 4 位 ICAO"
        elif dep == arr:
            error = "起降机场相同"
        elif not 0 < cruise_fl <= 450:
            error = "巡航高度不合法"
        if error:
            result["warnings"].append(f"input_invalid: {error}")
            result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            return result

        order = ["aip", "graph"] if force is None else [force]
        for name in order:
            if name == "aip":
                r = self._try_aip(dep, arr, cruise_fl, result)
            elif name == "graph":
                r = self._try_graph(dep, arr, cruise_fl, n_variants, result)
            elif name == "simbrief":
                r = self._try_simbrief(dep, arr, cruise_fl, result)
            else:
                continue
            if r is not None:
                result.update(r)
                # D-20：生成成功也要带 SimBrief 链接，避免前端分支漏判
                result["external_url"] = result["external_url"] or build_url(dep, arr, cruise_fl)
                result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                return result

        self._try_simbrief(dep, arr, cruise_fl, result)
        if result["status"] != "deferred":
            result["status"] = "failed"
        result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return result

    # -- providers -------------------------------------------------------
    def _try_aip(self, dep, arr, fl, result):
        t = time.perf_counter()
        attempt = {"provider": "AIP", "status": "failed", "reason": "", "ms": 0.0}
        try:
            candidates = self.aip.lookup(dep, arr, fl)
        except Exception as exc:  # noqa: BLE001
            candidates = []
            attempt["reason"] = f"{type(exc).__name__}: {exc}"
        if not candidates:
            attempt["reason"] = attempt["reason"] or "no_match"
            attempt["ms"] = round((time.perf_counter() - t) * 1000, 1)
            result["attempts"].append(attempt)
            return None

        for cand in candidates:
            tokens = cand["route"].split()
            if tokens[0].upper() != dep or tokens[-1].upper() != arr:
                attempt["reason"] = "route_endpoints_mismatch"
                continue
            resolved, resolve_err, graph_airways, segments = self._resolve(tokens)
            if resolved is False:
                attempt["reason"] = f"resolve_failed: {resolve_err}"
                continue
            checks, warns = self._checks(dep, arr, fl, tokens, graph_airways, segments)
            if checks.get("coverage", {}).get("pass") is False:
                attempt["reason"] = "coverage_fail"
                continue
            if checks["altitude"]["valid"] is False:
                attempt["reason"] = "altitude_invalid"
                continue
            attempt.update({"status": "ok", "reason": "",
                            "ms": round((time.perf_counter() - t) * 1000, 1)})
            result["attempts"].append(attempt)
            confidence = "high" if resolved and checks["navdata_checked"] and \
                checks["coverage"].get("pass") is not False else "medium"
            return {
                "status": "ok", "provider": "AIP",
                "route": cand["route"], "tokens": tokens,
                "confidence": confidence,
                "navdata_checked": checks["navdata_checked"],
                "source": f"aip:{cand['source']}",
                "warnings": result["warnings"] + warns,
                "coverage": checks["coverage"], "altitude": checks["altitude"],
                "gcd_nm": checks["coverage"].get("gcd_nm"),
            }
        attempt["ms"] = round((time.perf_counter() - t) * 1000, 1)
        result["attempts"].append(attempt)
        return None

    def _resolve(self, tokens):
        if not self.enable_graph or not self.graph.available:
            return None, "graph_unavailable", None, None
        net = self.graph.load()
        if net is None:
            return None, self.graph.error, None, None
        info, reason = net.resolve(tokens)
        if info is None:
            return False, reason or "unresolved", None, None
        path = info["path"]
        segments = []
        for i in range(len(path) - 1):
            aw = net.edge_airway(path[i], path[i + 1])
            if aw and aw != "DCT":
                segments.append((aw, net.node_ident[path[i]], net.node_ident[path[i + 1]]))
        return True, "", [a for a in (net.route_airways(tokens) or []) if a != "DCT"], segments

    def _try_graph(self, dep, arr, fl, n_variants, result):
        t = time.perf_counter()
        attempt = {"provider": "GRAPH", "status": "failed", "reason": "", "ms": 0.0}
        if not self.enable_graph or not self.graph.available:
            attempt["reason"] = "graph_unavailable"
            attempt["ms"] = round((time.perf_counter() - t) * 1000, 1)
            result["attempts"].append(attempt)
            return None
        plans = self.graph.plan(dep, arr, n_variants)
        if not plans:
            attempt["reason"] = self.graph.error or "no_plan"
            attempt["ms"] = round((time.perf_counter() - t) * 1000, 1)
            result["attempts"].append(attempt)
            return None

        for plan in plans:
            if not plan["resolve_ok"]:
                attempt["reason"] = f"resolve_failed: {plan['resolve_error']}"
                continue
            gcd = plan["gcd_nm"] or 0.0
            dist = plan["distance_nm"] or 0.0
            ratio = dist / gcd if gcd > 0 else 1.0
            if ratio > MAX_DETOUR_RATIO:
                attempt["reason"] = f"detour_too_large: {ratio:.2f}x"
                continue
            checks, warns = self._checks(dep, arr, fl, plan["tokens"], plan["airways"], plan["segments"])
            if checks.get("coverage", {}).get("pass") is False:
                attempt["reason"] = "coverage_fail"
                continue
            if checks["altitude"]["valid"] is False:
                attempt["reason"] = "altitude_invalid"
                continue
            attempt.update({"status": "ok", "reason": "",
                            "ms": round((time.perf_counter() - t) * 1000, 1)})
            result["attempts"].append(attempt)
            confidence = "high" if checks["navdata_checked"] else "medium"
            return {
                "status": "ok", "provider": "GRAPH",
                "route": plan["route"], "tokens": plan["tokens"],
                "distance_nm": plan["distance_nm"], "gcd_nm": plan["gcd_nm"],
                "confidence": confidence,
                "navdata_checked": checks["navdata_checked"],
                "source": "network.pkl",
                "warnings": result["warnings"] + warns,
                "coverage": checks["coverage"], "altitude": checks["altitude"],
            }
        attempt["ms"] = round((time.perf_counter() - t) * 1000, 1)
        result["attempts"].append(attempt)
        return None

    def _try_simbrief(self, dep, arr, fl, result):
        t = time.perf_counter()
        result.update({
            "status": "deferred", "provider": "SIMBRIEF", "route": None, "tokens": [],
            "confidence": "low", "requires_online": True,
            "external_url": build_url(dep, arr, fl),
            "warnings": result["warnings"] + ["requires_online", "no_offline_candidate"],
        })
        result["attempts"].append({
            "provider": "SIMBRIEF", "status": "deferred",
            "reason": "外部在线源，不在本地编造航路",
            "ms": round((time.perf_counter() - t) * 1000, 1),
        })
        return result
