from __future__ import annotations

from pathlib import Path

from game_keyword_radar.collectors.steam import SteamCollector


FIXTURE = Path(__file__).parent / "fixtures" / "steam_search.html"


def test_parse_search_results_extracts_rank_and_fields():
    rows = SteamCollector.parse_search_results(
        FIXTURE.read_text(encoding="utf-8"), source="top_sellers", limit=10
    )
    assert [row.app_id for row in rows] == ["101", "202"]
    assert rows[0].name == "Alpha Game"
    assert rows[0].rank == 1
    assert rows[0].image_url == "https://example.com/alpha.jpg"


def test_parse_search_results_respects_limit():
    rows = SteamCollector.parse_search_results(
        FIXTURE.read_text(encoding="utf-8"), source="popular_new", limit=1
    )
    assert len(rows) == 1
    assert rows[0].source == "popular_new"


def test_parse_search_results_handles_empty_html():
    assert SteamCollector.parse_search_results("", source="top_sellers", limit=10) == []


def test_parse_search_results_ignores_invalid_appid():
    html = '<a class="search_result_row" data-ds-appid="bundle"><span class="title">Bundle</span></a>'
    assert SteamCollector.parse_search_results(html, source="top_sellers", limit=10) == []


def test_parse_release_date_handles_unknown_value():
    assert SteamCollector._parse_release_date({"release_date": {"date": "Coming soon"}}) is None


def test_parse_release_date_handles_standard_date():
    value = SteamCollector._parse_release_date({"release_date": {"date": "Aug 9, 2026"}})
    assert value is not None
    assert value.date().isoformat() == "2026-08-09"
