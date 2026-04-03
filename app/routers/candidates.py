from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CandidateSourceLink, CandidateUser, Source
from app.routers.context import RouteContext
from app.schemas import CandidateWithSourcesOut, CandidatesList, PageMeta, SourceRefOut


def make_candidates_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["candidates"])
    get_db = ctx.get_db
    get_workspace_id = ctx.get_workspace_id
    verify_admin_token = ctx.verify_admin_token

    @router.get("/candidates", response_model=CandidatesList)
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
        total = db.scalar(select(func.count()).select_from(total_stmt.subquery())) or 0

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

    @router.get("/candidates/{candidate_id}", response_model=CandidateWithSourcesOut)
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

    return router
