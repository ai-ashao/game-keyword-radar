"""Typed, replayable research decisions; separate from legacy DemandScore."""
from __future__ import annotations
from datetime import date as CalendarDate, datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


Lane = Literal["new_release", "rising", "new_demand", "exploration"]


class ReleaseDateEvidence(BaseModel):
    date: CalendarDate | None = None
    raw_text: str = ""
    precision: Literal["day", "month", "unknown"] = "day"
    source: str = "unknown"
    source_url: HttpUrl | None = None
    checked_at: datetime | None = None
    basis: Literal["verified_public", "platform_reported", "manual_verified", "unknown"] = "platform_reported"


class LifecycleAssessment(BaseModel):
    lifecycle: Literal["new_release", "established", "preview", "unknown"] = "unknown"
    recency_status: Literal["verified", "provisional_platform_date", "unknown"] = "unknown"
    release_stage: Literal["released", "early_access", "demo", "upcoming", "unknown"] = "unknown"
    age_days: int | None = None
    platform_age_days: int | None = None
    recent_eligible: bool = False
    reason: str = "发行依据尚未记录"
    evidence_ids: list[str] = Field(default_factory=list)
    as_of: datetime = Field(default_factory=now_utc)


class MomentumComparison(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    source: str
    metric: str
    period: Literal["intraday", "24h", "7d"]
    current_value: float | None = None
    baseline_value: float | None = None
    absolute_delta: float | None = None
    percent_change: float | None = None
    comparison_kind: Literal["window", "point_pair", "intraday", "sample_window"]
    comparable: bool = True
    qualified: bool = False
    low_base: bool = False
    direction: Literal["up", "down", "flat", "unknown"] = "unknown"
    strong: bool = False
    pair_count: int = 0
    current_span_hours: float = 0
    baseline_span_hours: float = 0
    actual_elapsed_hours: list[float] = Field(default_factory=list)
    current_observation_ids: list[str] = Field(default_factory=list)
    baseline_observation_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class MomentumAssessment(BaseModel):
    state: Literal["unknown", "early_signal", "rising", "stable", "falling", "mixed", "inconclusive"] = "unknown"
    period: Literal["intraday", "24h", "7d", "none"] = "none"
    comparisons: list[MomentumComparison] = Field(default_factory=list)
    persistence: Literal["untested", "single_spike", "sustained_observation"] = "untested"
    breadth: Literal["unknown", "concentrated", "broadening", "distributed"] = "unknown"
    rising_sources: list[str] = Field(default_factory=list)
    conflicting_sources: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    trigger_evidence_ids: list[str] = Field(default_factory=list)
    as_of: datetime = Field(default_factory=now_utc)


class SelectionDecision(BaseModel):
    game_slug: str
    lifecycle: LifecycleAssessment = Field(default_factory=LifecycleAssessment)
    momentum: MomentumAssessment = Field(default_factory=MomentumAssessment)
    eligible_lanes: list[Lane] = Field(default_factory=list)
    primary_lane: Lane | None = None
    decision: Literal["selected", "monitor_only", "deferred_budget", "excluded"] = "monitor_only"
    reason_codes: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    trigger_evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    selected_for_monitoring: bool = False
    selected_for_deep: bool = False
    selection_order: int | None = None
    entry_origin: Literal["automatic", "manual"] = "automatic"
    trigger_fingerprint: str = ""
    policy_version: str = "selection-2.1-r1"
    config_hash: str = ""
    as_of: datetime = Field(default_factory=now_utc)
