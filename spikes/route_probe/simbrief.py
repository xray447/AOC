"""SimBrief 链接生成（不编造航路，只把问题交还给人/外部服务）。"""
from __future__ import annotations

from urllib.parse import urlencode

BASE = "https://dispatch.simbrief.com/options/custom"


def build_url(dep: str, arr: str, cruise_fl: int, aircraft: str = "A320") -> str:
    q = {
        "orig": dep.upper(),
        "dest": arr.upper(),
        "type": aircraft,
        "fl": str(int(cruise_fl)),
        "navlog": "1",
    }
    return f"{BASE}?{urlencode(q)}"
