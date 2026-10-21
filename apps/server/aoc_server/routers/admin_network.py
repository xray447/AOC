"""管理端：机场、航点、公司航路、商业航线、班期模板、航班实例。"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aoc_core.ops import economy as econ

from ..db import utcnow
from ..errors import bad_request, conflict, not_found
from ..models import (AircraftLock, Airport, CompanyRoute, FlightInstance,
                      NetworkRoute, Roster, ScheduleTemplate, Waypoint)
from ..security import AdminContext, client_ip, get_db, require_admin_or_dispatcher
from ..services import ops, store

router = APIRouter(prefix="/admin/network", tags=["admin-network"])


def _airport(db: Session, ident: str) -> Airport:
    row = ops.airport_by_ident(db, ident)
    if not row:
        raise bad_request("AIRPORT_UNKNOWN", f"机场 {ident} 不在机场库中")
    return row


def _distance(db: Session, dep: str, arr: str) -> float:
    return round(econ.gcd_nm(ops.airport_dict(_airport(db, dep)),
                             ops.airport_dict(_airport(db, arr))), 1)


def route_dict(row: NetworkRoute) -> dict[str, Any]:
    return {"id": row.id, "dep_icao": row.dep_icao, "arr_icao": row.arr_icao,
            "distance_nm": row.distance_nm, "block_minutes": row.block_minutes,
            "min_type": row.min_type, "default_route": row.default_route,
            "active": row.active, "created_at": store.iso(row.created_at)}


def schedule_dict(row: ScheduleTemplate, route: NetworkRoute | None = None) -> dict[str, Any]:
    return {"id": row.id, "flight_number": row.flight_number, "route_id": row.route_id,
            "dep_local": row.dep_local, "days_of_week": row.days_of_week or [],
            "valid_from": row.valid_from.isoformat() if row.valid_from else None,
            "valid_to": row.valid_to.isoformat() if row.valid_to else None,
            "aircraft_type_id": row.aircraft_type_id, "turn_minutes": row.turn_minutes,
            "active": row.active,
            "dep_icao": route.dep_icao if route else None,
            "arr_icao": route.arr_icao if route else None,
            "created_at": store.iso(row.created_at)}


@router.get("/airports")
def airports(q: str | None = None, limit: int = Query(100, le=500),
             db: Session = Depends(get_db)) -> list[dict]:
    query = select(Airport)
    if q:
        like = f"%{q.upper()}%"
        query = query.where((Airport.ident.like(like)) | (Airport.name.like(like)))
    return [ops.airport_dict(row) for row in db.scalars(query.limit(limit)).all()]


# ---------------------------------------------------------------- 航线
@router.get("/routes")
def list_routes(ctx: AdminContext = Depends(require_admin_or_dispatcher),
                db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(NetworkRoute).where(NetworkRoute.company_id == ctx.company.id)
                      .order_by(NetworkRoute.dep_icao, NetworkRoute.arr_icao)).all()
    return [route_dict(row) for row in rows]


@router.post("/routes")
def create_route(body: dict[str, Any], request: Request,
                 ctx: AdminContext = Depends(require_admin_or_dispatcher),
                 db: Session = Depends(get_db)) -> dict:
    dep = str(body.get("dep_icao") or "").upper()
    arr = str(body.get("arr_icao") or "").upper()
    if not dep or not arr or dep == arr:
        raise bad_request("ROUTE_INVALID", "起降机场不能为空且不能相同")
    distance = float(body.get("distance_nm") or _distance(db, dep, arr))
    block = float(body.get("block_minutes") or econ.estimate_block_minutes(distance, 440))
    row = NetworkRoute(company_id=ctx.company.id, dep_icao=dep, arr_icao=arr,
                       distance_nm=distance, block_minutes=block,
                       min_type=body.get("min_type"), default_route=body.get("default_route"),
                       active=bool(body.get("active", True)))
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise conflict("ROUTE_EXISTS", "该起降对已存在") from exc
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="ROUTE_CREATE",
                entity="network_route", entity_id=row.id, after=route_dict(row),
                ip=client_ip(request))
    return route_dict(row)


@router.put("/routes/{route_id}")
def update_route(route_id: str, body: dict[str, Any], request: Request,
                 ctx: AdminContext = Depends(require_admin_or_dispatcher),
                 db: Session = Depends(get_db)) -> dict:
    row = db.get(NetworkRoute, route_id)
    if not row or row.company_id != ctx.company.id:
        raise not_found("ROUTE_NOT_FOUND", "航线不存在")
    before = route_dict(row)
    for field in ("distance_nm", "block_minutes", "min_type", "default_route", "active"):
        if field in body and body[field] is not None:
            setattr(row, field, body[field])
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="ROUTE_UPDATE",
                entity="network_route", entity_id=row.id, before=before,
                after=route_dict(row), ip=client_ip(request))
    db.flush()
    return route_dict(row)


@router.delete("/routes/{route_id}")
def delete_route(route_id: str, request: Request,
                 ctx: AdminContext = Depends(require_admin_or_dispatcher),
                 db: Session = Depends(get_db)) -> dict:
    row = db.get(NetworkRoute, route_id)
    if not row or row.company_id != ctx.company.id:
        raise not_found("ROUTE_NOT_FOUND", "航线不存在")
    used = db.scalar(select(ScheduleTemplate.id).where(ScheduleTemplate.route_id == row.id))
    if used:
        raise conflict("ROUTE_IN_USE", "航线仍被班期引用，请先删除班期或停用")
    db.delete(row)
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="ROUTE_DELETE",
                entity="network_route", entity_id=route_id, before=route_dict(row),
                ip=client_ip(request))
    return {"ok": True}


# ---------------------------------------------------------------- 班期
@router.get("/schedules")
def list_schedules(ctx: AdminContext = Depends(require_admin_or_dispatcher),
                   db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(ScheduleTemplate).where(
        ScheduleTemplate.company_id == ctx.company.id)
        .order_by(ScheduleTemplate.flight_number)).all()
    return [schedule_dict(row, db.get(NetworkRoute, row.route_id)) for row in rows]


def _valid_hhmm(value: str) -> bool:
    try:
        hour, minute = value.split(":")
        return 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
    except (ValueError, AttributeError):
        return False


@router.post("/schedules")
def create_schedule(body: dict[str, Any], request: Request,
                    ctx: AdminContext = Depends(require_admin_or_dispatcher),
                    db: Session = Depends(get_db)) -> dict:
    route = db.get(NetworkRoute, str(body.get("route_id") or ""))
    if not route or route.company_id != ctx.company.id:
        raise bad_request("ROUTE_NOT_FOUND", "航线不存在")
    number = str(body.get("flight_number") or "").upper().strip()
    dep_local = str(body.get("dep_local") or "09:00")
    if not number:
        raise bad_request("FLIGHT_NUMBER_REQUIRED", "航班号必填")
    if not _valid_hhmm(dep_local):
        raise bad_request("TIME_INVALID", "起飞时刻格式应为 HH:MM")
    exists = db.scalar(select(ScheduleTemplate.id).where(
        ScheduleTemplate.company_id == ctx.company.id,
        ScheduleTemplate.flight_number == number))
    if exists:
        raise conflict("SCHEDULE_EXISTS", "航班号已存在")
    row = ScheduleTemplate(
        company_id=ctx.company.id, flight_number=number, route_id=route.id,
        dep_local=dep_local, days_of_week=[int(d) for d in (body.get("days_of_week") or range(7))],
        valid_from=_date(body.get("valid_from")), valid_to=_date(body.get("valid_to")),
        aircraft_type_id=body.get("aircraft_type_id"),
        turn_minutes=int(body.get("turn_minutes") or 45), active=bool(body.get("active", True)))
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise conflict("SCHEDULE_EXISTS", "航班号已存在") from exc
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="SCHEDULE_CREATE",
                entity="schedule_template", entity_id=row.id,
                after=schedule_dict(row, route), ip=client_ip(request))
    return schedule_dict(row, route)


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise bad_request("DATE_INVALID", "日期格式应为 YYYY-MM-DD") from exc


@router.put("/schedules/{schedule_id}")
def update_schedule(schedule_id: str, body: dict[str, Any], request: Request,
                    ctx: AdminContext = Depends(require_admin_or_dispatcher),
                    db: Session = Depends(get_db)) -> dict:
    row = db.get(ScheduleTemplate, schedule_id)
    if not row or row.company_id != ctx.company.id:
        raise not_found("SCHEDULE_NOT_FOUND", "班期不存在")
    before = schedule_dict(row, db.get(NetworkRoute, row.route_id))
    for field in ("dep_local", "days_of_week", "aircraft_type_id", "turn_minutes", "active"):
        if field in body and body[field] is not None:
            setattr(row, field, body[field])
    if "valid_from" in body:
        row.valid_from = _date(body["valid_from"])
    if "valid_to" in body:
        row.valid_to = _date(body["valid_to"])
    if "dep_local" in body and not _valid_hhmm(str(body["dep_local"])):
        raise bad_request("TIME_INVALID", "起飞时刻格式应为 HH:MM")
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="SCHEDULE_UPDATE",
                entity="schedule_template", entity_id=row.id, before=before,
                after=schedule_dict(row, db.get(NetworkRoute, row.route_id)),
                ip=client_ip(request))
    db.flush()
    return schedule_dict(row, db.get(NetworkRoute, row.route_id))


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: str, request: Request,
                    ctx: AdminContext = Depends(require_admin_or_dispatcher),
                    db: Session = Depends(get_db)) -> dict:
    row = db.get(ScheduleTemplate, schedule_id)
    if not row or row.company_id != ctx.company.id:
        raise not_found("SCHEDULE_NOT_FOUND", "班期不存在")
    db.delete(row)
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="SCHEDULE_DELETE",
                entity="schedule_template", entity_id=schedule_id,
                before=schedule_dict(row), ip=client_ip(request))
    return {"ok": True}


@router.post("/schedules/import")
def import_schedules(body: dict[str, Any], request: Request,
                     ctx: AdminContext = Depends(require_admin_or_dispatcher),
                     db: Session = Depends(get_db)) -> dict:
    raw = str(body.get("csv") or "")
    if not raw.strip():
        raise bad_request("CSV_EMPTY", "CSV 内容为空")
    reader = csv.DictReader(io.StringIO(raw))
    required = {"flight_number", "dep", "arr", "dep_local"}
    if not reader.fieldnames or not required.issubset({f.strip() for f in reader.fieldnames}):
        raise bad_request("CSV_HEADER", f"CSV 需要表头：{', '.join(sorted(required))}")
    imported, errors = 0, []
    for index, row in enumerate(reader, start=2):
        try:
            with db.begin_nested():
                dep = str(row.get("dep") or "").upper()
                arr = str(row.get("arr") or "").upper()
                route = db.scalar(select(NetworkRoute).where(
                    NetworkRoute.company_id == ctx.company.id,
                    NetworkRoute.dep_icao == dep, NetworkRoute.arr_icao == arr))
                if not route:
                    distance = _distance(db, dep, arr)
                    route = NetworkRoute(company_id=ctx.company.id, dep_icao=dep, arr_icao=arr,
                                         distance_nm=distance,
                                         block_minutes=econ.estimate_block_minutes(distance, 440))
                    db.add(route)
                    db.flush()
                dep_local = str(row.get("dep_local") or "")
                if not _valid_hhmm(dep_local):
                    raise ValueError("dep_local 格式应为 HH:MM")
                days = row.get("days") or "0,1,2,3,4,5,6"
                number = str(row.get("flight_number") or "").upper()
                if db.scalar(select(ScheduleTemplate.id).where(
                        ScheduleTemplate.company_id == ctx.company.id,
                        ScheduleTemplate.flight_number == number)):
                    raise ValueError("航班号已存在")
                row_obj = ScheduleTemplate(
                    company_id=ctx.company.id, flight_number=number,
                    route_id=route.id, dep_local=dep_local,
                    days_of_week=[int(d) for d in str(days).split(",") if str(d).strip()],
                    aircraft_type_id=row.get("aircraft_type_id") or None,
                    active=True)
                db.add(row_obj)
                db.flush()
            imported += 1
        except Exception as exc:  # noqa: BLE001 - 错误行逐条报告
            errors.append({"line": index, "message": str(exc)})
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="SCHEDULE_IMPORT",
                entity="schedule_template", after={"imported": imported,
                                                   "failed": len(errors)},
                ip=client_ip(request))
    return {"imported": imported, "errors": errors}


# ---------------------------------------------------------------- 航班实例
@router.get("/flights")
def list_flights(status: str | None = None, date_from: str | None = None,
                 date_to: str | None = None, page: int = Query(1, ge=1),
                 page_size: int = Query(50, le=200),
                 ctx: AdminContext = Depends(require_admin_or_dispatcher),
                 db: Session = Depends(get_db)) -> dict:
    query = select(FlightInstance).where(FlightInstance.company_id == ctx.company.id)
    if status:
        query = query.where(FlightInstance.status.in_(
            [s.strip().upper() for s in status.split(",") if s.strip()]))
    if date_from:
        query = query.where(FlightInstance.scheduled_dep_utc >=
                            datetime.fromisoformat(date_from).replace(tzinfo=econ.timezone.utc))
    if date_to:
        query = query.where(FlightInstance.scheduled_dep_utc <=
                            (datetime.fromisoformat(date_to) + timedelta(days=1)).replace(
                                tzinfo=econ.timezone.utc))
    total = db.scalar(select(func.count(FlightInstance.id)).where(
        FlightInstance.company_id == ctx.company.id)) or 0
    rows = db.scalars(query.order_by(FlightInstance.scheduled_dep_utc)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [ops.flight_dict(row) for row in rows], "page": page,
            "page_size": page_size, "total": total}


@router.post("/flights/generate")
def generate_flights(body: dict[str, Any], request: Request,
                     ctx: AdminContext = Depends(require_admin_or_dispatcher),
                     db: Session = Depends(get_db)) -> dict:
    result = ops.generate_flights(db, ctx.company, days=int(body.get("days") or 7),
                                  start=_date(body.get("start_date")))
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="FLIGHTS_GENERATE",
                entity="flight_instance", after=result, ip=client_ip(request))
    store.emit(db, ctx.company.id, "FLIGHTS_GENERATED", entity="flight_instance",
               payload=result)
    return result


@router.post("/flights/{flight_id}/cancel")
def cancel_flight(flight_id: str, body: dict[str, Any] | None, request: Request,
                  ctx: AdminContext = Depends(require_admin_or_dispatcher),
                  db: Session = Depends(get_db)) -> dict:
    flight = db.get(FlightInstance, flight_id)
    if not flight or flight.company_id != ctx.company.id:
        raise not_found("FLIGHT_NOT_FOUND", "航班不存在")
    if flight.status == ops.COMPLETED:
        raise conflict("FLIGHT_COMPLETED", "已完成航班不能取消")
    before = ops.flight_dict(flight)
    flight.status = ops.CANCELLED
    flight.version += 1
    if flight.roster_id:
        roster = db.get(Roster, flight.roster_id)
        if roster:
            roster.status = "CANCELLED"
            lock = db.scalar(select(AircraftLock).where(
                AircraftLock.roster_id == roster.id, AircraftLock.status == ops.ACTIVE))
            if lock:
                lock.status = "RELEASED"
                lock.released_at = utcnow()
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="FLIGHT_CANCEL",
                entity="flight", entity_id=flight.id, before=before,
                after={"status": ops.CANCELLED}, reason=(body or {}).get("reason"),
                ip=client_ip(request))
    store.emit(db, ctx.company.id, "FLIGHT_CANCELLED", entity="flight",
               entity_id=flight.id, payload={"reason": (body or {}).get("reason")})
    db.flush()
    return ops.flight_dict(flight)


# ---------------------------------------------------------------- 航点/公司航路
@router.get("/waypoints")
def list_waypoints(ctx: AdminContext = Depends(require_admin_or_dispatcher),
                   db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Waypoint).where(Waypoint.company_id == ctx.company.id)
                      .order_by(Waypoint.ident)).all()
    return [{"id": row.id, "ident": row.ident, "kind": row.kind, "lat": row.lat,
             "lon": row.lon, "note": row.note} for row in rows]


@router.post("/waypoints")
def create_waypoint(body: dict[str, Any], request: Request,
                    ctx: AdminContext = Depends(require_admin_or_dispatcher),
                    db: Session = Depends(get_db)) -> dict:
    ident = str(body.get("ident") or "").upper().strip()
    if not ident:
        raise bad_request("IDENT_REQUIRED", "航点 ident 必填")
    try:
        lat, lon = float(body.get("lat")), float(body.get("lon"))
    except (TypeError, ValueError) as exc:
        raise bad_request("COORD_INVALID", "经纬度必须是数字") from exc
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise bad_request("COORD_INVALID", "经纬度超出范围")
    row = Waypoint(company_id=ctx.company.id, ident=ident,
                   kind=str(body.get("kind") or "FIX").upper(), lat=lat, lon=lon,
                   note=body.get("note"))
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise conflict("WAYPOINT_EXISTS", "航点已存在") from exc
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="WAYPOINT_CREATE",
                entity="waypoint", entity_id=row.id, ip=client_ip(request))
    return {"id": row.id, "ident": row.ident, "kind": row.kind, "lat": row.lat,
            "lon": row.lon, "note": row.note}


@router.get("/company-routes")
def list_company_routes(ctx: AdminContext = Depends(require_admin_or_dispatcher),
                        db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(CompanyRoute).where(CompanyRoute.company_id == ctx.company.id)
                      .order_by(CompanyRoute.dep_icao)).all()
    return [{"id": row.id, "dep_icao": row.dep_icao, "arr_icao": row.arr_icao,
             "route_string": row.route_string, "sid": row.sid, "star": row.star,
             "cruise_fl": row.cruise_fl, "min_type": row.min_type,
             "distance_nm": row.distance_nm} for row in rows]


@router.post("/company-routes")
def create_company_route(body: dict[str, Any], request: Request,
                         ctx: AdminContext = Depends(require_admin_or_dispatcher),
                         db: Session = Depends(get_db)) -> dict:
    dep = str(body.get("dep_icao") or "").upper()
    arr = str(body.get("arr_icao") or "").upper()
    row = CompanyRoute(company_id=ctx.company.id, dep_icao=dep, arr_icao=arr,
                       route_string=body.get("route_string"), sid=body.get("sid"),
                       star=body.get("star"), cruise_fl=int(body.get("cruise_fl") or 350),
                       min_type=body.get("min_type"),
                       distance_nm=float(body.get("distance_nm") or _distance(db, dep, arr)))
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise conflict("COMPANY_ROUTE_EXISTS", "公司航路已存在") from exc
    store.audit(db, company_id=ctx.company.id, actor=ctx.user, action="COMPANY_ROUTE_CREATE",
                entity="company_route", entity_id=row.id, ip=client_ip(request))
    return {"id": row.id, "dep_icao": row.dep_icao, "arr_icao": row.arr_icao,
            "route_string": row.route_string}
