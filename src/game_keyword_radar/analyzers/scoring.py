from __future__ import annotations

import hashlib
import math
from datetime import date

from game_keyword_radar.models import (
    Confidence,
    GameCandidate,
    KeywordCandidate,
    Opportunity,
    OpportunityStatus,
    ScoreBreakdown,
)


def _log_score(value: int | None, cap: int, points: float) -> float:
    if value is None or value <= 0:
        return 0.0
    return min(points, points * math.log10(value + 1) / math.log10(cap + 1))


def score_game(game: GameCandidate, candidate_count: int) -> float:
    rank_points = 0.0
    if game.steam_rank is not None:
        denominator = max(1, candidate_count - 1)
        rank_points = 30 * max(0, 1 - (game.steam_rank - 1) / denominator)
    player_points = _log_score(game.current_players, 1_000_000, 25)
    review_points = _log_score(game.reviews_total, 1_000_000, 20)
    release_points = 0.0
    if game.release_date:
        days = (date.today() - game.release_date).days
        if days < 0:
            release_points = 8
        elif days <= 30:
            release_points = 15
        elif days <= 90:
            release_points = 12
        elif days <= 365:
            release_points = 8
        else:
            release_points = 3
    confidence_points = {
        Confidence.HIGH: 10,
        Confidence.MEDIUM: 6,
        Confidence.LOW: 2,
    }[game.understanding_confidence]
    present = sum(
        value is not None
        for value in (game.steam_rank, game.current_players, game.reviews_total, game.release_date)
    )
    game.data_completeness = round((present + bool(game.mechanics)) / 5, 2)
    game.game_signal_score = round(
        rank_points + player_points + review_points + release_points + confidence_points,
        1,
    )
    return game.game_signal_score


def _page_scores(keyword: KeywordCandidate) -> tuple[float, float, float, float]:
    problem = {
        "calculation": 25,
        "navigation": 23,
        "troubleshooting": 22,
        "compatibility": 24,
        "status": 21,
        "solution": 20,
        "planning": 22,
        "reference": 17,
        "completion": 16,
        "advice": 14,
    }.get(keyword.intent, 12)
    page_intent = {"tool": 20, "tracker": 19, "database": 17, "guide": 13}.get(
        keyword.page_type, 10
    )
    feasibility = {"low": 20, "medium": 15, "high": 8}.get(
        keyword.build_difficulty, 10
    )
    maintenance = {"low": 10, "medium": 7, "high": 3}.get(
        keyword.maintenance_level, 5
    )
    return problem, page_intent, feasibility, maintenance


def _opportunity_id(app_id: str, keyword: str) -> str:
    digest = hashlib.sha1(f"{app_id}:{keyword}".encode(), usedforsecurity=False).hexdigest()
    return digest[:12]


def build_opportunities(game: GameCandidate, keywords: list[KeywordCandidate]) -> list[Opportunity]:
    opportunities: list[Opportunity] = []
    for keyword in keywords:
        problem, page_intent, feasibility, maintenance = _page_scores(keyword)
        breakdown = ScoreBreakdown(
            problem_intensity=problem,
            page_intent=page_intent,
            feasibility=feasibility,
            maintenance=maintenance,
            game_signal=round(game.game_signal_score * 0.15, 1),
            evidence_confidence=(
                8 if game.understanding_confidence == Confidence.HIGH else 5
                if game.understanding_confidence == Confidence.MEDIUM
                else 2
            ),
        )
        # Preserve the relative ranking while reserving the final 31 points for
        # demand and SERP validation that V1 does not automate.
        score = round(breakdown.total * 0.69, 1)
        if game.understanding_confidence == Confidence.LOW:
            score = min(score, 59.0)
        status = OpportunityStatus.NEEDS_VALIDATION if score >= 45 else OpportunityStatus.WATCH
        missing = ["live SERP evidence", "reliable search-volume metric"]
        if game.trend is None or game.trend.state.value != "ok":
            missing.append("Google Trends direction")
        risks = [
            "Keyword was generated from Steam metadata, not observed search demand.",
            "Existing tools and current SERP intent have not been verified.",
        ]
        if game.understanding_confidence == Confidence.LOW:
            risks.append("Game mechanics understanding is low confidence.")
        opportunities.append(
            Opportunity(
                id=_opportunity_id(game.app_id, keyword.keyword),
                app_id=game.app_id,
                game_name=game.name,
                game_image_url=game.image_url,
                keyword=keyword,
                raw_score=breakdown.total,
                score=round(score, 1),
                score_breakdown=breakdown,
                status=status,
                missing_evidence=missing,
                risks=risks,
                next_steps=[
                    f"Search {keyword.keyword!r} in the target market and classify the top 10 results.",
                    "Confirm the game mechanic in official documentation or gameplay evidence.",
                    "Estimate the smallest useful page or tool before implementation.",
                ],
            )
        )
    return sorted(opportunities, key=lambda item: (-item.score, item.keyword.keyword))
