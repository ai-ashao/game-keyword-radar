from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Literal

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
    INSUFFICIENT_DATA = "insufficient_data"
    BUDGET_EXHAUSTED = "budget_exhausted"
    STALE = "stale"


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


class GameEntity(BaseModel):
    canonical_name: str
    slug: str
    aliases: list[str] = Field(default_factory=list)
    platform_ids: dict[str, str] = Field(default_factory=dict)
    subreddits: list[str] = Field(default_factory=list)
    youtube_queries: list[str] = Field(default_factory=list)
    trends_terms: list[str] = Field(default_factory=list)
    release_date: date | None = None
    genres: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    mechanics: list[str] = Field(default_factory=list)
    understanding_confidence: Confidence = Confidence.LOW
    entity_match_confidence: float = Field(default=1, ge=0, le=1)
    match_method: str = "new"
    needs_review: bool = False


class EvidenceItem(BaseModel):
    id: str
    source: str
    title: str
    url: HttpUrl | None = None
    published_at: datetime | None = None
    captured_at: datetime = Field(default_factory=utc_now)
    author: str | None = None
    text: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    is_inference: bool = False


class PlatformSignal(BaseModel):
    source: str
    game_slug: str
    captured_at: datetime = Field(default_factory=utc_now)
    market: str = "US"
    status: SourceState = SourceState.OK
    confidence: Confidence = Confidence.LOW
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    history: dict[str, Any] = Field(default_factory=dict)
    cache_hit: bool = False
    origin: Literal["live", "demo"] = "live"
    entity_match_confidence: float = Field(default=1, ge=0, le=1)


class QuestionCluster(BaseModel):
    id: str
    game_slug: str
    cluster_name: str
    intent: str
    examples: list[EvidenceItem] = Field(default_factory=list)
    source_count: int = Field(default=0, ge=0)
    question_count: int = Field(default=0, ge=0)
    unique_authors: int = Field(default=0, ge=0)
    confidence: Confidence = Confidence.LOW


class DemandScore(BaseModel):
    score: float | None = Field(default=None, ge=0, le=100)
    # Missing components stay null. score is normalized over observed sources.
    components: dict[str, float | None] = Field(default_factory=dict)
    observed_weight: float = 0
    coverage: float = Field(default=0, ge=0, le=1)
    available_sources: list[str] = Field(default_factory=list)
    rising_sources: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.LOW
    note: str = "Observed-source research priority, not search volume or a success probability."


class PageOpportunity(BaseModel):
    id: str
    game_slug: str
    page_type: str
    path: str
    primary_keyword_hypothesis: str
    supporting_queries: list[str] = Field(default_factory=list)
    trigger_signals: list[EvidenceItem] = Field(default_factory=list)
    user_problem: str
    page_value: str
    maintenance_level: str
    build_difficulty: str
    existing_site_fit: str | None = None
    route_reason: str | None = None
    validation_status: str = "needs_validation"
    raw_score: float = Field(ge=0, le=100)
    score: float = Field(ge=0, le=69)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    evidence_level: str = "hypothesis"
    keyword_candidates: list[KeywordCandidate] = Field(default_factory=list)


class GameOpportunity(BaseModel):
    game_slug: str
    demand: DemandScore
    page_ids: list[str] = Field(default_factory=list)
    action: Literal["WATCH", "VALIDATE", "EXPAND_EXISTING_SITE", "VALIDATE_NEW_SITE", "SKIP"] = "WATCH"
    action_reason: str
    rank: int | None = None
    best_page_score: float | None = None
    research_priority: float = Field(default=0, ge=0, le=100)


class ValidationRecord(BaseModel):
    source_run_id: str = ""
    page_id: str
    game_slug: str
    keyword: str
    market: str
    language: str = "english"
    is_demo: bool = False
    stage: Literal["pending_semrush", "pending_serp", "validated", "skip"] = "pending_semrush"
    semrush_volume: int | None = Field(default=None, ge=0)
    semrush_kd: float | None = Field(default=None, ge=0, le=100)
    semrush_evidence: str = Field(default="", max_length=4000)
    semrush_checked_at: datetime | None = None
    serp_urls: list[HttpUrl] = Field(default_factory=list, max_length=10)
    serp_notes: str = Field(default="", max_length=8000)
    serp_checked_at: datetime | None = None
    decision: Literal["undecided", "build", "skip"] = "undecided"
    decision_reason: str = Field(default="", max_length=4000)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def require_manual_evidence(self):
        if self.stage in {"pending_serp", "validated"}:
            if self.semrush_volume is None or not self.semrush_evidence.strip() or not self.semrush_checked_at:
                raise ValueError("Semrush volume, evidence and checked date are required; zero is a valid observed volume.")
        if self.stage == "validated":
            if len(set(str(u) for u in self.serp_urls)) < 3 or not self.serp_notes.strip() or not self.serp_checked_at:
                raise ValueError("Validation requires at least three distinct inspected SERP URLs, notes and checked date.")
            if self.decision == "undecided" or not self.decision_reason.strip():
                raise ValueError("A manual Build/Skip decision and rationale are required.")
        if self.decision == "build" and self.stage != "validated":
            raise ValueError("Build is not allowed before manual validation.")
        if self.stage == "skip" and not self.decision_reason.strip():
            raise ValueError("Skipping requires a reason.")
        for checked in (self.semrush_checked_at, self.serp_checked_at):
            if checked and (checked.tzinfo is None or checked > utc_now()):
                raise ValueError("Checked dates must be timezone-aware and not in the future.")
        return self


class ScanSnapshot(BaseModel):
    schema_version: str | int = "1.0"
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
    entities: list[GameEntity] = Field(default_factory=list)
    platform_signals: list[PlatformSignal] = Field(default_factory=list)
    question_clusters: list[QuestionCluster] = Field(default_factory=list)
    page_opportunities: list[PageOpportunity] = Field(default_factory=list)
    game_opportunities: list[GameOpportunity] = Field(default_factory=list)

    @property
    def state(self) -> SourceState:
        if not self.games and not self.entities:
            return SourceState.FAILED if self.errors else SourceState.PARTIAL
        degraded = {SourceState.PARTIAL, SourceState.FAILED, SourceState.UNAVAILABLE, SourceState.STALE, SourceState.BUDGET_EXHAUSTED}
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
