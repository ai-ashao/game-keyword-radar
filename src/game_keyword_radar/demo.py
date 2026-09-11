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
    snapshot=build_demo_snapshot(settings)
    store=SnapshotStore(settings)
    if store.load_snapshot(snapshot.run_id):snapshot.run_id='demo-fixture-'+uuid4().hex[:8]
    store.save_snapshot(snapshot)
    return snapshot
