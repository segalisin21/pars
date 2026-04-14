from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ConfigDict, field_validator


class TargetingWeightsV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic: float = Field(default=1.0, ge=0.0, le=5.0)
    warmth: float = Field(default=1.0, ge=0.0, le=5.0)
    risk: float = Field(default=1.0, ge=0.0, le=5.0)


class TargetingThresholdsV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Minimum final score to include in "eligible" audience.
    min_send_score: int = Field(default=10, ge=-1000, le=1000)

    # Segment thresholds for A/B/C split. (C is everything below B.)
    segment_a_min: int = Field(default=40, ge=-1000, le=1000)
    segment_b_min: int = Field(default=10, ge=-1000, le=1000)

    @field_validator("segment_b_min")
    @classmethod
    def _b_not_above_a(cls, v: int, info):
        a = info.data.get("segment_a_min")
        if isinstance(a, int) and v > a:
            raise ValueError("segment_b_min must be <= segment_a_min")
        return v


class TargetingTermsV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords_include: list[str] = Field(default_factory=list, max_length=60)
    keywords_exclude: list[str] = Field(default_factory=list, max_length=60)
    intent_phrases: list[str] = Field(default_factory=list, max_length=60)

    @field_validator("keywords_include", "keywords_exclude", "intent_phrases", mode="after")
    @classmethod
    def _normalize_terms(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in v:
            s = str(raw).strip()
            if not s:
                continue
            if len(s) < 2 or len(s) > 64:
                continue
            s = s.lower()
            if s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out[:60]


class TargetingLimitsV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(default=14, ge=1, le=365)
    max_messages_per_source: int = Field(default=200, ge=1, le=5000)
    # Maximum total characters used to build per-candidate text for embeddings/scoring.
    max_candidate_text_chars: int = Field(default=4000, ge=200, le=20000)
    # Keep runs bounded (cost + time).
    max_candidates: int | None = Field(default=None, ge=1, le=200_000)


class TargetingModelsV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embedding_model: str = Field(default="text-embedding-3-small", min_length=3, max_length=64)


class TargetingParamsV2(BaseModel):
    """Quality-first targeting configuration used by UI Form + JSON (advanced).

    Strict schema: unknown keys are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal["v2"] = "v2"
    limits: TargetingLimitsV2 = Field(default_factory=TargetingLimitsV2)
    terms: TargetingTermsV2 = Field(default_factory=TargetingTermsV2)
    weights: TargetingWeightsV2 = Field(default_factory=TargetingWeightsV2)
    thresholds: TargetingThresholdsV2 = Field(default_factory=TargetingThresholdsV2)
    models: TargetingModelsV2 = Field(default_factory=TargetingModelsV2)


def params_to_dict(p: TargetingParamsV2) -> dict:
    return p.model_dump(mode="json", exclude_none=True)

