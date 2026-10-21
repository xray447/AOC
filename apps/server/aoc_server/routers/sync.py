"""同步：增量事件轮询 + 离线 outbox 批量补传（逐条 savepoint，互不影响）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..errors import ApiError
from ..models import SyncEvent
from ..security import UserContext, current_user, get_db
from ..services import ops, store

router = APIRouter(prefix="/sync", tags=["sync"])


def _event(row: SyncEvent) -> dict[str, Any]:
    return {"id": row.id, "kind": row.kind, "entity": row.entity,
            "entity_id": row.entity_id, "user_id": row.user_id,
            "payload": row.payload_json, "created_at": store.iso(row.created_at)}


@router.get("")
def sync(cursor: int = Query(0, ge=0), limit: int = Query(200, le=500),
         ctx: UserContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(SyncEvent).where(
        SyncEvent.company_id == ctx.company.id, SyncEvent.id > cursor)
        .order_by(SyncEvent.id).limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1].id if rows else cursor
    economy = store.current_setting(db, ctx.company.id, store.ECONOMY)
    policy = store.current_setting(db, ctx.company.id, store.POLICY)
    return {
        "cursor": next_cursor, "has_more": has_more,
        "server_time": store.iso(utcnow()), "events": [_event(row) for row in rows],
        "company": {"id": ctx.company.id, "balance": ctx.company.balance},
        "config_versions": {"economy": economy.version if economy else 0,
                            "policy": policy.version if policy else 0},
    }


@router.post("/batch")
def batch(body: dict[str, Any], ctx: UserContext = Depends(current_user),
          db: Session = Depends(get_db)) -> dict:
    items = body.get("items") or []
    if not isinstance(items, list):
        raise ApiError(400, "BATCH_INVALID", "items 必须是数组")
    results: list[dict[str, Any]] = []
    for item in items[:200]:
        item_id = str(item.get("id") or "")
        kind = str(item.get("type") or "").upper()
        payload = item.get("payload") or {}
        if item_id:
            hit = store.find_idempotent(db, ctx.company.id, ctx.user.id,
                                        f"batch:{item_id}", "/api/v1/sync/batch")
            if hit:
                results.append({"id": item_id, "status": "duplicate", "result": hit[1]})
                continue
        try:
            with db.begin_nested():
                result = _dispatch(db, ctx, kind, payload)
                if item_id:
                    store.save_idempotent(db, ctx.company.id, ctx.user.id,
                                          f"batch:{item_id}", "/api/v1/sync/batch",
                                          200, result)
            results.append({"id": item_id, "status": "ok", "result": result})
        except ApiError as exc:
            results.append({"id": item_id, "status": "error", "code": exc.code,
                            "message": exc.message, "retryable": exc.status_code >= 500})
        except Exception as exc:  # noqa: BLE001 - 单条失败不影响整批
            results.append({"id": item_id, "status": "error", "code": "BATCH_ITEM_FAILED",
                            "message": str(exc), "retryable": True})
    return {"results": results, "server_time": store.iso(utcnow())}


def _dispatch(db: Session, ctx: UserContext, kind: str, payload: dict[str, Any]) -> dict:
    flight_id = str(payload.get("flight_id") or "")
    if kind == "START":
        return ops.start_flight(db, ctx.company, ctx.user, flight_id)
    if kind == "LOADSHEET":
        return {"loadsheet": ops.generate_loadsheet(db, ctx.company, ctx.user, flight_id)}
    if kind == "TRACK":
        return ops.upload_track(db, ctx.company, ctx.user, flight_id,
                                payload.get("chunks") or [])
    if kind == "LANDING":
        return ops.land_flight(db, ctx.company, ctx.user, flight_id, payload)
    if kind == "ABANDON":
        return ops.abandon_flight(db, ctx.company, ctx.user, flight_id, payload.get("reason"))
    if kind == "HEARTBEAT":
        return ops.heartbeat(db, ctx.company, ctx.user, str(payload.get("lock_id") or ""))
    raise ApiError(400, "BATCH_TYPE_INVALID", f"未知离线操作类型：{kind}")
