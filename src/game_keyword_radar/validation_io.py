"""Portable search-validation packs and append-only CSV evidence imports."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Iterable


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _norm(name: str) -> str:
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def freshness_status(checked_at: datetime, *, fresh_days: int = 14, stale_days: int = 45, now: datetime | None = None) -> str:
    now = now or _now()
    age = (now - checked_at).days
    return "fresh" if age <= fresh_days else "aging" if age <= stale_days else "stale"


def validation_rows(snapshot) -> list[dict]:
    entities = {e.slug: e for e in snapshot.entities}
    games = {g.game_slug: g for g in snapshot.game_opportunities}
    decisions = {d.game_slug: d for d in snapshot.selection_decisions}
    rows = []
    for page in snapshot.page_opportunities:
        entity = entities.get(page.game_slug)
        game = games.get(page.game_slug)
        decision = decisions.get(page.game_slug)
        rows.append({
            "run_id": snapshot.run_id,
            "game_slug": page.game_slug,
            "game_name": entity.canonical_name if entity else page.game_slug,
            "platform_ids": json.dumps(entity.platform_ids if entity else {}, ensure_ascii=False, sort_keys=True),
            "page_id": page.id,
            "page_type": page.page_type,
            "keyword": page.primary_keyword_hypothesis,
            "supporting_queries": " | ".join(page.supporting_queries[:20]),
            "evidence_level": page.evidence_level,
            "question_count": page.question_count,
            "content_proxy_count": page.content_proxy_count,
            "action": game.action if game else "WATCH",
            "why_now": " | ".join(decision.reasons) if decision else "",
            "missing_evidence": "Semrush Volume/KD/Intent; Trends; SERP intent/competition",
            "market": snapshot.country,
            "language": snapshot.language,
        })
    return rows


def export_validation_pack(snapshot, path: Path) -> Path:
    rows = validation_rows(snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".md":
        lines = [f"# Validation Pack · {snapshot.run_id}", ""]
        for row in rows:
            lines += [f"## {row['game_name']} · {row['keyword']}", "",
                      f"- Page: `{row['page_id']}` / `{row['page_type']}`",
                      f"- Action: **{row['action']}**", f"- WHY NOW: {row['why_now'] or 'n/a'}",
                      f"- Evidence: {row['evidence_level']} (questions={row['question_count']}, proxies={row['content_proxy_count']})",
                      f"- Validate: {row['missing_evidence']}", ""]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
    fields = list(rows[0].keys()) if rows else ["run_id", "game_slug", "page_id", "keyword", "market", "language"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    return path


class SearchEvidenceStore:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "search_evidence"

    def _append_unique(self, kind: str, rows: Iterable[dict]) -> dict:
        folder = self.root / kind
        folder.mkdir(parents=True, exist_ok=True)
        added = duplicates = 0
        for row in rows:
            raw = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
            digest = hashlib.sha256(raw.encode()).hexdigest()
            path = folder / f"{digest}.json"
            if path.exists():
                duplicates += 1; continue
            path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            added += 1
        return {"added": added, "duplicates": duplicates}

    def import_semrush(self, path: Path, *, market: str, language: str = "english", checked_at: datetime | None = None) -> dict:
        checked_at = checked_at or _now()
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            headers = {_norm(h): h for h in (reader.fieldnames or [])}
            def col(*names):
                return next((headers[_norm(n)] for n in names if _norm(n) in headers), None)
            keyword_col = col("Keyword", "Query")
            if not keyword_col:
                raise ValueError("Semrush CSV must contain a Keyword/Query column")
            mappings = {
                "volume": col("Volume", "Search Volume"), "kd": col("KD", "KD %", "Keyword Difficulty"),
                "intent": col("Intent"), "trend": col("Trend"), "cpc": col("CPC"),
                "competition": col("Competition", "Com."),
            }
            rows = []
            for raw in reader:
                record = {"kind":"semrush", "keyword":raw.get(keyword_col,"").strip(), "market":market,
                    "language":language, "checked_at":checked_at.isoformat(),
                    "freshness_status":freshness_status(checked_at), "source_file":path.name,
                    "raw":raw, "metrics":{k:(raw.get(v) if v else None) for k,v in mappings.items()}}
                if record["keyword"]: rows.append(record)
        return {**self._append_unique("semrush", rows), "rows":len(rows), "missing_columns":[k for k,v in mappings.items() if not v]}

    def import_trends(self, path: Path, *, geo: str, timeframe: str, search_type: str = "web", checked_at: datetime | None = None) -> dict:
        checked_at = checked_at or _now()
        # Keep Trends rows verbatim: relative indices must never be rewritten as absolute volume.
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        record = {"kind":"google_trends_csv", "geo":geo, "timeframe":timeframe,
            "search_type":search_type, "checked_at":checked_at.isoformat(),
            "freshness_status":freshness_status(checked_at), "source_file":path.name,
            "relative_only":True, "rows":rows}
        result = self._append_unique("trends", [record])
        return {**result, "rows":len(rows)}
