from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import InviteAttempt
from app.routers.context import RouteContext
from app.schemas import InviteAttemptOut, InviteAttemptsList, PageMeta


def make_invite_attempts_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["invite-attempts"])
    get_db = ctx.get_db
    get_workspace_id = ctx.get_workspace_id
    verify_admin_token = ctx.verify_admin_token

    @router.get("/invite-attempts", response_model=InviteAttemptsList)
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
        total = db.scalar(select(func.count()).select_from(total_stmt.subquery())) or 0

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

    return router
