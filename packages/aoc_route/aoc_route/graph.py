"""Pre-train 航路图（network.pkl）薄封装。

可选依赖：没有 Pre-train 产物时 `available=False`，上层直接走 SimBrief。
按 07 §5 的 M1 要求，若图的边带 `min_fl/max_fl`，规划时按巡航高度过滤。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PRE_TRAIN = ROOT / "Pre-train"
DEFAULT_PKL = ROOT / "data" / "network.pkl"


class GraphProvider:
    def __init__(self, pre_train_dir: str | Path | None = None, pkl: str | Path | None = None):
        self.pre_train = Path(pre_train_dir) if pre_train_dir else DEFAULT_PRE_TRAIN
        self.pkl = Path(pkl) if pkl else (
            DEFAULT_PKL if DEFAULT_PKL.exists() else self.pre_train / "artifacts" / "network.pkl"
        )
        self._net = None
        self.error = ""
        self.load_ms: float | None = None

    @property
    def available(self) -> bool:
        return self.pkl.exists() and (self.pre_train / "src" / "network.py").exists()

    def load(self):
        if self._net is not None:
            return self._net
        if not self.available:
            self.error = f"network.pkl 或 Pre-train/src 不存在: {self.pkl}"
            return None
        t0 = time.perf_counter()
        if str(self.pre_train) not in sys.path:
            sys.path.insert(0, str(self.pre_train))
        try:
            from src.network import Network  # type: ignore
            self._net = Network.load(self.pkl)
        except Exception as exc:  # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"
            return None
        self.load_ms = round((time.perf_counter() - t0) * 1000, 1)
        return self._net

    def plan(self, dep: str, arr: str, cruise_fl: int = 350, n_variants: int = 1) -> list[dict]:
        net = self.load()
        if net is None:
            return []
        try:
            plans = net.plan(dep.upper(), arr.upper(), n_variants=n_variants, cruise_fl=cruise_fl)
        except TypeError:
            # 旧版 Network.plan 没有 cruise_fl 参数
            plans = net.plan(dep.upper(), arr.upper(), n_variants=n_variants)
        out = []
        for p in plans:
            tokens = p["tokens"]
            info, reason = net.resolve(tokens)
            segments = []
            if info is not None:
                path = info["path"]
                for i in range(len(path) - 1):
                    aw = net.edge_airway(path[i], path[i + 1])
                    if aw and aw != "DCT":
                        segments.append((aw, net.node_ident[path[i]], net.node_ident[path[i + 1]]))
            out.append({
                "tokens": tokens,
                "route": " ".join(tokens),
                "distance_nm": round(float(p["distance_nm"]), 1),
                "gcd_nm": round(float(p["gcd_nm"]), 1),
                "resolve_ok": info is not None,
                "resolve_error": reason or "",
                "airways": [a for a in (net.route_airways(tokens) or []) if a != "DCT"],
                "segments": segments,
                "sid": p.get("sid"),
                "star": p.get("star"),
            })
        return out
