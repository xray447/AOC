"""管理端：经济参数与异常结算策略（版本、预览、发布、回滚）。"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from aoc_core.ops import policy as policy_engine
from aoc_core.ops.specs import PARAM_SCHEMA, default_economy, default_policy

from ..errors import bad_request, not_found
from ..models import CompanyConfigVersion
from ..security import AdminContext, client_ip, get_db, require_admin, require_admin_or_dispatcher
from ..services import ops, store

router = APIRouter(prefix="/admin", tags=["admin-config"])


def _setting_payload(ctx: AdminContext, db: Session, kind: str) -> dict[str, Any]:
    setting = store.current_setting(db, ctx.company.id, kind)
    if not setting:
        payload = default_economy() if kind == store.ECONOMY else default_policy()
        return {"version": 0, "payload": payload,
                "defaults": default_economy() if kind == store.ECONOMY else default_policy(),
                "updated_at": None, "updated_by": None}
    return {"version": setting.version, "payload": setting.payload_json,
            "defaults": default_economy() if kind == store.ECONOMY else default_policy(),
            "updated_at": store.iso(setting.updated_at), "updated_by": setting.updated_by}


@router.get("/schema")
@router.get("/settings/schema", include_in_schema=False)
def schema(ctx: AdminContext = Depends(require_admin_or_dispatcher)) -> dict:
    return {"economy": PARAM_SCHEMA, "economy_defaults": default_economy(),
            "policy_defaults": default_policy(),
            "groups": ["需求与载客", "票价与收入", "成本", "惩罚"]}


# ---------------------------------------------------------------- 经济
@router.get("/economy")
@router.get("/settings/economy", include_in_schema=False)
def get_economy(ctx: AdminContext = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    data = _setting_payload(ctx, db, store.ECONOMY)
    data["schema"] = PARAM_SCHEMA
    return data


@router.put("/economy")
@router.put("/settings/economy", include_in_schema=False)
@router.post("/settings/economy/publish", include_in_schema=False)
def publish_economy(body: dict[str, Any], request: Request,
                    ctx: AdminContext = Depends(require_admin),
                    db: Session = Depends(get_db)) -> dict:
    payload = body.get("payload") or {}
    expected = int(body.get("version") or 0)
    ops.validate_config(store.ECONOMY, payload)
    merged = {**default_economy(), **payload}
    setting = store.publish_setting(
        db, ctx.company, kind=store.ECONOMY, payload=merged, expected_version=expected,
        reason=body.get("reason"), actor=ctx.user, ip=client_ip(request),
        request_id=request.headers.get("x-request-id"))
    return {"version": setting.version, "payload": setting.payload_json,
            "updated_at": store.iso(setting.updated_at)}


@router.get("/economy/versions")
@router.get("/settings/economy/versions", include_in_schema=False)
def economy_versions(limit: int = Query(30, le=100),
                     ctx: AdminContext = Depends(require_admin),
                     db: Session = Depends(get_db)) -> list[dict]:
    return store.list_versions(db, ctx.company.id, store.ECONOMY, limit)


@router.get("/economy/versions/{version}")
@router.get("/settings/economy/versions/{version}", include_in_schema=False)
def economy_version(version: int, ctx: AdminContext = Depends(require_admin),
                    db: Session = Depends(get_db)) -> dict:
    row = db.scalar(select(CompanyConfigVersion).where(
        CompanyConfigVersion.company_id == ctx.company.id,
        CompanyConfigVersion.kind == store.ECONOMY,
        CompanyConfigVersion.version == version))
    if not row:
        raise not_found("CONFIG_VERSION_NOT_FOUND", "版本不存在")
    return {"version": row.version, "payload": row.payload_json, "reason": row.reason,
            "created_by": row.created_by, "created_at": store.iso(row.created_at)}


@router.post("/economy/rollback")
@router.post("/settings/economy/rollback", include_in_schema=False)
def economy_rollback(body: dict[str, Any], request: Request,
                     ctx: AdminContext = Depends(require_admin),
                     db: Session = Depends(get_db)) -> dict:
    setting = store.rollback_setting(
        db, ctx.company, kind=store.ECONOMY, target_version=int(body.get("target_version") or 0),
        expected_version=int(body.get("version") or 0), reason=body.get("reason"),
        actor=ctx.user, ip=client_ip(request),
        request_id=request.headers.get("x-request-id"))
    return {"version": setting.version, "payload": setting.payload_json,
            "updated_at": store.iso(setting.updated_at)}


@router.post("/economy/preview")
@router.post("/settings/economy/preview", include_in_schema=False)
def economy_preview(body: dict[str, Any], ctx: AdminContext = Depends(require_admin)) -> dict:
    payload = body.get("payload") or {}
    return ops.preview_economy(payload, int(body.get("samples") or 100))


# ---------------------------------------------------------------- 异常策略
@router.get("/policy")
@router.get("/settings/settlement-policy", include_in_schema=False)
def get_policy(ctx: AdminContext = Depends(require_admin_or_dispatcher),
               db: Session = Depends(get_db)) -> dict:
    return _setting_payload(ctx, db, store.POLICY)


@router.put("/policy")
@router.put("/settings/settlement-policy", include_in_schema=False)
def publish_policy(body: dict[str, Any], request: Request,
                   ctx: AdminContext = Depends(require_admin),
                   db: Session = Depends(get_db)) -> dict:
    payload = body.get("payload") or {}
    expected = int(body.get("version") or 0)
    ops.validate_config(store.POLICY, payload)
    merged = {**default_policy(), **payload}
    setting = store.publish_setting(
        db, ctx.company, kind=store.POLICY, payload=merged, expected_version=expected,
        reason=body.get("reason"), actor=ctx.user, ip=client_ip(request),
        request_id=request.headers.get("x-request-id"))
    return {"version": setting.version, "payload": setting.payload_json,
            "updated_at": store.iso(setting.updated_at)}


@router.get("/policy/versions")
@router.get("/settings/settlement-policy/versions", include_in_schema=False)
def policy_versions(limit: int = Query(30, le=100),
                    ctx: AdminContext = Depends(require_admin),
                    db: Session = Depends(get_db)) -> list[dict]:
    return store.list_versions(db, ctx.company.id, store.POLICY, limit)


@router.post("/policy/rollback")
@router.post("/settings/settlement-policy/rollback", include_in_schema=False)
def policy_rollback(body: dict[str, Any], request: Request,
                    ctx: AdminContext = Depends(require_admin),
                    db: Session = Depends(get_db)) -> dict:
    setting = store.rollback_setting(
        db, ctx.company, kind=store.POLICY, target_version=int(body.get("target_version") or 0),
        expected_version=int(body.get("version") or 0), reason=body.get("reason"),
        actor=ctx.user, ip=client_ip(request),
        request_id=request.headers.get("x-request-id"))
    return {"version": setting.version, "payload": setting.payload_json,
            "updated_at": store.iso(setting.updated_at)}


@router.post("/policy/preview")
@router.post("/settings/settlement-policy/preview", include_in_schema=False)
def policy_preview(body: dict[str, Any] = Body(default_factory=dict),
                   ctx: AdminContext = Depends(require_admin)) -> dict:
    anomalies = body.get("anomalies")
    if not anomalies:
        raise bad_request("ANOMALIES_REQUIRED", "请提供要模拟的异常组合")
    return ops.preview_policy(body.get("payload") or {}, anomalies)


@router.post("/settings/settlement-policy/resolve", include_in_schema=False)
def policy_resolve(body: dict[str, Any] = Body(default_factory=dict),
                   ctx: AdminContext = Depends(require_admin),
                   db: Session = Depends(get_db)) -> dict:
    """按 pilot/机型/单机返回合并后的有效策略与来源（W-A 兼容接口）。"""
    _, current = store.setting_payload(db, ctx.company.id, store.POLICY)
    pilot = body.get("pilot") or {}
    user = SimpleNamespace(id=str(pilot.get("id") or ""),
                           username=str(pilot.get("username") or ""))
    effective, sources = ops.effective_policy(
        body.get("policy") or current, aircraft_type=body.get("aircraft_type") or {},
        aircraft=body.get("aircraft") or {}, user=user)
    anomalies = body.get("anomalies") or []
    evaluation = policy_engine.evaluate(effective, anomalies)
    return {"effective": effective, "sources": sources, "evaluation": evaluation}
