from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    country: str = Field(default_factory=lambda: os.getenv("GKR_COUNTRY", "US"))
    language: str = Field(default_factory=lambda: os.getenv("GKR_LANGUAGE", "english"))
    request_timeout: float = Field(
        default_factory=lambda: float(os.getenv("GKR_REQUEST_TIMEOUT", "15")),
        gt=0,
        le=60,
    )
    max_concurrency: int = Field(
        default_factory=lambda: int(os.getenv("GKR_MAX_CONCURRENCY", "4")),
        ge=1,
        le=10,
    )
    default_limit: int = Field(
        default_factory=lambda: int(os.getenv("GKR_DEFAULT_LIMIT", "10")),
        ge=1,
        le=30,
    )
    trends_enabled: bool = Field(
        default_factory=lambda: _env_bool("GKR_TRENDS_ENABLED", False)
    )
    project_root: Path = PROJECT_ROOT

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    # V2: independent, bounded providers. Secrets never enter snapshots or the UI.
    steam_enabled: bool = Field(default_factory=lambda: _env_bool("GKR_STEAM_ENABLED", True))
    twitch_enabled: bool = Field(default_factory=lambda: _env_bool("GKR_TWITCH_ENABLED", True))
    youtube_enabled: bool = Field(default_factory=lambda: _env_bool("GKR_YOUTUBE_ENABLED", True))
    reddit_enabled: bool = Field(default_factory=lambda: _env_bool("GKR_REDDIT_ENABLED", True))
    discovery_limit: int = Field(default=80, ge=1, le=100)
    deep_analysis_limit: int = Field(default=10, ge=0, le=30)
    twitch_client_id: str = Field(default_factory=lambda: os.getenv("TWITCH_CLIENT_ID", ""), repr=False, exclude=True)
    twitch_client_secret: str = Field(default_factory=lambda: os.getenv("TWITCH_CLIENT_SECRET", ""), repr=False, exclude=True)
    youtube_api_key: str = Field(default_factory=lambda: os.getenv("YOUTUBE_API_KEY", ""), repr=False, exclude=True)
    twitch_max_stream_pages: int = Field(default=3, ge=1, le=10)
    twitch_sample_pages: int = Field(default=3, ge=1, le=10)
    youtube_search_budget: int = Field(default=20, ge=0, le=100)
    youtube_daily_search_budget: int = Field(default=80, ge=0, le=100)
    youtube_video_budget: int = Field(default=30, ge=0, le=100)
    youtube_queries_per_game: int = Field(default=2, ge=1, le=4)
    youtube_region: str = "US"
    youtube_language: str = "en"
    reddit_subreddits: list[str] = Field(default_factory=lambda: ["gaming", "Steam"])
    reddit_max_requests: int = Field(default=30, ge=0, le=120)
    trends_provider: str = "legacy"
    trends_geo: str = "US"
    trends_timeframe: str = "today 1-m"
    cache_ttl_seconds: int = Field(default=3600, ge=0, le=86400)
    twitch_cache_ttl_seconds: int = Field(default=900, ge=0, le=86400)
    history_24h_tolerance_hours: float = Field(default=6, gt=0, le=12)
    history_7d_tolerance_hours: float = Field(default=24, gt=0, le=48)
    entity_overrides: list[dict] = Field(default_factory=list)
    existing_sites: dict[str, list[str]] = Field(default_factory=lambda: {
        "WorkshopFetch": ["steam workshop", "workshop download", "steamcmd"],
        "FN Sprite Hub": ["fortnite sprite"],
        "GameKitHQ": ["calculator", "tracker", "generator", "planner"],
    })

    @classmethod
    def load(cls, project_root: Path | None = None) -> "Settings":
        """Read local .env + optional radar.toml. No evaluation or shell expansion."""
        import shlex
        import tomllib
        root = (project_root or PROJECT_ROOT).resolve()
        env = root / ".env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.removeprefix("export ").split("=", 1)
                key = key.strip()
                if not key.replace("_", "").isalnum():
                    continue
                try:
                    parts = shlex.split(value, comments=True)
                except ValueError:
                    continue
                os.environ.setdefault(key, " ".join(parts))
        config = root / "radar.toml"
        payload = tomllib.loads(config.read_text(encoding="utf-8")) if config.is_file() else {}
        accepted: dict = {}
        sections = {"sources": {k: f"{k}_enabled" for k in ["steam", "twitch", "trends", "youtube", "reddit"]},
                    "scan": {}, "budgets": {}, "markets": {"steam_country": "country"}, "history": {}}
        for section, mapping in sections.items():
            for key, value in payload.get(section, {}).items():
                target = mapping.get(key, key)
                if target not in cls.model_fields:
                    raise ValueError(f"Unknown radar.toml setting: {section}.{key}")
                accepted[target] = value
        for key in ("existing_sites", "entity_overrides"):
            if key in payload:
                accepted[key] = payload[key]
        accepted["project_root"] = root
        if "country" in accepted:
            accepted.setdefault("trends_geo", accepted["country"])
            accepted.setdefault("youtube_region", accepted["country"])
        return cls(**accepted)
