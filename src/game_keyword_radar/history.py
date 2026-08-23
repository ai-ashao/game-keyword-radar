from __future__ import annotations

from game_keyword_radar.models import (
    GameCandidate,
    GameSnapshotChange,
    Opportunity,
    OpportunitySnapshotChange,
    ScanSnapshot,
    SnapshotComparison,
)


def _difference(current: int | float | None, baseline: int | float | None):
    if current is None or baseline is None:
        return None
    return current - baseline


def _game_change(
    current: GameCandidate | None, baseline: GameCandidate | None
) -> GameSnapshotChange:
    game = current or baseline
    assert game is not None
    if baseline is None:
        change = "new"
    elif current is None:
        change = "removed"
    else:
        change = "changed"
    signal_delta = _difference(
        current.game_signal_score if current else None,
        baseline.game_signal_score if baseline else None,
    )
    return GameSnapshotChange(
        app_id=game.app_id,
        game_name=game.name,
        change=change,
        current_players=current.current_players if current else None,
        baseline_players=baseline.current_players if baseline else None,
        player_delta=_difference(
            current.current_players if current else None,
            baseline.current_players if baseline else None,
        ),
        current_rank=current.steam_rank if current else None,
        baseline_rank=baseline.steam_rank if baseline else None,
        rank_delta=_difference(
            current.steam_rank if current else None,
            baseline.steam_rank if baseline else None,
        ),
        current_signal=current.game_signal_score if current else None,
        baseline_signal=baseline.game_signal_score if baseline else None,
        signal_delta=round(signal_delta, 1) if signal_delta is not None else None,
    )


def _opportunity_change(
    current: Opportunity | None, baseline: Opportunity | None
) -> OpportunitySnapshotChange:
    opportunity = current or baseline
    assert opportunity is not None
    score_delta = _difference(
        current.score if current else None,
        baseline.score if baseline else None,
    )
    if baseline is None:
        change = "new"
    elif current is None:
        change = "removed"
    elif score_delta and score_delta > 0:
        change = "rising"
    else:
        change = "falling"
    return OpportunitySnapshotChange(
        opportunity_id=opportunity.id,
        app_id=opportunity.app_id,
        game_name=opportunity.game_name,
        keyword=opportunity.keyword.keyword,
        cluster=opportunity.keyword.cluster,
        page_type=opportunity.keyword.page_type,
        change=change,
        current_score=current.score if current else None,
        baseline_score=baseline.score if baseline else None,
        score_delta=round(score_delta, 1) if score_delta is not None else None,
    )


def compare_snapshots(current: ScanSnapshot, baseline: ScanSnapshot) -> SnapshotComparison:
    current_games = {game.app_id: game for game in current.games}
    baseline_games = {game.app_id: game for game in baseline.games}
    game_changes: list[GameSnapshotChange] = []
    for app_id in sorted(current_games.keys() | baseline_games.keys()):
        current_game = current_games.get(app_id)
        baseline_game = baseline_games.get(app_id)
        if current_game is not None and baseline_game is not None:
            unchanged = (
                current_game.current_players == baseline_game.current_players
                and current_game.steam_rank == baseline_game.steam_rank
                and current_game.game_signal_score == baseline_game.game_signal_score
            )
            if unchanged:
                continue
        game_changes.append(_game_change(current_game, baseline_game))

    current_opportunities = {item.id: item for item in current.opportunities}
    baseline_opportunities = {item.id: item for item in baseline.opportunities}
    opportunity_changes: list[OpportunitySnapshotChange] = []
    for opportunity_id in sorted(
        current_opportunities.keys() | baseline_opportunities.keys()
    ):
        current_item = current_opportunities.get(opportunity_id)
        baseline_item = baseline_opportunities.get(opportunity_id)
        if (
            current_item is not None
            and baseline_item is not None
            and current_item.score == baseline_item.score
        ):
            continue
        opportunity_changes.append(_opportunity_change(current_item, baseline_item))

    game_priority = {"new": 0, "removed": 1, "changed": 2}
    game_changes.sort(
        key=lambda item: (
            game_priority[item.change],
            -(abs(item.signal_delta) if item.signal_delta is not None else 0),
            item.game_name.lower(),
        )
    )
    opportunity_priority = {"new": 0, "rising": 1, "falling": 2, "removed": 3}
    opportunity_changes.sort(
        key=lambda item: (
            opportunity_priority[item.change],
            -(abs(item.score_delta) if item.score_delta is not None else 0),
            item.keyword.lower(),
        )
    )

    comparable = (
        current.country == baseline.country
        and current.language == baseline.language
        and current.is_demo == baseline.is_demo
    )
    note = (
        "两次快照市场、语言和数据类型一致；变化仅表示本地扫描差异，不代表搜索需求。"
        if comparable
        else "两次快照的市场、语言或示例状态不同，只展示原始差异，不应据此判断趋势。"
    )
    return SnapshotComparison(
        current_run_id=current.run_id,
        baseline_run_id=baseline.run_id,
        current_generated_at=current.generated_at,
        baseline_generated_at=baseline.generated_at,
        comparable=comparable,
        note=note,
        new_games=sum(item.change == "new" for item in game_changes),
        removed_games=sum(item.change == "removed" for item in game_changes),
        changed_games=sum(item.change == "changed" for item in game_changes),
        new_opportunities=sum(item.change == "new" for item in opportunity_changes),
        removed_opportunities=sum(
            item.change == "removed" for item in opportunity_changes
        ),
        rising_opportunities=sum(
            item.change == "rising" for item in opportunity_changes
        ),
        falling_opportunities=sum(
            item.change == "falling" for item in opportunity_changes
        ),
        game_changes=game_changes,
        opportunity_changes=opportunity_changes,
    )
