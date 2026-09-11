"""Optional Trends provider boundary. The restricted Alpha requires an authorized adapter."""
from __future__ import annotations
import asyncio
from datetime import datetime
from statistics import mean
from typing import Protocol
from game_keyword_radar.models import PlatformSignal, SourceState, Confidence
from game_keyword_radar.sources.base import JsonCache, missing

class TrendsProvider(Protocol):
    async def fetch(self, entity, geo: str | None = None, timeframe: str | None = None) -> PlatformSignal: ...

class OfficialTrendsProvider:
    def __init__(self, settings, adapter=None):
        self.settings, self.adapter = settings, adapter
    async def fetch(self, entity, geo=None, timeframe=None):
        market = geo or self.settings.trends_geo
        if self.adapter is None:
            return missing('trends', entity, market, SourceState.UNAVAILABLE,
                'Official Trends Alpha access/authorized adapter not configured. No public endpoint has been invented.')
        # Authorized callers implement the documented endpoint for their granted Alpha version.
        signal = await self.adapter.fetch(entity.trends_terms or [entity.canonical_name], market, timeframe or self.settings.trends_timeframe)
        return PlatformSignal.model_validate({**signal, 'source':'trends', 'game_slug':entity.slug, 'market':market})

class LegacyTrendsProvider:
    def __init__(self, settings):
        self.settings = settings
        self.cache = JsonCache(settings.data_dir / 'cache')
    @staticmethod
    def available():
        try: import pytrends_modern
        except ImportError: return False
        return True
    def _collect(self, terms, geo, timeframe):
        from pytrends_modern import TrendReq
        client = TrendReq(hl='en-US', tz=0, timeout=(5, self.settings.request_timeout))
        client.build_payload(kw_list=terms[:1], timeframe=timeframe, geo=geo, gprop='')
        frame = client.interest_over_time()
        if frame is None or frame.empty or terms[0] not in frame: return None
        if 'isPartial' in frame:
            frame = frame[~frame['isPartial'].astype(bool)]
        values = [float(v) for v in frame[terms[0]].tolist()]
        if len(values)<4 or not any(v>0 for v in values): return None
        split = max(1, len(values)//2)
        old, new = mean(values[:split]), mean(values[split:])
        related = []
        try:
            rows = (client.related_queries() or {}).get(terms[0], {}).get('rising')
            if rows is not None and not rows.empty: related = [str(x) for x in rows['query'].tolist()[:10]]
        except Exception: pass
        return {'trend_direction': 'rising' if new>old+5 else 'falling' if new<old-5 else 'flat',
            'recent_vs_baseline':new/old if old else None, 'direction_delta':new-old,
            'peak_ratio':new/max(values), 'recent_interest':new, 'baseline_interest':old,
            'geo_strength':None, 'related_query_signals':related, 'relative_values':values,
            'term':terms[0], 'geo':geo, 'timeframe':timeframe}
    async def fetch(self, entity, geo=None, timeframe=None):
        geo, timeframe = geo or self.settings.trends_geo, timeframe or self.settings.trends_timeframe
        if not self.available():
            return missing('trends', entity, geo, SourceState.UNAVAILABLE, 'Install the optional trends extra for the legacy provider')
        key = [entity.trends_terms or [entity.canonical_name], geo, timeframe]
        cached = self.cache.get('trends', key, self.settings.cache_ttl_seconds)
        if cached:
            return PlatformSignal.model_validate(cached['payload']).model_copy(update={'game_slug':entity.slug,'cache_hit':True})
        # to_thread protects the event loop; pytrends socket timeouts bound its requests.
        data = await asyncio.to_thread(self._collect, *key)
        if data is None:
            return missing('trends', entity, geo, SourceState.INSUFFICIENT_DATA, 'Insufficient complete nonzero relative-interest observations')
        signal = PlatformSignal(source='trends', game_slug=entity.slug, market=geo, metrics=data, confidence=Confidence.MEDIUM,
            notes=['Unofficial, best-effort relative direction. Never a Google monthly search volume.',
                   'Geo strength across regions is not measured by this single-region request.'])
        self.cache.put('trends', key, signal.model_dump(mode='json'))
        return signal
