from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_serializer, field_validator


def iso_utc_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # Ensure `Z` suffix instead of `+00:00`
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


class ErrorEnvelope(BaseModel):
    error: dict[str, Any]


CollectMode = Literal["participants", "messages", "both", "auto"]


class SourceCreate(BaseModel):
    type: Literal["group", "chat", "channel"]
    identifier: str = Field(min_length=1, max_length=256)
    enabled: bool = True
    notes: str | None = Field(default=None, max_length=512)
    collect_mode: CollectMode = "participants"

    @field_validator("identifier")
    @classmethod
    def normalize_identifier(cls, v: str) -> str:
        v = v.strip()
        if v.startswith("@"):
            v = v[1:]
        return v


class SourceOut(BaseModel):
    id: int
    type: str
    identifier: str
    enabled: bool
    notes: str | None
    collect_mode: CollectMode
    telegram_title: str | None = None
    telegram_participants_count: int | None = None
    telegram_meta_updated_at: datetime | None = None

    @field_serializer("telegram_meta_updated_at")
    def ser_meta_ts(self, v: datetime | None) -> str | None:
        return iso_utc_z(v)


class SourcesList(BaseModel):
    items: list[SourceOut]


class SourcePatch(BaseModel):
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=512)
    collect_mode: CollectMode | None = None


class TargetCreate(BaseModel):
    identifier: str = Field(min_length=1, max_length=256)
    enabled: bool = True
    notes: str | None = Field(default=None, max_length=512)

    @field_validator("identifier")
    @classmethod
    def normalize_identifier(cls, v: str) -> str:
        v = v.strip()
        if v.startswith("@"):
            v = v[1:]
        return v


class TargetOut(BaseModel):
    id: int
    identifier: str
    enabled: bool
    notes: str | None


class TargetsList(BaseModel):
    items: list[TargetOut]


class TargetPatch(BaseModel):
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=512)


class CollectRunCreate(BaseModel):
    source_ids: list[int] = Field(min_length=1)


class CollectRunOut(BaseModel):
    id: int
    status: str
    source_ids: list[int]
    started_at: datetime
    finished_at: datetime | None
    stats: dict[str, Any]

    @field_serializer("started_at", "finished_at")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class CollectRunsList(BaseModel):
    items: list[CollectRunOut]


class InvitePolicy(BaseModel):
    max_per_minute: int = Field(default=2, ge=1, le=60)
    max_per_hour: int = Field(default=30, ge=1, le=10000)
    cooldown_minutes: int = Field(default=1440, ge=0, le=525600)


class InviteRunCreate(BaseModel):
    target_id: int
    policy: InvitePolicy = Field(default_factory=InvitePolicy)


class InviteRunOut(BaseModel):
    id: int
    status: str
    target_id: int
    policy: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None
    stats: dict[str, Any]

    @field_serializer("started_at", "finished_at")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class InviteRunsList(BaseModel):
    items: list[InviteRunOut]


class TelegramRequestCodeIn(BaseModel):
    phone: str = Field(min_length=3, max_length=32)


class TelegramRequestCodeOut(BaseModel):
    token: str | None
    error: str | None


class TelegramVerifyCodeIn(BaseModel):
    token: str = Field(min_length=10, max_length=256)
    code: str = Field(min_length=1, max_length=16)
    password: str | None = Field(default=None, max_length=256)


class TelegramVerifyCodeOut(BaseModel):
    success: bool
    session_string: str | None
    error: str | None


class PageMeta(BaseModel):
    limit: int
    offset: int
    total: int


class SourceRefOut(BaseModel):
    id: int
    type: str
    identifier: str


class CandidateOut(BaseModel):
    id: int
    tg_user_id: int | None
    username: str | None
    display_name: str | None
    first_seen_at: datetime
    last_seen_at: datetime

    @field_serializer("first_seen_at", "last_seen_at")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class CandidateWithSourcesOut(CandidateOut):
    sources: list[SourceRefOut] = Field(default_factory=list)


class CandidatesList(BaseModel):
    items: list[CandidateWithSourcesOut]
    page: PageMeta


class InviteAttemptOut(BaseModel):
    id: int
    invite_run_id: int
    target_id: int
    candidate_id: int
    status: str
    error_code: str | None
    attempted_at: datetime

    @field_serializer("attempted_at")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class InviteAttemptsList(BaseModel):
    items: list[InviteAttemptOut]
    page: PageMeta


class SuppressionOut(BaseModel):
    id: int
    tg_user_id: int | None
    username: str | None
    reason: str
    until: datetime | None
    created_at: datetime

    @field_serializer("until", "created_at")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class SuppressionListOut(BaseModel):
    items: list[SuppressionOut]
    page: PageMeta


class AuditEventOut(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_id: int | None
    meta: dict[str, Any]
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class AuditEventsList(BaseModel):
    items: list[AuditEventOut]
    page: PageMeta


