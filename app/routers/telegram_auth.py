from __future__ import annotations

from fastapi import APIRouter, Depends

from app.routers.context import RouteContext
from app.schemas import TelegramRequestCodeIn, TelegramRequestCodeOut, TelegramVerifyCodeIn, TelegramVerifyCodeOut
from app.telegram_auth_web import request_code as tg_request_code
from app.telegram_auth_web import verify_code as tg_verify_code


def make_telegram_auth_router(ctx: RouteContext) -> APIRouter:
    router = APIRouter(tags=["telegram-auth"])
    verify_admin_token = ctx.verify_admin_token

    @router.post("/telegram/auth/request_code", response_model=TelegramRequestCodeOut)
    async def telegram_request_code(payload: TelegramRequestCodeIn, _auth=Depends(verify_admin_token)):
        r = await tg_request_code(payload.phone)
        return TelegramRequestCodeOut(token=r.token, error=r.error)

    @router.post("/telegram/auth/verify_code", response_model=TelegramVerifyCodeOut)
    async def telegram_verify_code(payload: TelegramVerifyCodeIn, _auth=Depends(verify_admin_token)):
        r = await tg_verify_code(payload.token, payload.code, password=payload.password)
        return TelegramVerifyCodeOut(success=r.success, session_string=r.session_string, error=r.error)

    return router
