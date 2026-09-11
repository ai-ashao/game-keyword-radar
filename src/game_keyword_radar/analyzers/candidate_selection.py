"""Admit by a reason, then allocate by lane; never by the legacy Demand score."""
from __future__ import annotations
import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable
from game_keyword_radar.config import Settings
from game_keyword_radar.models import GameEntity, GameAnnotation, EvidenceItem, PlatformSignal
from game_keyword_radar.research_models import SelectionDecision, MomentumAssessment
from game_keyword_radar.policy_config import LANES, PRIMARY_LANES
from game_keyword_radar.observations import VALID, canonical, observation_id
from game_keyword_radar.analyzers.lifecycle import classify_lifecycle
from game_keyword_radar.analyzers.demand_momentum import number
from game_keyword_radar.analyzers.question_mining import RULES


def quotas(limit: int, weights: dict[str, float]) -> dict[str, int]:
    """Hamilton / largest-remainder allocation with insertion-order tie breaks."""
    if limit < 0 or not weights or any(not number(w) or w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError("Invalid allocation limit / weights")
    total = sum(weights.values())
    exact = {lane: limit * weight / total for lane, weight in weights.items()}
    result = {lane: math.floor(value) for lane, value in exact.items()}
    order = {key: index for index, key in enumerate(weights)}
    remainders = sorted(weights, key=lambda k: (-(exact[k] - result[k]), order[k]))
    for lane in remainders[:limit - sum(result.values())]:
        result[lane] += 1
    return result


def fresh_demand(evidence: Iterable[EvidenceItem], as_of: datetime, days: int) -> list[EvidenceItem]:
    """Dated, linked, task-specific evidence; discovery time is not publication time."""
    cutoff = as_of - timedelta(days=days)
    result, seen = [], set()
    for item in evidence:
        if item.is_inference or not item.url or item.published_at is None or not item.published_at.tzinfo:
            continue
        if not item.captured_at.tzinfo or item.captured_at > as_of or not cutoff <= item.published_at <= as_of:
            continue
        explicit = item.metrics.get("intent") in RULES
        if not explicit and not any(re.search(rule, item.title, re.I) for _, rule in RULES.values()):
            continue
        if item.source not in {"reddit", "youtube", "manual"}:
            continue
        # A copied title is not a second independent question, even across providers.
        key = re.sub(r"\W+", " ", item.title.casefold()).strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return sorted(result, key=lambda e: (e.source != "reddit", -e.published_at.timestamp(), e.id))


def initial_attention(signals: list[PlatformSignal], settings: Settings):
    cfg = settings.momentum
    checks = (("steam", "current_players", cfg.initial_steam_players),
              ("twitch", "total_viewers", cfg.initial_twitch_viewers),
              ("twitch", "live_channels", cfg.initial_twitch_channels))
    matches, gaps = [], []
    for source, metric, threshold in checks:
        s = next((x for x in signals if x.source == source and x.status in VALID), None)
        value = s.metrics.get(metric) if s else None
        if number(value) and value >= threshold:
            matches.append(observation_id(s))
        elif number(value):
            gaps.append(f"{source}.{metric}: {value:g} / 初始观察阈值 {threshold}（未达不等于零需求）")
    return list(dict.fromkeys(matches)), gaps


def decide_candidate(entity: GameEntity, signals: list[PlatformSignal], momentum: MomentumAssessment,
                     settings: Settings, as_of: datetime, *, evidence: list[EvidenceItem] | None = None,
                     manual: GameAnnotation | None = None) -> SelectionDecision:
    life = classify_lifecycle(entity, as_of, settings)
    decision = SelectionDecision(game_slug=entity.slug, lifecycle=life, momentum=momentum,
                                 policy_version=settings.selection.policy_version,
                                 config_hash=settings.policy_hash(), as_of=as_of)
    if manual and manual.checked_at > as_of:
        manual = None
    if entity.is_game is False or "non_game" in entity.manual_labels or (manual and manual.non_game):
        decision.decision = "excluded"
        decision.reason_codes = ["not_a_game"]
        decision.reasons = ["有明确非游戏分类依据，不进入游戏机会池"]
        return decision
    if "ignored" in entity.manual_labels or (manual and manual.ignored):
        decision.decision = "excluded"
        decision.reason_codes = ["manually_ignored"]
        decision.reasons = ["用户已明确忽略；原始记录保留"]
        return decision
    available = [s for s in signals if s.status in VALID and s.metrics and s.captured_at.tzinfo
                 and as_of - timedelta(hours=settings.momentum.window_hours) <= s.captured_at <= as_of]
    attention, gaps = initial_attention(available, settings)
    recent = fresh_demand(evidence or [], as_of, settings.selection.recent_demand_days)
    pending_manual = bool(manual and manual.research_requested_at and manual.research_requested_at <= as_of
                          and (manual.research_consumed_at is None or manual.research_consumed_at < manual.research_requested_at))
    lanes = []
    if life.recent_eligible and attention:
        lanes.append("new_release")
        decision.reason_codes.append("recent_release_initial_attention")
        decision.reasons.append(life.reason + "；已取得至少一种初始关注观测")
        decision.trigger_evidence_ids.extend([*life.evidence_ids, *attention])
    # Strong mixed-direction cases remain researchable, with the conflict visible.
    growth = [c for c in momentum.comparisons if c.absolute_delta is not None and c.absolute_delta > 0
              and c.strong and c.metric in {"current_players", "total_viewers"}]
    if growth and not (all(c.source == "twitch" for c in growth) and momentum.breadth == "concentrated"):
        lanes.append("rising")
        decision.reason_codes.append("qualified_growth" if momentum.rising_sources else "limited_growth_clue")
        decision.reasons.append("有可比多点增长观测" if momentum.rising_sources
                                else "有点对 / 部分样本增长线索，尚非持续增长结论")
        decision.trigger_evidence_ids.extend(momentum.trigger_evidence_ids)
    if recent:
        lanes.append("new_demand")
        decision.reason_codes.append("dated_task_evidence")
        decision.reasons.append("已有近期、可定位的具体页面任务；需求是否真正新增仍需人工核实")
        decision.trigger_evidence_ids.extend(e.id for e in recent)
    positive_early = any(c.absolute_delta is not None and c.absolute_delta > 0
                         and (c.strong or c.low_base or c.period == "intraday" and c.direction == "up")
                         for c in momentum.comparisons)
    unresolved_seed = (life.lifecycle in {"unknown", "preview"} and
                       bool(entity.discovery_sources or entity.platform_ids or (manual and manual.watch)))
    weak_new = life.recent_eligible and not attention
    # A large concentrated observation by itself does NOT give a known mature game a new trigger.
    concentrated_seed = (life.lifecycle != "established" and momentum.breadth == "concentrated"
                         and bool(attention))
    if weak_new or unresolved_seed or positive_early or concentrated_seed:
        lanes.append("exploration")
        reason = ("below_initial_attention" if weak_new else "early_growth_clue" if positive_early
                  else "concentrated_attention" if concentrated_seed else "identity_or_release_unverified")
        decision.reason_codes.append(reason)
        decision.reasons.append({"below_initial_attention": "近期发行但关注尚弱，保留探索 / 后续监测",
                                 "early_growth_clue": "有早期变化，基数 / 持续性尚不足",
                                 "concentrated_attention": "单次集中注意力，等待频道与非头部观众扩散",
                                 "identity_or_release_unverified": "游戏身份或发行阶段待核实，不将首次发现写成新游"}[reason])
        decision.trigger_evidence_ids.extend(momentum.trigger_evidence_ids or life.evidence_ids)
    if pending_manual:
        decision.entry_origin = "manual"
        lanes.append("exploration")
        decision.reason_codes.append("manual_research_request")
        decision.reasons.append("人工指定研究：" + manual.reason)
        if manual.evidence_url:
            decision.trigger_evidence_ids.append(str(manual.evidence_url))
    decision.eligible_lanes = [lane for lane in PRIMARY_LANES if lane in lanes]
    decision.primary_lane = next(iter(decision.eligible_lanes), None)
    if decision.primary_lane:
        decision.decision = "deferred_budget"  # Allocation is a separate operation.
    else:
        decision.reason_codes.append("mature_without_new_trigger" if life.lifecycle == "established" else "no_current_trigger")
        decision.reasons.append("只有规模 / 既有热榜证据，本轮不占自动深度名额；不代表没有商业价值")
    if life.recency_status != "verified":
        decision.missing_evidence.append("有来源的首次公开可玩发行时间")
    if momentum.state == "unknown":
        decision.missing_evidence.append("同口径独立历史观测")
    if not recent:
        decision.missing_evidence.append("近期具体问题 / 页面任务证据")
    decision.missing_evidence.extend(gaps if weak_new else [])
    decision.trigger_evidence_ids = list(dict.fromkeys(decision.trigger_evidence_ids))
    # New scan timestamps and slightly different raw values alone never bypass the cooldown.
    meaningful = [*decision.reason_codes, *life.evidence_ids, *sorted(e.id for e in recent),
                  *sorted(momentum.rising_sources), momentum.state if growth or positive_early else ""]
    decision.trigger_fingerprint = hashlib.sha256(canonical(meaningful).encode()).hexdigest()[:24]
    return decision


def _time(value: datetime | None) -> float:
    return value.timestamp() if value and value.tzinfo else 0


def _sort_key(decision: SelectionDecision, entity: GameEntity):
    momentum = decision.momentum
    grade = 0 if momentum.state in {"rising", "mixed"} and momentum.rising_sources else 1 if momentum.comparisons else 2
    waiting = (_time(entity.last_deep_analyzed_at), _time(entity.first_seen_at))
    if decision.primary_lane == "new_release":
        return (decision.lifecycle.recency_status != "verified", grade, *waiting, entity.slug)
    if decision.primary_lane == "rising":
        return (grade, momentum.persistence != "sustained_observation",
                momentum.breadth != "broadening", *waiting, entity.slug)
    if decision.primary_lane == "new_demand":
        return (len(decision.missing_evidence), *waiting, entity.slug)
    return (*waiting, _time(entity.last_observed_at), entity.slug)


def allocate_deep(decisions: list[SelectionDecision], entities: list[GameEntity], settings: Settings,
                  as_of: datetime, limit: int) -> dict:
    if not 0 <= limit <= 30:
        raise ValueError("Deep limit must be between 0 and 30")
    entity_map = {e.slug: e for e in entities}
    if len({d.game_slug for d in decisions}) != len(decisions):
        raise ValueError("Duplicate selection decision for one entity")
    eligible = [d for d in decisions if d.primary_lane and d.decision != "excluded"]
    ready = []
    for d in eligible:
        e = entity_map[d.game_slug]
        cooling = bool(e.last_deep_analyzed_at and e.last_deep_analyzed_at <= as_of
                       and as_of - e.last_deep_analyzed_at < timedelta(hours=settings.selection.deep_cooldown_hours))
        unchanged_trigger = not e.last_deep_trigger_fingerprint or e.last_deep_trigger_fingerprint == d.trigger_fingerprint
        if cooling and unchanged_trigger and d.entry_origin != "manual":
            d.reason_codes.append("deep_cooldown")
            d.reasons.append("同一有效触发仍处于自动深度分析冷却期")
        else:
            ready.append(d)
    manual = sorted((d for d in ready if d.entry_origin == "manual"), key=lambda d: d.game_slug)[:limit]
    automatic_budget = limit - len(manual)
    initial = quotas(automatic_budget, settings.selection.weights)
    exploratory_cap = math.ceil(settings.selection.exploration_max_share * automatic_budget)
    groups = {lane: sorted((d for d in ready if d.entry_origin != "manual" and d.primary_lane == lane),
                           key=lambda d: _sort_key(d, entity_map[d.game_slug])) for lane in LANES}
    chosen = list(manual)
    counts = {lane: 0 for lane in LANES}
    for lane in LANES:
        amount = min(initial[lane], exploratory_cap) if lane == "exploration" else initial[lane]
        picked = groups[lane][:amount]
        chosen.extend(picked)
        counts[lane] += len(picked)
        groups[lane] = groups[lane][len(picked):]
    for lane in LANES:
        amount = limit - len(chosen)
        if lane == "exploration":
            amount = min(amount, exploratory_cap - counts[lane])
        picked = groups[lane][:max(0, amount)]
        chosen.extend(picked)
        counts[lane] += len(picked)
    chosen_slugs = {d.game_slug for d in chosen}
    for index, d in enumerate(chosen, 1):
        d.decision = "selected"
        d.selected_for_deep = True
        d.selection_order = index
        d.reason_codes.append("manual_budget_allocated" if d.entry_origin == "manual" else "lane_budget_allocated")
    for d in eligible:
        if d.game_slug not in chosen_slugs and "deep_cooldown" not in d.reason_codes:
            d.reason_codes.append("deep_budget_deferred")
            d.reasons.append("符合候选条件，但本轮名额不足 / 探索占比上限；保留至后续轮转")
    return {"eligible_entities": len(eligible), "deep_budget": limit, "deep_selected": len(chosen),
            "automatic_selected": len(chosen) - len(manual), "manual_selected": len(manual),
            "lane_quotas": initial, "lane_selected": counts, "exploration_cap": exploratory_cap,
            "unused_deep_slots": limit - len(chosen),
            "budget_deferred": sum(d.decision == "deferred_budget" for d in decisions),
            "mature_without_trigger": sum("mature_without_new_trigger" in d.reason_codes for d in decisions),
            "monitor_only": sum(d.decision == "monitor_only" for d in decisions),
            "excluded": sum(d.decision == "excluded" for d in decisions),
            "needs_review": sum(e.needs_review for e in entities)}


def allocate_basic(entities: list[GameEntity], settings: Settings, as_of: datetime, limit: int,
                   *, tracked_slugs: set[str] | None = None, metadata: bool = False) -> list[GameEntity]:
    """Protect recent-release ingress before fresh metrics exist; round-robin others."""
    tracked_slugs = tracked_slugs or set()
    groups = {"recent": [], "tracked": [], "unresolved": []}
    for e in entities:
        if e.is_game is False or set(e.manual_labels) & {"ignored", "non_game"}:
            continue
        life = classify_lifecycle(e, as_of, settings)
        recent_hint = bool(set(e.discovery_sources) & {"popular_new", "steam_popular_new"})
        if life.recent_eligible or recent_hint and life.lifecycle != "established":
            lane = "recent"
        elif e.slug in tracked_slugs:
            lane = "tracked"
        elif life.lifecycle in {"unknown", "preview"}:
            lane = "unresolved"
        elif metadata:
            # Low-frequency mature metadata refresh may use only leftover unresolved slots.
            lane = "unresolved"
        else:
            continue
        groups[lane].append(e)
    for lane in groups:
        groups[lane].sort(key=lambda e: (_time(e.last_observed_at), _time(e.last_deep_analyzed_at),
                                        min(e.discovery_ranks.values(), default=99999) if metadata else 0, e.slug))
    cfg = settings.discovery_budget
    weights = {"recent": cfg.recent_release_metadata_share,
               "tracked": cfg.tracked_trigger_metadata_share, "unresolved": cfg.unresolved_metadata_share}
    counts = quotas(limit, weights)
    selected = []
    for lane in groups:
        selected.extend(groups[lane][:counts[lane]])
        groups[lane] = groups[lane][counts[lane]:]
    for lane in groups:
        selected.extend(groups[lane][:max(0, limit - len(selected))])
    return selected
