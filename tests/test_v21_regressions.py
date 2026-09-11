"""Business regressions, not the old score's arithmetic correctness."""
from datetime import timedelta
from game_keyword_radar.config import Settings
from game_keyword_radar.demo import build_demo_snapshot
from game_keyword_radar.models import ScanSnapshot, GameEntity, PageOpportunity
from game_keyword_radar.storage import SnapshotStore
from game_keyword_radar.history_v2 import compare_v2


def test_A34_twitch_only_history_count(tmp_path):
    store = SnapshotStore(Settings(project_root=tmp_path))
    snap = ScanSnapshot(schema_version=2, run_id='twitch-only', country='US', language='english',
        entities=[GameEntity(slug='only', canonical_name='Only', platform_ids={'twitch':'9'})],
        page_opportunities=[PageOpportunity(id='p', game_slug='only', page_type='guide', path='/guide',
          primary_keyword_hypothesis='only guide', user_problem='Observed', page_value='Solve',
          maintenance_level='low', build_difficulty='low', raw_score=40, score=40)])
    store.save_snapshot(snap)
    summary = store.list_snapshots()[0]
    assert (summary.games_count, summary.opportunities_count) == (1, 1)


def test_A35_identical_games_unchanged(tmp_path):
    old = build_demo_snapshot(Settings(project_root=tmp_path))
    new = old.model_copy(deep=True)
    new.run_id = 'unchanged-copy'
    new.generated_at += timedelta(hours=2)
    result = compare_v2(new, old)
    assert all(row['change'] == 'unchanged' for row in result['v2_game_changes'])
    assert result['score_changed_games'] == 0
