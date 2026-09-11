"""Explicit local evidence, never silently fetched or presented as platform data."""
from __future__ import annotations
from game_keyword_radar.models import GameAnnotation, EvidenceItem, GameEntity


def apply_annotation(entity: GameEntity, item: GameAnnotation | None, as_of):
    if item is None or item.checked_at > as_of:
        return
    if item.ignored and 'ignored' not in entity.manual_labels:
        entity.manual_labels.append('ignored')
    elif not item.ignored:
        entity.manual_labels = [s for s in entity.manual_labels if s != 'ignored']
    if item.non_game:
        entity.is_game = False
        if 'manual_non_game' not in entity.manual_labels:
            entity.manual_labels.append('manual_non_game')
    elif 'manual_non_game' in entity.manual_labels:
        entity.manual_labels.remove('manual_non_game')
        entity.is_game = None  # Return to unresolved, not automatically confirmed as a game.
    if item.first_public_playable_at:
        entity.first_public_playable_at = item.first_public_playable_at
        entity.release_date_basis = 'manual_verified'
        if item.evidence_url:
            entity.release_sources = list(dict.fromkeys(entity.release_sources + [str(item.evidence_url)]))
    if item.release_stage != "unknown":
        entity.release_stage = item.release_stage
    entity.platform_ids.update(item.platform_ids)
    entity.aliases = list(dict.fromkeys(entity.aliases + item.aliases))


def annotation_evidence(item: GameAnnotation | None, as_of) -> list[EvidenceItem]:
    if not item or not item.intent or not item.evidence_url or item.checked_at > as_of:
        return []
    return [EvidenceItem(id='manual:' + item.game_slug + ':' + item.checked_at.isoformat(),
        source='manual', title=item.reason, text=item.reason, url=item.evidence_url,
        captured_at=item.checked_at, published_at=item.evidence_published_at,
        metrics={'intent': item.intent, 'origin': 'manual', 'question_intent': True})]
