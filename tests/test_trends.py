from __future__ import annotations

from game_keyword_radar.collectors.trends import TrendsCollector
from game_keyword_radar.config import Settings
from game_keyword_radar.models import GameCandidate, SourceState


def sample_game() -> GameCandidate:
    return GameCandidate(
        app_id="1",
        name="Example",
        store_url="https://store.steampowered.com/app/1/",
    )


async def test_trends_disabled_is_skipped(tmp_path):
    games, status = await TrendsCollector(Settings(project_root=tmp_path)).enrich(
        [sample_game()], enabled=False
    )
    assert len(games) == 1
    assert status.state == SourceState.SKIPPED


async def test_trends_missing_extra_is_unavailable(tmp_path, monkeypatch):
    collector = TrendsCollector(Settings(project_root=tmp_path))
    monkeypatch.setattr(collector, "available", lambda: False)
    _, status = await collector.enrich([sample_game()], enabled=True)
    assert status.state == SourceState.UNAVAILABLE
