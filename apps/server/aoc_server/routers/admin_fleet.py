"""管理端：机型模板、单机档案、强制释放锁。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import utcnow
from ..errors import bad_request, conflict, not_found
from ..models import Aircraft, AircraftLock, AircraftType, Airport, FlightInstance, Roster
from ..security import AdminContext, client_ip, get_db, require_admin, require_admin_or_dispatcher
from ..services import ops, store

router = APIRouter(prefix="/admin/fleet", tags=["admin-fleet"])

TYPE_FIELDS = ("manufacturer", "role", "demand_profile", "pax_capacity", "cargo_capacity_kg",
               "oew_kg", "mtow_kg", "mzfw_kg", "mlw_kg", "fuel_capacity_kg", "fuel_burn_kg_h",
               "cruise_speed_kt", "cruise_fl", "min_runway_m", "range_nm", "lease_per_hour",
               "charter_rate_per_hour", "allow_scheduled", "allow_charter", "fare_multiplier",
               "active", "cabin_config_json")


@router.get("/types")
def list_types(ctx: AdminContext = Depends(require_admin_or_dispatcher),
               db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(AircraftType).where(AircraftType.company_id == ctx.company.id)
                      .order_by(AircraftType.icao, AircraftType.variant)).all()
    return [ops.type_dict(row) for row in rows]


@router.post("/types")
def create_type(body: dict[str, Any], request: Request,
                ctx: AdminContext = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    icao = str(body.get("icao") or "").upper().strip()
    if not icao:
        raise bad_request("ICAO_REQUIRED", "机型 ICAO 必填")
    variant = str(body.get("variant") or "STANDARD").upper()
    exists = db.scalar(select(AircraftType.id).where(
        AircraftType.company_id == ctx.company.id, AircraftType.icao == icao,
        AircraftType.variant == variant))
    if exists:
        raise conflict("TYPE_EXISTS", "同 ICAO/variant 的机型已存在")
    row = AircraftType(company_id=ctx.company.id, icao=icao, variant=variant,
                       name=str(body.get("name") or icao), cabin_config_json={})
    for field in TYPE_FIELDS:
        if field in body and body[field] is not None:
            setattr(row, field, body[field])
    if not row.cabin_config_json:
        row.cabin_config_json = {}
    if body.get("pax_capacity") is None:
        row.pax_capacity = sum(int(v or 0) for v in row.cabin_config_json.values())
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise conflict("TYPE_EXISTS", "机型已存在") from exc
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="TYPE_CREATE",
                entity="aircraft_type", entity_id=row.id, after=ops.type_dict(row),
                ip=client_ip(request))
    return ops.type_dict(row)


@router.put("/types/{type_id}")
def update_type(type_id: str, body: dict[str, Any], request: Request,
                ctx: AdminContext = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    row = db.get(AircraftType, type_id)
    if not row or row.company_id != ctx.company.id:
        raise not_found("TYPE_NOT_FOUND", "机型不存在")
    before = ops.type_dict(row)
    for field in TYPE_FIELDS:
        if field in body and body[field] is not None:
            setattr(row, field, body[field])
    if "name" in body and body["name"]:
        row.name = str(body["name"])
    if "cabin_config_json" in body and isinstance(body["cabin_config_json"], dict):
        row.pax_capacity = sum(int(v or 0) for v in body["cabin_config_json"].values())
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="TYPE_UPDATE",
                entity="aircraft_type", entity_id=row.id, before=before,
                after=ops.type_dict(row), ip=client_ip(request))
    db.flush()
    return ops.type_dict(row)


@router.get("/aircraft")
def list_aircraft(ctx: AdminContext = Depends(require_admin_or_dispatcher),
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
        item["lock"] = ops.lock_dict(lock) if lock else None
        out.append(item)
    return out


@router.post("/aircraft")
def create_aircraft(body: dict[str, Any], request: Request,
                    ctx: AdminContext = Depends(require_admin),
                    db: Session = Depends(get_db)) -> dict:
    registration = str(body.get("registration") or "").upper().strip()
    if not registration:
        raise bad_request("REGISTRATION_REQUIRED", "注册号必填")
    type_row = db.get(AircraftType, str(body.get("type_id") or ""))
    if not type_row or type_row.company_id != ctx.company.id:
        raise bad_request("TYPE_NOT_FOUND", "机型不存在")
    base = str(body.get("base_icao") or ctx.company.base_icao).upper()
    current = str(body.get("current_icao") or base).upper()
    for ident in (base, current):
        if not db.scalar(select(Airport.id).where(Airport.ident == ident)):
            raise bad_request("AIRPORT_UNKNOWN", f"机场 {ident} 不在机场库中")
    exists = db.scalar(select(Aircraft.id).where(Aircraft.company_id == ctx.company.id,
                                                 Aircraft.registration == registration))
    if exists:
        raise conflict("AIRCRAFT_EXISTS", "注册号已存在")
    row = Aircraft(company_id=ctx.company.id, registration=registration, type_id=type_row.id,
                   base_icao=base, current_icao=current,
                   status=str(body.get("status") or "ACTIVE").upper(),
                   acquisition=str(body.get("acquisition") or "LEASE").upper(),
                   lease_per_hour=body.get("lease_per_hour"),
                   fuel_kg=float(body.get("fuel_kg") or 0),
                   livery=body.get("livery"), note=body.get("note"))
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise conflict("AIRCRAFT_EXISTS", "注册号已存在") from exc
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="AIRCRAFT_CREATE",
                entity="aircraft", entity_id=row.id, after=ops.aircraft_dict(row, type_row),
                ip=client_ip(request))
    return ops.aircraft_dict(row, type_row)


@router.put("/aircraft/{aircraft_id}")
def update_aircraft(aircraft_id: str, body: dict[str, Any], request: Request,
                    ctx: AdminContext = Depends(require_admin),
                    db: Session = Depends(get_db)) -> dict:
    row = db.get(Aircraft, aircraft_id)
    if not row or row.company_id != ctx.company.id:
        raise not_found("AIRCRAFT_NOT_FOUND", "飞机不存在")
    before = ops.aircraft_dict(row)
    reason = str(body.get("reason") or "").strip()
    if "current_icao" in body and body["current_icao"]:
        ident = str(body["current_icao"]).upper()
        if ident != row.current_icao:
            if not reason:
                raise bad_request("REASON_REQUIRED", "修改飞机当前位置必须填写原因")
            if db.scalar(select(AircraftLock.id).where(
                    AircraftLock.aircraft_id == row.id,
                    AircraftLock.status == ops.ACTIVE)):
                raise conflict("AIRCRAFT_LOCKED", "飞机有活动锁，不能手工改位置")
            if not db.scalar(select(Airport.id).where(Airport.ident == ident)):
                raise bad_request("AIRPORT_UNKNOWN", f"机场 {ident} 不在机场库中")
            row.current_icao = ident
    for field in ("base_icao", "status", "acquisition", "lease_per_hour", "fuel_kg",
                  "livery", "note"):
        if field in body and body[field] is not None:
            setattr(row, field, body[field])
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="AIRCRAFT_UPDATE",
                entity="aircraft", entity_id=row.id, before=before,
                after=ops.aircraft_dict(row), reason=reason, ip=client_ip(request))
    db.flush()
    return ops.aircraft_dict(row)


@router.post("/aircraft/{aircraft_id}/release-lock")
def release_lock(aircraft_id: str, body: dict[str, Any], request: Request,
                 ctx: AdminContext = Depends(require_admin_or_dispatcher),
                 db: Session = Depends(get_db)) -> dict:
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise bad_request("REASON_REQUIRED", "强制释放锁必须填写原因")
    aircraft = db.get(Aircraft, aircraft_id)
    if not aircraft or aircraft.company_id != ctx.company.id:
        raise not_found("AIRCRAFT_NOT_FOUND", "飞机不存在")
    lock = db.scalar(select(AircraftLock).where(
        AircraftLock.company_id == ctx.company.id, AircraftLock.aircraft_id == aircraft.id,
        AircraftLock.status == ops.ACTIVE))
    if not lock:
        raise conflict("NO_ACTIVE_LOCK", "该飞机没有活动锁")
    lock.status = "RELEASED"
    lock.released_at = utcnow()
    roster = db.get(Roster, lock.roster_id) if lock.roster_id else None
    released_flights = []
    if roster:
        roster.status = "CANCELLED"
        for flight in db.scalars(select(FlightInstance).where(
                FlightInstance.roster_id == roster.id,
                FlightInstance.status.in_([ops.HELD, ops.IN_FLIGHT]))).all():
            flight.status = ops.ABANDONED
            flight.version += 1
            released_flights.append(flight.id)
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="LOCK_FORCE_RELEASE",
                entity="aircraft_lock", entity_id=lock.id, reason=reason,
                after={"aircraft_id": aircraft.id, "flights": released_flights},
                ip=client_ip(request))
    store.emit(db, ctx.company.id, "LOCK_RELEASED", entity="aircraft",
               entity_id=aircraft.id, payload={"reason": reason})
    db.flush()
    return {"ok": True, "released_flights": released_flights}
