from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import SuppressionList, utcnow
from app.routers.context import RouteContext
from app.schemas import PageMeta, SuppressionListOut, SuppressionOut


def make_suppression_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["suppression"])
    get_db = ctx.get_db
    get_workspace_id = ctx.get_workspace_id
    verify_admin_token = ctx.verify_admin_token

    @router.get("/suppression", response_model=SuppressionListOut)
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

        total_stmt = select(SuppressionList.id).where(SuppressionList.workspace_id == workspace_id)
        if active_only:
            now = utcnow()
            total_stmt = total_stmt.where((SuppressionList.until.is_(None)) | (SuppressionList.until > now))
        if reason:
            total_stmt = total_stmt.where(SuppressionList.reason == reason)
        if q:
            qq = q.strip()
            if qq.startswith("@"):
                qq = qq[1:]
            like = f"%{qq.lower()}%"
            total_stmt = total_stmt.where((SuppressionList.username.is_not(None) & (SuppressionList.username.ilike(like))))
        total = db.scalar(select(func.count()).select_from(total_stmt.subquery())) or 0
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

    return router
