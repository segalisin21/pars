from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, TelegramAccount
from app.routers.context import RouteContext
from app.schemas import (
    TelegramAccountCreate,
    TelegramAccountOut,
    TelegramAccountPatch,
    TelegramAccountsList,
    TelegramAccountTestOut,
)
from app.telegram_accounts_service import create_telegram_account, test_telegram_account_connection


def _account_out(acc: TelegramAccount) -> TelegramAccountOut:
    return TelegramAccountOut(
        id=acc.id,
        label=acc.label,
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

    @router.get("/telegram-accounts", response_model=TelegramAccountsList)
    def list_accounts(db: Session = Depends(get_db), _auth=Depends(verify_admin_token)):
        rows = db.scalars(select(TelegramAccount).order_by(TelegramAccount.id.asc())).all()
        return TelegramAccountsList(items=[_account_out(a) for a in rows])

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

    return router
