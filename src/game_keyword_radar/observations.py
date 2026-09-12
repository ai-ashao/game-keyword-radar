"""Observation identity and measurement scope, shared by full and lightweight runs."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from typing import Iterable
from game_keyword_radar.models import PlatformSignal, SourceState

VALID = {SourceState.OK, SourceState.PARTIAL}
SCOPE_FIELDS = {
    "steam": ("provider", "country", "metric_region", "measurement", "metric_unit", "language"),
    "twitch": ("provider", "sampling_scope", "sampling_complete", "sample_page_limit", "measurement", "window", "metric_unit", "language", "game_id"),
    "youtube": ("provider", "queries", "region_code", "relevance_language", "window_days", "measurement", "metric_unit"),
    "reddit": ("provider", "subreddits", "window_days", "language"),
    "trends": ("provider", "term", "geo", "timeframe", "normalization", "search_type", "language"),
}


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def scope_key(signal: PlatformSignal) -> str:
    """Stable measurement-scope key.

    Comparisons are only meaningful when provider, metric scope, market, window/measurement,
    and applicable language are the same.  Cross-provider evidence may corroborate a decision
    but must not be stitched into one numeric time series.
    """
    fields = {}
    for key in SCOPE_FIELDS.get(signal.source, ()):
        value = signal.metrics.get(key)
        fields[key] = sorted(value) if isinstance(value, list) and all(isinstance(x, str) for x in value) else value
    return canonical([signal.source, signal.game_slug, signal.market, signal.origin,
                      signal.scope_version, signal.metric_scope, fields])


def comparable(a: PlatformSignal, b: PlatformSignal) -> bool:
    return (a.game_slug == b.game_slug and a.source == b.source and a.origin == b.origin
            and scope_key(a) == scope_key(b))


def observation_id(signal: PlatformSignal) -> str:
    if signal.observation_id:
        return signal.observation_id
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
