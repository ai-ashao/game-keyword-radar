"""Timestamp-aware observed-signal comparisons. Cached samples cannot create growth."""
from __future__ import annotations
from datetime import timedelta
from game_keyword_radar.models import SourceState

PRIMARY = {'steam':'current_players','twitch':'total_viewers','youtube':'recent_guide_video_count','reddit':'question_count','trends':'recent_interest'}

def scope_key(signal):
    m = signal.metrics
    keys = {'steam':['country'], 'twitch':['sampling_scope','sampling_complete','sample_page_limit'],
            'youtube':['queries','region_code','relevance_language','window_days'],
            'reddit':['subreddits'],'trends':['term','geo','timeframe']}.get(signal.source,[])
    return repr([signal.source,signal.game_slug,signal.market,signal.origin,[(k,m.get(k)) for k in keys]])

def change(current, baseline):
    primary = PRIMARY.get(current.source)
    values = {}
    for key,value in current.metrics.items():
        old = baseline.metrics.get(key)
        if isinstance(value,(int,float)) and not isinstance(value,bool) and isinstance(old,(int,float)) and not isinstance(old,bool):
            values[key] = {'current':value,'baseline':old,'delta':value-old,'percent':(value-old)/old*100 if old!=0 else None}
    return {'baseline_captured_at':baseline.captured_at.isoformat(),'current_captured_at':current.captured_at.isoformat(),
        'elapsed_hours':round((current.captured_at-baseline.captured_at).total_seconds()/3600,3),
        'primary_metric':primary,'primary_percent':values.get(primary,{}).get('percent'), 'metrics':values,
        'note':'Snapshot observation difference, not daily average or search-volume forecast. Zero baseline has no percentage.'}

def attach_history(signals, snapshots, settings):
    prior = [s for snap in snapshots for s in snap.platform_signals]
    for signal in signals:
        signal.history = {}
        if signal.status not in {SourceState.OK,SourceState.PARTIAL}: continue
        eligible = [s for s in prior if scope_key(s)==scope_key(signal) and s.status in {SourceState.OK,SourceState.PARTIAL}
                    and s.captured_at < signal.captured_at]
        if not eligible: continue
        previous = max(eligible,key=lambda s:s.captured_at)
        signal.history['previous'] = change(signal,previous)
        for label,hours,tolerance in [('24h',24,settings.history_24h_tolerance_hours),('7d',168,settings.history_7d_tolerance_hours)]:
            target = signal.captured_at-timedelta(hours=hours)
            candidates = [s for s in eligible if abs((s.captured_at-target).total_seconds())<=tolerance*3600]
            if candidates:
                signal.history[label] = change(signal,min(candidates,key=lambda s:abs((s.captured_at-target).total_seconds())))
    return signals

def compare_v2(current, baseline):
    from game_keyword_radar.observations import scope_key as measurement_scope
    metadata_equal = (current.country, current.language, current.is_demo) == (baseline.country, baseline.language, baseline.is_demo)
    policy_equal = (current.analysis_version, current.selection_policy_version, current.policy_config_hash) == (baseline.analysis_version, baseline.selection_policy_version, baseline.policy_config_hash)
    comparable = metadata_equal and policy_equal
    oldsignals = {(s.game_slug, s.source): s for s in baseline.platform_signals}
    platform_changes = []
    for s in current.platform_signals:
        old = oldsignals.get((s.game_slug, s.source))
        if metadata_equal and old and measurement_scope(s) == measurement_scope(old) and s.captured_at > old.captured_at and s.status in {SourceState.OK, SourceState.PARTIAL} and old.status in {SourceState.OK, SourceState.PARTIAL}:
            platform_changes.append({'game_slug': s.game_slug, 'source': s.source, **change(s, old)})
    oldgames = {g.game_slug: g for g in baseline.game_opportunities}
    newpages = {p.id: p for p in current.page_opportunities}
    oldpages = {p.id: p for p in baseline.page_opportunities}
    game_changes = []
    for game in current.game_opportunities:
        old = oldgames.get(game.game_slug)
        rank = old.rank - game.rank if old and old.rank and game.rank else None
        score = round(game.demand.score - old.demand.score, 1) if old and game.demand.score is not None and old.demand.score is not None else None
        current_scopes = sorted(measurement_scope(s) for s in current.platform_signals if s.game_slug == game.game_slug and s.status in {SourceState.OK, SourceState.PARTIAL})
        old_scopes = sorted(measurement_scope(s) for s in baseline.platform_signals if s.game_slug == game.game_slug and s.status in {SourceState.OK, SourceState.PARTIAL})
        score_comparable = bool(old and comparable and set(game.demand.available_sources) == set(old.demand.available_sources) and current_scopes == old_scopes)
        page_changed = bool(old and set(game.page_ids) != set(old.page_ids))
        fields = []
        if old:
            if game.rank != old.rank: fields.append('rank')
            if game.demand.score != old.demand.score: fields.append('score')
            if page_changed: fields.append('pages')
            if game.demand.coverage != old.demand.coverage: fields.append('coverage')
            if game.action != old.action: fields.append('action')
        game_changes.append({'game_slug': game.game_slug, 'change': 'new' if old is None else 'changed' if fields else 'unchanged',
            'changed_fields': fields, 'rank_change': rank, 'demand_score_change': score,
            'score_comparable': score_comparable, 'pages_changed': page_changed,
            'coverage_change': round(game.demand.coverage-old.demand.coverage, 3) if old else None})
    return {'comparable': comparable, 'current_run_id': current.run_id, 'baseline_run_id': baseline.run_id,
        'note': '观测差异不是搜索量预测。政策、分析版本、可用来源或采样范围不同，分数变化不可解释为需求变化。',
        'v2_game_changes': game_changes, 'platform_changes': platform_changes,
        'score_changed_games': sum('score' in g['changed_fields'] for g in game_changes),
        'rank_changed_games': sum('rank' in g['changed_fields'] for g in game_changes),
        'page_changed_games': sum(g['pages_changed'] for g in game_changes),
        'unchanged_games': sum(g['change']=='unchanged' for g in game_changes),
        'new_page_opportunities': [newpages[k].model_dump(mode='json') for k in sorted(newpages.keys()-oldpages.keys())],
        'removed_page_opportunities': [oldpages[k].model_dump(mode='json') for k in sorted(oldpages.keys()-newpages.keys())],
        'removed_games': sorted(set(oldgames)-{g.game_slug for g in current.game_opportunities})}
