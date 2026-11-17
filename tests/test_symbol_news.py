"""Hermetic contract tests for symbol-news aggregation and all four callers."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tapebasis import tools_finviz, tools_market, tools_tradingview
from tapebasis.freshness import parse_news_timestamp
from tapebasis.news import NEWS_LIMIT, merge_news
from tapebasis.providers_state import ProviderError
from tapebasis.symbols import Resolution


REFERENCE = datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc)


def story(
    title: str,
    published: object,
    url: str,
    source: str = "Newswire",
) -> dict[str, object]:
    """Return one normalized provider item with explicit publication evidence."""
    return {"title": title, "published": published, "url": url, "source": source}


def resolved(query: str, provider: str) -> Resolution:
    """Return a provider-native symbol resolution without network discovery."""
    return Resolution(
        query=query,
        provider=provider,
        symbol="NASDAQ:AAPL" if provider == "TRADINGVIEW" else "AAPL",
        method="explicit",
        confidence=1.0,
    )


@pytest.fixture
def resolved_news_calls(monkeypatch):
    """Replace symbol discovery with direct Apple resolutions in every feed."""
    from tapebasis import symbols

    async def fake_resolve(query, provider, **kwargs):
        return resolved(query, provider)

    monkeypatch.setattr(symbols, "resolve", fake_resolve)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Nov-16-26 06:02PM", "2026-11-16T23:02:00+00:00"),
        ("Today 02:47AM", "2026-11-17T07:47:00+00:00"),
        ("04:58PM", "2026-11-17T21:58:00+00:00"),
        ("not a publication time", None),
    ],
)
def test_finviz_news_timestamps(raw, expected):
    """Normalize Finviz wall clocks to UTC and reject unknown time honestly."""
    parsed = parse_news_timestamp(raw, reference=REFERENCE)
    assert (parsed.isoformat() if parsed else None) == expected
    if parsed:
        assert parsed.isoformat() == expected


def test_same_url_and_title_produce_provider_consensus():
    """Recognize rewritten titles on one URL and exact syndicated headlines."""
    result = merge_news({
        "FINVIZ": [
            story("Apple opens Austin research campus", 1794912000, "https://news.test/apple"),
            story("Apple raises quarterly revenue guidance", 1794835600, "https://a.test/2"),
        ],
        "TRADINGVIEW": [
            story("AAPL starts new Austin research campus", 1794912060,
                  "HTTPS://WWW.NEWS.TEST/apple/?utm_source=feed"),
            story("Apple raises quarterly revenue guidance", 1794835600, "https://b.test/3"),
        ],
    })
    assert result["items"][0]["providers"] == ["TRADINGVIEW", "FINVIZ"]
    assert result["items"][0]["matching"] == ["same_url"]
    assert result["items"][1]["matching"] == ["same_title"]
    assert all(item["consensus"] for item in result["items"])
    assert result["items"][0]["consensus_kind"] == "provider_corroboration"


def test_similar_titles_match_but_unrelated_company_news_does_not():
    """Require substantial shared wording, not a shared company name."""
    result = merge_news({
        "FINVIZ": [
            story("Apple wins regulatory approval for new payment service", 1794912000, "https://a.test/1"),
            story("Apple faces antitrust trial in France next month", 1794911900, "https://a.test/2"),
        ],
        "YAHOO": [
            story("Apple wins approval from regulators to launch payment service", 1794912060, "https://b.test/1"),
            story("Apple supplier expands chip production in Arizona", 1794911800, "https://b.test/2"),
        ],
    })
    assert result["count"] == 3
    assert result["consensus_count"] == 1
    assert result["items"][0]["matching"] == ["similar_title"]


def test_same_provider_duplicates_never_gain_consensus():
    """Collapse provider-internal repeats without inventing corroboration."""
    feeds = {"FINVIZ": [
        story("Apple raises quarterly revenue guidance", 1, "https://a.test/story"),
        story("A different Apple headline", 2, "https://a.test/story"),
    ]}
    feeds["FINVIZ"] = list(reversed(feeds["FINVIZ"]))
    result = merge_news(feeds)
    assert result["count"] == 1
    assert result["duplicates_collapsed"] == 1
    assert result["items"][0]["provider_count"] == 1
    assert result["items"][0]["consensus"] is False
    assert result["items"][0]["title"] == "A different Apple headline"


def test_newest_ten_win_even_when_a_provider_was_added_last():
    """Order by publication time, not by provider priority or input order."""
    feeds = {provider: [] for provider in ("TRADINGVIEW", "FINVIZ", "YAHOO")}
    for index in range(12):
        provider = "YAHOO" if index == 0 else "FINVIZ"
        feeds[provider].append(story(
            f"Story number {index}", f"2026-11-{index + 1:02d}T12:00:00Z",
            f"https://news.test/{index}",
        ))
    feeds["TRADINGVIEW"].append(story("Undated story", "unreadable", "https://unrelated.test/1"))
    result = merge_news(feeds)
    assert result["count"] == NEWS_LIMIT == 10
    assert result["items"][0]["title"] == "Story number 11"
    assert "Story number 0" not in {item["title"] for item in result["items"]}
    assert result["items"][-1]["title"] == "Story number 2"
    assert "Undated story" in {item["title"] for item in merge_news(feeds, limit=50)["items"]}
    undated = merge_news({"YAHOO": feeds["TRADINGVIEW"]})["items"][0]
    assert undated["published_at"] is None


def test_fewer_than_ten_real_stories_has_count_and_no_padding():
    """Return actual valid stories and an explicit shortfall, never filler."""
    result = merge_news(
        {"FINVIZ": [story("One real story", 1794912000, "https://a.test/1"), {"title": ""}],
         "YAHOO": [story("Another real story", 1794910000, "https://b.test/2")]},
        errors=[{"provider": "TRADINGVIEW", "code": "NO_DATA", "message": "token missing"}],
    )
    assert result["count"] == 2
    assert len(result["items"]) == 2
    assert result["has_full_limit"] is False
    assert "2 unique valid stories" in result["shortfall_reason"]
    assert "TRADINGVIEW (NO_DATA)" in result["shortfall_reason"]
    assert "no filler" in result["shortfall_reason"]


@pytest.mark.asyncio
async def test_stock_news_merges_all_real_provider_shapes(
    monkeypatch, resolved_news_calls
):
    """Keep Finviz reactions and retain newer Yahoo stories beside Finviz."""
    from tapebasis import fv_access, tv_access, yh_access
    from tapebasis.providers_state import NoDataError

    async def tv_news(symbol, limit=10):
        raise NoDataError("TRADINGVIEW", "MARKETAUX_API_TOKEN not configured")

    async def fv_news(symbol, limit=10, include_reactions=True):
        return {"ticker": symbol, "news": [
            {"headline": "Apple raises quarterly revenue guidance",
             "datetime": "Nov-16-26 06:02PM", "source": "Reuters",
             "url": "https://news.test/apple", "reaction_day_percent": 2.1},
        ]}

    async def yh_news(symbol, limit=10):
        return {"items": [
            story("Apple raises quarterly revenue guidance after strong demand", 1794865320, "https://news.test/apple"),
            story("Yahoo-only latest breaking Apple story", 1795000000, "https://yahoo.test/new"),
        ]}

    monkeypatch.setattr(tv_access, "news", tv_news)
    monkeypatch.setattr(fv_access, "news", fv_news)
    monkeypatch.setattr(yh_access, "news", yh_news)
    result = await tools_market.stock_news("AAPL")
    assert result["data_provider"] == "PARTIAL"
    assert result["data"]["count"] == 2
    assert result["data"]["items"][0]["title"] == "Yahoo-only latest breaking Apple story"
    merged = result["data"]["items"][1]
    assert merged["reaction_day_percent"] == 2.1
    assert merged["providers"] == ["FINVIZ", "YAHOO"]
    assert merged["consensus"] is True
    assert result["data"]["by_provider"]["YAHOO"][1]["title"] == result["data"]["items"][0]["title"]
    assert result["data"]["provider_calls"]["coverage"] == "PARTIAL"
    assert {error["provider"] for error in result["errors"]} == {"TRADINGVIEW"}


@pytest.mark.asyncio
async def test_stock_news_uses_valid_story_coverage_not_empty_http_success(
    monkeypatch, resolved_news_calls
):
    """A payload without headlines is not a data answer, even on HTTP success."""
    from tapebasis import fv_access, tv_access, yh_access

    async def tv_news(symbol, limit=10):
        raise NoDataError("TRADINGVIEW", "MARKETAUX_API_TOKEN not configured")

    async def empty_finviz(symbol, limit=10, include_reactions=True):
        return {"news": [], "count": 0}

    async def yahoo_news(symbol, limit=10):
        return {"items": [story("A real Yahoo report", 1795000000, "https://y.test/1")]}

    monkeypatch.setattr(tv_access, "news", tv_news)
    monkeypatch.setattr(fv_access, "news", empty_finviz)
    monkeypatch.setattr(yh_access, "news", yahoo_news)
    result = await tools_market.stock_news("AAPL")
    assert result["data_provider"] == "YAHOO"
    assert result["providers_answered"] == ["YAHOO"]
    assert result["data"]["data_provider"] == "YAHOO"
    assert result["data"]["count"] == 1
    assert result["data"]["provider_calls"]["answered"] == ["FINVIZ", "YAHOO"]
    assert result["data"]["provider_calls"]["coverage"] == "PARTIAL"


@pytest.mark.asyncio
async def test_stock_news_no_valid_stories_is_not_labelled_complete_coverage(
    monkeypatch, resolved_news_calls
):
    """Successful empty payloads remain auditable but cannot manufacture ALL."""
    from tapebasis import fv_access, tv_access, yh_access
    from tapebasis.providers_state import NoDataError

    async def tv_news(symbol, limit=10):
        raise NoDataError("TRADINGVIEW", "MARKETAUX_API_TOKEN not configured")

    async def empty_feed(symbol, limit=10, **kwargs):
        return {"news": [], "items": [], "count": 0}

    monkeypatch.setattr(tv_access, "news", tv_news)
    monkeypatch.setattr(fv_access, "news", empty_feed)
    monkeypatch.setattr(yh_access, "news", empty_feed)
    result = await tools_market.stock_news("AAPL")
    assert result["data_provider"] == "NONE"
    assert result["data"]["data_provider"] == "NONE"
    assert result["providers_answered"] == []
    assert result["data"]["count"] == 0
    assert result["data"]["provider_calls"]["answered"] == ["FINVIZ", "YAHOO"]
    assert "no filler stories" in result["data"]["shortfall_reason"]


@pytest.mark.asyncio
async def test_market_sentiment_keeps_primary_label_and_labels_news_separately(monkeypatch):
    """Do not attribute Yahoo news to Finviz's locally computed sentiment."""
    from tapebasis import news

    async def fake_sentiment(symbol, limit=20):
        return {"provider": "local-vader", "sentiment_score": 0.2, "sentiment_label": "Bullish"}

    async def fake_news(symbol, **kwargs):
        return {"block": {"items": [], "count": 0, "limit": 10, "unique_stories": 0,
                          "errors": [], "data_provider": "PARTIAL",
                          "providers_answered": ["FINVIZ", "YAHOO"], "endpoints": {},
                          "shortfall_reason": "available feeds supplied no stories"}}

    monkeypatch.setattr(tools_tradingview, "_sentiment_payload", fake_sentiment)
    monkeypatch.setattr(news, "fetch_news", fake_news)
    result = await tools_tradingview.market_sentiment("AAPL")
    assert result["data_provider"] == "FINVIZ"
    assert result["data"]["news"]["data_provider"] == "PARTIAL"
    assert result["fields"]["news"]["source"] is None
    assert result["fields"]["news"]["coverage"] == "PARTIAL"
    assert result["fields"]["news"]["supplied"] == ["FINVIZ", "YAHOO"]
    assert result["fields"]["sentiment_score"]["source"] == "FINVIZ"


@pytest.mark.asyncio
async def test_market_sentiment_unavailable_still_carries_news(monkeypatch):
    """Attach evidence without changing an unavailable sentiment verdict."""
    from tapebasis import news

    async def unavailable(symbol, limit=20):
        return {"provider": "unavailable", "sentiment_score": None,
                "sentiment_label": "Unavailable", "note": "no sentiment material"}

    async def fake_news(symbol, **kwargs):
        return {"block": {"items": [], "count": 0, "limit": 10, "unique_stories": 0,
                          "errors": [], "data_provider": "YAHOO",
                          "providers_answered": ["YAHOO"], "endpoints": {},
                          "shortfall_reason": "one provider supplied no stories"}}

    monkeypatch.setattr(tools_tradingview, "_sentiment_payload", unavailable)
    monkeypatch.setattr(news, "fetch_news", fake_news)
    result = await tools_tradingview.market_sentiment("AAPL")
    assert result["data_provider"] == "NONE"
    assert result["data"]["sentiment_label"] == "Unavailable"
    assert result["fields"]["sentiment_score"]["source"] == "NONE"
    assert result["fields"]["news"]["source"] is None
    assert result["fields"]["news"]["coverage"] == "YAHOO"
    assert result["data"]["news"]["providers_answered"] == ["YAHOO"]
    assert "No sentiment backend could compute a score" in result["notice"]
    assert "News coverage is separate" in result["notice"]
    assert "No provider could supply any data" not in result["notice"]


@pytest.mark.asyncio
async def test_combined_analysis_aggregates_news_without_erasing_price_errors(monkeypatch):
    """Preserve composite provenance, price errors and independently merged news."""
    from tapebasis import fv_access, news, tv_access, yh_access
    from tapebasis.providers_state import NoDataError

    async def technical(symbol, exchange="NASDAQ", timeframe="1D"):
        return {"price_data": {"current_price": 200.0}, "rsi": {"value": 40.0}}

    async def sentiment(symbol, limit=20):
        return {"provider": "local-vader", "sentiment_score": 0.3}

    async def snapshot(symbol):
        return {"numeric": {"Price": 200.0}}

    async def quote(symbol):
        raise NoDataError("YAHOO", "price unavailable in this fixture")

    async def resolve_yahoo(symbol):
        return resolved(symbol, "YAHOO")

    async def fake_news(symbol, **kwargs):
        item = story("Apple latest merged event", 1795000000, "https://news.test/apple")
        return {"block": {"items": [item | {"providers": ["FINVIZ", "YAHOO"]}],
                          "count": 1, "limit": 10, "unique_stories": 1,
                          "errors": [{"provider": "TRADINGVIEW", "code": "NO_DATA"}],
                          "data_provider": "PARTIAL", "providers_answered": ["FINVIZ", "YAHOO"],
                          "endpoints": {"YAHOO": "Yahoo news"},
                          "shortfall_reason": "available feeds supplied 1 unique valid story"}}

    monkeypatch.setattr(tv_access, "technical_analysis", technical)
    monkeypatch.setattr(tools_tradingview, "_sentiment_payload", sentiment)
    monkeypatch.setattr(fv_access, "snapshot", snapshot)
    monkeypatch.setattr(yh_access, "quote", quote)
    monkeypatch.setattr(tools_tradingview, "_yahoo_resolution", resolve_yahoo)
    monkeypatch.setattr(news, "fetch_news", fake_news)
    result = await tools_tradingview.combined_analysis("AAPL")
    assert result["data"]["news"]["items"][0]["providers"] == ["FINVIZ", "YAHOO"]
    assert result["news"]["data_provider"] == "PARTIAL"
    assert {error["provider"] for error in result["errors"]} == {"YAHOO", "TRADINGVIEW"}


@pytest.mark.asyncio
async def test_why_moving_preserves_editorial_failure_and_returns_separate_news(monkeypatch):
    """Never turn a failed editorial leg into Finviz success by merging news."""
    from tapebasis import fv_access, news

    async def broken(symbol):
        raise ProviderError("FINVIZ", "upstream blocked", code="UPSTREAM_BLOCKED")

    async def fake_news(symbol, **kwargs):
        return {"block": {"items": [], "count": 0, "limit": 10, "unique_stories": 0,
                          "errors": [], "data_provider": "YAHOO",
                          "providers_answered": ["YAHOO"], "endpoints": {"YAHOO": "Yahoo news"},
                          "shortfall_reason": "available feeds supplied no stories"}}

    monkeypatch.setattr(fv_access, "why_moving", broken)
    monkeypatch.setattr(news, "fetch_news", fake_news)
    result = await tools_finviz.stock_why_moving("AAPL")
    assert result["data"] is None
    assert result["data_provider"] == "NONE"
    assert result["errors"][0]["code"] == "UPSTREAM_BLOCKED"
    assert result["news"]["data_provider"] == "YAHOO"
