"""Steam adapter; public store discovery plus independent detail/player hydration.

A player endpoint failure must never discard successful app metadata (or vice versa).
All raw successful payloads carry an observation time, market and source status.
"""
from __future__ import annotations
import asyncio
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from bs4 import BeautifulSoup
from game_keyword_radar.models import GameCandidate, SourceStatus, SourceState, Evidence, utc_now
from game_keyword_radar.sources.base import HttpProvider, safe_error, ProviderError, BudgetExceeded

SEARCH_URL = 'https://store.steampowered.com/search/results/'
APP_DETAILS_URL = 'https://store.steampowered.com/api/appdetails'
PLAYER_COUNT_URL = 'https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/'

@dataclass(slots=True)
class SearchRow:
    app_id: str
    name: str
    rank: int
    source: str
    store_url: str
    image_url: str | None = None
    release_text: str | None = None

@dataclass(slots=True)
class SteamCollection:
    games: list[GameCandidate] = field(default_factory=list)
    statuses: list[SourceStatus] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

class SteamProvider(HttpProvider):
    name = 'steam'

    def __init__(self, settings, client=None):
        super().__init__(settings, client)
        self.raw_responses: list[dict] = []
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def _get_json(self, url, *, params):
        key = [url, params]
        # Live CCU needs fresher caching than relatively static app metadata.
        ttl = min(self.settings.cache_ttl_seconds, 300) if url == PLAYER_COUNT_URL else self.settings.cache_ttl_seconds
        cached = self.cache.get(self.name, key, ttl)
        if cached:
            self.cache_hits += 1
            record = {**cached, 'source': self.name, 'market': self.settings.country, 'url': url,
                      'params': params, 'status': 'ok', 'cache_hit': True}
            self.raw_responses.append(record)
            return cached['payload']
        async with self._semaphore:
            data = await self.get_json(url, params=params)
        record = self.cache.put(self.name, key, data)
        self.raw_responses.append({**record, 'source': self.name, 'market': self.settings.country,
                                  'url': url, 'params': params, 'status': 'ok', 'cache_hit': False})
        return data

    @staticmethod
    def parse_search_results(html: str, *, source: str, limit: int) -> list[SearchRow]:
        soup = BeautifulSoup(html, 'html.parser')
        rows, seen = [], set()
        for element in soup.select('a.search_result_row'):
            app_id = str(element.get('data-ds-appid') or '').split(',')[0].strip()
            title = element.select_one('span.title')
            if not app_id.isdigit() or title is None or app_id in seen:
                continue
            seen.add(app_id)
            image, release = element.select_one('div.search_capsule img'), element.select_one('div.search_released')
            rows.append(SearchRow(app_id, title.get_text(' ', strip=True), len(rows)+1, source,
                                  f'https://store.steampowered.com/app/{app_id}/',
                                  str(image.get('src')) if image and image.get('src') else None,
                                  release.get_text(' ', strip=True) if release else None))
            if len(rows) >= limit:
                break
        return rows

    async def fetch_listing(self, source: str, limit: int):
        params = {'query': '', 'start': 0, 'count': min(max(limit, 1), 100), 'dynamic_data': '',
                  'sort_by': '_ASC', 'snr': '1_7_7_230_7', 'filter': {'top_sellers':'topsellers','popular_new':'popularnew'}[source],
                  'infinite': 1, 'cc': self.settings.country.lower(), 'l': self.settings.language,
                  'category1': 998}
        payload = await self._get_json(SEARCH_URL, params=params)
        return self.parse_search_results(str(payload.get('results_html') or ''), source=source, limit=limit), payload

    async def fetch_app_details(self, app_id):
        payload = await self._get_json(APP_DETAILS_URL, params={'appids': app_id, 'cc': self.settings.country.lower(), 'l':'en'})
        row = payload.get(app_id)
        return row.get('data') if isinstance(row, dict) and row.get('success') and isinstance(row.get('data'), dict) else None

    async def fetch_current_players(self, app_id):
        payload = await self._get_json(PLAYER_COUNT_URL, params={'appid': app_id})
        row = payload.get('response', {})
        value = row.get('player_count')
        return int(value) if row.get('result') == 1 and isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None

    @staticmethod
    def _parse_release_date(data):
        raw = (data.get('release_date') or {}).get('date', '')
        for fmt in ('%b %d, %Y', '%d %b, %Y', '%b %Y'):
            try:
                return datetime.strptime(raw, fmt)
            except (ValueError, TypeError):
                pass
        return None

    async def _hydrate(self, row, merged, *, metadata_only=False):
        async def no_player(): return None
        results = await asyncio.gather(self.fetch_app_details(row.app_id),
            no_player() if metadata_only else self.fetch_current_players(row.app_id), return_exceptions=True)
        details = results[0] if isinstance(results[0], dict) else {}
        players = results[1] if isinstance(results[1], int) else None
        if details and details.get('type') not in {None, 'game', 'demo'}:
            return None
        rows = [r for k, r in merged.items() if k.startswith(f'{row.app_id}:')]
        ranks = {r.source: r.rank for r in rows} or {row.source: row.rank}
        release = self._parse_release_date(details)
        evidence = [Evidence(label='Steam discovery rank', value=min(ranks.values()), source=','.join(ranks), source_url=SEARCH_URL)]
        for label, result in zip(('app_details', 'current_players'), results):
            if isinstance(result, Exception):
                evidence.append(Evidence(label=f'Steam {label} collection', value=safe_error(result), source='collector_error'))
        # Attribute CCU to its actual fetch/cache timestamp, not this scan's wall clock.
        player_records = [r for r in self.raw_responses if r['url'] == PLAYER_COUNT_URL and str(r['params'].get('appid')) == row.app_id]
        captured = datetime.fromisoformat(player_records[-1]['captured_at']) if player_records else utc_now()
        detail_records = [r for r in self.raw_responses if r['url'] == APP_DETAILS_URL and str(r['params'].get('appids')) == row.app_id]
        metadata_time = datetime.fromisoformat(detail_records[-1]['captured_at']) if detail_records else None
        release_data = details.get('release_date') or {}
        raw_date = str(release_data.get('date') or '')
        stage = ('demo' if details.get('type') == 'demo' else 'upcoming' if release_data.get('coming_soon')
                 else 'early_access' if any(x.get('description') == 'Early Access' for x in details.get('genres', []))
                 else 'released' if details.get('type') == 'game' else 'unknown')
        precision = 'month' if release and len(raw_date.replace(',', '').split()) == 2 else 'day' if release else 'unknown'
        return GameCandidate(release_stage=stage, release_date_raw=raw_date, release_date_precision=precision,
            metadata_captured_at=metadata_time, app_type=details.get('type') or 'unknown', app_id=row.app_id, name=details.get('name') or row.name,
            discovery_sources=list(ranks), discovery_ranks=ranks, steam_rank=min(ranks.values()),
            release_date=release.date() if release else None, current_players=players,
            reviews_total=(details.get('recommendations') or {}).get('total'),
            genres=[x['description'] for x in details.get('genres', []) if isinstance(x, dict) and x.get('description')],
            categories=[x['description'] for x in details.get('categories', []) if isinstance(x, dict) and x.get('description')],
            short_description=details.get('short_description'), image_url=details.get('header_image') or row.image_url,
            store_url=row.store_url, evidence=evidence, collected_at=captured)

    async def collect(self, limit):
        if not 1 <= limit <= 100:
            raise ValueError('discovery limit must be between 1 and 100')
        result, rows = SteamCollection(), []
        for source in ('top_sellers', 'popular_new'):
            try:
                found, _ = await self.fetch_listing(source, limit)
                rows.extend(found)
                result.statuses.append(SourceStatus(source=f'steam_{source}', state=SourceState.OK if found else SourceState.INSUFFICIENT_DATA,
                    message=f'{len(found)} parseable games', records=len(found)))
            except Exception as exc:
                note = f'Steam {source}: {safe_error(exc)}'
                result.errors.append(note)
                result.statuses.append(SourceStatus(source=f'steam_{source}', state=SourceState.FAILED, message=note))
        groups = {}
        for row in rows:
            groups.setdefault(row.app_id, []).append(row)
        recent = sorted((g for g in groups.values() if any(r.source == 'popular_new' for r in g)), key=lambda g: min(r.rank for r in g if r.source == 'popular_new'))
        other = sorted((g for g in groups.values() if g not in recent), key=lambda g: min(r.rank for r in g))
        reserved = min(len(recent), (limit * 6 + 9) // 10)
        ordered = recent[:reserved] + other[:limit-reserved]
        ordered += recent[reserved:reserved+max(0, limit-len(ordered))]
        lookup = {f'{r.app_id}:{r.source}':r for r in rows}
        hydrated = await asyncio.gather(*(self._hydrate(group[0], lookup) for group in ordered), return_exceptions=True)
        for item in hydrated:
            if isinstance(item, GameCandidate):
                result.games.append(item)
            elif isinstance(item, Exception):
                result.errors.append(f'Steam hydration: {safe_error(item)}')
        result.raw = {'source':'steam', 'captured_at':utc_now().isoformat(), 'market':self.settings.country,
                      'status':'partial' if result.errors else 'ok', 'responses': self.raw_responses}
        return result


    async def discover_rows(self, limit: int):
        """Untruncated union of bounded source rows; metadata is budgeted later."""
        rows, statuses, errors = [], [], []
        for source in ("popular_new", "top_sellers"):
            try:
                found, _ = await self.fetch_listing(source, limit)
                rows.extend(found)
                statuses.append(SourceStatus(source=f"steam_{source}",
                    state=SourceState.OK if found else SourceState.INSUFFICIENT_DATA,
                    records=len(found), message=f"{len(found)} source rows; not a validated opportunity count"))
            except Exception as exc:
                message = safe_error(exc)
                errors.append(f"steam_{source}: {message}")
                statuses.append(SourceStatus(source=f"steam_{source}", state=SourceState.BUDGET_EXHAUSTED
                    if isinstance(exc, BudgetExceeded) else SourceState.FAILED, message=message))
        return rows, statuses, errors

    async def metadata(self, entities, rows):
        """One metadata lookup per selected Steam app. No hidden size ranking."""
        lookup = {f"{row.app_id}:{row.source}": row for row in rows}
        games, errors = [], []
        for entity in entities:
            app_id = entity.platform_ids.get("steam")
            if not app_id:
                continue
            row = next((x for x in rows if x.app_id == app_id),
                SearchRow(app_id, entity.canonical_name, 1, "tracked", f"https://store.steampowered.com/app/{app_id}/"))
            try:
                game = await self._hydrate(row, lookup, metadata_only=True)
                if game is None:
                    entity.is_game = False
                else:
                    games.append(game)
            except Exception as exc:
                errors.append(safe_error(exc))
        return games, errors

    async def observe(self, entity):
        from game_keyword_radar.models import PlatformSignal, Confidence, EvidenceItem
        from game_keyword_radar.observations import stamp_observation
        from game_keyword_radar.sources.base import missing
        app_id = entity.platform_ids.get("steam")
        if not app_id:
            return missing("steam", entity, "GLOBAL", SourceState.UNAVAILABLE, "No linked Steam app ID")
        try:
            count = await self.fetch_current_players(app_id)
            if count is None:
                return missing("steam", entity, "GLOBAL", SourceState.INSUFFICIENT_DATA, "Steam did not return a player observation")
            row = next(r for r in reversed(self.raw_responses) if r["url"] == PLAYER_COUNT_URL and str(r["params"].get("appid")) == app_id)
            captured = datetime.fromisoformat(row["captured_at"])
            metrics = {"current_players": count, "country": self.settings.country,
                       "player_region": "GLOBAL", "store_country": self.settings.country, "appid": app_id}
            return stamp_observation(PlatformSignal(source="steam", game_slug=entity.slug, market="GLOBAL",
                captured_at=captured, window_started_at=captured, window_finished_at=captured,
                scope_version="2.1", metric_scope={"metric": "global_current_players", "app_id": app_id},
                status=SourceState.OK, confidence=Confidence.MEDIUM, cache_hit=row.get("cache_hit", False), metrics=metrics,
                evidence=[EvidenceItem(id=f"steam:{app_id}:{captured.isoformat()}", source="steam", title=entity.canonical_name,
                    url=f"https://store.steampowered.com/app/{app_id}/", captured_at=captured, metrics=metrics)],
                notes=["全球瞬时在线观测，不是日均在线；商店查询国家不是玩家地域。", "元数据与玩家观测分别缓存。"] ))
        except Exception as exc:
            return missing("steam", entity, "GLOBAL", SourceState.BUDGET_EXHAUSTED if isinstance(exc, BudgetExceeded) else SourceState.FAILED, safe_error(exc))
