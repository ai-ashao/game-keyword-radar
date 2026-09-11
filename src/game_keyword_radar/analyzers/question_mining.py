"""Deterministic, inspectable question/content-intent clustering, without an LLM."""
from __future__ import annotations
import hashlib
import re
from game_keyword_radar.models import QuestionCluster, Confidence

RULES = {
    'workshop': ('Workshop / SteamCMD issues', r'\b(steamcmd|workshop).{0,60}\b(download|error|stuck|not working|install)|\b(download|error|stuck).{0,60}workshop'),
    'calculator': ('Calculation / material planning', r'\b(calculat(?:or|e|ion)|how many (?:materials|resources|items)|drop (?:rate|chance)|material requirements?|damage formula|crafting costs?)\b'),
    'tracker': ('Progress / resource tracking', r'\b(tracker|track (?:my|your|progress)|checklist|completion progress|resource tracking)\b'),
    'codes': ('Redeem codes', r'\b(redeem|redemption|gift codes?|promo codes?|working codes|new codes|codes list)\b'),
    'tier-list': ('Comparisons / tier lists', r'\b(tier list|best (?:characters?|weapons?|classes|heroes|units)|compare (?:weapons?|characters?))\b'),
    'locations': ('Map / boss / item locations', r'\b(where (?:is|are|can I find)|boss locations?|item locations?|resource nodes?|interactive map|where to find)\b'),
    'builds': ('Builds / loadouts', r'\b(best builds?|build guide|build planner|skill tree|loadouts?)\b'),
    'errors': ('Errors / troubleshooting', r'\b(error|not working|crash(?:es|ing)?|stuck|fix|failed to)\b'),
    'walkthrough': ('Walkthrough / puzzle solutions', r'\b(walkthrough|puzzle solutions?|solve (?:the|this) puzzle|all endings)\b'),
    'guide': ('Beginner questions', r'\b(beginner guide|how (?:do I|can I|to)|tutorial|getting started)\b'),
}

def mine_questions(entity, signals):
    buckets = {}
    unique = {}
    for signal in signals:
        if signal.game_slug != entity.slug or signal.source not in {'reddit','youtube','trends'}: continue
        for item in signal.evidence:
            if item.is_inference: continue
            unique[(item.source, item.id)] = item
    for item in unique.values():
        # Titles are deliberately used instead of unrelated quoted reply/body text.
        text = item.title
        for intent, (_, pattern) in RULES.items():
            if intent == 'codes' and re.search(r'\b(error|source|programming) codes?\b', text, re.I): continue
            if re.search(pattern, text, re.I):
                buckets.setdefault(intent, []).append(item)
                # Specific demand should not also inflate a generic beginner bucket.
                if intent in {'workshop','calculator','tracker','codes','tier-list','locations','builds','walkthrough'}: break
    clusters = []
    for intent, examples in buckets.items():
        sources = {e.source for e in examples}
        authors = {e.author for e in examples if e.author}
        confidence = Confidence.HIGH if len(sources)>=2 and len(examples)>=3 else Confidence.MEDIUM if len(examples)>=2 else Confidence.LOW
        clusters.append(QuestionCluster(id=f'{entity.slug}:{intent}', game_slug=entity.slug, cluster_name=RULES[intent][0],
            intent=intent, examples=examples, source_count=len(sources), question_count=len(examples), unique_authors=len(authors), confidence=confidence))
    return sorted(clusters, key=lambda c:(-c.question_count, c.intent))
