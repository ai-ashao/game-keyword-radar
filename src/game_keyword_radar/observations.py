"""Observation identity and measurement scope, shared by full and lightweight runs."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from typing import Iterable
from game_keyword_radar.models import PlatformSignal, SourceState

VALID = {SourceState.OK, SourceState.PARTIAL}
SCOPE_FIELDS = {
    "steam": ("country", "metric_region", "measurement", "language"),
    "twitch": ("sampling_scope", "sampling_complete", "sample_page_limit", "language", "game_id"),
    "youtube": ("queries", "region_code", "relevance_language", "window_days"),
    "reddit": ("subreddits", "window_days"),
    "trends": ("provider", "term", "geo", "timeframe", "normalization"),
}


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def scope_key(signal: PlatformSignal) -> str:
    fields = {}
    for key in SCOPE_FIELDS.get(signal.source, ()):
        value = signal.metrics.get(key)
        fields[key] = sorted(value) if isinstance(value, list) and all(isinstance(x, str) for x in value) else value
    return canonical([signal.source, signal.game_slug, signal.market, signal.origin,
                      signal.scope_version, signal.metric_scope, fields])


def observation_id(signal: PlatformSignal) -> str:
    if signal.observation_id:
        return signal.observation_id
    # Derived cluster counts, provenance notes and legacy scores cannot mint samples.
    metrics = {k: v for k, v in signal.metrics.items()
               if k not in {"repeated_question_clusters", "twitch_rank", "category_rank"}}
    captured = signal.captured_at
    stamp = captured.astimezone(timezone.utc).isoformat() if captured.tzinfo else captured.isoformat()
    return hashlib.sha256(canonical([scope_key(signal), stamp, metrics]).encode()).hexdigest()[:24]


def stamp_observation(signal: PlatformSignal) -> PlatformSignal:
    if signal.status in VALID and signal.metrics and signal.observation_id is None:
        signal.observation_id = observation_id(signal)
    return signal


def unique_observations(signals: Iterable[PlatformSignal], as_of: datetime) -> list[PlatformSignal]:
    result = {}
    for signal in signals:
        if signal.status not in VALID or not signal.captured_at.tzinfo or signal.captured_at > as_of:
            continue
        key = observation_id(signal)
        result.setdefault(key, signal)
    return sorted(result.values(), key=lambda s: (s.captured_at, observation_id(s)))
