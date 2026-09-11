"""Regression contracts from the existing V1/V1.1 repository, exercised against V2.
This file does not replace the repository's original test files.
"""
import json
from datetime import timedelta
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from game_keyword_radar.config import Settings
from game_keyword_radar.models import ScoreBreakdown,SourceStatus,SourceState
from game_keyword_radar.demo import build_demo_snapshot
from game_keyword_radar.history import compare_snapshots
from game_keyword_radar.storage import SnapshotStore
from game_keyword_radar.reporters.markdown import MarkdownReporter
from game_keyword_radar.web.app import create_app

@pytest.fixture
def settings(tmp_path):return Settings(project_root=tmp_path)

def test_legacy_limit_above_30_rejected(settings):
    with pytest.raises(ValidationError):Settings(project_root=settings.project_root,default_limit=31)

def test_directory_contract(settings):
    assert settings.data_dir==settings.project_root/'data'
    assert settings.reports_dir==settings.project_root/'reports'

def test_score_breakdown_sum():
    s=ScoreBreakdown(problem_intensity=20,page_intent=15,feasibility=10,maintenance=5,game_signal=7.5,evidence_confidence=4)
    assert s.total==61.5

def test_score_breakdown_range():
    with pytest.raises(ValidationError):ScoreBreakdown(problem_intensity=26,page_intent=10,feasibility=10,maintenance=5,game_signal=5,evidence_confidence=5)

def test_source_status_defaults():
    assert SourceStatus(source='steam',state=SourceState.OK,message='ok').records==0

def test_optional_skipped_does_not_degrade(settings):
    s=build_demo_snapshot(settings)
    assert any(x.state==SourceState.SKIPPED for x in s.source_statuses) and s.state==SourceState.OK

def test_legacy_raw_score_restored(settings):
    s=build_demo_snapshot(settings);data=s.model_dump(mode='json');data['opportunities'][0].pop('raw_score')
    restored=type(s).model_validate(data)
    assert restored.opportunities[0].raw_score==restored.opportunities[0].score_breakdown.total

def test_roundtrip(settings):
    s=build_demo_snapshot(settings);store=SnapshotStore(settings);path=store.save_snapshot(s)
    assert path.exists() and store.load_latest()==s

def test_raw_payload(settings):
    p=SnapshotStore(settings).save_raw('steam',{'records':[1,2]})
    assert json.loads(p.read_text())['records']==[1,2]

def test_fixture_flags(settings):
    s=build_demo_snapshot(settings)
    assert s.is_demo and s.raw_metadata['dataset']=='fixture'

def test_report_limits_contract(settings):
    report=MarkdownReporter(settings).render(build_demo_snapshot(settings))
    assert '示例数据' in report and '不是搜索量' in report and 'live SERP evidence' in report

def test_report_filename(settings):
    s=build_demo_snapshot(settings);p=MarkdownReporter(settings).save(s)
    assert s.run_id in p.name and p.exists()

def history_pair(settings):
    old=build_demo_snapshot(settings);old.run_id='older-run';new=old.model_copy(deep=True);new.run_id='newer-run'
    new.generated_at=old.generated_at+timedelta(hours=1)
    new.games[0].current_players+=500;new.opportunities[0].score+=1
    store=SnapshotStore(settings);store.save_snapshot(old);store.save_snapshot(new)
    return old,new

def test_history_list_order(settings):
    old,new=history_pair(settings);store=SnapshotStore(settings)
    assert [s.run_id for s in store.list_snapshots()]==['newer-run','older-run']
    assert store.load_snapshot('older-run')==old

def test_invalid_history_ignored(settings):
    store=SnapshotStore(settings);store.ensure_directories()
    (settings.data_dir/'processed'/'broken-snapshot.json').write_text('not-json')
    assert store.list_snapshots()==[] and store.load_snapshot('../latest') is None

def test_mismatched_snapshot_filename_ignored(settings):
    store=SnapshotStore(settings);s=build_demo_snapshot(settings);s.run_id='valid-run';store.save_snapshot(s)
    mismatched=s.model_copy(deep=True);mismatched.run_id='internal-run'
    (settings.data_dir/'processed'/'different-run-snapshot.json').write_text(mismatched.model_dump_json())
    assert [x.run_id for x in store.list_snapshots()]==['valid-run']

def test_legacy_compare_tracks_deltas(settings):
    old,new=history_pair(settings);result=compare_snapshots(new,old)
    assert result.rising_opportunities==1 and result.changed_games==1
    assert result.game_changes[0].player_delta==500

def test_compare_market_warning(settings):
    old,new=history_pair(settings);new.country='GB';result=compare_snapshots(new,old)
    assert not result.comparable and '不应据此判断趋势' in result.note

def test_compare_unchanged_omitted(settings):
    old=build_demo_snapshot(settings);new=old.model_copy(deep=True);new.run_id='another'
    result=compare_snapshots(new,old)
    assert result.game_changes==[] and result.opportunity_changes==[]

def test_compare_falling_score(settings):
    old=build_demo_snapshot(settings);new=old.model_copy(deep=True);new.run_id='lower';new.opportunities[0].score-=2.5
    result=compare_snapshots(new,old)
    assert result.falling_opportunities==1 and result.opportunity_changes[0].score_delta==-2.5

def test_legacy_history_endpoint_contract(settings):
    old,new=history_pair(settings)
    with TestClient(create_app(settings)) as api:
        h=api.get('/api/snapshots').json();c=api.get('/api/compare',params={'current_run_id':new.run_id})
        assert [x['run_id'] for x in h]==['newer-run','older-run']
        assert c.json()['baseline_run_id']==old.run_id and c.json()['rising_opportunities']==1
        assert api.get('/api/snapshots/'+old.run_id).status_code==200

def test_oldest_auto_compare_404(settings):
    old,new=history_pair(settings)
    with TestClient(create_app(settings)) as api:
        assert api.get('/api/compare',params={'current_run_id':old.run_id}).status_code==404
        assert api.get('/api/report',params={'run_id':old.run_id}).status_code==200
