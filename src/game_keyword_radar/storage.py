from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from contextlib import contextmanager
from uuid import uuid4
import fcntl

from game_keyword_radar.config import Settings
from game_keyword_radar.models import ScanSnapshot, SnapshotSummary, GameEntity, ValidationRecord


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
        return bool(run_id) and run_id not in {".", ".."} and len(run_id) <= 160 and all(character in allowed for character in run_id)

    def save_raw(self, source: str, payload: dict[str, Any]) -> Path:
        if not self._safe_run_id(source):
            raise ValueError("Invalid source identifier")
        self.ensure_directories()
        path = self.settings.data_dir / "raw" / source / f"{self._stamp()}-{uuid4().hex[:8]}.json"
        self._atomic_json(path, payload)
        return path

    def save_snapshot(self, snapshot: ScanSnapshot) -> Path:
        if not self._safe_run_id(snapshot.run_id):
            raise ValueError("Invalid run ID")
        self.ensure_directories()
        payload = snapshot.model_dump(mode="json")
        processed = self.settings.data_dir / "processed" / f"{snapshot.run_id}-snapshot.json"
        # Run IDs identify immutable evidence. Loading V1 never migrates it on disk.
        if processed.exists():
            if json.loads(processed.read_text(encoding="utf-8")) != payload:
                raise ValueError("Snapshot ID already exists; use a new run ID")
            return processed
        self._atomic_json(processed, payload)
        self._atomic_json(self.settings.data_dir / "last-attempt.json", payload)
        if snapshot.games or snapshot.entities:
            latest = self.load_latest()
            if snapshot.is_demo:
                self._atomic_json(self.settings.data_dir / "latest-demo.json", payload)
            else:
                self._atomic_json(self.settings.data_dir / "latest-live.json", payload)
            # A fixture must not replace a user's live default view.
            if not snapshot.is_demo or latest is None or latest.is_demo:
                self._atomic_json(self.settings.data_dir / "latest.json", payload)
        self._atomic_json(self.settings.data_dir / "history-index.json",
                          [s.model_dump(mode="json") for s in self.list_snapshots()])
        return processed

    def load_latest(self) -> ScanSnapshot | None:
        path = self.settings.data_dir / "latest.json"
        if not path.exists():
            return None
        try:
            return ScanSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def load_entities(self) -> list[GameEntity]:
        path = self.settings.data_dir / "entities.json"
        if not path.exists():
            return []
        try:
            return [GameEntity.model_validate(e) for e in json.loads(path.read_text(encoding="utf-8"))]
        except (OSError, ValueError):
            # Fail visibly instead of replacing an unreadable registry with a new one.
            raise ValueError("entities.json is unreadable; restore or repair the local entity registry")

    def save_entities(self, entities: list[GameEntity]) -> None:
        self._atomic_json(self.settings.data_dir / "entities.json", [e.model_dump(mode="json") for e in entities])

    @contextmanager
    def scan_lock(self):
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        with (self.settings.data_dir / ".scan.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another CLI or Dashboard scan is already running")
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

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
