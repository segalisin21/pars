from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    identifier: Mapped[str] = mapped_column(String(256), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    telegram_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    telegram_participants_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telegram_meta_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Where to pull contacts: participants list, message senders, both, or auto (messages if participant list empty).
    collect_mode: Mapped[str] = mapped_column(String(32), default="participants", nullable=False)

    workspace: Mapped[Workspace] = relationship()

    __table_args__ = (UniqueConstraint("workspace_id", "type", "identifier", name="uq_source_workspace_type_identifier"),)


class InviteTarget(Base):
    __tablename__ = "invite_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    identifier: Mapped[str] = mapped_column(String(256), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    workspace: Mapped[Workspace] = relationship()

    __table_args__ = (UniqueConstraint("workspace_id", "identifier", name="uq_target_workspace_identifier"),)


class CandidateUser(Base):
    __tablename__ = "candidate_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    workspace: Mapped[Workspace] = relationship()

    __table_args__ = (
        UniqueConstraint("workspace_id", "tg_user_id", name="uq_candidate_workspace_tg_user_id"),
        UniqueConstraint("workspace_id", "username", name="uq_candidate_workspace_username"),
    )


class CandidateSourceLink(Base):
    __tablename__ = "candidate_source_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate_users.id"), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    candidate: Mapped[CandidateUser] = relationship()
    source: Mapped[Source] = relationship()
    workspace: Mapped[Workspace] = relationship()

    __table_args__ = (UniqueConstraint("workspace_id", "candidate_id", "source_id", name="uq_candidate_source_workspace"),)


class CandidateFeatures(Base):
    """Computed targeting features & scoring for a candidate (workspace-scoped)."""

    __tablename__ = "candidate_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate_users.id"), nullable=False, index=True)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    # Source-context aggregate.
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_priority_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    seen_as: Mapped[str] = mapped_column(String(16), nullable=False, default="participants")  # participants|messages|both|mixed

    # Profile metadata flags.
    has_username: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_display_name: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Text-derived features (best-effort, limited).
    topic_keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    intent_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Risk-first scoring.
    warmth_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    send_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    segment: Mapped[str] = mapped_column(String(8), nullable=False, default="C")  # A|B|C

    reasons: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Optional: computed under a specific targeting profile.
    targeting_profile_id: Mapped[int | None] = mapped_column(ForeignKey("targeting_profiles.id"), nullable=True, index=True)
    semantic_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0..1000 scaled cosine similarity

    candidate: Mapped[CandidateUser] = relationship()
    workspace: Mapped[Workspace] = relationship()

    __table_args__ = (
        UniqueConstraint("workspace_id", "candidate_id", name="uq_candidate_features_ws_candidate"),
        Index("ix_candidate_features_ws_segment_score", "workspace_id", "segment", "send_score"),
    )


class CandidateProfileFeatures(Base):
    """Computed targeting features & scoring for a candidate under a specific targeting profile."""

    __tablename__ = "candidate_profile_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate_users.id"), nullable=False, index=True)
    targeting_profile_id: Mapped[int] = mapped_column(ForeignKey("targeting_profiles.id"), nullable=False, index=True)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    # Snapshot of base features (helps explainability in UI without joins).
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_priority_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    seen_as: Mapped[str] = mapped_column(String(16), nullable=False, default="participants")
    has_username: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_display_name: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    topic_keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    intent_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Profile-specific scoring.
    semantic_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0..1000
    warmth_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    send_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    segment: Mapped[str] = mapped_column(String(8), nullable=False, default="C")
    reasons: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    candidate: Mapped[CandidateUser] = relationship()
    workspace: Mapped[Workspace] = relationship()
    profile: Mapped["TargetingProfile"] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "candidate_id",
            "targeting_profile_id",
            name="uq_candidate_profile_features_ws_candidate_profile",
        ),
        Index(
            "ix_candidate_profile_features_ws_profile_score",
            "workspace_id",
            "targeting_profile_id",
            "send_score",
        ),
        Index(
            "ix_candidate_profile_features_ws_profile_segment_score",
            "workspace_id",
            "targeting_profile_id",
            "segment",
            "send_score",
        ),
    )


class TargetingProfile(Base):
    __tablename__ = "targeting_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    query: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    language_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="mixed")  # ru|mixed
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    draft_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    draft_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    workspace: Mapped[Workspace] = relationship()


class TargetingRun(Base):
    __tablename__ = "targeting_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("targeting_profiles.id"), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")  # queued|running|succeeded|failed|cancelled
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")  # capture_messages|embed_and_score|done
    progress: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped[Workspace] = relationship()
    profile: Mapped["TargetingProfile"] = relationship()
    logs: Mapped[list["TargetingRunLog"]] = relationship(back_populates="run")


class TargetingRunLog(Base):
    __tablename__ = "targeting_run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("targeting_runs.id"), nullable=False, index=True)
    msg: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    run: Mapped["TargetingRun"] = relationship(back_populates="logs")
    workspace: Mapped[Workspace] = relationship()


class CandidateMessage(Base):
    __tablename__ = "candidate_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate_users.id"), nullable=False, index=True)
    msg_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    candidate: Mapped[CandidateUser] = relationship()
    source: Mapped[Source] = relationship()
    workspace: Mapped[Workspace] = relationship()

    __table_args__ = (
        Index("ix_candidate_messages_ws_candidate_date", "workspace_id", "candidate_id", "msg_date"),
        UniqueConstraint("workspace_id", "candidate_id", "text_hash", name="uq_candidate_messages_ws_candidate_hash"),
    )


class CandidateEmbedding(Base):
    __tablename__ = "candidate_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate_users.id"), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="text-embedding-3-small")
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("workspace_id", "candidate_id", name="uq_candidate_embeddings_ws_candidate"),)


class TelegramAppCredentials(Base):
    """Singleton: Telegram App credentials (api_id/api_hash) encrypted at rest."""

    __tablename__ = "telegram_app_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    api_id_encrypted: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    api_hash_encrypted: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TelegramAccount(Base):
    """Global pool of Telegram user sessions (not workspace-scoped)."""

    __tablename__ = "telegram_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    last_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    session_string_encrypted: Mapped[str] = mapped_column(String(8192), nullable=False)
    session_string_key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When set, this account should not be auto-selected until this time (e.g. after FloodWait).
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    spambot_status_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    spambot_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    spambot_error: Mapped[str | None] = mapped_column(String(128), nullable=True)


class SuppressionList(Base):
    __tablename__ = "suppression_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    workspace: Mapped[Workspace] = relationship()


class CollectRun(Base):
    __tablename__ = "collect_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    source_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    telegram_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_accounts.id"), nullable=True, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    workspace: Mapped[Workspace] = relationship()
    telegram_account: Mapped["TelegramAccount | None"] = relationship()


class InviteRun(Base):
    __tablename__ = "invite_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    telegram_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_accounts.id"), nullable=True, index=True
    )
    target_id: Mapped[int] = mapped_column(ForeignKey("invite_targets.id"), nullable=False, index=True)
    # Empty list = all candidates in workspace; otherwise only candidates linked to these sources.
    source_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    target: Mapped[InviteTarget] = relationship()
    workspace: Mapped[Workspace] = relationship()
    telegram_account: Mapped["TelegramAccount | None"] = relationship()


class BroadcastRun(Base):
    """Queued DM broadcast to workspace candidates (by sources and/or explicit ids)."""

    __tablename__ = "broadcast_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    telegram_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_accounts.id"), nullable=True, index=True
    )
    # Operator-defined idempotency key: same key + recipient = at most one successful delivery per workspace.
    message_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    message_body: Mapped[str] = mapped_column(Text, nullable=False)
    # Empty = all candidates; else filter by links to these sources (same semantics as InviteRun.source_ids).
    source_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    # If non-empty, only these candidate row ids (must belong to workspace).
    candidate_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    workspace: Mapped[Workspace] = relationship()
    telegram_account: Mapped["TelegramAccount | None"] = relationship()
    deliveries: Mapped[list["BroadcastDelivery"]] = relationship(back_populates="broadcast_run")


class BroadcastDelivery(Base):
    """Per-recipient broadcast outcome; partial unique index allows one success per (workspace, message_key, tg_user_id)."""

    __tablename__ = "broadcast_deliveries"
    __table_args__ = (
        Index(
            "uq_broadcast_delivery_success_ws_key_tg",
            "workspace_id",
            "message_key",
            "tg_user_id",
            unique=True,
            sqlite_where=text("status = 'success'"),
            postgresql_where=text("status = 'success'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    broadcast_run_id: Mapped[int] = mapped_column(ForeignKey("broadcast_runs.id"), nullable=False, index=True)
    message_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate_users.id"), nullable=False, index=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    # Cloud chat message id from MTProto when known (Telethon send_message); optional outbox re-check uses this id.
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    broadcast_run: Mapped["BroadcastRun"] = relationship(back_populates="deliveries")
    candidate: Mapped[CandidateUser] = relationship()
    workspace: Mapped[Workspace] = relationship()


class InviteAttempt(Base):
    __tablename__ = "invite_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    invite_run_id: Mapped[int] = mapped_column(ForeignKey("invite_runs.id"), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("invite_targets.id"), nullable=False, index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate_users.id"), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    candidate: Mapped[CandidateUser] = relationship()
    workspace: Mapped[Workspace] = relationship()


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    workspace: Mapped[Workspace] = relationship()
