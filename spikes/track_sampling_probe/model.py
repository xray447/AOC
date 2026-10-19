"""采样点模型（V-03）。"""
from __future__ import annotations

from dataclasses import dataclass


class Mode:
    STRAIGHT = "STRAIGHT"
    TURN = "TURN"
    CLIMB_DESCENT = "CLIMB_DESCENT"
    APPROACH = "APPROACH"
    TAXI = "TAXI"
    EVENT = "EVENT"


@dataclass
class Sample:
    t: float          # 相对开始时间（秒）
    lat: float
    lon: float
    alt_ft: float
    agl_ft: float
    gs_kt: float
    vs_fpm: float
    hdg_deg: float
    on_ground: bool
    fuel_kg: float
    g_force: float
    gear: int = 0     # 0 收上 / 1 放下
    flaps: int = 0    # 襟翼档位
