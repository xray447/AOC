"""通用存储能力：审计、配置版本（草稿→预览→发布→回滚）、同步事件、幂等。"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import bad_request, conflict
from ..models import (AppUser, AuditLog, Company, CompanyConfigVersion, CompanySetting,
                      CompanySettingHistory, IdempotencyKey, SyncEvent)

ECONOMY = "ECONOMY"
POLICY = "POLICY"
CONFIG_KINDS = {ECONOMY, POLICY}


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat().replace("+00:00", "Z")


def audit(db: Session, *, company_id: str | None, actor: AppUser | None, action: str,
          entity: str | None = None, entity_id: str | None = None,
          before: dict | None = None, after: dict | None = None,
          reason: str | None = None, ip: str | None = None,
          request_id: str | None = None, user_agent: str | None = None,
          result: str = "OK") -> AuditLog:
    row = AuditLog(
        company_id=company_id, actor_id=actor.id if actor else None,
        actor_name=actor.username if actor else None, action=action, entity=entity,
        entity_id=entity_id, result=result, before_json=before, after_json=after,
        reason=reason, ip=ip, request_id=request_id, user_agent=user_agent,
    )
    db.add(row)
    db.flush()
    return row


def emit(db: Session, company_id: str, kind: str, *, entity: str | None = None,
         entity_id: str | None = None, payload: dict | None = None,
         user_id: str | None = None) -> SyncEvent:
    event = SyncEvent(company_id=company_id, user_id=user_id, kind=kind, entity=entity,
                      entity_id=entity_id, payload_json=payload)
    db.add(event)
    db.flush()
    return event


# ---------------------------------------------------------------- 配置版本
def current_setting(db: Session, company_id: str, kind: str) -> CompanySetting | None:
    return db.scalar(select(CompanySetting).where(CompanySetting.company_id == company_id,
                                                 CompanySetting.kind == kind))


def setting_payload(db: Session, company_id: str, kind: str) -> tuple[int, dict[str, Any]]:
    row = current_setting(db, company_id, kind)
    if not row:
        return 0, {}
    return row.version, copy.deepcopy(row.payload_json or {})


def ensure_setting(db: Session, company_id: str, kind: str, payload: dict[str, Any],
                   actor_id: str | None = None) -> CompanySetting:
    existing = current_setting(db, company_id, kind)
    if existing:
        return existing
    row = CompanySetting(company_id=company_id, kind=kind, version=1,
                         payload_json=copy.deepcopy(payload), updated_by=actor_id)
    db.add(row)
    db.flush()
    db.add(CompanyConfigVersion(company_id=company_id, kind=kind, version=1,
                                payload_json=copy.deepcopy(payload), reason="初始化",
                                created_by=actor_id))
    db.add(CompanySettingHistory(company_id=company_id, kind=kind, version=1,
                                 payload_json=copy.deepcopy(payload), action="PUBLISH",
                                 actor_id=actor_id, reason="初始化"))
    return row


def publish_setting(db: Session, company: Company, *, kind: str, payload: dict[str, Any],
                    expected_version: int, reason: str | None, actor: AppUser,
                    ip: str | None = None, request_id: str | None = None) -> CompanySetting:
    # PostgreSQL 下锁住配置行，保证“读版本-写新版本”原子；SQLite 由 BEGIN IMMEDIATE 串行化。
    setting = db.scalar(select(CompanySetting).where(
        CompanySetting.company_id == company.id, CompanySetting.kind == kind)
        .with_for_update())
    if setting is None:
        raise bad_request("CONFIG_MISSING", "配置尚未初始化")
    if expected_version != setting.version:
        raise conflict("CONFIG_VERSION_CONFLICT",
                       f"配置已被他人修改（当前 v{setting.version}），请刷新后合并",
                       {"current_version": setting.version, "your_version": expected_version,
                        "current_payload": setting.payload_json})
    before = copy.deepcopy(setting.payload_json or {})
    setting.version += 1
    setting.payload_json = copy.deepcopy(payload)
    setting.updated_by = actor.id
    db.add(CompanyConfigVersion(company_id=company.id, kind=kind, version=setting.version,
                                payload_json=copy.deepcopy(payload), reason=reason,
                                created_by=actor.id))
    db.add(CompanySettingHistory(company_id=company.id, kind=kind, version=setting.version,
                                 payload_json=copy.deepcopy(payload), action="PUBLISH",
                                 actor_id=actor.id, reason=reason))
    audit(db, company_id=company.id, actor=actor, action=f"CONFIG_PUBLISH_{kind}",
          entity="company_setting", entity_id=setting.id, before=before, after=payload,
          reason=reason, ip=ip, request_id=request_id)
    emit(db, company.id, "CONFIG_CHANGED", entity="company_setting", entity_id=setting.id,
         payload={"kind": kind, "version": setting.version})
    db.flush()
    return setting


def rollback_setting(db: Session, company: Company, *, kind: str, target_version: int,
                     expected_version: int, reason: str | None, actor: AppUser,
                     ip: str | None = None, request_id: str | None = None) -> CompanySetting:
    target = db.scalar(select(CompanyConfigVersion).where(
        CompanyConfigVersion.company_id == company.id, CompanyConfigVersion.kind == kind,
        CompanyConfigVersion.version == target_version))
    if not target:
        raise bad_request("CONFIG_VERSION_NOT_FOUND", "目标版本不存在")
    setting = publish_setting(db, company, kind=kind, payload=target.payload_json or {},
                              expected_version=expected_version, reason=reason or f"回滚到 v{target_version}",
                              actor=actor, ip=ip, request_id=request_id)
    db.add(CompanySettingHistory(company_id=company.id, kind=kind, version=setting.version,
                                 payload_json=copy.deepcopy(setting.payload_json),
                                 action="ROLLBACK", actor_id=actor.id,
                                 reason=reason or f"回滚到 v{target_version}"))
    db.flush()
    return setting


def list_versions(db: Session, company_id: str, kind: str, limit: int = 30) -> list[dict[str, Any]]:
    rows = db.scalars(select(CompanyConfigVersion)
                      .where(CompanyConfigVersion.company_id == company_id,
                             CompanyConfigVersion.kind == kind)
                      .order_by(CompanyConfigVersion.version.desc()).limit(limit)).all()
    return [{"version": r.version, "reason": r.reason, "created_by": r.created_by,
             "created_at": iso(r.created_at), "payload": r.payload_json} for r in rows]


# ---------------------------------------------------------------- 幂等
def find_idempotent(db: Session, company_id: str, user_id: str, key: str,
                    path: str) -> tuple[int, dict] | None:
    if not key:
        return None
    row = db.scalar(select(IdempotencyKey).where(
        IdempotencyKey.company_id == company_id, IdempotencyKey.user_id == user_id,
        IdempotencyKey.key == key))
    if not row:
        return None
    if row.path != path:
        raise conflict("IDEMPOTENCY_REUSED", "同一 Idempotency-Key 被用于不同请求")
    return row.status_code, copy.deepcopy(row.response_json or {})


def save_idempotent(db: Session, company_id: str, user_id: str, key: str, path: str,
                    status_code: int, response: dict) -> None:
    if not key:
        return
    db.add(IdempotencyKey(company_id=company_id, user_id=user_id, key=key, path=path,
                          status_code=status_code, response_json=copy.deepcopy(response)))
    db.flush()
