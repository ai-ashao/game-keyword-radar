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
        clusters=mine_questions(entity,signals)
        for s in signals:
            if s.source=='reddit' and s.status in {SourceState.OK,SourceState.PARTIAL}:
                s.metrics['repeated_question_clusters']=sum(sum(e.source=='reddit' for e in c.examples)>=2 for c in clusters)
        demand=score_demand(signals)
        pages=build_page_graph(entity,clusters,demand,settings)
        snapshot.question_clusters.extend(clusters)
        snapshot.page_opportunities.extend(pages)
        snapshot.game_opportunities.append(route_game(entity,demand,pages))
    snapshot.game_opportunities.sort(key=lambda g:(-g.research_priority,g.game_slug))
    for rank,item in enumerate(snapshot.game_opportunities,1):item.rank=rank
    return snapshot

class Scanner:
    def __init__(self,settings:Settings,providers:dict|None=None,progress=None):
        self.settings=settings;self.store=SnapshotStore(settings);self.providers=providers or {};self.progress=progress
    def notify(self,phase,message):
        if self.progress:self.progress(phase,message)
    async def run(self,*,limit=None,with_trends=None,deep=None,discovery_limit=None):
        if limit is not None and not 1<=limit<=30:raise ValueError('legacy limit must be between 1 and 30; use discovery_limit for broad scans')
        count=discovery_limit if discovery_limit is not None else limit if limit is not None else self.settings.discovery_limit
        n=deep if deep is not None else self.settings.deep_analysis_limit
        if not 1<=count<=100:raise ValueError('discovery_limit must be between 1 and 100')
        if not 0<=n<=30:raise ValueError('deep must be between 0 and 30')
        with self.store.scan_lock():
            return await self._run(count,n,with_trends)
    async def _run(self,count,deep,with_trends):
        settings=self.settings
        enabled={s:getattr(settings,f'{s}_enabled') for s in SOURCES}
        if with_trends is not None:enabled['trends']=with_trends
        providers={
            'steam':self.providers.get('steam') or SteamProvider(settings),
            'twitch':self.providers.get('twitch') or TwitchProvider(settings),
            'youtube':self.providers.get('youtube') or YouTubeProvider(settings),
            'reddit':self.providers.get('reddit') or RedditProvider(settings),
            'trends':self.providers.get('trends') or (OfficialTrendsProvider(settings) if settings.trends_provider=='official' else LegacyTrendsProvider(settings)),
        }
        run_id=utc_now().strftime('%Y-%m-%dT%H-%M-%SZ')+'-'+uuid4().hex[:8]
        snapshot=ScanSnapshot(schema_version=2,run_id=run_id,country=settings.country,language=settings.language,
            raw_metadata={'discovery_limit':count,'deep_analysis_limit':deep,'trends_enabled':enabled['trends'],
                'markets':{'steam':settings.country,'youtube':settings.youtube_region,'trends':settings.trends_geo,'twitch':'GLOBAL','reddit':'GLOBAL'}})
        resolver=EntityResolver(self.store.load_entities(),settings.entity_overrides)
        selected={};signal_map={};failures={};discovery_statuses=[]
        try:
            self.notify('discovery','发现 Steam / Twitch 候选游戏')
            if enabled['steam']:
                try:
                    collection=await providers['steam'].collect(count)
                    snapshot.games=[enrich_game_profile(g) for g in collection.games]
                    snapshot.errors.extend(collection.errors)
                    if not collection.games and collection.errors:failures["steam"]="; ".join(collection.errors)
                    discovery_statuses.extend(collection.statuses)
                    self.store.save_raw('steam',collection.raw)
                    snapshot.raw_metadata['steam_raw_saved']=True
                    for game in snapshot.games:
                        entity=resolver.from_steam(game);selected[entity.slug]=entity
                        signal_map[(entity.slug,'steam')]=steam_signal(entity,game,settings)
                except Exception as exc:
                    failures['steam']=safe_error(exc);snapshot.errors.append('steam: '+safe_error(exc))
            if enabled['twitch']:
                try:
                    games,samples=await providers['twitch'].discover(count)
                    lookup={s['game_id']:s for s in samples}
                    for game in games:
                        entity=resolver.resolve(game['name'],'twitch',game['id']);selected[entity.slug]=entity
                        if game.get('igdb_id'):entity.platform_ids.setdefault('igdb',str(game['igdb_id']))
                        sample=lookup.get(game['id'])
                        if sample:
                            signal_map[(entity.slug,'twitch')]=PlatformSignal(source='twitch',game_slug=entity.slug,market='GLOBAL',
                                captured_at=sample['captured_at'],status=SourceState.PARTIAL,metrics=sample['metrics'],
                                cache_hit=sample.get('cache_hit',False),notes=['Broad discovery uses a bounded top-stream sample; not full game totals.'])
                except Exception as exc:
                    failures['twitch']=safe_error(exc);snapshot.errors.append('twitch: '+safe_error(exc))
            # Union candidates before truncation so Twitch-only games are not discarded.
            preliminary=[]
            for entity in selected.values():
                signals=[v for (slug,_),v in signal_map.items() if slug==entity.slug]
                d=score_demand(signals)
                preliminary.append((d.score or 0,entity))
            preliminary.sort(key=lambda x:(-x[0],x[1].slug))
            snapshot.entities=[e for _,e in preliminary[:count]]
            selected_steam_ids={e.platform_ids.get("steam") for e in snapshot.entities}
            snapshot.games=[g for g in snapshot.games if g.app_id in selected_steam_ids]
            for game in snapshot.games:score_game(game,len(snapshot.games))
            deep_entities=snapshot.entities[:deep]
            snapshot.raw_metadata['deep_game_slugs']=[e.slug for e in deep_entities]
            deep_slugs=set(snapshot.raw_metadata['deep_game_slugs'])
            # Keep non-Steam games; every entity always has five explicit source states.
            for entity in snapshot.entities:
                for source in SOURCES:
                    market=settings.country if source=='steam' else settings.youtube_region if source=='youtube' else settings.trends_geo if source=='trends' else 'GLOBAL'
                    key=(entity.slug,source)
                    if key in signal_map:continue
                    note='Disabled in configuration' if not enabled[source] else 'Outside bounded deep-analysis selection' if entity.slug not in deep_slugs and source!='steam' else 'No linked Steam record' if source=='steam' else 'Not collected'
                    state=SourceState.SKIPPED if not enabled[source] or entity.slug not in deep_slugs else SourceState.UNAVAILABLE
                    signal_map[key]=missing(source,entity,market,state,note)
            for index,entity in enumerate(deep_entities,1):
                self.notify('enrichment',f'深度验证 {index}/{len(deep_entities)}：{entity.canonical_name}')
                for source in ('twitch','youtube','reddit','trends'):
                    if not enabled[source]:continue
                    try:
                        signal=await providers[source].fetch(entity)
                        prior=signal_map.get((entity.slug,source))
                        if source=='twitch' and prior and signal.metrics and signal.metrics.get('twitch_rank') is None:
                            signal.metrics['twitch_rank']=prior.metrics.get('twitch_rank')
                        signal_map[(entity.slug,source)]=signal
                    except Exception as exc:
                        # Keep a valid broad sample if deep fetching failed, with explicit failure notes.
                        old=signal_map.get((entity.slug,source))
                        if old and old.status in {SourceState.OK,SourceState.PARTIAL} and old.metrics:
                            old.status=SourceState.PARTIAL;old.notes.append('Deep enrichment failed: '+safe_error(exc))
                        else:
                            market=settings.youtube_region if source=='youtube' else settings.trends_geo if source=='trends' else 'GLOBAL'
                            signal_map[(entity.slug,source)]=missing(source,entity,market,
                                SourceState.BUDGET_EXHAUSTED if isinstance(exc,BudgetExceeded) else SourceState.FAILED,safe_error(exc))
            snapshot.platform_signals=[signal_map[(e.slug,s)] for e in snapshot.entities for s in SOURCES]
            self.notify('analysis','比较历史、聚合玩家问题、生成页面机会')
            history=[]
            for summary in self.store.list_snapshots()[:250]:
                if (summary.country,summary.language,summary.is_demo)!=(snapshot.country,snapshot.language,snapshot.is_demo):continue
                old=self.store.load_snapshot(summary.run_id)
                if old:history.append(old)
            attach_history(snapshot.platform_signals,history,settings)
            analyze(snapshot,settings)
            for game in snapshot.games:
                entity=next(e for e in snapshot.entities if e.platform_ids.get("steam")==game.app_id)
                keywords=[k for p in snapshot.page_opportunities if p.game_slug==entity.slug for k in p.keyword_candidates]
                snapshot.opportunities.extend(build_opportunities(game,keywords))
            snapshot.opportunities.sort(key=lambda p:(-p.score,p.id))
            for source in SOURCES:
                signals=[s for s in snapshot.platform_signals if s.source==source]
                good=[s for s in signals if s.status in {SourceState.OK,SourceState.PARTIAL} and s.metrics]
                if not enabled[source]:state=SourceState.SKIPPED;note='Disabled'
                elif good:state=SourceState.OK if all(s.status==SourceState.OK for s in signals) else SourceState.PARTIAL;note=f'{len(good)}/{len(signals)} entities have usable observations'
                elif source in failures:state=SourceState.FAILED;note=failures[source]
                else:
                    readiness=next(x for x in configured_sources(settings) if x['source']==source)
                    observed_states={s.status for s in signals}
                    priority=(SourceState.FAILED,SourceState.BUDGET_EXHAUSTED,SourceState.UNAVAILABLE,SourceState.INSUFFICIENT_DATA,SourceState.SKIPPED)
                    state=next((candidate for candidate in priority if candidate in observed_states),SourceState.UNAVAILABLE if not readiness['configured'] else SourceState.INSUFFICIENT_DATA)
                    notes=list(dict.fromkeys(n for signal in signals for n in signal.notes))
                    note='; '.join(notes[:3]) or ('Credentials or optional dependency missing' if not readiness['configured'] else 'No usable observations')
                snapshot.source_statuses.append(SourceStatus(source=source,state=state,message=note,records=len(good),official_api=source in {'twitch','youtube'}))
            snapshot.source_statuses.extend(discovery_statuses)
            snapshot.raw_metadata['entity_match_suggestions']=resolver.suggestions
            for source,provider in providers.items():
                raw=getattr(provider,'raw',None)
                if raw:self.store.save_raw(source,{'source':source,'run_id':run_id,'captured_at':utc_now().isoformat(),
                    'status':next((s.state.value for s in snapshot.source_statuses if s.source==source),'unknown'),
                    'market':snapshot.raw_metadata['markets'].get(source),'responses':raw})
            if snapshot.entities:self.store.save_entities(resolver.entities)
            self.store.save_snapshot(snapshot)
            from game_keyword_radar.reporters.markdown import MarkdownReporter
            MarkdownReporter(settings).save(snapshot)
            self.notify('complete',f'完成：{len(snapshot.entities)} 个游戏，{len(snapshot.page_opportunities)} 个页面假设')
            return snapshot
        finally:
            for provider in providers.values():
                close=getattr(provider,'close',None)
                if close:await close()
