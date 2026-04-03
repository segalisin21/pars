from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Source
from app.queue import get_rq_queue, is_queue_enabled
from app.routers.context import RouteContext
from app.schemas import SourceCreate, SourceOut, SourcePatch, SourcesList
from app.services import refresh_source_telegram_meta
from app.telegram_client import TelegramClient
from app.worker_jobs import execute_refresh_source_meta


def make_sources_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["sources"])
    get_db = ctx.get_db
    get_tg = ctx.get_tg
    get_workspace_id = ctx.get_workspace_id
    verify_admin_token = ctx.verify_admin_token
    source_row_out = ctx.source_row_out

    @router.post("/sources", response_model=SourceOut, status_code=201)
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
            collect_mode=payload.collect_mode,
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
        return source_row_out(src)

    @router.get("/sources", response_model=SourcesList)
    def list_sources(db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
        items = db.scalars(select(Source).where(Source.workspace_id == workspace_id).order_by(Source.id.asc())).all()
        return SourcesList(items=[source_row_out(s) for s in items])

    @router.patch("/sources/{source_id}", response_model=SourceOut)
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
        if payload.collect_mode is not None:
            src.collect_mode = payload.collect_mode
        db.commit()
        db.refresh(src)
        db.add(
            AuditEvent(
                workspace_id=workspace_id,
                action="source.patch",
                entity_type="source",
                entity_id=src.id,
                meta={"enabled": src.enabled, "collect_mode": src.collect_mode},
            )
        )
        db.commit()
        return source_row_out(src)

    @router.post("/sources/{source_id}/refresh_telegram_meta")
    def refresh_source_telegram_meta_route(
        source_id: int,
        db: Session = Depends(get_db),
        tg: TelegramClient = Depends(get_tg),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        src = db.get(Source, source_id)
        if src is None or src.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "source_not_found", "message": "Source not found", "details": {"id": source_id}}},
            )
        if is_queue_enabled():
            q = get_rq_queue()
            q.enqueue(
                execute_refresh_source_meta,
                source_id=source_id,
                job_timeout=120,
            )
            return JSONResponse(
                status_code=202,
                content=source_row_out(src).model_dump(mode="json"),
            )
        refresh_source_telegram_meta(db, workspace_id, source_id, tg)
        db.commit()
        db.refresh(src)
        db.add(
            AuditEvent(
                workspace_id=workspace_id,
                action="source.refresh_telegram_meta",
                entity_type="source",
                entity_id=src.id,
                meta={},
            )
        )
        db.commit()
        return source_row_out(src)

    return router
