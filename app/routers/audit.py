from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.routers.context import RouteContext
from app.schemas import AuditEventOut, AuditEventsList, PageMeta


def make_audit_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["audit"])
    get_db = ctx.get_db
    get_workspace_id = ctx.get_workspace_id
    verify_admin_token = ctx.verify_admin_token

    @router.get("/audit", response_model=AuditEventsList)
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

        total_stmt = select(AuditEvent.id).where(AuditEvent.workspace_id == workspace_id)
        if action:
            total_stmt = total_stmt.where(AuditEvent.action == action)
        if entity_type:
            total_stmt = total_stmt.where(AuditEvent.entity_type == entity_type)
        total = db.scalar(select(func.count()).select_from(total_stmt.subquery())) or 0

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

    return router
