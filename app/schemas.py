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

# How broadcast DMs resolve the Telegram peer (stored on BroadcastRun.policy).
DmRecipient = Literal["tg_user_id", "username"]


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
    # Optional global Telegram account; omit for auto-selection among enabled accounts / env session.
    telegram_account_id: int | None = None


class CollectRunOut(BaseModel):
    id: int
    status: str
    source_ids: list[int]
    telegram_account_id: int | None = None
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
    # Stop after this many successful channel invites (omit or null = no cap).
    max_invites: int | None = Field(default=None)

    @field_validator("max_invites")
    @classmethod
    def _validate_max_invites(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v < 1 or v > 100_000:
            raise ValueError("max_invites must be between 1 and 100000")
        return v


class InviteRunCreate(BaseModel):
    target_id: int
    policy: InvitePolicy = Field(default_factory=InvitePolicy)
    # Empty = invite from all candidates in workspace; otherwise only candidates collected from these sources.
    source_ids: list[int] = Field(default_factory=list, max_length=50)
    telegram_account_id: int | None = None

    @field_validator("source_ids", mode="after")
    @classmethod
    def _dedupe_source_ids(cls, v: list[int]) -> list[int]:
        return sorted(set(v))


class InviteRunOut(BaseModel):
    id: int
    status: str
    target_id: int
    source_ids: list[int]
    telegram_account_id: int | None = None
    policy: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None
    stats: dict[str, Any]

    @field_serializer("started_at", "finished_at")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class InviteRunsList(BaseModel):
    items: list[InviteRunOut]


class BroadcastPolicy(BaseModel):
    max_per_minute: int = Field(default=2, ge=1, le=60)
    max_per_hour: int = Field(default=30, ge=1, le=10000)
    max_total: int | None = Field(default=None)
    dm_recipient: DmRecipient = "tg_user_id"
    # Optional targeting filters (require precomputed CandidateFeatures).
    targeting_segment: Literal["A", "B", "C"] | None = None
    min_send_score: int | None = Field(default=None)
    targeting_profile_id: int | None = None

    @field_validator("max_total")
    @classmethod
    def _validate_max_total(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v < 1 or v > 100_000:
            raise ValueError("max_total must be between 1 and 100000")
        return v

    @field_validator("min_send_score")
    @classmethod
    def _validate_min_send_score(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v < -1000 or v > 1000:
            raise ValueError("min_send_score must be between -1000 and 1000")
        return v


class BroadcastRunCreate(BaseModel):
    message_key: str = Field(min_length=1, max_length=128)
    message_body: str = Field(min_length=1, max_length=4096)
    policy: BroadcastPolicy = Field(default_factory=BroadcastPolicy)
    source_ids: list[int] = Field(default_factory=list, max_length=50)
    candidate_ids: list[int] = Field(default_factory=list, max_length=5000)
    telegram_account_id: int | None = None

    @field_validator("message_key")
    @classmethod
    def _normalize_message_key(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("message_key is required")
        for ch in s:
            if not (ch.isalnum() or ch in ("_", "-", ".")):
                raise ValueError("message_key allows only letters, digits, underscore, hyphen, dot")
        return s

    @field_validator("source_ids", mode="after")
    @classmethod
    def _dedupe_source_ids(cls, v: list[int]) -> list[int]:
        return sorted(set(v))

    @field_validator("candidate_ids", mode="after")
    @classmethod
    def _dedupe_candidate_ids(cls, v: list[int]) -> list[int]:
        return sorted(set(v))


class BroadcastPreviewIn(BaseModel):
    message_key: str = Field(min_length=1, max_length=128)
    source_ids: list[int] = Field(default_factory=list, max_length=50)
    candidate_ids: list[int] = Field(default_factory=list, max_length=5000)
    dm_recipient: DmRecipient = "tg_user_id"

    @field_validator("message_key")
    @classmethod
    def _normalize_preview_key(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("message_key is required")
        return s

    @field_validator("source_ids", mode="after")
    @classmethod
    def _dedupe_preview_sources(cls, v: list[int]) -> list[int]:
        return sorted(set(v))

    @field_validator("candidate_ids", mode="after")
    @classmethod
    def _dedupe_preview_candidates(cls, v: list[int]) -> list[int]:
        return sorted(set(v))


class BroadcastPreviewOut(BaseModel):
    scan_total: int
    suppressed: int
    missing_tg_user_id: int
    missing_username: int
    already_sent: int
    eligible: int


class BroadcastRunOut(BaseModel):
    id: int
    status: str
    message_key: str
    message_body: str
    source_ids: list[int]
    candidate_ids: list[int]
    telegram_account_id: int | None = None
    policy: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None
    stats: dict[str, Any]

    @field_serializer("started_at", "finished_at")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class BroadcastRunsList(BaseModel):
    items: list[BroadcastRunOut]


class BroadcastRunPatch(BaseModel):
    message_body: str = Field(min_length=1, max_length=4096)


class BroadcastDeliveryOut(BaseModel):
    id: int
    broadcast_run_id: int
    candidate_id: int
    tg_user_id: int
    status: str
    error_code: str | None
    attempted_at: datetime
    telegram_message_id: int | None = None
    username: str | None = None
    display_name: str | None = None

    @field_serializer("attempted_at")
    def _serialize_attempted_at(self, v: datetime):
        return iso_utc_z(v)


class TargetingPreviewIn(BaseModel):
    source_ids: list[int] = Field(default_factory=list, max_length=50)
    candidate_ids: list[int] = Field(default_factory=list, max_length=5000)
    segment: Literal["A", "B", "C", "any"] = "any"
    limit: int = Field(default=50, ge=1, le=200)

    @field_validator("source_ids", mode="after")
    @classmethod
    def _dedupe_tp_sources(cls, v: list[int]) -> list[int]:
        return sorted(set(v))

    @field_validator("candidate_ids", mode="after")
    @classmethod
    def _dedupe_tp_candidates(cls, v: list[int]) -> list[int]:
        return sorted(set(v))


class TargetingCandidateOut(BaseModel):
    candidate_id: int
    tg_user_id: int | None
    username: str | None
    display_name: str | None
    last_seen_at: datetime
    segment: str
    send_score: int
    warmth_score: int
    risk_score: int
    source_count: int
    seen_as: str
    topic_keywords: list[str]
    intent_flags: list[str]
    reasons: dict[str, Any]

    @field_serializer("last_seen_at")
    def _serialize_last_seen_at(self, v: datetime):
        return iso_utc_z(v)


class TargetingPreviewOut(BaseModel):
    counts_by_segment: dict[str, int]
    top: list[TargetingCandidateOut]


class TargetingProfileOut(BaseModel):
    id: int
    name: str
    query: str
    language_mode: str
    params: dict[str, Any]
    draft_params: dict[str, Any] | None = None
    draft_updated_at: datetime | None = None
    updated_at: datetime

    @field_serializer("updated_at", "draft_updated_at")
    def _serialize_tp_updated(self, v: datetime | None):
        return iso_utc_z(v)


class TargetingProfilesList(BaseModel):
    items: list[TargetingProfileOut]


class TargetingAiSuggestIn(BaseModel):
    query: str = Field(min_length=2, max_length=512)
    language_mode: Literal["ru", "mixed"] = "mixed"
    name: str | None = Field(default=None, max_length=128)


class TargetingAiSuggestOut(BaseModel):
    profile: TargetingProfileOut


class TargetingProfileCreateIn(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    query: str = Field(min_length=2, max_length=512)
    language_mode: Literal["ru", "mixed"] = "mixed"
    params: dict[str, Any] = Field(default_factory=dict)


class TargetingProfilePatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    query: str | None = Field(default=None, min_length=2, max_length=512)
    language_mode: Literal["ru", "mixed"] | None = None
    params: dict[str, Any] | None = None


class TargetingAiSuggestDraftOut(BaseModel):
    draft_params: dict[str, Any]
    diff: list[dict[str, Any]]


class TargetingApplyDraftOut(BaseModel):
    profile: TargetingProfileOut


class TargetingProfilePreviewIn(BaseModel):
    profile_id: int
    segment: Literal["A", "B", "C", "any"] = "any"
    limit: int = Field(default=50, ge=1, le=200)


class TargetingProfilePreviewOut(BaseModel):
    counts_by_segment: dict[str, int]
    top: list[TargetingCandidateOut]


class TargetingCandidatesList(BaseModel):
    items: list[TargetingCandidateOut]
    page: PageMeta


class TargetingRunLogOut(BaseModel):
    id: int
    msg: str
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class TargetingRunOut(BaseModel):
    id: int
    profile_id: int
    status: str
    stage: str
    progress: dict[str, Any]
    error: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    logs: list[TargetingRunLogOut] = Field(default_factory=list)

    @field_serializer("created_at", "updated_at", "started_at", "finished_at")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class TargetingRunStartOut(BaseModel):
    run_id: int


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


class TelegramAppCredentialsOut(BaseModel):
    configured: bool
    api_id: int | None = None
    updated_at: datetime | None = None

    @field_serializer("updated_at")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class TelegramAppCredentialsPutIn(BaseModel):
    api_id: int = Field(gt=0)
    api_hash: str = Field(min_length=8, max_length=128)


class TelegramAccountCreate(BaseModel):
    label: str = Field(default="", max_length=128)
    session_string: str = Field(min_length=1, max_length=8192)


class TelegramAccountPatch(BaseModel):
    label: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None


class TelegramAccountOut(BaseModel):
    id: int
    label: str
    last_username: str | None = None
    enabled: bool
    created_at: datetime
    last_used_at: datetime | None
    last_ok_at: datetime | None
    last_error_code: str | None
    last_error_at: datetime | None
    cooldown_until: datetime | None

    @field_serializer("created_at", "last_used_at", "last_ok_at", "last_error_at", "cooldown_until")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class TelegramAccountsList(BaseModel):
    items: list[TelegramAccountOut]


class TelegramAccountTestOut(BaseModel):
    ok: bool
    username: str | None = None
    error: str | None = None


class TelegramInboxMessageOut(BaseModel):
    id: int
    date: str | None = None
    text: str
    out: bool = False


class TelegramInboxOut(BaseModel):
    peer: str
    items: list[TelegramInboxMessageOut]
    error: str | None = None


class TelegramAccountBusyOut(BaseModel):
    kind: str
    run_id: int
    status: str
    started_at: datetime

    @field_serializer("started_at")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class TelegramAccountStatusOut(BaseModel):
    account: TelegramAccountOut
    busy: TelegramAccountBusyOut | None = None
    spambot_status_text: str | None = None
    spambot_checked_at: datetime | None = None
    spambot_error: str | None = None

    @field_serializer("spambot_checked_at")
    def _serialize_dt(self, v: datetime | None):
        return iso_utc_z(v)


class TelegramAccountsStatusList(BaseModel):
    items: list[TelegramAccountStatusOut]


class TelegramAccountSpamBotCheckOut(BaseModel):
    enqueued: bool
    job_id: str | None = None


class PageMeta(BaseModel):
    limit: int
    offset: int
    total: int


class BroadcastDeliveriesList(BaseModel):
    items: list[BroadcastDeliveryOut]
    page: PageMeta


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


