"""Explicit synthetic fixture. Never call this as a fallback for a failed live scan."""
from __future__ import annotations
from datetime import timedelta
from uuid import uuid4
from game_keyword_radar.models import GameCandidate, ScanSnapshot, SourceStatus, SourceState, PlatformSignal, EvidenceItem, utc_now, Confidence
from game_keyword_radar.analyzers.game_profile import enrich_game_profile
from game_keyword_radar.analyzers.scoring import score_game, build_opportunities
from game_keyword_radar.analyzers.entity_resolution import EntityResolver
from game_keyword_radar.pipeline import analyze, steam_signal
from game_keyword_radar.history_v2 import attach_history
from game_keyword_radar.storage import SnapshotStore

SPECS = [
    ('demo-001','Frontier Forge',38400,12800,['Survival','Open World','Crafting'],['Online Co-op','Steam Workshop'],
     ['How many materials for a Frontier Forge base?','Frontier Forge crafting calculator guide','Frontier Forge workshop download stuck','Where to find Frontier Forge boss locations?','Frontier Forge progress tracker'],['crafting','workshop','locations','tracker']),
    ('demo-002','Signal Tactics',9800,4300,['Strategy','Simulation','RPG'],['Single-player'],
     ['Signal Tactics best build guide','Signal Tactics damage calculator','Signal Tactics best characters tier list','How do I redeem Signal Tactics gift codes?'],['builds','calculator','tier-list','codes']),
    ('demo-003','The Glass Archive',1900,820,['Puzzle','Adventure','Mystery'],['Single-player'],
     ['The Glass Archive puzzle solutions','The Glass Archive walkthrough chapter 2','The Glass Archive beginner guide'],['walkthrough','guide']),
]

def build_demo_snapshot(settings):
    now=utc_now();resolver=EntityResolver()
    snapshot=ScanSnapshot(schema_version=2,run_id='demo-fixture',country=settings.country,language=settings.language,is_demo=True,
        raw_metadata={'dataset':'fixture','purpose':'dashboard onboarding','notice':'ALL figures, games and questions are synthetic, not live platform facts'})
    for index,(appid,name,players,reviews,genres,categories,titles,_) in enumerate(SPECS,1):
        game=GameCandidate(app_id=appid,name=name,steam_rank=index,discovery_sources=['fixture'],discovery_ranks={'fixture':index},
            release_date=now.date()-timedelta(days=index*7),current_players=players,reviews_total=reviews,genres=genres,categories=categories,
            short_description='SYNTHETIC FIXTURE: '+', '.join(genres),store_url='https://example.invalid/fixture',collected_at=now)
        enrich_game_profile(game);score_game(game,3)
        snapshot.games.append(game)
        entity=resolver.from_steam(game);entity.platform_ids['twitch']=f'demo-twitch-{index}'
        snapshot.entities.append(entity)
        steam=steam_signal(entity,game,settings);steam.origin='demo';steam.notes=['SYNTHETIC fixture observation']
        evidence=[EvidenceItem(id=f'fixture:{index}:{n}',source='reddit' if n%2==0 else 'youtube',title=title,
            url=f'https://example.invalid/fixture/{index}/{n}',author=f'fixture-author-{n}',
            published_at=now-timedelta(days=n+1),captured_at=now) for n,title in enumerate(titles)]
        signals=[steam,
            PlatformSignal(source='twitch',game_slug=entity.slug,market='GLOBAL',origin='demo',confidence=Confidence.MEDIUM,
                metrics={'total_viewers':18000//index,'live_channels':100//index,'top_stream_viewers':3000//index,
                    'audience_concentration':.167,'sampling_complete':True,'sampling_scope':'game_streams','sample_page_limit':3,'twitch_rank':index*4},notes=['SYNTHETIC fixture']),
            PlatformSignal(source='youtube',game_slug=entity.slug,market=settings.youtube_region,origin='demo',confidence=Confidence.MEDIUM,
                metrics={'recent_video_count':20//index,'recent_guide_video_count':12//index,'creator_count':8//index,
                    'top_video_views':220000//index,'median_views':15000//index,'view_velocity_proxy':500//index,'intent_video_share':.6,
                    'sample_only':True,'window_days':30,'queries':[name],'region_code':settings.youtube_region,'relevance_language':'en'},
                evidence=[e for e in evidence if e.source=='youtube'],notes=['SYNTHETIC fixture; counts are not current facts']),
            PlatformSignal(source='reddit',game_slug=entity.slug,market='GLOBAL',origin='demo',confidence=Confidence.MEDIUM,
                metrics={'question_count':len([e for e in evidence if e.source=='reddit']),'unique_authors':3,'comment_activity':None,'subreddits':['fixture'],'sample_only':True},
                evidence=[e for e in evidence if e.source=='reddit'],notes=['SYNTHETIC fixture']),
            PlatformSignal(source='trends',game_slug=entity.slug,market=settings.trends_geo,origin='demo',status=SourceState.SKIPPED,
                notes=['Optional Trends intentionally missing in this fixture: missing is not zero'])]
        snapshot.platform_signals.extend(signals)
    baseline=snapshot.model_copy(deep=True)
    for signal in baseline.platform_signals:
        signal.captured_at-=timedelta(hours=24)
        if signal.source=='steam':signal.metrics['current_players']=int(signal.metrics['current_players']*.65)
        if signal.source=='twitch':signal.metrics['total_viewers']=int(signal.metrics['total_viewers']*.5)
    attach_history(snapshot.platform_signals,[baseline],settings)
    analyze(snapshot,settings)
    # Retain legacy keyword/report consumers alongside the V2 Page Graph.
    for game,entity in zip(snapshot.games,snapshot.entities):
        keywords=[k for p in snapshot.page_opportunities if p.game_slug==entity.slug for k in p.keyword_candidates]
        snapshot.opportunities.extend(build_opportunities(game,keywords))
    snapshot.opportunities.sort(key=lambda p:(-p.score,p.id))
    snapshot.source_statuses=[SourceStatus(source=s,state=SourceState.SKIPPED if s=='trends' else SourceState.OK,
        message='SYNTHETIC FIXTURE — not live API verification',records=0 if s=='trends' else 3) for s in ('steam','twitch','youtube','reddit','trends')]
    return snapshot

def save_demo(settings):
    snapshot=build_v21_demo_snapshot(settings)
    store=SnapshotStore(settings)
    if store.load_snapshot(snapshot.run_id):snapshot.run_id='demo-fixture-'+uuid4().hex[:8]
    store.save_snapshot(snapshot)
    return snapshot


def build_v21_demo_snapshot(settings):
    """Five synthetic decision lanes, with time-consistent replay evidence."""
    from game_keyword_radar.models import GameEntity
    from game_keyword_radar.analyzers.candidate_selection import decide_candidate, allocate_deep
    from game_keyword_radar.analyzers.momentum import assess_momentum
    from game_keyword_radar.observations import stamp_observation
    now=utc_now()
    snapshot=build_demo_snapshot(settings)
    snapshot.generated_at=now
    snapshot.analysis_version='2.1'
    snapshot.selection_policy_version=settings.selection.policy_version
    snapshot.policy_config_hash=settings.policy_hash()
    # Existing fixtures become: recent release, established growth, unknown exploratory.
    for i,e in enumerate(snapshot.entities):
        e.first_seen_at=now-timedelta(days=2)
        e.release_stage='released' if i<2 else 'unknown'
        e.first_public_playable_at=(now-timedelta(days=12 if i==0 else 700)).date() if i<2 else None
        e.release_date_basis='verified_public' if i<2 else 'unknown'
        e.release_sources=['https://example.invalid/synthetic-release'] if i<2 else []
        if i==2: e.platform_release_dates={};e.release_date=None
    for name,slug in [('Evergreen Arena','evergreen-arena'),('Copper Workshop','copper-workshop')]:
        e=GameEntity(canonical_name=name,slug=slug,release_stage='released',
            first_public_playable_at=(now-timedelta(days=2000)).date(),release_date_basis='verified_public',
            release_sources=['https://example.invalid/synthetic-release'],first_seen_at=now,
            discovery_sources=['fixture'],platform_ids={'steam':'fixture-'+slug},is_game=True)
        snapshot.entities.append(e)
        for source in ('steam','twitch','youtube','reddit','trends'):
            metrics=({'current_players':700000,'country':settings.country} if source=='steam' else
                     {'total_viewers':60000,'live_channels':200,'audience_concentration':.1,
                      'sampling_complete':True,'sampling_scope':'game_streams','sample_page_limit':3} if source=='twitch' else {})
            snapshot.platform_signals.append(PlatformSignal(source=source,game_slug=slug,origin='demo',
                captured_at=now,market='GLOBAL',metrics=metrics,status=SourceState.OK if metrics else SourceState.SKIPPED,
                notes=['SYNTHETIC fixture, not live data']))
    copper=next(s for s in snapshot.platform_signals if s.game_slug=='copper-workshop' and s.source=='reddit')
    copper.status=SourceState.OK
    copper.metrics={'question_count':1,'unique_authors':1,'sample_only':True}
    copper.evidence=[EvidenceItem(id='fixture-copper-question',source='reddit',title='Copper Workshop SteamCMD download stuck after update',
        published_at=now-timedelta(days=1),captured_at=now-timedelta(minutes=1),url='https://example.invalid/synthetic-question')]
    prior=[]
    for signal in snapshot.platform_signals:
        signal.captured_at=now
        signal.history={}
        signal.scope_version='2.1'
        if signal.source in {'steam','twitch'}:
            signal.market='GLOBAL'
        if signal.source=='twitch' and signal.metrics:
            signal.metrics['top1_viewer_share']=signal.metrics.get('audience_concentration',.1)
            signal.metrics['non_top1_viewers']=signal.metrics.get('total_viewers',0)*(1-signal.metrics['top1_viewer_share'])
        signal.observation_id=None
        stamp_observation(signal)
        if signal.source not in {'steam','twitch'} or signal.game_slug=='the-glass-archive':continue
        for hours in (2,4,24,26,28):
            old=signal.model_copy(deep=True)
            old.captured_at=now-timedelta(hours=hours)
            old.observation_id=None
            if signal.game_slug=='signal-tactics' and hours>=24:
                for metric in ('current_players','total_viewers','live_channels','non_top1_viewers'):
                    if metric in old.metrics:old.metrics[metric]=old.metrics[metric]/3
            stamp_observation(old)
            prior.append(old)
    decisions=[]
    for e in snapshot.entities:
        signals=[s for s in snapshot.platform_signals if s.game_slug==e.slug]
        m=assess_momentum(e.slug,signals,prior,settings,now)
        # Only Copper's prior issue is an admission trigger in this synthetic fixture.
        evidence=copper.evidence if e.slug=='copper-workshop' else []
        d=decide_candidate(e,signals,m,settings,now,evidence=evidence)
        d.selected_for_monitoring=True
        decisions.append(d)
    summary=allocate_deep(decisions,snapshot.entities,settings,now,10)
    snapshot.selection_decisions=decisions
    snapshot.selection_summary={**summary,'raw_discovery_rows':9,'unique_entities':5,'metadata_entities':5,'monitored_entities':5}
    snapshot.before_deep_selection={'as_of':now.isoformat(),'summary':dict(snapshot.selection_summary),
        'decisions':[d.model_dump(mode='json') for d in decisions]}
    snapshot.raw_metadata.update({'dataset':'fixture','deep_game_slugs':[d.game_slug for d in decisions if d.selected_for_deep],
        'demo_history_observations':[s.model_dump(mode='json') for s in prior], 'policy':settings.public_policy()})
    analyze(snapshot,settings)
    snapshot.selection_summary.update(validation_candidates=sum(g.action!='WATCH' and g.selection.selected_for_deep for g in snapshot.game_opportunities),
        question_pages=sum(p.evidence_level=='observed_question' for p in snapshot.page_opportunities),
        content_proxy_pages=sum(p.evidence_level=='observed_content_proxy' for p in snapshot.page_opportunities),
        hypothesis_pages=sum(p.evidence_level=='hypothesis' for p in snapshot.page_opportunities))
    snapshot.after_deep_assessment={'as_of':now.isoformat(),'games':[g.model_dump(mode='json') for g in snapshot.game_opportunities]}
    snapshot.source_statuses=[SourceStatus(source=source,state=SourceState.PARTIAL if source!='trends' else SourceState.SKIPPED,
        message='ALL observations synthetic; not live verification',records=sum(s.source==source and bool(s.metrics) for s in snapshot.platform_signals)) for source in ('steam','twitch','youtube','reddit','trends')]
    return snapshot
