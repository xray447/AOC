"""Alembic 环境：开发用 SQLite，部署用 PostgreSQL（AOC_DATABASE_URL）。"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
for pkg in (ROOT / "packages" / "aoc_core", HERE):
    if str(pkg) not in sys.path:
        sys.path.insert(0, str(pkg))

from aoc_server.config import Settings  # noqa: E402
from aoc_server.db import Base  # noqa: E402
from aoc_server import models  # noqa: E402,F401

config = context.config
if config.config_file_name and Path(config.config_file_name).is_file():
    try:
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    except Exception:  # noqa: BLE001 - 没有 logging 配置也能跑
        pass

url = config.get_main_option("sqlalchemy.url") or Settings.from_env().database_url
config.set_main_option("sqlalchemy.url", url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
