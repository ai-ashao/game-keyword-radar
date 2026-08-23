from __future__ import annotations

from dataclasses import dataclass
import re

from game_keyword_radar.models import Confidence, GameCandidate, KeywordCandidate


@dataclass(frozen=True, slots=True)
class Pattern:
    mechanic: str
    suffix: str
    cluster: str
    page_type: str
    intent: str
    difficulty: str
    maintenance: str
    rationale: str


PATTERNS: tuple[Pattern, ...] = (
    Pattern("rpg_builds", "build planner", "Build planning", "tool", "planning", "high", "medium", "RPG systems often create repeated build decisions."),
    Pattern("rpg_builds", "skill tree", "Skill tree", "database", "reference", "medium", "medium", "Players need a structured view of skills and unlocks."),
    Pattern("rpg_builds", "damage calculator", "Damage calculation", "tool", "calculation", "high", "high", "Stat-heavy RPG combat can support a calculation tool."),
    Pattern("crafting", "crafting calculator", "Crafting", "tool", "calculation", "medium", "medium", "Crafting loops create quantity and dependency questions."),
    Pattern("crafting", "recipe database", "Recipes", "database", "reference", "medium", "high", "Recipe discovery is a repeated lookup need."),
    Pattern("crafting", "resource calculator", "Resources", "tool", "calculation", "medium", "medium", "Resource planning can be reduced to repeatable inputs."),
    Pattern("open_world", "interactive map", "Map", "tool", "navigation", "high", "high", "Exploration games create location and completion needs."),
    Pattern("open_world", "item locations", "Map", "guide", "navigation", "medium", "high", "Location queries can support the same map cluster."),
    Pattern("strategy_economy", "profit calculator", "Economy", "tool", "calculation", "medium", "medium", "Management systems create optimization questions."),
    Pattern("strategy_economy", "production calculator", "Production", "tool", "calculation", "high", "medium", "Production chains benefit from deterministic planning."),
    Pattern("strategy_economy", "upgrade priority", "Progression", "guide", "advice", "low", "high", "Players compare upgrades and progression order."),
    Pattern("puzzles", "walkthrough", "Walkthrough", "guide", "solution", "medium", "high", "Puzzle progress creates direct solution intent."),
    Pattern("puzzles", "puzzle solutions", "Walkthrough", "guide", "solution", "medium", "high", "Individual puzzle answers belong to a walkthrough cluster."),
    Pattern("puzzles", "all endings", "Endings", "guide", "completion", "low", "medium", "Branching outcomes create completion queries."),
    Pattern("combat_loadouts", "weapon database", "Weapons", "database", "reference", "medium", "high", "Combat games often need comparable weapon stats."),
    Pattern("combat_loadouts", "best settings", "Performance", "guide", "troubleshooting", "low", "medium", "Performance and control tuning is a recurring need."),
    Pattern("multiplayer", "player count", "Player activity", "tracker", "status", "low", "low", "Players often check activity before investing time."),
    Pattern("live_service", "server status", "Server status", "tracker", "status", "medium", "high", "Persistent online services create repeated outage and availability checks."),
    Pattern("mods", "mod compatibility", "Mods", "database", "compatibility", "high", "high", "Workshop support creates version compatibility questions."),
    Pattern("mods", "mod load order", "Mods", "guide", "troubleshooting", "medium", "high", "Mod combinations create configuration problems."),
)


def _supporting_keywords(game_name: str, pattern: Pattern) -> list[str]:
    suffix = pattern.suffix
    variants = [f"{game_name} {suffix}"]
    if "calculator" in suffix:
        variants.append(f"{game_name} {suffix.replace('calculator', 'planner')}")
    elif "database" in suffix:
        variants.append(f"{game_name} {suffix.replace('database', 'wiki')}")
    elif suffix == "interactive map":
        variants.extend([f"{game_name} map", f"{game_name} locations map"])
    elif suffix == "walkthrough":
        variants.append(f"{game_name} complete guide")
    return list(dict.fromkeys(item.lower() for item in variants))


def _query_name(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[™®©]", "", name)).strip()


def generate_keywords(game: GameCandidate) -> list[KeywordCandidate]:
    candidates: list[KeywordCandidate] = []
    query_name = _query_name(game.name)
    for pattern in PATTERNS:
        if pattern.mechanic not in game.mechanics:
            continue
        candidates.append(
            KeywordCandidate(
                keyword=f"{query_name} {pattern.suffix}".lower(),
                supporting_keywords=_supporting_keywords(query_name, pattern),
                cluster=pattern.cluster,
                page_type=pattern.page_type,
                intent=pattern.intent,
                trigger=pattern.mechanic,
                rationale=pattern.rationale,
                build_difficulty=pattern.difficulty,
                maintenance_level=pattern.maintenance,
                evidence_confidence=(
                    Confidence.MEDIUM
                    if game.understanding_confidence == Confidence.HIGH
                    else Confidence.LOW
                ),
            )
        )
    # Keep one canonical page candidate per cluster/page type while retaining variants.
    deduped: dict[tuple[str, str], KeywordCandidate] = {}
    for candidate in candidates:
        key = (candidate.cluster.lower(), candidate.page_type)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = candidate
        else:
            existing.supporting_keywords = list(
                dict.fromkeys(existing.supporting_keywords + candidate.supporting_keywords)
            )
    return list(deduped.values())
