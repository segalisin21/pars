from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from app.telegram_client import FloodWaitError, TelegramClient, TgUser


@dataclass(frozen=True)
class TelethonConfig:
    api_id: int
    api_hash: str
    session_string: str


def _get_telegram_api() -> tuple[int, str]:
    api_id = os.getenv("TG_API_ID") or os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TG_API_HASH") or os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise RuntimeError("TG_API_ID and TG_API_HASH are required")
    return int(api_id), str(api_hash)


def _get_session_string() -> str:
    v = os.getenv("TG_SESSION_STRING") or os.getenv("TELEGRAM_SESSION_STRING")
    if not v:
        raise RuntimeError("TG_SESSION_STRING is required")
    return str(v)


def _normalize_identifier(identifier: str) -> str:
    s = identifier.strip()
    if s.startswith("@"):
        s = s[1:]
    return s


class TelethonTelegramClient(TelegramClient):
    """
    Minimal synchronous adapter over Telethon.
    - Used only in `worker` (Railway) where real Telegram access is required.
    - All network work happens inside a short-lived Telethon client session.
    """

    def __init__(self, cfg: TelethonConfig):
        self._cfg = cfg

    @classmethod
    def from_env(cls) -> "TelethonTelegramClient":
        api_id, api_hash = _get_telegram_api()
        session_string = _get_session_string()
        return cls(TelethonConfig(api_id=api_id, api_hash=api_hash, session_string=session_string))

    def get_participants(self, source_identifier: str) -> list[TgUser]:
        return asyncio.run(self._get_participants_async(source_identifier))

    def invite_to_target(self, target_identifier: str, tg_user_id: int) -> None:
        asyncio.run(self._invite_to_target_async(target_identifier, tg_user_id))

    async def _get_participants_async(self, source_identifier: str) -> list[TgUser]:
        try:
            from telethon import TelegramClient as _TelethonClient  # type: ignore
            from telethon.sessions import StringSession  # type: ignore
            from telethon.errors import FloodWaitError as _TelethonFloodWait  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("Telethon is not installed") from e

        ident = _normalize_identifier(source_identifier)
        client = _TelethonClient(StringSession(self._cfg.session_string), self._cfg.api_id, self._cfg.api_hash)
        try:
            await client.connect()
            entity = await client.get_entity(ident)
            out: list[TgUser] = []
            async for u in client.iter_participants(entity):
                first = getattr(u, "first_name", None) or ""
                last = getattr(u, "last_name", None) or ""
                name = (first + " " + last).strip() or None
                out.append(
                    TgUser(
                        tg_user_id=getattr(u, "id", None),
                        username=getattr(u, "username", None),
                        display_name=name,
                    )
                )
            return out
        except _TelethonFloodWait as e:  # pragma: no cover (network)
            raise FloodWaitError(int(getattr(e, "seconds", 0)))
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def _invite_to_target_async(self, target_identifier: str, tg_user_id: int) -> None:
        try:
            from telethon import TelegramClient as _TelethonClient  # type: ignore
            from telethon.sessions import StringSession  # type: ignore
            from telethon.errors import FloodWaitError as _TelethonFloodWait  # type: ignore
            from telethon.tl.functions.channels import InviteToChannelRequest  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("Telethon is not installed") from e

        ident = _normalize_identifier(target_identifier)
        client = _TelethonClient(StringSession(self._cfg.session_string), self._cfg.api_id, self._cfg.api_hash)
        try:
            await client.connect()
            entity = await client.get_entity(ident)
            await client(InviteToChannelRequest(channel=entity, users=[tg_user_id]))
        except _TelethonFloodWait as e:  # pragma: no cover (network)
            raise FloodWaitError(int(getattr(e, "seconds", 0)))
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

