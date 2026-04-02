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

