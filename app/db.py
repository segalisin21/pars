from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def _pool_int(name: str, default: int, *, min_v: int = 1, max_v: int | None = None) -> int:
    raw = os.getenv(name)
    if not raw:
        v = default
    else:
        try:
            v = int(raw)
        except ValueError:
            v = default
    v = max(min_v, v)
    if max_v is not None:
        v = min(max_v, v)
    return v


def create_postgres_engine(database_url: str):
    """Postgres engine with configurable QueuePool (env: SQLALCHEMY_POOL_*)."""
    return create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=_pool_int("SQLALCHEMY_POOL_SIZE", 10, min_v=1, max_v=50),
        max_overflow=_pool_int("SQLALCHEMY_MAX_OVERFLOW", 20, min_v=0, max_v=100),
        pool_timeout=_pool_int("SQLALCHEMY_POOL_TIMEOUT", 60, min_v=5, max_v=600),
    )


def create_sqlite_engine(sqlite_url: str):
    # Note: for in-memory SQLite in tests, the engine is created in the fixture
    # with StaticPool; production code can use a file URL.
    return create_engine(sqlite_url, future=True)


def create_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False)


def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    db = session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

