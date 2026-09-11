"""Official Helix client. Global streams are a *sample*, never a game-wide total."""
from __future__ import annotations
import hashlib
import json
import os
import time
from datetime import datetime
import httpx
from game_keyword_radar.models import PlatformSignal, SourceState, Confidence, GameEntity
from game_keyword_radar.sources.base import HttpProvider, ProviderError, missing
from game_keyword_radar.storage import SnapshotStore

HELIX = 'https://api.twitch.tv/helix/'
TOKEN = 'https://id.twitch.tv/oauth2/token'
NON_GAMES = {'just chatting', 'music', 'special events', 'sports', 'talk shows & podcasts', 'pools, hot tubs, and beaches', 'irl', 'art', 'makers & crafting', 'software and game development'}

class TwitchProvider(HttpProvider):
    name = 'twitch'

    def __init__(self, settings, client=None):
        super().__init__(settings, client)
        key = hashlib.sha256(settings.twitch_client_id.encode()).hexdigest()[:16]
        self.token_path = settings.data_dir / 'private' / f'twitch-token-{key}.json'
        self._token = None
        self._expires = 0
        self.raw: list[dict] = []

    @property
    def configured(self):
        return bool(self.settings.twitch_client_id and self.settings.twitch_client_secret)

    async def token(self, *, force=False):
        if not self.configured:
            raise ProviderError('Missing TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET')
        if not force and self._token and time.time() < self._expires - 60:
            return self._token
        if not force:
            try:
                saved = json.loads(self.token_path.read_text())
                if saved['expires_at'] > time.time()+60:
                    self._token, self._expires = saved['token'], saved['expires_at']
                    return self._token
            except (OSError, ValueError, KeyError, TypeError):
                pass
        self.consume_attempt()
        response = await self.client.post(TOKEN, data={'client_id':self.settings.twitch_client_id,
            'client_secret':self.settings.twitch_client_secret, 'grant_type':'client_credentials'})
        response.raise_for_status()
        result = response.json()
        if not result.get('access_token') or not isinstance(result.get('expires_in'), (int, float)):
            raise ProviderError('Twitch token response missing fields')
        self._token, self._expires = result['access_token'], time.time()+result['expires_in']
        self.token_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        SnapshotStore._atomic_json(self.token_path, {'token':self._token, 'expires_at':self._expires})
        os.chmod(self.token_path, 0o600)
        return self._token

    async def helix(self, endpoint, params=None):
        for attempt in range(2):
            token = await self.token(force=bool(attempt))
            try:
                payload = await self.get_json(HELIX+endpoint, params=params,
                    headers={'Client-Id':self.settings.twitch_client_id, 'Authorization':f'Bearer {token}'})
                if not isinstance(payload.get('data'), list):
                    raise ProviderError('Twitch data must be a list')
                return payload
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 401 or attempt:
                    raise
        raise ProviderError('Twitch authentication failed')

    @staticmethod
    def aggregate(streams, *, complete=False, rank=None, scope='global_top_streams'):
        unique = {row['id']:row for row in streams if row.get('id')}
        rows = list(unique.values())
        viewers = sum(max(0, int(row.get('viewer_count', 0))) for row in rows)
        channels = len({row.get('user_id') or row['id'] for row in rows})
        top = max((int(row.get('viewer_count', 0)) for row in rows), default=0)
        ordered = sorted((max(0, int(row.get('viewer_count', 0))) for row in rows), reverse=True)
        return {'observed_viewers': viewers, 'observed_live_channels': channels,
                'top1_viewer_share': round(top/viewers,4) if viewers else None,
                'top3_viewer_share': round(sum(ordered[:3])/viewers,4) if viewers else None,
                'non_top1_viewers': viewers-top, 'broadcaster_ids': sorted({str(row.get('user_id') or row['id']) for row in rows}),
                'total_viewers': viewers, 'live_channels': channels,
                'avg_viewers_per_channel': round(viewers/channels, 2) if channels else 0,
                'top_stream_viewers':top, 'audience_concentration': round(top/viewers, 4) if viewers else None,
                'twitch_rank':rank, 'sampling_complete':complete, 'sampling_scope':scope,
                'metric_label':'game_stream_observation' if complete else 'sample_lower_bound',
                'breadth_confidence': 'low' if viewers and top/viewers > .7 else 'medium'}

    async def discover(self, limit):
        if not self.configured:
            return [], []
        key = ['discovery', limit, self.settings.twitch_max_stream_pages]
        cached = self.cache.get(self.name, key, self.settings.twitch_cache_ttl_seconds)
        if cached:
            self.cache_hits += 1
            return cached['payload']['games'], [{**s, 'cache_hit':True} for s in cached['payload']['signals']]
        # Top categories give a category rank, independent of sampled stream coverage.
        games, cursor = [], None
        while len(games) < limit:
            params = {'first':min(100, limit-len(games))}
            if cursor: params['after'] = cursor
            data = await self.helix('games/top', params)
            games.extend(data['data'])
            cursor = data.get('pagination', {}).get('cursor')
            if not cursor or not data['data']: break
        ranks = {g['id']:i+1 for i,g in enumerate(games)}
        ids = [g['id'] for g in games]
        if ids:
            details = await self.helix('games', [('id', i) for i in ids[:100]])
            lookup = {g['id']:g for g in details['data']}
            games = [{**g, **lookup.get(g['id'], {}), 'twitch_rank':ranks[g['id']]} for g in games]
        all_streams, cursor, complete = [], None, False
        for _ in range(self.settings.twitch_max_stream_pages):
            params = {'first':100}
            if cursor: params['after'] = cursor
            data = await self.helix('streams', params)
            all_streams.extend(data['data'])
            cursor = data.get('pagination', {}).get('cursor')
            if not cursor:
                complete = True
                break
        signals = []
        now = datetime.now().astimezone().isoformat()
        for game in games:
            if game['name'].casefold() in NON_GAMES: continue
            streams = [s for s in all_streams if s.get('game_id') == game['id']]
            # A category missing from a top-stream sample is NOT zero viewers.
            metrics = self.aggregate(streams, complete=complete, rank=ranks[game['id']]) if streams or complete else {'twitch_rank':ranks[game['id']], 'sampling_complete':False, 'sampling_scope':'global_top_streams'}
            metrics['sample_page_limit'] = self.settings.twitch_max_stream_pages
            signals.append({'game_id':game['id'], 'metrics':metrics, 'captured_at':now, 'cache_hit':False})
        games = [g for g in games if g['name'].casefold() not in NON_GAMES]
        self.raw.append({'source':'twitch', 'captured_at':now, 'status':'ok', 'market':'GLOBAL',
                         'games':games, 'streams':all_streams, 'scope':'bounded_global_stream_sample'})
        self.cache.put(self.name, key, {'games':games, 'signals':signals})
        return games, signals

    async def fetch(self, entity: GameEntity):
        if not self.configured:
            return missing(self.name, entity, 'GLOBAL', SourceState.UNAVAILABLE, 'Twitch credentials are not configured')
        game_id = entity.platform_ids.get('twitch')
        if not game_id:
            matches_by_id = {}
            for name in list(dict.fromkeys([entity.canonical_name, *entity.aliases]))[:5]:
                matches = await self.helix('games', {'name': name})
                for game in matches['data']:
                    if game['name'].casefold() == name.casefold():
                        matches_by_id[game['id']] = game
            if len(matches_by_id) != 1:
                return missing(self.name, entity, 'GLOBAL', SourceState.INSUFFICIENT_DATA,
                    'No unique exact Twitch name/verified-alias match; not evidence of no Twitch audience')
            game_id = next(iter(matches_by_id))
            entity.platform_ids['twitch'] = game_id
        key = ['game-v21', game_id, self.settings.twitch_pages]
        cached = self.cache.get(self.name, key, self.settings.twitch_cache_ttl_seconds)
        if cached:
            signal = PlatformSignal.model_validate(cached['payload'])
            return signal.model_copy(update={'game_slug':entity.slug, 'cache_hit':True})
        started = datetime.now().astimezone()
        streams, cursor, complete = [], None, False
        for _ in range(self.settings.twitch_pages):
            params = {'first':100, 'game_id':game_id}
            if cursor: params['after'] = cursor
            result = await self.helix('streams', params)
            streams.extend(result['data'])
            cursor = result.get('pagination', {}).get('cursor')
            if not cursor:
                complete = True
                break
        metrics = self.aggregate(streams, complete=complete, scope='game_streams')
        metrics['sample_page_limit'] = self.settings.twitch_pages
        metrics['game_id'] = game_id
        signal = PlatformSignal(source=self.name, game_slug=entity.slug, market='GLOBAL', metrics=metrics,
            scope_version='2.1', metric_scope={'metric':'single_game_stream_observation','game_id':game_id},
            window_started_at=started, window_finished_at=datetime.now().astimezone(),
            status=SourceState.OK if complete else SourceState.PARTIAL,
            confidence=Confidence.MEDIUM if complete and metrics['breadth_confidence'] != 'low' else Confidence.LOW,
            notes=['Live observations, not a daily average. Pagination can change during collection.',
                   'Bounded sample: viewer/channel counts are lower bounds.' if not complete else 'All returned pages consumed.'])
        from game_keyword_radar.observations import stamp_observation
        stamp_observation(signal)
        self.raw.append({'source':'twitch', 'captured_at':signal.captured_at.isoformat(), 'status':signal.status.value,
                         'market':'GLOBAL', 'game_id':game_id, 'streams':streams})
        self.cache.put(self.name, key, signal.model_dump(mode='json'))
        return signal


    async def discover_categories(self, limit):
        """Category ingress only. Directed observation is independently budgeted."""
        if not self.configured:
            return [], []
        key = ["categories-v21", limit]
        cached = self.cache.get(self.name, key, self.settings.twitch_cache_ttl_seconds)
        if cached:
            self.cache_hits += 1
            return cached['payload']['games'], []
        games, cursor = [], None
        while len(games) < limit:
            params = {'first': min(100, limit-len(games))}
            if cursor: params['after'] = cursor
            result = await self.helix('games/top', params)
            games.extend(result['data'])
            cursor = result.get('pagination', {}).get('cursor')
            if not result['data'] or not cursor: break
        captured = datetime.now().astimezone().isoformat()
        rows = [{**g, 'twitch_rank': i+1, 'rank_scope': {'requested':limit, 'returned':len(games)},
                 'captured_at':captured, 'is_non_game': g['name'].casefold() in NON_GAMES}
                for i, g in enumerate(games)]
        self.raw.append({'source':'twitch', 'captured_at':captured, 'scope':'bounded_category_list', 'games':rows})
        self.cache.put(self.name, key, {'games':rows})
        return rows, []
