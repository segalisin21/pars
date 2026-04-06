"""Encrypt/decrypt secrets at rest (Telegram session strings)."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


def get_fernet() -> Fernet:
    raw = (os.getenv("APP_ENCRYPTION_KEY") or "").strip()
    if not raw:
        raise RuntimeError("APP_ENCRYPTION_KEY is required to store Telegram session strings")
    try:
        return Fernet(raw.encode("utf-8"))
    except Exception as e:  # pragma: no cover
        raise RuntimeError("APP_ENCRYPTION_KEY must be a valid Fernet key (URL-safe base64)") from e


def encrypt_string(plaintext: str, *, key_version: int = 1) -> tuple[str, int]:
    _ = key_version
    f = get_fernet()
    token = f.encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii"), 1


def decrypt_string(ciphertext: str, *, key_version: int = 1) -> str:
    _ = key_version
    f = get_fernet()
    try:
        return f.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("decryption_failed") from e
