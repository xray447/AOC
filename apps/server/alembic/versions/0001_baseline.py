"""M3 基线：一次建立全部表（后续按需拆分为增量迁移）。

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-21
"""
from __future__ import annotations

from alembic import op

from aoc_server.db import Base
from aoc_server import models  # noqa: F401

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
