"""航路图运行时配置（`Pre-train/src/config.py` 的建图子集快照）。

只保留建图 / 最短路（Dijkstra）**运行时**需要的常量：机场筛选口径、程序端点硬约束、
DCT 桥半径、航路类型优先级。训练 / 模型 / torch 相关配置不进这里（`Pre-train` 仍是
训练侧的唯一来源，本包只是随产品分发的运行时副本）。

改动口径时的规则：改这里必须同步 `Pre-train/src/config.py`，否则离线建图（Pre-train
CLI）与产品内建图会给出不同的图。
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# 默认路径（运行时总是显式传 navdata / pkl，这两项只服务于手工调试）
# ---------------------------------------------------------------------------
DB_PATH = Path("little_navmap_navigraph.sqlite")
NETWORK_PKL = Path("network.pkl")

# ---------------------------------------------------------------------------
# 运行范围
# ---------------------------------------------------------------------------
SCOPE = "global"  # "china" | "global"

SCOPE_PRESETS = {
    # 中国境内：ICAO 的 Z 区（排除 ZK=朝鲜、ZM=蒙古），且要有 ≥4000ft 的硬质跑道。
    "china": {
        "airport_where": "region LIKE 'Z%' AND region NOT IN ('ZK','ZM') AND country = 'EEU'",
        "min_runway_ft": 4000,
        "min_hard_runways": 1,
        "require_approach": False,
        "link_radius_nm": 120.0,        # DCT 回退：机场到航路节点的最大搜索半径
        "link_topk": 25,                # DCT 回退：每个机场保留的候选点数
        "procedure_match_nm": 5.0,      # SID/STAR 端点坐标对到航路节点的最大容差
        # 程序端点硬约束：机场有 SID/STAR 时，航路首点必须是 SID 出口点、末点必须是 STAR 入口点
        "require_procedure_anchors": True,
        "max_pairs": 20000,
        "n_variants": 3,
        "direct_dct_max_nm": 120.0,
        "max_detour_ratio": 1.9,
        "max_detour_slack_nm": 250.0,
    },
    "japan": {
        "airport_where": "region LIKE 'RJ%'",
        "min_runway_ft": 4000,
        "min_hard_runways": 1,
        "require_approach": True,
        "link_radius_nm": 150.0,
        "link_topk": 30,
        "procedure_match_nm": 5.0,
        "require_procedure_anchors": True,
        "max_pairs": 400000,
        "n_variants": 1,
        "direct_dct_max_nm": 120.0,
        "max_detour_ratio": 1.9,
        "max_detour_slack_nm": 250.0,
    },
    # 全球：跑道 ≥4000ft、有仪表进近程序的大中型机场。
    "global": {
        "airport_where": "1 = 1",
        "min_runway_ft": 4000,
        "min_hard_runways": 1,
        "require_approach": True,
        "link_radius_nm": 150.0,
        "link_topk": 30,
        "procedure_match_nm": 5.0,
        "require_procedure_anchors": True,
        "max_pairs": 400000,
        "n_variants": 1,
        "direct_dct_max_nm": 120.0,
        "max_detour_ratio": 1.9,
        "max_detour_slack_nm": 250.0,
    },
}
CFG = SCOPE_PRESETS[SCOPE]

# ---------------------------------------------------------------------------
# 程序端点硬约束（与 Pre-train 同口径）：机场有 SID/STAR 时首末点必须是程序端点
# ---------------------------------------------------------------------------
REQUIRE_PROCEDURE_ANCHORS = bool(CFG.get("require_procedure_anchors", True))

# ---------------------------------------------------------------------------
# 航路图构建
# ---------------------------------------------------------------------------
# 同一对相邻航路点之间存在多条航路时的取舍优先级（越小越优先）。
# B = 高中低空都可用的航路，J = 高空 Jet 航路，V = 低空 Victor 航路。
AIRWAY_TYPE_RANK = {"B": 0, "J": 1, "V": 2}

# 程序端点（终端区点）到航路节点的 "DCT 桥" 参数（海里）。
# 正常情况只连 BRIDGE_RADIUS_NM 内的航路节点；半径内一个都没有时只连最近的那一个，
# 避免偏远机场变成死点，同时不制造任意远距离跳。桥是有方向的：SID 出口点只出、STAR 入口点只进。
BRIDGE_RADIUS_NM = 40.0
BRIDGE_FALLBACK_NM = 400.0
