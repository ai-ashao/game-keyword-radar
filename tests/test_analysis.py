from __future__ import annotations

from datetime import date

from game_keyword_radar.analyzers.game_profile import enrich_game_profile
from game_keyword_radar.analyzers.keywords import generate_keywords
from game_keyword_radar.analyzers.scoring import build_opportunities, score_game
from game_keyword_radar.models import Confidence, GameCandidate, OpportunityStatus


def game(**overrides) -> GameCandidate:
    values = {
        "app_id": "123",
        "name": "Test Game",
        "steam_rank": 1,
        "release_date": date.today(),
        "current_players": 10_000,
        "reviews_total": 5_000,
        "genres": ["Survival", "Open World", "Crafting"],
        "categories": ["Online Co-op", "Steam Workshop"],
        "short_description": "Build a base, craft equipment and explore the world.",
        "store_url": "https://store.steampowered.com/app/123/",
    }
    values.update(overrides)
    return GameCandidate(**values)


def test_game_profile_infers_mechanics_from_steam_metadata():
    candidate = enrich_game_profile(game())
    assert {"crafting", "open_world", "multiplayer"}.issubset(candidate.mechanics)
    assert "mods" not in candidate.mechanics
    assert candidate.understanding_confidence == Confidence.HIGH
    assert candidate.evidence[-1].is_inference is True


def test_game_profile_stays_low_when_metadata_is_empty():
    candidate = enrich_game_profile(game(genres=[], categories=[], short_description=None))
    assert candidate.mechanics == []
    assert candidate.understanding_confidence == Confidence.LOW


def test_keyword_generation_is_mechanic_limited():
    candidate = enrich_game_profile(game())
    keywords = [item.keyword for item in generate_keywords(candidate)]
    assert "test game crafting calculator" in keywords
    assert "test game interactive map" in keywords
    assert not any("damage calculator" in item for item in keywords)


def test_keyword_generation_retains_supporting_variants():
    candidate = enrich_game_profile(game())
    item = next(item for item in generate_keywords(candidate) if item.keyword.endswith("interactive map"))
    assert "test game map" in item.supporting_keywords
    assert "test game locations map" in item.supporting_keywords


def test_game_score_is_bounded_and_tracks_completeness():
    candidate = enrich_game_profile(game())
    score = score_game(candidate, 10)
    assert 0 <= score <= 100
    assert candidate.data_completeness == 1


def test_missing_fields_reduce_game_completeness():
    candidate = enrich_game_profile(
        game(release_date=None, current_players=None, reviews_total=None, genres=[], categories=[], short_description=None)
    )
    score_game(candidate, 10)
    assert candidate.data_completeness < 0.5


def test_opportunity_without_serp_is_capped_at_sixty_nine():
    candidate = enrich_game_profile(game())
    score_game(candidate, 10)
    opportunities = build_opportunities(candidate, generate_keywords(candidate))
    assert opportunities
    assert max(item.score for item in opportunities) <= 69
    assert all(item.score == round(item.raw_score * 0.69, 1) for item in opportunities)
    assert all(item.status == OpportunityStatus.NEEDS_VALIDATION for item in opportunities if item.score >= 45)
    assert all("live SERP evidence" in item.missing_evidence for item in opportunities)


def test_low_confidence_opportunity_is_capped_at_fifty_nine():
    candidate = enrich_game_profile(
        game(
            genres=["Action"],
            categories=[],
            short_description="Fast combat.",
            current_players=900_000,
            reviews_total=900_000,
        )
    )
    assert candidate.understanding_confidence == Confidence.LOW
    score_game(candidate, 2)
    opportunities = build_opportunities(candidate, generate_keywords(candidate))
    assert opportunities
    assert max(item.score for item in opportunities) <= 59


def test_missing_trends_is_evidence_gap_not_zero_demand():
    candidate = enrich_game_profile(game())
    score_game(candidate, 10)
    opportunity = build_opportunities(candidate, generate_keywords(candidate))[0]
    assert "Google Trends direction" in opportunity.missing_evidence
    assert all("zero" not in risk.lower() for risk in opportunity.risks)


def test_trademark_symbol_is_removed_from_query_keyword():
    candidate = enrich_game_profile(game(name="Example™", genres=["Action"]))
    keywords = generate_keywords(candidate)
    assert keywords
    assert all("™" not in item.keyword for item in keywords)
