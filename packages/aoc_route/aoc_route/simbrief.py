"""SimBrief 预填链接。链接与航路生成解耦（D-20）。"""
from __future__ import annotations

from urllib.parse import urlencode

BASE = "https://dispatch.simbrief.com/options/custom"


def build_url(dep: str, arr: str, cruise_fl: int = 350, aircraft: str | None = "A320",
              route: str | None = None) -> str:
    dep, arr = (dep or "").strip().upper(), (arr or "").strip().upper()
    if not dep or not arr:
        return ""
    q: dict[str, str] = {"orig": dep, "dest": arr, "navlog": "1"}
    if aircraft:
        q["type"] = aircraft
    q["fl"] = str(int(cruise_fl))
    if route:
        q["route"] = route
    return f"{BASE}?{urlencode(q)}"
