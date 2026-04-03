"""HTTP route modules (APIRouter factories)."""

from __future__ import annotations

from fastapi import FastAPI

from app.routers.audit import make_audit_router
from app.routers.candidates import make_candidates_router
from app.routers.collect_runs import make_collect_runs_router
from app.routers.context import RouteContext
from app.routers.health import make_health_router
from app.routers.invite_attempts import make_invite_attempts_router
from app.routers.invite_runs import make_invite_runs_router
from app.routers.sources import make_sources_router
from app.routers.suppression import make_suppression_router
from app.routers.targets import make_targets_router
from app.routers.telegram_auth import make_telegram_auth_router


def register_routes(app: FastAPI, ctx: RouteContext) -> None:
    """Mount all domain routers on the app (flat paths, no global prefix)."""
    app.include_router(make_health_router())
    app.include_router(make_sources_router(ctx))
    app.include_router(make_targets_router(ctx))
    app.include_router(make_candidates_router(ctx))
    app.include_router(make_invite_attempts_router(ctx))
    app.include_router(make_suppression_router(ctx))
    app.include_router(make_collect_runs_router(ctx))
    app.include_router(make_invite_runs_router(ctx))
    app.include_router(make_audit_router(ctx))
    app.include_router(make_telegram_auth_router(ctx))
