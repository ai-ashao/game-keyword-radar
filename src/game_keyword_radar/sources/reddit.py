"""Best-effort public RSS. No authentication bypass, proxies or comment-count guesses."""
from __future__ import annotations
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from bs4 import BeautifulSoup
from game_keyword_radar.models import PlatformSignal, EvidenceItem, Confidence, SourceState
from game_keyword_radar.sources.base import HttpProvider, missing, safe_error
from game_keyword_radar.sources.youtube import relevant, INTENT

ATOM = {'a':'http://www.w3.org/2005/Atom'}
QUESTION = re.compile(r'\?|\b(how (?:do|can|to)|where (?:is|are|can)|best|codes?|tier list|builds?|map|locations?|items?|boss|error|not working|stuck|calculator|tracker|calculate|materials?)\b', re.I)

class RedditProvider(HttpProvider):
    name = 'reddit'

    def __init__(self, settings, client=None):
        super().__init__(settings, client)
        self.raw = []

    @staticmethod
    def parse_feed(text, entity, dedicated=False):
        # Prevent unbounded documents/entity declarations even though stdlib doesn't load external DTDs.
        if len(text) > 2_000_000 or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise ValueError('Unsupported RSS document')
        root = ET.fromstring(text)
        result = []
        for entry in root.findall('a:entry', ATOM)[:100]:
            title = entry.findtext('a:title', default='', namespaces=ATOM)
            content = BeautifulSoup(entry.findtext('a:content', default='', namespaces=ATOM), 'html.parser').get_text(' ', strip=True)[:3000]
            if not dedicated and not relevant(entity, title+' '+content): continue
            link = next((x.get('href') for x in entry.findall('a:link', ATOM) if x.get('href','').startswith('https://www.reddit.com/')), None)
            identifier = entry.findtext('a:id', default=link or title, namespaces=ATOM)
            author = entry.findtext('a:author/a:name', default=None, namespaces=ATOM)
            published = entry.findtext('a:published', default=None, namespaces=ATOM) or entry.findtext('a:updated', default=None, namespaces=ATOM)
            try:
                when = datetime.fromisoformat(published.replace('Z','+00:00')) if published else None
                if when and not when.tzinfo: when = None
            except ValueError: when = None
            result.append(EvidenceItem(id='reddit:'+identifier, source='reddit', title=title, text=content,
                url=link, author=author, published_at=when,
                metrics={'question_intent':bool(QUESTION.search(title)), 'comment_count':None}))
        return result

    async def fetch(self, entity):
        subs = list(dict.fromkeys([*entity.subreddits, *self.settings.reddit_subreddits]))[:3]
        evidence, notes, captures = [], [], []
        used_network = False
        for sub in subs:
            if not re.fullmatch(r'[A-Za-z0-9_]{2,40}', sub):
                notes.append('Invalid subreddit ignored')
                continue
            dedicated = sub.casefold() in {s.casefold() for s in entity.subreddits}
            params = {'q':f'"{entity.canonical_name}"', 'restrict_sr':'on', 'sort':'new', 't':'month', 'limit':50}
            url = f'https://www.reddit.com/r/{sub}/new/.rss' if dedicated else f'https://www.reddit.com/r/{sub}/search.rss'
            if dedicated: params = {'limit':50}
            key = [url, params]
            cached = self.cache.get(self.name, key, self.settings.cache_ttl_seconds)
            try:
                if cached:
                    text = cached['payload']['text']
                    self.cache_hits += 1
                    captured = datetime.fromisoformat(cached['captured_at'])
                else:
                    if self.calls >= self.settings.reddit_max_requests:
                        notes.append('Reddit request budget exhausted')
                        break
                    self.calls += 1
                    used_network = True
                    response = await self.client.get(url, params=params)
                    response.raise_for_status()
                    text = response.text
                    # Validate before caching; don't cache a block page or invalid feed.
                    self.parse_feed(text, entity, dedicated)
                    record = self.cache.put(self.name, key, {'text':text})
                    captured = datetime.fromisoformat(record['captured_at'])
                captures.append(captured)
                entries = self.parse_feed(text, entity, dedicated)
                for e in entries: e.captured_at = captured
                evidence.extend(entries)
                self.raw.append({'source':'reddit', 'url':url, 'params':params, 'market':'GLOBAL',
                                 'captured_at':captured.isoformat(), 'status':'ok', 'text':text})
            except Exception as exc:
                notes.append(f'r/{sub}: {safe_error(exc)}')
                # Respect a public endpoint refusal; do not retry via alternate hosts.
                if 'HTTP 429' in notes[-1] or 'HTTP 403' in notes[-1]: break
        evidence = list({e.id:e for e in evidence}.values())
        if not evidence:
            return missing(self.name, entity, 'GLOBAL', SourceState.UNAVAILABLE if notes else SourceState.INSUFFICIENT_DATA,
                           '; '.join(notes) or 'No clearly game-matched posts in the RSS sample')
        questions = [e for e in evidence if e.metrics['question_intent']]
        return PlatformSignal(source=self.name, game_slug=entity.slug, market='GLOBAL',
            captured_at=min(captures), evidence=evidence, cache_hit=not used_network,
            status=SourceState.PARTIAL if notes else SourceState.OK, confidence=Confidence.MEDIUM if len(questions)>=3 else Confidence.LOW,
            metrics={'question_count':len(questions), 'unique_authors':len({e.author for e in questions if e.author}),
                'comment_activity':None, 'problem_intent_share':len(questions)/len(evidence),
                'sample_size':len(evidence), 'subreddits':subs, 'sample_only':True},
            notes=notes+['Public RSS sample only; comment activity is unavailable, not zero.',
                         'Dedicated subreddits come from explicit entity configuration; names are not guessed.'])
