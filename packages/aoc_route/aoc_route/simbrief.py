"""SimBrief 预填链接。链接与航路生成解耦（D-20）。"""
from __future__ import annotations

from urllib.parse import urlencode

BASE = "https://dispatch.simbrief.com/options/custom"


def _weight(value: float | int | None) -> str | None:
    if value is None:
        return None
    try:
        return str(int(round(float(value))))
    except (TypeError, ValueError):
        return None


def build_url(dep: str, arr: str, aircraft: str | None = "A320",
              route: str | None = None, callsign: str | None = None,
              payload_kg: float | None = None, registration: str | None = None) -> str:
    """起降/机型/航路/呼号 + 注册号 + 配载（kg）。

    不预填高度（fl）：巡航高度交给 SimBrief 自己算。
    """
    dep, arr = (dep or "").strip().upper(), (arr or "").strip().upper()
    if not dep or not arr:
        return ""
    q: dict[str, str] = {"orig": dep, "dest": arr, "navlog": "1"}
    if aircraft:
        q["type"] = aircraft
    if callsign:
        q["callsign"] = str(callsign).strip().upper()
    if registration:
        q["reg"] = str(registration).strip().upper()
    if route:
        q["route"] = route
    payload = _weight(payload_kg)
    if payload is not None:
        q["payload"] = payload
    return f"{BASE}?{urlencode(q)}"
