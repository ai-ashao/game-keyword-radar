"""Persistent circuit-breaker state for optional best-effort providers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


class BestEffortCircuitBreaker:
    def __init__(self, data_dir: Path, provider: str, *, failure_limit: int = 3, cooldown_hours: int = 24):
        self.path = data_dir / "provider_state" / f"{provider}.json"
        self.provider = provider
        self.failure_limit = failure_limit
        self.cooldown = timedelta(hours=cooldown_hours)

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def allowed(self, now: datetime | None = None) -> tuple[bool, str]:
        now = now or self._now()
        state = self._load()
        raw = state.get("disabled_until")
        if raw:
            try:
                until = datetime.fromisoformat(raw)
                if until.tzinfo and until > now:
                    return False, f"circuit open until {until.isoformat()}"
            except ValueError:
                pass
        return True, "ready"

    def success(self, now: datetime | None = None) -> None:
        now = now or self._now()
        state = self._load()
        state.update({
            "provider": self.provider,
            "failure_count": 0,
            "last_success_at": now.isoformat(),
            "last_failure_reason": "",
            "retry_after": None,
            "disabled_until": None,
        })
        self._save(state)

    def failure(self, reason: str, *, kind: str = "failed", now: datetime | None = None) -> None:
        now = now or self._now()
        state = self._load()
        count = int(state.get("failure_count") or 0) + 1
        state.update({
            "provider": self.provider,
            "failure_count": count,
            "last_failure_at": now.isoformat(),
            "last_failure_reason": reason[:800],
            "last_failure_kind": kind,
        })
        if count >= self.failure_limit and kind in {"blocked", "rate_limited", "parse_failed", "failed"}:
            until = now + self.cooldown
            state["retry_after"] = until.isoformat()
            state["disabled_until"] = until.isoformat()
        self._save(state)

    def state(self) -> dict:
        return self._load()
