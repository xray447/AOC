"""运营领域：机场/机型/机队/航线/班期/航班实例/抽班/配载/结算/账本。"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aoc_core.ops import economy as econ
from aoc_core.ops import policy as policy_mod
from aoc_core.ops.specs import (build_aircraft_types, default_economy, default_policy,
                                PARAM_SCHEMA)

from ..config import repo_root
from ..db import utcnow
from ..errors import bad_request, conflict, forbidden, not_found
from ..models import (Aircraft, AircraftLock, AircraftType, Airport, AppUser, Company,
                      EconomySnapshot, FlightInstance, FlightRecord, LedgerEntry, LoadSheet,
                      NetworkRoute, Roster, RosterLeg, ScheduleTemplate, Settlement,
                      TrackChunk)
from . import store

ACTIVE = "ACTIVE"
SCHEDULED = "SCHEDULED"
HELD = "HELD"
IN_FLIGHT = "IN_FLIGHT"
COMPLETED = "COMPLETED"
CANCELLED = "CANCELLED"
ABANDONED = "ABANDONED"
SETTLED = "SETTLED"
VOID = "VOID"
LOCK_MINUTES = 45

AIRPORTS: list[tuple[str, str, float, float, float, str, str, float, float]] = [
    # ident, name, lat, lon, elev_ft, country, size_class, demand, tier
    ("ZBAA", "Beijing Capital", 40.0801, 116.5846, 116, "CN", "large", 180, 1.10),
    ("ZBAD", "Beijing Daxing", 39.5098, 116.4106, 98, "CN", "large", 170, 1.10),
    ("ZSSS", "Shanghai Hongqiao", 31.1979, 121.3363, 10, "CN", "large", 160, 1.05),
    ("ZSPD", "Shanghai Pudong", 31.1434, 121.8052, 13, "CN", "large", 180, 1.10),
    ("ZSHC", "Hangzhou Xiaoshan", 30.2295, 120.4344, 23, "CN", "medium", 90, 1.00),
    ("ZSNJ", "Nanjing Lukou", 31.7420, 118.8622, 49, "CN", "medium", 85, 1.00),
    ("ZUUU", "Chengdu Tianfu", 30.3125, 104.4413, 1625, "CN", "large", 150, 1.05),
    ("ZPPP", "Kunming Changshui", 25.1019, 102.9292, 6903, "CN", "large", 130, 1.00),
    ("ZLXY", "Xi'an Xianyang", 34.4471, 108.7516, 1572, "CN", "medium", 95, 1.00),
    ("ZHHH", "Wuhan Tianhe", 30.7838, 114.2081, 113, "CN", "medium", 90, 1.00),
    ("ZGHA", "Changsha Huanghua", 28.1892, 113.2196, 217, "CN", "medium", 80, 1.00),
    ("ZJHK", "Haikou Meilan", 19.9349, 110.4589, 75, "CN", "medium", 70, 0.95),
    ("ZGGG", "Guangzhou Baiyun", 23.3924, 113.2988, 50, "CN", "large", 170, 1.10),
    ("ZGSZ", "Shenzhen Bao'an", 22.6393, 113.8107, 13, "CN", "large", 150, 1.05),
    ("ZBTJ", "Tianjin Binhai", 39.1244, 117.3462, 10, "CN", "medium", 70, 0.95),
    ("RJTT", "Tokyo Haneda", 35.5533, 139.7812, 21, "JP", "large", 170, 1.10),
    ("RJAA", "Narita", 35.7647, 140.3864, 141, "JP", "large", 150, 1.05),
    ("VHHH", "Hong Kong", 22.3080, 113.9185, 28, "HK", "large", 160, 1.10),
    ("WSSS", "Singapore Changi", 1.3644, 103.9915, 22, "SG", "large", 170, 1.10),
    ("OMDB", "Dubai", 25.2532, 55.3657, 62, "AE", "large", 180, 1.10),
    ("EGLL", "London Heathrow", 51.4700, -0.4543, 83, "GB", "large", 180, 1.10),
    ("LFPG", "Paris CDG", 49.0097, 2.5479, 392, "FR", "large", 170, 1.10),
    ("KJFK", "New York JFK", 40.6413, -73.7781, 13, "US", "large", 180, 1.10),
]


# ---------------------------------------------------------------- 序列化
def iso(dt: datetime | None) -> str | None:
    return store.iso(dt)


def airport_dict(row: Airport) -> dict[str, Any]:
    return {"ident": row.ident, "name": row.name, "lat": row.lat, "lon": row.lon,
            "elevation_ft": row.elevation_ft, "country": row.country,
            "size_class": row.size_class, "demand": row.demand, "tier": row.tier}


def type_dict(row: AircraftType) -> dict[str, Any]:
    return {
        "id": row.id, "icao": row.icao, "variant": row.variant, "name": row.name,
        "manufacturer": row.manufacturer, "role": row.role, "demand_profile": row.demand_profile,
        "cabin_config_json": row.cabin_config_json or {}, "pax_capacity": row.pax_capacity,
        "cargo_capacity_kg": row.cargo_capacity_kg, "oew_kg": row.oew_kg,
        "mtow_kg": row.mtow_kg, "mzfw_kg": row.mzfw_kg, "mlw_kg": row.mlw_kg,
        "fuel_capacity_kg": row.fuel_capacity_kg, "fuel_burn_kg_h": row.fuel_burn_kg_h,
        "cruise_speed_kt": row.cruise_speed_kt, "cruise_fl": row.cruise_fl,
        "min_runway_m": row.min_runway_m, "range_nm": row.range_nm,
        "lease_per_hour": row.lease_per_hour,
        "charter_rate_per_hour": row.charter_rate_per_hour,
        "allow_scheduled": row.allow_scheduled, "allow_charter": row.allow_charter,
        "fare_multiplier": row.fare_multiplier, "active": row.active,
    }


def aircraft_dict(row: Aircraft, type_row: AircraftType | None = None) -> dict[str, Any]:
    out = {
        "id": row.id, "registration": row.registration, "type_id": row.type_id,
        "base_icao": row.base_icao, "current_icao": row.current_icao, "status": row.status,
        "acquisition": row.acquisition, "lease_per_hour": row.lease_per_hour,
        "total_hours": row.total_hours, "total_cycles": row.total_cycles,
        "fuel_kg": row.fuel_kg, "livery": row.livery, "note": row.note,
        "created_at": iso(row.created_at), "updated_at": iso(row.updated_at),
    }
    if type_row is not None:
        out["type"] = {"id": type_row.id, "icao": type_row.icao, "variant": type_row.variant,
                       "name": type_row.name, "role": type_row.role,
                       "pax_capacity": type_row.pax_capacity}
    return out


def flight_dict(row: FlightInstance, *, aircraft: Aircraft | None = None,
                pilot: AppUser | None = None) -> dict[str, Any]:
    out = {
        "id": row.id, "flight_number": row.flight_number, "dep_icao": row.dep_icao,
        "arr_icao": row.arr_icao, "scheduled_dep_utc": iso(row.scheduled_dep_utc),
        "scheduled_arr_utc": iso(row.scheduled_arr_utc), "distance_nm": row.distance_nm,
        "block_minutes": row.block_minutes, "status": row.status,
        "aircraft_id": row.aircraft_id, "pilot_id": row.pilot_id,
        "roster_id": row.roster_id, "route_string": row.route_string, "version": row.version,
        "created_at": iso(row.created_at),
    }
    if aircraft is not None:
        out["aircraft"] = {"id": aircraft.id, "registration": aircraft.registration,
                           "current_icao": aircraft.current_icao}
    if pilot is not None:
        out["pilot"] = {"id": pilot.id, "username": pilot.username,
                        "display_name": pilot.display_name}
    return out


def roster_dict(db: Session, row: Roster) -> dict[str, Any]:
    legs = db.scalars(select(RosterLeg).where(RosterLeg.roster_id == row.id)
                      .order_by(RosterLeg.sequence)).all()
    flights = []
    for leg in legs:
        flight = db.get(FlightInstance, leg.flight_id)
        if flight:
            flights.append({**flight_dict(flight), "leg_status": leg.status,
                            "sequence": leg.sequence})
    aircraft = db.get(Aircraft, row.aircraft_id)
    type_row = db.get(AircraftType, aircraft.type_id) if aircraft else None
    lock = db.scalar(select(AircraftLock).where(AircraftLock.roster_id == row.id,
                                                AircraftLock.status == ACTIVE))
    return {
        "id": row.id, "mode": row.mode, "status": row.status,
        "aircraft": aircraft_dict(aircraft, type_row) if aircraft else None,
        "legs": flights, "expires_at": iso(row.expires_at),
        "lock": lock_dict(lock) if lock else None,
        "created_at": iso(row.created_at), "updated_at": iso(row.updated_at),
    }


def lock_dict(row: AircraftLock) -> dict[str, Any]:
    return {"id": row.id, "aircraft_id": row.aircraft_id, "user_id": row.user_id,
            "roster_id": row.roster_id, "kind": row.kind, "status": row.status,
            "heartbeat_at": iso(row.heartbeat_at), "expires_at": iso(row.expires_at),
            "created_at": iso(row.created_at)}


def settlement_dict(row: Settlement) -> dict[str, Any]:
    return {
        "id": row.id, "flight_id": row.flight_id, "user_id": row.user_id,
        "status": row.status, "action": row.action, "factor": row.factor,
        "revenue_gross": row.revenue_gross, "cost_total": row.cost_total, "profit": row.profit,
        "revenue_items": row.revenue_items_json or [],
        "cost_items": row.cost_items_json or [],
        "anomalies": row.anomalies_json or [], "on_time_note": row.on_time_note,
        "advance_amount": row.advance_amount, "reviewed_by": row.reviewed_by,
        "reviewed_at": iso(row.reviewed_at), "review_reason": row.review_reason,
        "created_at": iso(row.created_at),
    }


def ledger_dict(row: LedgerEntry) -> dict[str, Any]:
    return {"id": row.id, "flight_id": row.flight_id, "settlement_id": row.settlement_id,
            "entry_type": row.entry_type, "direction": row.direction, "amount": row.amount,
            "balance_after": row.balance_after, "note": row.note,
            "created_at": iso(row.created_at)}


# ---------------------------------------------------------------- 初始化
def seed_airports(db: Session) -> None:
    existing = {row for row in db.scalars(select(Airport.ident)).all()}
    for ident, name, lat, lon, elev, country, size, demand, tier in AIRPORTS:
        if ident in existing:
            continue
        db.add(Airport(ident=ident, name=name, lat=lat, lon=lon, elevation_ft=elev,
                       country=country, size_class=size, demand=demand, tier=tier))
    db.flush()


def seed_types(db: Session, company_id: str) -> None:
    catalog_path = repo_root() / "data" / "aircraft_types.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        catalog = []
    for item in build_aircraft_types(catalog):
        exists = db.scalar(select(AircraftType.id).where(
            AircraftType.company_id == company_id, AircraftType.icao == item["icao"],
            AircraftType.variant == item["variant"]))
        if exists:
            continue
        db.add(AircraftType(
            company_id=company_id, icao=item["icao"], variant=item["variant"],
            name=item["name"], manufacturer=item.get("manufacturer"),
            role=item.get("role", "AIRLINER"), demand_profile=item.get("demand_profile", "MASS"),
            cabin_config_json=item.get("cabin_config_json") or {},
            pax_capacity=int(item.get("pax_capacity") or 0),
            cargo_capacity_kg=float(item.get("cargo_capacity_kg") or 0),
            oew_kg=float(item.get("oew_kg") or 0), mtow_kg=float(item.get("mtow_kg") or 0),
            mzfw_kg=float(item.get("mzfw_kg") or 0), mlw_kg=float(item.get("mlw_kg") or 0),
            fuel_capacity_kg=float(item.get("fuel_capacity_kg") or 0),
            fuel_burn_kg_h=float(item.get("fuel_burn_kg_h") or 2400),
            cruise_speed_kt=float(item.get("cruise_speed_kt") or 440),
            cruise_fl=float(item.get("cruise_fl") or 350),
            min_runway_m=float(item.get("min_runway_m") or 1600),
            range_nm=float(item.get("range_nm") or 3000),
            lease_per_hour=float(item.get("lease_per_hour") or 2000),
            charter_rate_per_hour=float(item.get("charter_rate_per_hour") or 0),
            allow_scheduled=bool(item.get("allow_scheduled", True)),
            allow_charter=bool(item.get("allow_charter", True)),
            fare_multiplier=float(item.get("fare_multiplier") or 1.0),
        ))
    db.flush()


def seed_demo(db: Session, company: Company) -> None:
    """演示数据：3 架飞机 + 4 条航线 + 班期 + 未来 7 天航班。"""
    if db.scalar(select(Aircraft.id).where(Aircraft.company_id == company.id).limit(1)):
        return
    types = {t.icao: t for t in db.scalars(
        select(AircraftType).where(AircraftType.company_id == company.id)).all()}
    fleet = [("B-1001", "A320"), ("B-1002", "B738"), ("B-1003", "A333")]
    for registration, icao in fleet:
        type_row = types.get(icao)
        if not type_row:
            continue
        db.add(Aircraft(company_id=company.id, registration=registration, type_id=type_row.id,
                        base_icao=company.base_icao, current_icao=company.base_icao,
                        status=ACTIVE, acquisition="LEASE", fuel_kg=type_row.fuel_capacity_kg * 0.5))
    db.flush()
    routes = [("ZBAA", "ZSSS"), ("ZSSS", "ZSPD"), ("ZBAA", "ZUUU"), ("ZSPD", "RJTT")]
    for dep, arr in routes:
        _ensure_route(db, company, dep, arr)
    aircraft = db.scalars(select(Aircraft).where(Aircraft.company_id == company.id)
                          .order_by(Aircraft.registration)).all()
    schedules = [("AOC101", "ZBAA", "ZSSS", "08:00", aircraft[0] if aircraft else None),
                 ("AOC102", "ZSSS", "ZSPD", "13:00", aircraft[0] if aircraft else None),
                 ("AOC201", "ZBAA", "ZUUU", "09:30", aircraft[1] if len(aircraft) > 1 else None),
                 ("AOC301", "ZSPD", "RJTT", "16:00", aircraft[2] if len(aircraft) > 2 else None)]
    for number, dep, arr, hhmm, plane in schedules:
        route = db.scalar(select(NetworkRoute).where(
            NetworkRoute.company_id == company.id, NetworkRoute.dep_icao == dep,
            NetworkRoute.arr_icao == arr))
        if not route:
            continue
        db.add(ScheduleTemplate(
            company_id=company.id, flight_number=number, route_id=route.id, dep_local=hhmm,
            days_of_week=[0, 1, 2, 3, 4, 5, 6], aircraft_type_id=plane.type_id if plane else None,
            turn_minutes=45, active=True))
    db.flush()
    generate_flights(db, company, days=7)


def _ensure_route(db: Session, company: Company, dep: str, arr: str) -> NetworkRoute:
    route = db.scalar(select(NetworkRoute).where(
        NetworkRoute.company_id == company.id, NetworkRoute.dep_icao == dep,
        NetworkRoute.arr_icao == arr))
    if route:
        return route
    dep_row = airport_by_ident(db, dep)
    arr_row = airport_by_ident(db, arr)
    distance = round(econ.gcd_nm(airport_dict(dep_row) if dep_row else None,
                                 airport_dict(arr_row) if arr_row else None), 1)
    speed = 440.0
    block = econ.estimate_block_minutes(distance, speed)
    route = NetworkRoute(company_id=company.id, dep_icao=dep, arr_icao=arr,
                         distance_nm=distance, block_minutes=block, active=True)
    db.add(route)
    db.flush()
    return route


def airport_by_ident(db: Session, ident: str) -> Airport | None:
    return db.scalar(select(Airport).where(Airport.ident == (ident or "").upper()))


def ensure_company_defaults(db: Session, company: Company, *, seed_types_flag: bool = True) -> None:
    seed_airports(db)
    if seed_types_flag:
        seed_types(db, company.id)
    store.ensure_setting(db, company.id, store.ECONOMY, default_economy())
    store.ensure_setting(db, company.id, store.POLICY, default_policy())
    db.flush()


# ---------------------------------------------------------------- 班期与航班实例
def generate_flights(db: Session, company: Company, *, days: int = 7,
                     start: date | None = None) -> dict[str, Any]:
    days = max(1, min(int(days or 7), 60))
    start = start or (utcnow().date() - timedelta(days=1))
    schedules = db.scalars(select(ScheduleTemplate).where(
        ScheduleTemplate.company_id == company.id, ScheduleTemplate.active.is_(True))).all()
    created = 0
    skipped = 0
    for offset in range(days + 1):
        day = start + timedelta(days=offset)
        for schedule in schedules:
            route = db.get(NetworkRoute, schedule.route_id)
            if not route or not route.active:
                continue
            weekdays = schedule.days_of_week or list(range(7))
            if day.weekday() not in {int(d) for d in weekdays}:
                continue
            if schedule.valid_from and day < schedule.valid_from:
                continue
            if schedule.valid_to and day > schedule.valid_to:
                continue
            dep_iso = econ.local_to_utc(datetime(day.year, day.month, day.day),
                                        schedule.dep_local, route.dep_icao)
            dep = econ.parse_utc(dep_iso)
            exists = db.scalar(select(FlightInstance.id).where(
                FlightInstance.company_id == company.id,
                FlightInstance.flight_number == schedule.flight_number,
                FlightInstance.scheduled_dep_utc == dep))
            if exists:
                skipped += 1
                continue
            arr = dep + timedelta(minutes=route.block_minutes or 60)
            db.add(FlightInstance(
                company_id=company.id, schedule_id=schedule.id,
                flight_number=schedule.flight_number, dep_icao=route.dep_icao,
                arr_icao=route.arr_icao, scheduled_dep_utc=dep, scheduled_arr_utc=arr,
                distance_nm=route.distance_nm, block_minutes=route.block_minutes,
                status=SCHEDULED, route_string=route.default_route))
            created += 1
    db.flush()
    return {"created": created, "skipped": skipped, "days": days}


# ---------------------------------------------------------------- 抽班
def _release_expired_locks(db: Session, company_id: str) -> int:
    now = utcnow()
    locks = db.scalars(select(AircraftLock).where(
        AircraftLock.company_id == company_id, AircraftLock.status == ACTIVE,
        AircraftLock.expires_at < now)).all()
    for lock in locks:
        lock.status = "EXPIRED"
        lock.released_at = now
        roster = db.get(Roster, lock.roster_id) if lock.roster_id else None
        if roster and roster.status == ACTIVE:
            roster.status = "EXPIRED"
            for leg in db.scalars(select(RosterLeg).where(RosterLeg.roster_id == roster.id)).all():
                if leg.status == HELD:
                    leg.status = "EXPIRED"
                    flight = db.get(FlightInstance, leg.flight_id)
                    if flight and flight.status == HELD and flight.roster_id == roster.id:
                        flight.status = SCHEDULED
                        flight.aircraft_id = None
                        flight.pilot_id = None
                        flight.roster_id = None
    if locks:
        db.flush()
    return len(locks)


def _pick_aircraft(db: Session, company: Company, requested_id: str | None,
                   dep_icao: str | None) -> Aircraft:
    query = select(Aircraft).where(Aircraft.company_id == company.id,
                                   Aircraft.status == ACTIVE)
    if requested_id:
        query = query.where(Aircraft.id == requested_id)
    elif dep_icao:
        query = query.where(Aircraft.current_icao == dep_icao.upper())
    if db.bind and db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    rows = db.scalars(query.order_by(Aircraft.registration)).all()
    if not rows:
        raise conflict("NO_AIRCRAFT", "没有满足条件的可用飞机")
    for row in rows:
        locked = db.scalar(select(AircraftLock.id).where(
            AircraftLock.company_id == company.id, AircraftLock.aircraft_id == row.id,
            AircraftLock.status == ACTIVE))
        if not locked:
            return row
    raise conflict("AIRCRAFT_LOCKED", "可用飞机都已被占用")


def draw_roster(db: Session, company: Company, user: AppUser, body: dict[str, Any]) -> dict[str, Any]:
    _release_expired_locks(db, company.id)
    active = db.scalar(select(Roster).where(Roster.company_id == company.id,
                                            Roster.user_id == user.id,
                                            Roster.status == ACTIVE))
    if active:
        raise conflict("ROSTER_ACTIVE", "已有进行中的任务，请先完成或取消")
    mode = str(body.get("mode") or "SCHEDULED").upper()
    max_legs = max(1, min(int(body.get("max_legs") or 3), 6))
    now = utcnow()
    flight_ids = [str(x) for x in (body.get("flight_ids") or [])]

    if mode == "FREE":
        dep = str(body.get("dep_icao") or "").upper()
        arr = str(body.get("arr_icao") or "").upper()
        if not dep or not arr:
            raise bad_request("DEP_ARR_REQUIRED", "自由飞需要起降机场")
        aircraft = _pick_aircraft(db, company, body.get("aircraft_id"), dep)
        dep_row, arr_row = airport_by_ident(db, dep), airport_by_ident(db, arr)
        if not dep_row or not arr_row:
            raise bad_request("AIRPORT_UNKNOWN", "起降机场不在机场库中")
        distance = round(econ.gcd_nm(airport_dict(dep_row), airport_dict(arr_row)), 1)
        type_row = db.get(AircraftType, aircraft.type_id)
        block = econ.estimate_block_minutes(distance, type_row.cruise_speed_kt if type_row else 440)
        flight = FlightInstance(
            company_id=company.id, flight_number=f"FREE{now.strftime('%H%M%S')}",
            dep_icao=dep, arr_icao=arr, scheduled_dep_utc=now,
            scheduled_arr_utc=now + timedelta(minutes=block), distance_nm=distance,
            block_minutes=block, status=HELD, aircraft_id=aircraft.id, pilot_id=user.id)
        db.add(flight)
        db.flush()
        flights = [flight]
    else:
        if flight_ids:
            rows = db.scalars(select(FlightInstance).where(
                FlightInstance.company_id == company.id,
                FlightInstance.id.in_(flight_ids))).all()
            by_id = {row.id: row for row in rows}
            flights = [by_id[i] for i in flight_ids if i in by_id]
            if len(flights) != len(flight_ids):
                raise not_found("FLIGHT_NOT_FOUND", "部分航班不存在")
        else:
            dep = str(body.get("dep_icao") or "").upper()
            query = select(FlightInstance).where(
                FlightInstance.company_id == company.id,
                FlightInstance.status == SCHEDULED,
                FlightInstance.scheduled_dep_utc >= now - timedelta(minutes=30),
                FlightInstance.scheduled_dep_utc <= now + timedelta(hours=24))
            if dep:
                query = query.where(FlightInstance.dep_icao == dep)
            flights = db.scalars(query.order_by(FlightInstance.scheduled_dep_utc)
                                 .limit(max_legs * 4)).all()
            if not flights and not dep:
                flights = db.scalars(select(FlightInstance).where(
                    FlightInstance.company_id == company.id,
                    FlightInstance.status == SCHEDULED)
                    .order_by(FlightInstance.scheduled_dep_utc).limit(max_legs * 4)).all()
            if not flights:
                raise conflict("NO_FLIGHTS", "未来 24 小时没有可抽取的航班")
            aircraft_pos = str(body.get("dep_icao") or flights[0].dep_icao).upper()
            chain: list[FlightInstance] = []
            cursor = aircraft_pos
            for flight in flights:
                if flight.dep_icao != cursor:
                    continue
                chain.append(flight)
                cursor = flight.arr_icao
                if len(chain) >= max_legs:
                    break
            flights = chain or [flights[0]]

        for flight in flights:
            if flight.status != SCHEDULED:
                raise conflict("FLIGHT_TAKEN", f"{flight.flight_number} 已被抽取")
        aircraft = _pick_aircraft(db, company, body.get("aircraft_id"), flights[0].dep_icao)
        if flights[0].dep_icao != aircraft.current_icao:
            raise conflict("AIRCRAFT_POSITION",
                           f"{aircraft.registration} 当前在 {aircraft.current_icao}，无法执行 {flights[0].dep_icao} 出发的航班")
        type_row = db.get(AircraftType, aircraft.type_id)
        if type_row and not type_row.allow_scheduled and mode != "FREE":
            raise conflict("TYPE_NOT_SCHEDULED", f"{type_row.icao} 不允许执行定期航班")
        for idx, flight in enumerate(flights):
            flight.status = HELD
            flight.aircraft_id = aircraft.id
            flight.pilot_id = user.id
            flight.version += 1
            if idx == 0:
                flight.roster_id = None

    expires = now + timedelta(minutes=LOCK_MINUTES)
    roster = Roster(company_id=company.id, user_id=user.id, aircraft_id=aircraft.id,
                    mode=mode, status=ACTIVE, expires_at=expires)
    db.add(roster)
    db.flush()
    lock = AircraftLock(company_id=company.id, aircraft_id=aircraft.id, user_id=user.id,
                        roster_id=roster.id, kind="FREE" if mode == "FREE" else "SCHEDULED",
                        status=ACTIVE, heartbeat_at=now, expires_at=expires)
    db.add(lock)
    for index, flight in enumerate(flights, start=1):
        flight.roster_id = roster.id
        db.add(RosterLeg(roster_id=roster.id, flight_id=flight.id, sequence=index,
                         status=HELD))
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise conflict("AIRCRAFT_LOCKED", "该飞机已被其他机组占用") from exc
    store.emit(db, company.id, "ROSTER_DRAWN", entity="roster", entity_id=roster.id,
               payload={"roster_id": roster.id, "aircraft_id": aircraft.id},
               user_id=user.id)
    store.audit(db, company_id=company.id, actor=user, action="ROSTER_DRAW",
                entity="roster", entity_id=roster.id,
                after={"flight_ids": [f.id for f in flights], "aircraft_id": aircraft.id},
                request_id=body.get("request_id"))
    return roster_dict(db, roster)


def current_roster(db: Session, company: Company, user: AppUser) -> dict[str, Any] | None:
    _release_expired_locks(db, company.id)
    roster = db.scalar(select(Roster).where(Roster.company_id == company.id,
                                            Roster.user_id == user.id,
                                            Roster.status == ACTIVE)
                       .order_by(Roster.created_at.desc()))
    return roster_dict(db, roster) if roster else None


def roster_by_id(db: Session, company: Company, roster_id: str) -> Roster:
    roster = db.get(Roster, roster_id)
    if not roster or roster.company_id != company.id:
        raise not_found("ROSTER_NOT_FOUND", "任务不存在")
    return roster


# ---------------------------------------------------------------- 配载/开始
def snapshot_for(db: Session, company: Company, flight: FlightInstance) -> EconomySnapshot:
    row = db.scalar(select(EconomySnapshot).where(EconomySnapshot.flight_id == flight.id))
    if row:
        return row
    _, economy_payload = store.setting_payload(db, company.id, store.ECONOMY)
    _, policy_payload = store.setting_payload(db, company.id, store.POLICY)
    row = EconomySnapshot(company_id=company.id, flight_id=flight.id,
                          economy_json=economy_payload, policy_json=policy_payload,
                          environment_json={"pinned_at": iso(utcnow())})
    db.add(row)
    db.flush()
    return row


def _owned_flight(db: Session, company: Company, user: AppUser, flight_id: str) -> FlightInstance:
    flight = db.get(FlightInstance, flight_id)
    if not flight or flight.company_id != company.id:
        raise not_found("FLIGHT_NOT_FOUND", "航班不存在")
    if flight.pilot_id != user.id:
        raise forbidden("NOT_YOUR_FLIGHT", "该航班不属于当前账号")
    return flight


def start_flight(db: Session, company: Company, user: AppUser, flight_id: str,
                 body: dict[str, Any] | None = None) -> dict[str, Any]:
    flight = _owned_flight(db, company, user, flight_id)
    if flight.status == IN_FLIGHT:
        return {"flight": flight_dict(flight), "already_started": True}
    if flight.status != HELD:
        raise conflict("FLIGHT_NOT_HELD", "航班当前不可开始")
    snapshot = snapshot_for(db, company, flight)
    flight.status = IN_FLIGHT
    flight.version += 1
    roster = db.get(Roster, flight.roster_id) if flight.roster_id else None
    if roster:
        leg = db.scalar(select(RosterLeg).where(RosterLeg.roster_id == roster.id,
                                                RosterLeg.flight_id == flight.id))
        if leg:
            leg.status = IN_FLIGHT
        roster.expires_at = utcnow() + timedelta(hours=6)
    lock = db.scalar(select(AircraftLock).where(AircraftLock.company_id == company.id,
                                                AircraftLock.aircraft_id == flight.aircraft_id,
                                                AircraftLock.status == ACTIVE))
    if lock:
        lock.kind = "IN_FLIGHT"
        lock.heartbeat_at = utcnow()
        lock.expires_at = utcnow() + timedelta(hours=6)
    store.emit(db, company.id, "FLIGHT_STARTED", entity="flight", entity_id=flight.id,
               payload={"flight": flight_dict(flight), "economy_version": snapshot.id},
               user_id=user.id)
    db.flush()
    return {"flight": flight_dict(flight), "snapshot_id": snapshot.id}


def generate_loadsheet(db: Session, company: Company, user: AppUser,
                       flight_id: str) -> dict[str, Any]:
    flight = _owned_flight(db, company, user, flight_id)
    if flight.status not in {HELD, IN_FLIGHT}:
        raise conflict("FLIGHT_NOT_ACTIVE", "航班未处于可配载状态")
    existing = db.scalar(select(LoadSheet).where(LoadSheet.flight_id == flight.id))
    if existing:
        return existing.payload_json
    snapshot = snapshot_for(db, company, flight)
    aircraft = db.get(Aircraft, flight.aircraft_id) if flight.aircraft_id else None
    type_row = db.get(AircraftType, aircraft.type_id) if aircraft else None
    if not aircraft or not type_row:
        raise conflict("AIRCRAFT_MISSING", "航班没有可用飞机")
    payload = econ.generate_load_sheet(
        dep=flight.dep_icao, arr=flight.arr_icao, distance_nm=flight.distance_nm,
        block_minutes=flight.block_minutes,
        aircraft_type=type_dict(type_row), params=snapshot.economy_json,
        seed=f"{flight.id}:{user.id}", dep_time_utc=iso(flight.scheduled_dep_utc),
        dep_meta=_meta(db, flight.dep_icao), arr_meta=_meta(db, flight.arr_icao),
    )
    row = LoadSheet(company_id=company.id, flight_id=flight.id, payload_json=payload)
    db.add(row)
    db.flush()
    store.emit(db, company.id, "LOADSHEET_READY", entity="flight", entity_id=flight.id,
               payload={"flight_id": flight.id}, user_id=user.id)
    return payload


def effective_policy(policy: dict[str, Any], *, aircraft_type: dict[str, Any],
                     aircraft: dict[str, Any], user: AppUser) -> tuple[dict[str, Any], dict[str, str]]:
    """公司 → 机型 → 单机（aoc_core）→ 飞行员（M3 新增，最高优先级）。"""
    effective, sources = policy_mod.resolve_policy(
        policy, aircraft_type=aircraft_type, aircraft=aircraft)
    if str(policy.get("scope_mode") or "COMPANY_ONLY").upper() != "ALLOW_OVERRIDES":
        return effective, sources
    keys = {user.id.upper(), user.username.upper()}
    for item in policy.get("overrides") or []:
        if str(item.get("scope_type") or "").upper() != "PILOT":
            continue
        if str(item.get("scope_id") or "").upper() not in keys:
            continue
        patch = item.get("policy") or {}
        effective = policy_mod._deep_merge(effective, patch)  # noqa: SLF001 - 与 M2 合并语义保持一致
        for key, value in patch.items():
            if key == "rules" and isinstance(value, dict):
                for rule in value:
                    sources[f"rules.{rule}"] = "PILOT"
            else:
                sources[key] = "PILOT"
    return effective, sources


def _meta(db: Session, ident: str) -> dict[str, Any]:
    row = airport_by_ident(db, ident)
    if not row:
        return {"demand": 90, "tier": 1.0, "size_class": "medium", "business_ratio": 0.06}
    return {"demand": row.demand, "tier": row.tier, "size_class": row.size_class,
            "business_ratio": 0.06}


def heartbeat(db: Session, company: Company, user: AppUser, lock_id: str) -> dict[str, Any]:
    lock = db.get(AircraftLock, lock_id)
    if not lock or lock.company_id != company.id or lock.user_id != user.id:
        raise not_found("LOCK_NOT_FOUND", "锁不存在")
    if lock.status != ACTIVE:
        raise conflict("LOCK_CLOSED", "锁已释放或过期")
    lock.heartbeat_at = utcnow()
    lock.expires_at = utcnow() + timedelta(hours=6 if lock.kind == "IN_FLIGHT" else 1)
    db.flush()
    return lock_dict(lock)


# ---------------------------------------------------------------- 轨迹
def upload_track(db: Session, company: Company, user: AppUser, flight_id: str,
                 chunks: list[dict[str, Any]]) -> dict[str, Any]:
    flight = _owned_flight(db, company, user, flight_id)
    saved = 0
    duplicates = 0
    for chunk in chunks:
        seq = int(chunk.get("seq") or 0)
        existing = db.scalar(select(TrackChunk).where(TrackChunk.flight_id == flight.id,
                                                      TrackChunk.seq == seq))
        if existing:
            duplicates += 1
            continue
        points = chunk.get("points") or []
        db.add(TrackChunk(company_id=company.id, flight_id=flight.id, seq=seq,
                          points_json=points,
                          started_at=_dt(chunk.get("started_at")),
                          ended_at=_dt(chunk.get("ended_at"))))
        saved += 1
    db.flush()
    total = db.scalar(select(TrackChunk.id).where(TrackChunk.flight_id == flight.id)
                      .order_by(TrackChunk.seq.desc()).limit(1))
    store.emit(db, company.id, "TRACK_UPLOADED", entity="flight", entity_id=flight.id,
               payload={"saved": saved, "duplicates": duplicates}, user_id=user.id)
    return {"saved": saved, "duplicates": duplicates, "has_track": bool(total)}


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return econ.parse_utc(str(value))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- 落地与结算
def land_flight(db: Session, company: Company, user: AppUser, flight_id: str,
                body: dict[str, Any]) -> dict[str, Any]:
    flight = _owned_flight(db, company, user, flight_id)
    existing = db.scalar(select(Settlement).where(Settlement.flight_id == flight.id))
    if existing:
        return {"settlement": settlement_dict(existing), "idempotent": True}
    if flight.status not in {IN_FLIGHT, HELD}:
        raise conflict("FLIGHT_NOT_ACTIVE", "航班不在执行中")
    snapshot = snapshot_for(db, company, flight)

    scheduled_dep = flight.scheduled_dep_utc
    actual_dep = _dt(body.get("actual_dep_utc")) or scheduled_dep
    actual_arr = _dt(body.get("actual_arr_utc")) or utcnow()
    if actual_arr < actual_dep:
        actual_arr = actual_dep + timedelta(minutes=flight.block_minutes or 60)
    block_minutes = max(1.0, (actual_arr - actual_dep).total_seconds() / 60.0)
    aircraft = db.get(Aircraft, flight.aircraft_id) if flight.aircraft_id else None
    type_row = db.get(AircraftType, aircraft.type_id) if aircraft else None
    if not aircraft or not type_row:
        raise conflict("AIRCRAFT_MISSING", "航班没有可用飞机")
    loadsheet = db.scalar(select(LoadSheet).where(LoadSheet.flight_id == flight.id))
    if not loadsheet:
        generate_loadsheet(db, company, user, flight.id)
        loadsheet = db.scalar(select(LoadSheet).where(LoadSheet.flight_id == flight.id))

    fuel_used = float(body.get("fuel_used_kg") or
                      (type_row.fuel_burn_kg_h or 2400) * block_minutes / 60.0)
    events = body.get("events") or []
    flags = body.get("anomaly_flags") or []
    anomaly_input = {
        "anomaly_flags": flags,
        "data_gap_seconds": body.get("data_gap_seconds") or 0,
    }
    anomalies = policy_mod.detect_anomalies(anomaly_input, events)
    effective, policy_sources = effective_policy(
        snapshot.policy_json, aircraft_type=type_dict(type_row),
        aircraft=aircraft_dict(aircraft), user=user)
    evaluation = policy_mod.evaluate(effective, anomalies)
    action = str(evaluation.get("action") or "ACCEPT").upper()

    amounts = econ.settle_amounts(
        params=snapshot.economy_json, aircraft=aircraft_dict(aircraft),
        aircraft_type=type_dict(type_row), load_sheet=loadsheet.payload_json,
        distance_nm=flight.distance_nm,
        block_minutes=block_minutes, fuel_used_kg=fuel_used,
        scheduled_dep_utc=iso(scheduled_dep), actual_dep_utc=iso(actual_dep),
        arr=flight.arr_icao, arr_time_utc=iso(actual_arr))

    record = FlightRecord(
        company_id=company.id, flight_id=flight.id, user_id=user.id, aircraft_id=aircraft.id,
        actual_dep_utc=actual_dep, actual_arr_utc=actual_arr, block_minutes=round(block_minutes, 1),
        distance_nm=flight.distance_nm, fuel_used_kg=round(fuel_used, 1),
        landing_json=body.get("landing") or {}, anomaly_json=anomalies)
    db.add(record)

    settlement = Settlement(
        company_id=company.id, flight_id=flight.id, user_id=user.id,
        status="HELD" if action == "REVIEW" else SETTLED,
        action=action, factor=float(evaluation.get("payout_factor") or 0.0),
        revenue_gross=float(amounts["revenue_gross"]), cost_total=float(amounts["cost_total"]),
        profit=float(amounts["profit"]), revenue_items_json=amounts["revenue_items"],
        cost_items_json=amounts["cost_items"], policy_json=effective,
        anomalies_json=evaluation.get("breakdown") or [],
        on_time_note=amounts.get("on_time_note"))
    db.add(settlement)
    db.flush()

    if action == "REVIEW":
        ratio = float(effective.get("review_advance_ratio") or 0.0)
        if ratio > 0 and amounts["revenue_gross"] > 0:
            settlement.advance_amount = round(amounts["revenue_gross"] * ratio, 2)
            _write_advance(db, company, settlement, flight, user, settlement.advance_amount)
        store.emit(db, company.id, "SETTLEMENT_HELD", entity="settlement",
                   entity_id=settlement.id, payload={"flight_id": flight.id}, user_id=user.id)
    else:
        cost_mode = str(effective.get("reject_cost_mode") or "FULL").upper()
        _finalize_settlement(db, company, settlement, flight, float(evaluation.get("payout_factor") or 0.0),
                             action, cost_mode, policy_sources)
        store.emit(db, company.id, "SETTLEMENT_READY", entity="settlement",
                   entity_id=settlement.id, payload={"flight_id": flight.id}, user_id=user.id)

    _complete_flight(db, flight, aircraft, actual_arr)
    store.audit(db, company_id=company.id, actor=user, action="FLIGHT_LANDED",
                entity="flight", entity_id=flight.id,
                after={"settlement_id": settlement.id, "action": action})
    db.flush()
    flight_out = flight_dict(flight, aircraft=aircraft)
    return {"settlement": settlement_dict(settlement), "flight": flight_out,
            "record_id": record.id, "economy_version": snapshot.id}


def _write_advance(db: Session, company: Company, settlement: Settlement,
                   flight: FlightInstance, user: AppUser, amount: float) -> None:
    balance = company.balance
    balance += amount
    company.balance = balance
    db.add(LedgerEntry(company_id=company.id, flight_id=flight.id,
                       settlement_id=settlement.id, user_id=user.id,
                       entry_type="ADVANCE", direction="CREDIT", amount=round(amount, 2),
                       balance_after=round(balance, 2), note="复核预付款"))


def _finalize_settlement(db: Session, company: Company, settlement: Settlement,
                         flight: FlightInstance, factor: float, action: str,
                         cost_mode: str, policy_sources: dict[str, str] | None = None) -> None:
    factor = max(0.0, min(1.0, float(factor)))
    revenue_items = settlement.revenue_items_json or []
    cost_items = settlement.cost_items_json or []
    revenue_total = round(sum(float(i.get("amount") or 0) for i in revenue_items) * factor, 2)
    allowed_costs = [i for i in cost_items
                     if policy_mod.cost_item_allowed(cost_mode, str(i.get("type") or ""))]
    cost_total = round(sum(float(i.get("amount") or 0) for i in allowed_costs), 2)
    profit = round(revenue_total - cost_total, 2)
    is_void = action == "REJECT" and str(cost_mode).upper() == "NONE"

    settlement.factor = factor
    settlement.action = action
    settlement.revenue_gross = revenue_total
    settlement.cost_total = cost_total
    settlement.profit = 0.0 if is_void else profit
    settlement.status = VOID if is_void else SETTLED

    if is_void:
        if settlement.advance_amount:
            _recoup_advance(db, company, settlement, flight)
        return

    balance = company.balance
    if settlement.advance_amount:
        balance = _recoup_advance(db, company, settlement, flight, balance)
    entries: list[tuple[str, str, float, str]] = []
    for item in revenue_items:
        amount = round(float(item.get("amount") or 0) * factor, 2)
        if amount:
            entries.append((str(item.get("type") or "REVENUE"), "CREDIT", amount,
                            str(item.get("note") or "")))
    for item in allowed_costs:
        amount = round(float(item.get("amount") or 0), 2)
        if amount:
            entries.append((str(item.get("type") or "COST"), "DEBIT", amount,
                            str(item.get("note") or "")))
    for entry_type, direction, amount, note in entries:
        balance += amount if direction == "CREDIT" else -amount
        db.add(LedgerEntry(company_id=company.id, flight_id=flight.id,
                           settlement_id=settlement.id, user_id=settlement.user_id,
                           entry_type=entry_type, direction=direction, amount=amount,
                           balance_after=round(balance, 2), note=note[:255]))
    company.balance = round(balance, 2)


def _recoup_advance(db: Session, company: Company, settlement: Settlement,
                    flight: FlightInstance, balance: float | None = None) -> float:
    current = company.balance if balance is None else balance
    amount = float(settlement.advance_amount or 0)
    if amount <= 0:
        return current
    current -= amount
    company.balance = round(current, 2)
    db.add(LedgerEntry(company_id=company.id, flight_id=flight.id,
                       settlement_id=settlement.id, user_id=settlement.user_id,
                       entry_type="ADVANCE_RECOUP", direction="DEBIT", amount=round(amount, 2),
                       balance_after=round(current, 2), note="复核完成后冲回预付款"))
    return current


def _complete_flight(db: Session, flight: FlightInstance, aircraft: Aircraft,
                     actual_arr: datetime) -> None:
    flight.status = COMPLETED
    flight.version += 1
    aircraft.current_icao = flight.arr_icao
    aircraft.total_hours = round(aircraft.total_hours + max(0.1, flight.block_minutes / 60.0), 2)
    aircraft.total_cycles += 1
    roster = db.get(Roster, flight.roster_id) if flight.roster_id else None
    if roster:
        leg = db.scalar(select(RosterLeg).where(RosterLeg.roster_id == roster.id,
                                                RosterLeg.flight_id == flight.id))
        if leg:
            leg.status = COMPLETED
            db.flush()
        remaining = db.scalars(select(RosterLeg).where(RosterLeg.roster_id == roster.id,
                                                       RosterLeg.status.in_([HELD, IN_FLIGHT]))).all()
        if not remaining:
            roster.status = COMPLETED
            lock = db.scalar(select(AircraftLock).where(AircraftLock.roster_id == roster.id,
                                                        AircraftLock.status == ACTIVE))
            if lock:
                lock.status = "RELEASED"
                lock.released_at = utcnow()
    db.flush()


def review_settlement(db: Session, company: Company, admin: AppUser, settlement_id: str,
                      body: dict[str, Any], *, ip: str | None = None,
                      request_id: str | None = None) -> dict[str, Any]:
    settlement = db.scalar(select(Settlement).where(Settlement.id == settlement_id)
                           .with_for_update())
    if not settlement or settlement.company_id != company.id:
        raise not_found("SETTLEMENT_NOT_FOUND", "结算不存在")
    if settlement.status != "HELD":
        raise conflict("SETTLEMENT_NOT_HELD", "该结算不在复核队列")
    action = str(body.get("action") or "").upper()
    if action not in {"ACCEPT", "WEIGHTED", "REJECT"}:
        raise bad_request("ACTION_INVALID", "复核动作必须是 ACCEPT/WEIGHTED/REJECT")
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise bad_request("REASON_REQUIRED", "复核必须填写原因")
    if action == "ACCEPT":
        factor = 1.0
    elif action == "REJECT":
        factor = 0.0
    else:
        try:
            factor = float(body.get("factor"))
        except (TypeError, ValueError) as exc:
            raise bad_request("FACTOR_REQUIRED", "WEIGHTED 必须提供 0–1 的 factor") from exc
        if not 0.0 <= factor <= 1.0:
            raise bad_request("FACTOR_RANGE", "factor 必须在 0–1")
    flight = db.get(FlightInstance, settlement.flight_id)
    if not flight:
        raise not_found("FLIGHT_NOT_FOUND", "航班不存在")
    cost_mode = str((settlement.policy_json or {}).get("reject_cost_mode") or "FULL").upper()
    before = settlement_dict(settlement)
    _finalize_settlement(db, company, settlement, flight, factor, action, cost_mode)
    settlement.reviewed_by = admin.id
    settlement.reviewed_at = utcnow()
    settlement.review_reason = reason
    store.audit(db, company_id=company.id, actor=admin, action="SETTLEMENT_REVIEW",
                entity="settlement", entity_id=settlement.id, before=before,
                after=settlement_dict(settlement), reason=reason, ip=ip,
                request_id=request_id)
    store.emit(db, company.id, "SETTLEMENT_REVIEWED", entity="settlement",
               entity_id=settlement.id, payload={"flight_id": flight.id},
               user_id=settlement.user_id)
    db.flush()
    return settlement_dict(settlement)


def abandon_flight(db: Session, company: Company, user: AppUser, flight_id: str,
                   reason: str | None = None) -> dict[str, Any]:
    flight = _owned_flight(db, company, user, flight_id)
    if flight.status == COMPLETED:
        raise conflict("FLIGHT_COMPLETED", "航班已完成，不能取消")
    before = flight_dict(flight)
    flight.status = ABANDONED
    flight.version += 1
    roster = db.get(Roster, flight.roster_id) if flight.roster_id else None
    if roster:
        leg = db.scalar(select(RosterLeg).where(RosterLeg.roster_id == roster.id,
                                                RosterLeg.flight_id == flight.id))
        if leg:
            leg.status = CANCELLED
            db.flush()
        remaining = db.scalars(select(RosterLeg).where(
            RosterLeg.roster_id == roster.id,
            RosterLeg.status.in_([HELD, IN_FLIGHT]))).all()
        if not remaining:
            roster.status = CANCELLED
            lock = db.scalar(select(AircraftLock).where(AircraftLock.roster_id == roster.id,
                                                        AircraftLock.status == ACTIVE))
            if lock:
                lock.status = "RELEASED"
                lock.released_at = utcnow()
    store.audit(db, company_id=company.id, actor=user, action="FLIGHT_ABANDONED",
                entity="flight", entity_id=flight.id, before=before,
                after={"status": ABANDONED}, reason=reason)
    store.emit(db, company.id, "FLIGHT_ABANDONED", entity="flight", entity_id=flight.id,
               payload={"reason": reason}, user_id=user.id)
    db.flush()
    return {"flight": flight_dict(flight)}


# ---------------------------------------------------------------- 配置预览/校验
def validate_config(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == store.ECONOMY:
        if not isinstance(payload, dict):
            raise bad_request("CONFIG_INVALID", "经济参数必须是对象")
        errors: dict[str, str] = {}
        for item in PARAM_SCHEMA:
            key = item["key"]
            if key not in payload:
                continue
            try:
                value = float(payload[key])
            except (TypeError, ValueError):
                errors[key] = "必须是数字"
                continue
            if value < float(item["min"]) or value > float(item["max"]):
                errors[key] = f"取值范围 {item['min']}–{item['max']}"
        if errors:
            raise bad_request("CONFIG_INVALID", "参数校验失败", {"fields": errors})
        return payload
    if kind == store.POLICY:
        scope = str(payload.get("scope_mode") or "COMPANY_ONLY").upper()
        if scope not in {"COMPANY_ONLY", "ALLOW_OVERRIDES"}:
            raise bad_request("CONFIG_INVALID", "scope_mode 只能是 COMPANY_ONLY/ALLOW_OVERRIDES")
        cost_mode = str(payload.get("reject_cost_mode") or "FULL").upper()
        if cost_mode not in {"FULL", "DIRECT_ONLY", "NONE"}:
            raise bad_request("CONFIG_INVALID", "reject_cost_mode 只能是 FULL/DIRECT_ONLY/NONE")
        ratio = float(payload.get("review_advance_ratio") or 0)
        if not 0 <= ratio <= 0.5:
            raise bad_request("CONFIG_INVALID", "review_advance_ratio 必须在 0–0.5")
        return payload
    raise bad_request("CONFIG_KIND_INVALID", "未知配置类型")


def preview_economy(payload: dict[str, Any], samples: int = 100) -> dict[str, Any]:
    validate_config(store.ECONOMY, payload)
    merged = {**default_economy(), **(payload or {})}
    return econ.synthetic_preview(merged, samples=max(10, min(int(samples or 100), 500)))


def preview_policy(payload: dict[str, Any], anomalies: list[dict[str, Any]]) -> dict[str, Any]:
    validate_config(store.POLICY, payload)
    merged = {**default_policy(), **(payload or {})}
    effective, sources = policy_mod.resolve_policy(merged)
    result = policy_mod.evaluate(effective, anomalies)
    return {"evaluation": result, "sources": sources, "effective": effective}
