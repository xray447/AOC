"""管理端：运行监控、异常结算复核、飞机锁。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..errors import bad_request, conflict, not_found
from ..models import (Aircraft, AircraftLock, AppUser, FlightInstance, LoadSheet, Roster,
                      Settlement, TrackChunk)
from ..security import AdminContext, client_ip, get_db, require_admin_or_dispatcher
from ..services import ops, store

router = APIRouter(prefix="/admin/ops", tags=["admin-ops"])


@router.get("/flights")
def list_flights(status: str | None = None, pilot_id: str | None = None,
                 aircraft_id: str | None = None, page: int = Query(1, ge=1),
                 page_size: int = Query(50, le=200),
                 ctx: AdminContext = Depends(require_admin_or_dispatcher),
                 db: Session = Depends(get_db)) -> dict:
    query = select(FlightInstance).where(FlightInstance.company_id == ctx.company.id)
    if status:
        query = query.where(FlightInstance.status.in_(
            [s.strip().upper() for s in status.split(",") if s.strip()]))
    if pilot_id:
        query = query.where(FlightInstance.pilot_id == pilot_id)
    if aircraft_id:
        query = query.where(FlightInstance.aircraft_id == aircraft_id)
    total = db.scalar(select(func.count(FlightInstance.id)).where(
        FlightInstance.company_id == ctx.company.id)) or 0
    rows = db.scalars(query.order_by(FlightInstance.scheduled_dep_utc.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for row in rows:
        aircraft = db.get(Aircraft, row.aircraft_id) if row.aircraft_id else None
        pilot = db.get(AppUser, row.pilot_id) if row.pilot_id else None
        settlement = db.scalar(select(Settlement).where(Settlement.flight_id == row.id))
        item = ops.flight_dict(row, aircraft=aircraft, pilot=pilot)
        item["settlement_status"] = settlement.status if settlement else None
        items.append(item)
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.get("/flights/{flight_id}")
def flight_detail(flight_id: str, ctx: AdminContext = Depends(require_admin_or_dispatcher),
                  db: Session = Depends(get_db)) -> dict:
    flight = db.get(FlightInstance, flight_id)
    if not flight or flight.company_id != ctx.company.id:
        raise not_found("FLIGHT_NOT_FOUND", "航班不存在")
    aircraft = db.get(Aircraft, flight.aircraft_id) if flight.aircraft_id else None
    pilot = db.get(AppUser, flight.pilot_id) if flight.pilot_id else None
    loadsheet = db.scalar(select(LoadSheet).where(LoadSheet.flight_id == flight.id))
    settlement = db.scalar(select(Settlement).where(Settlement.flight_id == flight.id))
    chunks = db.scalars(select(TrackChunk).where(TrackChunk.flight_id == flight.id)
                        .order_by(TrackChunk.seq)).all()
    points = [p for chunk in chunks for p in (chunk.points_json or [])]
    step = max(1, len(points) // 2000)
    return {
        "flight": ops.flight_dict(flight, aircraft=aircraft, pilot=pilot),
        "loadsheet": loadsheet.payload_json if loadsheet else None,
        "settlement": ops.settlement_dict(settlement) if settlement else None,
        "track": {"chunks": len(chunks), "points": len(points),
                  "sampled": points[::step]},
    }


@router.get("/review")
def review_queue(ctx: AdminContext = Depends(require_admin_or_dispatcher),
                 db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Settlement).where(
        Settlement.company_id == ctx.company.id, Settlement.status == "HELD")
        .order_by(Settlement.created_at)).all()
    out = []
    for row in rows:
        flight = db.get(FlightInstance, row.flight_id)
        pilot = db.get(AppUser, row.user_id)
        item = ops.settlement_dict(row)
        item["flight"] = ops.flight_dict(flight) if flight else None
        item["pilot"] = {"id": pilot.id, "username": pilot.username,
                         "display_name": pilot.display_name} if pilot else None
        out.append(item)
    return out


@router.post("/review/{settlement_id}")
def review(settlement_id: str, body: dict[str, Any], request: Request,
           ctx: AdminContext = Depends(require_admin_or_dispatcher),
           db: Session = Depends(get_db)) -> dict:
    return ops.review_settlement(db, ctx.company, ctx.user, settlement_id, body,
                                 ip=client_ip(request),
                                 request_id=request.headers.get("x-request-id"))


@router.get("/locks")
def list_locks(ctx: AdminContext = Depends(require_admin_or_dispatcher),
               db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(AircraftLock).where(
        AircraftLock.company_id == ctx.company.id,
        AircraftLock.status == ops.ACTIVE).order_by(AircraftLock.created_at)).all()
    out = []
    for row in rows:
        aircraft = db.get(Aircraft, row.aircraft_id)
        user = db.get(AppUser, row.user_id)
        roster = db.get(Roster, row.roster_id) if row.roster_id else None
        item = ops.lock_dict(row)
        item["aircraft"] = {"registration": aircraft.registration,
                            "current_icao": aircraft.current_icao} if aircraft else None
        item["user"] = {"username": user.username, "display_name": user.display_name} if user else None
        item["roster_status"] = roster.status if roster else None
        out.append(item)
    return out


@router.post("/locks/{lock_id}/release")
def release(lock_id: str, body: dict[str, Any], request: Request,
            ctx: AdminContext = Depends(require_admin_or_dispatcher),
            db: Session = Depends(get_db)) -> dict:
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise bad_request("REASON_REQUIRED", "强制释放必须填写原因")
    lock = db.get(AircraftLock, lock_id)
    if not lock or lock.company_id != ctx.company.id:
        raise not_found("LOCK_NOT_FOUND", "锁不存在")
    if lock.status != ops.ACTIVE:
        raise conflict("LOCK_CLOSED", "锁已释放或过期")
    before = ops.lock_dict(lock)
    lock.status = "RELEASED"
    lock.released_at = utcnow()
    released_flights = []
    roster = db.get(Roster, lock.roster_id) if lock.roster_id else None
    if roster:
        roster.status = "CANCELLED"
        for flight in db.scalars(select(FlightInstance).where(
                FlightInstance.roster_id == roster.id,
                FlightInstance.status.in_([ops.HELD, ops.IN_FLIGHT]))).all():
            flight.status = ops.ABANDONED
            flight.version += 1
            released_flights.append(flight.id)
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="LOCK_FORCE_RELEASE",
                entity="aircraft_lock", entity_id=lock.id, before=before,
                after={"status": "RELEASED", "flights": released_flights}, reason=reason,
                ip=client_ip(request))
    store.emit(db, ctx.company.id, "LOCK_RELEASED", entity="aircraft",
               entity_id=lock.aircraft_id, payload={"reason": reason})
    db.flush()
    return {"ok": True, "released_flights": released_flights}
