"""M3 服务端数据模型：公司/账号/权限/机队/班表/抽班/结算/同步。"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (JSON, Boolean, Date, Float, ForeignKey, Index, Integer, String,
                        Text, UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime, utcnow


def new_id() -> str:
    return str(uuid.uuid4())


def _pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_id)


class TimestampsMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow,
                                                nullable=False)


# ---------------------------------------------------------------- 公司与账号
class Company(Base, TimestampsMixin):
    __tablename__ = "company"

    id: Mapped[str] = _pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    icao: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    callsign_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    base_icao: Mapped[str] = mapped_column(String(8), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    initial_balance: Mapped[float] = mapped_column(Float, default=5_000_000.0, nullable=False)
    balance: Mapped[float] = mapped_column(Float, default=5_000_000.0, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class AppUser(Base, TimestampsMixin):
    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("company_id", "username", name="uq_user_company_username"),)

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(16), default="PILOT", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class RefreshToken(Base):
    __tablename__ = "refresh_token"

    id: Mapped[str] = _pk()
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class WebSession(Base):
    __tablename__ = "web_session"

    id: Mapped[str] = _pk()
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class InviteCode(Base):
    __tablename__ = "invite_code"

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="PILOT", nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = _pk()
    company_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    actor_name: Mapped[str | None] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16), default="OK", nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False,
                                                 index=True)


# ---------------------------------------------------------------- 导航与机队
class Airport(Base):
    __tablename__ = "airport"

    id: Mapped[str] = _pk()
    ident: Mapped[str] = mapped_column(String(8), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    elevation_ft: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    country: Mapped[str | None] = mapped_column(String(8))
    size_class: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    demand: Mapped[float] = mapped_column(Float, default=90.0, nullable=False)
    tier: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)


class AircraftType(Base, TimestampsMixin):
    __tablename__ = "aircraft_type"
    __table_args__ = (UniqueConstraint("company_id", "icao", "variant", name="uq_type_company_icao_variant"),)

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    icao: Mapped[str] = mapped_column(String(8), nullable=False)
    variant: Mapped[str] = mapped_column(String(24), default="STANDARD", nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(16), default="AIRLINER", nullable=False)
    demand_profile: Mapped[str] = mapped_column(String(16), default="MASS", nullable=False)
    cabin_config_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    pax_capacity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cargo_capacity_kg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    oew_kg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    mtow_kg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    mzfw_kg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    mlw_kg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fuel_capacity_kg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fuel_burn_kg_h: Mapped[float] = mapped_column(Float, default=2400.0, nullable=False)
    cruise_speed_kt: Mapped[float] = mapped_column(Float, default=440.0, nullable=False)
    cruise_fl: Mapped[float] = mapped_column(Float, default=350.0, nullable=False)
    min_runway_m: Mapped[float] = mapped_column(Float, default=1600.0, nullable=False)
    range_nm: Mapped[float] = mapped_column(Float, default=3000.0, nullable=False)
    lease_per_hour: Mapped[float] = mapped_column(Float, default=2000.0, nullable=False)
    charter_rate_per_hour: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    allow_scheduled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_charter: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fare_multiplier: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Aircraft(Base, TimestampsMixin):
    __tablename__ = "aircraft"
    __table_args__ = (UniqueConstraint("company_id", "registration", name="uq_aircraft_registration"),)

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    registration: Mapped[str] = mapped_column(String(16), nullable=False)
    type_id: Mapped[str] = mapped_column(ForeignKey("aircraft_type.id"), nullable=False)
    base_icao: Mapped[str] = mapped_column(String(8), nullable=False)
    current_icao: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False)
    acquisition: Mapped[str] = mapped_column(String(16), default="LEASE", nullable=False)
    lease_per_hour: Mapped[float | None] = mapped_column(Float)
    total_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_cycles: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fuel_kg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    livery: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)


class AircraftLock(Base):
    __tablename__ = "aircraft_lock"
    __table_args__ = (
        Index("uq_aircraft_active_lock", "company_id", "aircraft_id", unique=True,
              sqlite_where=text("status = 'ACTIVE'"),
              postgresql_where=text("status = 'ACTIVE'")),
        Index("ix_aircraft_lock_company_status", "company_id", "status"),
    )

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False)
    aircraft_id: Mapped[str] = mapped_column(ForeignKey("aircraft.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), nullable=False, index=True)
    roster_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(16), default="SCHEDULED", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class Waypoint(Base, TimestampsMixin):
    __tablename__ = "waypoint"
    __table_args__ = (UniqueConstraint("company_id", "ident", name="uq_waypoint_company_ident"),)

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    ident: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="FIX", nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class CompanyRoute(Base, TimestampsMixin):
    __tablename__ = "company_route"
    __table_args__ = (UniqueConstraint("company_id", "dep_icao", "arr_icao", name="uq_company_route"),)

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    dep_icao: Mapped[str] = mapped_column(String(8), nullable=False)
    arr_icao: Mapped[str] = mapped_column(String(8), nullable=False)
    route_string: Mapped[str | None] = mapped_column(Text)
    sid: Mapped[str | None] = mapped_column(String(32))
    star: Mapped[str | None] = mapped_column(String(32))
    cruise_fl: Mapped[int] = mapped_column(Integer, default=350, nullable=False)
    min_type: Mapped[str | None] = mapped_column(String(16))
    distance_nm: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class NetworkRoute(Base, TimestampsMixin):
    __tablename__ = "network_route"
    __table_args__ = (UniqueConstraint("company_id", "dep_icao", "arr_icao", name="uq_network_route"),)

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    dep_icao: Mapped[str] = mapped_column(String(8), nullable=False)
    arr_icao: Mapped[str] = mapped_column(String(8), nullable=False)
    distance_nm: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    block_minutes: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    min_type: Mapped[str | None] = mapped_column(String(16))
    default_route: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ScheduleTemplate(Base, TimestampsMixin):
    __tablename__ = "schedule_template"

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    flight_number: Mapped[str] = mapped_column(String(16), nullable=False)
    route_id: Mapped[str] = mapped_column(ForeignKey("network_route.id"), nullable=False)
    dep_local: Mapped[str] = mapped_column(String(5), default="09:00", nullable=False)
    days_of_week: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    aircraft_type_id: Mapped[str | None] = mapped_column(String(36))
    turn_minutes: Mapped[int] = mapped_column(Integer, default=45, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class FlightInstance(Base, TimestampsMixin):
    __tablename__ = "flight_instance"
    __table_args__ = (
        UniqueConstraint("company_id", "flight_number", "scheduled_dep_utc", name="uq_flight_number_dep"),
        Index("ix_flight_company_status_dep", "company_id", "status", "scheduled_dep_utc"),
    )

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False)
    schedule_id: Mapped[str | None] = mapped_column(String(36))
    flight_number: Mapped[str] = mapped_column(String(16), nullable=False)
    dep_icao: Mapped[str] = mapped_column(String(8), nullable=False)
    arr_icao: Mapped[str] = mapped_column(String(8), nullable=False)
    scheduled_dep_utc: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    scheduled_arr_utc: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    distance_nm: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    block_minutes: Mapped[float] = mapped_column(Float, default=60.0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="SCHEDULED", nullable=False)
    aircraft_id: Mapped[str | None] = mapped_column(String(36), index=True)
    pilot_id: Mapped[str | None] = mapped_column(String(36), index=True)
    roster_id: Mapped[str | None] = mapped_column(String(36), index=True)
    route_string: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Roster(Base, TimestampsMixin):
    __tablename__ = "roster"
    __table_args__ = (
        Index("uq_roster_active_user", "company_id", "user_id", unique=True,
              sqlite_where=text("status = 'ACTIVE'"),
              postgresql_where=text("status = 'ACTIVE'")),
    )

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), nullable=False, index=True)
    aircraft_id: Mapped[str] = mapped_column(ForeignKey("aircraft.id"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="SCHEDULED", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class RosterLeg(Base):
    __tablename__ = "roster_leg"

    id: Mapped[str] = _pk()
    roster_id: Mapped[str] = mapped_column(ForeignKey("roster.id"), nullable=False, index=True)
    flight_id: Mapped[str] = mapped_column(ForeignKey("flight_instance.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="HELD", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


# ---------------------------------------------------------------- 飞行与结算
class FlightRecord(Base):
    __tablename__ = "flight_record"

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    flight_id: Mapped[str] = mapped_column(ForeignKey("flight_instance.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    aircraft_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actual_dep_utc: Mapped[datetime | None] = mapped_column(UTCDateTime)
    actual_arr_utc: Mapped[datetime | None] = mapped_column(UTCDateTime)
    block_minutes: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    distance_nm: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fuel_used_kg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    landing_json: Mapped[dict | None] = mapped_column(JSON)
    anomaly_json: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class TrackChunk(Base):
    __tablename__ = "track_chunk"
    __table_args__ = (UniqueConstraint("flight_id", "seq", name="uq_track_flight_seq"),)

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    flight_id: Mapped[str] = mapped_column(ForeignKey("flight_instance.id"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    points_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class LoadSheet(Base):
    __tablename__ = "load_sheet"

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    flight_id: Mapped[str] = mapped_column(ForeignKey("flight_instance.id"), unique=True,
                                           nullable=False, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class Settlement(Base):
    __tablename__ = "settlement"

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    flight_id: Mapped[str] = mapped_column(ForeignKey("flight_instance.id"), unique=True,
                                           nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="SETTLED", nullable=False)
    action: Mapped[str] = mapped_column(String(16), default="ACCEPT", nullable=False)
    factor: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    revenue_gross: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost_total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    profit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    revenue_items_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    cost_items_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    anomalies_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    on_time_note: Mapped[str | None] = mapped_column(String(120))
    advance_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    review_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class LedgerEntry(Base):
    __tablename__ = "ledger_entry"

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    flight_id: Mapped[str | None] = mapped_column(String(36), index=True)
    settlement_id: Mapped[str | None] = mapped_column(String(36), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    balance_after: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False,
                                                 index=True)


class CompanyConfigVersion(Base):
    __tablename__ = "company_config_version"
    __table_args__ = (UniqueConstraint("company_id", "kind", "version", name="uq_config_version"),)

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class CompanySetting(Base):
    __tablename__ = "company_setting"
    __table_args__ = (UniqueConstraint("company_id", "kind", name="uq_company_setting_kind"),)

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow,
                                                 nullable=False)


class CompanySettingHistory(Base):
    __tablename__ = "company_setting_history"

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    action: Mapped[str] = mapped_column(String(16), default="PUBLISH", nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class EconomySnapshot(Base):
    __tablename__ = "economy_snapshot"

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    flight_id: Mapped[str] = mapped_column(ForeignKey("flight_instance.id"), nullable=False, index=True)
    economy_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    policy_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    environment_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class SyncEvent(Base):
    __tablename__ = "sync_event"
    __table_args__ = (Index("ix_sync_company_id", "company_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    entity: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    payload_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_key"
    __table_args__ = (UniqueConstraint("company_id", "user_id", "key", name="uq_idempotency_user_key"),)

    id: Mapped[str] = _pk()
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    response_json: Mapped[dict | None] = mapped_column(JSON)
    status_code: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


JSONValue = dict[str, Any]
