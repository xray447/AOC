"""SimBrief 预填链接。链接与航路生成解耦（D-20）。"""
from __future__ import annotations

import re
from urllib.parse import urlencode

BASE = "https://dispatch.simbrief.com/options/custom"
KG_PER_TON = 1000.0


def _manualzfw(zfw_kg: float | int | None) -> str | None:
    """ZFW（kg）→ SimBrief `manualzfw`（吨 t = 1000 kg，保留 3 位小数）。

    V-2 实测（2026-11-02）：`manualzfw` 的单位是吨，不是 1000 lb。
    166714 kg → `166.714`；传 367.542 会被当成 367.542 t（远超 MTOW）丢弃。
    """
    if zfw_kg is None:
        return None
    try:
        value = float(zfw_kg) / KG_PER_TON
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return f"{value:.3f}"


def split_callsign(callsign: str | None) -> tuple[str, str | None]:
    """呼号 → (airline, fltnum)。

    `AOC101` → ("AOC", "101")、`AUV123` → ("AUV", "123")；
    没有末尾数字时只返回前缀（fltnum=None），呼号需在 SimBrief 内手动确认。
    """
    text = re.sub(r"[^A-Za-z0-9]", "", str(callsign or "")).upper()
    if not text:
        return "", None
    match = re.match(r"^(.*?)(\d+)$", text)
    if not match or not match.group(1):
        return text, None
    return match.group(1), match.group(2)


def build_url(dep: str, arr: str, aircraft: str | None = "A320",
              route: str | None = None, callsign: str | None = None,
              zfw_kg: float | None = None, registration: str | None = None) -> str:
    """起降/机型/航路/注册号 + 配载（ZFW → `manualzfw`）。

    SimBrief 不接受 `callsign`/`payload`：呼号拆成 `airline` + `fltnum`，
    配载改用零油重（`manualzfw`，单位吨）。不预填高度（fl），交给 SimBrief 自算。
    """
    dep, arr = (dep or "").strip().upper(), (arr or "").strip().upper()
    if not dep or not arr:
        return ""
    q: dict[str, str] = {"orig": dep, "dest": arr, "navlog": "1"}
    if aircraft:
        q["type"] = aircraft
    airline, fltnum = split_callsign(callsign)
    if airline:
        q["airline"] = airline
    if fltnum:
        q["fltnum"] = fltnum
    if registration:
        q["reg"] = str(registration).strip().upper()
    if route:
        q["route"] = route
    manualzfw = _manualzfw(zfw_kg)
    if manualzfw is not None:
        q["manualzfw"] = manualzfw
    return f"{BASE}?{urlencode(q)}"
