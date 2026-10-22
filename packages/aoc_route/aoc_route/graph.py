"""航路图（network.pkl）的加载 / 建图 / 求解封装。

建图与 Dijkstra 求解的源码**内置在 `aoc_route.net`**（只依赖 numpy + scipy），随产品
一起打包，因此 CI 与安装包不再需要仓库外的 `Pre-train/src`。图数据（pkl）仍不进仓库：

* **本地建图**：用用户在设置里选的 navdata（Little Navmap / Navigraph SQLite）现场建图，
  缓存到 `cache_dir/network-<airac>-<指纹>.pkl`（全球口径约 15 s）；
* **现成产物**：`data/network.pkl`（可选，随包发布时用）。

`pre_train_dir` / `AOC_PRETRAIN` 仍可指向外部 Pre-train 工程做算法对照（可选）；
不配置时一律用内置实现，避免开发机与 CI 各走一套代码。
"""
from __future__ import annotations

import hashlib
import os
import sys
import threading
import time
from pathlib import Path


def _resolve_root() -> Path:
    """仓库布局 / PyInstaller onedir 都能定位 `data`（D-30）。"""
    env = os.environ.get("AOC_ROOT")
    if env and Path(env).is_dir():
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", str(Path(sys.executable).parent)))
    return Path(__file__).resolve().parents[3]


ROOT = _resolve_root()
DEFAULT_PKL = ROOT / "data" / "network.pkl"


def find_pre_train_dir() -> Path | None:
    """外部 Pre-train 工程（可选），只认环境变量 `AOC_PRETRAIN`。

    仓库根的 `Pre-train/` 不再自动生效：内置 `aoc_route.net` 就是它的运行时副本，
    两套同时存在只会让开发机与 CI 的行为分叉。要对照算法就显式给环境变量。
    """
    env = os.environ.get("AOC_PRETRAIN")
    if env and (Path(env) / "src" / "network.py").exists():
        return Path(env)
    return None


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
        if self.pre_train is not None and not (self.pre_train / "src" / "network.py").exists():
            self.pre_train = None                      # 没有 src/network.py 就不是 Pre-train
        self.pkl = Path(pkl) if pkl else (
            DEFAULT_PKL if DEFAULT_PKL.exists() else self._external_pkl()
        )
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._net = None
        self._lock = threading.Lock()
        self.error = ""
        self.load_ms: float | None = None
        self.built_dir: Path | None = None

    def _external_pkl(self) -> Path:
        if self.pre_train is not None:
            return self.pre_train / "artifacts" / "network.pkl"
        return DEFAULT_PKL

    @property
    def network_source(self) -> str:
        """建图 / 求解源码的位置（排障用）：外部 Pre-train 或内置包。"""
        if self.pre_train is not None:
            return str(self.pre_train / "src" / "network.py")
        from .net import network

        return str(Path(network.__file__))

    @property
    def available(self) -> bool:
        return self.pkl.exists()

    def _network_class(self):
        """优先外部 Pre-train（显式配置时），否则用内置的运行时副本。"""
        if self.pre_train is not None:
            if str(self.pre_train) not in sys.path:
                sys.path.insert(0, str(self.pre_train))
            from src.network import Network  # type: ignore

            return Network
        from .net.network import Network

        return Network

    def load(self):
        if self._net is not None:
            return self._net
        if not self.pkl.exists():
            self.error = f"航路图不存在: {self.pkl}"
            return None
        t0 = time.perf_counter()
        try:
            self._net = self._network_class().load(self.pkl)
        except Exception as exc:  # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"
            return None
        self.load_ms = round((time.perf_counter() - t0) * 1000, 1)
        return self._net

    # -- 本地建图 ---------------------------------------------------------
    def ensure(self, navdata_path: str | Path | None, airac: str | None = None,
               verbose: bool = False) -> bool:
        """确保有一张用 *当前* navdata 建的图；必要时现场建图并落盘缓存。

        命中缓存只做一次文件存在判断 + 反序列化（毫秒级），可以放心在后台线程里反复调用。
        缓存读不出来（旧版本 pkl 的类路径不同、文件损坏）时丢弃重建，不做静默降级。
        """
        if not navdata_path:
            self.error = "未配置 navdata，无法建图"
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
                if self.load() is not None:
                    self.error = ""
                    return True
                target.unlink(missing_ok=True)
                self._net = None
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
        return self._network_class().build(verbose=verbose, db_path=str(navdata_path))

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
                # info["path"] 是**矩阵下标**（0/1 被虚拟源汇点占用），转 ident 要减偏移
                from .net.network import NODE_OFFSET

                path = info["path"]
                for i in range(len(path) - 1):
                    aw = net.edge_airway(path[i], path[i + 1])
                    if aw and aw != "DCT":
                        segments.append((
                            aw,
                            net.node_ident[path[i] - NODE_OFFSET],
                            net.node_ident[path[i + 1] - NODE_OFFSET],
                        ))
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
