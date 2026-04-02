from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base, create_session_factory, create_sqlite_engine
from app.dependencies import get_db as make_get_db, get_tg_client as make_get_tg
from app.models import CollectRun, InviteRun, InviteTarget, Source
from app.schemas import (
    CollectRunCreate,
    CollectRunOut,
    CollectRunsList,
    InviteRunCreate,
    InviteRunOut,
    InviteRunsList,
    SourceCreate,
    SourcePatch,
    SourceOut,
    SourcesList,
    TargetCreate,
    TargetPatch,
    TargetOut,
    TargetsList,
    TelegramRequestCodeIn,
    TelegramRequestCodeOut,
    TelegramVerifyCodeIn,
    TelegramVerifyCodeOut,
)
from app.queue import is_queue_enabled, get_rq_queue
from app.services import run_collect, run_invite
from app.telegram_client import TelegramClient
from app.telegram_auth_web import request_code as tg_request_code, verify_code as tg_verify_code
from app.worker_jobs import execute_collect_run, execute_invite_run


def error(code: str, message: str, details: dict | None = None) -> HTTPException:
    payload = {"error": {"code": code, "message": message, "details": details or {}}}
    return HTTPException(status_code=400, detail=payload)


def create_app(
    *,
    session_factory=None,
    tg_client: TelegramClient | None = None,
) -> FastAPI:
    app = FastAPI(title="telegram-audience-collector-inviter", version="0.1.0")

    admin_token = os.getenv("ADMIN_TOKEN")
    cors_allowed_origins = [o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
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
        # Ensure our documented error envelope is returned at the top-level,
        # not nested under {"detail": ...}.
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": "http_error", "message": str(exc.detail), "details": {}}})

    if session_factory is None:
        engine = create_sqlite_engine("sqlite:///./app.db")
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

    if tg_client is None:
        class _NoopTelegramClient(TelegramClient):
            def get_participants(self, source_identifier: str):
                return []

            def invite_to_target(self, target_identifier: str, tg_user_id: int) -> None:
                return None

        tg_client = _NoopTelegramClient()

    get_db = make_get_db(session_factory)
    get_tg = make_get_tg(tg_client)

    def verify_admin_token(request: Request):
        # Local-dev convenience: if ADMIN_TOKEN is not set, skip auth.
        if not admin_token:
            return
        auth = request.headers.get("Authorization", "")
        expected = f"Bearer {admin_token}"
        if auth != expected:
            raise HTTPException(
                status_code=401,
                detail={"error": {"code": "unauthorized", "message": "Missing or invalid token", "details": {}}},
            )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/sources", response_model=SourceOut, status_code=201)
    def create_source(payload: SourceCreate, db: Session = Depends(get_db), _auth=Depends(verify_admin_token)):
        src = Source(type=payload.type, identifier=payload.identifier, enabled=payload.enabled, notes=payload.notes)
        db.add(src)
        db.commit()
        db.refresh(src)
        return SourceOut(id=src.id, type=src.type, identifier=src.identifier, enabled=src.enabled, notes=src.notes)

    @app.get("/sources", response_model=SourcesList)
    def list_sources(db: Session = Depends(get_db)):
        items = db.scalars(select(Source).order_by(Source.id.asc())).all()
        return SourcesList(
            items=[
                SourceOut(id=s.id, type=s.type, identifier=s.identifier, enabled=s.enabled, notes=s.notes)
                for s in items
            ]
        )

    @app.patch("/sources/{source_id}", response_model=SourceOut)
    def patch_source(
        source_id: int,
        payload: SourcePatch,
        db: Session = Depends(get_db),
        _auth=Depends(verify_admin_token),
    ):
        src = db.get(Source, source_id)
        if src is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "source_not_found", "message": "Source not found", "details": {"id": source_id}}},
            )
        if payload.enabled is not None:
            src.enabled = payload.enabled
        if payload.notes is not None:
            src.notes = payload.notes
        db.commit()
        db.refresh(src)
        return SourceOut(id=src.id, type=src.type, identifier=src.identifier, enabled=src.enabled, notes=src.notes)

    @app.post("/targets", response_model=TargetOut, status_code=201)
    def create_target(payload: TargetCreate, db: Session = Depends(get_db), _auth=Depends(verify_admin_token)):
        tgt = InviteTarget(identifier=payload.identifier, enabled=payload.enabled, notes=payload.notes)
        db.add(tgt)
        db.commit()
        db.refresh(tgt)
        return TargetOut(id=tgt.id, identifier=tgt.identifier, enabled=tgt.enabled, notes=tgt.notes)

    @app.get("/targets", response_model=TargetsList)
    def list_targets(db: Session = Depends(get_db)):
        items = db.scalars(select(InviteTarget).order_by(InviteTarget.id.asc())).all()
        return TargetsList(items=[TargetOut(id=t.id, identifier=t.identifier, enabled=t.enabled, notes=t.notes) for t in items])

    @app.patch("/targets/{target_id}", response_model=TargetOut)
    def patch_target(
        target_id: int,
        payload: TargetPatch,
        db: Session = Depends(get_db),
        _auth=Depends(verify_admin_token),
    ):
        tgt = db.get(InviteTarget, target_id)
        if tgt is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "target_not_found", "message": "Target not found", "details": {"id": target_id}}},
            )
        if payload.enabled is not None:
            tgt.enabled = payload.enabled
        if payload.notes is not None:
            tgt.notes = payload.notes
        db.commit()
        db.refresh(tgt)
        return TargetOut(id=tgt.id, identifier=tgt.identifier, enabled=tgt.enabled, notes=tgt.notes)

    @app.post("/collect-runs", response_model=CollectRunOut, status_code=202)
    def start_collect_run(
        payload: CollectRunCreate,
        db: Session = Depends(get_db),
        tg: TelegramClient = Depends(get_tg),
        _auth=Depends(verify_admin_token),
    ):
        # Validate source ids up-front (consistent 404 behavior)
        for sid in payload.source_ids:
            if db.get(Source, sid) is None:
                raise HTTPException(
                    status_code=404,
                    detail={"error": {"code": "source_not_found", "message": "Source not found", "details": {"id": sid}}},
                )

        if is_queue_enabled():
            run = CollectRun(status="queued", source_ids=payload.source_ids, stats={})
            db.add(run)
            db.commit()
            db.refresh(run)
            q = get_rq_queue()
            q.enqueue(execute_collect_run, run_id=run.id)
            return CollectRunOut(
                id=run.id,
                status=run.status,
                source_ids=run.source_ids,
                started_at=run.started_at,
                finished_at=run.finished_at,
                stats=run.stats,
            )

        # Local-first fallback: run synchronously
        try:
            run = run_collect(db, tg, payload.source_ids)
            db.commit()
            db.refresh(run)
        except KeyError as e:
            sid = str(e).split(":")[-1].strip("'")
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "source_not_found", "message": "Source not found", "details": {"id": sid}}},
            )

        return CollectRunOut(
            id=run.id,
            status=run.status,
            source_ids=run.source_ids,
            started_at=run.started_at,
            finished_at=run.finished_at,
            stats=run.stats,
        )

    @app.get("/collect-runs", response_model=CollectRunsList)
    def list_collect_runs(db: Session = Depends(get_db)):
        runs = db.scalars(select(CollectRun).order_by(CollectRun.id.desc())).all()
        return CollectRunsList(
            items=[
                CollectRunOut(
                    id=r.id,
                    status=r.status,
                    source_ids=r.source_ids,
                    started_at=r.started_at,
                    finished_at=r.finished_at,
                    stats=r.stats,
                )
                for r in runs
            ]
        )

    @app.get("/collect-runs/{run_id}", response_model=CollectRunOut)
    def get_collect_run(run_id: int, db: Session = Depends(get_db)):
        run = db.get(CollectRun, run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "collect_run_not_found", "message": "Collect run not found", "details": {"id": run_id}}},
            )
        return CollectRunOut(
            id=run.id,
            status=run.status,
            source_ids=run.source_ids,
            started_at=run.started_at,
            finished_at=run.finished_at,
            stats=run.stats,
        )

    @app.post("/invite-runs", response_model=InviteRunOut, status_code=202)
    def start_invite_run(
        payload: InviteRunCreate,
        db: Session = Depends(get_db),
        tg: TelegramClient = Depends(get_tg),
        _auth=Depends(verify_admin_token),
    ):
        tgt = db.get(InviteTarget, payload.target_id)
        if tgt is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "target_not_found", "message": "Target not found", "details": {"id": payload.target_id}}},
            )
        if not tgt.enabled:
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "validation_error", "message": "Invalid target state", "details": {}}},
            )

        if is_queue_enabled():
            run = InviteRun(status="queued", target_id=payload.target_id, policy=payload.policy.model_dump(), stats={})
            db.add(run)
            db.commit()
            db.refresh(run)
            q = get_rq_queue()
            q.enqueue(execute_invite_run, run_id=run.id)
            return InviteRunOut(
                id=run.id,
                status=run.status,
                target_id=run.target_id,
                policy=run.policy,
                started_at=run.started_at,
                finished_at=run.finished_at,
                stats=run.stats,
            )

        # Local-first fallback: run synchronously
        try:
            run = run_invite(db, tg, payload.target_id, payload.policy.model_dump())
            db.commit()
            db.refresh(run)
        except KeyError as e:
            tid = str(e).split(":")[-1].strip("'")
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "target_not_found", "message": "Target not found", "details": {"id": tid}}},
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "validation_error", "message": "Invalid target state", "details": {}}},
            )

        return InviteRunOut(
            id=run.id,
            status=run.status,
            target_id=run.target_id,
            policy=run.policy,
            started_at=run.started_at,
            finished_at=run.finished_at,
            stats=run.stats,
        )

    @app.get("/invite-runs", response_model=InviteRunsList)
    def list_invite_runs(db: Session = Depends(get_db)):
        runs = db.scalars(select(InviteRun).order_by(InviteRun.id.desc())).all()
        return InviteRunsList(
            items=[
                InviteRunOut(
                    id=r.id,
                    status=r.status,
                    target_id=r.target_id,
                    policy=r.policy,
                    started_at=r.started_at,
                    finished_at=r.finished_at,
                    stats=r.stats,
                )
                for r in runs
            ]
        )

    @app.get("/invite-runs/{run_id}", response_model=InviteRunOut)
    def get_invite_run(run_id: int, db: Session = Depends(get_db)):
        run = db.get(InviteRun, run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "invite_run_not_found", "message": "Invite run not found", "details": {"id": run_id}}},
            )
        return InviteRunOut(
            id=run.id,
            status=run.status,
            target_id=run.target_id,
            policy=run.policy,
            started_at=run.started_at,
            finished_at=run.finished_at,
            stats=run.stats,
        )

    @app.post("/telegram/auth/request_code", response_model=TelegramRequestCodeOut)
    async def telegram_request_code(payload: TelegramRequestCodeIn, _auth=Depends(verify_admin_token)):
        r = await tg_request_code(payload.phone)
        return TelegramRequestCodeOut(token=r.token, error=r.error)

    @app.post("/telegram/auth/verify_code", response_model=TelegramVerifyCodeOut)
    async def telegram_verify_code(payload: TelegramVerifyCodeIn, _auth=Depends(verify_admin_token)):
        r = await tg_verify_code(payload.token, payload.code, password=payload.password)
        return TelegramVerifyCodeOut(success=r.success, session_string=r.session_string, error=r.error)

    return app


app = create_app()

