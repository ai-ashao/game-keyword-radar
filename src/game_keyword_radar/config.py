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
