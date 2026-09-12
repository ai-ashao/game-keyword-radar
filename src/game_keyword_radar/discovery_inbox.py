"""Append-only discovery inbox for low-cost candidate hints.

Hints are not GameEntity facts. They stay separate until entity resolution/manual review.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DiscoveryInbox:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "discovery_inbox"

    @staticmethod
    def _key(row: dict) -> str:
        identity = {
            "source": row.get("source"),
            "source_id": row.get("source_id"),
            "canonical_url": row.get("canonical_url"),
            "query_or_topic": row.get("query_or_topic"),
            "candidate_game": row.get("candidate_game"),
            "candidate_task": row.get("candidate_task"),
            "region": row.get("region"),
        }
        raw = json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def append_many(self, rows: list[dict]) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        added = duplicates = 0
        for raw in rows:
            row = dict(raw)
            row.setdefault("inbox_status", "unresolved_entity")
            row.setdefault("stored_at", _now())
            digest = self._key(row)
            path = self.root / f"{digest}.json"
            if path.exists():
                # Keep first_seen immutable; update only last_seen and latest payload.
                try:
                    previous = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    previous = {}
                row["first_seen_at"] = previous.get("first_seen_at") or previous.get("stored_at") or row.get("first_seen_at") or row["stored_at"]
                row["last_seen_at"] = _now()
                path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                duplicates += 1
            else:
                row.setdefault("first_seen_at", row["stored_at"])
                row["last_seen_at"] = row["stored_at"]
                path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                added += 1
        return {"added": added, "duplicates": duplicates, "total_input": len(rows)}

    def list(self, limit: int = 100) -> list[dict]:
        result = []
        for path in self.root.glob("*.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            row["_id"] = path.stem
            result.append(row)
        result.sort(key=lambda r: r.get("last_seen_at") or r.get("stored_at") or "", reverse=True)
        return result[:limit]
