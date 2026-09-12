"""Google Trends Trending Now RSS discovery, no API key required."""
from __future__ import annotations
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
import httpx

RSS_URL = "https://trends.google.com/trending/rss"


def _tag(node, name: str):
    for child in node:
        if child.tag.rsplit('}', 1)[-1].casefold() == name.casefold():
            return (child.text or '').strip()
    return ""


def parse_trending_rss(xml: bytes, *, geo: str) -> list[dict]:
    root = ET.fromstring(xml)
    rows = []
    for item in root.iter():
        if item.tag.rsplit('}', 1)[-1].casefold() != 'item':
            continue
        title = _tag(item, 'title')
        if not title:
            continue
        published_raw = _tag(item, 'pubDate')
        try:
            published = parsedate_to_datetime(published_raw).isoformat() if published_raw else None
        except (TypeError, ValueError):
            published = None
        rows.append({
            'source':'google_trends_rss',
            'source_id':f'google-trends-rss:{geo.upper()}',
            'query_or_topic':title,
            'candidate_game':title,
            'candidate_task':None,
            'region':geo.upper(),
            'published_at':published,
            'observed_at':datetime.now(timezone.utc).isoformat(),
            'source_url':_tag(item, 'link') or None,
            'approx_traffic':_tag(item, 'approx_traffic') or None,
            'confidence':'low',
            'evidence_type':'trend_discovery',
            'note':'Trending topic only; not absolute search volume and not yet a resolved game entity.',
        })
    return rows


async def fetch_trending_rss(*, geo: str = 'US', timeout: float = 15,
                             client: httpx.AsyncClient | None = None) -> list[dict]:
    owns = client is None
    client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True,
        headers={'User-Agent':'GameKeywordRadar/2.2 local research'})
    try:
        response = await client.get(RSS_URL, params={'geo':geo.upper()})
        response.raise_for_status()
        return parse_trending_rss(response.content, geo=geo)
    finally:
        if owns:
            await client.aclose()
