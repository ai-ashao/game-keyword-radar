"""Pipeline ordering, manual state, HTTP budgets, and monitoring separation."""
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import asyncio
import json
import pytest
import httpx
from fastapi.testclient import TestClient
from game_keyword_radar.config import Settings
from game_keyword_radar.models import *
from game_keyword_radar.pipeline import Scanner
from game_keyword_radar.storage import SnapshotStore
from game_keyword_radar.sources.steam import SearchRow
from game_keyword_radar.sources.twitch import TwitchProvider
from game_keyword_radar.sources.base import HttpProvider, BudgetExceeded
from game_keyword_radar.web.app import create_app
from game_keyword_radar.history_v2 import compare_v2
from game_keyword_radar.monitoring import MonitorController
from game_keyword_radar.demo import build_v21_demo_snapshot
from test_v21_selection import NOW, entity, signal, window

class IngressSteam:
    def __init__(self,events):self.events=events
    async def discover_rows(self,limit):
        self.events.append('discovery')
        return [SearchRow('1','New Small Game',1,'popular_new','https://store.steampowered.com/app/1/'),
                SearchRow('2','Mature Huge Game',1,'top_sellers','https://store.steampowered.com/app/2/')],[],[]
    async def metadata(self,entities,rows):
        self.events.append('metadata')
        return [GameCandidate(app_id=e.platform_ids['steam'],name=e.canonical_name,store_url='https://example.com/game',
                release_stage='released',release_date=(NOW-timedelta(days=3 if e.platform_ids['steam']=='1' else 1000)).date(),
                release_date_precision='day',metadata_captured_at=NOW,collected_at=NOW,genres=['Crafting']) for e in entities],[]
    async def observe(self,e):
        self.events.append('observe-steam:'+e.slug)
        return signal(e.slug,value=300 if e.platform_ids['steam']=='1' else 900000)
    async def close(self):pass

class IngressTwitch:
    def __init__(self,events):self.events=events
    async def discover_categories(self,limit):
        return [{'id':'99','name':'Twitch Only Game'}],[]
    async def fetch(self,e):
        self.events.append('observe-twitch:'+e.slug)
        return signal(e.slug,source='twitch',value=500)
    async def close(self):pass

class Deep:
    def __init__(self,source,events):self.source=source;self.events=events;self.raw=[]
    async def fetch(self,e):
        self.events.append('deep-'+self.source+':'+e.slug)
        return PlatformSignal(source=self.source,game_slug=e.slug,captured_at=NOW,metrics={'sample_size':1},
            evidence=[EvidenceItem(id=self.source+e.slug,source=self.source,title=e.canonical_name+' crafting calculator',
                url='https://example.com/task',captured_at=NOW,published_at=NOW-timedelta(days=1))])
    async def close(self):pass

def fake_providers(events):
    return {'steam':IngressSteam(events),'twitch':IngressTwitch(events),**{s:Deep(s,events) for s in ['youtube','reddit','trends']}}

async def test_A04_A05_directed_observation_before_deep_and_twitch_only_preserved(tmp_path):
    events=[];s=Settings(project_root=tmp_path)
    result=await Scanner(s,fake_providers(events),clock=lambda:NOW).run(discovery_limit=10,deep=4)
    assert len(result.entities)==3
    assert events.index('observe-twitch:new-small-game')<next(i for i,x in enumerate(events) if x.startswith('deep-'))
    assert not any('mature-huge-game' in x for x in events if x.startswith('deep-'))
    assert any(e.slug=='twitch-only-game' for e in result.entities)
    assert result.selection_summary['mature_without_trigger']==1
    assert result.before_deep_selection['decisions']==[d.model_dump(mode='json') for d in result.selection_decisions]
    assert all(datetime.fromisoformat(d['as_of'])==NOW for d in result.before_deep_selection['decisions'])
    assert result.raw_metadata['deep_game_slugs'] and SnapshotStore(s).load_latest().analysis_version=='2.1'

async def test_A25_zero_deep_never_calls_problem_sources(tmp_path):
    events=[];s=Settings(project_root=tmp_path)
    result=await Scanner(s,fake_providers(events),clock=lambda:NOW).run(deep=0)
    assert not any(e.startswith('deep-') for e in events)
    assert result.selection_summary['deep_selected']==0

async def test_A37_monitoring_separation_gap_no_synthetic_catchup(tmp_path):
    s=Settings(project_root=tmp_path);store=SnapshotStore(s)
    full=build_v21_demo_snapshot(s);store.save_snapshot(full)
    before=(s.data_dir/'latest.json').read_bytes()
    store.save_monitoring_state({'last_completed_at':(NOW-timedelta(hours=20)).isoformat()})
    result=await Scanner(s,fake_providers([]),clock=lambda:NOW).monitor_once()
    assert isinstance(result,MonitoringSnapshot)
    assert (s.data_dir/'latest.json').read_bytes()==before
    assert not (s.reports_dir/f'{result.run_id}-game-keywords.md').exists()
    assert len(list((s.data_dir/'observations').glob('*/*.json')))==1
    assert result.raw_metadata['missed_intervals']==9
    assert len(store.history_records(as_of=NOW+timedelta(days=1)))==1 # only LIVE monitoring; Demo excluded

async def test_A37_shared_lock_blocks_other_scans(tmp_path):
    s=Settings(project_root=tmp_path)
    with SnapshotStore(s).scan_lock():
        with pytest.raises(RuntimeError):
            await Scanner(s,fake_providers([]),clock=lambda:NOW).monitor_once()
        with pytest.raises(RuntimeError):
            await Scanner(s,fake_providers([]),clock=lambda:NOW).run(deep=0)

async def test_monitor_controller_explicit_start_and_stop(tmp_path):
    calls=[]
    class FakeScanner:
        def __init__(self,s):pass
        async def monitor_once(self):calls.append('actual');return SimpleNamespace(run_id='once')
    m=MonitorController(Settings(project_root=tmp_path),scanner_factory=FakeScanner)
    assert not m.enabled and not calls
    assert m.start()
    await asyncio.sleep(.01)
    assert calls==['actual'] and m.enabled
    await m.stop()
    assert not m.enabled and not m.running

@pytest.mark.parametrize('variant',['rank','pages','policy'])
def test_A36_separate_history_changes(variant,tmp_path):
    s=Settings(project_root=tmp_path);old=build_v21_demo_snapshot(s);new=old.model_copy(deep=True)
    new.run_id='second';new.generated_at+=timedelta(hours=2)
    if variant=='rank':new.game_opportunities[0].rank+=1
    elif variant=='pages':new.game_opportunities[0].page_ids.append('hypothesis-new')
    else:new.selection_policy_version='next-policy'
    data=compare_v2(new,old)
    assert data['score_changed_games']==0
    assert data['rank_changed_games']==(1 if variant=='rank' else 0)
    assert data['page_changed_games']==(1 if variant=='pages' else 0)
    if variant=='policy':assert not data['comparable'] and not data['v2_game_changes'][0]['score_comparable']

async def test_request_budget_counts_failed_attempts_and_cache(tmp_path):
    from game_keyword_radar.sources.steam import SteamProvider, PLAYER_COUNT_URL
    settings=Settings(project_root=tmp_path,request_budget={'steam_attempts_per_run':1})
    calls=[]
    def fail(req):calls.append(req);return httpx.Response(503)
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        p=SteamProvider(settings,client)
        with pytest.raises(httpx.HTTPStatusError):await p.fetch_current_players('1')
        with pytest.raises(BudgetExceeded):await p.fetch_current_players('2')
        assert p.calls==1 and len(calls)==1
    def success(req):return httpx.Response(200,json={'response':{'result':1,'player_count':500}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(success)) as client:
        p=SteamProvider(settings,client)
        e=entity();a=await p.observe(e);b=await p.observe(e)
        assert a.observation_id==b.observation_id and a.captured_at==b.captured_at and b.cache_hit
        assert p.calls==1

async def test_A04_twitch_exact_game_id_not_top_games_required(tmp_path):
    settings=Settings(project_root=tmp_path,twitch_client_id='dummy',twitch_client_secret='dummy',request_budget={'twitch_attempts_per_run':3})
    paths=[]
    def handler(req):
        paths.append(req.url.path)
        if req.url.path.endswith('/token'):return httpx.Response(200,json={'access_token':'mock','expires_in':3600})
        if req.url.path.endswith('/games'):return httpx.Response(200,json={'data':[{'id':'42','name':'synthetic'}]})
        assert req.url.params['game_id']=='42'
        return httpx.Response(200,json={'data':[{'id':'stream','user_id':'channel','viewer_count':100,'game_id':'42'}],'pagination':{}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p=TwitchProvider(settings,client);e=entity();s=await p.fetch(e)
        assert s.metrics['total_viewers']==100 and s.metrics['non_top1_viewers']==0 and s.observation_id
        assert p.calls==3 and not any('games/top' in x for x in paths)
        b=await p.fetch(e)
        assert b.cache_hit and p.calls==3

async def test_rate_limit_honored_without_alternate_hosts(tmp_path):
    calls=[]
    def handler(req):calls.append(str(req.url));return httpx.Response(429,headers={'Retry-After':'60'})
    s=Settings(project_root=tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p=HttpProvider(s,client)
        with pytest.raises(httpx.HTTPStatusError):await p.get_json('https://api.example.com/')
        from game_keyword_radar.sources.base import ProviderError
        with pytest.raises(ProviderError):await p.get_json('https://api.example.com/')
    assert len(calls)==1

def test_policy_seed_annotation_and_future_timestamp_guards(tmp_path):
    s=Settings(project_root=tmp_path)
    with TestClient(create_app(s)) as api:
        policy=api.get('/api/policy').json()
        assert policy['policy']['selection']['new_release_weight']==4
        assert api.put('/api/policy',json={'unknown':{}}).status_code==422
        assert api.put('/api/policy',json={'selection':{'typo':1}}).status_code==422
        assert api.put('/api/policy',json={'selection':{'new_release_days':60}}).status_code==200
        seed=api.post('/api/seeds',json={'canonical_name':'Seed Game','platform':'steam','platform_id':'42','reason':'Research request','evidence_url':'https://example.com/game'})
        assert seed.status_code==200
        slug=seed.json()['entity']['slug']
        a=api.put('/api/annotations',json={'game_slug':slug,'watch':True})
        assert a.status_code==200
        assert api.put('/api/annotations',json={'game_slug':slug,'first_public_playable_at':'2026-09-01'}).status_code==422
        assert api.put('/api/annotations',json={'game_slug':slug,'reason':'future','research_requested_at':(utc_now()+timedelta(days=1)).isoformat()}).status_code==422
        assert not (s.project_root/'radar.toml').exists()
        assert api.get('/api/monitoring').json()['enabled'] is False

def test_manual_evidence_applies_next_run_and_has_publication_time(tmp_path):
    from game_keyword_radar.annotations import annotation_evidence,apply_annotation
    a=GameAnnotation(game_slug='synthetic',reason='Workshop error after update',evidence_url='https://example.com/q',
        intent='workshop',evidence_published_at=NOW-timedelta(days=1),checked_at=NOW)
    assert annotation_evidence(a,NOW)[0].published_at==NOW-timedelta(days=1)
    g=entity();apply_annotation(g,a,NOW)
    assert g.release_stage=='released' # watch/intent form must not reset lifecycle stage

def test_policy_api_no_credentials_and_csrf(tmp_path):
    s=Settings(project_root=tmp_path,twitch_client_secret='private-test-value')
    with TestClient(create_app(s)) as api:
        for path in ['/api/policy','/api/monitoring','/api/sources']:
            assert 'private-test-value' not in api.get(path).text
        assert api.put('/api/policy',json={},headers={'Origin':'https://evil.example'}).status_code==403
        assert api.post('/api/seeds',json={},headers={'Origin':'https://evil.example'}).status_code==403
