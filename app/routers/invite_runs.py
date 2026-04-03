from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, InviteRun, InviteTarget, utcnow
from app.queue import get_rq_queue, is_queue_enabled
from app.routers.context import RouteContext
from app.schemas import InviteRunCreate, InviteRunOut, InviteRunsList
from app.services import process_invite_run, run_invite
from app.telegram_client import TelegramClient
from app.worker_jobs import execute_invite_run


def make_invite_runs_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["invite-runs"])
    get_db = ctx.get_db
    get_tg = ctx.get_tg
    get_workspace_id = ctx.get_workspace_id
    verify_admin_token = ctx.verify_admin_token
    rq_timeout = ctx.rq_timeout_seconds

    @router.post("/invite-runs", response_model=InviteRunOut, status_code=202)
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
                job_timeout=rq_timeout("RQ_INVITE_TIMEOUT_SECONDS", 1800),
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

    @router.get("/invite-runs", response_model=InviteRunsList)
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

    @router.get("/invite-runs/{run_id}", response_model=InviteRunOut)
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

    @router.post("/invite-runs/{run_id}/resume", response_model=InviteRunOut, status_code=202)
    def resume_invite_run(
        run_id: int,
        db: Session = Depends(get_db),
        tg: TelegramClient = Depends(get_tg),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        run = db.get(InviteRun, run_id)
        if run is None or run.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "invite_run_not_found", "message": "Invite run not found", "details": {"id": run_id}}},
            )
        if run.status != "paused":
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "invite_run_not_resumable",
                        "message": "Only paused invite runs can be resumed",
                        "details": {"id": run_id, "status": run.status},
                    }
                },
            )

        run.status = "queued"
        db.flush()

        if is_queue_enabled():
            db.commit()
            db.refresh(run)
            q = get_rq_queue()
            q.enqueue(
                execute_invite_run,
                run_id=run.id,
                job_timeout=rq_timeout("RQ_INVITE_TIMEOUT_SECONDS", 1800),
            )
            db.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    action="invite.resume",
                    entity_type="invite_run",
                    entity_id=run.id,
                    meta={"target_id": run.target_id},
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

        try:
            process_invite_run(db, tg, run)
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

        db.add(
            AuditEvent(
                workspace_id=workspace_id,
                action="invite.resume",
                entity_type="invite_run",
                entity_id=run.id,
                meta={"target_id": run.target_id, "sync": True},
            )
        )
        db.commit()
        db.refresh(run)
        return InviteRunOut(
            id=run.id,
            status=run.status,
            target_id=run.target_id,
            policy=run.policy,
            started_at=run.started_at,
            finished_at=run.finished_at,
            stats=run.stats,
        )

    @router.post("/invite-runs/{run_id}/cancel", response_model=InviteRunOut)
    def cancel_invite_run(
        run_id: int,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        run = db.get(InviteRun, run_id)
        if run is None or run.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "invite_run_not_found", "message": "Invite run not found", "details": {"id": run_id}}},
            )
        if run.status not in {"queued", "paused"}:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "invite_run_not_cancellable",
                        "message": "Only queued or paused invite runs can be cancelled",
                        "details": {"id": run_id, "status": run.status},
                    }
                },
            )

        merged = dict(run.stats) if isinstance(run.stats, dict) else {}
        merged["pause_reason"] = "cancelled"
        run.status = "cancelled"
        run.finished_at = utcnow()
        run.stats = merged
        db.add(
            AuditEvent(
                workspace_id=workspace_id,
                action="invite.cancel",
                entity_type="invite_run",
                entity_id=run.id,
                meta={"target_id": run.target_id},
            )
        )
        db.commit()
        db.refresh(run)
        return InviteRunOut(
            id=run.id,
            status=run.status,
            target_id=run.target_id,
            policy=run.policy,
            started_at=run.started_at,
            finished_at=run.finished_at,
            stats=run.stats,
        )

    return router
