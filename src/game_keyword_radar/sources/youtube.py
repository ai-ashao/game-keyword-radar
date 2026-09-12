"""YouTube evidence provider.

Preferred path: YouTube Data API v3 when an existing key is already configured.
Zero-new-credential fallback: bounded yt-dlp public search during Deep analysis only.
The public fallback never enables cookies/login/proxy/token helpers and degrades cleanly.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import shutil
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo
import fcntl
from game_keyword_radar.models import PlatformSignal, SourceState, Confidence, EvidenceItem, utc_now
from game_keyword_radar.sources.base import HttpProvider, BudgetExceeded, ProviderError, missing
from game_keyword_radar.storage import SnapshotStore
from game_keyword_radar.provider_state import BestEffortCircuitBreaker

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
        self.breaker = BestEffortCircuitBreaker(settings.data_dir, 'youtube-public')

    @property
    def configured(self):
        return bool(self.settings.youtube_api_key) or self.public_available()

    @staticmethod
    def public_available():
        return shutil.which('yt-dlp') is not None

    def _reserve_search(self):
        if self.search_calls >= self.settings.youtube_search_budget:
            raise BudgetExceeded('Per-scan YouTube search-call budget exhausted')
        path = self.settings.data_dir / 'budgets' / 'youtube-search.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path.parent / '.youtube.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:
                ledger = json.loads(path.read_text())
            except FileNotFoundError:
                ledger = {}
            except (ValueError, OSError):
                raise BudgetExceeded('Local YouTube budget ledger is unreadable; repair it before further calls')
            day = datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()
            used = ledger.get('used', 0) if ledger.get('day') == day else 0
            if not isinstance(used, int) or used < 0:
                raise BudgetExceeded('Invalid local YouTube budget ledger')
            if used >= self.settings.youtube_daily_search_budget:
                raise BudgetExceeded('Local daily YouTube search-call budget exhausted')
            SnapshotStore._atomic_json(path, {'day':day, 'used':used+1, 'unit':'search.list calls'})
        self.search_calls += 1

    async def _request(self, endpoint, params):
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

    async def _public_query(self, query: str, limit: int = 10) -> list[dict]:
        exe = shutil.which('yt-dlp')
        if not exe:
            raise ProviderError('yt-dlp is not installed')
        # --ignore-config prevents a local yt-dlp config from silently adding cookies/proxies/accounts.
        proc = await asyncio.create_subprocess_exec(exe, '--ignore-config', '--no-warnings', '--flat-playlist',
            '--dump-json', '--playlist-end', str(limit), f'ytsearch{limit}:{query}',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=max(10, self.settings.request_timeout * 2))
        except asyncio.TimeoutError:
            proc.kill(); await proc.communicate()
            raise ProviderError('yt-dlp public search timed out')
        if proc.returncode:
            text = stderr.decode('utf-8', 'replace').strip()
            raise ProviderError('yt-dlp public search failed: ' + text[:300])
        rows = []
        for line in stdout.decode('utf-8', 'replace').splitlines():
            if not line.strip(): continue
            try: rows.append(json.loads(line))
            except ValueError: continue
        return rows

    async def _fetch_public(self, entity):
        allowed, reason = self.breaker.allowed()
        if not allowed:
            return missing(self.name, entity, self.settings.youtube_region, SourceState.UNAVAILABLE,
                           f'Public YouTube fallback disabled by circuit breaker: {reason}')
        if not self.public_available():
            return missing(self.name, entity, self.settings.youtube_region, SourceState.UNAVAILABLE,
                           'No YOUTUBE_API_KEY and yt-dlp is not installed')
        queries = self.queries(entity)
        evidence, notes = [], []
        try:
            for query in queries:
                self.search_calls += 1
                if self.search_calls > self.settings.youtube_search_budget:
                    notes.append('Public YouTube per-scan query budget exhausted'); break
                rows = await self._public_query(query, limit=10)
                for row in rows:
                    title = row.get('title') or ''
                    if not row.get('id') or not relevant(entity, title):
                        continue
                    evidence.append(EvidenceItem(id=f'youtube-public:{row["id"]}', source='youtube', title=title,
                        url=f'https://www.youtube.com/watch?v={row["id"]}', captured_at=utc_now(),
                        author=str(row.get('channel_id') or row.get('channel') or row.get('uploader') or '') or None,
                        metrics={'intent_video':bool(INTENT.search(title)), 'provider':'yt_dlp_public'}))
            # de-dupe videos found by multiple queries
            evidence = list({e.id:e for e in evidence}.values())
            self.breaker.success()
        except Exception as exc:
            kind = 'blocked' if any(x in str(exc).casefold() for x in ('sign in','captcha','po token','forbidden')) else 'failed'
            self.breaker.failure(str(exc), kind=kind)
            return missing(self.name, entity, self.settings.youtube_region, SourceState.UNAVAILABLE, str(exc))
        if not evidence:
            return missing(self.name, entity, self.settings.youtube_region, SourceState.INSUFFICIENT_DATA,
                           'No clearly game-matched videos in bounded yt-dlp public search')
        intent = [e for e in evidence if e.metrics.get('intent_video')]
        metrics = {'provider':'yt_dlp_public', 'recent_video_count':len(evidence),
            'recent_guide_video_count':len(intent), 'creator_count':len({e.author for e in evidence if e.author}),
            'intent_video_share':len(intent)/len(evidence), 'sample_size':len(evidence), 'sample_only':True,
            'window_days':None, 'queries':queries, 'region_code':self.settings.youtube_region,
            'relevance_language':self.settings.youtube_language, 'measurement':'public_search_sample'}
        return PlatformSignal(source=self.name, game_slug=entity.slug, market=self.settings.youtube_region,
            captured_at=utc_now(), metrics=metrics, evidence=evidence, confidence=Confidence.LOW,
            status=SourceState.PARTIAL, scope_version='youtube-public-v1',
            metric_scope={'provider':'yt_dlp_public','measurement':'public_search_sample'},
            notes=notes+['Best-effort yt-dlp public search; not YouTube Data API, total video supply, search volume, or viewer geography.',
                         'No cookies, login, proxy, PO-token helper, or other credential path is enabled by Game Keyword Radar.'])

    async def fetch(self, entity):
        if not self.settings.youtube_api_key:
            return await self._fetch_public(entity)
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
                notes.append(str(exc)); break
        if not ids:
            return missing(self.name, entity, self.settings.youtube_region,
                SourceState.BUDGET_EXHAUSTED if notes else SourceState.INSUFFICIENT_DATA,
                '; '.join(notes) if notes else 'No clearly game-matched videos in the bounded recent search sample')
        rows = []
        ordered = sorted(ids)
        for start in range(0, len(ordered), 50):
            try:
                result, captured = await self._request('videos', {'part':'snippet,statistics', 'id':','.join(ordered[start:start+50])})
                captures.append(captured); rows.extend(result['items'])
            except BudgetExceeded as exc:
                notes.append(str(exc)); break
        evidence, views, velocities = [], [], []
        for row in rows:
            snippet, stats = row.get('snippet') or {}, row.get('statistics') or {}
            try:
                published = datetime.fromisoformat(snippet['publishedAt'].replace('Z','+00:00'))
                if not published.tzinfo or published > now or (now-published).days > 31: continue
                raw_views = stats.get('viewCount'); count = int(raw_views) if raw_views is not None else None
            except (ValueError, KeyError, TypeError):
                continue
            age = max(1, (now-published).total_seconds()/3600)
            velocity = round(count/age, 2) if count is not None else None
            title = snippet.get('title','')
            item = EvidenceItem(id=f'youtube:{row["id"]}', source='youtube', title=title,
                url=f'https://www.youtube.com/watch?v={row["id"]}', published_at=published,
                captured_at=datetime.fromisoformat(min(captures)), author=snippet.get('channelId'),
                metrics={'views':count, 'views_per_hour_proxy':velocity, 'intent_video':bool(INTENT.search(title)),
                         'provider':'youtube_data_api'})
            evidence.append(item)
            if count is not None: views.append(count)
            if velocity is not None: velocities.append(velocity)
        if not evidence:
            return missing(self.name, entity, self.settings.youtube_region, SourceState.BUDGET_EXHAUSTED if notes else SourceState.INSUFFICIENT_DATA,
                           '; '.join(notes) or 'No usable video details')
        recent = [e for e in evidence if (now-e.published_at).total_seconds() <= 7*86400]
        intent = [e for e in evidence if e.metrics['intent_video']]
        metrics = {'provider':'youtube_data_api', 'recent_video_count':len(evidence), 'recent_guide_video_count':len(intent),
            'video_count_7d':len(recent), 'guide_video_count_7d':sum(e.metrics['intent_video'] for e in recent),
            'creator_count':len({e.author for e in evidence if e.author}),
            'top_video_views':max(views) if views else None, 'median_views':median(views) if views else None,
            'view_velocity_proxy':median(velocities) if velocities else None,
            'intent_video_share':len(intent)/len(evidence), 'sample_size':len(evidence),
            'sample_only':True, 'window_days':30, 'published_after':after, 'measurement':'youtube_api_recent_search',
            'queries':queries, 'region_code':self.settings.youtube_region, 'relevance_language':self.settings.youtube_language}
        signal = PlatformSignal(source=self.name, game_slug=entity.slug, market=self.settings.youtube_region,
            captured_at=datetime.fromisoformat(min(captures)), metrics=metrics, evidence=evidence,
            confidence=Confidence.MEDIUM if metrics['creator_count'] >= 3 else Confidence.LOW,
            status=SourceState.PARTIAL if notes else SourceState.OK, scope_version='youtube-api-v1',
            metric_scope={'provider':'youtube_data_api','measurement':'youtube_api_recent_search','window_days':30},
            notes=notes+['Retrieved sample, not total YouTube supply or Google search volume.',
                         'Velocity is lifetime views / video age, not measured views gained this hour.',
                         'regionCode filters video availability; it does not identify viewer geography.'])
        if not notes: self.cache.put(self.name, signal_key, signal.model_dump(mode='json'))
        return signal
