from __future__ import annotations
import json
from datetime import timedelta
from pathlib import Path
import pytest
from pydantic import ValidationError
from game_keyword_radar.models import *
from game_keyword_radar.config import Settings
from game_keyword_radar.analyzers.entity_resolution import EntityResolver, normalized
from game_keyword_radar.analyzers.demand_momentum import score_demand
from game_keyword_radar.analyzers.question_mining import mine_questions
from game_keyword_radar.analyzers.page_graph import build_page_graph,route_game
from game_keyword_radar.history_v2 import attach_history,compare_v2
from game_keyword_radar.demo import build_demo_snapshot,save_demo
from game_keyword_radar.storage import SnapshotStore
from game_keyword_radar.validation import ValidationStore

@pytest.fixture
def settings(tmp_path):return Settings(project_root=tmp_path)
@pytest.fixture
def entity():return GameEntity(canonical_name='Example Game',slug='example-game')
def sig(entity,source='steam',value=100,**kw):
    metrics={'current_players':value,'country':'US'} if source=='steam' else {'total_viewers':value,'live_channels':10,'sampling_scope':'game_streams','sampling_complete':True,'sample_page_limit':3}
    return PlatformSignal(source=source,game_slug=entity.slug,metrics=metrics,**kw)
def cluster(entity,title,source='reddit',count=1):
    signals=[PlatformSignal(source=source,game_slug=entity.slug,evidence=[EvidenceItem(id=f'{source}:{i}',source=source,title=title,author=f'a{i}') for i in range(count)])]
    return mine_questions(entity,signals)

@pytest.mark.parametrize('name',['EXAMPLE GAME','Example-Game','Example™ Game'])
def test_entity_normalized_match(name):
    r=EntityResolver();a=r.resolve('Example Game','steam','1');b=r.resolve(name,'twitch','2')
    assert a is b and len(r.entities)==1

def test_entity_exact_platform_id_precedes_name():
    r=EntityResolver();a=r.resolve('Old Name','steam','1');b=r.resolve('New Name','steam','1')
    assert a is b and 'New Name' in a.aliases

def test_entity_alias():
    r=EntityResolver(overrides=[{'canonical_name':'Example Game','aliases':['EG'],'platform_ids':{'steam':'1'}}])
    e=r.resolve('EG','twitch','2');assert e.slug=='example-game' and e.match_method=='alias'

def test_fuzzy_not_merged():
    r=EntityResolver();a=r.resolve('Example Game','steam','1');b=r.resolve('Example Game II','twitch','2')
    assert a is not b and len(r.entities)==2 and r.suggestions and not r.suggestions[0]['applied']

def test_conflicting_same_platform_id_never_overwrites():
    r=EntityResolver();a=r.resolve('Example Game','steam','1');b=r.resolve('Example Game','steam','2')
    assert a.slug!=b.slug and a.platform_ids['steam']=='1'

def test_missing_not_zero(entity):
    empty=score_demand([PlatformSignal(source='steam',game_slug=entity.slug,status=SourceState.UNAVAILABLE)])
    zero=score_demand([sig(entity,value=0)])
    assert empty.score is None and empty.components['steam'] is None
    assert zero.score==0 and zero.components['steam']==0

def test_missing_extra_sources_do_not_reduce_observed_score(entity):
    one=score_demand([sig(entity)])
    two=score_demand([sig(entity),PlatformSignal(source='twitch',game_slug=entity.slug,status=SourceState.UNAVAILABLE)])
    assert one.score==two.score and one.coverage==two.coverage

def test_no_history_no_rising_invention(entity):
    score=score_demand([sig(entity),sig(entity,'twitch')])
    assert score.rising_sources==[] and score.components['cross_platform'] is None

def test_single_stream_concentration_penalized(entity):
    broad=sig(entity,'twitch',10000);broad.metrics['audience_concentration']=.1
    narrow=broad.model_copy(deep=True);narrow.metrics['audience_concentration']=.95
    assert score_demand([narrow]).score<score_demand([broad]).score

def test_ambiguous_title_does_not_add_every_template(entity,settings):
    demand=score_demand([])
    pages=build_page_graph(entity,cluster(entity,'Example Game screenshot'),demand,settings)
    assert pages==[]

@pytest.mark.parametrize('title',['Example Game source code','Example Game error code 404','Example Game best settings'])
def test_no_unrelated_codes_tier_or_map(title,entity,settings):
    pages=build_page_graph(entity,cluster(entity,title),score_demand([]),settings)
    assert all(p.path not in {'/codes','/tier-list','/boss-locations','/item-locations'} for p in pages)

def test_actual_code_evidence_triggers_page(entity,settings):
    pages=build_page_graph(entity,cluster(entity,'How do I redeem Example Game gift codes?'),score_demand([]),settings)
    assert any(p.path=='/codes' and p.trigger_signals for p in pages)

def test_mechanic_hypothesis_explicit(entity,settings):
    entity.mechanics=['crafting']
    pages=build_page_graph(entity,[],score_demand([]),settings)
    assert len(pages)==1 and pages[0].evidence_level=='hypothesis'
    assert all(e.is_inference for e in pages[0].trigger_signals)

def test_existing_site_route_priority(entity,settings):
    pages=build_page_graph(entity,cluster(entity,'Example Game Steam Workshop download stuck'),score_demand([sig(entity)]),settings)
    assert pages[0].existing_site_fit=='WorkshopFetch'
    assert route_game(entity,score_demand([sig(entity)]),pages).action=='EXPAND_EXISTING_SITE'
    assert pages[0].validation_status=='needs_validation'

def test_all_scores_capped(settings):
    d=build_demo_snapshot(settings)
    assert all(0<=p.score<=69 and p.trigger_signals for p in d.page_opportunities)
    assert all(g.action!='BUILD' for g in d.game_opportunities)

def test_dedup_questions_by_source_id(entity):
    e=EvidenceItem(id='post:1',source='reddit',title='Example Game crafting calculator')
    signals=[PlatformSignal(source='reddit',game_slug=entity.slug,evidence=[e,e])]
    c=mine_questions(entity,signals)
    assert c[0].question_count==1

def test_youtube_proxy_not_claimed_question(entity,settings):
    pages=build_page_graph(entity,cluster(entity,'Example Game crafting calculator guide',source='youtube'),score_demand([]),settings)
    assert pages[0].evidence_level=='observed_content_proxy'

def test_history_uses_near_24h_not_previous_scan(entity,settings):
    current=sig(entity,value=200)
    too_recent=sig(entity,value=50,captured_at=current.captured_at-timedelta(hours=1))
    old=sig(entity,value=100,captured_at=current.captured_at-timedelta(hours=24))
    snapshot=lambda s:ScanSnapshot(run_id='history',country='US',language='english',platform_signals=[s])
    attach_history([current],[snapshot(too_recent)],settings)
    assert '24h' not in current.history and current.history['previous']['elapsed_hours']==1
    attach_history([current],[snapshot(too_recent),snapshot(old)],settings)
    assert current.history['24h']['primary_percent']==100

def test_history_seven_day_window(entity,settings):
    now=sig(entity,value=200);old=sig(entity,value=100,captured_at=now.captured_at-timedelta(days=7))
    snap=ScanSnapshot(run_id='old',country='US',language='english',platform_signals=[old])
    attach_history([now],[snap],settings)
    assert now.history['7d']['primary_percent']==100 and '24h' not in now.history

def test_cache_same_timestamp_no_change(entity,settings):
    now=sig(entity);old=now.model_copy(deep=True);now.cache_hit=True
    attach_history([now],[ScanSnapshot(run_id='a',country='US',language='english',platform_signals=[old])],settings)
    assert now.history=={}

@pytest.mark.parametrize('field,value',[('market','GB'),('origin','demo')])
def test_incompatible_history_ignored(field,value,entity,settings):
    current=sig(entity);old=sig(entity,captured_at=current.captured_at-timedelta(hours=24));setattr(old,field,value)
    attach_history([current],[ScanSnapshot(run_id='a',country='US',language='english',platform_signals=[old])],settings)
    assert current.history=={}

def test_changed_sample_limit_not_comparable(entity,settings):
    current=sig(entity,'twitch');old=sig(entity,'twitch',captured_at=current.captured_at-timedelta(hours=24));old.metrics['sample_page_limit']=1
    attach_history([current],[ScanSnapshot(run_id='a',country='US',language='english',platform_signals=[old])],settings)
    assert not current.history

def test_zero_history_baseline_no_infinite_growth(entity,settings):
    current=sig(entity,value=100);old=sig(entity,value=0,captured_at=current.captured_at-timedelta(hours=24))
    attach_history([current],[ScanSnapshot(run_id='a',country='US',language='english',platform_signals=[old])],settings)
    assert current.history['24h']['primary_percent'] is None

def test_failed_attempt_keeps_latest(settings):
    store=SnapshotStore(settings);good=build_demo_snapshot(settings);good.is_demo=False
    store.save_snapshot(good)
    empty=ScanSnapshot(schema_version=2,run_id='failed',country='US',language='english',errors=['failure'])
    store.save_snapshot(empty)
    assert store.load_latest().run_id==good.run_id and store.load_snapshot('failed')

def test_demo_cannot_overwrite_live(settings):
    store=SnapshotStore(settings);live=build_demo_snapshot(settings);live.is_demo=False;live.run_id='live-test';store.save_snapshot(live)
    demo=save_demo(settings)
    assert store.load_latest().run_id=='live-test' and demo.is_demo

def test_snapshot_immutable(settings):
    store=SnapshotStore(settings);s=build_demo_snapshot(settings);store.save_snapshot(s)
    s.games[0].current_players+=1
    with pytest.raises(ValueError):store.save_snapshot(s)

def test_v1_load_readonly(settings):
    store=SnapshotStore(settings);s=build_demo_snapshot(settings).model_dump(mode='json');s['schema_version']='1.0'
    for key in ('entities','platform_signals','page_opportunities','question_clusters','game_opportunities'):s.pop(key)
    s['opportunities'][0].pop('raw_score')
    path=settings.data_dir/'processed'/'legacy-snapshot.json';path.parent.mkdir(parents=True)
    s['run_id']='legacy';path.write_text(json.dumps(s));before=path.read_bytes()
    loaded=store.load_snapshot('legacy')
    assert loaded and loaded.entities==[] and path.read_bytes()==before
    assert loaded.opportunities[0].raw_score==loaded.opportunities[0].score_breakdown.total

@pytest.mark.parametrize('run_id',['../outside','..','.','a/b','a'*200])
def test_unsafe_snapshot_writes_rejected(run_id,settings):
    s=build_demo_snapshot(settings);s.run_id=run_id
    with pytest.raises(ValueError):SnapshotStore(settings).save_snapshot(s)

def test_raw_unique_within_second(settings):
    store=SnapshotStore(settings)
    a=store.save_raw('youtube',{'ok':True});b=store.save_raw('youtube',{'error':'timeout'})
    assert a!=b and a.exists() and b.exists()

def valid_record(**kwargs):
    base={'page_id':'p','game_slug':'g','keyword':'g calculator','market':'US'};base.update(kwargs)
    return ValidationRecord(**base)

@pytest.mark.parametrize('stage',['pending_serp','validated'])
def test_validation_requires_semrush(stage):
    with pytest.raises(ValidationError):valid_record(stage=stage)

def test_build_requires_manual_validation():
    with pytest.raises(ValidationError):valid_record(decision='build')

def test_zero_volume_is_valid_semrush_observation():
    r=valid_record(stage='pending_serp',semrush_volume=0,semrush_evidence='US keyword exact result: 0',semrush_checked_at=utc_now()-timedelta(minutes=1))
    assert r.semrush_volume==0

def test_duplicate_serp_urls_not_three_results():
    with pytest.raises(ValidationError):valid_record(stage='validated',semrush_volume=10,semrush_evidence='checked',semrush_checked_at=utc_now(),
        serp_urls=['https://example.com/a']*3,serp_notes='checked',serp_checked_at=utc_now(),decision='build',decision_reason='gap')

def test_validated_record_with_evidence_persists(settings):
    r=valid_record(stage='validated',semrush_volume=100,semrush_evidence='US checked',semrush_checked_at=utc_now()-timedelta(minutes=1),
        serp_urls=[f'https://example.com/{i}' for i in range(3)],serp_notes='Comparison of intended page types',serp_checked_at=utc_now()-timedelta(minutes=1),decision='build',decision_reason='Observed page gap')
    store=ValidationStore(settings);store.save(r)
    assert store.list()[0].stage=='validated'

def test_future_validation_not_accepted():
    with pytest.raises(ValidationError):valid_record(semrush_checked_at=utc_now()+timedelta(days=1))

def test_source_secrets_not_serialized(settings):
    settings.twitch_client_secret='secret';settings.youtube_api_key='private'
    data=settings.model_dump_json()
    assert 'twitch_client_secret' not in data and 'youtube_api_key' not in data and '"secret"' not in data and '"private"' not in data

def test_config_toml(tmp_path):
    (tmp_path/'radar.toml').write_text('[scan]\ndiscovery_limit=55\ndeep_analysis_limit=3\n[sources]\nreddit=false\n')
    s=Settings.load(tmp_path)
    assert s.discovery_limit==55 and s.deep_analysis_limit==3 and not s.reddit_enabled

def test_config_unknown_key_rejected(tmp_path):
    (tmp_path/'radar.toml').write_text('[scan]\nunknown_setting=2\n')
    with pytest.raises(ValueError):Settings.load(tmp_path)
