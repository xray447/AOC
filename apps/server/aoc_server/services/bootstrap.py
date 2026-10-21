"""首次启动：建公司、管理员、机场/机型与默认配置（可重复执行）。"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import AppUser, Company
from ..security import ROLE_ADMIN, hash_password
from . import ops

log = logging.getLogger("aoc-server")

DEFAULT_PASSWORD = "aoc-admin-2026"


def bootstrap(db: Session, settings: Settings) -> dict[str, Any]:
    company = db.scalar(select(Company).order_by(Company.created_at).limit(1))
    created_company = False
    if not company:
        company = Company(
            name=settings.bootstrap_company, icao=settings.bootstrap_icao,
            callsign_prefix=settings.bootstrap_callsign, base_icao=settings.bootstrap_base,
            currency=settings.bootstrap_currency, initial_balance=5_000_000.0,
            balance=5_000_000.0, timezone="UTC",
        )
        db.add(company)
        db.flush()
        created_company = True
        log.info("已创建公司 %s (%s)", company.name, company.icao)

    ops.ensure_company_defaults(db, company, seed_types_flag=settings.seed_types)

    admin = db.scalar(select(AppUser).where(AppUser.company_id == company.id,
                                            AppUser.role == ROLE_ADMIN).limit(1))
    created_admin = False
    password_used: str | None = None
    if not admin:
        password_used = settings.bootstrap_password or DEFAULT_PASSWORD
        admin = AppUser(
            company_id=company.id, username=settings.bootstrap_admin,
            display_name="管理员", role=ROLE_ADMIN,
            password_hash=hash_password(password_used), active=True,
        )
        db.add(admin)
        db.flush()
        created_admin = True
        if not settings.bootstrap_password:
            log.warning("已创建默认管理员 %s / %s，请登录后立即修改密码",
                        settings.bootstrap_admin, DEFAULT_PASSWORD)
        else:
            log.info("已创建管理员 %s（密码来自 AOC_BOOTSTRAP_PASSWORD）", settings.bootstrap_admin)

    if settings.seed_demo:
        ops.seed_demo(db, company)

    db.flush()
    return {
        "company_id": company.id,
        "company_created": created_company,
        "admin_created": created_admin,
        "admin_username": admin.username if admin else None,
        "bootstrap_password": password_used,
    }
