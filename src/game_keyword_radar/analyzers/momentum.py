"""Window-based changes, not popularity-based predictions.

Raw differences are retained even when evidence is insufficient for 'rising'.
All decisions are made using only observations that existed at as_of.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from functools import lru_cache
from statistics import median
from game_keyword_radar.config import Settings
from game_keyword_radar.models import PlatformSignal
from game_keyword_radar.research_models import MomentumAssessment, MomentumComparison
from game_keyword_radar.observations import VALID, scope_key, observation_id, unique_observations
from game_keyword_radar.analyzers.demand_momentum import number

METRICS = {"steam": ("current_players",),
           "twitch": ("total_viewers", "live_channels", "non_top1_viewers")}


def span(rows: list[PlatformSignal]) -> float:
    return (rows[-1].captured_at - rows[0].captured_at).total_seconds() / 3600 if len(rows) > 1 else 0


def paired_windows(current, baseline, hours, tolerance):
    """Maximum-cardinality, minimum-offset chronological one-to-one pairing."""
    target_seconds, tolerance_seconds = hours * 3600, tolerance * 3600
    # Full retained history is not modified; bound the combinatorial pairing input.
    # Evenly preserve the time range when users manually oversample a window.
    def bounded(rows):
        if len(rows) <= 48:
            return rows
        return [rows[round(i * (len(rows) - 1) / 47)] for i in range(48)]
    current, baseline = bounded(current), bounded(baseline)

    @lru_cache(None)
    def solve(i, j):
        if i == len(current) or j == len(baseline):
            return (0, 0.0, ())
        options = [solve(i + 1, j), solve(i, j + 1)]
        elapsed = (current[i].captured_at - baseline[j].captured_at).total_seconds()
        distance = abs(elapsed - target_seconds)
        if elapsed > 0 and distance <= tolerance_seconds:
            count, cost, pairs = solve(i + 1, j + 1)
            options.append((count + 1, cost + distance, ((i, j),) + pairs))
        return min(options, key=lambda v: (-v[0], v[1], v[2]))

    return [(current[i], baseline[j]) for i, j in solve(0, 0)[2]]


def thresholds(source, metric, cfg):
    if source == "steam":
        return cfg.steam_baseline_floor, cfg.steam_growth_fraction, cfg.steam_absolute_growth
    if metric == "live_channels":
        return cfg.twitch_channel_baseline_floor, cfg.twitch_channel_growth_fraction, cfg.twitch_channel_absolute_growth
    return cfg.twitch_viewer_baseline_floor, cfg.twitch_viewer_growth_fraction, cfg.twitch_viewer_absolute_growth


def make_comparison(source, metric, current, base, period, cfg, *, window=False):
    c, b = median(s.metrics[metric] for s in current), median(s.metrics[metric] for s in base)
    floor, fraction, absolute = thresholds(source, metric, cfg)
    low_base = b < floor
    delta = c - b
    percent = delta / b * 100 if b > 0 and not low_base else None
    limited = source == "twitch" and (
        current[-1].metrics.get("sampling_scope") != "game_streams"
        or current[-1].metrics.get("sampling_complete") is not True)
    qualified = bool(window and not limited and not low_base)
    kind = "intraday" if period == "intraday" else "sample_window" if window and limited else "window" if window else "point_pair"
    direction = "unknown" if percent is None else "up" if percent > cfg.direction_deadband_fraction * 100 else "down" if percent < -cfg.direction_deadband_fraction * 100 else "flat"
    strong = (percent is not None and abs(percent) >= fraction * 100 and abs(delta) >= absolute)
    limitations = []
    if low_base:
        limitations.append("low_base：只展示绝对变化，不以极小 / 零基数百分比排序")
    if limited:
        limitations.append("仅同口径样本变化，不能认证全游戏增长")
    if not window:
        limitations.append("点对 / 日内线索，不是24h/7d持续增长证据")
    return MomentumComparison(source=source, metric=metric, period=period,
        current_value=c, baseline_value=b, absolute_delta=delta, percent_change=percent,
        comparison_kind=kind, qualified=qualified, low_base=low_base, direction=direction,
        strong=strong, pair_count=len(current), current_span_hours=round(span(current), 3),
        baseline_span_hours=round(span(base), 3),
        current_observation_ids=[observation_id(s) for s in current],
        baseline_observation_ids=[observation_id(s) for s in base],
        actual_elapsed_hours=[round((a.captured_at - z.captured_at).total_seconds() / 3600, 3)
                              for a, z in zip(current, base)], limitations=limitations)


def assess_momentum(game_slug: str, signals: list[PlatformSignal], prior: list[PlatformSignal],
                    settings: Settings, as_of: datetime) -> MomentumAssessment:
    if as_of.tzinfo is None:
        raise ValueError("as_of must contain a timezone")
    cfg = settings.momentum
    result = MomentumAssessment(as_of=as_of)
    current_sources = {s.source: s for s in signals if s.game_slug == game_slug}
    latest_twitch = None
    for source, metrics in METRICS.items():
        latest = current_sources.get(source)
        # Failed current readings never manufacture a new observation from an old value.
        if latest is None or latest.status not in VALID or not latest.captured_at.tzinfo or latest.captured_at > as_of:
            continue
        if as_of - latest.captured_at > timedelta(hours=cfg.window_hours):
            result.limitations.append(f"{source}: 最近观测已经过期")
            continue
        if source == "twitch":
            latest_twitch = latest
        all_rows = unique_observations([*prior, latest], as_of)
        all_rows = [s for s in all_rows if s.game_slug == game_slug and s.source == source
                    and s.origin == latest.origin and s.captured_at <= latest.captured_at]
        comparable_rows = [s for s in all_rows if scope_key(s) == scope_key(latest)]
        if len(all_rows) != len(comparable_rows):
            result.limitations.append(f"{source}: 不同口径 / 版本观测未用于比较")
        for metric in metrics:
            rows = [s for s in comparable_rows if number(s.metrics.get(metric)) and s.metrics[metric] >= 0]
            if not rows or observation_id(rows[-1]) != observation_id(latest):
                continue
            t = latest.captured_at
            current = [s for s in rows if t - timedelta(hours=cfg.window_hours) <= s.captured_at <= t]
            for period, hours, tolerance in (("24h", 24, cfg.match_24h_tolerance_hours),
                                             ("7d", 168, cfg.match_7d_tolerance_hours)):
                baseline = [s for s in rows
                            if t - timedelta(hours=hours + cfg.window_hours + tolerance) <= s.captured_at
                            <= t - timedelta(hours=hours - tolerance)]
                pairs = paired_windows(current, baseline, hours, tolerance)
                if not pairs:
                    continue
                now_rows, old_rows = [a for a, _ in pairs], [b for _, b in pairs]
                multi = (len(pairs) >= cfg.minimum_unique_observations
                         and span(now_rows) >= cfg.minimum_span_hours
                         and span(old_rows) >= cfg.minimum_span_hours)
                result.comparisons.append(make_comparison(source, metric, now_rows, old_rows, period, cfg, window=multi))
            if len(current) >= cfg.minimum_unique_observations and span(current) >= cfg.minimum_span_hours:
                # Intraday uses actual end points; never labels this a daily average.
                row = make_comparison(source, metric, current[-1:], current[:1], "intraday", cfg)
                row.pair_count = len(current)
                row.current_span_hours = round(span(current), 3)
                row.current_observation_ids = [observation_id(s) for s in current]
                result.comparisons.append(row)
    if latest_twitch:
        m = latest_twitch.metrics
        share = m.get("top1_viewer_share", m.get("audience_concentration"))
        channels = m.get("live_channels")
        if number(share) and share > cfg.top1_concentration_warning:
            result.breadth = "concentrated"
            result.limitations.append("Twitch观众集中于单个直播间；不直接推断赛事、推广或虚假流量")
        elif number(channels) and channels >= cfg.initial_twitch_channels and number(share):
            result.breadth = "distributed"
        channel_up = any(c.source == "twitch" and c.metric == "live_channels"
                         and c.direction == "up" and c.strong for c in result.comparisons)
        non_head_up = any(c.source == "twitch" and c.metric == "non_top1_viewers"
                          and c.absolute_delta is not None and c.absolute_delta > 0 for c in result.comparisons)
        if channel_up and non_head_up:
            result.breadth = "broadening"
    primary = [c for c in result.comparisons if (c.source, c.metric) in
               {("steam", "current_players"), ("twitch", "total_viewers")}]
    qualified = [c for c in primary if c.qualified]
    up = [c for c in qualified if c.direction == "up"]
    down = [c for c in qualified if c.direction == "down"]
    strong_up = [c for c in up if c.strong and not (c.source == "twitch" and result.breadth == "concentrated")]
    strong_down = [c for c in down if c.strong]
    early = [c for c in result.comparisons if c.absolute_delta is not None and c.absolute_delta > 0
             and (c.strong or c.low_base or c.period == "intraday" and c.direction == "up")]
    if up and down:
        result.state = "mixed"
        result.conflicting_sources = sorted({c.source for c in [*up, *down]})
    elif strong_up:
        result.state = "rising"
    elif strong_down:
        result.state = "falling"
    elif early or (latest_twitch is not None and result.breadth == "concentrated"
                   and number(latest_twitch.metrics.get("total_viewers"))
                   and latest_twitch.metrics["total_viewers"] >= cfg.initial_twitch_viewers):
        result.state = "early_signal"
    elif qualified and all(c.direction == "flat" for c in qualified):
        result.state = "stable"
    elif primary:
        result.state = "inconclusive"
    result.rising_sources = sorted({c.source for c in strong_up})
    if qualified:
        result.persistence = "sustained_observation"
    elif latest_twitch is not None and result.breadth == "concentrated":
        result.persistence = "single_spike"
        result.limitations.append("单次集中观测；没有基线时不能证明发生了时间上的暴涨")
    relevant = [c for c in result.comparisons if c.strong or c.low_base]
    if relevant:
        result.period = next((p for p in ("24h", "7d", "intraday") if any(c.period == p for c in relevant)), "none")
    elif result.comparisons:
        result.period = result.comparisons[0].period
    if not result.comparisons:
        result.limitations.append("缺少独立、同口径的历史基线；不是稳定或零需求")
    result.trigger_evidence_ids = list(dict.fromkeys(
        identifier for c in relevant for identifier in [*c.current_observation_ids, *c.baseline_observation_ids]))
    return result
