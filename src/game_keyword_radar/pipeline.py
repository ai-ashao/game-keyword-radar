from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from game_keyword_radar.analyzers.game_profile import enrich_game_profile
from game_keyword_radar.analyzers.keywords import generate_keywords
from game_keyword_radar.analyzers.scoring import build_opportunities, score_game
from game_keyword_radar.collectors.steam import SteamCollector
from game_keyword_radar.collectors.trends import TrendsCollector
from game_keyword_radar.config import Settings
from game_keyword_radar.models import ScanSnapshot
from game_keyword_radar.reporters.markdown import MarkdownReporter
from game_keyword_radar.storage import SnapshotStore


class Scanner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = SnapshotStore(settings)
        self.reporter = MarkdownReporter(settings)

    async def run(self, *, limit: int | None = None, with_trends: bool | None = None) -> ScanSnapshot:
        requested_limit = limit if limit is not None else self.settings.default_limit
        if not 1 <= requested_limit <= 30:
            raise ValueError("limit must be between 1 and 30")
        trends_enabled = (
            with_trends if with_trends is not None else self.settings.trends_enabled
        )
        run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        run_id = f"{run_id}-{uuid4().hex[:6]}"

        async with SteamCollector(self.settings) as collector:
            steam = await collector.collect(requested_limit)
        self.store.save_raw("steam", steam.raw)

        games = [enrich_game_profile(game) for game in steam.games]
        games, trends_status = await TrendsCollector(self.settings).enrich(
            games, enabled=trends_enabled
        )
        opportunities = []
        for game in games:
            score_game(game, max(1, len(games)))
            opportunities.extend(build_opportunities(game, generate_keywords(game)))
        opportunities.sort(key=lambda item: (-item.score, item.keyword.keyword))

        snapshot = ScanSnapshot(
            run_id=run_id,
            country=self.settings.country,
            language=self.settings.language,
            source_statuses=[*steam.statuses, trends_status],
            games=games,
            opportunities=opportunities,
            errors=steam.errors,
            raw_metadata={
                "requested_limit": requested_limit,
                "trends_enabled": trends_enabled,
                "steam_raw_saved": True,
            },
        )
        self.store.save_snapshot(snapshot)
        self.reporter.save(snapshot)
        return snapshot
