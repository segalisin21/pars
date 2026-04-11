from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, TimeoutError as SATimeoutError
from app.db import Base, create_postgres_engine, create_session_factory, create_sqlite_engine
from app.dependencies import get_db as make_get_db, get_tg_client as make_get_tg, get_workspace_id
from app.models import Source, Workspace
from app.routers import register_routes
from app.routers.context import RouteContext
from app.schemas import SourceOut
from app.telegram_client import TelegramClient

logger = logging.getLogger(__name__)


def _rq_timeout_seconds(env_var: str, default_seconds: int) -> int:
    raw = os.getenv(env_var)
    if not raw:
        return default_seconds
    try:
        v = int(raw)
    except ValueError:
        return default_seconds
    return max(1, v)


def _ensure_default_workspace(session_factory) -> None:
    db = session_factory()
    try:
        if db.get(Workspace, 1) is None:
            db.add(Workspace(id=1, name="default"))
            db.commit()
    finally:
        db.close()


def create_app(
    *,
    session_factory=None,
    tg_client: TelegramClient | None = None,
) -> FastAPI:
    admin_token = os.getenv("ADMIN_TOKEN")
    cors_allowed_origins = [o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if admin_token:
            if len(admin_token) < 32:
                logger.warning(
                    "ADMIN_TOKEN is shorter than 32 characters; policy recommends secrets.token_urlsafe(32) or longer."
                )
        elif os.getenv("DATABASE_URL", "").startswith("postgres") or os.getenv("RAILWAY_ENVIRONMENT"):
            logger.warning(
                "ADMIN_TOKEN is not set: mutating API routes are unauthenticated. Set ADMIN_TOKEN in production."
            )
        yield

    app = FastAPI(
        title="telegram-audience-collector-inviter",
        version="0.1.0",
        lifespan=lifespan,
    )
    if cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_allowed_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "http_error", "message": str(exc.detail), "details": {}}},
        )

    @app.exception_handler(DBAPIError)
    async def db_exception_handler(_request: Request, _exc: DBAPIError):
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "db_unavailable", "message": "Database is temporarily unavailable", "details": {}}},
        )

    @app.exception_handler(SATimeoutError)
    async def pool_timeout_handler(_request: Request, _exc: SATimeoutError):
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "db_pool_timeout",
                    "message": "Database connection pool is busy; try again shortly",
                    "details": {},
                }
            },
        )

    if session_factory is None:
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            engine = create_postgres_engine(db_url)
        else:
            engine = create_sqlite_engine("sqlite:///./app.db")
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

    _ensure_default_workspace(session_factory)

    if tg_client is None:
        class _NoopTelegramClient(TelegramClient):
            def iter_participants(self, source_identifier: str):
                return iter(())

            def get_participants(self, source_identifier: str):
                return []

            def iter_users_from_messages(self, source_identifier: str, *, limit=None, min_date=None):
                return iter(())

            def invite_to_target(self, target_identifier: str, tg_user_id: int) -> None:
                return None

            def send_direct_message(self, tg_user_id: int, text: str) -> None:
                return None

        tg_client = _NoopTelegramClient()

    get_db = make_get_db(session_factory)
    get_tg = make_get_tg(tg_client)

    def source_row_out(s: Source) -> SourceOut:
        cm = getattr(s, "collect_mode", None) or "participants"
        if cm not in {"participants", "messages", "both", "auto"}:
            cm = "participants"
        return SourceOut(
            id=s.id,
            type=s.type,
            identifier=s.identifier,
            enabled=s.enabled,
            notes=s.notes,
            collect_mode=cm,
            telegram_title=s.telegram_title,
            telegram_participants_count=s.telegram_participants_count,
            telegram_meta_updated_at=s.telegram_meta_updated_at,
        )

    def verify_admin_token(request: Request):
        if not admin_token:
            return
        auth = request.headers.get("Authorization", "")
        expected = f"Bearer {admin_token}"
        a_b = auth.encode("utf-8")
        e_b = expected.encode("utf-8")
        if len(a_b) != len(e_b) or not hmac.compare_digest(a_b, e_b):
            raise HTTPException(
                status_code=401,
                detail={"error": {"code": "unauthorized", "message": "Missing or invalid token", "details": {}}},
            )

    ctx = RouteContext(
        get_db=get_db,
        get_tg=get_tg,
        get_workspace_id=get_workspace_id,
        verify_admin_token=verify_admin_token,
        source_row_out=source_row_out,
        rq_timeout_seconds=_rq_timeout_seconds,
    )
    register_routes(app, ctx)

    return app


app = create_app()
