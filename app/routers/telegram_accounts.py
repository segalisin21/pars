from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, BroadcastRun, CollectRun, InviteRun, TelegramAccount
from app.queue import get_rq_queue, is_queue_enabled
from app.routers.context import RouteContext
from app.schemas import (
    TelegramAccountCreate,
    TelegramAccountBusyOut,
    TelegramAccountOut,
    TelegramAccountPatch,
    TelegramAccountSpamBotCheckOut,
    TelegramAccountStatusOut,
    TelegramAccountsList,
    TelegramAccountsStatusList,
    TelegramAccountTestOut,
)
from app.worker_jobs import execute_spambot_check
from app.telegram_accounts_service import create_telegram_account, test_telegram_account_connection


def _account_out(acc: TelegramAccount) -> TelegramAccountOut:
    return TelegramAccountOut(
        id=acc.id,
        label=acc.label,
        last_username=acc.last_username,
        enabled=acc.enabled,
        created_at=acc.created_at,
        last_used_at=acc.last_used_at,
        last_ok_at=acc.last_ok_at,
        last_error_code=acc.last_error_code,
        last_error_at=acc.last_error_at,
        cooldown_until=acc.cooldown_until,
    )


def make_telegram_accounts_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["telegram-accounts"])
    get_db = ctx.get_db
    verify_admin_token = ctx.verify_admin_token
    rq_timeout = ctx.rq_timeout_seconds

    def _busy_for_account(db: Session, account_id: int) -> TelegramAccountBusyOut | None:
        active = {"queued", "running"}
        best: tuple[datetime, TelegramAccountBusyOut] | None = None

        rows = db.scalars(
            select(CollectRun).where(CollectRun.telegram_account_id == account_id).where(CollectRun.status.in_(active))
        ).all()
        for r in rows:
            if best is None or r.started_at > best[0]:
                best = (r.started_at, TelegramAccountBusyOut(kind="collect", run_id=r.id, status=r.status, started_at=r.started_at))

        rows2 = db.scalars(
            select(InviteRun).where(InviteRun.telegram_account_id == account_id).where(InviteRun.status.in_(active))
        ).all()
        for r in rows2:
            if best is None or r.started_at > best[0]:
                best = (r.started_at, TelegramAccountBusyOut(kind="invite", run_id=r.id, status=r.status, started_at=r.started_at))

        rows3 = db.scalars(
            select(BroadcastRun)
            .where(BroadcastRun.telegram_account_id == account_id)
            .where(BroadcastRun.status.in_(active))
        ).all()
        for r in rows3:
            if best is None or r.started_at > best[0]:
                best = (
                    r.started_at,
                    TelegramAccountBusyOut(kind="broadcast", run_id=r.id, status=r.status, started_at=r.started_at),
                )

        return best[1] if best is not None else None

    @router.get("/telegram-accounts", response_model=TelegramAccountsList)
    def list_accounts(db: Session = Depends(get_db), _auth=Depends(verify_admin_token)):
        rows = db.scalars(select(TelegramAccount).order_by(TelegramAccount.id.asc())).all()
        return TelegramAccountsList(items=[_account_out(a) for a in rows])

    @router.get("/telegram-accounts/status", response_model=TelegramAccountsStatusList)
    def list_accounts_status(db: Session = Depends(get_db), _auth=Depends(verify_admin_token)):
        rows = db.scalars(select(TelegramAccount).order_by(TelegramAccount.id.asc())).all()
        items: list[TelegramAccountStatusOut] = []
        for a in rows:
            items.append(
                TelegramAccountStatusOut(
                    account=_account_out(a),
                    busy=_busy_for_account(db, a.id),
                    spambot_status_text=a.spambot_status_text,
                    spambot_checked_at=a.spambot_checked_at,
                    spambot_error=a.spambot_error,
                )
            )
        return TelegramAccountsStatusList(items=items)

    @router.post("/telegram-accounts", response_model=TelegramAccountOut, status_code=201)
    def create_account(
        payload: TelegramAccountCreate,
        db: Session = Depends(get_db),
        _auth=Depends(verify_admin_token),
    ):
        try:
            acc = create_telegram_account(db, label=payload.label, session_string=payload.session_string)
        except RuntimeError as e:
            raise HTTPException(
                status_code=503,
                detail={"error": {"code": "encryption_unavailable", "message": str(e), "details": {}}},
            ) from e
        db.commit()
        db.refresh(acc)
        db.add(
            AuditEvent(
                workspace_id=1,
                action="telegram_account.create",
                entity_type="telegram_account",
                entity_id=acc.id,
                meta={"label": acc.label},
            )
        )
        db.commit()
        return _account_out(acc)

    @router.patch("/telegram-accounts/{account_id}", response_model=TelegramAccountOut)
    def patch_account(
        account_id: int,
        payload: TelegramAccountPatch,
        db: Session = Depends(get_db),
        _auth=Depends(verify_admin_token),
    ):
        acc = db.get(TelegramAccount, account_id)
        if acc is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": "Telegram account not found", "details": {"id": account_id}}},
            )
        if payload.label is not None:
            acc.label = payload.label.strip()[:128]
        if payload.enabled is not None:
            acc.enabled = payload.enabled
        db.commit()
        db.refresh(acc)
        db.add(
            AuditEvent(
                workspace_id=1,
                action="telegram_account.patch",
                entity_type="telegram_account",
                entity_id=acc.id,
                meta={"enabled": acc.enabled},
            )
        )
        db.commit()
        return _account_out(acc)

    @router.delete("/telegram-accounts/{account_id}", status_code=204)
    def delete_account(
        account_id: int,
        db: Session = Depends(get_db),
        _auth=Depends(verify_admin_token),
    ):
        acc = db.get(TelegramAccount, account_id)
        if acc is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": "Telegram account not found", "details": {"id": account_id}}},
            )
        db.delete(acc)
        db.add(
            AuditEvent(
                workspace_id=1,
                action="telegram_account.delete",
                entity_type="telegram_account",
                entity_id=account_id,
                meta={},
            )
        )
        db.commit()
        return None

    @router.post("/telegram-accounts/{account_id}/test", response_model=TelegramAccountTestOut)
    def test_account(
        account_id: int,
        db: Session = Depends(get_db),
        _auth=Depends(verify_admin_token),
    ):
        acc = db.get(TelegramAccount, account_id)
        if acc is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": "Telegram account not found", "details": {"id": account_id}}},
            )
        r = test_telegram_account_connection(db, account_id)
        db.commit()
        return TelegramAccountTestOut(ok=bool(r.get("ok")), username=r.get("username"), error=r.get("error"))

    @router.post("/telegram-accounts/{account_id}/spambot/check", response_model=TelegramAccountSpamBotCheckOut)
    def spambot_check(
        account_id: int,
        db: Session = Depends(get_db),
        _auth=Depends(verify_admin_token),
    ):
        acc = db.get(TelegramAccount, account_id)
        if acc is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": "Telegram account not found", "details": {"id": account_id}}},
            )
        if not is_queue_enabled():
            raise HTTPException(
                status_code=503,
                detail={"error": {"code": "queue_disabled", "message": "RQ queue is disabled", "details": {}}},
            )
        q = get_rq_queue()
        job = q.enqueue(
            execute_spambot_check,
            account_id=account_id,
            job_timeout=rq_timeout("RQ_SPAMBOT_TIMEOUT_SECONDS", 300),
        )
        acc.spambot_error = None
        db.commit()
        return TelegramAccountSpamBotCheckOut(enqueued=True, job_id=str(getattr(job, "id", None) or ""))

    return router
