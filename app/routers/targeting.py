from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from sqlalchemy import func

from app.models import CandidateProfileFeatures, CandidateUser, TargetingProfile, TargetingRun, TargetingRunLog, utcnow
from app.queue import get_rq_queue, is_queue_enabled
from app.openai_client import create_chat_json
from app.routers.context import RouteContext
from app.schemas import (
    PageMeta,
    TargetingAiSuggestIn,
    TargetingAiSuggestOut,
    TargetingAiSuggestDraftOut,
    TargetingApplyDraftOut,
    TargetingCandidateOut,
    TargetingCandidatesList,
    TargetingProfileCreateIn,
    TargetingProfileOut,
    TargetingProfilePatchIn,
    TargetingProfilePreviewIn,
    TargetingProfilePreviewOut,
    TargetingProfilesList,
    TargetingRunOut,
    TargetingRunStartOut,
)
from app.targeting_params import TargetingParamsV2, params_to_dict
from app.worker_jobs import execute_targeting_run


def _dt_utc(v: datetime) -> datetime:
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


def _profile_out(p: TargetingProfile) -> TargetingProfileOut:
    return TargetingProfileOut(
        id=int(p.id),
        name=str(p.name),
        query=str(p.query),
        language_mode=str(p.language_mode),
        params=p.params if isinstance(p.params, dict) else {},
        draft_params=p.draft_params if isinstance(p.draft_params, dict) else None,
        draft_updated_at=_dt_utc(p.draft_updated_at) if p.draft_updated_at else None,
        updated_at=_dt_utc(p.updated_at),
    )


def _json_diff(before: dict, after: dict) -> list[dict]:
    diff: list[dict] = []
    keys = sorted(set(before.keys()) | set(after.keys()))
    for k in keys:
        b = before.get(k, None)
        a = after.get(k, None)
        if b == a:
            continue
        diff.append({"path": k, "before": b, "after": a})
    return diff


def _suggest_sys_prompt() -> str:
    return (
        "You are a targeting assistant for Telegram audience selection.\n"
        "Return ONLY valid JSON that matches this strict schema (no extra keys):\n"
        "{\n"
        '  \"version\": \"v2\",\n'
        "  \"limits\": {\n"
        "    \"days\": int (1..365),\n"
        "    \"max_messages_per_source\": int (1..5000),\n"
        "    \"max_candidate_text_chars\": int (200..20000),\n"
        "    \"max_candidates\": int|null (1..200000)\n"
        "  },\n"
        "  \"terms\": {\n"
        "    \"keywords_include\": string[] (<=60 items, each 2..64 chars),\n"
        "    \"keywords_exclude\": string[] (<=60),\n"
        "    \"intent_phrases\": string[] (<=60)\n"
        "  },\n"
        "  \"weights\": { \"semantic\": float (0..5), \"warmth\": float (0..5), \"risk\": float (0..5) },\n"
        "  \"thresholds\": {\n"
        "    \"min_send_score\": int (-1000..1000),\n"
        "    \"segment_a_min\": int (-1000..1000),\n"
        "    \"segment_b_min\": int (-1000..1000, must be <= segment_a_min)\n"
        "  },\n"
        "  \"models\": { \"embedding_model\": string }\n"
        "}\n"
        "Language rules:\n"
        "- RU-first; if language_mode is mixed, include common EN synonyms too.\n"
        "- Prefer short, high-signal keywords and intent phrases.\n"
        "- Avoid any personal data, phone numbers, or names.\n"
    )


def make_targeting_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["targeting"])
    get_db = ctx.get_db
    get_workspace_id = ctx.get_workspace_id
    verify_admin_token = ctx.verify_admin_token
    rq_timeout = ctx.rq_timeout_seconds

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
            items=[_profile_out(p) for p in rows]
        )

    @router.post("/targeting/profiles", response_model=TargetingProfileOut, status_code=201)
    def create_profile(
        payload: TargetingProfileCreateIn,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        try:
            v2 = TargetingParamsV2.model_validate(payload.params)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "invalid_params", "message": "Invalid TargetingParamsV2", "details": {"error": str(e)}}},
            )
        now = utcnow()
        prof = TargetingProfile(
            workspace_id=workspace_id,
            name=(payload.name or payload.query).strip()[:128],
            query=payload.query.strip(),
            language_mode=payload.language_mode,
            params=params_to_dict(v2),
            created_at=now,
            updated_at=now,
        )
        db.add(prof)
        db.commit()
        db.refresh(prof)
        return _profile_out(prof)

    @router.patch("/targeting/profiles/{profile_id}", response_model=TargetingProfileOut)
    def patch_profile(
        profile_id: int,
        payload: TargetingProfilePatchIn,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        prof = db.get(TargetingProfile, int(profile_id))
        if prof is None or prof.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "targeting_profile_not_found", "message": "Targeting profile not found", "details": {"id": profile_id}}},
            )
        if payload.name is not None:
            prof.name = payload.name.strip()[:128]
        if payload.query is not None:
            prof.query = payload.query.strip()
        if payload.language_mode is not None:
            prof.language_mode = payload.language_mode
        if payload.params is not None:
            try:
                v2 = TargetingParamsV2.model_validate(payload.params)
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail={"error": {"code": "invalid_params", "message": "Invalid TargetingParamsV2", "details": {"error": str(e)}}},
                )
            prof.params = params_to_dict(v2)
        prof.updated_at = utcnow()
        db.commit()
        db.refresh(prof)
        return _profile_out(prof)

    @router.post("/targeting/profiles/{profile_id}/clone", response_model=TargetingProfileOut, status_code=201)
    def clone_profile(
        profile_id: int,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        src = db.get(TargetingProfile, int(profile_id))
        if src is None or src.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "targeting_profile_not_found", "message": "Targeting profile not found", "details": {"id": profile_id}}},
            )
        now = utcnow()
        prof = TargetingProfile(
            workspace_id=workspace_id,
            name=(f"{src.name} (copy)" if (src.name or "").strip() else f"{src.query} (copy)")[:128],
            query=src.query,
            language_mode=src.language_mode,
            params=src.params if isinstance(src.params, dict) else {},
            created_at=now,
            updated_at=now,
        )
        db.add(prof)
        db.commit()
        db.refresh(prof)
        return _profile_out(prof)

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
        sys = _suggest_sys_prompt()
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
        try:
            v2 = TargetingParamsV2.model_validate(params)
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail={
                    "error": {
                        "code": "openai_invalid_params",
                        "message": "OpenAI returned JSON but it does not match TargetingParamsV2",
                        "details": {"error": str(e)},
                    }
                },
            )

        name = (payload.name or payload.query).strip()[:128]
        now = utcnow()
        prof = TargetingProfile(
            workspace_id=workspace_id,
            name=name,
            query=payload.query.strip(),
            language_mode=payload.language_mode,
            params=params_to_dict(v2),
            created_at=now,
            updated_at=now,
        )
        db.add(prof)
        db.flush()
        return TargetingAiSuggestOut(
            profile=_profile_out(prof)
        )

    @router.post("/targeting/profiles/{profile_id}/ai-suggest", response_model=TargetingAiSuggestDraftOut)
    def ai_suggest_draft(
        profile_id: int,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        prof = db.get(TargetingProfile, int(profile_id))
        if prof is None or prof.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "targeting_profile_not_found", "message": "Targeting profile not found", "details": {"id": profile_id}}},
            )
        # Reuse suggest logic by calling the same OpenAI prompt with the current profile query.
        payload = TargetingAiSuggestIn(query=prof.query, language_mode=prof.language_mode, name=prof.name)
        # Call existing suggest implementation logic by duplicating minimal prompt.
        sys = _suggest_sys_prompt()
        user = f"Target: {payload.query}\nLanguage mode: {payload.language_mode}"
        res = create_chat_json(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
        )
        content = res["choices"][0]["message"]["content"]
        params = json.loads(content)
        v2 = TargetingParamsV2.model_validate(params)
        draft = params_to_dict(v2)
        before = prof.params if isinstance(prof.params, dict) else {}
        prof.draft_params = draft
        prof.draft_updated_at = utcnow()
        db.commit()
        return TargetingAiSuggestDraftOut(draft_params=draft, diff=_json_diff(before, draft))

    @router.post("/targeting/profiles/{profile_id}/apply-draft", response_model=TargetingApplyDraftOut)
    def apply_draft(
        profile_id: int,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        prof = db.get(TargetingProfile, int(profile_id))
        if prof is None or prof.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "targeting_profile_not_found", "message": "Targeting profile not found", "details": {"id": profile_id}}},
            )
        if not isinstance(prof.draft_params, dict):
            raise HTTPException(
                status_code=409,
                detail={"error": {"code": "no_draft", "message": "No draft params to apply", "details": {"id": profile_id}}},
            )
        try:
            v2 = TargetingParamsV2.model_validate(prof.draft_params)
        except Exception as e:
            raise HTTPException(
                status_code=409,
                detail={"error": {"code": "invalid_draft", "message": "Draft params are invalid", "details": {"error": str(e)}}},
            )
        prof.params = params_to_dict(v2)
        prof.draft_params = None
        prof.draft_updated_at = None
        prof.updated_at = utcnow()
        db.commit()
        db.refresh(prof)
        return TargetingApplyDraftOut(profile=_profile_out(prof))

    @router.post("/targeting/profiles/preview", response_model=TargetingProfilePreviewOut)
    def preview_profile(
        payload: TargetingProfilePreviewIn,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        seg = payload.segment if payload.segment in {"A", "B", "C"} else None
        base = (
            select(CandidateProfileFeatures, CandidateUser)
            .join(CandidateUser, CandidateUser.id == CandidateProfileFeatures.candidate_id)
            .where(
                CandidateProfileFeatures.workspace_id == workspace_id,
                CandidateUser.workspace_id == workspace_id,
                CandidateProfileFeatures.targeting_profile_id == int(payload.profile_id),
            )
        )
        if seg is not None:
            base = base.where(CandidateProfileFeatures.segment == seg)
        rows = db.execute(base.order_by(CandidateProfileFeatures.send_score.desc()).limit(int(payload.limit))).all()

        cnt_stmt = (
            select(CandidateProfileFeatures.segment, func.count(CandidateProfileFeatures.id))
            .where(
                CandidateProfileFeatures.workspace_id == workspace_id,
                CandidateProfileFeatures.targeting_profile_id == int(payload.profile_id),
            )
            .group_by(CandidateProfileFeatures.segment)
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

    @router.get("/targeting/profiles/{profile_id}/candidates/top", response_model=TargetingProfilePreviewOut)
    def list_candidates_top(
        profile_id: int,
        n: int = 50,
        segment: str | None = None,
        min_send_score: int | None = None,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        n = max(1, min(int(n), 500))
        seg = segment if segment in {"A", "B", "C"} else None
        stmt = (
            select(CandidateProfileFeatures, CandidateUser)
            .join(CandidateUser, CandidateUser.id == CandidateProfileFeatures.candidate_id)
            .where(
                CandidateProfileFeatures.workspace_id == workspace_id,
                CandidateUser.workspace_id == workspace_id,
                CandidateProfileFeatures.targeting_profile_id == int(profile_id),
            )
        )
        if seg is not None:
            stmt = stmt.where(CandidateProfileFeatures.segment == seg)
        if min_send_score is not None:
            stmt = stmt.where(CandidateProfileFeatures.send_score >= int(min_send_score))
        rows = db.execute(stmt.order_by(CandidateProfileFeatures.send_score.desc()).limit(n)).all()
        counts = {str(s): int(c) for s, c in db.execute(
            select(CandidateProfileFeatures.segment, func.count(CandidateProfileFeatures.id))
            .where(CandidateProfileFeatures.workspace_id == workspace_id, CandidateProfileFeatures.targeting_profile_id == int(profile_id))
            .group_by(CandidateProfileFeatures.segment)
        ).all()}
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

    @router.get("/targeting/profiles/{profile_id}/candidates", response_model=TargetingCandidatesList)
    def list_candidates(
        profile_id: int,
        limit: int = 50,
        offset: int = 0,
        segment: str | None = None,
        min_send_score: int | None = None,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        seg = segment if segment in {"A", "B", "C"} else None
        stmt = (
            select(CandidateProfileFeatures, CandidateUser)
            .join(CandidateUser, CandidateUser.id == CandidateProfileFeatures.candidate_id)
            .where(
                CandidateProfileFeatures.workspace_id == workspace_id,
                CandidateUser.workspace_id == workspace_id,
                CandidateProfileFeatures.targeting_profile_id == int(profile_id),
            )
        )
        if seg is not None:
            stmt = stmt.where(CandidateProfileFeatures.segment == seg)
        if min_send_score is not None:
            stmt = stmt.where(CandidateProfileFeatures.send_score >= int(min_send_score))
        rows = db.execute(stmt.order_by(CandidateProfileFeatures.send_score.desc()).limit(limit).offset(offset)).all()

        count_base = (
            select(CandidateProfileFeatures.id)
            .where(CandidateProfileFeatures.workspace_id == workspace_id, CandidateProfileFeatures.targeting_profile_id == int(profile_id))
        )
        if seg is not None:
            count_base = count_base.where(CandidateProfileFeatures.segment == seg)
        if min_send_score is not None:
            count_base = count_base.where(CandidateProfileFeatures.send_score >= int(min_send_score))
        total = db.scalar(select(func.count()).select_from(count_base.subquery())) or 0

        items = [
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
        return TargetingCandidatesList(items=items, page=PageMeta(limit=limit, offset=offset, total=int(total)))

    @router.post("/targeting/profiles/{profile_id}/start", response_model=TargetingRunStartOut, status_code=202)
    def start_targeting_run(
        profile_id: int,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        prof = db.get(TargetingProfile, int(profile_id))
        if prof is None or prof.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "targeting_profile_not_found", "message": "Targeting profile not found", "details": {"id": profile_id}}},
            )
        if not is_queue_enabled():
            raise HTTPException(
                status_code=409,
                detail={"error": {"code": "queue_not_configured", "message": "REDIS_URL is not set; cannot start async targeting run", "details": {}}},
            )

        now = utcnow()
        run = TargetingRun(
            workspace_id=workspace_id,
            profile_id=int(prof.id),
            status="queued",
            stage="queued",
            progress={},
            error={},
            created_at=now,
            updated_at=now,
            started_at=None,
            finished_at=None,
        )
        db.add(run)
        db.flush()
        db.add(TargetingRunLog(workspace_id=workspace_id, run_id=run.id, msg="queued"))
        db.commit()

        q = get_rq_queue()
        q.enqueue(
            execute_targeting_run,
            run_id=run.id,
            job_timeout=rq_timeout("RQ_TARGETING_TIMEOUT_SECONDS", 3600),
        )
        return TargetingRunStartOut(run_id=int(run.id))

    @router.get("/targeting/runs/{run_id}", response_model=TargetingRunOut)
    def get_targeting_run(
        run_id: int,
        db: Session = Depends(get_db),
        workspace_id: int = Depends(get_workspace_id),
        _auth=Depends(verify_admin_token),
    ):
        run = db.get(TargetingRun, int(run_id))
        if run is None or run.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "targeting_run_not_found", "message": "Targeting run not found", "details": {"id": run_id}}},
            )
        logs = db.scalars(
            select(TargetingRunLog).where(TargetingRunLog.workspace_id == workspace_id, TargetingRunLog.run_id == run.id).order_by(TargetingRunLog.id.desc()).limit(50)
        ).all()
        logs_out = [{"id": int(l.id), "msg": str(l.msg), "created_at": _dt_utc(l.created_at)} for l in reversed(logs)]
        return TargetingRunOut(
            id=int(run.id),
            profile_id=int(run.profile_id),
            status=str(run.status),
            stage=str(run.stage),
            progress=run.progress if isinstance(run.progress, dict) else {},
            error=run.error if isinstance(run.error, dict) else {},
            created_at=_dt_utc(run.created_at),
            updated_at=_dt_utc(run.updated_at),
            started_at=_dt_utc(run.started_at) if run.started_at else None,
            finished_at=_dt_utc(run.finished_at) if run.finished_at else None,
            logs=logs_out,  # pydantic will coerce dicts to TargetingRunLogOut
        )

    return router

