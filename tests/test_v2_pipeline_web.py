from __future__ import annotations
import asyncio
import json
from datetime import timedelta
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from game_keyword_radar.models import *
from game_keyword_radar.config import Settings
from game_keyword_radar.sources.steam import SteamCollection
from game_keyword_radar.pipeline import Scanner
from game_keyword_radar.storage import SnapshotStore
from game_keyword_radar.demo import build_demo_snapshot
from game_keyword_radar.web.app import create_app

class FakeSteam:
    def __init__(self,fail=False):self.fail=fail
    async def collect(self,limit):
        if self.fail:raise RuntimeError('steam unreachable')
        return SteamCollection(games=[GameCandidate(app_id='123',name='Example Game',store_url='https://store.steampowered.com/app/123/',
            genres=['Crafting','Open World'],current_players=3000,reviews_total=500,steam_rank=1)],raw={'source':'steam','market':'US','status':'ok','fixture':True})
    async def close(self):pass
class FakeTwitch:
    def __init__(self,fail=False):self.fail=fail
    async def discover(self,limit):
        if self.fail:raise RuntimeError('twitch unreachable')
        return ([{'id':'42','name':'Example Game'},{'id':'43','name':'Twitch Only Game'}],
                [{'game_id':'42','metrics':{'total_viewers':5000,'live_channels':100,'twitch_rank':1},'captured_at':utc_now()},
                 {'game_id':'43','metrics':{'total_viewers':1500,'live_channels':50,'twitch_rank':2},'captured_at':utc_now()}])
    async def fetch(self,entity):
        if self.fail:raise RuntimeError('twitch unreachable')
        return PlatformSignal(source='twitch',game_slug=entity.slug,market='GLOBAL',metrics={'total_viewers':2000,'live_channels':20,'sampling_complete':True,'sampling_scope':'game_streams','sample_page_limit':3})
    async def close(self):pass
class FakeDeep:
    def __init__(self,source,fail=False):self.source=source;self.fail=fail;self.slugs=[]
    async def fetch(self,entity):
        self.slugs.append(entity.slug)
        if self.fail:raise RuntimeError('source unreachable')
        metrics={'recent_guide_video_count':3,'creator_count':3,'intent_video_share':1,'view_velocity_proxy':500} if self.source=='youtube' else {'question_count':2,'unique_authors':2} if self.source=='reddit' else {'direction_delta':10,'trend_direction':'rising'}
        return PlatformSignal(source=self.source,game_slug=entity.slug,metrics=metrics,
            evidence=[EvidenceItem(id=f'{self.source}:{entity.slug}',source=self.source,title=f'{entity.canonical_name} crafting calculator',url='https://example.com/evidence')])
    async def close(self):pass

def providers(failed=None):
    return {'steam':FakeSteam(failed=='steam'),'twitch':FakeTwitch(failed=='twitch'),
            **{s:FakeDeep(s,failed==s) for s in ('youtube','reddit','trends')}}

async def test_pipeline_merges_entities_and_preserves_twitch_only(tmp_path):
    s=Settings(project_root=tmp_path,trends_enabled=True);result=await Scanner(s,providers()).run(discovery_limit=5,deep=2)
    assert result.schema_version==2 and len(result.entities)==2 and len(result.platform_signals)==10
    assert next(e for e in result.entities if e.canonical_name=='Example Game').platform_ids=={'steam':'123','twitch':'42'}
    assert result.page_opportunities and result.opportunities
    assert all(p.validation_status=='needs_validation' for p in result.page_opportunities)
    assert SnapshotStore(s).load_latest().run_id==result.run_id

@pytest.mark.parametrize('source',['steam','twitch','youtube','reddit','trends'])
async def test_each_source_can_fail_without_aborting_pipeline(source,tmp_path):
    result=await Scanner(Settings(project_root=tmp_path,trends_enabled=True),providers(source)).run(discovery_limit=5,deep=2)
    assert result.entities and result.source_statuses and result.run_id
    status=next(s for s in result.source_statuses if s.source==source)
    assert status.state in {SourceState.FAILED,SourceState.INSUFFICIENT_DATA,SourceState.UNAVAILABLE}
    if source in {'youtube','reddit','trends'}:assert any(s.source==source and s.status==SourceState.FAILED for s in result.platform_signals)

async def test_deep_budget_limits_candidate_calls(tmp_path):
    p=providers();result=await Scanner(Settings(project_root=tmp_path,trends_enabled=True),p).run(discovery_limit=5,deep=1)
    assert len(p['youtube'].slugs)==1 and len(p['reddit'].slugs)==1
    assert len(result.raw_metadata['deep_game_slugs'])==1

async def test_disabled_all_sources_keeps_previous_snapshot(tmp_path):
    s=Settings(project_root=tmp_path,steam_enabled=False,twitch_enabled=False,youtube_enabled=False,reddit_enabled=False,trends_enabled=False)
    old=build_demo_snapshot(s);old.run_id='previous';old.is_demo=False;store=SnapshotStore(s);store.save_snapshot(old)
    result=await Scanner(s,providers()).run(deep=0)
    assert not result.entities and store.load_latest().run_id=='previous'

async def test_second_scan_stable_entity_ids(tmp_path):
    s=Settings(project_root=tmp_path);a=await Scanner(s,providers()).run(discovery_limit=5,deep=2)
    b=await Scanner(s,providers()).run(discovery_limit=5,deep=2)
    assert [e.slug for e in a.entities]==[e.slug for e in b.entities]
    # V2.1 rotates the second exploratory entity into Deep; existing IDs remain stable.
    assert {p.id for p in a.page_opportunities}.issubset({p.id for p in b.page_opportunities})
    assert all('24h' not in sig.history for sig in b.platform_signals)

@pytest.fixture
def api(tmp_path):
    with TestClient(create_app(Settings(project_root=tmp_path))) as client:yield client

def test_empty_shell_and_version(api):
    r=api.get('/')
    assert r.status_code==200 and '今天，什么值得' in r.text
    assert '/static/styles.css?v=2.1.0rc1' in r.text
    assert 'id="download-report" aria-disabled="true"' in r.text
    assert api.get('/api/snapshot').status_code==404

def test_web_demo_full_page_graph(api):
    d=api.post('/api/demo').json()
    assert d['run_id']=='demo-fixture' and d['is_demo'] and d['schema_version']==2
    assert len(d['entities'])==5 and len(d['platform_signals'])==25
    assert api.get('/api/report').status_code==200
    assert api.get('/api/keywords.csv').headers['content-disposition'].endswith('-validation-keywords.csv"')

def test_repeated_demo_new_snapshot_id(api):
    first=api.post('/api/demo').json();second=api.post('/api/demo').json()
    assert first['run_id']!=second['run_id']
    assert len(api.get('/api/snapshots').json())==2

def record_for(api):
    snapshot=api.post('/api/demo').json();page=snapshot['page_opportunities'][0]
    return {'page_id':page['id'],'game_slug':page['game_slug'],'keyword':page['primary_keyword_hypothesis'],
            'market':snapshot['country'],'language':snapshot['language'],'is_demo':True,'source_run_id':snapshot['run_id']}

def test_validation_roundtrip_and_gate(api):
    record=record_for(api)
    assert api.put('/api/validation',json=record).status_code==200
    assert api.get('/api/validation').json()[0]['stage']=='pending_semrush'
    assert api.put('/api/validation',json={**record,'decision':'build'}).status_code==422

def test_validation_cannot_reassign_market_or_fake_page(api):
    record=record_for(api)
    assert api.put('/api/validation',json={**record,'market':'GB'}).status_code==422
    assert api.put('/api/validation',json={**record,'page_id':'unknown'}).status_code==404

def test_validation_manual_completion(api):
    record=record_for(api)
    checked=(utc_now()-timedelta(minutes=10)).isoformat()
    record.update(stage='validated',decision='build',decision_reason='Manual gap analysis',semrush_volume=1200,
        semrush_evidence='US exact keyword export',semrush_checked_at=checked,serp_checked_at=checked,
        serp_urls=['https://a.example.com/1','https://b.example.com/2','https://c.example.com/3'],serp_notes='Three results inspected for intent and coverage')
    assert api.put('/api/validation',json=record).status_code==200
    projected=api.get('/api/snapshot').json()
    assert next(p for p in projected['page_opportunities'] if p['id']==record['page_id'])['validation_status']=='validated'
    # Source file is still the original needs_validation snapshot.
    original=api.app.state.store.load_snapshot(record['source_run_id'])
    assert next(p for p in original.page_opportunities if p.id==record['page_id']).validation_status=='needs_validation'

def test_source_readiness_not_fake_ok_or_secrets(api):
    data=api.get('/api/sources').json()
    assert all(c['status']!='ok' for c in data['configuration'])
    assert 'client_secret' not in json.dumps(data) and 'api_key' not in json.dumps(data)

@pytest.mark.parametrize('path',['/api/demo','/api/scan'])
def test_csrf_protected(api,path):
    r=api.post(path,json={},headers={'Origin':'https://evil.example'})
    assert r.status_code==403

def test_dns_rebinding_host_rejected(api):
    assert api.get('/api/sources',headers={'Host':'evil.example'}).status_code==400

def test_security_headers_and_no_inline_scripts(api):
    r=api.get('/')
    assert "script-src 'self'" in r.headers['content-security-policy']
    assert '<script>' not in r.text

@pytest.mark.parametrize('payload',[{'limit':31},{'deep':31},{'discovery_limit':101},{'deep':-1}])
def test_scan_budget_bounds(api,payload):
    assert api.post('/api/scan',json=payload).status_code==422

def test_compare_missing_or_same(api):
    d=api.post('/api/demo').json()
    assert api.get('/api/compare',params={'current_run_id':d['run_id'],'baseline_run_id':d['run_id']}).status_code==422
    assert api.get('/api/compare',params={'current_run_id':'unknown'}).status_code==404

def test_compare_auto_baseline(api):
    a=api.post('/api/demo').json();b=api.post('/api/demo').json()
    r=api.get('/api/compare',params={'current_run_id':b['run_id']})
    assert r.status_code==200 and r.json()['baseline_run_id']==a['run_id']

def test_report_selected_snapshot(api):
    a=api.post('/api/demo').json();api.post('/api/demo')
    r=api.get('/api/report',params={'run_id':a['run_id']})
    assert a['run_id'] in r.headers['content-disposition'] and 'WHY THIS PAGE EXISTS' in r.text

def test_health_and_idle(api):
    assert api.get('/health').json()['status']=='ok'
    assert not api.get('/api/status').json()['running']
