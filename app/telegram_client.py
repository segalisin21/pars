from __future__ import annotations

from dataclasses import dataclass


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
    def get_participants(self, source_identifier: str) -> list[TgUser]:
        raise NotImplementedError

    def invite_to_target(self, target_identifier: str, tg_user_id: int) -> None:
        raise NotImplementedError

