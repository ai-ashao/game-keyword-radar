from __future__ import annotations

from datetime import date

from game_keyword_radar.analyzers.game_profile import enrich_game_profile
from game_keyword_radar.analyzers.keywords import generate_keywords
from game_keyword_radar.analyzers.scoring import build_opportunities, score_game
from game_keyword_radar.config import Settings
from game_keyword_radar.models import GameCandidate, ScanSnapshot, SourceState, SourceStatus


def build_demo_snapshot(settings: Settings) -> ScanSnapshot:
    """Build clearly-labelled fixture data for visual onboarding and tests."""

    games = [
        GameCandidate(
            app_id="demo-001",
            name="Frontier Forge",
            discovery_sources=["fixture"],
            discovery_ranks={"fixture": 1},
            steam_rank=1,
            release_date=date.today(),
            current_players=38_400,
            reviews_total=12_800,
            genres=["Survival", "Open World", "Crafting"],
            categories=["Online Co-op", "Steam Workshop"],
            short_description="Fixture: gather resources, craft gear, build bases and explore.",
            image_url="https://placehold.co/920x430/14323b/d8fff7?text=Fixture+Game",
            store_url="https://store.steampowered.com/",
        ),
        GameCandidate(
            app_id="demo-002",
            name="Signal Tactics",
            discovery_sources=["fixture"],
            discovery_ranks={"fixture": 2},
            steam_rank=2,
            release_date=date.today(),
            current_players=9_800,
            reviews_total=4_300,
            genres=["Strategy", "Simulation", "RPG"],
            categories=["Single-player"],
            short_description="Fixture: manage production, plan squads and tune character builds.",
            image_url="https://placehold.co/920x430/1b253f/e9edff?text=Fixture+Game",
            store_url="https://store.steampowered.com/",
        ),
        GameCandidate(
            app_id="demo-003",
            name="The Glass Archive",
            discovery_sources=["fixture"],
            discovery_ranks={"fixture": 3},
            steam_rank=3,
            release_date=date.today(),
            current_players=1_900,
            reviews_total=820,
            genres=["Puzzle", "Adventure", "Mystery"],
            categories=["Single-player"],
            short_description="Fixture: solve linked puzzles and discover multiple endings.",
            image_url="https://placehold.co/920x430/382337/fff0fb?text=Fixture+Game",
            store_url="https://store.steampowered.com/",
        ),
    ]
    opportunities = []
    for game in games:
        enrich_game_profile(game)
        score_game(game, len(games))
        opportunities.extend(build_opportunities(game, generate_keywords(game)))
    opportunities.sort(key=lambda item: (-item.score, item.keyword.keyword))
    return ScanSnapshot(
        run_id="demo-fixture",
        country=settings.country,
        language=settings.language,
        is_demo=True,
        source_statuses=[
            SourceStatus(
                source="fixture",
                state=SourceState.OK,
                message="Synthetic onboarding data; not current platform facts.",
                records=len(games),
            ),
            SourceStatus(
                source="google_trends",
                state=SourceState.SKIPPED,
                message="Optional Trends collection was disabled for the fixture.",
            ),
        ],
        games=games,
        opportunities=opportunities,
        raw_metadata={"dataset": "fixture", "purpose": "dashboard onboarding"},
    )
