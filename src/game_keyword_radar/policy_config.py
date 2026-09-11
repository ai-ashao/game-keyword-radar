"""Versioned V2.1 policy defaults. All thresholds are calibration hypotheses."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

LANES = ("new_release", "rising", "new_demand", "exploration")
PRIMARY_LANES = ("new_release", "new_demand", "rising", "exploration")


class StrictPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SelectionSettings(StrictPolicy):
    policy_version: str = Field(default="selection-2.1-r1", min_length=1, max_length=80)
    profile: Literal["opportunity"] = "opportunity"
    new_release_days: int = Field(default=90, ge=1, le=365)
    new_release_weight: int = Field(default=4, ge=0, le=100)
    rising_weight: int = Field(default=3, ge=0, le=100)
    new_demand_weight: int = Field(default=1, ge=0, le=100)
    exploration_weight: int = Field(default=2, ge=0, le=100)
    exploration_max_share: float = Field(default=.4, ge=0, le=1)
    allow_unfilled_slots: Literal[True] = True
    allow_single_source_candidates: Literal[True] = True
    require_twitch_for_each_game: Literal[False] = False
    mature_without_trigger: Literal["monitor_only"] = "monitor_only"
    deep_cooldown_hours: float = Field(default=24, ge=0, le=720)
    # Explicit implementation default for the plan's "recent demand" window.
    recent_demand_days: int = Field(default=14, ge=1, le=90)

    @model_validator(mode="after")
    def nonempty_weights(self):
        if not sum(self.weights.values()):
            raise ValueError("At least one selection lane must have positive weight")
        return self

    @property
    def weights(self) -> dict[str, int]:
        return {lane: getattr(self, f"{lane}_weight") for lane in LANES}


class MonitoringSettings(StrictPolicy):
    enabled: bool = False
    interval_minutes: int = Field(default=120, ge=1, le=1440)
    active_entity_limit: int = Field(default=80, ge=1, le=100)
    twitch_pages_per_game: int = Field(default=3, ge=1, le=10)


class DiscoveryBudget(StrictPolicy):
    source_row_limit: int = Field(default=100, ge=1, le=100)
    metadata_requests_per_scan: int = Field(default=80, ge=0, le=200)
    recent_release_metadata_share: float = Field(default=.6, ge=0, le=1)
    tracked_trigger_metadata_share: float = Field(default=.2, ge=0, le=1)
    unresolved_metadata_share: float = Field(default=.2, ge=0, le=1)

    @model_validator(mode="after")
    def shares_sum_to_one(self):
        total = sum((self.recent_release_metadata_share,
                     self.tracked_trigger_metadata_share, self.unresolved_metadata_share))
        if abs(total - 1) > 1e-6:
            raise ValueError("Metadata allocation shares must sum to 1")
        return self


class RequestBudget(StrictPolicy):
    steam_attempts_per_run: int = Field(default=260, ge=0, le=2000)
    twitch_attempts_per_run: int = Field(default=260, ge=0, le=2000)
    count_failed_attempts: Literal[True] = True


class MomentumSettings(StrictPolicy):
    initial_steam_players: int = Field(default=250, ge=1)
    initial_twitch_viewers: int = Field(default=100, ge=1)
    initial_twitch_channels: int = Field(default=3, ge=1)
    window_hours: float = Field(default=6, ge=4, le=24)
    minimum_unique_observations: int = Field(default=3, ge=3, le=20)
    minimum_span_hours: float = Field(default=4, gt=0, le=24)
    match_24h_tolerance_hours: float = Field(default=1, gt=0, le=3)
    match_7d_tolerance_hours: float = Field(default=2, gt=0, le=6)
    steam_baseline_floor: int = Field(default=100, ge=1)
    steam_growth_fraction: float = Field(default=.4, gt=0, le=10)
    steam_absolute_growth: int = Field(default=200, ge=1)
    twitch_viewer_baseline_floor: int = Field(default=100, ge=1)
    twitch_viewer_growth_fraction: float = Field(default=.4, gt=0, le=10)
    twitch_viewer_absolute_growth: int = Field(default=100, ge=1)
    twitch_channel_baseline_floor: int = Field(default=5, ge=1)
    twitch_channel_growth_fraction: float = Field(default=.5, gt=0, le=10)
    twitch_channel_absolute_growth: int = Field(default=3, ge=1)
    top1_concentration_warning: float = Field(default=.7, gt=0, le=1)
    direction_deadband_fraction: float = Field(default=.1, ge=0, lt=1)

    @model_validator(mode="after")
    def window_contains_span(self):
        if self.minimum_span_hours > self.window_hours:
            raise ValueError("minimum_span_hours must not exceed window_hours")
        if self.direction_deadband_fraction >= min(self.steam_growth_fraction,
            self.twitch_viewer_growth_fraction, self.twitch_channel_growth_fraction):
            raise ValueError("Direction deadband must be smaller than growth thresholds")
        return self
