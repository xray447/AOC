"""玩家 API：航班、飞机、抽班、配载、轨迹、落地、结算、账本。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import forbidden, not_found
from ..models import (Aircraft, AircraftLock, AircraftType, Airport, AppUser, FlightInstance,
                      LedgerEntry, LoadSheet, Settlement, TrackChunk)
from ..security import UserContext, current_user, get_db
from ..services import ops, store
from .auth import company_dict

router = APIRouter(tags=["player"])


def _idem(ctx: UserContext, db: Session, request: Request):
    key = request.headers.get("idempotency-key", "").strip()
    hit = store.find_idempotent(db, ctx.company.id, ctx.user.id, key, request.url.path)
    return key, hit


def _save_idem(ctx: UserContext, db: Session, request: Request, key: str, data: dict) -> None:
    store.save_idempotent(db, ctx.company.id, ctx.user.id, key, request.url.path, 200, data)


@router.get("/company")
def get_company(ctx: UserContext = Depends(current_user)) -> dict:
    return company_dict(ctx.company)


@router.get("/flights")
def list_flights(status: str | None = None, mine: bool = False, limit: int = Query(50, le=200),
                 ctx: UserContext = Depends(current_user),
                 db: Session = Depends(get_db)) -> list[dict]:
    query = select(FlightInstance).where(FlightInstance.company_id == ctx.company.id)
    if status:
        wanted = [s.strip().upper() for s in status.split(",") if s.strip()]
        query = query.where(FlightInstance.status.in_(wanted))
    if mine:
        query = query.where(FlightInstance.pilot_id == ctx.user.id)
    rows = db.scalars(query.order_by(FlightInstance.scheduled_dep_utc).limit(limit)).all()
    out = []
    for row in rows:
        aircraft = db.get(Aircraft, row.aircraft_id) if row.aircraft_id else None
        out.append(ops.flight_dict(row, aircraft=aircraft))
    return out


@router.get("/flights/{flight_id}")
def get_flight(flight_id: str, ctx: UserContext = Depends(current_user),
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
    return {
        "flight": ops.flight_dict(flight, aircraft=aircraft, pilot=pilot),
        "loadsheet": loadsheet.payload_json if loadsheet else None,
        "settlement": ops.settlement_dict(settlement) if settlement else None,
        "track": {"chunks": len(chunks), "points": sum(len(c.points_json or []) for c in chunks)},
    }


@router.get("/aircraft")
def list_aircraft(ctx: UserContext = Depends(current_user),
                  db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Aircraft).where(Aircraft.company_id == ctx.company.id)
                      .order_by(Aircraft.registration)).all()
    out = []
    for row in rows:
        type_row = db.get(AircraftType, row.type_id)
        lock = db.scalar(select(AircraftLock).where(
            AircraftLock.company_id == ctx.company.id, AircraftLock.aircraft_id == row.id,
            AircraftLock.status == ops.ACTIVE))
        item = ops.aircraft_dict(row, type_row)
        item["locked"] = bool(lock)
        out.append(item)
    return out


@router.get("/airports")
def list_airports(q: str | None = None, limit: int = Query(50, le=200),
                  db: Session = Depends(get_db)) -> list[dict]:
    query = select(Airport)
    if q:
        like = f"%{q.upper()}%"
        query = query.where((Airport.ident.like(like)) | (Airport.name.like(like)))
    rows = db.scalars(query.order_by(Airport.ident).limit(limit)).all()
    return [ops.airport_dict(row) for row in rows]


@router.post("/roster/draw")
def draw(request: Request, body: dict[str, Any] = Body(default_factory=dict),
         ctx: UserContext = Depends(current_user), db: Session = Depends(get_db)):
    key, hit = _idem(ctx, db, request)
    if hit:
        return JSONResponse(content=hit[1], status_code=hit[0])
    data = ops.draw_roster(db, ctx.company, ctx.user, body)
    _save_idem(ctx, db, request, key, data)
    return data


@router.get("/roster/current")
def roster_current(ctx: UserContext = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict:
    return {"roster": ops.current_roster(db, ctx.company, ctx.user)}


@router.get("/roster/{roster_id}")
def roster_detail(roster_id: str, ctx: UserContext = Depends(current_user),
                  db: Session = Depends(get_db)) -> dict:
    roster = ops.roster_by_id(db, ctx.company, roster_id)
    if roster.user_id != ctx.user.id:
        raise forbidden("NOT_YOUR_ROSTER", "任务不属于当前账号")
    return ops.roster_dict(db, roster)


@router.post("/flights/{flight_id}/start")
def start(flight_id: str, request: Request, ctx: UserContext = Depends(current_user),
          db: Session = Depends(get_db)):
    key, hit = _idem(ctx, db, request)
    if hit:
        return JSONResponse(content=hit[1], status_code=hit[0])
    data = ops.start_flight(db, ctx.company, ctx.user, flight_id)
    _save_idem(ctx, db, request, key, data)
    return data


@router.get("/flights/{flight_id}/loadsheet")
def loadsheet(flight_id: str, request: Request, ctx: UserContext = Depends(current_user),
              db: Session = Depends(get_db)):
    key, hit = _idem(ctx, db, request)
    if hit:
        return JSONResponse(content=hit[1], status_code=hit[0])
    result = {"loadsheet": ops.generate_loadsheet(db, ctx.company, ctx.user, flight_id)}
    _save_idem(ctx, db, request, key, result)
    return result


@router.post("/flights/{flight_id}/track")
def track(flight_id: str, body: dict[str, Any], request: Request,
          ctx: UserContext = Depends(current_user), db: Session = Depends(get_db)):
    key, hit = _idem(ctx, db, request)
    if hit:
        return JSONResponse(content=hit[1], status_code=hit[0])
    data = ops.upload_track(db, ctx.company, ctx.user, flight_id, body.get("chunks") or [])
    _save_idem(ctx, db, request, key, data)
    return data


@router.post("/flights/{flight_id}/landing")
def landing(flight_id: str, body: dict[str, Any], request: Request,
            ctx: UserContext = Depends(current_user), db: Session = Depends(get_db)):
    key, hit = _idem(ctx, db, request)
    if hit:
        return JSONResponse(content=hit[1], status_code=hit[0])
    data = ops.land_flight(db, ctx.company, ctx.user, flight_id, body)
    _save_idem(ctx, db, request, key, data)
    return data


@router.post("/flights/{flight_id}/abandon")
def abandon(flight_id: str, request: Request, body: dict[str, Any] | None = Body(default=None),
            ctx: UserContext = Depends(current_user), db: Session = Depends(get_db)):
    key, hit = _idem(ctx, db, request)
    if hit:
        return JSONResponse(content=hit[1], status_code=hit[0])
    data = ops.abandon_flight(db, ctx.company, ctx.user, flight_id,
                              (body or {}).get("reason"))
    _save_idem(ctx, db, request, key, data)
    return data


@router.get("/settlements")
def settlements(limit: int = Query(50, le=200), ctx: UserContext = Depends(current_user),
                db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Settlement).where(
        Settlement.company_id == ctx.company.id, Settlement.user_id == ctx.user.id)
        .order_by(Settlement.created_at.desc()).limit(limit)).all()
    return [ops.settlement_dict(row) for row in rows]


@router.get("/ledger")
def ledger(limit: int = Query(100, le=500), ctx: UserContext = Depends(current_user),
           db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(LedgerEntry).where(
        LedgerEntry.company_id == ctx.company.id, LedgerEntry.user_id == ctx.user.id)
        .order_by(LedgerEntry.created_at.desc()).limit(limit)).all()
    return {"balance": ctx.company.balance, "entries": [ops.ledger_dict(row) for row in rows]}


@router.post("/locks/{lock_id}/heartbeat")
def heartbeat(lock_id: str, ctx: UserContext = Depends(current_user),
              db: Session = Depends(get_db)) -> dict:
    return ops.heartbeat(db, ctx.company, ctx.user, lock_id)
