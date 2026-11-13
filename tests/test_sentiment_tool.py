"""Token-free sentiment path: Marketaux preferred, local scoring as fallback.

These tests pin the promise the user actually asked for: ``market_sentiment``
works with no API key at all. They also pin the honesty requirement, a local
lexicon score must never be presented as vendor output, and "no material to
score" must never become a fabricated neutral-looking 0.0.
"""
from __future__ import annotations

import pytest

from tapebasis import tools_tradingview


@pytest.fixture
def no_token(monkeypatch):
    monkeypatch.delenv("MARKETAUX_API_TOKEN", raising=False)


@pytest.fixture
def fake_finviz_news(monkeypatch):
    from tapebasis import fv_access

    async def fake_news(symbol, limit=30, include_reactions=True):
        return {
            "ticker": symbol,
            "news": [
                {"datetime": "Today 09:00AM", "headline": "Apple beats estimates and raises guidance",
                 "source": "Reuters", "url": "https://example.com/1"},
                {"datetime": "Today 08:00AM", "headline": "Apple stock plunges on weak margins",
                 "source": "CNBC", "url": "https://example.com/2"},
                {"datetime": "Yesterday", "headline": "Apple: 3 Key Takeaways for Investors",
                 "source": "Barron's", "url": "https://example.com/3"},
            ],
            "count": 3,
            "as_of": "2026-11-04T07:00:00Z",
        }

    monkeypatch.setattr(fv_access, "news", fake_news)


@pytest.mark.asyncio
async def test_sentiment_works_with_no_api_token(no_token, fake_finviz_news):
    result = await tools_tradingview.market_sentiment("AAPL")
    assert result["data"]["sentiment_score"] is not None
    assert result["data"]["posts_analyzed"] == 3
    assert result["data"]["provider"] == "local-vader"


@pytest.mark.asyncio
async def test_local_path_is_labelled_as_local_not_vendor(no_token, fake_finviz_news):
    result = await tools_tradingview.market_sentiment("AAPL")
    assert "local" in result["sources"]["FINVIZ"].lower()
    assert "Marketaux" not in result["sources"]["FINVIZ"]
    assert result["data"]["scoring"]["runs"].startswith("locally")


@pytest.mark.asyncio
async def test_local_path_is_attributed_to_finviz_not_tradingview(no_token, fake_finviz_news):
    """The headlines are Finviz's; only the lexicon scoring is ours.

    Labelling the envelope TRADINGVIEW would attribute the data to a provider
    that did not supply it, the exact mislabelling this server exists to avoid.
    """
    result = await tools_tradingview.market_sentiment("AAPL")
    assert result["data_provider"] == "FINVIZ"
    assert result["verification"] == "SINGLE_SOURCE"
    assert "FINVIZ" in result["sources"]
    assert "TRADINGVIEW" not in result["sources"]


@pytest.mark.asyncio
async def test_sentiment_still_reports_a_direction(no_token, fake_finviz_news):
    """Two bullish-ish items vs one bearish must not collapse to 0.0."""
    result = await tools_tradingview.market_sentiment("AAPL")
    assert result["data"]["sentiment_label"] in {
        "Bullish", "Strongly Bullish", "Neutral", "Bearish", "Strongly Bearish"
    }
    assert result["data"]["bullish_count"] >= 1
    assert result["data"]["bearish_count"] >= 1


@pytest.mark.asyncio
async def test_no_fabricated_score_when_nothing_can_be_scored(no_token, monkeypatch):
    """Neither Marketaux nor Finviz available -> explicit gap, not 0.0/Neutral."""
    from tapebasis import fv_access

    async def broken(*args, **kwargs):
        raise RuntimeError("finviz down")

    monkeypatch.setattr(fv_access, "news", broken)
    result = await tools_tradingview.market_sentiment("AAPL")
    assert result["data"]["sentiment_score"] is None
    assert result["data"]["sentiment_label"] == "Unavailable"
    assert result["data"]["provider"] == "unavailable"
    assert result["warnings"]


@pytest.mark.asyncio
async def test_marketaux_is_preferred_when_a_token_exists(monkeypatch):
    """A token flips the backend to the licensed path, not the local one."""
    from tapebasis.providers.tradingview.core.services import marketaux_service

    monkeypatch.setenv("MARKETAUX_API_TOKEN", "test-token")

    def fake_analyze(symbol, category="all", limit=20):
        return {
            "symbol": symbol.upper(), "sentiment_score": 0.42,
            "sentiment_label": "Strongly Bullish", "posts_analyzed": 3,
            "bullish_count": 2, "bearish_count": 1, "neutral_count": 0,
            "top_posts": [], "sources": ["Marketaux news"], "provider": "marketaux",
        }

    monkeypatch.setattr(marketaux_service, "analyze_sentiment", fake_analyze)
    result = await tools_tradingview.market_sentiment("AAPL")
    assert result["data"]["provider"] == "marketaux"
    assert result["data"]["sentiment_score"] == pytest.approx(0.42)
    assert "Marketaux" in result["sources"]["TRADINGVIEW"]


@pytest.mark.asyncio
async def test_rejected_token_falls_back_locally_instead_of_reporting_zero(
    monkeypatch, fake_finviz_news
):
    """An invalid/expired token must not surface as a neutral 0.0 score.

    0.0 is a legitimate reading ("the news is balanced"). Using it for "we
    could not fetch anything" makes a data gap look like a finding, so the
    invalid-token path must fall back and say why.
    """
    from tapebasis.providers.tradingview.core.services import marketaux_service

    monkeypatch.setenv("MARKETAUX_API_TOKEN", "invalid-token")

    def rejected(symbol, category="all", limit=20):
        return {
            "symbol": symbol.upper(), "sentiment_score": None,
            "sentiment_label": "Unavailable", "posts_analyzed": 0,
            "bullish_count": 0, "bearish_count": 0, "neutral_count": 0,
            "top_posts": [], "sources": ["Marketaux news"], "provider": "marketaux",
            "error": "Marketaux returned no articles (unavailable)",
        }

    monkeypatch.setattr(marketaux_service, "analyze_sentiment", rejected)
    result = await tools_tradingview.market_sentiment("AAPL")
    assert result["data"]["provider"] == "local-vader"
    assert result["data"]["sentiment_score"] is not None
    assert "Marketaux returned no articles" in result["data"]["licensed_path_unavailable"]


@pytest.mark.asyncio
async def test_combined_analysis_sentiment_leg_needs_no_token(no_token, monkeypatch):
    """The composite's sentiment leg must also survive without a token."""
    from tapebasis import fv_access, tv_access, yh_access

    async def fake_technical_analysis(symbol, exchange="NASDAQ", timeframe="1D"):
        return {
            "price_data": {"current_price": 331.9, "volume": 1000},
            "rsi": {"value": 41.7},
            "atr": {"value": 7.4},
        }

    async def fake_news(symbol, limit=30, include_reactions=True):
        return {"news": [{"headline": "Apple beats estimates"}], "count": 1, "as_of": "x"}

    async def fake_snapshot(symbol):
        return {"numeric": {"Price": 331.9}}

    async def fake_quote(symbol):
        return {"price": 331.9, "change_pct": -1.9}

    async def fake_resolve(query, provider, **kwargs):
        from tapebasis.symbols import Resolution

        return Resolution(
            query=query,
            provider=provider,
            symbol={"TRADINGVIEW": "NASDAQ:AAPL"}.get(provider, "AAPL"),
            method="explicit",
            confidence=1.0,
        )

    monkeypatch.setattr(tv_access, "technical_analysis", fake_technical_analysis)
    monkeypatch.setattr(fv_access, "news", fake_news)
    monkeypatch.setattr(fv_access, "snapshot", fake_snapshot)
    monkeypatch.setattr(yh_access, "quote", fake_quote)
    monkeypatch.setattr(tools_tradingview, "_yahoo_resolution", lambda s: fake_resolve(s, "YAHOO"))

    result = await tools_tradingview.combined_analysis("AAPL")
    sentiment_leg = result["data"]["sentiment"]
    assert sentiment_leg is not None
    assert sentiment_leg["sentiment_score"] is not None
    assert sentiment_leg["provider"] == "local-vader"
