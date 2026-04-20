from __future__ import annotations

from sqlalchemy.orm import Session

from app.crypto import decrypt_string, encrypt_string
from app.models import TelegramAppCredentials, utcnow


def get_telegram_api(db: Session) -> tuple[int | None, str | None]:
    """
    Prefer DB-stored Telegram App credentials (encrypted), otherwise return (None, None).
    Callers may fall back to env when None.
    """
    row = db.get(TelegramAppCredentials, 1)
    if row is None:
        return None, None
    if not row.api_id_encrypted or not row.api_hash_encrypted:
        return None, None
    try:
        api_id_raw = decrypt_string(row.api_id_encrypted, key_version=row.key_version).strip()
        api_hash = decrypt_string(row.api_hash_encrypted, key_version=row.key_version).strip()
        if not api_id_raw or not api_hash:
            return None, None
        return int(api_id_raw), api_hash
    except Exception:
        return None, None


def set_telegram_api(db: Session, *, api_id: int, api_hash: str) -> TelegramAppCredentials:
    api_hash = (api_hash or "").strip()
    if not api_hash:
        raise ValueError("api_hash_required")

    enc_id, ver = encrypt_string(str(int(api_id)).strip())
    enc_hash, _ = encrypt_string(api_hash, key_version=ver)

    row = db.get(TelegramAppCredentials, 1)
    if row is None:
        row = TelegramAppCredentials(id=1)
        db.add(row)

    row.api_id_encrypted = enc_id
    row.api_hash_encrypted = enc_hash
    row.key_version = ver
    row.updated_at = utcnow()
    db.flush()
    return row

