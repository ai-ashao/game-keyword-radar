from __future__ import annotations

import asyncio
from statistics import mean
from typing import Any

from game_keyword_radar.config import Settings
from game_keyword_radar.models import GameCandidate, SourceState, SourceStatus, TrendSignal


class TrendsCollector:
    """Optional, bounded Google Trends collector using standard HTTP mode only."""

    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def available() -> bool:
        try:
            import pytrends_modern  # noqa: F401
        except ImportError:
            return False
        return True

    def _collect_one(self, game_name: str) -> TrendSignal:
        from pytrends_modern import TrendReq

        client = TrendReq(hl="en-US", tz=0, timeout=(5, self.settings.request_timeout))
        client.build_payload(
            kw_list=[game_name],
            timeframe="today 1-m",
            geo=self.settings.country,
            gprop="",
        )
        frame = client.interest_over_time()
        if frame is None or getattr(frame, "empty", True) or game_name not in frame:
            return TrendSignal(
                geo=self.settings.country,
                state=SourceState.PARTIAL,
                note="Google Trends returned insufficient_data.",
            )
        values = [float(value) for value in frame[game_name].tolist()]
        midpoint = max(1, len(values) // 2)
        earlier = mean(values[:midpoint])
        recent = mean(values[midpoint:] or values[:midpoint])
        related: list[str] = []
        try:
            related_payload: dict[str, Any] = client.related_queries() or {}
            rows = related_payload.get(game_name, {}).get("rising")
            if rows is not None and not getattr(rows, "empty", True):
                related = [str(value) for value in rows["query"].tolist()[:5]]
        except Exception:
            related = []
        return TrendSignal(
            geo=self.settings.country,
            mean_interest=round(mean(values), 1),
            recent_interest=round(recent, 1),
            direction_delta=round(recent - earlier, 1),
            related_queries=related,
            state=SourceState.OK,
            note="Relative interest for this game only; not comparable as search volume.",
        )

    async def enrich(
        self, games: list[GameCandidate], *, enabled: bool
    ) -> tuple[list[GameCandidate], SourceStatus]:
        if not enabled:
            return games, SourceStatus(
                source="google_trends",
                state=SourceState.SKIPPED,
                message="Optional Trends collection was disabled.",
                official_api=False,
            )
        if not self.available():
            return games, SourceStatus(
                source="google_trends",
                state=SourceState.UNAVAILABLE,
                message="Install the trends extra to enable this optional signal.",
                official_api=False,
            )

        checked = 0
        failed = 0
        for game in games[:5]:
            try:
                game.trend = await asyncio.to_thread(self._collect_one, game.name)
                checked += 1
            except Exception as exc:
                game.trend = TrendSignal(
                    geo=self.settings.country,
                    state=SourceState.FAILED,
                    note=f"Trends request failed: {exc}",
                )
                failed += 1
            await asyncio.sleep(0.5)
        state = SourceState.OK if checked and not failed else SourceState.PARTIAL
        return games, SourceStatus(
            source="google_trends",
            state=state,
            message=f"Checked {checked} games; {failed} failed. Maximum budget is 5 games.",
            official_api=False,
            records=checked,
        )
