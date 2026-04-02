from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


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

