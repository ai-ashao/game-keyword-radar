from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from game_keyword_radar.config import Settings
from game_keyword_radar.models import Evidence, GameCandidate, SourceState, SourceStatus


SEARCH_URL = "https://store.steampowered.com/search/results/"
APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
PLAYER_COUNT_URL = (
    "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
)


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


class SteamCollector:
    """Collects public Steam Store signals with bounded retries and graceful failure."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self._owns_client = client is None
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)

    async def __aenter__(self) -> SteamCollector:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.settings.request_timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "GameKeywordRadar/0.1 (+local research tool; respectful requests)"
                    )
                },
            )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("SteamCollector must be used as an async context manager")
        return self._client

    async def _get_json(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with self._semaphore:
                    response = await self.client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("expected a JSON object")
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.35 * (2**attempt))
        raise RuntimeError(f"request failed after 3 attempts: {last_error}")

    async def fetch_listing(self, source: str, limit: int) -> tuple[list[SearchRow], dict]:
        filter_name = {"top_sellers": "topsellers", "popular_new": "popularnew"}[source]
        params = {
            "query": "",
            "start": 0,
            "count": min(max(limit, 1), 30),
            "dynamic_data": "",
            "sort_by": "_ASC",
            "snr": "1_7_7_230_7",
            "filter": filter_name,
            "infinite": 1,
            "cc": self.settings.country.lower(),
            "l": self.settings.language,
        }
        payload = await self._get_json(SEARCH_URL, params=params)
        html = str(payload.get("results_html") or "")
        rows = self.parse_search_results(html, source=source, limit=limit)
        return rows, {
            "source": source,
            "endpoint": SEARCH_URL,
            "params": params,
            "records": [asdict(row) for row in rows],
        }

    @staticmethod
    def parse_search_results(html: str, *, source: str, limit: int) -> list[SearchRow]:
        soup = BeautifulSoup(html, "html.parser")
        rows: list[SearchRow] = []
        seen: set[str] = set()
        for element in soup.select("a.search_result_row"):
            app_id = str(element.get("data-ds-appid") or "").split(",")[0].strip()
            title = element.select_one("span.title")
            if not app_id.isdigit() or title is None or app_id in seen:
                continue
            seen.add(app_id)
            image = element.select_one("div.search_capsule img")
            release = element.select_one("div.search_released")
            rows.append(
                SearchRow(
                    app_id=app_id,
                    name=title.get_text(" ", strip=True),
                    rank=len(rows) + 1,
                    source=source,
                    store_url=f"https://store.steampowered.com/app/{app_id}/",
                    image_url=str(image.get("src")) if image and image.get("src") else None,
                    release_text=release.get_text(" ", strip=True) if release else None,
                )
            )
            if len(rows) >= limit:
                break
        return rows

    async def fetch_app_details(self, app_id: str) -> dict[str, Any] | None:
        payload = await self._get_json(
            APP_DETAILS_URL,
            params={
                "appids": app_id,
                "cc": self.settings.country.lower(),
                "l": "en",
            },
        )
        result = payload.get(app_id)
        if not isinstance(result, dict) or not result.get("success"):
            return None
        data = result.get("data")
        return data if isinstance(data, dict) else None

    async def fetch_current_players(self, app_id: str) -> int | None:
        payload = await self._get_json(PLAYER_COUNT_URL, params={"appid": app_id})
        response = payload.get("response")
        if not isinstance(response, dict) or response.get("result") != 1:
            return None
        count = response.get("player_count")
        return int(count) if isinstance(count, int | float) and count >= 0 else None

    @staticmethod
    def _parse_release_date(data: dict[str, Any]) -> datetime | None:
        release = data.get("release_date")
        if not isinstance(release, dict):
            return None
        raw = str(release.get("date") or "").strip()
        for fmt in ("%b %d, %Y", "%d %b, %Y", "%b %Y"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        return None

    async def _hydrate(self, row: SearchRow, merged: dict[str, SearchRow]) -> GameCandidate | None:
        try:
            details, players = await asyncio.gather(
                self.fetch_app_details(row.app_id),
                self.fetch_current_players(row.app_id),
            )
        except Exception as exc:  # one game must not abort the scan
            details = None
            players = None
            hydration_error = str(exc)
        else:
            hydration_error = None

        if details is not None and details.get("type") not in {None, "game"}:
            return None

        source_rows = [item for key, item in merged.items() if key.startswith(f"{row.app_id}:")]
        sources = sorted({item.source for item in source_rows}) or [row.source]
        ranks = {item.source: item.rank for item in source_rows} or {row.source: row.rank}
        release_dt = self._parse_release_date(details or {})
        recommendations = (details or {}).get("recommendations")
        reviews_total = (
            recommendations.get("total")
            if isinstance(recommendations, dict)
            and isinstance(recommendations.get("total"), int)
            else None
        )
        genres = [
            str(item.get("description"))
            for item in (details or {}).get("genres", [])
            if isinstance(item, dict) and item.get("description")
        ]
        categories = [
            str(item.get("description"))
            for item in (details or {}).get("categories", [])
            if isinstance(item, dict) and item.get("description")
        ]
        name = str((details or {}).get("name") or row.name)
        store_url = f"https://store.steampowered.com/app/{row.app_id}/"
        evidence = [
            Evidence(
                label="Steam discovery rank",
                value=min(ranks.values()),
                source=",".join(sources),
                source_url=SEARCH_URL,
            )
        ]
        if hydration_error:
            evidence.append(
                Evidence(
                    label="Steam detail collection",
                    value=hydration_error,
                    source="collector_error",
                    is_inference=False,
                )
            )
        return GameCandidate(
            app_id=row.app_id,
            name=name,
            discovery_sources=sources,
            discovery_ranks=ranks,
            steam_rank=min(ranks.values()),
            release_date=release_dt.date() if release_dt else None,
            current_players=players,
            reviews_total=reviews_total,
            genres=genres,
            categories=categories,
            short_description=(details or {}).get("short_description"),
            image_url=(details or {}).get("header_image") or row.image_url,
            store_url=store_url,
            evidence=evidence,
        )

    async def collect(self, limit: int) -> SteamCollection:
        collection = SteamCollection()
        listing_rows: list[SearchRow] = []
        raw_listings: list[dict] = []
        for source in ("top_sellers", "popular_new"):
            try:
                rows, raw = await self.fetch_listing(source, limit)
                listing_rows.extend(rows)
                raw_listings.append(raw)
                state = SourceState.OK if rows else SourceState.PARTIAL
                collection.statuses.append(
                    SourceStatus(
                        source=f"steam_{source}",
                        state=state,
                        message=(
                            f"Collected {len(rows)} candidates."
                            if rows
                            else "Steam returned no parseable candidates."
                        ),
                        official_api=False,
                        records=len(rows),
                    )
                )
            except Exception as exc:
                message = f"Steam {source} failed: {exc}"
                collection.errors.append(message)
                collection.statuses.append(
                    SourceStatus(
                        source=f"steam_{source}",
                        state=SourceState.FAILED,
                        message=message,
                        official_api=False,
                    )
                )

        grouped: dict[str, list[SearchRow]] = {}
        for row in listing_rows:
            grouped.setdefault(row.app_id, []).append(row)
        ordered = sorted(
            grouped.values(),
            key=lambda rows: (min(r.rank for r in rows), -len(rows)),
        )[:limit]
        lookup = {f"{row.app_id}:{row.source}": row for row in listing_rows}
        if ordered:
            games = await asyncio.gather(
                *(self._hydrate(rows[0], lookup) for rows in ordered),
                return_exceptions=True,
            )
            for result in games:
                if isinstance(result, GameCandidate):
                    collection.games.append(result)
                elif isinstance(result, Exception):
                    collection.errors.append(f"Steam game hydration failed: {result}")

        collection.raw = {
            "collected_at": datetime.utcnow().isoformat() + "Z",
            "country": self.settings.country,
            "language": self.settings.language,
            "listings": raw_listings,
        }
        if not collection.games and not collection.errors:
            collection.errors.append("Steam produced no usable game records.")
        return collection
