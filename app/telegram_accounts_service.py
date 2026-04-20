"""Global Telegram account pool: selection, encryption, Telethon client factory."""

from __future__ import annotations

import logging
import os
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.crypto import decrypt_string, encrypt_string
from app.models import TelegramAccount, utcnow
from app.telegram_app_credentials_service import get_telegram_api as _get_telegram_api_from_db
from app.telethon_client import TelethonConfig, TelethonTelegramClient
from app.telegram_client import TelegramClient

logger = logging.getLogger(__name__)


def create_telegram_account(
    db: Session,
    *,
    label: str,
    session_string: str,
) -> TelegramAccount:
    enc, ver = encrypt_string(session_string.strip())
    acc = TelegramAccount(
        label=(label or "").strip() or "account",
        enabled=True,
        session_string_encrypted=enc,
        session_string_key_version=ver,
    )
    db.add(acc)
    db.flush()
    return acc


def select_telegram_account(
    db: Session,
    preferred_id: int | None,
) -> TelegramAccount | None:
    """Pick an enabled account: preferred if valid, else LRU among eligible (cooldown passed)."""
    now = utcnow()
    if preferred_id is not None:
        acc = db.get(TelegramAccount, preferred_id)
        if acc is None or not acc.enabled:
            return None
        if acc.cooldown_until is not None and acc.cooldown_until > now:
            return None
        return acc

    stmt = (
        select(TelegramAccount)
        .where(TelegramAccount.enabled.is_(True))
        .where(or_(TelegramAccount.cooldown_until.is_(None), TelegramAccount.cooldown_until <= now))
        .order_by(TelegramAccount.last_used_at.asc().nulls_first(), TelegramAccount.id.asc())
    )
    return db.scalar(stmt)


def _client_from_account(db: Session, acc: TelegramAccount) -> TelethonTelegramClient:
    session_string = decrypt_string(acc.session_string_encrypted, key_version=acc.session_string_key_version)
    api_id, api_hash = _get_telegram_api(db)
    return TelethonTelegramClient(TelethonConfig(api_id=api_id, api_hash=api_hash, session_string=session_string))


def telethon_client_for_account(db: Session, account_id: int) -> TelethonTelegramClient:
    acc = db.get(TelegramAccount, account_id)
    if acc is None:
        raise RuntimeError("telegram_account_not_found")
    if not acc.enabled:
        raise RuntimeError("telegram_account_disabled")
    return _client_from_account(db, acc)


def resolve_telegram_client_for_run(
    db: Session,
    *,
    preferred_account_id: int | None,
) -> tuple[TelegramClient, TelegramAccount | None]:
    """
    Returns (client, account_used).
    Falls back to TG_SESSION_STRING / env Telethon when no DB accounts or selection fails.
    """
    acc = select_telegram_account(db, preferred_account_id)
    if acc is not None:
        try:
            client = _client_from_account(db, acc)
        except ValueError:
            logger.exception("telegram_account decrypt failed account_id=%s", acc.id)
            acc.last_error_code = "decrypt_failed"
            acc.last_error_at = utcnow()
            db.flush()
            raise RuntimeError("telegram_account_decrypt_failed") from None

        acc.last_used_at = utcnow()
        acc.last_ok_at = utcnow()
        acc.last_error_code = None
        db.flush()
        return client, acc

    try:
        return TelethonTelegramClient.from_env(), None
    except Exception:
        logger.warning("no DB telegram account and TG_SESSION_STRING missing")
        raise


def prepare_telegram_client_for_worker_run(
    db: Session,
    run,
    preferred_account_id: int | None,
) -> tuple[TelegramClient, TelegramAccount | None]:
    """
    If run.telegram_account_id is unset, auto-select an account and persist on the run.
    Then build Telethon client from that account, or fall back to env session string.
    """
    rid = getattr(run, "telegram_account_id", None)
    if rid is None:
        acc = select_telegram_account(db, preferred_account_id)
        if acc is not None:
            run.telegram_account_id = acc.id
            db.flush()

    rid2 = getattr(run, "telegram_account_id", None)
    if rid2 is not None:
        acc = db.get(TelegramAccount, rid2)
        if acc is None or not acc.enabled:
            raise RuntimeError("telegram_account_invalid")
        now = utcnow()
        if acc.cooldown_until is not None and acc.cooldown_until > now:
            raise RuntimeError("telegram_account_in_cooldown")
        try:
            client = _client_from_account(db, acc)
        except ValueError:
            acc.last_error_code = "decrypt_failed"
            acc.last_error_at = utcnow()
            db.flush()
            raise RuntimeError("telegram_account_decrypt_failed") from None
        acc.last_used_at = utcnow()
        acc.last_ok_at = utcnow()
        acc.last_error_code = None
        db.flush()
        return client, acc

    return resolve_telegram_client_for_run(db, preferred_account_id=None)


def _get_telegram_api_from_env() -> tuple[int, str]:
    api_id = os.getenv("TG_API_ID") or os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TG_API_HASH") or os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise RuntimeError("TG_API_ID and TG_API_HASH are required")
    return int(api_id), str(api_hash)


def _get_telegram_api(db: Session) -> tuple[int, str]:
    api_id, api_hash = _get_telegram_api_from_db(db)
    if api_id and api_hash:
        return int(api_id), str(api_hash)
    return _get_telegram_api_from_env()


def mark_account_cooldown(db: Session, account_id: int | None, until: datetime | None) -> None:
    if account_id is None or until is None:
        return
    acc = db.get(TelegramAccount, account_id)
    if acc is None:
        return
    if acc.cooldown_until is None or until > acc.cooldown_until:
        acc.cooldown_until = until
    acc.last_error_code = "flood_wait"
    acc.last_error_at = utcnow()
    db.flush()


def test_telegram_account_connection(db: Session, account_id: int) -> dict:
    """Verify session with Telegram; updates last_ok_at / last_error_* on the row."""
    acc = db.get(TelegramAccount, account_id)
    if acc is None:
        return {"ok": False, "error": "not_found", "username": None}
    try:
        client = _client_from_account(db, acc)
    except ValueError:
        acc.last_error_code = "decrypt_failed"
        acc.last_error_at = utcnow()
        db.flush()
        return {"ok": False, "error": "decrypt_failed", "username": None}
    ok, username, err = client.verify_session()
    if ok:
        acc.last_ok_at = utcnow()
        acc.last_username = username
        acc.last_error_code = None
    else:
        acc.last_error_code = err or "verify_failed"
        acc.last_error_at = utcnow()
    db.flush()
    return {"ok": ok, "error": err, "username": username}
