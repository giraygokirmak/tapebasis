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


# ── Yahoo's chart shape ─────────────────────────────────────────────────────


def _yahoo_chart(*, candles: list[tuple[int, float | None]], periods=None) -> dict:
    """A minimal Yahoo chart payload with per-day session windows."""
    meta = {
        "currency": "USD",
        "exchangeName": "NMS",
        "regularMarketPrice": 348.51,
        "regularMarketTime": 1794344400,
        "previousClose": 350.69,
        "chartPreviousClose": 350.69,
        "currentTradingPeriod": {
            "pre": {"start": 1794387600, "end": 1794407400},
            "regular": {"start": 1794407400, "end": 1794430800},
            "post": {"start": 1794430800, "end": 1794445200},
        },
    }
    if periods is not None:
        meta["tradingPeriods"] = periods
    return {
        "chart": {
            "result": [
                {
                    "meta": meta,
                    "timestamp": [ts for ts, _ in candles],
                    "indicators": {"quote": [{"close": [c for _, c in candles]}]},
                }
            ]
        }
    }


def test_yahoo_range_one_day_no_longer_carries_candles():
    """The request asks for the narrowest window that still has candles.

    ``range=1d`` is answered with ``meta`` alone now, so a shaper that reads
    ``timestamp`` reported "unexpected response shape: 'timestamp'" on every
    call and the session timeline silently disappeared from the response.
    """
    from tapebasis.providers.tradingview.core.services.extended_hours_service import (
        _quote_url,
    )
    from tapebasis.yh_access import _CHART

    url = _quote_url("AAPL")
    assert url.startswith(f"{_CHART}/AAPL?")
    assert "range=2d" in url
    assert "includePrePost=true" in url


def test_candles_are_classified_by_their_own_day():
    """Two days of candles must not be read against one day's windows.

    ``range=2d`` is what still returns candles, and it brings two session days.
    Walking them against ``currentTradingPeriod`` (today only) filed yesterday's
    regular prints as today's pre-market, which is the wrong session entirely.
    """
    from tapebasis.providers.tradingview.core.services.extended_hours_service import (
        _shape_extended_hours,
    )

    periods = {
        "pre": [
            [{"start": 1794301200, "end": 1794321000}],
            [{"start": 1794387600, "end": 1794407400}],
        ],
        "regular": [
            [{"start": 1794321000, "end": 1794344400}],
            [{"start": 1794407400, "end": 1794430800}],
        ],
        "post": [
            [{"start": 1794344400, "end": 1794358800}],
            [{"start": 1794430800, "end": 1794445200}],
        ],
    }
    payload = _yahoo_chart(
        candles=[
            (1794310000, 340.0),  # yesterday pre-market
            (1794330000, 346.0),  # yesterday regular
            (1794350000, 347.5),  # yesterday post-market
            (1794395000, 345.89),  # today pre-market (the latest print)
        ],
        periods=periods,
    )
    shaped = _shape_extended_hours("AAPL", payload)

    assert shaped["pre_market"]["price"] == pytest.approx(345.89)
    # The regular block keeps the consolidated tape, not yesterday's last candle.
    assert shaped["regular"]["price"] == pytest.approx(348.51)
    # The post block is yesterday's after-hours print, which is the most recent
    # print in that session: the tool reports "no after-hours print yet" by
    # leaving the block null, not by hiding an older one that exists.
    assert shaped["post_market"]["price"] == pytest.approx(347.5)
    assert shaped["post_market"]["as_of_utc"].startswith("2026-11-10")


def test_a_post_window_past_midnight_is_not_tomorrows_pre_market():
    """The post session ends at 01:00 UTC, after the day has rolled.

    A candle at 00:30 UTC belongs to the previous session's after-hours, and
    filing it under the next day's pre-market would report a print that has not
    happened yet.
    """
    from tapebasis.providers.tradingview.core.services.extended_hours_service import (
        _shape_extended_hours,
    )

    periods = {
        "pre": [[{"start": 1794301200, "end": 1794321000}]],
        "regular": [[{"start": 1794321000, "end": 1794344400}]],
        "post": [[{"start": 1794344400, "end": 1794370200}]],
    }
    payload = _yahoo_chart(
        candles=[(1794365000, 349.25)],  # 00:03 UTC, inside yesterday's post
        periods=periods,
    )
    shaped = _shape_extended_hours("AAPL", payload)

    assert shaped["post_market"]["price"] == pytest.approx(349.25)
    assert shaped["pre_market"] is None


def test_a_payload_without_a_candle_array_stays_an_error_not_a_crash():
    """A shape change is reported as NO_DATA, never as an exception."""
    from tapebasis.providers.tradingview.core.services.extended_hours_service import (
        _shape_extended_hours,
    )

    shaped = _shape_extended_hours("AAPL", _yahoo_chart(candles=[]))
    # An empty candle list is a real (if empty) answer, not a shape error.
    assert "error" not in shaped

    shaped = _shape_extended_hours("AAPL", {"chart": {"result": [{"meta": {}}]}})
    assert "timestamp" in shaped["error"]
