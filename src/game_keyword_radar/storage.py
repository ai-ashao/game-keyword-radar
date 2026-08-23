from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from game_keyword_radar.config import Settings
from game_keyword_radar.models import ScanSnapshot, SnapshotSummary


class SnapshotStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    def ensure_directories(self) -> None:
        for directory in (
            self.settings.data_dir / "raw",
            self.settings.data_dir / "processed",
            self.settings.reports_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _atomic_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
                handle.write("\n")
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _stamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

    @staticmethod
    def _safe_run_id(run_id: str) -> bool:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
        return bool(run_id) and all(character in allowed for character in run_id)

    def save_raw(self, source: str, payload: dict[str, Any]) -> Path:
        self.ensure_directories()
        path = self.settings.data_dir / "raw" / f"{self._stamp()}-{source}.json"
        self._atomic_json(path, payload)
        return path

    def save_snapshot(self, snapshot: ScanSnapshot) -> Path:
        self.ensure_directories()
        payload = snapshot.model_dump(mode="json")
        processed = self.settings.data_dir / "processed" / f"{snapshot.run_id}-snapshot.json"
        latest = self.settings.data_dir / "latest.json"
        self._atomic_json(processed, payload)
        self._atomic_json(latest, payload)
        return processed

    def load_latest(self) -> ScanSnapshot | None:
        path = self.settings.data_dir / "latest.json"
        if not path.exists():
            return None
        return ScanSnapshot.model_validate_json(path.read_text(encoding="utf-8"))

    def list_snapshots(self) -> list[SnapshotSummary]:
        processed = self.settings.data_dir / "processed"
        if not processed.exists():
            return []
        summaries: list[SnapshotSummary] = []
        for path in processed.glob("*-snapshot.json"):
            try:
                snapshot = ScanSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if (
                not self._safe_run_id(snapshot.run_id)
                or path.name != f"{snapshot.run_id}-snapshot.json"
            ):
                continue
            summaries.append(
                SnapshotSummary(
                    run_id=snapshot.run_id,
                    generated_at=snapshot.generated_at,
                    country=snapshot.country,
                    language=snapshot.language,
                    is_demo=snapshot.is_demo,
                    state=snapshot.state,
                    games_count=len(snapshot.games),
                    opportunities_count=len(snapshot.opportunities),
                )
            )
        return sorted(summaries, key=lambda item: item.generated_at, reverse=True)

    def load_snapshot(self, run_id: str) -> ScanSnapshot | None:
        if not self._safe_run_id(run_id):
            return None
        path = self.settings.data_dir / "processed" / f"{run_id}-snapshot.json"
        if not path.is_file():
            return None
        try:
            snapshot = ScanSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return snapshot if snapshot.run_id == run_id else None
