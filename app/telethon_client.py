from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from app.telegram_client import (
    DirectMessageSendResult,
    FloodWaitError,
    SourceTelegramMeta,
    TelegramClient,
    TgMessageSnippet,
    TgUser,
)


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


def _resolved_user_id_from_message(msg) -> int | None:
    """Best-effort numeric peer user id from a Telethon Message (private chat)."""
    if msg is None:
        return None
    try:
        from telethon.tl.types import PeerUser  # type: ignore
    except Exception:
        PeerUser = None  # type: ignore[misc, assignment]
    if PeerUser is not None:
        pid = getattr(msg, "peer_id", None)
        if isinstance(pid, PeerUser):
            return int(pid.user_id)
        to_id = getattr(msg, "to_id", None)
        if isinstance(to_id, PeerUser):
            return int(to_id.user_id)
    uid = getattr(getattr(msg, "peer_id", None), "user_id", None)
    if uid is not None:
        try:
            return int(uid)
        except (TypeError, ValueError):
            pass
    uid2 = getattr(getattr(msg, "to_id", None), "user_id", None)
    if uid2 is not None:
        try:
            return int(uid2)
        except (TypeError, ValueError):
            pass
    return None


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

    def verify_session(self) -> tuple[bool, str | None, str | None]:
        """Connect, call get_me(), disconnect. Returns (ok, username_or_none, error_message_or_none)."""
        try:
            from telethon.sync import TelegramClient as _TelethonClient  # type: ignore
            from telethon.sessions import StringSession  # type: ignore
        except Exception as e:  # pragma: no cover
            return False, None, str(e)

        client = _TelethonClient(StringSession(self._cfg.session_string), self._cfg.api_id, self._cfg.api_hash)
        try:
            client.connect()
            if not client.is_user_authorized():
                return False, None, "not_authorized"
            me = client.get_me()
            un = getattr(me, "username", None) or None
            return True, un, None
        except Exception as e:
            return False, None, type(e).__name__
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    def fetch_spambot_status(self) -> tuple[bool, str | None, str | None]:
        """
        Best-effort anti-spam status via @SpamBot.
        Sends /start then returns the latest bot message text.
        """
        try:
            from telethon.sync import TelegramClient as _TelethonClient  # type: ignore
            from telethon.sessions import StringSession  # type: ignore
        except Exception as e:  # pragma: no cover
            return False, None, str(e)

        client = _TelethonClient(StringSession(self._cfg.session_string), self._cfg.api_id, self._cfg.api_hash)
        try:
            client.connect()
            if not client.is_user_authorized():
                return False, None, "not_authorized"
            client.send_message("SpamBot", "/start")
            msgs = client.get_messages("SpamBot", limit=1)
            if not msgs:
                return False, None, "no_response"
            m = msgs[0]
            txt = getattr(m, "message", None)
            if not isinstance(txt, str) or not txt.strip():
                return False, None, "empty_response"
            return True, txt.strip(), None
        except Exception as e:
            return False, None, type(e).__name__
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

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

    def supports_outbox_verify(self) -> bool:  # noqa: D102
        return True

    def send_direct_message(
        self,
        text: str,
        *,
        tg_user_id: int | None = None,
        username: str | None = None,
    ) -> DirectMessageSendResult:
        if (tg_user_id is None) == (username is None):
            raise ValueError("send_direct_message requires exactly one of tg_user_id or username")
        try:
            from telethon.sync import TelegramClient as _TelethonClient  # type: ignore
            from telethon.sessions import StringSession  # type: ignore
            from telethon.errors import FloodWaitError as _TelethonFloodWait  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("Telethon is not installed") from e

        target: int | str = int(tg_user_id) if tg_user_id is not None else _normalize_identifier(username or "")
        client = _TelethonClient(StringSession(self._cfg.session_string), self._cfg.api_id, self._cfg.api_hash)
        try:
            client.connect()
            msg = client.send_message(target, text)
            mid = int(getattr(msg, "id", 0) or 0) or None
            out = bool(getattr(msg, "out", True))
            resolved = _resolved_user_id_from_message(msg) if username is not None else None
            return DirectMessageSendResult(message_id=mid, out=out, resolved_tg_user_id=resolved)
        except _TelethonFloodWait as e:  # pragma: no cover (network)
            raise FloodWaitError(int(getattr(e, "seconds", 0)))
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    def verify_direct_message_outbox(
        self,
        message_id: int,
        *,
        tg_user_id: int | None = None,
        username: str | None = None,
    ) -> bool:
        if (tg_user_id is None) == (username is None):
            raise ValueError("verify_direct_message_outbox requires exactly one of tg_user_id or username")
        try:
            from telethon.sync import TelegramClient as _TelethonClient  # type: ignore
            from telethon.sessions import StringSession  # type: ignore
            from telethon.errors import FloodWaitError as _TelethonFloodWait  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("Telethon is not installed") from e

        peer: int | str = int(tg_user_id) if tg_user_id is not None else _normalize_identifier(username or "")
        client = _TelethonClient(StringSession(self._cfg.session_string), self._cfg.api_id, self._cfg.api_hash)
        try:
            client.connect()
            raw = client.get_messages(peer, ids=int(message_id))
            if raw is None:
                return False
            # ids=int returns a single Message; ids=list returns TotalList (subclass of list).
            m = raw[0] if isinstance(raw, list) else raw
            if m is None or getattr(m, "id", None) is None:
                return False
            return bool(getattr(m, "out", False))
        except _TelethonFloodWait as e:  # pragma: no cover (network)
            raise FloodWaitError(int(getattr(e, "seconds", 0)))
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    def iter_users_from_messages(
        self,
        source_identifier: str,
        *,
        limit: int | None = None,
        min_date: datetime | None = None,
    ) -> Iterable[TgUser]:
        try:
            from telethon.sync import TelegramClient as _TelethonClient  # type: ignore
            from telethon.sessions import StringSession  # type: ignore
            from telethon.errors import FloodWaitError as _TelethonFloodWait  # type: ignore
            from telethon.tl.types import PeerUser, User as TLUser  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("Telethon is not installed") from e

        ident = _normalize_identifier(source_identifier)
        client = _TelethonClient(StringSession(self._cfg.session_string), self._cfg.api_id, self._cfg.api_hash)
        try:
            client.connect()
            entity = client.get_entity(ident)
            lim = limit if limit is not None and limit > 0 else None
            for msg in client.iter_messages(entity, limit=lim):
                if not msg or getattr(msg, "action", None) is not None:
                    continue
                if min_date is not None and msg.date:
                    mdt = msg.date
                    if mdt.tzinfo is None:
                        mdt = mdt.replace(tzinfo=timezone.utc)
                    cmp_min = min_date
                    if cmp_min.tzinfo is None:
                        cmp_min = cmp_min.replace(tzinfo=timezone.utc)
                    if mdt < cmp_min:
                        break
                sender = getattr(msg, "sender", None)
                if sender is None and msg.from_id is not None and isinstance(msg.from_id, PeerUser):
                    try:
                        sender = client.get_entity(msg.from_id)
                    except Exception:
                        sender = None
                if not isinstance(sender, TLUser):
                    continue
                if getattr(sender, "bot", False):
                    continue
                uid = int(sender.id)
                un = getattr(sender, "username", None) or None
                first = getattr(sender, "first_name", None) or ""
                last = getattr(sender, "last_name", None) or ""
                name = (first + " " + last).strip() or None
                yield TgUser(tg_user_id=uid, username=un, display_name=name)
        except _TelethonFloodWait as e:  # pragma: no cover (network)
            raise FloodWaitError(int(getattr(e, "seconds", 0)))
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    def iter_message_snippets(
        self,
        source_identifier: str,
        *,
        limit: int | None = None,
        min_date: datetime | None = None,
    ) -> Iterable[TgMessageSnippet]:
        try:
            from telethon.sync import TelegramClient as _TelethonClient  # type: ignore
            from telethon.sessions import StringSession  # type: ignore
            from telethon.errors import FloodWaitError as _TelethonFloodWait  # type: ignore
            from telethon.tl.types import PeerUser, User as TLUser  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("Telethon is not installed") from e

        ident = _normalize_identifier(source_identifier)
        client = _TelethonClient(StringSession(self._cfg.session_string), self._cfg.api_id, self._cfg.api_hash)
        try:
            client.connect()
            entity = client.get_entity(ident)
            lim = limit if limit is not None and limit > 0 else None
            for msg in client.iter_messages(entity, limit=lim):
                if not msg or getattr(msg, "action", None) is not None:
                    continue
                txt = getattr(msg, "message", None)
                if not isinstance(txt, str) or not txt.strip():
                    continue
                if min_date is not None and msg.date:
                    mdt = msg.date
                    if mdt.tzinfo is None:
                        mdt = mdt.replace(tzinfo=timezone.utc)
                    cmp_min = min_date
                    if cmp_min.tzinfo is None:
                        cmp_min = cmp_min.replace(tzinfo=timezone.utc)
                    if mdt < cmp_min:
                        break
                sender = getattr(msg, "sender", None)
                if sender is None and msg.from_id is not None and isinstance(msg.from_id, PeerUser):
                    try:
                        sender = client.get_entity(msg.from_id)
                    except Exception:
                        sender = None
                if not isinstance(sender, TLUser):
                    continue
                if getattr(sender, "bot", False):
                    continue
                uid = int(sender.id)
                un = getattr(sender, "username", None) or None
                first = getattr(sender, "first_name", None) or ""
                last = getattr(sender, "last_name", None) or ""
                name = (first + " " + last).strip() or None
                yield TgMessageSnippet(sender=TgUser(tg_user_id=uid, username=un, display_name=name), text=txt.strip(), date=msg.date)
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


async def async_verify_session(cfg: TelethonConfig) -> tuple[bool, str | None, str | None]:
    """Async connect, get_me, disconnect. Returns (ok, username, error)."""
    try:
        from telethon import TelegramClient as _TelethonClient  # type: ignore
        from telethon.sessions import StringSession  # type: ignore
    except Exception as e:  # pragma: no cover
        return False, None, str(e)

    client = _TelethonClient(StringSession(cfg.session_string), cfg.api_id, cfg.api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False, None, "not_authorized"
        me = await client.get_me()
        un = getattr(me, "username", None) or None
        return True, un, None
    except Exception as e:  # pragma: no cover (network)
        return False, None, type(e).__name__
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def async_fetch_inbox_text(
    cfg: TelethonConfig,
    *,
    peer: str,
    limit: int = 20,
) -> tuple[bool, list[dict], str | None]:
    """
    Fetch last messages from a peer (e.g. '777000' or 'SpamBot' or '@username').
    Returns (ok, items, error). Items are minimal dicts for UI.
    """
    try:
        from telethon import TelegramClient as _TelethonClient  # type: ignore
        from telethon.sessions import StringSession  # type: ignore
    except Exception as e:  # pragma: no cover
        return False, [], str(e)

    peer_norm = peer.strip()
    if peer_norm.startswith("@"):
        peer_norm = peer_norm[1:]

    lim = int(limit) if int(limit) > 0 else 20
    lim = min(lim, 50)

    client = _TelethonClient(StringSession(cfg.session_string), cfg.api_id, cfg.api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False, [], "not_authorized"
        msgs = await client.get_messages(peer_norm, limit=lim)
        out: list[dict] = []
        for m in list(msgs or []):
            txt = getattr(m, "message", None)
            if not isinstance(txt, str):
                txt = ""
            dt = getattr(m, "date", None)
            out.append(
                {
                    "id": int(getattr(m, "id", 0) or 0),
                    "date": dt.isoformat() if dt is not None else None,
                    "text": txt,
                    "out": bool(getattr(m, "out", False)),
                }
            )
        return True, out, None
    except Exception as e:  # pragma: no cover (network)
        return False, [], type(e).__name__
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
