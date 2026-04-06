from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, CollectRun, Source, TelegramAccount
from app.queue import get_rq_queue, is_queue_enabled
from app.routers.context import RouteContext
from app.schemas import CollectRunCreate, CollectRunOut, CollectRunsList
from app.services import run_collect
from app.telegram_client import TelegramClient
from app.worker_jobs import execute_collect_run


def make_collect_runs_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["collect-runs"])
    get_db = ctx.get_db
    get_tg = ctx.get_tg
    get_workspace_id = ctx.get_workspace_id
    verify_admin_token = ctx.verify_admin_token
    rq_timeout = ctx.rq_timeout_seconds

    @router.post("/collect-runs", response_model=CollectRunOut, status_code=202)
    def start_collect_run(
        payload: CollectRunCreate,
        db: Session = Depends(get_db),
        tg: TelegramClient = Depends(get_tg),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        for sid in payload.source_ids:
            src = db.get(Source, sid)
            if src is None or src.workspace_id != workspace_id:
                raise HTTPException(
                    status_code=404,
                    detail={"error": {"code": "source_not_found", "message": "Source not found", "details": {"id": sid}}},
                )

        if payload.telegram_account_id is not None:
            acc = db.get(TelegramAccount, payload.telegram_account_id)
            if acc is None or not acc.enabled:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": {
                            "code": "telegram_account_not_found",
                            "message": "Telegram account not found or disabled",
                            "details": {"id": payload.telegram_account_id},
                        }
                    },
                )

        if is_queue_enabled():
            run = CollectRun(
                workspace_id=workspace_id,
                status="queued",
                source_ids=payload.source_ids,
                telegram_account_id=payload.telegram_account_id,
                stats={},
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            q = get_rq_queue()
            q.enqueue(
                execute_collect_run,
                run_id=run.id,
                job_timeout=rq_timeout("RQ_COLLECT_TIMEOUT_SECONDS", 1800),
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
                telegram_account_id=getattr(run, "telegram_account_id", None),
                started_at=run.started_at,
                finished_at=run.finished_at,
                stats=run.stats,
            )

        try:
            run = run_collect(
                db,
                tg,
                payload.source_ids,
                workspace_id,
                telegram_account_id=payload.telegram_account_id,
            )
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
            telegram_account_id=getattr(run, "telegram_account_id", None),
            started_at=run.started_at,
            finished_at=run.finished_at,
            stats=run.stats,
        )

    @router.get("/collect-runs", response_model=CollectRunsList)
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
                    telegram_account_id=getattr(r, "telegram_account_id", None),
                    started_at=r.started_at,
                    finished_at=r.finished_at,
                    stats=r.stats,
                )
                for r in runs
            ]
        )

    @router.get("/collect-runs/{run_id}", response_model=CollectRunOut)
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
            telegram_account_id=getattr(run, "telegram_account_id", None),
            started_at=run.started_at,
            finished_at=run.finished_at,
            stats=run.stats,
        )

    return router
