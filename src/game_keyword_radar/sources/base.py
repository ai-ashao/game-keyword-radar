from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from game_keyword_radar.config import Settings
from game_keyword_radar.models import GameEntity, PlatformSignal, SourceState, utc_now
from game_keyword_radar.storage import SnapshotStore


class ProviderError(RuntimeError):
    pass


class BudgetExceeded(ProviderError):
    pass


def safe_error(exc: Exception) -> str:
    """HTTP exception strings can contain API keys in URLs; never persist them."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, ProviderError):
        return str(exc)
    return type(exc).__name__


def missing(source: str, entity: GameEntity, market: str, status: SourceState, note: str) -> PlatformSignal:
    return PlatformSignal(source=source, game_slug=entity.slug, market=market, status=status,
                          notes=[note], failure_reason=note, entity_match_confidence=entity.entity_match_confidence)


class JsonCache:
    def __init__(self, root: Path):
        self.root = root

    def path(self, source: str, key: Any) -> Path:
        digest = hashlib.sha256(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()
        return self.root / source / f"{digest}.json"

    def get(self, source: str, key: Any, ttl: int) -> dict | None:
        try:
            result = json.loads(self.path(source, key).read_text(encoding="utf-8"))
            age = time.time() - result["stored_epoch"]
            return result if 0 <= age <= ttl else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def put(self, source: str, key: Any, payload: Any) -> dict:
        record = {"stored_epoch": time.time(), "captured_at": utc_now().isoformat(), "payload": payload}
        SnapshotStore._atomic_json(self.path(source, key), record)
        return record


class HttpProvider:
    name = "base"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=settings.request_timeout, follow_redirects=False,
            headers={"User-Agent": "GameKeywordRadar/2.1 local research tool"})
        self.owns_client = client is None
        self.cache = JsonCache(settings.data_dir / "cache")
        self.calls = 0
        self.rate_limited_until = 0.0
        self.cache_hits = 0

    async def close(self):
        if self.owns_client:
            await self.client.aclose()

    def consume_attempt(self) -> None:
        limit = (self.settings.request_budget.steam_attempts_per_run if self.name == "steam"
                 else self.settings.request_budget.twitch_attempts_per_run if self.name == "twitch" else None)
        if limit is not None and self.calls >= limit:
            raise BudgetExceeded(f"{self.name} request-attempt budget exhausted")
        if self.rate_limited_until > time.time():
            raise ProviderError(f"{self.name}: rate_limited; wait for reset")
        self.calls += 1

    async def get_json(self, url: str, *, params: Any = None, headers: dict | None = None) -> dict:
        # Small reset delays may be retried once; every attempt including failures is charged.
        for attempt in range(2):
            self.consume_attempt()
            response = await self.client.get(url, params=params, headers=headers)
            if response.status_code == 429:
                try:
                    reset = float(response.headers.get("Ratelimit-Reset", time.time() + 60))
                    delay = float(response.headers.get("Retry-After", max(0, reset-time.time())))
                except ValueError:
                    delay = 60
                self.rate_limited_until = time.time() + max(1, delay)
                if attempt == 0 and 0 < delay <= 2:
                    await asyncio.sleep(max(1, delay))
                    continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ProviderError("Invalid upstream JSON shape")
            return payload
        raise ProviderError("Bounded retry exhausted")
