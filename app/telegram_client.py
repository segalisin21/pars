from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class SourceTelegramMeta:
    """Resolved Telegram metadata for a source (channel/chat title and subscriber/member count)."""

    title: str | None
    participants_count: int | None


@dataclass(frozen=True)
class TgUser:
    tg_user_id: int | None
    username: str | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class TgMessageSnippet:
    """Minimal message info for targeting analysis (no media)."""

    sender: TgUser
    text: str
    date: datetime | None = None


@dataclass(frozen=True)
class DirectMessageSendResult:
    """Outcome of send_direct_message: Telegram server accepted the message (MTProto success).

    ``message_id`` is the cloud chat message id when the implementation returns it (e.g. Telethon);
    ``None`` if unavailable. This does not imply the recipient read the message.

    When the send used a username peer, ``resolved_tg_user_id`` may contain the numeric user id
    from the API response (for storage in ``BroadcastDelivery``).
    """

    message_id: int | None = None
    out: bool = True
    resolved_tg_user_id: int | None = None


class FloodWaitError(Exception):
    def __init__(self, seconds: int):
        super().__init__(f"Flood wait for {seconds} seconds")
        self.seconds = seconds


class TelegramClient:
    def iter_participants(self, source_identifier: str) -> Iterable[TgUser]:
        raise NotImplementedError

    def get_participants(self, source_identifier: str) -> list[TgUser]:
        return list(self.iter_participants(source_identifier))

    def invite_to_target(self, target_identifier: str, tg_user_id: int) -> None:
        raise NotImplementedError

    def send_direct_message(
        self,
        text: str,
        *,
        tg_user_id: int | None = None,
        username: str | None = None,
    ) -> DirectMessageSendResult:
        """Send a private DM; specify exactly one of ``tg_user_id`` or ``username`` (no @)."""
        raise NotImplementedError

    def supports_outbox_verify(self) -> bool:
        """Whether ``verify_direct_message_outbox`` can run a meaningful check (second MTProto round-trip)."""
        return False

    def verify_direct_message_outbox(
        self,
        message_id: int,
        *,
        tg_user_id: int | None = None,
        username: str | None = None,
    ) -> bool:
        """Re-fetch message by id in the private chat; specify exactly one of ``tg_user_id`` or ``username``.

        Default: unsupported (returns False). Telethon implementation overrides.
        """
        return False

    def fetch_source_meta(self, source_identifier: str) -> SourceTelegramMeta | None:
        """Return title and participants_count when supported; None if unavailable (noop client)."""
        return None

    def iter_users_from_messages(
        self,
        source_identifier: str,
        *,
        limit: int | None = None,
        min_date: datetime | None = None,
    ) -> Iterable[TgUser]:
        """Yield users inferred from message senders (supergroups/chats). Default: none (noop)."""
        return iter(())

    def iter_message_snippets(
        self,
        source_identifier: str,
        *,
        limit: int | None = None,
        min_date: datetime | None = None,
    ) -> Iterable[TgMessageSnippet]:
        """Yield lightweight (sender, text, date) for recent messages. Default: none."""
        _ = min_date
        _ = limit
        return iter(())

