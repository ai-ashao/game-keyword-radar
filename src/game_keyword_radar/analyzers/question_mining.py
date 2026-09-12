"""Deterministic task-level question/content-intent clustering, without an LLM."""
from __future__ import annotations
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
    'errors': ('Errors / troubleshooting', r'\b(error|not working|crash(?:es|ing)?|stuck|fix|failed to|cannot|can\'t)\b'),
    'walkthrough': ('Walkthrough / puzzle solutions', r'\b(walkthrough|puzzle solutions?|solve (?:the|this) puzzle|all endings)\b'),
    'guide': ('Beginner questions', r'\b(beginner guide|how (?:do I|can I|to)|tutorial|getting started)\b'),
}

TASK_RULES = {
    'errors': [
        ('startup-crash', r'\b(start(?:up|ing| launch)?|launch).{0,30}\b(crash|error|failed)|\bcrash(?:es|ing)?\b'),
        ('microphone', r'\b(mic|microphone|voice chat|voice input)\b'),
        ('audio', r'\b(no sound|sound not working|audio|speaker)\b'),
        ('multiplayer', r'\b(multiplayer|co-?op|matchmaking|connect(?:ion)?|server)\b'),
        ('download-stuck', r'\b(download|install|update).{0,30}\b(stuck|failed|error|not working)\b'),
    ],
    'locations': [('boss', r'\bboss\b'), ('resource', r'\b(resource|node|ore|material)\b'),
                  ('item', r'\b(item|weapon|armor|key)\b'), ('npc', r'\bnpc\b')],
    'calculator': [('damage', r'\bdamage\b'), ('drop-rate', r'\bdrop (?:rate|chance)\b'),
                   ('resource', r'\b(resource|material|how many)\b'), ('crafting', r'\bcraft')],
    'walkthrough': [('all-endings', r'\ball endings?\b'), ('puzzle', r'\bpuzzle\b')],
    'builds': [('loadout', r'\bloadout\b'), ('skill-tree', r'\bskill tree\b'), ('build', r'\bbuild')],
}

def _task_key(intent: str, title: str) -> str:
    for key, pattern in TASK_RULES.get(intent, []):
        if re.search(pattern, title, re.I):
            return key
    return intent


def mine_questions(entity, signals):
    buckets = {}
    unique = {}
    for signal in signals:
        if signal.game_slug != entity.slug or signal.source not in {'reddit','youtube','trends','manual'}:
            continue
        for item in signal.evidence:
            if item.is_inference:
                continue
            unique[(item.source, item.id)] = item
    ordered = sorted(unique.values(), key=lambda e: (e.source not in {'reddit','manual'}, e.id))
    seen_titles = set()
    for item in ordered:
        title_key = re.sub(r'\W+', ' ', item.title.casefold()).strip()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        text = item.title
        for intent, (_, pattern) in RULES.items():
            if intent == 'codes' and re.search(r'\b(error|source|programming) codes?\b', text, re.I):
                continue
            if item.metrics.get('intent') == intent or re.search(pattern, text, re.I):
                task = _task_key(intent, text)
                buckets.setdefault((intent, task), []).append(item)
                break
    clusters = []
    for (intent, task), examples in buckets.items():
        sources = {e.source for e in examples}
        authors = {e.author for e in examples if e.author}
        confidence = Confidence.HIGH if len(sources)>=2 and len(examples)>=3 else Confidence.MEDIUM if len(examples)>=2 else Confidence.LOW
        label = RULES[intent][0] if task == intent else f"{RULES[intent][0]} · {task.replace('-', ' ')}"
        clusters.append(QuestionCluster(id=f'{entity.slug}:{intent}:{task}', game_slug=entity.slug, cluster_name=label,
            intent=intent, examples=examples, source_count=len(sources), question_count=sum(e.source in {'reddit','manual'} for e in examples),
            content_proxy_count=sum(e.source not in {'reddit','manual'} for e in examples), unique_authors=len(authors), confidence=confidence))
    return sorted(clusters, key=lambda c:(-c.question_count, -c.content_proxy_count, c.intent, c.id))
