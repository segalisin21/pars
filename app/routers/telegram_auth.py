from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.routers.context import RouteContext
from app.schemas import (
    TelegramAppCredentialsOut,
    TelegramAppCredentialsPutIn,
    TelegramRequestCodeIn,
    TelegramRequestCodeOut,
    TelegramVerifyCodeIn,
    TelegramVerifyCodeOut,
)
from app.models import TelegramAppCredentials
from app.telegram_app_credentials_service import get_telegram_api, set_telegram_api
from app.telegram_auth_web import request_code as tg_request_code
from app.telegram_auth_web import verify_code as tg_verify_code


def make_telegram_auth_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["telegram-auth"])
    verify_admin_token = ctx.verify_admin_token
    get_db = ctx.get_db

    @router.get("/telegram/app-credentials", response_model=TelegramAppCredentialsOut)
    def telegram_get_app_credentials(db: Session = Depends(get_db), _auth=Depends(verify_admin_token)):
        api_id, api_hash = get_telegram_api(db)
        row = db.get(TelegramAppCredentials, 1)
        _ = api_hash
        return TelegramAppCredentialsOut(
            configured=bool(api_id and api_hash),
            api_id=api_id,
            updated_at=getattr(row, "updated_at", None) if row is not None else None,
        )

    @router.put("/telegram/app-credentials", response_model=TelegramAppCredentialsOut)
    def telegram_put_app_credentials(
        payload: TelegramAppCredentialsPutIn,
        db: Session = Depends(get_db),
        _auth=Depends(verify_admin_token),
    ):
        try:
            row = set_telegram_api(db, api_id=payload.api_id, api_hash=payload.api_hash)
        except ValueError as e:
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "validation_error", "message": str(e), "details": {}}},
            ) from e
        db.commit()
        return TelegramAppCredentialsOut(configured=True, api_id=payload.api_id, updated_at=row.updated_at)

    @router.post("/telegram/auth/request_code", response_model=TelegramRequestCodeOut)
    async def telegram_request_code(
        payload: TelegramRequestCodeIn,
        db: Session = Depends(get_db),
        _auth=Depends(verify_admin_token),
    ):
        api_id, api_hash = get_telegram_api(db)
        r = await tg_request_code(payload.phone, api_id=api_id, api_hash=api_hash)
        return TelegramRequestCodeOut(token=r.token, error=r.error)

    @router.post("/telegram/auth/verify_code", response_model=TelegramVerifyCodeOut)
    async def telegram_verify_code(
        payload: TelegramVerifyCodeIn,
        db: Session = Depends(get_db),
        _auth=Depends(verify_admin_token),
    ):
        api_id, api_hash = get_telegram_api(db)
        r = await tg_verify_code(payload.token, payload.code, password=payload.password, api_id=api_id, api_hash=api_hash)
        return TelegramVerifyCodeOut(success=r.success, session_string=r.session_string, error=r.error)

    return router
