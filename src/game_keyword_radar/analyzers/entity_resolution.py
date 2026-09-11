from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher

from game_keyword_radar.models import GameCandidate, GameEntity


def normalized(name: str) -> str:
    name = unicodedata.normalize("NFKC", re.sub("[™®©]", "", name)).casefold()
    return re.sub(r"[^\w]+", " ", name, flags=re.UNICODE).strip()


def slugify(name: str) -> str:
    slug = normalized(name).replace(" ", "-")
    return slug or "game-" + hashlib.sha256(name.encode()).hexdigest()[:10]


class EntityResolver:
    def __init__(self, existing: list[GameEntity] | None = None, overrides: list[dict] | None = None):
        self.entities = [e.model_copy(deep=True) for e in (existing or [])]
        self.suggestions: list[dict] = []
        for override in overrides or []:
            data = dict(override)
            data.setdefault("slug", slugify(data["canonical_name"]))
            data["platform_ids"] = {k: str(v) for k, v in data.get("platform_ids", {}).items()}
            entity = GameEntity.model_validate(data)
            found = next((e for e in self.entities if e.slug == entity.slug), None)
            if found:
                found.aliases = list(dict.fromkeys(found.aliases + entity.aliases))
                found.platform_ids.update(entity.platform_ids)
                for field in ("subreddits", "youtube_queries", "trends_terms", "mechanics"):
                    if getattr(entity, field):
                        setattr(found, field, getattr(entity, field))
            else:
                self.entities.append(entity)

    def resolve(self, name: str, platform: str, platform_id: str) -> GameEntity:
        platform_id = str(platform_id)
        match = next((e for e in self.entities if e.platform_ids.get(platform) == platform_id), None)
        method, confidence = "platform_id", 1.0
        if match is None:
            candidates = [e for e in self.entities
                          if e.platform_ids.get(platform) in (None, platform_id)]
            exact = [e for e in candidates if e.canonical_name.casefold() == name.casefold()]
            norm = [e for e in candidates if normalized(e.canonical_name) == normalized(name)]
            aliases = [e for e in candidates if normalized(name) in {normalized(a) for a in e.aliases}]
            for group, how, score in [(exact,"exact",1.0),(norm,"normalized",.98),(aliases,"alias",.95)]:
                if len(group) == 1:
                    match, method, confidence = group[0], how, score
                    break
            if match is None:
                for candidate in candidates:
                    similarity = SequenceMatcher(None, normalized(name), normalized(candidate.canonical_name)).ratio()
                    if similarity >= .78:
                        self.suggestions.append({"name": name, "platform": platform, "platform_id": platform_id,
                            "candidate_slug": candidate.slug, "similarity": round(similarity,3),
                            "applied": False})
        if match is None:
            slug = slugify(name)
            if any(e.slug == slug for e in self.entities):
                slug += "-" + hashlib.sha256(f"{platform}:{platform_id}".encode()).hexdigest()[:8]
            match = GameEntity(canonical_name=name, slug=slug)
            self.entities.append(match)
            method, confidence = "new", 1.0
        match.platform_ids[platform] = platform_id
        match.match_method = method
        match.entity_match_confidence = min(match.entity_match_confidence, confidence)
        if name != match.canonical_name and name not in match.aliases:
            match.aliases.append(name)
        return match

    def from_steam(self, game: GameCandidate) -> GameEntity:
        entity = self.resolve(game.name, "steam", game.app_id)
        entity.release_date = game.release_date
        entity.genres = game.genres
        entity.categories = game.categories
        entity.mechanics = list(dict.fromkeys(entity.mechanics + game.mechanics))
        entity.understanding_confidence = game.understanding_confidence
        return entity
