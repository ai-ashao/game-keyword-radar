"""YouTube Data API v3, bounded search calls and cached video statistics.

Counts describe retrieved, relevant videos, NOT the total supply of YouTube videos.
Search call budget is configurable independently of Google's changing quota policy.
"""
from __future__ import annotations
import hashlib
import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo
import fcntl
from game_keyword_radar.models import PlatformSignal, SourceState, Confidence, EvidenceItem, utc_now
from game_keyword_radar.sources.base import HttpProvider, BudgetExceeded, ProviderError, missing
from game_keyword_radar.storage import SnapshotStore

API = 'https://www.googleapis.com/youtube/v3/'
INTENT = re.compile(r'\b(guide|tutorial|how to|builds?|calculator|tracker|codes?|tier list|locations?|walkthrough|best|fix|error|stuck)\b', re.I)

def relevant(entity, title):
    haystack = re.sub(r'[^\w]+', ' ', title.casefold()).strip()
    for alias in [entity.canonical_name, *entity.aliases]:
        name = re.sub(r'[^\w]+', ' ', re.sub('[™®©]', '', alias).casefold()).strip()
        if name and re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', haystack):
            return True
    return False

class YouTubeProvider(HttpProvider):
    name = 'youtube'

    def __init__(self, settings, client=None):
        super().__init__(settings, client)
        self.search_calls = 0
        self.video_calls = 0
        self.raw = []

    @property
    def configured(self):
        return bool(self.settings.youtube_api_key)

    def _reserve_search(self):
        if self.search_calls >= self.settings.youtube_search_budget:
            raise BudgetExceeded('Per-scan YouTube search-call budget exhausted')
        # Count attempts before network I/O. Failed API calls may also consume quota.
        path = self.settings.data_dir / 'budgets' / 'youtube-search.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path.parent / '.youtube.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                ledger = json.loads(path.read_text())
            except FileNotFoundError:
                ledger = {}
            except (ValueError, OSError):
                raise BudgetExceeded('Local YouTube budget ledger is unreadable; repair it before further calls')
            day = datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()
            # The conservative shared local budget covers all configured keys.
            used = ledger.get('used', 0) if ledger.get('day') == day else 0
            if not isinstance(used, int) or used < 0:
                raise BudgetExceeded('Invalid local YouTube budget ledger')
            if used >= self.settings.youtube_daily_search_budget:
                raise BudgetExceeded('Local daily YouTube search-call budget exhausted')
            SnapshotStore._atomic_json(path, {'day':day, 'used':used+1, 'unit':'search.list calls'})
        self.search_calls += 1

    async def _request(self, endpoint, params):
        # Cache keys deliberately exclude the API key.
        key = [endpoint, params]
        cached = self.cache.get(self.name, key, self.settings.cache_ttl_seconds)
        if cached:
            self.cache_hits += 1
            self.raw.append({'source':'youtube', 'endpoint':endpoint, 'params':params, 'cache_hit':True, **cached})
            return cached['payload'], cached['captured_at']
        if endpoint == 'search':
            self._reserve_search()
        else:
            if self.video_calls >= self.settings.youtube_video_budget:
                raise BudgetExceeded('YouTube videos.list call budget exhausted')
            self.video_calls += 1
        result = await self.get_json(API+endpoint, params={**params, 'key':self.settings.youtube_api_key})
        if not isinstance(result.get('items'), list):
            raise ProviderError('YouTube items must be a list')
        record = self.cache.put(self.name, key, result)
        self.raw.append({'source':'youtube', 'endpoint':endpoint, 'params':params, 'cache_hit':False, **record})
        return result, record['captured_at']

    def queries(self, entity):
        if entity.youtube_queries:
            return entity.youtube_queries[:self.settings.youtube_queries_per_game]
        suffix = 'beginner guide'
        if 'rpg_builds' in entity.mechanics: suffix = 'best build'
        elif 'crafting' in entity.mechanics: suffix = 'crafting guide'
        elif 'puzzles' in entity.mechanics: suffix = 'walkthrough'
        elif 'codes' in entity.mechanics: suffix = 'redeem codes'
        return [entity.canonical_name, f'{entity.canonical_name} {suffix}'][:self.settings.youtube_queries_per_game]

    async def fetch(self, entity):
        if not self.configured:
            return missing(self.name, entity, self.settings.youtube_region, SourceState.UNAVAILABLE, 'YOUTUBE_API_KEY is not configured')
        # Day-grained cutoff makes repeated scans cacheable, with an explicit observed window.
        now = utc_now()
        after = (now-timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace('+00:00','Z')
        queries = self.queries(entity)
        signal_key = ['signal', entity.slug, queries, after, self.settings.youtube_region, self.settings.youtube_language]
        cache = self.cache.get(self.name, signal_key, self.settings.cache_ttl_seconds)
        if cache:
            return PlatformSignal.model_validate(cache['payload']).model_copy(update={'cache_hit':True})
        ids, notes, captures = set(), [], []
        for query in queries:
            try:
                result, captured = await self._request('search', {'part':'snippet', 'type':'video', 'q':query,
                    'publishedAfter':after, 'order':'date', 'maxResults':25,
                    'regionCode':self.settings.youtube_region, 'relevanceLanguage':self.settings.youtube_language})
                captures.append(captured)
                for row in result['items']:
                    video_id = (row.get('id') or {}).get('videoId')
                    if video_id and relevant(entity, (row.get('snippet') or {}).get('title', '')+' '+(row.get('snippet') or {}).get('description', '')):
                        ids.add(video_id)
            except BudgetExceeded as exc:
                notes.append(str(exc))
                break
        if not ids:
            return missing(self.name, entity, self.settings.youtube_region,
                SourceState.BUDGET_EXHAUSTED if notes else SourceState.INSUFFICIENT_DATA,
                '; '.join(notes) if notes else 'No clearly game-matched videos in the bounded recent search sample')
        rows = []
        ordered = sorted(ids)
        for start in range(0, len(ordered), 50):
            try:
                result, captured = await self._request('videos', {'part':'snippet,statistics', 'id':','.join(ordered[start:start+50])})
                captures.append(captured)
                rows.extend(result['items'])
            except BudgetExceeded as exc:
                notes.append(str(exc))
                break
        evidence, views, velocities = [], [], []
        for row in rows:
            snippet, stats = row.get('snippet') or {}, row.get('statistics') or {}
            try:
                published = datetime.fromisoformat(snippet['publishedAt'].replace('Z','+00:00'))
                if not published.tzinfo or published > now or (now-published).days > 31: continue
                raw_views = stats.get('viewCount')
                count = int(raw_views) if raw_views is not None else None
            except (ValueError, KeyError, TypeError):
                continue
            age = max(1, (now-published).total_seconds()/3600)
            velocity = round(count/age, 2) if count is not None else None
            title = snippet.get('title','')
            item = EvidenceItem(id=f'youtube:{row["id"]}', source='youtube', title=title,
                url=f'https://www.youtube.com/watch?v={row["id"]}', published_at=published,
                captured_at=datetime.fromisoformat(min(captures)), author=snippet.get('channelId'),
                metrics={'views':count, 'views_per_hour_proxy':velocity, 'intent_video':bool(INTENT.search(title))})
            evidence.append(item)
            if count is not None: views.append(count)
            if velocity is not None: velocities.append(velocity)
        if not evidence:
            return missing(self.name, entity, self.settings.youtube_region, SourceState.BUDGET_EXHAUSTED if notes else SourceState.INSUFFICIENT_DATA,
                           '; '.join(notes) or 'No usable video details')
        recent = [e for e in evidence if (now-e.published_at).total_seconds() <= 7*86400]
        intent = [e for e in evidence if e.metrics['intent_video']]
        metrics = {'recent_video_count':len(evidence), 'recent_guide_video_count':len(intent),
            'video_count_7d':len(recent), 'guide_video_count_7d':sum(e.metrics['intent_video'] for e in recent),
            'creator_count':len({e.author for e in evidence if e.author}),
            'top_video_views':max(views) if views else None, 'median_views':median(views) if views else None,
            'view_velocity_proxy':median(velocities) if velocities else None,
            'intent_video_share':len(intent)/len(evidence), 'sample_size':len(evidence),
            'sample_only':True, 'window_days':30, 'published_after':after,
            'queries':queries, 'region_code':self.settings.youtube_region, 'relevance_language':self.settings.youtube_language}
        signal = PlatformSignal(source=self.name, game_slug=entity.slug, market=self.settings.youtube_region,
            captured_at=datetime.fromisoformat(min(captures)), metrics=metrics, evidence=evidence,
            confidence=Confidence.MEDIUM if metrics['creator_count'] >= 3 else Confidence.LOW,
            status=SourceState.PARTIAL if notes else SourceState.OK,
            notes=notes+['Retrieved sample, not total YouTube supply or Google search volume.',
                         'Velocity is lifetime views / video age, not measured views gained this hour.',
                         'regionCode filters video availability; it does not identify viewer geography.'])
        # A failed/limited result never replaces the previous complete cache.
        if not notes: self.cache.put(self.name, signal_key, signal.model_dump(mode='json'))
        return signal
