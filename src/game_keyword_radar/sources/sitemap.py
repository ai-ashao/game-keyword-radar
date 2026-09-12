"""Low-cost Sitemap/Sitemap-Index incremental discovery.

A first successful read establishes a baseline and emits no "new market event".
Partial reads never infer deletions.  URL-derived candidates are discovery hints only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import httpx

TRACKING_KEYS = {"gclid", "fbclid", "msclkid", "mc_cid", "mc_eid"}
TASK_WORDS = {
    "codes", "wiki", "guide", "guides", "walkthrough", "calculator", "tracker",
    "build", "builds", "tier-list", "tierlist", "locations", "map", "database",
    "boss", "items", "item", "characters", "weapons", "classes", "faq", "fix",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_KEYS]
    query.sort()
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


@dataclass(frozen=True)
class SitemapEntry:
    url: str
    lastmod: str | None = None


@dataclass
class SitemapResult:
    source_id: str
    observed_at: str
    coverage_status: str
    baseline_created: bool
    total_entries: int
    new_entries: list[dict]
    errors: list[str]


class SitemapScanner:
    def __init__(self, data_dir: Path, *, timeout: float = 15, max_entries: int = 5000,
                 max_depth: int = 2, client: httpx.AsyncClient | None = None):
        self.data_dir = data_dir
        self.max_entries = max_entries
        self.max_depth = max_depth
        self.client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True,
            headers={"User-Agent": "GameKeywordRadar/2.2 (+local research; sitemap only)"})
        self._owns_client = client is None

    async def close(self):
        if self._owns_client:
            await self.client.aclose()

    async def _fetch(self, url: str) -> bytes:
        response = await self.client.get(url)
        response.raise_for_status()
        return response.content

    @staticmethod
    def _parse(xml: bytes) -> tuple[str, list[SitemapEntry]]:
        root = ET.fromstring(xml)
        tag = root.tag.rsplit("}", 1)[-1].lower()
        rows = []
        for node in root:
            values = {child.tag.rsplit("}", 1)[-1].lower(): (child.text or "").strip() for child in node}
            if values.get("loc"):
                rows.append(SitemapEntry(canonical_url(values["loc"]), values.get("lastmod") or None))
        return tag, rows

    async def _walk(self, url: str, depth: int, seen_maps: set[str], errors: list[str]) -> list[SitemapEntry]:
        if depth > self.max_depth or len(seen_maps) > 100:
            errors.append(f"coverage limit reached at {url}")
            return []
        url = canonical_url(url)
        if url in seen_maps:
            return []
        seen_maps.add(url)
        try:
            kind, rows = self._parse(await self._fetch(url))
        except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
            errors.append(f"{url}: {type(exc).__name__}: {str(exc)[:240]}")
            return []
        if kind == "sitemapindex":
            result: list[SitemapEntry] = []
            for row in rows:
                if len(result) >= self.max_entries:
                    errors.append("entry limit reached")
                    break
                result.extend(await self._walk(row.url, depth + 1, seen_maps, errors))
            return result[:self.max_entries]
        return rows[:self.max_entries]

    def _baseline_path(self, source_id: str) -> Path:
        digest = hashlib.sha256(source_id.encode()).hexdigest()[:16]
        return self.data_dir / "sitemap_baselines" / f"{digest}.json"

    @staticmethod
    def infer_candidate(url: str) -> dict:
        parts = [p for p in urlsplit(url).path.split("/") if p]
        clean = [re.sub(r"[-_]+", " ", p).strip() for p in parts]
        task = next((p for p in reversed(clean) if p.replace(" ", "-").casefold() in TASK_WORDS), None)
        game = None
        if clean:
            # Prefer the segment immediately before a known task; otherwise keep the last slug as low-confidence hint.
            if task:
                idx = clean.index(task)
                game = clean[idx - 1] if idx > 0 else None
            if not game:
                game = clean[-2] if len(clean) >= 2 and clean[-1].casefold() in TASK_WORDS else clean[-1]
        return {"candidate_game": game, "candidate_task": task, "confidence": "low"}

    async def scan(self, source_id: str, sitemap_url: str) -> SitemapResult:
        observed = utc_now()
        errors: list[str] = []
        rows = await self._walk(sitemap_url, 0, set(), errors)
        unique = {row.url: row for row in rows}
        coverage = "partial" if errors else "complete"
        path = self._baseline_path(source_id)
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            previous_urls = set(previous.get("urls", []))
            baseline_created = False
        except (FileNotFoundError, OSError, ValueError, TypeError):
            previous_urls = set()
            baseline_created = True
        current_urls = set(unique)
        new_urls = [] if baseline_created else sorted(current_urls - previous_urls)
        # Save the latest successful observed set. On partial coverage, union with prior prevents fake re-adds next run.
        persisted = current_urls if coverage == "complete" else current_urls | previous_urls
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"source_id": source_id, "sitemap_url": canonical_url(sitemap_url),
                   "observed_at": observed.isoformat(), "coverage_status": coverage,
                   "urls": sorted(persisted)}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        new_entries = []
        for url in new_urls:
            row = unique[url]
            new_entries.append({"source_id": source_id, "canonical_url": url,
                "observed_at": observed.isoformat(), "first_seen_at": observed.isoformat(),
                "lastmod": row.lastmod, "coverage_status": coverage, **self.infer_candidate(url)})
        return SitemapResult(source_id=source_id, observed_at=observed.isoformat(), coverage_status=coverage,
            baseline_created=baseline_created, total_entries=len(current_urls), new_entries=new_entries, errors=errors)
