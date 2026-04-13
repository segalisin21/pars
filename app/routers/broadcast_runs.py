from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, BroadcastDelivery, BroadcastRun, CandidateUser, Source, TelegramAccount, utcnow
from app.queue import get_rq_queue, is_queue_enabled
from app.routers.context import RouteContext
from app.schemas import (
    BroadcastDeliveriesList,
    BroadcastDeliveryOut,
    BroadcastPreviewIn,
    BroadcastPreviewOut,
    BroadcastRunCreate,
    BroadcastRunOut,
    BroadcastRunPatch,
    BroadcastRunsList,
    PageMeta,
)
from app.services import count_broadcast_preview, process_broadcast_run, run_broadcast
from app.telegram_client import TelegramClient
from app.worker_jobs import execute_broadcast_run


def _broadcast_run_out(run: BroadcastRun) -> BroadcastRunOut:
    raw_s = getattr(run, "source_ids", None)
    source_ids = list(raw_s) if isinstance(raw_s, list) else []
    raw_c = getattr(run, "candidate_ids", None)
    candidate_ids = list(raw_c) if isinstance(raw_c, list) else []
    return BroadcastRunOut(
        id=run.id,
        status=run.status,
        message_key=run.message_key,
        message_body=run.message_body,
        source_ids=source_ids,
        candidate_ids=candidate_ids,
        telegram_account_id=getattr(run, "telegram_account_id", None),
        policy=run.policy if isinstance(run.policy, dict) else {},
        started_at=run.started_at,
        finished_at=run.finished_at,
        stats=run.stats if isinstance(run.stats, dict) else {},
    )


def make_broadcast_runs_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["broadcast-runs"])
    get_db = ctx.get_db
    get_tg = ctx.get_tg
    get_workspace_id = ctx.get_workspace_id
    verify_admin_token = ctx.verify_admin_token
    rq_timeout = ctx.rq_timeout_seconds

    @router.post("/broadcast-runs/preview", response_model=BroadcastPreviewOut)
    def preview_broadcast(
        payload: BroadcastPreviewIn,
        db: Session = Depends(get_db),
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
        for cid in payload.candidate_ids:
            cand = db.get(CandidateUser, cid)
            if cand is None or cand.workspace_id != workspace_id:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": {"code": "candidate_not_found", "message": "Candidate not found", "details": {"id": cid}},
                    },
                )
        counts = count_broadcast_preview(
            db,
            workspace_id,
            message_key=payload.message_key.strip(),
            source_ids=payload.source_ids,
            candidate_ids=payload.candidate_ids,
        )
        return BroadcastPreviewOut(**counts)

    @router.post("/broadcast-runs", response_model=BroadcastRunOut, status_code=202)
    def start_broadcast_run(
        payload: BroadcastRunCreate,
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
        for cid in payload.candidate_ids:
            cand = db.get(CandidateUser, cid)
            if cand is None or cand.workspace_id != workspace_id:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": {"code": "candidate_not_found", "message": "Candidate not found", "details": {"id": cid}},
                    },
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

        policy_dump = payload.policy.model_dump()
        if is_queue_enabled():
            run = BroadcastRun(
                workspace_id=workspace_id,
                status="queued",
                message_key=payload.message_key,
                message_body=payload.message_body,
                source_ids=payload.source_ids,
                candidate_ids=payload.candidate_ids,
                policy=policy_dump,
                stats={},
                telegram_account_id=payload.telegram_account_id,
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            q = get_rq_queue()
            q.enqueue(
                execute_broadcast_run,
                run_id=run.id,
                job_timeout=rq_timeout("RQ_BROADCAST_TIMEOUT_SECONDS", 1800),
            )
            db.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    action="broadcast.start",
                    entity_type="broadcast_run",
                    entity_id=run.id,
                    meta={
                        "message_key": payload.message_key,
                        "message_len": len(payload.message_body),
                        "source_ids": payload.source_ids,
                        "candidate_ids_count": len(payload.candidate_ids),
                    },
                )
            )
            db.commit()
            return _broadcast_run_out(run)

        try:
            run = run_broadcast(
                db,
                tg,
                workspace_id,
                message_key=payload.message_key,
                message_body=payload.message_body,
                source_ids=payload.source_ids,
                candidate_ids=payload.candidate_ids,
                policy=policy_dump,
                telegram_account_id=payload.telegram_account_id,
            )
            db.commit()
            db.refresh(run)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "validation_error", "message": "Invalid broadcast run", "details": {}}},
            )

        db.add(
            AuditEvent(
                workspace_id=workspace_id,
                action="broadcast.start",
                entity_type="broadcast_run",
                entity_id=run.id,
                meta={
                    "message_key": payload.message_key,
                    "message_len": len(payload.message_body),
                    "source_ids": payload.source_ids,
                    "candidate_ids_count": len(payload.candidate_ids),
                    "sync": True,
                },
            )
        )
        db.commit()
        db.refresh(run)
        return _broadcast_run_out(run)

    @router.get("/broadcast-runs", response_model=BroadcastRunsList)
    def list_broadcast_runs(db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
        runs = db.scalars(
            select(BroadcastRun).where(BroadcastRun.workspace_id == workspace_id).order_by(BroadcastRun.id.desc())
        ).all()
        return BroadcastRunsList(items=[_broadcast_run_out(r) for r in runs])

    @router.get("/broadcast-runs/{run_id}", response_model=BroadcastRunOut)
    def get_broadcast_run(run_id: int, db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
        run = db.get(BroadcastRun, run_id)
        if run is None or run.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {"code": "broadcast_run_not_found", "message": "Broadcast run not found", "details": {"id": run_id}},
                },
            )
        return _broadcast_run_out(run)

    @router.get("/broadcast-runs/{run_id}/deliveries", response_model=BroadcastDeliveriesList)
    def list_broadcast_deliveries(
        run_id: int,
        status: str | None = None,
        error_code: str | None = None,
        limit: int = 50,
        offset: int = 0,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
    ):
        run = db.get(BroadcastRun, run_id)
        if run is None or run.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {"code": "broadcast_run_not_found", "message": "Broadcast run not found", "details": {"id": run_id}},
                },
            )

        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))

        stmt = (
            select(BroadcastDelivery, CandidateUser.username, CandidateUser.display_name)
            .outerjoin(CandidateUser, BroadcastDelivery.candidate_id == CandidateUser.id)
            .where(
                BroadcastDelivery.workspace_id == workspace_id,
                BroadcastDelivery.broadcast_run_id == run_id,
            )
        )
        if status:
            stmt = stmt.where(BroadcastDelivery.status == status)
        if error_code:
            stmt = stmt.where(BroadcastDelivery.error_code == error_code)

        rows = db.execute(stmt.order_by(BroadcastDelivery.id.desc()).limit(limit).offset(offset)).all()

        count_base = select(BroadcastDelivery.id).where(
            BroadcastDelivery.workspace_id == workspace_id,
            BroadcastDelivery.broadcast_run_id == run_id,
        )
        if status:
            count_base = count_base.where(BroadcastDelivery.status == status)
        if error_code:
            count_base = count_base.where(BroadcastDelivery.error_code == error_code)
        total = db.scalar(select(func.count()).select_from(count_base.subquery())) or 0

        items = [
            BroadcastDeliveryOut(
                id=d.id,
                broadcast_run_id=d.broadcast_run_id,
                candidate_id=d.candidate_id,
                tg_user_id=int(d.tg_user_id),
                status=d.status,
                error_code=d.error_code,
                attempted_at=d.attempted_at,
                username=uname,
                display_name=dname,
            )
            for d, uname, dname in rows
        ]
        return BroadcastDeliveriesList(items=items, page=PageMeta(limit=limit, offset=offset, total=total))

    @router.patch("/broadcast-runs/{run_id}", response_model=BroadcastRunOut)
    def patch_broadcast_run(
        run_id: int,
        payload: BroadcastRunPatch,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        run = db.get(BroadcastRun, run_id)
        if run is None or run.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {"code": "broadcast_run_not_found", "message": "Broadcast run not found", "details": {"id": run_id}},
                },
            )
        if run.status not in {"queued", "paused"}:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "code": "broadcast_run_not_editable",
                        "message": "Only queued or paused broadcast runs can update message_body",
                        "details": {"id": run_id, "status": run.status},
                    }
                },
            )
        run.message_body = payload.message_body
        db.add(
            AuditEvent(
                workspace_id=workspace_id,
                action="broadcast.update",
                entity_type="broadcast_run",
                entity_id=run.id,
                meta={"message_key": run.message_key, "message_len": len(payload.message_body)},
            )
        )
        db.commit()
        db.refresh(run)
        return _broadcast_run_out(run)

    @router.post("/broadcast-runs/{run_id}/resume", response_model=BroadcastRunOut, status_code=202)
    def resume_broadcast_run(
        run_id: int,
        db: Session = Depends(get_db),
        tg: TelegramClient = Depends(get_tg),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        run = db.get(BroadcastRun, run_id)
        if run is None or run.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {"code": "broadcast_run_not_found", "message": "Broadcast run not found", "details": {"id": run_id}},
                },
            )
        if run.status != "paused":
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "broadcast_run_not_resumable",
                        "message": "Only paused broadcast runs can be resumed",
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
                execute_broadcast_run,
                run_id=run.id,
                job_timeout=rq_timeout("RQ_BROADCAST_TIMEOUT_SECONDS", 1800),
            )
            db.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    action="broadcast.resume",
                    entity_type="broadcast_run",
                    entity_id=run.id,
                    meta={"message_key": run.message_key},
                )
            )
            db.commit()
            return _broadcast_run_out(run)

        try:
            process_broadcast_run(db, tg, run)
            db.commit()
            db.refresh(run)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "validation_error", "message": "Invalid broadcast run", "details": {}}},
            )

        db.add(
            AuditEvent(
                workspace_id=workspace_id,
                action="broadcast.resume",
                entity_type="broadcast_run",
                entity_id=run.id,
                meta={"message_key": run.message_key, "sync": True},
            )
        )
        db.commit()
        db.refresh(run)
        return _broadcast_run_out(run)

    @router.post("/broadcast-runs/{run_id}/cancel", response_model=BroadcastRunOut)
    def cancel_broadcast_run(
        run_id: int,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        run = db.get(BroadcastRun, run_id)
        if run is None or run.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {"code": "broadcast_run_not_found", "message": "Broadcast run not found", "details": {"id": run_id}},
                },
            )
        if run.status not in {"queued", "paused"}:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "broadcast_run_not_cancellable",
                        "message": "Only queued or paused broadcast runs can be cancelled",
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
                action="broadcast.cancel",
                entity_type="broadcast_run",
                entity_id=run.id,
                meta={"message_key": run.message_key},
            )
        )
        db.commit()
        db.refresh(run)
        return _broadcast_run_out(run)

    return router
