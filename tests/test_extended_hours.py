"""Extended-hours tool: the pre/post volumes TradingView was already sending.

The scanner returns ``premarket_volume`` and ``postmarket_volume`` on the same
row as the prices, and this tool requested them on every call and then never
read the two fields. A pre-market print with no size cannot be told apart from
a single lot.
"""
from __future__ import annotations

import pytest

from tapebasis import tools_market
from tapebasis.symbols import Resolution


def _resolved(provider: str, symbol: str) -> Resolution:
    return Resolution(
        query="AAPL",
        provider=provider,
        symbol=symbol,
        method="explicit",
        confidence=1.0,
        note="",
    )


@pytest.fixture
def fake_hours(monkeypatch, tv_quote, fv_quote):
    from tapebasis import fv_access, tv_access, yh_access

    state = {"tv": dict(tv_quote), "yh": None}

    async def tv_quote_call(symbol):
        return state["tv"]

    async def fv_quote_call(symbol):
        return fv_quote

    async def yh_hours(symbol):
        return state["yh"]

    async def fake_resolve(query, provider, **kwargs):
        return {
            "TRADINGVIEW": _resolved(provider, "NASDAQ:AAPL"),
            "FINVIZ": _resolved(provider, "AAPL"),
            "YAHOO": _resolved(provider, "AAPL"),
            "BLOOMBERG": _resolved(provider, "AAPL:US"),
        }[provider]

    monkeypatch.setattr(tv_access, "quote", tv_quote_call)
    monkeypatch.setattr(fv_access, "quote", fv_quote_call)
    monkeypatch.setattr(yh_access, "extended_hours", yh_hours)
    monkeypatch.setattr(tools_market, "resolve", fake_resolve)
    return state


@pytest.mark.asyncio
async def test_premarket_volume_is_served_when_yahoo_has_no_sessions(fake_hours):
    """Falls back to the TradingView row, which carried the size all along."""
    fake_hours["tv"].update(
        {
            "premarket_close": 332.47,
            "premarket_change": 0.17,
            "premarket_volume": 67876,
            "postmarket_close": 330.1,
            "postmarket_change": -0.5,
            "postmarket_volume": 9291073,
        }
    )
    result = await tools_market.stock_extended_hours("AAPL")
    data = result["data"]

    assert data["pre_market"]["price"] == pytest.approx(332.47)
    assert data["pre_market"]["volume"] == 67876
    assert data["post_market"]["price"] == pytest.approx(330.1)
    assert data["post_market"]["volume"] == 9291073

    # Also exposed flat, so a caller reading one session does not need the block.
    assert data["tradingview_premarket_volume"] == 67876
    assert data["tradingview_postmarket_volume"] == 9291073


@pytest.mark.asyncio
async def test_premarket_session_omits_volume_when_the_feed_has_none(fake_hours):
    """A null volume is reported as null, never invented as 0."""
    fake_hours["tv"]["premarket_volume"] = None
    result = await tools_market.stock_extended_hours("AAPL")
    assert result["data"]["pre_market"]["volume"] is None


@pytest.mark.asyncio
async def test_yahoo_sessions_still_win_when_present(fake_hours):
    """The volume addition must not override the richer session timeline."""
    fake_hours["yh"] = {
        "pre_market": {"price": 332.0, "change_pct": 0.1, "volume": 5000},
        "regular": {"price": 331.9, "change_pct": -1.9},
        "post_market": None,
    }
    result = await tools_market.stock_extended_hours("AAPL")
    assert result["data"]["pre_market"] == {
        "price": 332.0,
        "change_pct": 0.1,
        "volume": 5000,
    }
    # The TradingView reading is still visible next to it.
    assert result["data"]["tradingview_premarket_volume"] == 67876
