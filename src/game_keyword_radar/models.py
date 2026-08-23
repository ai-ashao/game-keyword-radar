from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SourceState(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"


class OpportunityStatus(StrEnum):
    NEEDS_VALIDATION = "needs_validation"
    WATCH = "watch"
    SKIP = "skip"


class Evidence(BaseModel):
    label: str
    value: str | int | float | bool | None = None
    source: str
    source_url: HttpUrl | None = None
    collected_at: datetime = Field(default_factory=utc_now)
    is_inference: bool = False


class SourceStatus(BaseModel):
    source: str
    state: SourceState
    message: str
    official_api: bool = False
    records: int = Field(default=0, ge=0)
    checked_at: datetime = Field(default_factory=utc_now)


class TrendSignal(BaseModel):
    timeframe: str = "today 1-m"
    geo: str = "US"
    mean_interest: float | None = Field(default=None, ge=0, le=100)
    recent_interest: float | None = Field(default=None, ge=0, le=100)
    direction_delta: float | None = None
    related_queries: list[str] = Field(default_factory=list)
    state: SourceState = SourceState.SKIPPED
    note: str = "Google Trends is an optional relative signal."


class GameCandidate(BaseModel):
    app_id: str
    name: str
    discovery_sources: list[str] = Field(default_factory=list)
    discovery_ranks: dict[str, int] = Field(default_factory=dict)
    steam_rank: int | None = Field(default=None, ge=1)
    release_date: date | None = None
    current_players: int | None = Field(default=None, ge=0)
    reviews_total: int | None = Field(default=None, ge=0)
    genres: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    short_description: str | None = None
    image_url: HttpUrl | None = None
    store_url: HttpUrl
    mechanics: list[str] = Field(default_factory=list)
    understanding_confidence: Confidence = Confidence.LOW
    game_signal_score: float = Field(default=0, ge=0, le=100)
    data_completeness: float = Field(default=0, ge=0, le=1)
    trend: TrendSignal | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=utc_now)


class ScoreBreakdown(BaseModel):
    problem_intensity: float = Field(ge=0, le=25)
    page_intent: float = Field(ge=0, le=20)
    feasibility: float = Field(ge=0, le=20)
    maintenance: float = Field(ge=0, le=10)
    game_signal: float = Field(ge=0, le=15)
    evidence_confidence: float = Field(ge=0, le=10)

    @property
    def total(self) -> float:
        return round(
            self.problem_intensity
            + self.page_intent
            + self.feasibility
            + self.maintenance
            + self.game_signal
            + self.evidence_confidence,
            1,
        )


class KeywordCandidate(BaseModel):
    keyword: str
    supporting_keywords: list[str] = Field(default_factory=list)
    cluster: str
    page_type: str
    intent: str
    trigger: str
    rationale: str
    build_difficulty: str
    maintenance_level: str
    evidence_confidence: Confidence


class Opportunity(BaseModel):
    id: str
    app_id: str
    game_name: str
    game_image_url: HttpUrl | None = None
    keyword: KeywordCandidate
    raw_score: float = Field(ge=0, le=100)
    score: float = Field(ge=0, le=100)
    score_breakdown: ScoreBreakdown
    status: OpportunityStatus
    missing_evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def restore_legacy_raw_score(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "raw_score" in value:
            return value
        breakdown = value.get("score_breakdown")
        if not isinstance(breakdown, dict):
            return value
        fields = (
            "problem_intensity",
            "page_intent",
            "feasibility",
            "maintenance",
            "game_signal",
            "evidence_confidence",
        )
        if all(isinstance(breakdown.get(field), (int, float)) for field in fields):
            value = dict(value)
            value["raw_score"] = round(sum(breakdown[field] for field in fields), 1)
        return value


class ScanSnapshot(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    generated_at: datetime = Field(default_factory=utc_now)
    country: str
    language: str
    is_demo: bool = False
    source_statuses: list[SourceStatus] = Field(default_factory=list)
    games: list[GameCandidate] = Field(default_factory=list)
    opportunities: list[Opportunity] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def state(self) -> SourceState:
        if not self.games:
            return SourceState.FAILED if self.errors else SourceState.PARTIAL
        degraded = {SourceState.PARTIAL, SourceState.FAILED, SourceState.UNAVAILABLE}
        if self.errors or any(s.state in degraded for s in self.source_statuses):
            return SourceState.PARTIAL
        return SourceState.OK


class SnapshotSummary(BaseModel):
    run_id: str
    generated_at: datetime
    country: str
    language: str
    is_demo: bool
    state: SourceState
    games_count: int = Field(ge=0)
    opportunities_count: int = Field(ge=0)


class GameSnapshotChange(BaseModel):
    app_id: str
    game_name: str
    change: str
    current_players: int | None = Field(default=None, ge=0)
    baseline_players: int | None = Field(default=None, ge=0)
    player_delta: int | None = None
    current_rank: int | None = Field(default=None, ge=1)
    baseline_rank: int | None = Field(default=None, ge=1)
    rank_delta: int | None = None
    current_signal: float | None = Field(default=None, ge=0, le=100)
    baseline_signal: float | None = Field(default=None, ge=0, le=100)
    signal_delta: float | None = None


class OpportunitySnapshotChange(BaseModel):
    opportunity_id: str
    app_id: str
    game_name: str
    keyword: str
    cluster: str
    page_type: str
    change: str
    current_score: float | None = Field(default=None, ge=0, le=100)
    baseline_score: float | None = Field(default=None, ge=0, le=100)
    score_delta: float | None = None


class SnapshotComparison(BaseModel):
    current_run_id: str
    baseline_run_id: str
    current_generated_at: datetime
    baseline_generated_at: datetime
    comparable: bool = True
    note: str
    new_games: int = Field(ge=0)
    removed_games: int = Field(ge=0)
    changed_games: int = Field(ge=0)
    new_opportunities: int = Field(ge=0)
    removed_opportunities: int = Field(ge=0)
    rising_opportunities: int = Field(ge=0)
    falling_opportunities: int = Field(ge=0)
    game_changes: list[GameSnapshotChange] = Field(default_factory=list)
    opportunity_changes: list[OpportunitySnapshotChange] = Field(default_factory=list)
