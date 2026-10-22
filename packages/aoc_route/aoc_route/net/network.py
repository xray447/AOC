"""航路网络：建图 + 求解（老师）+ 校验。

本文件是 ``Pre-train/src/network.py`` 的运行时副本（随产品打包），只把包路径从
``src.*`` 改成 ``aoc_route.net.*``；算法、数据格式与 Pre-train 保持一致，改动需双向同步。

结构
----
* 节点 = 导航库里 ``airway`` 航段引用到的航路点（约 4.7 万个，含被复制成航路点的 VOR/NDB）；
* 边   = 航段。带方向（``direction`` N=双向 / F=正向 / B=反向）、航路名、高度范围；
* 机场不直接落在航路上，用 DCT 接到最近的一批航路点（真实签派也是这么做的）。

求解
----
把"机场 → 航路网 → 机场"包装成一个虚拟源点 S / 虚拟汇点 T 的最短路问题，
交给 ``scipy.sparse.csgraph.dijkstra``（C 实现）。每次查询只改写 S 行和 T 列的权重，
不必重建矩阵，单个 OD 约几毫秒。

多样性
------
拿到第一条最短路后，把它用到的边权重乘以一个惩罚因子再跑一次，就能得到第二条
"绕开原路"的可行航路，重复即可得到多条候选（老师模型的数据来源）。
"""

import pickle

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from . import config, db, geo

DCT = "DCT"
S_INDEX = 0        # 虚拟源点
T_INDEX = 1        # 虚拟汇点
NODE_OFFSET = 2    # 航路点在矩阵中的下标偏移
INF = 1.0e9
INF_THRESHOLD = 1.0e8

# Pre-train 时期的包名。pkl 里保存的是 ``self.__dict__``，其中 `GridIndex` 等实例的类
# 路径是 ``src.geo.*``；本包同名源码在 ``aoc_route.net.*`` 下，读老缓存时按前缀重定向，
# 避免 ``ModuleNotFoundError: No module named 'src'`` 把已有缓存判成"不可用"。
_LEGACY_PACKAGE = "src"


class _CompatUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module == _LEGACY_PACKAGE or module.startswith(_LEGACY_PACKAGE + "."):
            module = (__package__ or "aoc_route.net") + module[len(_LEGACY_PACKAGE):]
        return super().find_class(module, name)


class Network:
    """航路图 + 机场接入点 + 求解/校验。"""

    def __init__(self):
        # ---- 航路点 ----
        self.waypoint_index = {}
        self.node_ident = []
        self.node_region = []
        self.node_type = []
        self.node_lat = np.zeros(0, dtype=np.float64)
        self.node_lon = np.zeros(0, dtype=np.float64)
        self.ident_to_nodes = {}
        self.n_nodes = 0
        self.n_procedure_nodes = 0   # 只被 SID/STAR 用到、不挂航路的"终端区点"节点数
        self.procedure_node_kinds = {}   # 上述节点号 -> {"sid","star"}（决定 DCT 桥的方向）
        # ---- 航路 ----
        self.airway_names = []
        self.airway_name_set = set()
        self._edge_u = np.zeros(0, dtype=np.int32)
        self._edge_v = np.zeros(0, dtype=np.int32)
        self._edge_w = np.zeros(0, dtype=np.float64)
        self._edge_name = np.zeros(0, dtype=np.int32)
        # ---- 机场 ----
        self.airports = {}
        self.airport_idents = []
        self.links = {}             # ident -> [(节点下标, DCT 距离nm), ...] 就近回退
        self.link_ident_nodes = {}  # ident -> {航路点ident: [节点下标]}（DCT 回退用）
        self.unlinked_airports = []
        # ---- SID / STAR 程序 ----
        self.node_index = None      # 航路点空间索引，把程序端点坐标对到图节点
        self.procedures = {}        # ident -> {"sid": [程序...], "star": [程序...]}
        self.sid_options = {}       # ident -> {SID名: {"nodes": {节点:程序里程}, "runways": {...}, ...}}
        self.star_options = {}      # ident -> {STAR名: {"nodes": {...}, ...}}
        self.sid_by_node = {}       # ident -> {节点: [(程序里程, SID名), ...]}（升序，候选列表）
        self.star_by_node = {}      # ident -> {节点: [(程序里程, STAR名), ...]}
        self._s_prepared = {}       # ident -> [[S 行扁平下标, 代价, SID名或None], ...]
        self._t_prepared = {}       # ident -> [[T 列扁平下标, 代价, STAR名或None], ...]
        self._s_proc = {}           # 同 _s_prepared，但只含真实 SID 端点（tier 0）
        self._t_proc = {}           # 同 _t_prepared，但只含真实 STAR 端点（tier 0）
        self._s_cost = {}           # ident -> {节点: 代价}
        self._t_cost = {}           # ident -> {节点: 代价}
        self._t_dct_only = {}       # ident -> {只能靠 DCT 收尾的节点}
        self._s_direct = None       # S -> T 直飞边的扁平下标
        # ---- 稀疏矩阵 ----
        self._mat = None
        self._indptr = None
        self._indices = None
        self._base_data = None
        self._name_data = None
        self._s_start = 0
        self._s_end = 0
        self._s_pos = {}
        self._t_flat = np.zeros(0, dtype=np.int64)
        self._t_pos = {}
        self.out_edges = {}         # 节点下标 -> [(航路名, 后继节点下标), ...]

    # ==================================================================
    # 构建
    # ==================================================================
    @classmethod
    def build(cls, verbose: bool = True, db_path=None) -> "Network":
        """建图。``db_path`` 为空时用 ``config.DB_PATH``；AOC 运行时会传入用户 navdata。"""
        conn = db.connect(db_path)
        try:
            waypoints = db.load_waypoints(conn)
            segments = db.load_airway_segments(conn)
            airports = db.load_airports(conn)
            procedures = db.load_procedures(conn, list(airports))
        finally:
            conn.close()

        net = cls()
        net._build_nodes(waypoints, segments)
        net._add_procedure_nodes(procedures)
        net._build_edges(segments)
        net._build_bridge_edges()
        net._build_airport_links(airports, procedures)
        net._build_matrix()
        net._post_process()
        net._prepare_links()

        if verbose:
            n_sid = sum(len(v["sid"]) for v in net.procedures.values())
            n_star = sum(len(v["star"]) for v in net.procedures.values())
            print("[network] 航路点(图节点) %d 个（其中 %d 个是仅程序用到的终端区点），"
                  "航段 %d 条，机场 %d 个"
                  % (net.n_nodes, net.n_procedure_nodes, len(net._edge_u), len(net.airports)))
            print("[network] 航路名 %d 个（含 DCT 桥），无接入点的机场 %d 个"
                  % (len(net.airway_names), len(net.unlinked_airports)))
            print("[network] SID %d 条 / STAR %d 条，覆盖机场 %d 个（有 SID）"
                  % (n_sid, n_star, sum(1 for v in net.procedures.values() if v["sid"])))
        return net

    def _build_nodes(self, waypoints, segments):
        used = set()
        for seg in segments:
            used.add(seg["u"])
            used.add(seg["v"])
        used = sorted(n for n in used if n in waypoints)   # 稳定顺序
        self.waypoint_index = {nid: i for i, nid in enumerate(used)}
        for nid in used:
            wp = waypoints[nid]
            self.node_ident.append(wp["ident"])
            self.node_region.append(wp["region"])
            self.node_type.append(wp["type"])
        self.node_lat = np.array([waypoints[n]["lat"] for n in used], dtype=np.float64)
        self.node_lon = np.array([waypoints[n]["lon"] for n in used], dtype=np.float64)
        self.n_nodes = len(used)
        for i, ident in enumerate(self.node_ident):
            self.ident_to_nodes.setdefault(ident, []).append(i)

    def _add_procedure_nodes(self, procedures, match_nm=None):
        """把"只被 SID/STAR 用到、不挂航路"的**终端区点**补成图节点。

        这类点（例如 BIKF 的 SID 出口、CYFB 的 STAR 入口）在导航库里是航路点，
        但**没有任何航路段引用**它们，所以建图时本来不会存在 —— 于是程序端点在图上找不到
        可匹配的节点，机场就只能退化成"就近 DCT 接入"，看起来像"没用 SID/STAR"。
        实测这类机场有 **142 个（SID）/ 76 个（STAR）**，且 100% 都属于这种情况。

        补成节点后，程序端点一定匹配得上（距离 ≈ 0），再由 :meth:`_build_bridge_edges`
        给它们接 `DCT` 桥到附近的航路节点，航路串就是真实飞行计划的写法：
        ``BIKF <SID> <出口点> DCT <航路点> V1 …``

        同时记下每个新节点是"谁的端点"（``procedure_node_kinds``），桥边据此定方向。
        """
        match_nm = float(config.CFG.get("procedure_match_nm", 5.0)
                         if match_nm is None else match_nm)
        pts = [(i, float(self.node_lat[i]), float(self.node_lon[i]))
               for i in range(self.n_nodes)]
        index = geo.GridIndex(pts, cell_deg=1.0)
        self.procedure_node_kinds = {}
        seen = {}                                     # (四舍五入坐标) -> (ident, 节点号)
        added = 0
        for procs in procedures.values():
            for kind in ("sid", "star"):
                for p in procs.get(kind, ()):
                    fixes = p["fixes"]
                    if not fixes:
                        continue
                    ident, lat, lon = fixes[-1] if kind == "sid" else fixes[0]
                    lat, lon = float(lat), float(lon)
                    if not ident:
                        continue
                    key = (round(lat, 3), round(lon, 3))
                    prev = seen.get(key)
                    if prev is not None:              # 同一个点被多个程序用到：合并"谁的端点"
                        self.procedure_node_kinds.setdefault(prev[1], set()).add(kind)
                        continue
                    if index.query_radius(lat, lon, match_nm):
                        continue                      # 已有节点能匹配上，不必新增
                    node = len(self.node_ident)
                    self.node_ident.append(ident)
                    self.node_region.append("")
                    self.node_type.append("W")
                    self.node_lat = np.append(self.node_lat, lat)
                    self.node_lon = np.append(self.node_lon, lon)
                    self.procedure_node_kinds[node] = {kind}
                    seen[key] = (ident, node)
                    added += 1
        self.n_nodes = len(self.node_ident)
        self.n_procedure_nodes = added
        for i in range(self.n_nodes - added, self.n_nodes):     # 只登记新增的节点
            self.ident_to_nodes.setdefault(self.node_ident[i], []).append(i)
        return added

    def _build_bridge_edges(self, radius_nm=None, fallback_nm=None, topk=None):
        """给"只有程序用到的终端区点"接 `DCT` 桥到附近的**航路节点**。

        桥用**伪航路名** ``DCT`` 表示，权重是大圆距离 —— 于是航路串天然写成
        ``… <SID出口点> DCT <航路点> …``（真实计划写法），而不是把 SID/STAR 丢掉。

        三条约束（都是为了别把终端区点变成"中转跳板"）：
        1. 只给**不挂任何航路**的节点加桥；
        2. 半径只取 ``config.BRIDGE_RADIUS_NM``（实测真实 DCT 腿中位数 13 NM）；
           半径内没有时**只连最近的那一个**（``BRIDGE_FALLBACK_NM`` 内），保证偏远机场不是死点；
        3. **有方向**：SID 出口点只连出去的边，STAR 入口点只连进来的边。
        """
        radius_nm = float(config.BRIDGE_RADIUS_NM if radius_nm is None else radius_nm)
        fallback_nm = float(config.BRIDGE_FALLBACK_NM if fallback_nm is None else fallback_nm)
        topk = int(config.CFG["link_topk"] if topk is None else topk)
        airway = np.zeros(self.n_nodes + NODE_OFFSET, dtype=bool)
        airway[np.concatenate([self._edge_u, self._edge_v]).astype(np.int64)] = True
        targets = [i for i in range(self.n_nodes) if airway[i + NODE_OFFSET]]
        if not targets:
            return 0
        index = geo.GridIndex([(i, float(self.node_lat[i]), float(self.node_lon[i]))
                               for i in targets], cell_deg=1.0)
        if DCT not in self.airway_name_set:              # 伪航路名
            self.airway_names.append(DCT)
            self.airway_name_set = set(self.airway_names)
        name_idx = len(self.airway_names) - 1
        kinds = getattr(self, "procedure_node_kinds", None) or {}

        us, vs, ws, ns = [], [], [], []

        def add(u, v, dist):                             # 矩阵下标
            us.append(u + NODE_OFFSET)
            vs.append(v + NODE_OFFSET)
            ws.append(float(dist))
            ns.append(name_idx)

        for i in range(self.n_nodes):
            if airway[i + NODE_OFFSET]:
                continue
            cands = index.query_radius(self.node_lat[i], self.node_lon[i], radius_nm)
            if not cands:                                # 半径内没有：只连最近的一个
                cands = index.query_radius(self.node_lat[i], self.node_lon[i], fallback_nm)
                cands.sort(key=lambda t: t[1])
                cands = cands[:1]
            else:
                cands.sort(key=lambda t: t[1])
                cands = cands[:topk]
            kind = kinds.get(i) or {"sid", "star"}
            for j, dist in cands:
                j = int(j)
                if "sid" in kind:                        # SID 出口点：出去
                    add(i, j, dist)
                if "star" in kind:                       # STAR 入口点：进来
                    add(j, i, dist)
        if not us:
            return 0
        self._edge_u = np.concatenate([self._edge_u, np.array(us, dtype=np.int32)])
        self._edge_v = np.concatenate([self._edge_v, np.array(vs, dtype=np.int32)])
        self._edge_w = np.concatenate([self._edge_w, np.array(ws, dtype=np.float64)])
        self._edge_name = np.concatenate([self._edge_name, np.array(ns, dtype=np.int32)])
        return len(us)

    def _build_edges(self, segments):
        name_idx = {}
        self.airway_names = []

        def nidx(name):
            if name not in name_idx:
                name_idx[name] = len(self.airway_names)
                self.airway_names.append(name)
            return name_idx[name]

        # direction: N=双向, F=正向(from->to), B=反向(to->from)
        dir_table = {"N": (True, True), "F": (True, False), "B": (False, True)}
        best = {}   # (u, v) -> (航路等级rank, 航路名下标, 距离)
        for seg in segments:
            ui = self.waypoint_index.get(seg["u"])
            vi = self.waypoint_index.get(seg["v"])
            if ui is None or vi is None or ui == vi:
                continue
            rank = config.AIRWAY_TYPE_RANK.get(seg["atype"], 3)
            dist = geo.haversine_nm(self.node_lat[ui], self.node_lon[ui],
                                    self.node_lat[vi], self.node_lon[vi])
            ni = nidx(seg["name"])
            fwd, bwd = dir_table.get(seg["direction"], (True, True))
            for (u, v), allowed in (((ui, vi), fwd), ((vi, ui), bwd)):
                if not allowed:
                    continue
                cand = (rank, ni, dist)
                old = best.get((u, v))
                if old is None or cand < old:
                    best[(u, v)] = cand

        n = len(best)
        us = np.empty(n, dtype=np.int32)
        vs = np.empty(n, dtype=np.int32)
        ws = np.empty(n, dtype=np.float64)
        ns = np.empty(n, dtype=np.int32)
        for k, ((u, v), (rank, ni, dist)) in enumerate(best.items()):
            us[k] = u + NODE_OFFSET
            vs[k] = v + NODE_OFFSET
            ws[k] = dist
            ns[k] = ni
        self._edge_u, self._edge_v, self._edge_w, self._edge_name = us, vs, ws, ns
        self.airway_name_set = set(self.airway_names)

    def _build_airport_links(self, airports, procedures=None):
        """把机场接到航路网上：**优先用真实 SID/STAR，没有程序才就近 DCT**。

        具体做法：
        * 用程序端点（SID 的出口点 / STAR 的入口点）的坐标在航路点里找一个最近的图节点
          （容差 ``procedure_match_nm``），命中就把它作为接入点，权重是**程序真实里程**；
        * 该机场没有任何可用程序点时，退回"半径 ``link_radius_nm`` 内最近的
          ``link_topk`` 个航路点"的 DCT 回退，权重是大圆距离；
        * 即使有程序，也会额外补上"没被程序点覆盖"的 DCT 回退点，
          免得程序出口点方向不合适时整条航路没法飞。
        """
        self.airports = airports
        self.airport_idents = sorted(airports)
        self.procedures = procedures or {}
        pts = [(i, float(self.node_lat[i]), float(self.node_lon[i])) for i in range(self.n_nodes)]
        self.node_index = geo.GridIndex(pts, cell_deg=1.0)
        radius = float(config.CFG["link_radius_nm"])
        topk = int(config.CFG["link_topk"])
        match_nm = float(config.CFG.get("procedure_match_nm", 5.0))

        for ident in self.airport_idents:
            ap = airports[ident]
            procs = self.procedures.get(ident, {})
            sid_opts, sid_by_node = self._match_procedures(
                procs.get("sid", []), ap, match_nm, "sid")
            star_opts, star_by_node = self._match_procedures(
                procs.get("star", []), ap, match_nm, "star")
            self.sid_options[ident] = sid_opts
            self.star_options[ident] = star_opts
            self.sid_by_node[ident] = sid_by_node
            self.star_by_node[ident] = star_by_node

            # DCT 回退：跳过已经被程序点覆盖的节点（保留程序这个更真实的标注）
            covered = set(sid_by_node) | set(star_by_node)
            cands = self.node_index.query_radius(ap["lat"], ap["lon"], radius)
            cands.sort(key=lambda t: t[1])
            dct = []
            for i, d in cands:
                node = int(i) + NODE_OFFSET
                if node in covered:
                    continue
                dct.append((node, float(d)))
                if len(dct) >= topk:
                    break
            self.links[ident] = dct
            if not dct and not sid_opts and not star_opts:
                self.unlinked_airports.append(ident)

    def _match_procedures(self, procs, airport, match_nm, kind):
        """把一组程序端点对到图节点上。

        返回 ``({程序名: {"nodes": {节点: 程序里程}, ...}}, {节点: [(里程, 程序名), ...]})``。
        同一个程序名可能对应多条跑道（不同航迹），因此 ``nodes`` 是"节点 -> 里程"的字典；
        而**同一个节点也可能被多条程序/多个跑道共用**（例如 ZBAA 出口点 ELKUR 上有 5 个程序名、
        ZSPD 出口点 PIKAS 上有 14 个），所以 by_node 的值是**按里程升序的 (里程, 程序名) 列表** ——
        这正是"没有气象信息、不知道用哪个跑道"时该给出的候选集合（见 ``procedure_choices()``）。
        """
        options = {}
        by_node = {}
        for p in procs:
            fixes = p["fixes"]
            is_sid = kind == "sid"
            endpoint = fixes[-1] if is_sid else fixes[0]
            cands = self.node_index.query_radius(endpoint[1], endpoint[2], match_nm)
            if not cands:
                continue
            node = int(min(cands, key=lambda t: t[1])[0]) + NODE_OFFSET
            # 程序里程：跑道端 -> 逐个航路点；没有跑道端坐标就用机场参考点
            anchor = p.get("end_latlon") or (airport["lat"], airport["lon"])
            pts = [(f[1], f[2]) for f in fixes]
            total = 0.0
            if is_sid:
                total += geo.haversine_nm(anchor[0], anchor[1], pts[0][0], pts[0][1])
            else:
                total += geo.haversine_nm(pts[-1][0], pts[-1][1], anchor[0], anchor[1])
            for a, b in zip(pts, pts[1:]):
                total += geo.haversine_nm(a[0], a[1], b[0], b[1])

            info = options.setdefault(p["name"], {
                "nodes": {}, "fixes": fixes, "runway": p["runway"],
                "end_fix": endpoint[0], "kind": kind,
                "runways": set(),
                "base_name": p.get("base_name", p["name"]),
                "transition": p.get("transition"),
            })
            info["runways"].add(p["runway"])
            prev = info["nodes"].get(node)
            if prev is None or total < prev:
                info["nodes"][node] = total
            # 一个节点上可能有多条程序；同名程序（不同跑道）**按名字去重**，只保留最短里程
            slot = by_node.setdefault(node, {})
            old = slot.get(p["name"])
            if old is None or total < old:
                slot[p["name"]] = total
        for node, slot in by_node.items():
            by_node[node] = sorted((c, n) for n, c in slot.items())
        return options, by_node

    def _prepare_links(self):
        """准备两套接入候选，供"两级求解"使用。

        * **tier 0（只含真实程序端点）**：``_s_proc`` / ``_t_proc``。有 SID/STAR 的机场
          只用程序出口/入口点，产出的航路串就是真实飞行计划的样子；
        * **tier 1（tier 0 + 就近 DCT 回退）**：``_s_prepared`` / ``_t_prepared``。
          用来救"程序端点方向不合适、或者该机场根本没有程序"的 OD 对。

        ⚠️ 程序端点硬约束（``config.REQUIRE_PROCEDURE_ANCHORS``）：
        只要机场**有** SID（出发侧）/ STAR（到达侧），就**不再**给它补 DCT 回退点 ——
        因为首点必须是 SID 的出口点、末点必须是 STAR 的入口点，DCT 回退点会破坏这条规则。
        结果是这类机场的 tier 1 与 tier 0 等价；DCT 只对没有程序的机场（以及收尾侧没有
        STAR 的机场）保留。

        ``_s_cost`` / ``_t_cost`` 存的是"节点 -> 该节点对应的真实里程"（程序点用程序里程、
        DCT 点用大圆距离），两种 tier 共用，用于算航路总里程。
        """
        strict = config.REQUIRE_PROCEDURE_ANCHORS
        for ident in self.airport_idents:
            dct = self.links.get(ident, ())
            sid_opts = self.sid_options.get(ident, {})
            star_opts = self.star_options.get(ident, {})
            # "必须用程序"看的是导航库里的原始程序（与 requires_sid/star 一致）
            raw_sid = bool(self.procedures.get(ident, {}).get("sid"))
            raw_star = bool(self.procedures.get(ident, {}).get("star"))
            # 有 SID 的机场：出发侧只留程序出口点；有 STAR 的机场：到达侧只留程序入口点
            s_dct = () if (strict and raw_sid) else dct
            t_dct = () if (strict and raw_star) else dct
            self._s_proc[ident] = self._pack(sid_opts, (), self._s_pos)[0]
            self._t_proc[ident] = self._pack(star_opts, (), self._t_pos)[0]
            prep = self._pack(sid_opts, s_dct, self._s_pos)
            self._s_prepared[ident], self._s_cost[ident] = prep[0], prep[1]
            prep = self._pack(star_opts, t_dct, self._t_pos)
            self._t_prepared[ident], self._t_cost[ident] = prep[0], prep[1]
            self._t_dct_only[ident] = prep[2]        # 只能靠 DCT 收尾的节点
        self._s_direct = self._s_pos.get(T_INDEX)

    @staticmethod
    def _pack(options, dct, pos_map):
        """返回 ``([[扁平下标, 代价, 程序名或 None], ...], {节点: 代价}, {纯 DCT 节点})``。

        同一个接入点可能被**多条程序/多个跑道**写（``_match_procedures`` 里 by_node 是列表），
        这里每个节点只保留**里程最小的那一条**：这样 Dijkstra 的目标值与
        ``_path_distance()`` 上报的里程完全一致（见 README §4⑨），
        写进航路串的那个程序名也就是"最短的那条"。
        """
        best = {}                       # 节点 -> [扁平下标, 代价, 程序名或 None]
        dct_only = set()
        for name, info in options.items():
            for node, c in info["nodes"].items():
                p = pos_map.get(node)
                if p is None:
                    continue
                cur = best.get(node)
                if cur is None or c < cur[1]:
                    best[node] = [p, c, name]
        for node, c in dct:
            if node in best:            # 程序端点优先，DCT 回退点不覆盖
                continue
            p = pos_map.get(node)
            if p is None:
                continue
            best[node] = [p, float(c), None]
            dct_only.add(node)
        items = list(best.values())
        cost = {node: v[1] for node, v in best.items()}
        return items, cost, dct_only


    def _build_matrix(self):
        n_total = self.n_nodes + NODE_OFFSET
        cand = set()
        for lst in self.links.values():
            for node, _ in lst:
                cand.add(node)
        for options in (self.sid_options, self.star_options):
            for opts in options.values():
                for info in opts.values():
                    cand.update(info["nodes"])
        cand_nodes = sorted(cand)

        # S 行：S -> 每个候选接入点（权重每次查询改写）；S -> T 表示"纯 DCT 直飞"
        s_cols = np.array(cand_nodes + [T_INDEX], dtype=np.int64)
        # T 列：每个候选接入点 -> T
        t_rows = np.array(cand_nodes, dtype=np.int64)

        us = np.concatenate([
            self._edge_u.astype(np.int64),
            np.full(s_cols.shape, S_INDEX, dtype=np.int64),
            t_rows,
        ])
        vs = np.concatenate([
            self._edge_v.astype(np.int64),
            s_cols,
            np.full(t_rows.shape, T_INDEX, dtype=np.int64),
        ])
        ws = np.concatenate([
            self._edge_w,
            np.full(s_cols.shape, INF, dtype=np.float64),
            np.full(t_rows.shape, INF, dtype=np.float64),
        ])
        ns = np.concatenate([
            self._edge_name.astype(np.int64),
            np.full(s_cols.shape, -1, dtype=np.int64),
            np.full(t_rows.shape, -1, dtype=np.int64),
        ])

        order = np.lexsort((vs, us))          # 主键 us，次键 vs
        us, vs, ws, ns = us[order], vs[order], ws[order], ns[order]
        counts = np.bincount(us, minlength=n_total)
        indptr = np.zeros(n_total + 1, dtype=np.int64)
        np.cumsum(counts, out=indptr[1:])

        self._mat = csr_matrix((ws, vs, indptr), shape=(n_total, n_total))
        self._indptr = np.asarray(self._mat.indptr, dtype=np.int64)
        self._indices = np.asarray(self._mat.indices, dtype=np.int64)
        self._base_data = np.asarray(self._mat.data, dtype=np.float64).copy()
        self._name_data = ns                     # 与 _base_data 下标一一对应

        self._s_start = int(self._indptr[S_INDEX])
        self._s_end = int(self._indptr[S_INDEX + 1])
        self._s_cols = self._indices[self._s_start:self._s_end]
        self._s_pos = {int(c): self._s_start + i for i, c in enumerate(self._s_cols)}

        self._t_flat = np.flatnonzero(self._indices == T_INDEX)
        rows_of_t = np.searchsorted(self._indptr, self._t_flat, side="right") - 1
        # 必须把 S 行那一条（S -> T 的直接直飞边）排除掉，否则每次查询重置 T 列时
        # 会把直飞边一起置成 INF，短程就再也选不到纯 DCT 直飞了。
        not_s_row = rows_of_t != S_INDEX
        self._t_flat = self._t_flat[not_s_row]
        rows_of_t = rows_of_t[not_s_row]
        self._t_pos = {int(r): int(p) for r, p in zip(rows_of_t, self._t_flat)}

    def _post_process(self):
        for ident, links in self.links.items():
            m = {}
            for node, _ in links:
                m.setdefault(self.node_ident[node - NODE_OFFSET], []).append(node)
            self.link_ident_nodes[ident] = m
        for i in range(len(self._edge_u)):
            u = int(self._edge_u[i])
            v = int(self._edge_v[i])
            nm = self.airway_names[int(self._edge_name[i])]
            self.out_edges.setdefault(u, []).append((nm, v))

    # ==================================================================
    # 持久化
    # ==================================================================
    def save(self, path=None):
        path = path or config.NETWORK_PKL
        path.parent.mkdir(parents=True, exist_ok=True)
        self._mat.data = self._base_data.copy()      # 存盘前还原成未惩罚的权重
        with open(path, "wb") as f:
            pickle.dump(self.__dict__, f, protocol=4)

    @classmethod
    def load(cls, path=None):
        path = path or config.NETWORK_PKL
        with open(path, "rb") as f:
            state = _CompatUnpickler(f).load()
        net = cls()
        net.__dict__.update(state)
        net._mat.data = net._base_data.copy()
        return net

    # ==================================================================
    # 基础查询
    # ==================================================================
    def _flat(self, u: int, v: int) -> int:
        """返回 (u,v) 边在扁平权重数组中的下标，不存在返回 -1。"""
        s = int(self._indptr[u])
        e = int(self._indptr[u + 1])
        cols = self._indices[s:e]
        i = int(np.searchsorted(cols, v))
        if i < cols.shape[0] and int(cols[i]) == v:
            return s + i
        return -1

    def airport(self, ident):
        return self.airports.get(ident)

    def has_links(self, ident) -> bool:
        """该机场能否接到航路网上（作为出发侧**或**到达侧至少一侧可用）。

        出发侧可用 = 有锚点好的 SID，或者"不要求 SID 且有 DCT 回退点"；到达侧同理。
        """
        if ident not in self.airports:
            return False
        dct = bool(self.links.get(ident))
        dep_ok = bool(self.sid_options.get(ident)) or (not self.requires_sid(ident) and dct)
        arr_ok = bool(self.star_options.get(ident)) or (not self.requires_star(ident) and dct)
        return dep_ok or arr_ok

    def requires_sid(self, ident) -> bool:
        """出发侧是否**必须**用真实 SID（= 导航库里该机场有 SID 且开启了硬约束）。

        判定看的是**导航库里的原始程序**（``self.procedures``），不是"锚点有没有匹配到图上"
        （``sid_options``）—— 只要机场有 SID 就必须用，不允许退化成 DCT。
        程序端点接不上航路网的机场（SID 142 个 / STAR 76 个）由"终端区点补节点 + `DCT` 桥"
        兜住（见 :meth:`_build_bridge_edges`），所以这条规则不会把 OD 对变成无解。
        """
        return bool(config.REQUIRE_PROCEDURE_ANCHORS
                    and self.procedures.get(ident, {}).get("sid"))

    def requires_star(self, ident) -> bool:
        """到达侧是否**必须**用真实 STAR（= 导航库里该机场有 STAR 且开启了硬约束）。"""
        return bool(config.REQUIRE_PROCEDURE_ANCHORS
                    and self.procedures.get(ident, {}).get("star"))

    def departure_nodes(self, ident):
        """从该机场出发可用的"首个航路点"集合（SID 出口点 ∪ DCT 回退点）。"""
        return set(self._s_cost.get(ident, ()))

    def arrival_nodes(self, ident):
        """可以收尾到该机场的"最后一个航路点"集合（STAR 入口点 ∪ DCT 回退点）。"""
        return set(self._t_cost.get(ident, ()))

    def dct_exit_nodes(self, ident):
        """只能靠 DCT 收尾的节点（不含 STAR 入口点）—— 校验航路串时用这个。"""
        return set(self._t_dct_only.get(ident, ()))

    def procedure_choices(self, ident, kind, fix_ident):
        """该锚点上的**全部**进/离场程序（不需要模型，也不需要查库）。

        返回 ``[{"name", "base_name", "transition", "runway", "runways", "distance_nm"}, ...]``，
        按程序里程升序。``kind`` 取 ``"sid"``（出发侧，锚点是 SID 出口点）或
        ``"star"``（到达侧，锚点是 STAR 入口点）。

        为什么是"列表"：不同跑道对应**不同的 SID/STAR 名字**，但**落同一个锚点**
        （例如 ZBAA 出口点 ``ELKUR`` 上有 5 个程序名 / 6 个跑道，ZSPD 出口点 ``PIKAS``
        上有 14 个程序名 / 8 个跑道）。没有气象/跑道信息时，只能把候选都列出来。
        """
        table = self.sid_by_node if kind == "sid" else self.star_by_node
        opts = self.sid_options if kind == "sid" else self.star_options
        by_node = table.get(ident, {})
        own = opts.get(ident, {})
        out = []
        for node, items in by_node.items():
            if self.node_ident[node - NODE_OFFSET] != fix_ident:
                continue
            for cost, name in items:
                info = own.get(name, {})
                out.append({
                    "name": name,
                    "base_name": info.get("base_name", name),
                    "transition": info.get("transition"),
                    "runway": info.get("runway", ""),
                    "runways": sorted(r for r in info.get("runways", ()) if r),
                    "distance_nm": float(cost),
                })
        out.sort(key=lambda d: (d["distance_nm"], d["name"]))
        return out

    def procedure_text(self, ident, name):
        """把程序展开成人类可读的路径，例如 ``18L/36R: SS301 SS302 SS303 LURMA ADBAS``。"""
        for kind in ("sid", "star"):
            info = getattr(self, kind + "_options").get(ident, {}).get(name)
            if info:
                runways = info.get("runways") or {info.get("runway") or "?"}
                rwy = "/".join(sorted(r for r in runways if r)) or "?"
                return "%s: %s" % (rwy, " ".join(f[0] for f in info["fixes"]))
        return None

    # ==================================================================
    # 求解
    # ==================================================================
    def _solve(self, dep, arr, penalties=None, allow_dct=False):
        """跑一次 Dijkstra。penalties: {扁平下标: 倍数}。

        ``allow_dct=False`` 时只用真实 SID/STAR 端点（tier 0）；为 True 时额外允许
        就近 DCT 回退点（tier 1）。

        返回 ``(path, cost, labels)``，``labels`` 是 ``{扁平下标: 程序名}``：
        S 行上指向 SID 出口点的边标 SID 名，T 列上从 STAR 入口点出来的边标 STAR 名，
        DCT 回退边不标。后续用 ``labels`` 把节点路径还原成带程序名的航路串。
        """
        a = self.airports.get(dep)
        b = self.airports.get(arr)
        if a is None or b is None:
            return None
        source = self._s_prepared if allow_dct else self._s_proc
        sink = self._t_prepared if allow_dct else self._t_proc
        s_items = source.get(dep)
        t_items = sink.get(arr)
        if not s_items or not t_items:
            return None

        # 程序端点硬约束（这里在**运行期**再兜一层：即使 network.pkl 是旧规则建的，
        # 也不会放出违反"首点=SID 出口点 / 末点=STAR 入口点"的航路）：
        # 出发机场有 SID 时只允许从 SID 出口点起飞，到达机场有 STAR 时只允许从 STAR 入口点收尾。
        if self.requires_sid(dep):
            s_items = [it for it in s_items if it[2]]
        if self.requires_star(arr):
            t_items = [it for it in t_items if it[2]]
        if not s_items or not t_items:
            return None

        gcd = geo.haversine_nm(a["lat"], a["lon"], b["lat"], b["lon"])
        data = self._base_data.copy()
        labels = {}
        data[self._s_start:self._s_end] = INF
        # 极短程允许纯 DCT 直飞；但两端任一侧必须走程序时，就不允许"机场 DCT 机场"
        if (gcd <= float(config.CFG["direct_dct_max_nm"]) and self._s_direct is not None
                and not self.requires_sid(dep) and not self.requires_star(arr)):
            data[self._s_direct] = gcd                      # 极短程允许纯 DCT 直飞
        for p, cost, name in s_items:
            data[p] = cost
            if name:
                labels[p] = name
        data[self._t_flat] = INF
        for p, cost, name in t_items:
            data[p] = cost
            if name:
                labels[p] = name
        if penalties:
            for flat, factor in penalties.items():
                if 0 <= flat < data.shape[0] and data[flat] < INF_THRESHOLD:
                    data[flat] *= factor

        self._mat.data = data
        dist, pred = dijkstra(self._mat, directed=True, indices=S_INDEX,
                              return_predecessors=True)
        if not np.isfinite(dist[T_INDEX]) or dist[T_INDEX] >= INF_THRESHOLD:
            return None

        path = []
        cur = T_INDEX
        while cur != S_INDEX:
            path.append(int(cur))
            cur = int(pred[cur])
            if cur < 0:
                return None
        path.append(S_INDEX)
        path.reverse()
        return path, float(dist[T_INDEX]), labels

    def _used_flats(self, path):
        flats = []
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            if u == S_INDEX:
                flats.append(self._s_pos.get(v, -1))
            elif v == T_INDEX:
                flats.append(self._t_pos.get(u, -1))
            else:
                flats.append(self._flat(u, v))
        return [f for f in flats if f >= 0]

    def _path_distance(self, dep, arr, path):
        a = self.airports[dep]
        b = self.airports[arr]
        total = 0.0
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            if u == S_INDEX and v == T_INDEX:
                total += geo.haversine_nm(a["lat"], a["lon"], b["lat"], b["lon"])
            elif u == S_INDEX:
                total += self._s_cost.get(dep, {}).get(v, 0.0)
            elif v == T_INDEX:
                total += self._t_cost.get(arr, {}).get(u, 0.0)
            else:
                flat = self._flat(u, v)
                total += float(self._base_data[flat]) if flat >= 0 else 0.0
        return total

    def path_to_tokens(self, dep, arr, path, labels=None, fold=False):
        """把节点路径转成航路 token 列表。

        遵循真实飞行计划的写法：

        * 有 SID 时写 ``出发机场 SID名 出口点``，没有则写 ``出发机场 DCT 首点``；
        * 换航路时写航路名；同一条航路连续飞行时省略中间点 —— 但**逐点写法**（``fold=False``，
          默认，数据集/模型用的形态）会把这条航路上的每个点都写出来；
        * 有 STAR 时写 ``入口点 STAR名 到达机场``，没有则写 ``末点 DCT 到达机场``。

        ``fold=True``（**折叠写法**，CLI/API 显示用）时，同一条航路上**只保留离开这条航路的
        那个点**（航路名 + 该点），首点（SID 出口点）与末点（STAR 入口点）不受影响：

        * 逐点：``ZBAA ELKU9Z ELKUR W40 DOXAB OVNUG PANKI ARENO YQG W568 LEDOV``
        * 折叠：``ZBAA ELKU9Z ELKUR W40 YQG W568 LEDOV``

        例：``ZBAA ADBAS8 ADBAS B339 ... AND AND6 ZSSS``
        """
        enroute = path[1:-1]
        if not enroute:
            return [dep, DCT, arr]
        labels = labels or {}
        sid = labels.get(self._s_pos.get(path[1], -1))
        star = labels.get(self._t_pos.get(path[-2], -1))

        # 每一跳用的是哪条航路
        names = []
        for i in range(len(enroute) - 1):
            flat = self._flat(enroute[i], enroute[i + 1])
            if flat < 0:
                return None
            names.append(self.airway_names[int(self._name_data[flat])])

        # 要写出来的点：默认逐点；折叠时"同一条航路上只写离开这条航路的那个点"
        # 例外：``DCT`` 段（程序端点的桥接段）**不折叠** —— 段中间可能是"双身份"的终端区点，
        # 省掉它会让折叠写法产生解析歧义（同名点/绕行），逐点写反而更清楚。
        if fold:
            keep = [k for k in range(1, len(enroute))
                    if k == len(enroute) - 1 or names[k - 1] != names[k]
                    or names[k - 1] == DCT]
        else:
            keep = list(range(1, len(enroute)))

        toks = [dep]
        toks += [sid] if sid else [DCT]
        toks.append(self.node_ident[enroute[0] - NODE_OFFSET])
        prev_name = None
        for k in keep:
            name = names[k - 1]
            if name != prev_name:
                toks.append(name)
            toks.append(self.node_ident[enroute[k] - NODE_OFFSET])
            prev_name = name
        toks += [star, arr] if star else [DCT, arr]
        return toks

    def fold_tokens(self, tokens, budget: int = 200000):
        """把一条航路串折叠成紧凑写法（同一条航路上只留"离开这条航路的那个点"）。

        解析失败返回 ``None``；纯 ``DCT`` 直飞、以及本来就是折叠写法的输入原样返回
        （所以对同一个航路串反复调用是幂等的）。折叠前后 :meth:`path_length_nm` 与
        :meth:`route_airways` 完全一致，SID/STAR 名、首点、末点也都不变。

        注意：数据集/词表/模型仍然用**逐点写法**（``path_to_tokens(fold=False)``），
        这里只负责显示层的压缩。
        """
        info, _ = self.resolve(tokens, budget=budget)
        if info is None:
            return None
        path = list(info["path"])
        if not path:
            return list(tokens)                     # 纯 DCT 直飞，没什么可折叠的
        labels = {}
        if info["sid"]:
            labels[self._s_pos[path[0]]] = info["sid"]
        if info["star"]:
            labels[self._t_pos[path[-1]]] = info["star"]
        return self.path_to_tokens(tokens[0], tokens[-1],
                                   [S_INDEX] + path + [T_INDEX], labels, fold=True)

    def plan(self, dep, arr, n_variants=1, penalty_factor=1.35):
        """生成若干条互不相同的可行航路（**两级**）。

        * tier 0：只用真实 SID/STAR 端点 —— 产出的航路串就是真实飞行计划的样子，
          例如 ``ZBAA LULT9Z LULTA V9 TONIL … SASANT ZSSS``；
        * tier 1：tier 0 无解时，额外放开"就近 DCT 回退点"（程序端点方向不合适、
          或者该机场根本没有程序时才会走到这一步）。

        返回 ``[{tokens, distance_nm, gcd_nm, n_enroute, sid, star}, ...]``，按里程升序。
        """
        if dep == arr:
            return []
        for allow_dct in (False, True):
            out = self._plan_tier(dep, arr, n_variants, penalty_factor, allow_dct)
            if out:
                return out
        return []

    def _plan_tier(self, dep, arr, n_variants, penalty_factor, allow_dct):
        out = []
        seen = set()
        penalties = {}
        for _ in range(int(n_variants) + 3):
            solved = self._solve(dep, arr, penalties or None, allow_dct=allow_dct)
            if solved is None:
                break
            path, _, labels = solved
            toks = self.path_to_tokens(dep, arr, path, labels)
            if toks is None:
                break
            key = tuple(toks)
            if key not in seen:
                seen.add(key)
                dep_ap = self.airports[dep]
                arr_ap = self.airports[arr]
                out.append({
                    "tokens": toks,
                    "distance_nm": self._path_distance(dep, arr, path),
                    "gcd_nm": geo.haversine_nm(dep_ap["lat"], dep_ap["lon"],
                                               arr_ap["lat"], arr_ap["lon"]),
                    "n_enroute": max(0, len(path) - 2),
                    "sid": labels.get(self._s_pos.get(path[1], -1)) if len(path) > 2 else None,
                    "star": labels.get(self._t_pos.get(path[-2], -1)) if len(path) > 2 else None,
                    "dct_fallback": bool(allow_dct),
                })
                if len(out) >= int(n_variants):
                    break
            for flat in self._used_flats(path):
                penalties[flat] = penalties.get(flat, 1.0) * float(penalty_factor)
        out.sort(key=lambda r: r["distance_nm"])
        return out

    # ==================================================================
    # 校验（用于判断模型输出的航路是否真的可飞）
    # ==================================================================
    def _successors(self, nodes, airway):
        res = set()
        for u in nodes:
            for name, v in self.out_edges.get(u, ()):
                if name == airway:
                    res.add(v)
        return res

    def _walk_along(self, nodes, airway, target_ident, visited, max_hops: int = 128):
        """沿 ``airway`` 从 ``nodes`` 继续飞，找出 ident 为 ``target_ident`` 的点。

        返回 ``[(节点, 沿途节点列表), ...]``（列表最后一个元素就是命中的点），找不到返回 ``[]``。
        这是**折叠写法**的解析支撑：``… ELKUR W40 YQG`` 里 ``YQG`` 与 ``ELKUR`` 之间
        图上前者不是后者的直接后继，要沿 W40 把 ``DOXAB OVNUG PANKI ARENO`` 这些中间点补回来。

        用 BFS，所以补回来的总是**最短**的那条航路段（里程/航路名序列与逐点写法一致）；
        ``visited`` 是航路上已经飞过的点（不允许绕回去），``max_hops`` 是安全上限。
        """
        hits = []
        seen = set(visited)
        frontier = []
        for u in nodes:
            for name, v in self.out_edges.get(u, ()):
                if name != airway or v in seen:
                    continue
                seen.add(v)
                frontier.append((v, [v]))
        for _ in range(int(max_hops)):
            if not frontier:
                break
            nxt = []
            for v, trail in frontier:
                if self.node_ident[v - NODE_OFFSET] == target_ident:
                    hits.append((v, trail))
                    continue                      # 命中就不再往后走
                for name, w in self.out_edges.get(v, ()):
                    if name != airway or w in seen:
                        continue
                    seen.add(w)
                    nxt.append((w, trail + [w]))
            if hits:                              # BFS：这一层有命中就收工，保证最短
                break
            frontier = nxt
        return hits

    def resolve(self, tokens, budget: int = 200000, allow_fold: bool = True):
        """解析航路串，返回 ``(info, 原因)``。

        文法是：

        ``出发机场 (DCT | SID名) 首点 [航路名 航路点]* 末点 (DCT | STAR名) 到达机场``

        其中 ``[航路名 航路点]*`` 支持**两种等价写法**：

        * **逐点写法**（数据集/模型训练用的形态）：同一条航路上每个中间点都写出来，
          每一跳都是图上一条真实存在、方向正确的边；
        * **折叠写法**（``allow_fold=True``，CLI/API 显示用）：同一条航路上只写"离开这条航路的
          那个点"，中间点由 :meth:`_walk_along` 沿这条航路 BFS 补回来 —— 两种写法解析出的
          节点路径、里程、航路名序列完全一致（``… ELKUR W40 YQG …`` 与
          ``… ELKUR W40 DOXAB OVNUG PANKI ARENO YQG …`` 等价）。

        **程序端点硬约束**（``config.REQUIRE_PROCEDURE_ANCHORS``，默认开启）：
        出发机场有 SID 时必须写 ``SID名 该程序的出口点``（首点就是 SID 结束点），
        到达机场有 STAR 时必须写 ``该程序的入口点 STAR名``（末点就是 STAR 起始点）；
        这类机场不再接受 ``DCT`` 接入（含 ``出发机场 DCT 到达机场`` 的纯直飞写法）。
        只有**没有**对应程序的机场才允许用 DCT。

        成功时 ``info = {"path": [航路点下标...], "sid": SID名或None, "star": STAR名或None}``。

        为什么要用 DFS 而不是顺序扫：航路名和航路点 ident 会重名（例如中国空域里既有
        一条 ``P179`` 航路，又有一个叫 ``P179`` 的导航台），所以一个 token 要同时尝试
        "当航路名"和"当航路点"两种解释，取第一条走通的路径。
        """
        if not tokens or len(tokens) < 3:
            return None, "航路过短"
        dep, arr = tokens[0], tokens[-1]
        if dep not in self.airports:
            return None, f"未知出发机场 {dep}"
        if arr not in self.airports:
            return None, f"未知到达机场 {arr}"
        n = len(tokens)

        # ---- 纯 DCT 直飞：出发机场 DCT 到达机场 ----
        if n == 3:
            if tokens[1] != DCT:
                return None, "最短航路只能是「出发机场 DCT 到达机场」"
            need_sid = self.requires_sid(dep)
            need_star = self.requires_star(arr)
            if need_sid or need_star:
                side = dep if need_sid else arr
                return None, (f"{side} 有 SID/STAR，航路首点必须是离场程序的出口点、"
                              f"末点必须是进场程序的入口点，不能用「{dep} DCT {arr}」直飞")
            a, b = self.airports[dep], self.airports[arr]
            gcd = geo.haversine_nm(a["lat"], a["lon"], b["lat"], b["lon"])
            if gcd > float(config.CFG["direct_dct_max_nm"]):
                return None, (f"这两点距离 {gcd:.0f}NM 超过 DCT 直飞上限 "
                              f"{config.CFG['direct_dct_max_nm']}NM，必须走航路")
            return {"path": [], "sid": None, "star": None}, "ok"

        # ---- 头部：(DCT | SID名) 首点 ----
        starts = []
        sid_used = None
        if tokens[1] == DCT:
            if self.requires_sid(dep):
                return None, (f"{dep} 有离场程序（SID），首点必须是「SID名 该程序的出口点」，"
                              f"不允许用 DCT 就近接入")
            for node in self.link_ident_nodes.get(dep, {}).get(tokens[2], ()):
                starts.append(node)
        else:
            info = self.sid_options.get(dep, {}).get(tokens[1])
            if info is None:
                return None, f"{tokens[1]} 不是 {dep} 的离场程序（SID），也不是 DCT"
            sid_used = tokens[1]
            for node in info["nodes"]:
                if self.node_ident[node - NODE_OFFSET] == tokens[2]:
                    starts.append(node)
        if not starts:
            return None, f"{tokens[2]} 不是 {dep} 的接入点（DCT 首点或 SID 出口点）"

        exit_dct = self._t_dct_only.get(arr, {})
        star_names = self.star_options.get(arr, {})
        bad_tail = None      # 记下"末点不合规"的具体原因，便于给出可读的报错

        def done(path, star):
            return {"path": path, "sid": sid_used, "star": star}, "ok"

        # (位置, 当前节点, 当前航路, 已走路径)
        stack = [(3, s, None, [s]) for s in reversed(starts)]
        while stack:
            if budget <= 0:
                return None, "搜索超预算"
            budget -= 1
            i, cur, airway, path = stack.pop()
            if i >= n:
                continue

            # ---- 尾部：末点 (DCT | STAR名) 到达机场 ----
            if i == n - 2:
                tok = tokens[i]
                info = star_names.get(tok)
                if info is not None and cur in info["nodes"]:
                    return done(path, tok)
                if tok == DCT:
                    # 到达机场有 STAR 时必须走程序收尾；没有 STAR 才允许 DCT 收尾
                    if cur in exit_dct and not self.requires_star(arr):
                        return done(path, None)
                    if self.requires_star(arr):
                        bad_tail = (f"{arr} 有进场程序（STAR），末点必须是该程序的入口点，"
                                    f"不允许用 DCT 收尾")
                    else:
                        bad_tail = (f"{self.node_ident[cur - NODE_OFFSET]} 不是 {arr} "
                                    f"的 DCT 收尾点")
                    continue
                if info is not None:
                    bad_tail = (f"{tok} 是 {arr} 的进场程序，但它的入口点不是 "
                                f"{self.node_ident[cur - NODE_OFFSET]}"
                                f"（末点必须是该程序的入口点）")
                continue

            tok = tokens[i]
            # 解释一：tok 是航路名，后面的 token 是这条航路上的航路点（后面还得留出收尾）
            if tok in self.airway_name_set and i <= n - 4:
                cands = self._on_airway(cur, tok, tokens[i + 1], path, allow_fold)
                for v, trail in reversed(cands):
                    stack.append((i + 2, v, tok, path + trail))
            # 解释二：tok 是航路点，沿当前航路继续飞
            if airway is not None and i <= n - 3:
                for v, trail in reversed(self._on_airway(cur, airway, tok, path, allow_fold)):
                    stack.append((i + 1, v, airway, path + trail))
        return None, bad_tail or "航路不可解析或不可飞"

    def _on_airway(self, nodes, airway, target_ident, path, allow_fold):
        """``airway`` 上、ident 为 ``target_ident`` 的候选点 ``[(节点, 新增节点列表), ...]``。

        逐点写法：目标点是当前点的**直接后继**（一跳）。
        折叠写法（``allow_fold=True``）：目标点可以是这条航路上更远处的点，中间点由
        :meth:`_walk_along` 沿航路补回来，因此两种写法解析出的节点路径、里程、
        航路名序列完全一致。
        """
        nodes = (nodes,) if isinstance(nodes, int) else nodes      # 起始状态里 cur 是单个节点
        if allow_fold:
            return self._walk_along(nodes, airway, target_ident, set(path))
        return [(v, [v]) for v in self._successors(nodes, airway)
                if self.node_ident[v - NODE_OFFSET] == target_ident]

    def validate(self, tokens, allow_fold: bool = True):
        """校验一条航路串（逐点写法与折叠写法都接受）。返回 ``(ok, reason)``。"""
        info, reason = self.resolve(tokens, allow_fold=allow_fold)
        return (info is not None), reason

    def path_length_nm(self, dep, arr, info):
        """按实际坐标累加航路里程（海里）。``info`` 来自 :meth:`resolve`。

        程序段用**程序真实里程**（``_s_cost`` / ``_t_cost`` 里存的就是按
        ``approach_leg`` 逐点累加的结果），而不是机场到端点的直线近似。
        """
        path = info.get("path") or []
        if not path:
            a, b = self.airports[dep], self.airports[arr]
            return geo.haversine_nm(a["lat"], a["lon"], b["lat"], b["lon"])
        total = self._s_cost.get(dep, {}).get(path[0], 0.0)
        for i in range(len(path) - 1):
            flat = self._flat(path[i], path[i + 1])
            total += float(self._base_data[flat]) if flat >= 0 else 0.0
        total += self._t_cost.get(arr, {}).get(path[-1], 0.0)
        return total

    def edge_airway(self, u, v):
        """返回边 (u, v) 使用的航路名；该边不存在时返回 None。"""
        flat = self._flat(u, v)
        return self.airway_names[int(self._name_data[flat])] if flat >= 0 else None

    def route_airways(self, tokens):
        """把航路串还原成"依次飞过的航路名序列"，解析失败返回 None。"""
        info, _ = self.resolve(tokens)
        if info is None:
            return None
        path = info["path"]
        return [self.edge_airway(path[i], path[i + 1]) for i in range(len(path) - 1)]

    # ==================================================================
    # 统计
    # ==================================================================
    def stats(self):
        reachable = [i for i in self.airport_idents if self.has_links(i)]
        n_sid = sum(len(v["sid"]) for v in self.procedures.values())
        n_star = sum(len(v["star"]) for v in self.procedures.values())
        return {
            "n_nodes": self.n_nodes,
            "n_procedure_nodes": self.n_procedure_nodes,
            "n_edges": int(len(self._edge_u)),
            "n_airways": len(self.airway_names),
            "n_airports": len(self.airports),
            "n_airports_with_links": len(reachable),
            "n_sid_procedures": n_sid,
            "n_star_procedures": n_star,
            "n_airports_with_sid": sum(1 for v in self.procedures.values() if v["sid"]),
            "n_airports_with_star": sum(1 for v in self.procedures.values() if v["star"]),
            "require_procedure_anchors": bool(config.REQUIRE_PROCEDURE_ANCHORS),
            "n_airports_sid_required": sum(1 for i in self.airport_idents
                                           if self.requires_sid(i)),
            "n_airports_star_required": sum(1 for i in self.airport_idents
                                            if self.requires_star(i)),
            "unlinked_airports": list(self.unlinked_airports),
        }

