"""SQLite 访问层：只读打开 Little Navmap / Navigraph 导航库。

这个库是 Little Navmap 用 atools 从 Navigraph 数据编译出来的，包含：
waypoint / airway / airport / vor / ndb / ils / approach / transition 等表。
注意两个坑：
  1. ``airport.icao`` 与 ``airport.type`` 这两列在本库里全为 NULL，唯一键是 ``airport.ident``；
  2. 库里没有真实航班航路表，只有航路"网络"（``airway`` 表是航段列表）。
"""

import sqlite3
from pathlib import Path

from . import config

# 机场筛选条件（在 config 的 preset 里给出）
_AIRPORT_BASE_WHERE = (
    "num_runway_hard >= ? AND longest_runway_length >= ?"
)


def connect(db_path=None) -> sqlite3.Connection:
    """以只读方式打开导航库。

    ``db_path`` 为空时用 ``config.DB_PATH``（离线建图 CLI）；AOC 运行时会把
    用户在设置里选择的 navdata 路径传进来，从而直接用用户库建图。
    """
    path = Path(db_path) if db_path else config.DB_PATH
    if not path.exists():
        raise FileNotFoundError(f"找不到导航库：{path}")
    uri = path.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_waypoints(conn):
    """返回 {waypoint_id: {...}}。

    ``type`` 取值：WN/WU 为普通航路点，V 为 VOR（nav_id 指向 vor 表），N 为 NDB。
    """
    rows = conn.execute(
        "SELECT waypoint_id, ident, region, type, nav_id, "
        "       num_victor_airway, num_jet_airway, lonx, laty "
        "FROM waypoint"
    )
    out = {}
    for r in rows:
        out[r["waypoint_id"]] = {
            "ident": r["ident"] or "",
            "region": r["region"] or "",
            "type": r["type"] or "W",
            "nav_id": r["nav_id"],
            "n_victor": r["num_victor_airway"] or 0,
            "n_jet": r["num_jet_airway"] or 0,
            "lat": float(r["laty"]),
            "lon": float(r["lonx"]),
        }
    return out


def load_airway_segments(conn):
    """加载航段。每条记录是某个航路片段上的一跳（from -> to）。"""
    rows = conn.execute(
        "SELECT airway_id, airway_name, airway_type, route_type, "
        "       airway_fragment_no, sequence_no, "
        "       from_waypoint_id, to_waypoint_id, direction, "
        "       minimum_altitude, maximum_altitude "
        "FROM airway"
    )
    out = []
    for r in rows:
        out.append(
            {
                "name": r["airway_name"],
                "atype": r["airway_type"] or "",
                "route_type": r["route_type"] or "",
                "fragment": r["airway_fragment_no"],
                "seq": r["sequence_no"],
                "u": r["from_waypoint_id"],
                "v": r["to_waypoint_id"],
                "direction": r["direction"] or "N",
                "min_alt": r["minimum_altitude"],
                "max_alt": r["maximum_altitude"],
            }
        )
    return out


def load_procedures(conn, airport_idents):
    """加载 SID / STAR（含 enroute 过渡 TRANS）。只读。

    本库里 SID/STAR 藏在 ``approach`` 表里（不是独立的 SID/STAR 表）：

    * ``type='GPS' AND suffix='D'`` → **离场程序 SID**，``approach_leg`` 按
      ``approach_leg_id`` 从**跑道侧排到公共点**；``transition``/``transition_leg``
      再从公共点**延伸到各自的航路侧出口点**（例如 KDEN ``BAYLR6``：
      ``… MTSUI BAYLR`` + ``TRANS HBU: BAYLR BOBBA HBU``）；
    * ``type='GPS' AND suffix='A'`` → **进场程序 STAR**，``approach_leg`` 从**公共点排到跑道侧**，
      ``transition_leg`` 则是从**航路侧入口点**汇到公共点（例如 KDEN ``AALLE4``：
      ``TRANS BBOTL: BBOTL AALLE`` + ``AALLE HEDDD … HAITR``）；
    * 程序名存在 ``approach.fix_ident`` 上（``BAYLR6``），跑道在 ``runway_name``
      或 ``arinc_name``（形如 ``RW18L``）里，起点坐标可用 ``runway_end_id`` 查。

    实测（全球）：只有 **14%** 的 SID/STAR 带 TRANS，而且高度集中在**美国（82%）**；
    中国只有 0.17%。带 TRANS 时程序名写成真实飞行计划的 ``程序名.过渡名``
    （过渡名取 ARINC 标识符 ``transition.fix_ident``，如 ``DUPN1A.DUR1A``），
    而**航路侧端点**取过渡 leg 链的端点坐标（两者偶尔不同名，如 ``DUR1A`` 的端点是 ``DURDA``）。

    返回 ``{机场ident: {"sid": [程序...], "star": [程序...]}}``，每个程序是 dict::

        {"name": "BAYLR6.HBU",     # 带 TRANS 时是 程序名.过渡名；不带时就是程序名
         "base_name": "BAYLR6", "transition": "HBU" 或 None,
         "runway": "08", "kind": "sid"/"star",
         "fixes": [("…", lat, lon), …, ("HBU", lat, lon)],   # 跑道侧 ↔ 航路侧 的完整链
         "end_fix": "HBU",          # SID 的出口点 / STAR 的入口点（= 航路侧端点）
         "end_latlon": (lat, lon) 或 None}   # 跑道端坐标（用于估程序里程）

    ``fixes`` 已按航路链顺序排列，**不含**被标记为复飞（``is_missed``）的航段。
    """
    idents = [i for i in (airport_idents or []) if i]
    if not idents:
        return {}
    marks = ",".join("?" * len(idents))
    scope = (f"a.type = 'GPS' AND a.suffix IN ('D','A') "
             f"AND a.airport_ident IN ({marks})")
    runway_pts = {
        r["runway_end_id"]: (float(r["laty"]), float(r["lonx"]))
        for r in conn.execute("SELECT runway_end_id, lonx, laty FROM runway_end")
    }
    rows = conn.execute(
        "SELECT a.approach_id, a.airport_ident, a.arinc_name, a.runway_name, a.suffix, "
        "       a.fix_ident, a.runway_end_id FROM approach a WHERE " + scope,
        idents,
    ).fetchall()

    # 一次 JOIN 把 leg / transition / transition_leg 全取回来（按量入内存），
    # 避免"每条程序一条 SQL"在 7 万条程序 × 2 张表上的开销。
    leg_of = {}
    for r in conn.execute(
            "SELECT l.approach_id, l.fix_ident, l.fix_laty, l.fix_lonx, l.is_missed "
            "FROM approach_leg l JOIN approach a ON a.approach_id = l.approach_id "
            "WHERE " + scope + " ORDER BY l.approach_leg_id", idents):
        ident = (r["fix_ident"] or "").strip()
        if r["is_missed"] or not ident or r["fix_laty"] is None or r["fix_lonx"] is None:
            continue
        leg_of.setdefault(r["approach_id"], []).append(
            (ident, float(r["fix_laty"]), float(r["fix_lonx"])))

    trans_of = {}
    for r in conn.execute(
            "SELECT t.transition_id, t.approach_id, t.fix_ident FROM transition t "
            "JOIN approach a ON a.approach_id = t.approach_id "
            "WHERE " + scope + " ORDER BY t.transition_id", idents):
        trans_of.setdefault(r["approach_id"], []).append(
            (r["transition_id"], (r["fix_ident"] or "").strip()))

    tleg_of = {}
    for r in conn.execute(
            "SELECT tl.transition_id, tl.fix_ident, tl.fix_laty, tl.fix_lonx "
            "FROM transition_leg tl "
            "JOIN transition t ON t.transition_id = tl.transition_id "
            "JOIN approach a ON a.approach_id = t.approach_id "
            "WHERE " + scope + " ORDER BY tl.transition_leg_id", idents):
        ident = (r["fix_ident"] or "").strip()
        if not ident or r["fix_laty"] is None or r["fix_lonx"] is None:
            continue
        tleg_of.setdefault(r["transition_id"], []).append(
            (ident, float(r["fix_laty"]), float(r["fix_lonx"])))

    out = {}
    for r in rows:
        chain = leg_of.get(r["approach_id"]) or []
        base = (r["fix_ident"] or "").strip()
        if len(chain) < 2 or not base:
            continue
        is_sid = (r["suffix"] or "").upper() == "D"
        kind = "sid" if is_sid else "star"
        runway = (r["runway_name"] or r["arinc_name"] or "").replace("RW", "").strip()
        anchor = runway_pts.get(r["runway_end_id"])

        # 不带 TRANS：整条程序就是 approach_leg 链（中国/欧洲绝大多数情况）
        variants = [(base, None, chain)]
        trans = trans_of.get(r["approach_id"]) or []
        if trans:
            variants = []
            for tid, tname in trans:
                tl = tleg_of.get(tid) or []
                if not tl:
                    continue
                if is_sid:
                    # transition 从公共点（chain 末点）延伸到航路侧出口点
                    merged = chain + (tl[1:] if tl[0][0] == chain[-1][0] else tl)
                else:
                    # transition 从航路侧入口点汇到公共点（chain 首点）
                    merged = (tl[:-1] if tl[-1][0] == chain[0][0] else tl) + chain
                if len(merged) < 2:
                    continue
                variants.append(("%s.%s" % (base, tname) if tname else base, tname or None,
                                 merged))
            if not variants:                      # TRANS 全为空：退回无过渡的写法
                variants = [(base, None, chain)]

        bucket = out.setdefault(r["airport_ident"], {"sid": [], "star": []})[kind]
        for label, tname, fixes in variants:
            bucket.append({
                "name": label,
                "base_name": base,
                "transition": tname,
                "runway": runway,
                "kind": kind,
                "fixes": fixes,
                "end_fix": fixes[-1][0] if is_sid else fixes[0][0],
                "end_latlon": anchor,
            })
    return out


def load_airports(conn):
    """按 config 里当前 SCOPE 的条件筛选机场，返回 {ident: {...}}。

    ident 在本库中唯一（17394 个），大型机场的 ident 就是 ICAO 代码（ZBAA/ZSSS/KJFK...）。
    """
    cfg = config.CFG
    where = [config.CFG["airport_where"], _AIRPORT_BASE_WHERE]
    params = [cfg["min_hard_runways"], cfg["min_runway_ft"]]
    if cfg.get("require_approach"):
        where.append("num_approach > 0")
    sql = (
        "SELECT airport_id, ident, name, region, country, lonx, laty, "
        "       longest_runway_length, num_approach, num_runway_hard "
        "FROM airport WHERE " + " AND ".join(where)
    )
    out = {}
    for r in conn.execute(sql, params):
        ident = (r["ident"] or "").strip()
        if not ident:
            continue
        out[ident] = {
            "airport_id": r["airport_id"],
            "name": r["name"] or "",
            "region": r["region"] or "",
            "country": r["country"] or "",
            "lat": float(r["laty"]),
            "lon": float(r["lonx"]),
            "runway_ft": r["longest_runway_length"] or 0,
            "n_approach": r["num_approach"] or 0,
        }
    return out
