from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db import Base, create_session_factory, create_sqlite_engine
from app.dependencies import get_db as make_get_db, get_tg_client as make_get_tg, get_workspace_id
from app.models import (
    AuditEvent,
    CandidateSourceLink,
    CandidateUser,
    CollectRun,
    InviteAttempt,
    InviteRun,
    InviteTarget,
    Source,
    SuppressionList,
    Workspace,
)
from app.schemas import (
    AuditEventOut,
    AuditEventsList,
    CandidateWithSourcesOut,
    CollectRunCreate,
    CollectRunOut,
    CollectRunsList,
    CandidatesList,
    InviteAttemptOut,
    InviteAttemptsList,
    InviteRunCreate,
    InviteRunOut,
    InviteRunsList,
    PageMeta,
    SourceCreate,
    SourcePatch,
    SourceOut,
    SourceRefOut,
    SourcesList,
    SuppressionListOut,
    SuppressionOut,
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


def _rq_timeout_seconds(env_var: str, default_seconds: int) -> int:
    raw = os.getenv(env_var)
    if not raw:
        return default_seconds
    try:
        v = int(raw)
    except ValueError:
        return default_seconds
    return max(1, v)


def error(code: str, message: str, details: dict | None = None) -> HTTPException:
    payload = {"error": {"code": code, "message": message, "details": details or {}}}
    return HTTPException(status_code=400, detail=payload)


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

    @app.exception_handler(DBAPIError)
    async def db_exception_handler(_request: Request, _exc: DBAPIError):
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "db_unavailable", "message": "Database is temporarily unavailable", "details": {}}},
        )

    if session_factory is None:
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            engine = create_engine(
                db_url,
                future=True,
                pool_pre_ping=True,
                pool_recycle=300,
            )
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
    def create_source(
        payload: SourceCreate,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        src = Source(
            workspace_id=workspace_id,
            type=payload.type,
            identifier=payload.identifier,
            enabled=payload.enabled,
            notes=payload.notes,
        )
        db.add(src)
        db.commit()
        db.refresh(src)
        db.add(
            AuditEvent(
                workspace_id=workspace_id,
                action="source.create",
                entity_type="source",
                entity_id=src.id,
                meta={"type": src.type, "identifier": src.identifier},
            )
        )
        db.commit()
        return SourceOut(id=src.id, type=src.type, identifier=src.identifier, enabled=src.enabled, notes=src.notes)

    @app.get("/sources", response_model=SourcesList)
    def list_sources(db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
        items = db.scalars(select(Source).where(Source.workspace_id == workspace_id).order_by(Source.id.asc())).all()
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
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        src = db.get(Source, source_id)
        if src is None or src.workspace_id != workspace_id:
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
        db.add(
            AuditEvent(
                workspace_id=workspace_id,
                action="source.patch",
                entity_type="source",
                entity_id=src.id,
                meta={"enabled": src.enabled},
            )
        )
        db.commit()
        return SourceOut(id=src.id, type=src.type, identifier=src.identifier, enabled=src.enabled, notes=src.notes)

    @app.post("/targets", response_model=TargetOut, status_code=201)
    def create_target(
        payload: TargetCreate,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        tgt = InviteTarget(
            workspace_id=workspace_id,
            identifier=payload.identifier,
            enabled=payload.enabled,
            notes=payload.notes,
        )
        db.add(tgt)
        db.commit()
        db.refresh(tgt)
        db.add(
            AuditEvent(
                workspace_id=workspace_id,
                action="target.create",
                entity_type="target",
                entity_id=tgt.id,
                meta={"identifier": tgt.identifier},
            )
        )
        db.commit()
        return TargetOut(id=tgt.id, identifier=tgt.identifier, enabled=tgt.enabled, notes=tgt.notes)

    @app.get("/targets", response_model=TargetsList)
    def list_targets(db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
        items = db.scalars(
            select(InviteTarget).where(InviteTarget.workspace_id == workspace_id).order_by(InviteTarget.id.asc())
        ).all()
        return TargetsList(items=[TargetOut(id=t.id, identifier=t.identifier, enabled=t.enabled, notes=t.notes) for t in items])

    @app.get("/candidates", response_model=CandidatesList)
    def list_candidates(
        q: str | None = None,
        source_id: int | None = None,
        has_tg_user_id: bool | None = None,
        limit: int = 50,
        offset: int = 0,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))

        stmt = select(CandidateUser).where(CandidateUser.workspace_id == workspace_id)
        if has_tg_user_id is True:
            stmt = stmt.where(CandidateUser.tg_user_id.is_not(None))
        elif has_tg_user_id is False:
            stmt = stmt.where(CandidateUser.tg_user_id.is_(None))

        if q:
            qq = q.strip()
            if qq.startswith("@"):
                qq = qq[1:]
            like = f"%{qq.lower()}%"
            stmt = stmt.where(
                (CandidateUser.username.is_not(None) & (CandidateUser.username.ilike(like)))
                | (CandidateUser.display_name.is_not(None) & (CandidateUser.display_name.ilike(like)))
            )

        if source_id is not None:
            stmt = stmt.join(CandidateSourceLink, CandidateSourceLink.candidate_id == CandidateUser.id).where(
                CandidateSourceLink.workspace_id == workspace_id,
                CandidateSourceLink.source_id == source_id,
            )

        candidates = db.scalars(stmt.order_by(CandidateUser.id.desc()).limit(limit).offset(offset)).all()

        # Total (simple, v1)
        total_stmt = select(CandidateUser.id).where(CandidateUser.workspace_id == workspace_id)
        if has_tg_user_id is True:
            total_stmt = total_stmt.where(CandidateUser.tg_user_id.is_not(None))
        elif has_tg_user_id is False:
            total_stmt = total_stmt.where(CandidateUser.tg_user_id.is_(None))
        if q:
            qq = q.strip()
            if qq.startswith("@"):
                qq = qq[1:]
            like = f"%{qq.lower()}%"
            total_stmt = total_stmt.where(
                (CandidateUser.username.is_not(None) & (CandidateUser.username.ilike(like)))
                | (CandidateUser.display_name.is_not(None) & (CandidateUser.display_name.ilike(like)))
            )
        if source_id is not None:
            total_stmt = total_stmt.join(CandidateSourceLink, CandidateSourceLink.candidate_id == CandidateUser.id).where(
                CandidateSourceLink.workspace_id == workspace_id,
                CandidateSourceLink.source_id == source_id,
            )
        total = len(db.scalars(total_stmt).all())

        c_ids = [c.id for c in candidates]
        sources_by_candidate: dict[int, list[SourceRefOut]] = {cid: [] for cid in c_ids}
        if c_ids:
            rows = db.execute(
                select(CandidateSourceLink.candidate_id, Source)
                .join(Source, Source.id == CandidateSourceLink.source_id)
                .where(
                    CandidateSourceLink.workspace_id == workspace_id,
                    CandidateSourceLink.candidate_id.in_(c_ids),
                )
                .order_by(Source.id.asc())
            ).all()
            for cid, src in rows:
                sources_by_candidate[int(cid)].append(SourceRefOut(id=src.id, type=src.type, identifier=src.identifier))

        return CandidatesList(
            items=[
                CandidateWithSourcesOut(
                    id=c.id,
                    tg_user_id=c.tg_user_id,
                    username=c.username,
                    display_name=c.display_name,
                    first_seen_at=c.first_seen_at,
                    last_seen_at=c.last_seen_at,
                    sources=sources_by_candidate.get(c.id, []),
                )
                for c in candidates
            ],
            page=PageMeta(limit=limit, offset=offset, total=total),
        )

    @app.get("/candidates/{candidate_id}", response_model=CandidateWithSourcesOut)
    def get_candidate(
        candidate_id: int,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        c = db.get(CandidateUser, candidate_id)
        if c is None or c.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "candidate_not_found", "message": "Candidate not found", "details": {"id": candidate_id}}},
            )
        rows = db.execute(
            select(Source)
            .join(CandidateSourceLink, CandidateSourceLink.source_id == Source.id)
            .where(
                CandidateSourceLink.workspace_id == workspace_id,
                CandidateSourceLink.candidate_id == candidate_id,
            )
            .order_by(Source.id.asc())
        ).scalars().all()
        sources = [SourceRefOut(id=s.id, type=s.type, identifier=s.identifier) for s in rows]
        return CandidateWithSourcesOut(
            id=c.id,
            tg_user_id=c.tg_user_id,
            username=c.username,
            display_name=c.display_name,
            first_seen_at=c.first_seen_at,
            last_seen_at=c.last_seen_at,
            sources=sources,
        )

    @app.get("/invite-attempts", response_model=InviteAttemptsList)
    def list_invite_attempts(
        invite_run_id: int | None = None,
        candidate_id: int | None = None,
        target_id: int | None = None,
        status: str | None = None,
        error_code: str | None = None,
        limit: int = 50,
        offset: int = 0,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))

        stmt = select(InviteAttempt).where(InviteAttempt.workspace_id == workspace_id)
        if invite_run_id is not None:
            stmt = stmt.where(InviteAttempt.invite_run_id == invite_run_id)
        if candidate_id is not None:
            stmt = stmt.where(InviteAttempt.candidate_id == candidate_id)
        if target_id is not None:
            stmt = stmt.where(InviteAttempt.target_id == target_id)
        if status:
            stmt = stmt.where(InviteAttempt.status == status)
        if error_code:
            stmt = stmt.where(InviteAttempt.error_code == error_code)

        rows = db.scalars(stmt.order_by(InviteAttempt.id.desc()).limit(limit).offset(offset)).all()

        total_stmt = select(InviteAttempt.id).where(InviteAttempt.workspace_id == workspace_id)
        if invite_run_id is not None:
            total_stmt = total_stmt.where(InviteAttempt.invite_run_id == invite_run_id)
        if candidate_id is not None:
            total_stmt = total_stmt.where(InviteAttempt.candidate_id == candidate_id)
        if target_id is not None:
            total_stmt = total_stmt.where(InviteAttempt.target_id == target_id)
        if status:
            total_stmt = total_stmt.where(InviteAttempt.status == status)
        if error_code:
            total_stmt = total_stmt.where(InviteAttempt.error_code == error_code)
        total = len(db.scalars(total_stmt).all())

        return InviteAttemptsList(
            items=[
                InviteAttemptOut(
                    id=a.id,
                    invite_run_id=a.invite_run_id,
                    target_id=a.target_id,
                    candidate_id=a.candidate_id,
                    status=a.status,
                    error_code=a.error_code,
                    attempted_at=a.attempted_at,
                )
                for a in rows
            ],
            page=PageMeta(limit=limit, offset=offset, total=total),
        )

    @app.get("/suppression", response_model=SuppressionListOut)
    def list_suppression(
        q: str | None = None,
        reason: str | None = None,
        active_only: bool = True,
        limit: int = 50,
        offset: int = 0,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        from app.models import utcnow

        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))

        stmt = select(SuppressionList).where(SuppressionList.workspace_id == workspace_id)
        if active_only:
            now = utcnow()
            stmt = stmt.where((SuppressionList.until.is_(None)) | (SuppressionList.until > now))
        if reason:
            stmt = stmt.where(SuppressionList.reason == reason)
        if q:
            qq = q.strip()
            if qq.startswith("@"):
                qq = qq[1:]
            like = f"%{qq.lower()}%"
            stmt = stmt.where((SuppressionList.username.is_not(None) & (SuppressionList.username.ilike(like))))

        rows = db.scalars(stmt.order_by(SuppressionList.id.desc()).limit(limit).offset(offset)).all()

        total = len(db.scalars(select(SuppressionList.id).where(SuppressionList.workspace_id == workspace_id)).all())
        return SuppressionListOut(
            items=[
                SuppressionOut(
                    id=s.id,
                    tg_user_id=s.tg_user_id,
                    username=s.username,
                    reason=s.reason,
                    until=s.until,
                    created_at=s.created_at,
                )
                for s in rows
            ],
            page=PageMeta(limit=limit, offset=offset, total=total),
        )

    @app.patch("/targets/{target_id}", response_model=TargetOut)
    def patch_target(
        target_id: int,
        payload: TargetPatch,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        tgt = db.get(InviteTarget, target_id)
        if tgt is None or tgt.workspace_id != workspace_id:
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
        db.add(
            AuditEvent(
                workspace_id=workspace_id,
                action="target.patch",
                entity_type="target",
                entity_id=tgt.id,
                meta={"enabled": tgt.enabled},
            )
        )
        db.commit()
        return TargetOut(id=tgt.id, identifier=tgt.identifier, enabled=tgt.enabled, notes=tgt.notes)

    @app.post("/collect-runs", response_model=CollectRunOut, status_code=202)
    def start_collect_run(
        payload: CollectRunCreate,
        db: Session = Depends(get_db),
        tg: TelegramClient = Depends(get_tg),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        # Validate source ids up-front (consistent 404 behavior)
        for sid in payload.source_ids:
            src = db.get(Source, sid)
            if src is None or src.workspace_id != workspace_id:
                raise HTTPException(
                    status_code=404,
                    detail={"error": {"code": "source_not_found", "message": "Source not found", "details": {"id": sid}}},
                )

        if is_queue_enabled():
            run = CollectRun(
                workspace_id=workspace_id,
                status="queued",
                source_ids=payload.source_ids,
                stats={},
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            q = get_rq_queue()
            q.enqueue(
                execute_collect_run,
                run_id=run.id,
                job_timeout=_rq_timeout_seconds("RQ_COLLECT_TIMEOUT_SECONDS", 1800),
            )
            db.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    action="collect.start",
                    entity_type="collect_run",
                    entity_id=run.id,
                    meta={"source_ids": payload.source_ids},
                )
            )
            db.commit()
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
            run = run_collect(db, tg, payload.source_ids, workspace_id)
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
    def list_collect_runs(db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
        runs = db.scalars(
            select(CollectRun).where(CollectRun.workspace_id == workspace_id).order_by(CollectRun.id.desc())
        ).all()
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
    def get_collect_run(run_id: int, db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
        run = db.get(CollectRun, run_id)
        if run is None or run.workspace_id != workspace_id:
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
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        tgt = db.get(InviteTarget, payload.target_id)
        if tgt is None or tgt.workspace_id != workspace_id:
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
            run = InviteRun(
                workspace_id=workspace_id,
                status="queued",
                target_id=payload.target_id,
                policy=payload.policy.model_dump(),
                stats={},
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            q = get_rq_queue()
            q.enqueue(
                execute_invite_run,
                run_id=run.id,
                job_timeout=_rq_timeout_seconds("RQ_INVITE_TIMEOUT_SECONDS", 1800),
            )
            db.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    action="invite.start",
                    entity_type="invite_run",
                    entity_id=run.id,
                    meta={"target_id": payload.target_id},
                )
            )
            db.commit()
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
            run = run_invite(db, tg, payload.target_id, payload.policy.model_dump(), workspace_id)
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

    @app.get("/audit", response_model=AuditEventsList)
    def list_audit(
        action: str | None = None,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))

        stmt = select(AuditEvent).where(AuditEvent.workspace_id == workspace_id)
        if action:
            stmt = stmt.where(AuditEvent.action == action)
        if entity_type:
            stmt = stmt.where(AuditEvent.entity_type == entity_type)

        rows = db.scalars(stmt.order_by(AuditEvent.id.desc()).limit(limit).offset(offset)).all()
        total = len(db.scalars(select(AuditEvent.id).where(AuditEvent.workspace_id == workspace_id)).all())

        return AuditEventsList(
            items=[
                AuditEventOut(
                    id=e.id,
                    action=e.action,
                    entity_type=e.entity_type,
                    entity_id=e.entity_id,
                    meta=e.meta,
                    created_at=e.created_at,
                )
                for e in rows
            ],
            page=PageMeta(limit=limit, offset=offset, total=total),
        )

    @app.get("/invite-runs", response_model=InviteRunsList)
    def list_invite_runs(db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
        runs = db.scalars(
            select(InviteRun).where(InviteRun.workspace_id == workspace_id).order_by(InviteRun.id.desc())
        ).all()
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
    def get_invite_run(run_id: int, db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
        run = db.get(InviteRun, run_id)
        if run is None or run.workspace_id != workspace_id:
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

