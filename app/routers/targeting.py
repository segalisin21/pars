from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from sqlalchemy import func

from app.models import CandidateFeatures, CandidateUser, TargetingProfile, utcnow
from app.openai_client import create_chat_json
from app.routers.context import RouteContext
from app.schemas import (
    TargetingAiSuggestIn,
    TargetingAiSuggestOut,
    TargetingCandidateOut,
    TargetingProfileOut,
    TargetingProfilePreviewIn,
    TargetingProfilePreviewOut,
    TargetingProfilesList,
)


def _dt_utc(v: datetime) -> datetime:
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


def make_targeting_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["targeting"])
    get_db = ctx.get_db
    get_workspace_id = ctx.get_workspace_id
    verify_admin_token = ctx.verify_admin_token

    @router.get("/targeting/profiles", response_model=TargetingProfilesList)
    def list_profiles(
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        rows = db.scalars(
            select(TargetingProfile).where(TargetingProfile.workspace_id == workspace_id).order_by(TargetingProfile.id.desc())
        ).all()
        return TargetingProfilesList(
            items=[
                TargetingProfileOut(
                    id=p.id,
                    name=p.name,
                    query=p.query,
                    language_mode=p.language_mode,
                    params=p.params if isinstance(p.params, dict) else {},
                    updated_at=_dt_utc(p.updated_at),
                )
                for p in rows
            ]
        )

    @router.post("/targeting/ai/suggest", response_model=TargetingAiSuggestOut)
    def ai_suggest(
        payload: TargetingAiSuggestIn,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        try:
            # Quick config check for clearer HTTP error.
            _ = create_chat_json  # keep import
        except Exception:
            pass
        sys = (
            "You are a targeting assistant for Telegram audience selection. "
            "Return a JSON object with: keywords_include (array of strings), keywords_exclude (array), intent_phrases (array), "
            "weights (object), defaults (object). Keep lists <= 60 items. Language: RU-first, but include EN synonyms if mixed."
        )
        user = f"Target: {payload.query}\nLanguage mode: {payload.language_mode}"
        try:
            res = create_chat_json(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
                response_format={"type": "json_object"},
            )
        except RuntimeError as e:
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "openai_not_configured", "message": str(e), "details": {}}},
            )
        try:
            content = res["choices"][0]["message"]["content"]
        except Exception as e:
            raise HTTPException(status_code=502, detail={"error": {"code": "openai_error", "message": str(e), "details": {}}})
        try:
            params = json.loads(content)
        except Exception:
            raise HTTPException(
                status_code=502,
                detail={"error": {"code": "openai_invalid_json", "message": "Invalid JSON from OpenAI", "details": {}}},
            )
        if not isinstance(params, dict):
            raise HTTPException(
                status_code=502,
                detail={"error": {"code": "openai_invalid_json", "message": "Invalid JSON object from OpenAI", "details": {}}},
            )

        name = (payload.name or payload.query).strip()[:128]
        now = utcnow()
        prof = TargetingProfile(
            workspace_id=workspace_id,
            name=name,
            query=payload.query.strip(),
            language_mode=payload.language_mode,
            params=params,
            created_at=now,
            updated_at=now,
        )
        db.add(prof)
        db.flush()
        return TargetingAiSuggestOut(
            profile=TargetingProfileOut(
                id=prof.id,
                name=prof.name,
                query=prof.query,
                language_mode=prof.language_mode,
                params=prof.params if isinstance(prof.params, dict) else {},
                updated_at=_dt_utc(prof.updated_at),
            )
        )

    @router.post("/targeting/profiles/preview", response_model=TargetingProfilePreviewOut)
    def preview_profile(
        payload: TargetingProfilePreviewIn,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        seg = payload.segment if payload.segment in {"A", "B", "C"} else None
        base = (
            select(CandidateFeatures, CandidateUser)
            .join(CandidateUser, CandidateUser.id == CandidateFeatures.candidate_id)
            .where(
                CandidateFeatures.workspace_id == workspace_id,
                CandidateUser.workspace_id == workspace_id,
                CandidateFeatures.targeting_profile_id == int(payload.profile_id),
            )
        )
        if seg is not None:
            base = base.where(CandidateFeatures.segment == seg)
        rows = db.execute(base.order_by(CandidateFeatures.send_score.desc()).limit(int(payload.limit))).all()

        cnt_stmt = (
            select(CandidateFeatures.segment, func.count(CandidateFeatures.id))
            .where(
                CandidateFeatures.workspace_id == workspace_id,
                CandidateFeatures.targeting_profile_id == int(payload.profile_id),
            )
            .group_by(CandidateFeatures.segment)
        )
        counts = {str(s): int(n) for s, n in db.execute(cnt_stmt).all()}
        top = [
            TargetingCandidateOut(
                candidate_id=int(c.id),
                tg_user_id=c.tg_user_id,
                username=c.username,
                display_name=c.display_name,
                last_seen_at=c.last_seen_at,
                segment=str(cf.segment),
                send_score=int(cf.send_score),
                warmth_score=int(cf.warmth_score),
                risk_score=int(cf.risk_score),
                source_count=int(cf.source_count),
                seen_as=str(cf.seen_as),
                topic_keywords=list(cf.topic_keywords or []),
                intent_flags=list(cf.intent_flags or []),
                reasons=cf.reasons if isinstance(cf.reasons, dict) else {},
            )
            for cf, c in rows
        ]
        return TargetingProfilePreviewOut(counts_by_segment=counts, top=top)

    return router

