"""异常与结算策略：覆盖合并 + 折算（docs/04 §11）。

检测在飞行记录侧（anomaly_flags / 事件），这里只负责「采不采纳、怎么扣」。
"""
from __future__ import annotations

import copy
from typing import Any

SEVERITY = {"ACCEPT": 0, "WEIGHTED": 1, "REVIEW": 2, "REJECT": 3}


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def resolve_policy(
    policy: dict[str, Any],
    *,
    aircraft_type: dict[str, Any] | None = None,
    aircraft: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """合并出生效策略与来源（M2 无飞行员覆盖；覆盖优先级：机型 < 单机）。"""
    base = copy.deepcopy(policy or {})
    overrides = base.pop("overrides", []) or []
    scope_mode = str(base.get("scope_mode") or "COMPANY_ONLY").upper()
    sources: dict[str, str] = {key: "COMPANY" for key in base.keys() if key != "rules"}
    sources.update({f"rules.{k}": "COMPANY" for k in (base.get("rules") or {})})
    effective = copy.deepcopy(base)
    if scope_mode != "ALLOW_OVERRIDES":
        return effective, sources

    type_keys = set()
    if aircraft_type:
        type_keys = {
            str(aircraft_type.get("id") or ""),
            str(aircraft_type.get("icao") or "").upper(),
            f"{aircraft_type.get('icao')}/{aircraft_type.get('variant')}".upper(),
            str(aircraft_type.get("registration") or ""),
        }
    aircraft_keys = set()
    if aircraft:
        aircraft_keys = {str(aircraft.get("id") or ""), str(aircraft.get("registration") or "").upper()}

    for item in overrides:
        scope_type = str(item.get("scope_type") or "").upper()
        scope_id = str(item.get("scope_id") or "").upper()
        if scope_type == "AIRCRAFT_TYPE" and scope_id in {k.upper() for k in type_keys if k}:
            effective = _deep_merge(effective, item.get("policy") or {})
            sources = _mark_sources(sources, item.get("policy") or {}, "AIRCRAFT_TYPE")
        elif scope_type == "AIRCRAFT" and scope_id in {k.upper() for k in aircraft_keys if k}:
            effective = _deep_merge(effective, item.get("policy") or {})
            sources = _mark_sources(sources, item.get("policy") or {}, "AIRCRAFT")
        # PILOT 覆盖在 M2 不存在（无账号），M3 再启用
    return effective, sources


def _mark_sources(sources: dict[str, str], patch: dict[str, Any], source: str) -> dict[str, str]:
    for key, value in patch.items():
        if key == "rules" and isinstance(value, dict):
            for rule in value:
                sources[f"rules.{rule}"] = source
        else:
            sources[key] = source
    return sources


def detect_anomalies(flight: dict[str, Any], events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """把飞行记录里的异常标记/事件折算成带单位的异常项。"""
    flags = {str(f).upper() for f in (flight.get("anomaly_flags") or [])}
    out: list[dict[str, Any]] = []
    gap_seconds = float(flight.get("data_gap_seconds") or 0)
    if gap_seconds <= 0 and "DATA_GAP" in flags:
        gap_seconds = 300.0
    if gap_seconds > 0:
        minutes = gap_seconds / 60.0
        out.append({"kind": "DATA_GAP", "units": round(minutes / 10.0, 3),
                    "value": round(minutes, 1), "detail": f"数据缺口 {minutes:.0f}min"})
    max_rate = 1.0
    pause_ratio = 0.0
    for ev in events or []:
        kind = str(ev.get("type") or "")
        payload = ev.get("payload") or {}
        if kind == "sim_rate":
            try:
                max_rate = max(max_rate, float(payload.get("to") or 1.0))
            except (TypeError, ValueError):
                continue
        elif kind == "pause" and payload.get("paused"):
            pause_ratio = max(pause_ratio, 0.25)
    if max_rate > 1.01:
        out.append({"kind": "SIM_RATE", "units": max_rate, "value": round(max_rate, 2),
                    "detail": f"时间加速 {max_rate:.1f}x"})
    elif "SIM_RATE" in flags and max_rate <= 1.01:
        max_rate = 4.0
        out.append({"kind": "SIM_RATE", "units": max_rate, "value": max_rate,
                    "detail": "时间加速（来自异常标记）"})
    if pause_ratio > 0 or "PAUSE" in flags:
        ratio = max(pause_ratio, 0.25 if "PAUSE" in flags else 0)
        out.append({"kind": "PAUSE", "units": ratio, "value": round(ratio, 3),
                    "detail": f"暂停占比 {ratio * 100:.0f}%"})
    if "TELEPORT" in flags:
        out.append({"kind": "TELEPORT", "units": 1, "value": 1, "detail": "相邻点速度 > 900kt"})
    if "FUEL_JUMP" in flags:
        out.append({"kind": "FUEL_JUMP", "units": 1, "value": 1, "detail": "油量单点跳变 > 20%"})
    if "TRACK_DISTANCE" in flags:
        out.append({"kind": "TRACK_DISTANCE", "units": 1, "value": 1, "detail": "轨迹/大圆比异常"})
    if "NO_TRACK" in flags or "MISSING_TRACK" in flags:
        out.append({"kind": "MISSING_TRACK", "units": 1, "value": 1, "detail": "轨迹缺失"})
    return out


def evaluate(policy: dict[str, Any], anomalies: list[dict[str, Any]]) -> dict[str, Any]:
    """返回 payout_factor / 最终动作 / 逐条明细。"""
    rules = policy.get("rules") or {}
    min_factor = float(policy.get("min_payout_factor", 0.4))
    default_action = str(policy.get("default_action") or "REVIEW").upper()
    factor = 1.0
    action = "ACCEPT"
    review_required = False
    breakdown: list[dict[str, Any]] = []

    for anomaly in anomalies:
        kind = str(anomaly.get("kind") or "").upper()
        rule = rules.get(kind) or {}
        if rule and rule.get("enabled") is False:
            breakdown.append({"kind": kind, "action": "IGNORED", "penalty": 0.0,
                              "detail": anomaly.get("detail") or kind})
            continue
        rule_action = str(rule.get("action") or default_action).upper()
        penalty = 0.0
        resolved_action = rule_action
        if rule_action == "WEIGHTED":
            if kind == "DATA_GAP":
                penalty = min(float(rule.get("max_penalty", 0.30)),
                              float(rule.get("penalty_per_10min", 0.05)) * float(anomaly.get("units") or 0))
            elif kind == "SIM_RATE":
                value = float(anomaly.get("value") or anomaly.get("units") or 0)
                for tier in sorted(rule.get("tiers") or [], key=lambda t: float(t.get("gt") or 0)):
                    if value > float(tier.get("gt") or 0):
                        if str(tier.get("action") or "").upper() == "REJECT":
                            resolved_action = "REJECT"
                        else:
                            penalty = float(tier.get("penalty") or 0.0)
            elif kind == "PAUSE":
                ratio = float(anomaly.get("value") or anomaly.get("units") or 0)
                if ratio > float(rule.get("ratio_gt", 0.20)):
                    penalty = float(rule.get("penalty", 0.10))
            else:
                penalty = float(rule.get("penalty", 0.0))
            if resolved_action == "WEIGHTED":
                factor -= penalty
        if resolved_action == "REJECT":
            factor = 0.0
        if resolved_action == "REVIEW":
            review_required = True
        if SEVERITY.get(resolved_action, 0) > SEVERITY.get(action, 0):
            action = resolved_action
        breakdown.append({
            "kind": kind, "action": resolved_action, "penalty": round(penalty, 4),
            "detail": anomaly.get("detail") or kind,
            "value": anomaly.get("value"), "units": anomaly.get("units"),
        })

    if action == "REJECT":
        factor = 0.0
    factor = round(max(min_factor, min(1.0, factor)), 4)
    if action == "REJECT":
        factor = 0.0
    return {
        "payout_factor": factor,
        "action": action,
        "review_required": review_required,
        "min_payout_factor": min_factor,
        "breakdown": breakdown,
    }


def cost_item_allowed(reject_cost_mode: str, entry_type: str) -> bool:
    mode = (reject_cost_mode or "FULL").upper()
    if mode == "FULL":
        return True
    if mode == "NONE":
        return False
    direct = {"COST_FUEL", "COST_LANDING", "COST_HANDLING", "COST_ATC"}
    return entry_type in direct
