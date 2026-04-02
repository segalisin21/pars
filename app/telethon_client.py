from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from app.telegram_client import FloodWaitError, SourceTelegramMeta, TelegramClient, TgUser


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

    def invite_to_target(self, target_identifier: str, tg_user_id: int) -> None:
        try:
            from telethon.sync import TelegramClient as _TelethonClient  # type: ignore
            from telethon.sessions import StringSession  # type: ignore
            from telethon.errors import FloodWaitError as _TelethonFloodWait  # type: ignore
            from telethon.tl.functions.channels import InviteToChannelRequest  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("Telethon is not installed") from e

        ident = _normalize_identifier(target_identifier)
        client = _TelethonClient(StringSession(self._cfg.session_string), self._cfg.api_id, self._cfg.api_hash)
        try:
            client.connect()
            entity = client.get_entity(ident)
            client(InviteToChannelRequest(channel=entity, users=[tg_user_id]))
        except _TelethonFloodWait as e:  # pragma: no cover (network)
            raise FloodWaitError(int(getattr(e, "seconds", 0)))
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    def iter_participants(self, source_identifier: str) -> Iterable[TgUser]:
        try:
            from telethon.sync import TelegramClient as _TelethonClient  # type: ignore
            from telethon.sessions import StringSession  # type: ignore
            from telethon.errors import FloodWaitError as _TelethonFloodWait  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("Telethon is not installed") from e

        ident = _normalize_identifier(source_identifier)
        client = _TelethonClient(StringSession(self._cfg.session_string), self._cfg.api_id, self._cfg.api_hash)
        try:
            client.connect()
            entity = client.get_entity(ident)
            for u in client.iter_participants(entity):
                first = getattr(u, "first_name", None) or ""
                last = getattr(u, "last_name", None) or ""
                name = (first + " " + last).strip() or None
                yield TgUser(
                    tg_user_id=getattr(u, "id", None),
                    username=getattr(u, "username", None),
                    display_name=name,
                )
        except _TelethonFloodWait as e:  # pragma: no cover (network)
            raise FloodWaitError(int(getattr(e, "seconds", 0)))
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    def fetch_source_meta(self, source_identifier: str) -> SourceTelegramMeta | None:
        try:
            from telethon.sync import TelegramClient as _TelethonClient  # type: ignore
            from telethon.sessions import StringSession  # type: ignore
            from telethon.tl.functions.channels import GetFullChannelRequest  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("Telethon is not installed") from e

        ident = _normalize_identifier(source_identifier)
        client = _TelethonClient(StringSession(self._cfg.session_string), self._cfg.api_id, self._cfg.api_hash)
        try:
            client.connect()
            entity = client.get_entity(ident)
            title = getattr(entity, "title", None)
            participants_count: int | None = getattr(entity, "participants_count", None)
            if participants_count is None and (
                getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False)
            ):
                full = client(GetFullChannelRequest(channel=entity))
                pc = getattr(full.full_chat, "participants_count", None)
                participants_count = int(pc) if pc is not None else None
            return SourceTelegramMeta(title=title, participants_count=participants_count)
        except Exception:
            return None
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

