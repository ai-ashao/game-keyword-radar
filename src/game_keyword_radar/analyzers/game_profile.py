from __future__ import annotations

from game_keyword_radar.models import Confidence, Evidence, GameCandidate


MECHANIC_RULES: dict[str, tuple[str, ...]] = {
    "rpg_builds": ("rpg", "role-playing", "action rpg", "jrpg"),
    "crafting": ("crafting", "survival", "sandbox", "base building"),
    "open_world": ("open world", "exploration"),
    "strategy_economy": ("strategy", "simulation", "management", "city builder"),
    "puzzles": ("puzzle", "escape room", "mystery"),
    "combat_loadouts": ("shooter", "fps", "third-person shooter", "action"),
    "multiplayer": ("multi-player", "multiplayer", "co-op", "mmo", "online pvp"),
    "live_service": ("massively multiplayer", "mmo", "online pvp"),
    "mods": ("mod support", "moddable", "modding", "supports mods"),
}


def enrich_game_profile(game: GameCandidate) -> GameCandidate:
    haystack = " ".join(
        [*game.genres, *game.categories, game.short_description or ""]
    ).lower()
    mechanics = [
        mechanic
        for mechanic, terms in MECHANIC_RULES.items()
        if any(term in haystack for term in terms)
    ]
    unique_signals = len(game.genres) + len(game.categories)
    if len(mechanics) >= 3 and unique_signals >= 5:
        confidence = Confidence.HIGH
    elif mechanics and unique_signals >= 2:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW
    game.mechanics = mechanics
    game.understanding_confidence = confidence
    game.evidence.append(
        Evidence(
            label="Inferred mechanics",
            value=", ".join(mechanics) if mechanics else "none",
            source="rule:steam_genres_categories_description",
            source_url=game.store_url,
            is_inference=True,
        )
    )
    return game
