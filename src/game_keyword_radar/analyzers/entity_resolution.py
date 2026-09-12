from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher

from game_keyword_radar.models import GameCandidate, GameEntity, utc_now
from game_keyword_radar.research_models import ReleaseDateEvidence


def normalized(name: str) -> str:
    name = unicodedata.normalize("NFKC", re.sub("[™®©]", "", name)).casefold()
    return re.sub(r"[^\w]+", " ", name, flags=re.UNICODE).strip()


def slugify(name: str) -> str:
    slug = normalized(name).replace(" ", "-")
    return slug or "game-" + hashlib.sha256(name.encode()).hexdigest()[:10]


class EntityResolver:
    """Conservative platform entity resolver.

    V2.2 rule: same platform id is authoritative. Name-only equality across platforms is a
    review suggestion, not an automatic merge. Verified cross-platform merges belong in
    entity_overrides, where both platform IDs are explicitly recorded.
    """
    def __init__(self, existing: list[GameEntity] | None = None, overrides: list[dict] | None = None, *, as_of=None):
        self.as_of = as_of or utc_now()
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
                found.needs_review = False
                found.match_method = "manual_override"
                for field in ("subreddits", "youtube_queries", "trends_terms", "mechanics"):
                    if getattr(entity, field):
                        setattr(found, field, getattr(entity, field))
            else:
                entity.match_method = "manual_override"
                entity.needs_review = False
                self.entities.append(entity)

    def resolve(self, name: str, platform: str, platform_id: str) -> GameEntity:
        platform_id = str(platform_id)
        match = next((e for e in self.entities if e.platform_ids.get(platform) == platform_id), None)
        method, confidence = "platform_id", 1.0
        # A different ID on the same platform is also a hard identity conflict.  Names and aliases
        # are suggestion-only once a platform ID exists; never overwrite an established ID because
        # two games happen to share a title.
        unresolved_name_matches = []
        if match is None:
            unresolved_name_matches = [e for e in self.entities
                if (normalized(e.canonical_name) == normalized(name)
                    or normalized(name) in {normalized(a) for a in e.aliases})]
            for candidate in self.entities:
                if candidate in unresolved_name_matches:
                    continue
                similarity = SequenceMatcher(None, normalized(name), normalized(candidate.canonical_name)).ratio()
                if similarity >= .78:
                    self.suggestions.append({"name": name, "platform": platform, "platform_id": platform_id,
                        "candidate_slug": candidate.slug, "similarity": round(similarity,3),
                        "resolution_status": "probable", "applied": False})

        if match is None:
            slug = slugify(name)
            if any(e.slug == slug for e in self.entities):
                slug += "-" + hashlib.sha256(f"{platform}:{platform_id}".encode()).hexdigest()[:8]
            match = GameEntity(canonical_name=name, slug=slug)
            self.entities.append(match)
            method, confidence = "new", 1.0
            if unresolved_name_matches:
                match.needs_review = True
                same_platform_conflict = any(platform in candidate.platform_ids for candidate in unresolved_name_matches)
                match.match_method = "unresolved_platform_id_conflict" if same_platform_conflict else "unresolved_cross_platform_name"
                match.entity_match_confidence = min(match.entity_match_confidence, 0.5)
                for candidate in unresolved_name_matches:
                    reason = "same_platform_different_id" if platform in candidate.platform_ids else "cross_platform_name_only"
                    self.suggestions.append({"name": name, "platform": platform, "platform_id": platform_id,
                        "candidate_slug": candidate.slug, "similarity": 1.0,
                        "resolution_status": "unresolved_entity", "reason": reason,
                        "applied": False})

        match.first_seen_at = match.first_seen_at or self.as_of
        match.first_seen_by_source.setdefault(platform, self.as_of)
        match.platform_ids[platform] = platform_id
        if method != "new" or not unresolved_name_matches:
            match.match_method = method
            match.entity_match_confidence = min(match.entity_match_confidence, confidence)
        if name != match.canonical_name and name not in match.aliases:
            match.aliases.append(name)
        return match

    def from_steam(self, game: GameCandidate) -> GameEntity:
        entity = self.resolve(game.name, "steam", game.app_id)
        entity.discovery_sources = list(dict.fromkeys(entity.discovery_sources + game.discovery_sources))
        entity.discovery_ranks.update(game.discovery_ranks)
        entity.is_game = game.app_type in {"game", "demo"} if game.app_type else entity.is_game
        prior_stage = entity.release_stage
        if game.release_stage != "unknown":
            entity.release_stage = game.release_stage
        if prior_stage == "early_access" and game.release_stage == "released":
            event = {"kind": "early_access_exit", "source_url": str(game.store_url),
                     "observed_at": self.as_of.isoformat()}
            if not any(x.get("kind") == "early_access_exit" for x in entity.release_events):
                entity.release_events.append(event)
        if game.release_date:
            incoming = ReleaseDateEvidence(
                date=game.release_date, raw_text=game.release_date_raw or game.release_date.isoformat(),
                precision=game.release_date_precision, source="steam", source_url=game.store_url,
                checked_at=game.metadata_captured_at or game.collected_at)
            previous = entity.platform_release_dates.get("steam")
            retain_old = (previous and previous.date and previous.source_url
                          and previous.precision == "day" and previous.date < game.release_date)
            if retain_old:
                event = {"kind": "platform_date_changed", "old_date": previous.date.isoformat(),
                         "reported_date": game.release_date.isoformat(), "source_url": str(game.store_url),
                         "observed_at": self.as_of.isoformat()}
                if not any(x.get("reported_date") == event["reported_date"] and
                           x.get("kind") == event["kind"] for x in entity.release_events):
                    entity.release_events.append(event)
                entity.release_date = previous.date
            else:
                entity.platform_release_dates["steam"] = incoming
                entity.release_date = game.release_date
        if game.release_stage == "demo" and not any(x.get("kind") == "demo" for x in entity.release_events):
            entity.release_events.append({"kind": "demo", "source_url": str(game.store_url)})
        if game.genres:
            entity.genres = game.genres
        if game.categories:
            entity.categories = game.categories
        entity.mechanics = list(dict.fromkeys(entity.mechanics + game.mechanics))
        if game.genres or game.categories or game.mechanics:
            entity.understanding_confidence = game.understanding_confidence
        return entity
