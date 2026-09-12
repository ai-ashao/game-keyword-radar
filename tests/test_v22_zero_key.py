from datetime import datetime, timezone
from pathlib import Path
import httpx
import pytest

from game_keyword_radar.analyzers.entity_resolution import EntityResolver
from game_keyword_radar.analyzers.question_mining import mine_questions
from game_keyword_radar.models import GameEntity, PlatformSignal, EvidenceItem
from game_keyword_radar.observations import comparable
from game_keyword_radar.provider_state import BestEffortCircuitBreaker
from game_keyword_radar.sources.sitemap import SitemapScanner


def test_cross_platform_same_name_is_suggestion_not_auto_merge():
    existing = [GameEntity(canonical_name="Peak", slug="peak", platform_ids={"steam":"100"})]
    resolver = EntityResolver(existing)
    twitch = resolver.resolve("Peak", "twitch", "200")
    assert twitch.slug != "peak"
    assert twitch.needs_review is True
    assert twitch.match_method == "unresolved_cross_platform_name"
    assert any(s.get("resolution_status") == "unresolved_entity" for s in resolver.suggestions)




def test_same_platform_same_name_different_id_is_not_auto_merged():
    existing = [GameEntity(canonical_name="Peak", slug="peak", platform_ids={"steam":"100"})]
    resolver = EntityResolver(existing)
    other = resolver.resolve("Peak", "steam", "999")
    assert other.slug != "peak"
    assert other.platform_ids["steam"] == "999"
    assert resolver.entities[0].platform_ids["steam"] == "100"
    assert other.match_method == "unresolved_platform_id_conflict"

def test_manual_override_allows_verified_cross_platform_merge():
    existing = [GameEntity(canonical_name="Peak", slug="peak", platform_ids={"steam":"100"})]
    resolver = EntityResolver(existing, [{"canonical_name":"Peak","slug":"peak","platform_ids":{"steam":"100","twitch":"200"}}])
    twitch = resolver.resolve("Peak", "twitch", "200")
    assert twitch.slug == "peak"
    assert twitch.needs_review is False


def test_scope_comparison_rejects_different_providers_and_markets():
    now=datetime.now(timezone.utc)
    a=PlatformSignal(source="youtube",game_slug="x",market="US",captured_at=now,
        metrics={"provider":"youtube_data_api","measurement":"recent_search"},scope_version="v1")
    b=PlatformSignal(source="youtube",game_slug="x",market="US",captured_at=now,
        metrics={"provider":"yt_dlp_public","measurement":"public_search_sample"},scope_version="v1")
    c=a.model_copy(update={"market":"FR"})
    assert not comparable(a,b)
    assert not comparable(a,c)


def test_task_level_error_clusters_split_distinct_jobs():
    e=GameEntity(canonical_name="Game X",slug="game-x")
    s=PlatformSignal(source="reddit",game_slug=e.slug,evidence=[
        EvidenceItem(id="1",source="reddit",title="Game X crashes on startup"),
        EvidenceItem(id="2",source="reddit",title="Game X microphone not working"),
        EvidenceItem(id="3",source="reddit",title="Game X audio not working"),
    ])
    clusters=mine_questions(e,[s])
    ids={c.id for c in clusters}
    assert "game-x:errors:startup-crash" in ids
    assert "game-x:errors:microphone" in ids
    assert "game-x:errors:audio" in ids


@pytest.mark.asyncio
async def test_sitemap_first_read_is_baseline_then_only_real_increment(tmp_path: Path):
    first=b'''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://x.test/game-a/guide</loc></url></urlset>'''
    second=b'''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://x.test/game-a/guide</loc></url><url><loc>https://x.test/game-b/codes</loc></url></urlset>'''
    calls=0
    def handler(request):
        nonlocal calls
        calls+=1
        return httpx.Response(200,content=first if calls==1 else second)
    client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    scanner=SitemapScanner(tmp_path,client=client)
    a=await scanner.scan("site","https://x.test/sitemap.xml")
    b=await scanner.scan("site","https://x.test/sitemap.xml")
    await client.aclose()
    assert a.baseline_created is True and a.new_entries == []
    assert b.baseline_created is False and len(b.new_entries) == 1


def test_best_effort_circuit_breaker(tmp_path: Path):
    breaker=BestEffortCircuitBreaker(tmp_path,"youtube-public",failure_limit=2,cooldown_hours=1)
    assert breaker.allowed()[0]
    breaker.failure("first")
    assert breaker.allowed()[0]
    breaker.failure("second")
    assert not breaker.allowed()[0]


def test_trends_rss_parser_keeps_topic_relative(tmp_path: Path):
    from game_keyword_radar.sources.trends_rss import parse_trending_rss
    xml=b'''<rss xmlns:ht="https://trends.google.com/trending/rss"><channel><item><title>Game X</title><pubDate>Sat, 12 Sep 2026 00:00:00 GMT</pubDate><ht:approx_traffic>20K+</ht:approx_traffic><link>https://example.test/x</link></item></channel></rss>'''
    rows=parse_trending_rss(xml,geo='US')
    assert rows[0]['query_or_topic']=='Game X'
    assert rows[0]['evidence_type']=='trend_discovery'
    assert 'volume' not in rows[0]


def test_discovery_inbox_deduplicates_without_promoting_entity(tmp_path: Path):
    from game_keyword_radar.discovery_inbox import DiscoveryInbox
    inbox=DiscoveryInbox(tmp_path)
    row={'source':'sitemap','source_id':'a','canonical_url':'https://x/game-a/guide','candidate_game':'game a'}
    assert inbox.append_many([row])['added']==1
    assert inbox.append_many([row])['duplicates']==1
    stored=inbox.list()
    assert stored[0]['inbox_status']=='unresolved_entity'
