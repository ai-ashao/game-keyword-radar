from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from game_keyword_radar.analyzers.entity_resolution import EntityResolver
from game_keyword_radar.analyzers.game_profile import enrich_game_profile
from game_keyword_radar.analyzers.scoring import score_game, build_opportunities
from game_keyword_radar.analyzers.demand_momentum import score_demand
from game_keyword_radar.analyzers.question_mining import mine_questions
from game_keyword_radar.analyzers.page_graph import build_page_graph, route_game
from game_keyword_radar.config import Settings
from game_keyword_radar.models import ScanSnapshot, PlatformSignal, SourceState, SourceStatus, Confidence, utc_now, EvidenceItem
from game_keyword_radar.sources.steam import SteamProvider
from game_keyword_radar.sources.twitch import TwitchProvider
from game_keyword_radar.sources.youtube import YouTubeProvider
from game_keyword_radar.sources.reddit import RedditProvider
from game_keyword_radar.sources.trends import LegacyTrendsProvider, OfficialTrendsProvider
from game_keyword_radar.sources.base import missing, safe_error, BudgetExceeded
from game_keyword_radar.storage import SnapshotStore
from game_keyword_radar.history_v2 import attach_history

SOURCES = ('steam','twitch','trends','youtube','reddit')

def configured_sources(settings):
    result=[]
    for source in SOURCES:
        enabled=getattr(settings,f'{source}_enabled')
        configured = bool(settings.twitch_client_id and settings.twitch_client_secret) if source=='twitch' else bool(settings.youtube_api_key) if source=='youtube' else (LegacyTrendsProvider.available() and settings.trends_provider=='legacy') if source=='trends' else True
        result.append({'source':source,'enabled':enabled,'configured':configured,
            'status':'skipped' if not enabled else 'unavailable' if not configured else 'ready_not_tested',
            'message':'配置就绪不等于接口实测成功；扫描后查看真实状态。'})
    return result

def steam_signal(entity, game, settings):
    errors=[e for e in game.evidence if e.source=='collector_error']
    metrics={'current_players':game.current_players,'reviews_total':game.reviews_total,'steam_rank':game.steam_rank,
        'release_age_days':(utc_now().date()-game.release_date).days if game.release_date else None,
        'country':settings.country,'discovery_ranks':game.discovery_ranks}
    return PlatformSignal(source='steam',game_slug=entity.slug,market=settings.country,captured_at=game.collected_at,
        status=SourceState.PARTIAL if errors else SourceState.OK,metrics=metrics,confidence=Confidence.MEDIUM,
        evidence=[EvidenceItem(id=f'steam:{game.app_id}',source='steam',title=game.name,url=game.store_url,
            captured_at=game.collected_at,text=game.short_description or '',metrics=metrics)],
        notes=['Current players are an instantaneous observation, not average concurrency.',
               'Store recommendations.total is retained as a review-scale proxy, not verified total review count.']+[str(e.value) for e in errors])

def analyze(snapshot, settings):
    snapshot.question_clusters=[];snapshot.page_opportunities=[];snapshot.game_opportunities=[]
    for entity in snapshot.entities:
        signals=[s for s in snapshot.platform_signals if s.game_slug==entity.slug]
        decision = next((d for d in snapshot.selection_decisions if d.game_slug == entity.slug), None)
        manual = snapshot.raw_metadata.get('manual_evidence', {}).get(entity.slug, [])
        extra = [PlatformSignal(source='manual', game_slug=entity.slug, evidence=[EvidenceItem.model_validate(e) for e in manual])] if manual else []
        clusters=mine_questions(entity,signals + extra)
        for s in signals:
            if s.source=='reddit' and s.status in {SourceState.OK,SourceState.PARTIAL}:
                s.metrics['repeated_question_clusters']=sum(sum(e.source=='reddit' for e in c.examples)>=2 for c in clusters)
        demand=score_demand(signals)
        pages=build_page_graph(entity,clusters,demand,settings, decision=decision)
        snapshot.question_clusters.extend(clusters)
        snapshot.page_opportunities.extend(pages)
        snapshot.game_opportunities.append(route_game(entity,demand,pages, decision=decision))
    if snapshot.analysis_version == '2.1':
        snapshot.game_opportunities.sort(key=lambda g:(not (g.selection and g.selection.selected_for_deep),
            g.selection.selection_order if g.selection and g.selection.selection_order is not None else 99999, g.game_slug))
    else:
        snapshot.game_opportunities.sort(key=lambda g:(-g.research_priority,g.game_slug))
    for rank,item in enumerate(snapshot.game_opportunities,1):item.rank=rank
    return snapshot

# The 2.1 selection path deliberately never calls score_demand for eligibility.
from dataclasses import asdict
from datetime import timedelta
from game_keyword_radar.models import MonitoringSnapshot
from game_keyword_radar.observations import VALID, stamp_observation
from game_keyword_radar.annotations import apply_annotation, annotation_evidence
from game_keyword_radar.analyzers.candidate_selection import allocate_basic, decide_candidate, allocate_deep
from game_keyword_radar.analyzers.momentum import assess_momentum


class Scanner:
    def __init__(self, settings: Settings, providers: dict | None = None, progress=None, clock=None):
        self.settings = settings
        self.store = SnapshotStore(settings)
        self.providers = providers or {}
        self.progress = progress
        self.clock = clock or utc_now

    def notify(self, phase, message):
        if self.progress:
            self.progress(phase, message)

    def make_providers(self):
        s = self.settings
        classes = {'steam': SteamProvider, 'twitch': TwitchProvider, 'youtube': YouTubeProvider,
                   'reddit': RedditProvider, 'trends': OfficialTrendsProvider if s.trends_provider == 'official' else LegacyTrendsProvider}
        return {name: self.providers.get(name) or cls(s) for name, cls in classes.items()}

    async def run(self, *, limit=None, with_trends=None, deep=None, discovery_limit=None, selection_profile=None):
        if limit is not None and not 1 <= limit <= 30:
            raise ValueError('legacy limit must be between 1 and 30; use discovery_limit for broad scans')
        if selection_profile not in {None, 'opportunity'}:
            raise ValueError('Only opportunity selection is supported')
        count = discovery_limit if discovery_limit is not None else limit if limit is not None else self.settings.discovery_limit
        n = deep if deep is not None else self.settings.deep_analysis_limit
        if not 1 <= count <= 100 or not 0 <= n <= 30:
            raise ValueError('discovery_limit must be 1..100 and deep 0..30')
        with self.store.scan_lock():
            return await self._run(count, n, with_trends, monitoring=False)

    async def monitor_once(self):
        with self.store.scan_lock():
            return await self._run(self.settings.discovery_limit, 0, False, monitoring=True)

    async def _basic(self, snapshot, providers, enabled, count, monitoring):
        settings = self.settings
        annotations = self.store.load_annotations()
        resolver = EntityResolver(self.store.load_entities(), settings.entity_overrides, as_of=self.clock())
        for entity in resolver.entities:
            apply_annotation(entity, annotations.get(entity.slug), self.clock())
        selected, signal_map, failures, rows = {}, {}, {}, []
        raw_rows, discovery_statuses, metadata_count = [], [], 0
        history = self.store.history_records(as_of=self.clock(), country=settings.country, language=settings.language)
        previous = next((h for h in reversed(history) if isinstance(h, ScanSnapshot)), None)
        watched = {slug for slug, a in annotations.items() if a.watch or a.research_requested_at and (a.research_consumed_at is None or a.research_requested_at > a.research_consumed_at)}
        if previous:
            watched.update(d.game_slug for d in previous.selection_decisions if d.eligible_lanes and d.decision != 'excluded')
        if enabled['steam'] or enabled['twitch']:
            for entity in resolver.entities:
                if entity.slug in watched:
                    selected[entity.slug] = entity
        self.notify('discovery', '读取来源列表与本地观察项，保留新游入口')
        if enabled['steam']:
            try:
                if hasattr(providers['steam'], 'discover_rows'):
                    rows, statuses, errors = await providers['steam'].discover_rows(min(count, settings.discovery_budget.source_row_limit))
                    discovery_statuses.extend(statuses)
                    snapshot.errors.extend(errors)
                    if errors and not rows:
                        failures["steam"] = "; ".join(errors)
                    raw_rows.extend({'source':'steam', **asdict(row)} for row in rows)
                    for row in rows:
                        entity = resolver.resolve(row.name, 'steam', row.app_id)
                        entity.discovery_sources = list(dict.fromkeys(entity.discovery_sources + [row.source]))
                        entity.discovery_ranks[row.source] = row.rank
                        selected[entity.slug] = entity
                else:
                    # Adapter compatibility for existing integrations and deterministic test fixtures.
                    collection = await providers['steam'].collect(count)
                    snapshot.games = [enrich_game_profile(g) for g in collection.games]
                    snapshot.errors.extend(collection.errors)
                    discovery_statuses.extend(collection.statuses)
                    for game in snapshot.games:
                        entity = resolver.from_steam(game)
                        selected[entity.slug] = entity
                        signal_map[(entity.slug,'steam')] = steam_signal(entity, game, settings)
                    raw_rows.extend({'source':'steam', 'app_id':g.app_id, 'name':g.name} for g in collection.games)
                    self.store.save_raw('steam', collection.raw)
            except Exception as exc:
                failures['steam'] = safe_error(exc)
                snapshot.errors.append('steam: ' + safe_error(exc))
        if enabled['twitch']:
            try:
                discovery = getattr(providers['twitch'], 'discover_categories', None) or providers['twitch'].discover
                games, samples = await discovery(min(count, settings.discovery_budget.source_row_limit))
                sample_map = {x['game_id']: x for x in samples}
                for game in games:
                    entity = resolver.resolve(game['name'], 'twitch', game['id'])
                    if game.get('igdb_id'):
                        entity.platform_ids.setdefault('igdb', str(game['igdb_id']))
                    if game.get('is_non_game'):
                        entity.is_game = False
                    entity.discovery_sources = list(dict.fromkeys(entity.discovery_sources + ['twitch_categories']))
                    if game.get('twitch_rank'):
                        entity.discovery_ranks['twitch_categories'] = game['twitch_rank']
                    selected[entity.slug] = entity
                    sample = sample_map.get(game['id'])
                    if sample:
                        signal_map[(entity.slug,'twitch')] = PlatformSignal(source='twitch', game_slug=entity.slug, market='GLOBAL',
                            captured_at=sample['captured_at'], metrics=sample['metrics'], cache_hit=sample.get('cache_hit',False),
                            status=SourceState.PARTIAL, notes=['Legacy bounded discovery sample, not a full game total'])
                raw_rows.extend({'source':'twitch_categories', **g} for g in games)
            except Exception as exc:
                failures['twitch'] = safe_error(exc)
                snapshot.errors.append('twitch: ' + safe_error(exc))
        # No global heat truncation. The UI can inspect every discovered entity.
        snapshot.entities = sorted(selected.values(), key=lambda e:e.slug)
        for entity in snapshot.entities:
            apply_annotation(entity, annotations.get(entity.slug), self.clock())
        if enabled['steam'] and hasattr(providers['steam'], 'metadata'):
            steam_entities = [e for e in snapshot.entities if e.platform_ids.get('steam')]
            targets = allocate_basic(steam_entities, settings, self.clock(), settings.discovery_budget.metadata_requests_per_scan,
                                     tracked_slugs=watched, metadata=True)
            games, errors = await providers['steam'].metadata(targets, rows)
            metadata_count = len(targets)
            snapshot.errors.extend('steam metadata: ' + error for error in errors)
            snapshot.games = [enrich_game_profile(g) for g in games]
            for game in snapshot.games:
                resolver.from_steam(game)
            for entity in snapshot.entities:
                apply_annotation(entity, annotations.get(entity.slug), self.clock())
        active = allocate_basic(snapshot.entities, settings, self.clock(),
            min(count, settings.monitoring.active_entity_limit), tracked_slugs=watched)
        active_slugs = {e.slug for e in active}
        self.notify('observing', f'初筛前定向观测 {len(active)} 个实体；不按旧 Demand 排名')
        for index, entity in enumerate(active, 1):
            self.notify('observing', f'轻量观测 {index}/{len(active)}：{entity.canonical_name}')
            if enabled['steam'] and hasattr(providers['steam'], 'observe') and entity.platform_ids.get('steam'):
                signal_map[(entity.slug,'steam')] = await providers['steam'].observe(entity)
            if enabled['twitch']:
                try:
                    signal_map[(entity.slug,'twitch')] = await providers['twitch'].fetch(entity)
                except Exception as exc:
                    signal_map[(entity.slug,'twitch')] = missing('twitch',entity,'GLOBAL',
                        SourceState.BUDGET_EXHAUSTED if isinstance(exc,BudgetExceeded) else SourceState.FAILED,safe_error(exc))
            successful = [s for (slug,_),s in signal_map.items() if slug==entity.slug and s.status in VALID and s.metrics]
            if successful:
                entity.last_observed_at = max(s.captured_at for s in successful)
        # Preserve immutable historical deep evidence when not fetched, with its original time.
        for entity in snapshot.entities:
            for source in SOURCES:
                key = (entity.slug, source)
                if key in signal_map:
                    continue
                market = settings.youtube_region if source=='youtube' else settings.trends_geo if source=='trends' else 'GLOBAL'
                prior = next((s for h in reversed(history) for s in h.platform_signals if s.game_slug==entity.slug and s.source==source and s.status in VALID and s.metrics), None)
                if not monitoring and source in {'youtube','reddit','trends'} and enabled[source] and prior and self.clock()-prior.captured_at < timedelta(days=settings.selection.recent_demand_days):
                    copy = prior.model_copy(deep=True)
                    copy.cache_hit = True
                    copy.notes.append('历史深度观测复用；原采集时间不变，本轮尚未请求')
                    signal_map[key] = copy
                else:
                    note = 'Disabled in configuration' if not enabled[source] else 'Outside bounded monitoring selection' if entity.slug not in active_slugs and source in {'steam','twitch'} else 'Awaiting lane selection / no linked platform observation'
                    signal_map[key] = missing(source,entity,market,SourceState.SKIPPED if not enabled[source] or entity.slug not in active_slugs else SourceState.UNAVAILABLE,note)
        for game in snapshot.games:
            entity = next((e for e in snapshot.entities if e.platform_ids.get('steam') == game.app_id), None)
            signal = signal_map.get((entity.slug,'steam')) if entity else None
            if signal and signal.status in VALID and 'current_players' in signal.metrics:
                game.current_players = signal.metrics['current_players']
                game.collected_at = signal.captured_at
        for s in signal_map.values():
            stamp_observation(s)
        snapshot.raw_metadata.update({'raw_discovery_rows':raw_rows,'raw_discovery_count':len(raw_rows),
            'metadata_entities':metadata_count,'active_game_slugs':[e.slug for e in active],
            'entity_match_suggestions':resolver.suggestions,'source_failures':failures,
            'manual_evidence':{e.slug:[x.model_dump(mode='json') for x in annotation_evidence(annotations.get(e.slug), self.clock())] for e in snapshot.entities}})
        return resolver, annotations, history, signal_map, discovery_statuses

    async def _run(self, count, deep, with_trends, *, monitoring):
        settings = self.settings
        enabled = {source:getattr(settings,f'{source}_enabled') for source in SOURCES}
        if with_trends is not None:
            enabled['trends'] = with_trends
        if monitoring:
            for source in ('youtube','reddit','trends'): enabled[source] = False
        providers = self.make_providers()
        run_id = self.clock().strftime('%Y-%m-%dT%H-%M-%SZ') + '-' + uuid4().hex[:8]
        snapshot = ScanSnapshot(schema_version=2, analysis_version='2.1', run_id=run_id,
            generated_at=self.clock(), country=settings.country, language=settings.language,
            selection_policy_version=settings.selection.policy_version, policy_config_hash=settings.policy_hash(),
            raw_metadata={'discovery_limit':count,'deep_analysis_limit':deep,'trends_enabled':enabled['trends'],
                          'policy':settings.public_policy(),'run_mode':'monitoring' if monitoring else 'full'})
        if monitoring:
            old_state = self.store.monitoring_state()
            try:
                last = datetime.fromisoformat(old_state['last_completed_at'])
                elapsed = (self.clock()-last).total_seconds()/60
                missed = max(0, int(elapsed//settings.monitoring.interval_minutes)-1)
            except (KeyError, ValueError, TypeError):
                missed = 0
            snapshot.raw_metadata['missed_intervals'] = missed
            snapshot.raw_metadata['gap_note'] = '服务离线 / 休眠 / 执行延迟导致的采样缺口；未补造样本' if missed else ''
        try:
            resolver, annotations, history, signal_map, discovery_statuses = await self._basic(snapshot, providers, enabled, count, monitoring)
            as_of = self.clock()
            snapshot.generated_at = as_of
            prior_signals = [s for h in history for s in h.platform_signals]
            self.notify('selecting','先比较独立历史，再进行通道准入与预算分配')
            decisions = []
            for entity in snapshot.entities:
                signals = [signal_map[(entity.slug,source)] for source in SOURCES]
                momentum = assess_momentum(entity.slug, signals, prior_signals, settings, as_of)
                evidence = [e for h in history for s in h.platform_signals if s.game_slug==entity.slug for e in s.evidence]
                evidence += annotation_evidence(annotations.get(entity.slug), as_of)
                d = decide_candidate(entity,signals,momentum,settings,as_of,evidence=evidence,manual=annotations.get(entity.slug))
                d.selected_for_monitoring = entity.slug in snapshot.raw_metadata['active_game_slugs']
                decisions.append(d)
            summary = allocate_deep(decisions,snapshot.entities,settings,as_of,deep)
            summary.update(raw_discovery_rows=snapshot.raw_metadata['raw_discovery_count'],
                unique_entities=len(snapshot.entities), metadata_entities=snapshot.raw_metadata['metadata_entities'],
                monitored_entities=sum(d.selected_for_monitoring for d in decisions))
            snapshot.selection_decisions = decisions
            snapshot.selection_summary = summary
            snapshot.before_deep_selection = {'as_of':as_of.isoformat(),'summary':dict(summary),
                'decisions':[d.model_dump(mode='json') for d in decisions]}
            selected = sorted((d for d in decisions if d.selected_for_deep), key=lambda d:d.selection_order)
            snapshot.raw_metadata['deep_game_slugs'] = [d.game_slug for d in selected]
            for index, decision in enumerate(selected,1):
                entity = next(e for e in snapshot.entities if e.slug == decision.game_slug)
                self.notify('enrichment',f'问题研究 {index}/{len(selected)}：{entity.canonical_name}（{decision.primary_lane}）')
                good_deep = False
                for source in ('youtube','reddit','trends'):
                    if not enabled[source]: continue
                    try:
                        signal = await providers[source].fetch(entity)
                        signal_map[(entity.slug,source)] = stamp_observation(signal)
                        good_deep |= signal.status in VALID and bool(signal.metrics or signal.evidence)
                    except Exception as exc:
                        market=settings.youtube_region if source=='youtube' else settings.trends_geo if source=='trends' else 'GLOBAL'
                        signal_map[(entity.slug,source)] = missing(source,entity,market,
                            SourceState.BUDGET_EXHAUSTED if isinstance(exc,BudgetExceeded) else SourceState.FAILED,safe_error(exc))
                if good_deep:
                    entity.last_deep_analyzed_at = self.clock()
                    entity.last_deep_trigger_fingerprint = decision.trigger_fingerprint
                    manual = annotations.get(entity.slug)
                    if decision.entry_origin == 'manual' and manual:
                        manual.research_consumed_at = self.clock()
                        self.store.save_annotation(manual, locked=True)
            snapshot.platform_signals = [signal_map[(e.slug,s)] for e in snapshot.entities for s in SOURCES]
            # Legacy point-pair changes remain diagnostic only; selection above used new windows.
            attach_history(snapshot.platform_signals,history,settings)
            for source in SOURCES:
                signals = [s for s in snapshot.platform_signals if s.source == source]
                good = [s for s in signals if s.status in VALID and s.metrics]
                if not enabled[source]:
                    state, note = SourceState.SKIPPED, 'Disabled / lightweight mode'
                elif good:
                    state = SourceState.OK if all(s.status==SourceState.OK for s in signals) else SourceState.PARTIAL
                    note = f'{len(good)}/{len(signals)} entities have observations; inspect their times/scopes'
                elif source in snapshot.raw_metadata['source_failures']:
                    state, note = SourceState.FAILED, snapshot.raw_metadata['source_failures'][source]
                else:
                    priority = (SourceState.FAILED,SourceState.BUDGET_EXHAUSTED,SourceState.UNAVAILABLE,SourceState.INSUFFICIENT_DATA,SourceState.SKIPPED)
                    state = next((x for x in priority if any(s.status==x for s in signals)),SourceState.UNAVAILABLE)
                    note = '; '.join(dict.fromkeys(n for s in signals for n in s.notes))[:800] or 'No usable observations / configured is not connected'
                snapshot.source_statuses.append(SourceStatus(source=source,state=state,message=note,records=len(good),official_api=source in {'twitch','youtube'}))
            snapshot.source_statuses.extend(discovery_statuses)
            snapshot.raw_metadata['request_attempts'] = {name:{'attempts':getattr(p,'calls',0),'cache_hits':getattr(p,'cache_hits',0)} for name,p in providers.items()}
            for source, provider in providers.items():
                raw = getattr(provider,'raw_responses',None) or getattr(provider,'raw',None)
                if raw:
                    self.store.save_raw(source, {'run_id':run_id,'source':source,'responses':raw})
            if snapshot.entities:
                self.store.save_entities(resolver.entities)
            if monitoring:
                result = MonitoringSnapshot(run_id=run_id,generated_at=self.clock(),country=settings.country,language=settings.language,
                    entity_slugs=[e.slug for e in snapshot.entities],platform_signals=[s for s in snapshot.platform_signals if s.source in {'steam','twitch'}],
                    source_statuses=snapshot.source_statuses,errors=snapshot.errors,raw_metadata=snapshot.raw_metadata)
                self.store.save_monitoring(result)
                state=self.store.monitoring_state()
                state.update(last_completed_at=result.generated_at.isoformat(),last_run_id=run_id,
                             active_game_slugs=snapshot.raw_metadata['active_game_slugs'], missed_intervals=snapshot.raw_metadata.get('missed_intervals',0), gap_note=snapshot.raw_metadata.get('gap_note',''))
                self.store.save_monitoring_state(state)
                self.notify('complete',f'轻量监测完成：{summary["monitored_entities"]} 个实体；完整报告保持不变')
                return result
            analyze(snapshot,settings)
            for game in snapshot.games:
                entity=next((e for e in snapshot.entities if e.platform_ids.get('steam')==game.app_id),None)
                if entity is None: continue
                score_game(game,max(1,len(snapshot.games)))
                keywords=[k for p in snapshot.page_opportunities if p.game_slug==entity.slug for k in p.keyword_candidates]
                snapshot.opportunities.extend(build_opportunities(game,keywords))
            snapshot.selection_summary.update(
                validation_candidates=sum(g.action in {'VALIDATE','EXPAND_EXISTING_SITE','VALIDATE_NEW_SITE'} and g.selection.selected_for_deep for g in snapshot.game_opportunities),
                question_pages=sum(p.evidence_level=='observed_question' for p in snapshot.page_opportunities),
                content_proxy_pages=sum(p.evidence_level=='observed_content_proxy' for p in snapshot.page_opportunities),
                hypothesis_pages=sum(p.evidence_level=='hypothesis' for p in snapshot.page_opportunities))
            snapshot.after_deep_assessment = {'as_of':self.clock().isoformat(), 'games':[g.model_dump(mode='json') for g in snapshot.game_opportunities]}
            self.store.save_snapshot(snapshot)
            from game_keyword_radar.reporters.markdown import MarkdownReporter
            MarkdownReporter(settings).save(snapshot)
            self.notify('complete',f'完成：{len(snapshot.entities)} 个实体，入选 {len(selected)}，可人工验证 {snapshot.selection_summary["validation_candidates"]}；不以热榜填满')
            return snapshot
        finally:
            for provider in providers.values():
                close=getattr(provider,'close',None)
                if close:
                    try: await close()
                    except Exception: pass
