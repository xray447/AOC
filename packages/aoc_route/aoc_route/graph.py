"""Pre-train 航路图（network.pkl）薄封装。

两种来源：

* **现成产物**：`data/network.pkl` 或 `Pre-train/artifacts/network.pkl`，直接加载；
* **本地建图**：用用户在设置里选的 navdata（Little Navmap / Navigraph SQLite）
  现场建图并缓存到 `cache_dir/network-<airac>-<指纹>.pkl`。建图只读导航库的
  `waypoint / airway / airport / approach` 四张表，不需要航班轨迹数据（全球口径约 15 s）。

依赖：`network.py` 的数学生态是 numpy + scipy；缺失时 `available=False`，上层走 SimBrief。
"""
from __future__ import annotations

import hashlib
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PRE_TRAIN = ROOT / "Pre-train"
DEFAULT_PKL = ROOT / "data" / "network.pkl"


def find_pre_train_dir() -> Path:
    """定位 `Pre-train`（含 `src/network.py`）。

    优先环境变量 `AOC_PRETRAIN`，其次仓库根目录，最后仓库上一级 —— 这样
    Tauri 打包后（resources 里带 `Pre-train/src`）也能找到，不再依赖 __file__ 的固定层级。
    """
    env = os.environ.get("AOC_PRETRAIN")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    candidates += [DEFAULT_PRE_TRAIN, ROOT.parent / "Pre-train"]
    for candidate in candidates:
        if (candidate / "src" / "network.py").exists():
            return candidate
    return Path(env) if env else DEFAULT_PRE_TRAIN


def cache_tag(navdata_path: str | Path, airac: str | None) -> str:
    """缓存文件名里的指纹：AIRAC + 库路径/时间/大小，任一变化就重建。"""
    path = Path(navdata_path)
    try:
        stat = path.stat()
        fingerprint = f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
    except OSError:
        fingerprint = str(navdata_path)
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:8]
    return f"{airac or 'unknown'}-{digest}"


class GraphProvider:
    def __init__(self, pre_train_dir: str | Path | None = None,
                 pkl: str | Path | None = None,
                 cache_dir: str | Path | None = None):
        self.pre_train = Path(pre_train_dir) if pre_train_dir else find_pre_train_dir()
        self.pkl = Path(pkl) if pkl else (
            DEFAULT_PKL if DEFAULT_PKL.exists() else self.pre_train / "artifacts" / "network.pkl"
        )
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._net = None
        self._lock = threading.Lock()
        self.error = ""
        self.load_ms: float | None = None
        self.built_dir: Path | None = None

    @property
    def network_py(self) -> Path:
        return self.pre_train / "src" / "network.py"

    @property
    def available(self) -> bool:
        return self.pkl.exists() and self.network_py.exists()

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

    # -- 本地建图 ---------------------------------------------------------
    def ensure(self, navdata_path: str | Path | None, airac: str | None = None,
               verbose: bool = False) -> bool:
        """确保有一张用 *当前* navdata 建的图；必要时现场建图并落盘缓存。

        命中缓存只做一次文件存在判断（毫秒级），可以放心在后台线程里反复调用。
        """
        if not navdata_path:
            self.error = "未配置 navdata，无法建图"
            return False
        if not self.network_py.exists():
            self.error = f"建图脚本不存在: {self.network_py}"
            return False
        if self.cache_dir is None:
            self.error = "未配置建图缓存目录"
            return False
        target = self.cache_dir / f"network-{cache_tag(navdata_path, airac)}.pkl"
        with self._lock:
            if target.exists():
                if self.pkl != target:
                    self.pkl = target
                    self._net = None
                self.error = ""
                return True
            t0 = time.perf_counter()
            try:
                net = self._build(navdata_path, verbose)
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + ".tmp")
                net.save(tmp)
                os.replace(tmp, target)
            except Exception as exc:  # noqa: BLE001
                self.error = f"建图失败 {type(exc).__name__}: {exc}"
                return False
            self.pkl = target
            self._net = net
            self.built_dir = target.parent
            self.load_ms = round((time.perf_counter() - t0) * 1000, 1)
            self.error = ""
            return True

    def _build(self, navdata_path: str | Path, verbose: bool = False):
        if str(self.pre_train) not in sys.path:
            sys.path.insert(0, str(self.pre_train))
        from src.network import Network  # type: ignore

        return Network.build(verbose=verbose, db_path=str(navdata_path))

    # -- 求解 -------------------------------------------------------------
    def plan(self, dep: str, arr: str, cruise_fl: int = 350, n_variants: int = 1) -> list[dict]:
        """对齐 Pre-train 的老师口径（`src.infer.graph_route`）：

        * 多要几条候选再取最短（`n_variants=1` 偶尔会漏掉更短的可飞航路，见 README §4⑨）；
        * `tokens` 是**折叠写法**（同一条航路上只写离开点），`tokens_full` 是逐点写法；
        * 候选按里程升序，调用方取第一条通过校验的即可。
        """
        net = self.load()
        if net is None:
            return []
        want = max(3, int(n_variants or 1))
        try:
            plans = net.plan(dep.upper(), arr.upper(), n_variants=want, cruise_fl=cruise_fl)
        except TypeError:
            # 旧版 Network.plan 没有 cruise_fl 参数
            plans = net.plan(dep.upper(), arr.upper(), n_variants=want)
        out = []
        for p in plans:
            full = list(p["tokens"])
            info, reason = net.resolve(full)
            folded = net.fold_tokens(full) if info is not None else None
            tokens = folded or full
            segments = []
            if info is not None:
                path = info["path"]
                for i in range(len(path) - 1):
                    aw = net.edge_airway(path[i], path[i + 1])
                    if aw and aw != "DCT":
                        segments.append((aw, net.node_ident[path[i]], net.node_ident[path[i + 1]]))
            out.append({
                "tokens": tokens,
                "tokens_full": full,
                "route": " ".join(tokens),
                "distance_nm": round(float(p["distance_nm"]), 1),
                "gcd_nm": round(float(p["gcd_nm"]), 1),
                "resolve_ok": info is not None,
                "resolve_error": reason or "",
                "airways": [a for a in (net.route_airways(full) or []) if a != "DCT"],
                "segments": segments,
                "sid": p.get("sid"),
                "star": p.get("star"),
            })
        out.sort(key=lambda r: r["distance_nm"])
        return out
