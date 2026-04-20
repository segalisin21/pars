from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

# In-memory pending auth state (token -> {phone, phone_code_hash, session_string, created_at})
_pending: dict[str, dict] = {}
_PENDING_TTL_SECONDS = 600


def _cleanup_expired() -> None:
    now = time.time()
    for token in list(_pending.keys()):
        if now - float(_pending[token].get("created_at", 0)) > _PENDING_TTL_SECONDS:
            del _pending[token]


def _get_telegram_api(api_id: Optional[int] = None, api_hash: Optional[str] = None) -> tuple[Optional[int], Optional[str]]:
    if api_id and api_hash:
        try:
            return int(api_id), str(api_hash)
        except Exception:
            return None, None
    api_id = os.getenv("TG_API_ID") or os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TG_API_HASH") or os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        return None, None
    try:
        return int(api_id), api_hash
    except Exception:
        return None, None


@dataclass(frozen=True)
class RequestCodeResult:
    token: str | None
    error: str | None


@dataclass(frozen=True)
class VerifyCodeResult:
    success: bool
    session_string: str | None
    error: str | None


async def request_code(phone: str, api_id: Optional[int] = None, api_hash: Optional[str] = None) -> RequestCodeResult:
    """
    Sends Telegram login code to the given phone.
    Returns a temporary token used for verify_code().
    """
    try:
        from telethon import TelegramClient  # type: ignore
        from telethon.sessions import StringSession  # type: ignore
        from telethon.errors import FloodWaitError  # type: ignore
    except Exception:
        return RequestCodeResult(token=None, error="Telethon не установлен. Установите зависимости (telethon).")

    api_id, api_hash = _get_telegram_api(api_id=api_id, api_hash=api_hash)
    if not api_id or not api_hash:
        return RequestCodeResult(token=None, error="TG_API_ID и TG_API_HASH не заданы в переменных окружения.")

    phone = phone.strip()
    if not phone:
        return RequestCodeResult(token=None, error="Телефон не задан.")

    session = StringSession()
    client = TelegramClient(session, api_id, api_hash)
    try:
        await client.connect()
        if await client.is_user_authorized():
            session_string = client.session.save()
            await client.disconnect()
            return RequestCodeResult(token=None, error=f"Уже авторизован. SESSION: {session_string}")

        sent = await client.send_code_request(phone)
        await client.disconnect()

        token = secrets.token_urlsafe(32)
        _cleanup_expired()
        _pending[token] = {
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
            "session_string": session.save(),
            "created_at": time.time(),
        }
        return RequestCodeResult(token=token, error=None)
    except FloodWaitError as e:  # pragma: no cover (network)
        try:
            await client.disconnect()
        except Exception:
            pass
        return RequestCodeResult(token=None, error=f"Подождите {getattr(e, 'seconds', 0)} сек. перед повторной попыткой.")
    except Exception as e:  # pragma: no cover (network)
        try:
            await client.disconnect()
        except Exception:
            pass
        return RequestCodeResult(token=None, error=str(e))


async def verify_code(
    token: str,
    code: str,
    password: Optional[str] = None,
    *,
    api_id: Optional[int] = None,
    api_hash: Optional[str] = None,
) -> VerifyCodeResult:
    """
    Completes sign-in by code (and optional 2FA password).
    On success returns a Telethon StringSession string to store in TG_SESSION_STRING.
    """
    try:
        from telethon import TelegramClient  # type: ignore
        from telethon.sessions import StringSession  # type: ignore
        from telethon.errors import PhoneCodeExpiredError, PhoneCodeInvalidError, SessionPasswordNeededError  # type: ignore
    except Exception:
        return VerifyCodeResult(False, None, "Telethon не установлен.")

    _cleanup_expired()
    data = _pending.get(token)
    if not data:
        return VerifyCodeResult(False, None, "Код истёк или неверный токен. Начните заново.")

    api_id, api_hash = _get_telegram_api(api_id=api_id, api_hash=api_hash)
    if not api_id or not api_hash:
        return VerifyCodeResult(False, None, "TG_API_ID и TG_API_HASH не заданы в переменных окружения.")

    phone = str(data.get("phone") or "").strip()
    phone_code_hash = str(data.get("phone_code_hash") or "")
    pending_session_string = str(data.get("session_string") or "")

    # Reuse the same StringSession that requested the code.
    client = TelegramClient(StringSession(pending_session_string), api_id, api_hash)
    try:
        await client.connect()
        if password:
            await client.sign_in(password=password)
        else:
            try:
                await client.sign_in(phone=phone, code=code.strip(), phone_code_hash=phone_code_hash)
            except SessionPasswordNeededError:
                await client.disconnect()
                return VerifyCodeResult(False, None, "NEEDS_PASSWORD")
            except PhoneCodeExpiredError:
                del _pending[token]
                await client.disconnect()
                return VerifyCodeResult(False, None, "Код истёк. Запросите новый.")
            except PhoneCodeInvalidError:
                del _pending[token]
                await client.disconnect()
                return VerifyCodeResult(False, None, "Неверный код. Запросите новый.")

        del _pending[token]
        session_string = client.session.save()
        await client.disconnect()
        return VerifyCodeResult(True, session_string, None)
    except Exception as e:  # pragma: no cover (network)
        try:
            await client.disconnect()
        except Exception:
            pass
        return VerifyCodeResult(False, None, str(e))

