"""Business regressions for V2.1. All numbers and game names are synthetic."""
from datetime import date, datetime, timedelta, timezone
import math
import json
import pytest
from pydantic import ValidationError
from game_keyword_radar.config import Settings
from game_keyword_radar.models import GameEntity, GameAnnotation, EvidenceItem, PlatformSignal, SourceState
from game_keyword_radar.research_models import ReleaseDateEvidence, MomentumAssessment, SelectionDecision
from game_keyword_radar.analyzers.lifecycle import classify_lifecycle
from game_keyword_radar.analyzers.momentum import assess_momentum
from game_keyword_radar.analyzers.candidate_selection import decide_candidate, allocate_deep, allocate_basic, quotas, fresh_demand
from game_keyword_radar.observations import stamp_observation, unique_observations

NOW = datetime(2026,9,11,12,tzinfo=timezone.utc)

@pytest.fixture
def settings(tmp_path): return Settings(project_root=tmp_path)

def entity(name='synthetic', age=5, *, verified=True, **kwargs):
    game=GameEntity(canonical_name=name,slug=name,platform_ids={'steam':'123'},discovery_sources=['popular_new'],
        first_seen_at=NOW,release_stage='released',**kwargs)
    if age is not None:
        d=(NOW-timedelta(days=age)).date()
        game.platform_release_dates['steam']=ReleaseDateEvidence(date=d,source='steam',source_url='https://store.steampowered.com/app/123/',checked_at=NOW)
        if verified:
            game.first_public_playable_at=d
            game.release_date_basis='verified_public'
            game.release_sources=['https://example.com/release']
    return game

def signal(slug='synthetic',value=300,*,source='steam',hours=0,complete=True,scope='game_streams',**metrics):
    values={'current_players':value,'country':'US'} if source=='steam' else {'total_viewers':value,'live_channels':8,
        'top1_viewer_share':.1,'non_top1_viewers':value*.9,'sampling_complete':complete,'sampling_scope':scope,'sample_page_limit':3}
    values.update(metrics)
    return stamp_observation(PlatformSignal(source=source,game_slug=slug,captured_at=NOW-timedelta(hours=hours),
        scope_version='2.1',market='GLOBAL',metrics=values))

def window(slug='synthetic',now=700,old=300,source='steam',**kw):
    return [signal(slug,now,source=source,hours=h,**kw) for h in (0,2,4)] + [signal(slug,old,source=source,hours=h,**kw) for h in (24,26,28)]

def decision(game,settings,signals=None,prior=None,**kw):
    current=signals if signals is not None else [signal(game.slug)]
    m=assess_momentum(game.slug,current,prior or [],settings,NOW)
    return decide_candidate(game,current,m,settings,NOW,**kw)

def test_A01_A02_mature_size_and_first_seen_do_not_admit(settings):
    g=entity(age=1000)
    d=decision(g,settings,[signal(value=900000)])
    summary=allocate_deep([d],[g],settings,NOW,10)
    assert d.lifecycle.lifecycle=='established' and d.primary_lane is None
    assert d.decision=='monitor_only' and summary['deep_selected']==0
    assert g.first_seen_at==NOW and d.lifecycle.age_days==1000

@pytest.mark.parametrize('source,value,extra',[('steam',250,{}),('twitch',100,{}),('twitch',1,{'live_channels':3})])
def test_A03_A11_initial_attention_is_OR_not_five_source_gate(source,value,extra,settings):
    g=entity();d=decision(g,settings,[signal(source=source,value=value,**extra)])
    assert d.primary_lane=='new_release' and d.momentum.state=='unknown'
    allocate_deep([d],[g],settings,NOW,1)
    assert d.selected_for_deep

@pytest.mark.parametrize('stage',['demo','upcoming'])
def test_A12_preview_is_not_released_new_game(stage,settings):
    g=entity();g.release_stage=stage
    d=decision(g,settings)
    assert d.lifecycle.lifecycle=='preview' and d.primary_lane=='exploration'

@pytest.mark.parametrize('kind',['port','rename','early_access_exit','rebrand'])
def test_A12_known_release_event_does_not_reset_age(kind,settings):
    g=entity(age=5,verified=False);g.release_events=[{'kind':kind}]
    life=classify_lifecycle(g,NOW,settings)
    assert not life.recent_eligible
    g.first_public_playable_at=(NOW-timedelta(days=900)).date();g.release_date_basis='manual_verified';g.release_sources=['https://example.com/verified-release']
    assert classify_lifecycle(g,NOW,settings).lifecycle=='established'

def test_A13_provisional_unknown_and_conflict_are_distinct(settings):
    g=entity(verified=False);d=decision(g,settings)
    assert d.primary_lane=='new_release' and d.lifecycle.recency_status=='provisional_platform_date'
    assert d.lifecycle.lifecycle=='unknown'
    g.platform_release_dates={};d=decision(g,settings)
    assert d.primary_lane=='exploration'
    g=entity(verified=False);g.release_date_conflict=True
    assert decision(g,settings).primary_lane=='exploration'

def test_release_evidence_future_ignored_and_asof_required(settings):
    g=entity(verified=False);g.platform_release_dates['steam'].checked_at=NOW+timedelta(days=1)
    assert not classify_lifecycle(g,NOW,settings).recent_eligible
    with pytest.raises(ValueError):classify_lifecycle(g,NOW.replace(tzinfo=None),settings)

def test_A06_single_broadcaster_not_sustained(settings):
    g=entity(age=None)
    d=decision(g,settings,[signal(source='twitch',value=90000,live_channels=1,top1_viewer_share=1,non_top1_viewers=0)])
    assert d.momentum.state=='early_signal' and d.momentum.breadth=='concentrated'
    assert d.primary_lane=='exploration' and not d.momentum.rising_sources

def test_A07_breadth_broadening(settings):
    values=window(source='twitch',now=600,old=200)
    for s in values:
        s.metrics['live_channels']=20 if s.captured_at>=NOW-timedelta(hours=4) else 5
        s.observation_id=None
    m=assess_momentum('synthetic',[values[0]],values[1:],settings,NOW)
    assert m.breadth=='broadening' and m.state=='rising'

def test_A08_A09_single_source_mature_rising_is_valid(settings):
    g=entity(age=1000);values=window()
    d=decision(g,settings,[values[0]],values[1:])
    assert d.primary_lane=='rising' and d.momentum.rising_sources==['steam']
    allocate_deep([d],[g],settings,NOW,1)
    assert d.selected_for_deep

def test_A10_recent_manual_task_admits_old_without_changing_age(settings):
    g=entity(age=1000)
    task=EvidenceItem(id='manual1',source='manual',title='Workshop download stuck after update',
        url='https://example.com/evidence',published_at=NOW-timedelta(days=1),captured_at=NOW,metrics={'intent':'workshop'})
    d=decision(g,settings,evidence=[task])
    assert d.primary_lane=='new_demand' and d.lifecycle.lifecycle=='established'
    assert 'manual1' in d.trigger_evidence_ids

@pytest.mark.parametrize('old,now',[(0,500),(2,20),(99,500)])
def test_A14_low_base_percent_is_null(old,now,settings):
    values=window(now=now,old=old);m=assess_momentum('synthetic',[values[0]],values[1:],settings,NOW)
    c=next(x for x in m.comparisons if x.period=='24h')
    assert c.percent_change is None and c.absolute_delta==now-old and c.low_base
    assert m.state=='early_signal' and not m.rising_sources

def test_A15_cache_duplicates_cannot_make_window(settings):
    a=signal(hours=24);b=signal(value=1000)
    copies=[b.model_copy(update={'cache_hit':True}) for _ in range(4)]
    m=assess_momentum('synthetic',[b],[a,*copies],settings,NOW)
    assert all(not c.qualified for c in m.comparisons)
    assert len(unique_observations([a,b,*copies],NOW))==2

@pytest.mark.parametrize('key,value',[('sampling_scope','global_top_streams'),('sample_page_limit',1),('sampling_complete',False)])
def test_A16_A17_scope_changes_not_growth(key,value,settings):
    values=window(source='twitch')
    for s in values[3:]:s.metrics[key]=value;s.observation_id=None
    m=assess_momentum('synthetic',[values[0]],values[1:],settings,NOW)
    assert not any(c.period=='24h' for c in m.comparisons)
    assert m.state!='rising'

@pytest.mark.parametrize('field,value',[('market','GB'),('scope_version','next'),('origin','demo')])
def test_A18_market_metric_or_origin_change_not_growth(field,value,settings):
    values=window()
    for s in values[3:]:setattr(s,field,value);s.observation_id=None
    m=assess_momentum('synthetic',[values[0]],values[1:],settings,NOW)
    assert not m.rising_sources and not any(c.period=='24h' for c in m.comparisons)

def test_A19_rank_only_or_missing_top_sample_is_not_zero_viewers(settings):
    s=PlatformSignal(source='twitch',game_slug='synthetic',captured_at=NOW,metrics={'category_rank':12})
    d=decision(entity(age=1000),settings,[s])
    assert d.momentum.state=='unknown' and d.primary_lane is None

def test_A20_only_point_pair_is_not_sustained(settings):
    m=assess_momentum('synthetic',[signal(value=1000)],[signal(value=200,hours=24)],settings,NOW)
    assert m.state=='early_signal' and m.persistence=='untested'
    assert m.comparisons[0].comparison_kind=='point_pair'

def test_A21_pairing_window_has_unique_ids_and_real_intervals(settings):
    values=window();m=assess_momentum('synthetic',[values[0]],values[1:],settings,NOW)
    c=next(x for x in m.comparisons if x.period=='24h')
    assert m.state=='rising' and c.qualified and c.pair_count==3
    assert len(set(c.baseline_observation_ids))==3 and c.actual_elapsed_hours==[24,24,24]
    assert c.current_value==700 and c.baseline_value==300

@pytest.mark.parametrize('now,state',[(300,'stable'),(360,'inconclusive'),(50,'falling')])
def test_momentum_stable_deadband_and_falling(now,state,settings):
    values=window(now=now,old=300)
    m=assess_momentum('synthetic',[values[0]],values[1:],settings,NOW)
    assert m.state==state

def test_A22_opposed_platforms_are_mixed(settings):
    steam=window();twitch=window(source='twitch',now=100,old=500)
    m=assess_momentum('synthetic',[steam[0],twitch[0]],[*steam[1:],*twitch[1:]],settings,NOW)
    assert m.state=='mixed' and set(m.conflicting_sources)=={'steam','twitch'}

def test_partial_window_is_a_clue_not_certified_growth(settings):
    values=window(source='twitch',complete=False)
    m=assess_momentum('synthetic',[values[0]],values[1:],settings,NOW)
    assert m.state=='early_signal' and not m.rising_sources
    assert any(c.comparison_kind=='sample_window' for c in m.comparisons)

def candidates_per_lane(settings,n=12):
    games=[];decisions=[]
    for lane in ('new_release','rising','new_demand','exploration'):
        for i in range(n):
            g=entity(f'{lane}-{i}',age=None)
            games.append(g)
            decisions.append(SelectionDecision(game_slug=g.slug,primary_lane=lane,eligible_lanes=[lane],decision='deferred_budget',as_of=NOW))
    return games,decisions

def test_A23_balanced_ten_and_no_duplicate_slots(settings):
    games,ds=candidates_per_lane(settings)
    s=allocate_deep(ds,games,settings,NOW,10)
    assert s['lane_selected']=={'new_release':4,'rising':3,'new_demand':1,'exploration':2}
    assert len({d.game_slug for d in ds if d.selected_for_deep})==10

def test_A24_multilane_one_primary_slot(settings):
    g=entity();values=window()
    d=decision(g,settings,[values[0]],values[1:])
    assert {'new_release','rising'}.issubset(d.eligible_lanes) and d.primary_lane=='new_release'
    assert allocate_deep([d],[g],settings,NOW,10)['deep_selected']==1

@pytest.mark.parametrize('n',[0,1,7,30])
def test_A25_integer_budgets(n,settings):
    games,ds=candidates_per_lane(settings,40);s=allocate_deep(ds,games,settings,NOW,n)
    assert s['deep_selected']==n and sum(s['lane_selected'].values())==n
    assert s['lane_selected']['exploration']<=math.ceil(.4*n)
    assert quotas(n,settings.selection.weights)==s['lane_quotas']

def test_A26_spare_exploration_cap_and_A27_no_filler(settings):
    games,ds=candidates_per_lane(settings)
    ds=[d for d in ds if d.primary_lane=='exploration']
    s=allocate_deep(ds,games,settings,NOW,10)
    assert s['deep_selected']==4 and s['unused_deep_slots']==6
    g=entity(age=500);d=decision(g,settings,[])
    assert allocate_deep([d],[g],settings,NOW,10)['deep_selected']==0

def test_A28_weak_new_kept_in_exploration(settings):
    d=decision(entity(),settings,[signal(value=12)])
    assert d.primary_lane=='exploration' and any('12' in e for e in d.missing_evidence)

def test_A29_cooldown_then_new_task_or_manual(settings):
    g=entity();d=decision(g,settings)
    g.last_deep_analyzed_at=NOW-timedelta(hours=2);g.last_deep_trigger_fingerprint=d.trigger_fingerprint
    allocate_deep([d],[g],settings,NOW,10)
    assert not d.selected_for_deep and 'deep_cooldown' in d.reason_codes
    task=EvidenceItem(id='fresh',source='reddit',title='New crafting calculator question',url='https://example.com/q',published_at=NOW,captured_at=NOW)
    new=decision(g,settings,evidence=[task]);allocate_deep([new],[g],settings,NOW,10)
    assert new.selected_for_deep

def test_A30_manual_old_game_consumes_budget(settings):
    g=entity(age=1000);a=GameAnnotation(game_slug=g.slug,reason='Explicit research request',research_requested_at=NOW,checked_at=NOW)
    d=decision(g,settings,manual=a);s=allocate_deep([d],[g],settings,NOW,1)
    assert d.entry_origin=='manual' and s['manual_selected']==1 and s['automatic_selected']==0

def test_A31_metadata_selection_protects_recent_ingress(settings):
    old=[entity(f'old-{i}',age=1000) for i in range(80)]
    fresh=[entity(f'new-{i}',age=4,verified=False) for i in range(80)]
    picked=allocate_basic(old+fresh,settings,NOW,10,metadata=True)
    assert sum(g.slug.startswith('new-') for g in picked)>=6
    assert all(not g.slug.startswith('old-') for g in allocate_basic(old+fresh,settings,NOW,10))

def test_A32_old_or_future_task_is_not_new(settings):
    g=entity(age=1000)
    def task(age):return EvidenceItem(id=str(age),source='reddit',title='crafting calculator',url='https://example.com/q',published_at=NOW-timedelta(days=age),captured_at=NOW)
    d=decision(g,settings,evidence=[task(90),task(-1)])
    assert not d.eligible_lanes
    same=task(1);copy=same.model_copy(update={'id':'other','source':'youtube'})
    assert len(fresh_demand([same,copy],NOW,14))==1

def test_A33_youtube_proxy_separate_from_questions(settings):
    from game_keyword_radar.analyzers.question_mining import mine_questions
    g=entity();video=EvidenceItem(id='v',source='youtube',title='crafting calculator guide',url='https://example.com/v')
    clusters=mine_questions(g,[PlatformSignal(source='youtube',game_slug=g.slug,evidence=[video])])
    assert len(clusters)==1 and clusters[0].question_count==0 and clusters[0].content_proxy_count==1

@pytest.mark.parametrize('text',['[typo]\na=1','[selection]\ntyop=1','[scan]\nunknown=1',
    '[selection]\nnew_release_weight=-1','[discovery_budget]\nrecent_release_metadata_share=0.1'])
def test_A40_unknown_sections_keys_ratios_fail(text,tmp_path):
    (tmp_path/'radar.toml').write_text(text)
    with pytest.raises((ValueError,ValidationError)):Settings.load(tmp_path)

def test_configuration_precedence_and_secrets_not_public(tmp_path,monkeypatch):
    (tmp_path/'.env').write_text('GKR_COUNTRY=DE\nTWITCH_CLIENT_SECRET=not-a-real-key\nGKR_SELECTION_NEW_RELEASE_DAYS=40\n')
    monkeypatch.setenv('GKR_COUNTRY','GB')
    (tmp_path/'radar.toml').write_text('[markets]\nsteam_country="US"\n[selection]\nnew_release_days=60\n')
    s=Settings.load(tmp_path)
    assert s.country=='US' and s.selection.new_release_days==60
    assert 'not-a-real-key' not in json.dumps(s.public_policy())
    assert 'not-a-real-key' not in s.model_dump_json()


def test_A12_rehydration_cannot_rejuvenate_existing_app(settings):
    from game_keyword_radar.analyzers.entity_resolution import EntityResolver
    from game_keyword_radar.models import GameCandidate
    resolver=EntityResolver(as_of=NOW)
    old=GameCandidate(app_id='123',name='Original Title',release_date=(NOW-timedelta(days=900)).date(),
        release_stage='early_access',release_date_precision='day',genres=['RPG'],categories=['Single-player'],
        store_url='https://store.steampowered.com/app/123/',collected_at=NOW)
    original=resolver.from_steam(old)
    new=old.model_copy(update={'name':'Renamed Title','release_date':(NOW-timedelta(days=3)).date(),'release_stage':'released'})
    updated=resolver.from_steam(new)
    assert updated.slug==original.slug
    assert classify_lifecycle(updated,NOW,settings).lifecycle=='established'
    assert updated.platform_release_dates['steam'].date==old.release_date
    assert any(e['kind']=='early_access_exit' for e in updated.release_events)
    unavailable=new.model_copy(update={'genres':[],'categories':[],'mechanics':[],'release_date':None,'release_stage':'unknown'})
    assert resolver.from_steam(unavailable).genres==['RPG']


def test_verified_release_requires_source_and_stage_annotation_provenance(settings):
    g=entity();g.release_sources=[]
    assert classify_lifecycle(g,NOW,settings).recency_status=='provisional_platform_date'
    with pytest.raises(ValidationError):GameAnnotation(game_slug='synthetic',release_stage='released')


def test_A21_seven_day_one_to_one_window_and_times(settings):
    values=[signal(value=1000,hours=h) for h in (0,2,4)]+[signal(value=500,hours=h) for h in (168,170,172)]
    m=assess_momentum('synthetic',[values[0]],values[1:],settings,NOW)
    c=next(c for c in m.comparisons if c.period=='7d')
    assert c.qualified and c.pair_count==3 and c.percent_change==100
    assert len(set(c.baseline_observation_ids))==3 and m.state=='rising'


def test_A32_synonymous_titles_do_not_create_four_page_intents(settings):
    from game_keyword_radar.analyzers.question_mining import mine_questions
    from game_keyword_radar.analyzers.page_graph import build_page_graph
    from game_keyword_radar.analyzers.demand_momentum import score_demand
    g=entity()
    examples=[EvidenceItem(id=f'q{i}',source='reddit',title=title,url=f'https://example.com/{i}',published_at=NOW,captured_at=NOW)
              for i,title in enumerate(['How to fix workshop download stuck?','Workshop download not working?',
                                        'Steam workshop download stuck?','How do I fix workshop download?'])]
    platform=PlatformSignal(source='reddit',game_slug=g.slug,evidence=examples,captured_at=NOW)
    clusters=mine_questions(g,[platform]);pages=build_page_graph(g,clusters,score_demand([platform]),settings)
    assert len({p.id for p in pages})==len(pages)==1
