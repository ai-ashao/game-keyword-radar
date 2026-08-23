from __future__ import annotations

from datetime import timedelta

from game_keyword_radar.config import Settings
from game_keyword_radar.demo import build_demo_snapshot
from game_keyword_radar.history import compare_snapshots


def snapshot_pair(tmp_path):
    baseline = build_demo_snapshot(Settings(project_root=tmp_path)).model_copy(deep=True)
    baseline.run_id = "baseline-run"
    current = baseline.model_copy(deep=True)
    current.run_id = "current-run"
    current.generated_at = baseline.generated_at + timedelta(days=1)

    current.games[0].current_players += 1_600
    current.games[0].steam_rank = 2
    current.games[0].game_signal_score += 2.5
    current.opportunities[0].score += 1.5

    removed_app_id = current.games[-1].app_id
    current.games = [game for game in current.games if game.app_id != removed_app_id]
    current.opportunities = [
        item for item in current.opportunities if item.app_id != removed_app_id
    ]

    new_game = baseline.games[1].model_copy(deep=True)
    new_game.app_id = "demo-new"
    new_game.name = "New Fixture Game"
    current.games.append(new_game)
    new_opportunity = baseline.opportunities[1].model_copy(deep=True)
    new_opportunity.id = "new-opportunity"
    new_opportunity.app_id = new_game.app_id
    new_opportunity.game_name = new_game.name
    current.opportunities.append(new_opportunity)
    return current, baseline


def test_compare_snapshots_tracks_additions_removals_and_score_changes(tmp_path):
    current, baseline = snapshot_pair(tmp_path)
    comparison = compare_snapshots(current, baseline)

    assert comparison.comparable is True
    assert comparison.new_games == 1
    assert comparison.removed_games == 1
    assert comparison.changed_games == 1
    assert comparison.new_opportunities == 1
    assert comparison.removed_opportunities > 0
    assert comparison.rising_opportunities == 1
    assert any(item.player_delta == 1_600 for item in comparison.game_changes)
    assert any(item.score_delta == 1.5 for item in comparison.opportunity_changes)


def test_compare_snapshots_flags_mismatched_markets(tmp_path):
    current, baseline = snapshot_pair(tmp_path)
    current.country = "GB"

    comparison = compare_snapshots(current, baseline)

    assert comparison.comparable is False
    assert "不应据此判断趋势" in comparison.note


def test_compare_snapshots_omits_unchanged_items(tmp_path):
    baseline = build_demo_snapshot(Settings(project_root=tmp_path))
    current = baseline.model_copy(deep=True)
    current.run_id = "another-run"

    comparison = compare_snapshots(current, baseline)

    assert comparison.game_changes == []
    assert comparison.opportunity_changes == []


def test_compare_snapshots_tracks_falling_opportunity(tmp_path):
    baseline = build_demo_snapshot(Settings(project_root=tmp_path))
    current = baseline.model_copy(deep=True)
    current.run_id = "lower-score-run"
    current.opportunities[0].score -= 2.5

    comparison = compare_snapshots(current, baseline)

    assert comparison.falling_opportunities == 1
    assert comparison.rising_opportunities == 0
    assert comparison.opportunity_changes[0].change == "falling"
    assert comparison.opportunity_changes[0].score_delta == -2.5
