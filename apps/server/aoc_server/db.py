"""数据库连接与迁移入口。

- 开发/测试：SQLite（WAL + BEGIN IMMEDIATE，写事务串行化）
- 部署：PostgreSQL 16（`AOC_DATABASE_URL=postgresql+psycopg://...`）
- 表结构由 SQLAlchemy metadata 建立；`alembic/` 提供生产迁移脚本。
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Engine, TypeDecorator, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """统一按 UTC 存/取；SQLite 没有时区，取回时补 UTC。"""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        is_sqlite = url.startswith("sqlite")
        if is_sqlite:
            self._ensure_sqlite_dir(url)
        self.engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False, "timeout": 30} if is_sqlite else {},
        )
        if is_sqlite:
            _configure_sqlite(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False,
                                            autoflush=False, future=True)

    @staticmethod
    def _ensure_sqlite_dir(url: str) -> None:
        raw = url.split("///", 1)[-1]
        if raw and raw != ":memory:":
            Path(raw).expanduser().parent.mkdir(parents=True, exist_ok=True)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        Base.metadata.drop_all(self.engine)

    @contextlib.contextmanager
    def session(self) -> Iterator[Session]:
        db = self.session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def dispose(self) -> None:
        self.engine.dispose()


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
        # 关闭 pysqlite 的隐式 BEGIN，交给下面的 begin 事件发 BEGIN IMMEDIATE。
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _on_begin(conn) -> None:  # noqa: ANN001
        conn.exec_driver_sql("BEGIN IMMEDIATE")
