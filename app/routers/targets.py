from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, InviteTarget
from app.routers.context import RouteContext
from app.schemas import TargetCreate, TargetOut, TargetPatch, TargetsList


def make_targets_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["targets"])
    get_db = ctx.get_db
    get_workspace_id = ctx.get_workspace_id
    verify_admin_token = ctx.verify_admin_token

    @router.post("/targets", response_model=TargetOut, status_code=201)
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

    @router.get("/targets", response_model=TargetsList)
    def list_targets(db: Session = Depends(get_db), workspace_id: int = Depends(get_workspace_id)):
        items = db.scalars(
            select(InviteTarget).where(InviteTarget.workspace_id == workspace_id).order_by(InviteTarget.id.asc())
        ).all()
        return TargetsList(items=[TargetOut(id=t.id, identifier=t.identifier, enabled=t.enabled, notes=t.notes) for t in items])

    @router.patch("/targets/{target_id}", response_model=TargetOut)
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

    return router
