"""Extended-hours tool: the pre/post volumes TradingView was already sending.

The scanner returns ``premarket_volume`` and ``postmarket_volume`` on the same
row as the prices, and this tool requested them on every call and then never
read the two fields. A pre-market print with no size cannot be told apart from
a single lot.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
import urllib.error

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

    state = {"tv": dict(tv_quote), "yh": None, "now": None}

    async def tv_quote_call(symbol):
        return state["tv"]

    async def fv_quote_call(symbol):
        return fv_quote

    async def yh_hours(symbol):
        return state["yh"]

    async def yh_overnight(symbol):
        return None

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
    monkeypatch.setattr(yh_access, "overnight", yh_overnight)
    monkeypatch.setattr(tools_market, "resolve", fake_resolve)
    monkeypatch.setattr(tools_market, "_utc_now", lambda: state["now"] or datetime.now(timezone.utc))
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


@pytest.mark.asyncio
async def test_only_like_sessions_are_compared(fake_hours, monkeypatch):
    """A pre-market print is not a disagreement with yesterday's post print."""
    from tapebasis import tv_access

    fake_hours["tv"].update({
        "current_session": "pre_market",
        "premarket_close": 332.47,
        "postmarket_close": 330.1,
        "update_time": "2026-11-04T13:30:00+00:00",
    })
    fake_hours["yh"] = {
        "pre_market": {
            "price": 332.5,
            "as_of_utc": "2026-11-04T13:30:00+00:00",
        },
        "post_market": {
            "price": 330.1,
            "as_of_utc": "2026-11-03T21:00:00+00:00",
        },
    }
    fake_hours["yh"]["regular"] = {
        "price": 331.9,
        "as_of_utc": "2026-11-03T21:00:00+00:00",
    }
    async def no_overnight(tickers, **kwargs):
        return {}

    monkeypatch.setattr(tv_access, "live_session_quotes", no_overnight)

    data = (await tools_market.stock_extended_hours("AAPL"))["data"]
    comparison = data["after_hours_comparison"]

    assert comparison["values"]["TRADINGVIEW"] == pytest.approx(332.47)
    assert comparison["values"]["YAHOO"] == pytest.approx(332.5)
    assert data["after_hours_readings"]["FINVIZ"] == pytest.approx(329.8)
    tv_yahoo = next(
        pair for pair in comparison["pairs"]
        if pair["between"] == ["TRADINGVIEW", "YAHOO"]
    )
    assert tv_yahoo["match"] is True
    tv_finviz = next(
        pair for pair in comparison["pairs"]
        if pair["between"] == ["TRADINGVIEW", "FINVIZ"]
    )
    assert tv_finviz["match"] is None
    assert "different trading sessions" in tv_finviz["not_comparable"]


@pytest.mark.asyncio
async def test_undated_reads_reach_the_envelope_as_not_comparable(
    fake_hours, monkeypatch, sa_quote
):
    """The envelope repeats the unresolved session verdict, not agreement."""
    from tapebasis import fv_access, sa_access, tv_access

    fake_hours["tv"]["update_time"] = None
    fake_hours["sa"] = sa_quote
    fake_hours["yh"] = {"post_market": {
        "price": 330.0,
        "as_of_utc": "2026-11-03T21:00:00+00:00",
    }}
    sa_quote["extended_hours"]["price_timestamp"] = None

    async def empty_finviz(symbol):
        return {"after_hours": {}}

    async def no_overnight(tickers, **kwargs):
        return {}

    monkeypatch.setattr(tv_access, "live_session_quotes", no_overnight)
    monkeypatch.setattr(fv_access, "quote", empty_finviz)
    monkeypatch.setattr(sa_access, "quote", lambda symbol: _async_value(sa_quote))

    result = await tools_market.stock_extended_hours("AAPL")

    comparison = result["comparisons"][0]
    assert comparison["field"] == "after_hours_price"
    assert comparison["match"] is None
    assert comparison["not_comparable"]
    assert "Compared fields agree within tolerance" not in result["notice"]
    assert "Not cross-checked" in result["notice"]
    assert any("after_hours_price" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_undated_extended_print_is_not_comparable(fake_hours, monkeypatch):
    """An undated provider cannot create a session conflict."""
    from tapebasis import tv_access

    fake_hours["tv"].update({
        "current_session": "regular",
        "premarket_close": 332.47,
        "postmarket_close": 330.1,
    })
    fake_hours["yh"] = {
        "pre_market": None,
        "post_market": {
            "price": 350.0,
            "as_of_utc": "2026-11-03T21:00:00+00:00",
        },
    }
    async def no_overnight(tickers, **kwargs):
        return {}

    monkeypatch.setattr(tv_access, "live_session_quotes", no_overnight)
    data = (await tools_market.stock_extended_hours("AAPL"))["data"]
    comparison = data["after_hours_comparison"]

    assert data["after_hours_readings"]["YAHOO"] == pytest.approx(350.0)
    assert comparison["match"] is None
    assert comparison["not_comparable"] is True
    for pair in comparison["pairs"]:
        assert pair["match"] is None
        assert pair.get("not_comparable")


@pytest.mark.asyncio
async def test_stockanalysis_keeps_its_named_session_when_undated(
    fake_hours, monkeypatch, sa_quote
):
    """A named but undated extended print cannot contradict another window."""
    from tapebasis import sa_access, tv_access

    fake_hours["tv"]["current_session"] = "regular"
    fake_hours["tv"]["update_time"] = None
    fake_hours["yh"] = {
        "post_market": {
            "price": 330.0,
            "as_of_utc": "2026-11-03T21:00:00+00:00",
        },
    }
    sa_quote["extended_hours"]["price_timestamp"] = None
    sa_quote["extended_hours"]["price"] = 350.0
    monkeypatch.setattr(sa_access, "quote", lambda symbol: _async_value(sa_quote))

    async def no_overnight(tickers, **kwargs):
        return {}

    async def no_finviz(symbol):
        return {"after_hours": {}}

    from tapebasis import fv_access

    monkeypatch.setattr(tv_access, "live_session_quotes", no_overnight)
    monkeypatch.setattr(fv_access, "quote", no_finviz)

    comparison = (await tools_market.stock_extended_hours("AAPL"))["data"][
        "after_hours_comparison"
    ]
    pair = next(
        pair for pair in comparison["pairs"]
        if pair["between"] == ["YAHOO", "SA"]
    )

    assert pair["match"] is None
    assert "post_market" in pair["not_comparable"]
    assert "no dated print" in pair["not_comparable"]


async def _async_value(value):
    """Return a fake provider payload from an awaitable access function."""
    return value


# -- Overnight providers -----------------------------------------------------


@pytest.mark.asyncio
async def test_overnight_keeps_each_provider_and_compares_like_prints(
    fake_hours, monkeypatch
):
    """Yahoo and TradingView are two overnight readings, not fallbacks."""
    from tapebasis import tv_access, yh_access

    stamp = 1793754000  # 2026-11-04 01:00 UTC: the prior evening at 20:00 ET
    async def tv_overnight(tickers, **kwargs):
        assert tickers == ["BOATS:AAPL"]
        return {"BOATS:AAPL": {
            "lp": 332.0,
            "lp_time": stamp,
            "chp": 0.04,
            "current_session": "out_of_session",
            "volume": 1200,
            "exchange": "BOATS",
            "update_mode": "streaming",
        }}

    async def yahoo_overnight(symbol):
        return {
            "session": "overnight",
            "price": 332.05,
            "change": 0.15,
            "change_percent": 0.045,
            "print_time": stamp,
            "exchange": "Blue Ocean ATS",
            "feed_mode": "streaming",
        }

    monkeypatch.setattr(tv_access, "live_session_quotes", tv_overnight)
    monkeypatch.setattr(yh_access, "overnight", yahoo_overnight)
    result = await tools_market.stock_extended_hours("AAPL")
    data = result["data"]

    assert data["overnight"]["price"] == pytest.approx(332.0)
    assert data["overnight"]["as_of_utc"] == "2026-11-04T01:00:00Z"
    assert data["overnight_source"] == tools_market.TRADINGVIEW
    assert data["overnight_readings"][tools_market.YAHOO]["price"] == pytest.approx(332.05)
    assert result["comparisons"][-1]["field"] == "overnight_price"
    assert result["comparisons"][-1]["match"] is True
    assert result["fields"]["overnight.price"]["compared"] == [
        tools_market.TRADINGVIEW, tools_market.YAHOO
    ]
    assert result["fields"]["overnight.price"]["source"] == tools_market.TRADINGVIEW
    assert set(result["fields"]["overnight.price"]["supplied"]) == {
        tools_market.TRADINGVIEW, tools_market.YAHOO
    }
    assert data["overnight"]["session_window_start_utc"] == "2026-11-04T01:00:00Z"


@pytest.mark.asyncio
async def test_overnight_does_not_compare_two_calendar_occurrences(
    fake_hours, monkeypatch
):
    """Two prints named overnight can belong to different trading windows."""
    from tapebasis import tv_access, yh_access

    async def tv_overnight(tickers, **kwargs):
        return {"BOATS:AAPL": {
            "lp": 332.0, "lp_time": 1793754000,
            "current_session": "out_of_session",
        }}

    async def yahoo_overnight(symbol):
        return {"price": 330.0, "print_time": 1793840400}

    monkeypatch.setattr(tv_access, "live_session_quotes", tv_overnight)
    monkeypatch.setattr(yh_access, "overnight", yahoo_overnight)
    result = await tools_market.stock_extended_hours("AAPL")
    comparison = result["data"]["overnight_comparison"]
    assert comparison["match"] is None
    assert comparison["not_comparable"] is True
    assert "different trading sessions" in comparison["pairs"][0]["not_comparable"]
    assert result["fields"]["overnight.price"]["compared"] == []


@pytest.mark.asyncio
async def test_fresh_yahoo_overnight_wins_and_names_its_source(
    fake_hours, monkeypatch
):
    """A Yahoo print can be newer than the BOATS reading on the same instrument."""
    from tapebasis import tv_access, yh_access

    async def tv_overnight(tickers, **kwargs):
        return {"BOATS:AAPL": {
            "lp": 332.0, "lp_time": 1793754000,
            "current_session": "out_of_session",
        }}

    async def yahoo_overnight(symbol):
        return {
            "session": "overnight", "price": 332.1,
            "print_time": 1793754060,
        }

    monkeypatch.setattr(tv_access, "live_session_quotes", tv_overnight)
    monkeypatch.setattr(yh_access, "overnight", yahoo_overnight)
    data = (await tools_market.stock_extended_hours("AAPL"))["data"]

    assert data["overnight_source"] == tools_market.YAHOO
    assert data["overnight"]["price"] == pytest.approx(332.1)


@pytest.mark.asyncio
async def test_overnight_failure_does_not_silently_become_no_print(
    fake_hours, monkeypatch
):
    """A reachable but failing session endpoint stays visible in the envelope."""
    from tapebasis import tv_access, yh_access
    from tapebasis.providers_state import ProviderError

    async def tv_overnight(tickers, **kwargs):
        raise ProviderError(
            tools_market.TRADINGVIEW, "socket timed out", code="UPSTREAM_TIMEOUT"
        )

    async def yahoo_overnight(symbol):
        raise ProviderError(tools_market.YAHOO, "not available")

    monkeypatch.setattr(tv_access, "live_session_quotes", tv_overnight)
    monkeypatch.setattr(yh_access, "overnight", yahoo_overnight)
    result = await tools_market.stock_extended_hours("AAPL")

    assert result["data"]["overnight"] is None
    assert result["data"]["overnight_source"] is None
    assert result["data"]["overnight_errors"] == [{
        "provider": tools_market.TRADINGVIEW,
        "code": "UPSTREAM_TIMEOUT",
        "message": "socket timed out",
        "detail": {"capability": "overnight"},
        }, {
            "provider": tools_market.YAHOO,
            "code": "PROVIDER_ERROR",
            "message": "not available",
            "detail": {"capability": "overnight"},
    }]
    assert result["errors"][-2:] == result["data"]["overnight_errors"]
    assert result["errors"][0]["code"] == "NO_DATA"


@pytest.mark.asyncio
async def test_historical_overnight_is_quoted_but_not_the_live_session(
    fake_hours, monkeypatch
):
    """At 04:31 ET BOATS's 03:59 print is retained, not promoted to live price."""
    from tapebasis import tv_access

    stamp = 1794560399
    fake_hours["now"] = datetime(2026, 11, 13, 9, 31, tzinfo=timezone.utc)

    async def tv_overnight(tickers, **kwargs):
        return {"BOATS:AAPL": {
            "lp": 166.58, "lp_time": stamp,
            "current_session": "out_of_session", "update_mode": "streaming",
        }}

    monkeypatch.setattr(tv_access, "live_session_quotes", tv_overnight)
    data = (await tools_market.stock_extended_hours("NVDA"))["data"]

    assert data["overnight"]["price"] == pytest.approx(166.58)
    assert data["overnight"]["is_current"] is False
    assert data["overnight"]["session_window_start_utc"] == "2026-11-13T01:00:00Z"
    assert data["overnight_is_current"] is False
    assert data["session"] != tools_market.OVERNIGHT
    assert data["pre_market"]["price"] == pytest.approx(332.47)


@pytest.mark.asyncio
async def test_overnight_does_not_claim_pre_market_print_is_live(
    fake_hours, monkeypatch
):
    """The session label follows a dated overnight print inside its window."""
    from tapebasis import tv_access, yh_access

    stamp = 1793754000
    fake_hours["tv"]["current_session"] = "pre_market"
    fake_hours["now"] = datetime.fromtimestamp(stamp + 120, timezone.utc)
    async def tv_overnight(tickers, **kwargs):
        return {"BOATS:AAPL": {
            "lp": 332.0, "lp_time": stamp, "current_session": "out_of_session",
        }}

    async def no_yahoo_overnight(symbol):
        return None

    monkeypatch.setattr(tv_access, "live_session_quotes", tv_overnight)
    monkeypatch.setattr(yh_access, "overnight", no_yahoo_overnight)
    data = (await tools_market.stock_extended_hours("AAPL"))["data"]

    assert data["session"] == tools_market.OVERNIGHT
    assert data["overnight"]["session"] == "overnight"
    assert data["pre_market"]["price"] == pytest.approx(332.47)


@pytest.mark.asyncio
async def test_yahoo_overnight_reads_the_web_header_fields(
    monkeypatch, _isolate_extended_session_upstreams
):
    """The Blue Ocean header is a quote field, not a 1-minute candle."""
    from tapebasis import yh_access

    calls = []
    async def fake_get(fetch):
        calls.append(fetch)
        return {
            "quoteResponse": {"result": [{
                "symbol": "NVDA",
                "regularMarketPrice": 166.19,
                "overnightMarketPrice": {"raw": 166.0},
                "overnightMarketTime": 1793822400,
                "overnightMarketChangePercent": {"raw": -0.1075},
            }], "error": None},
        }

    monkeypatch.setattr(
        yh_access, "overnight", _isolate_extended_session_upstreams[0]
    )
    monkeypatch.setattr(yh_access, "_yahoo_quote_request", fake_get)
    block = await yh_access.overnight("NVDA")
    assert len(calls) == 1
    assert block["price"] == pytest.approx(166.0)
    assert block["print_time"] == 1793822400
    assert block["reference_close"] == pytest.approx(166.19)
    assert block["change_percent"] == pytest.approx(-0.1075)
    assert block["volume"] is None
    captured = {}

    def capture_page(_opener, params):
        """Capture the prepared quote-header parameters without networking."""
        captured.update(params)
        return {"quoteResponse": {"result": [{}], "error": None}}
    monkeypatch.setattr(yh_access, "_quote_page", capture_page)
    import asyncio
    await asyncio.to_thread(calls[0], object(), {
        "overnightPrice": "true", "formatted": "true", "crumb": "guest",
    })
    assert captured["overnightPrice"] == "true"
    assert captured["symbols"] == "NVDA"
    assert captured["fields"] == ",".join([
        "symbol", "regularMarketPrice", "overnightMarketPrice",
        "overnightMarketChange", "overnightMarketChangePercent", "overnightMarketTime",
    ])


@pytest.mark.asyncio
async def test_yahoo_overnight_never_infers_a_different_reference_close():
    """Yahoo's regular price is the only published overnight change baseline."""
    from tapebasis.yh_access import _shape_overnight

    block = _shape_overnight("NVDA", {
        "quoteResponse": {"result": [{
            "overnightMarketPrice": 166.52,
            "overnightMarketChange": -2,
            "overnightMarketTime": 1794560388,
            "regularMarketPreviousClose": 173.73,
            "fulldayPrice": 168.2,
        }], "error": None},
    })
    assert block["reference_close"] is None
    assert block["price"] == pytest.approx(166.52)
    assert block["change"] == pytest.approx(-2)


def test_yahoo_overnight_rejects_an_undated_print():
    """A price without its observation time is not an overnight observation."""
    from tapebasis.yh_access import _shape_overnight

    block = _shape_overnight("NVDA", {
        "quoteResponse": {"result": [{
            "regularMarketPrice": 166.19,
            "overnightMarketPrice": 166.52,
            "postMarketPrice": 168.0,
        }], "error": None},
    })
    assert block is None


@pytest.mark.asyncio
async def test_yahoo_quote_session_unwraps_cookie_opener_and_cookie_crumb(monkeypatch):
    """Reuse Yahoo's native (crumb, opener) session without swapping identities."""
    from tapebasis import yh_access

    opener = type("Opener", (), {})()
    async def no_handshake():
        raise AssertionError("an unexpired cached session must be reused")
    monkeypatch.setattr(yh_access.blocking_pool, "run", no_handshake)
    yh_access._quote_session.update(opener=opener, crumb="guest", created=9999.0)
    monkeypatch.setattr(yh_access.time, "monotonic", lambda: 10000.0)

    async def cached():
        return await yh_access._quote_session_credentials()

    assert tuple(await cached()) == (opener, "guest")
    yh_access._quote_session.update(opener=None, crumb=None, created=0.0)

    async def handshake(_fn):
        return ("guest", opener)
    monkeypatch.setattr(yh_access.blocking_pool, "run", handshake)
    assert tuple(await cached()) == (opener, "guest")
    yh_access._quote_session.update(opener=None, crumb=None, created=0.0)


@pytest.mark.asyncio
async def test_yahoo_quote_request_refreshes_only_its_failed_session(monkeypatch):
    """A 401 gets one fresh cookie/crumb pair, never an opener/crumb swap."""
    from tapebasis import yh_access

    first, second = object(), object()
    state = {"opener": first, "crumb": "one", "created": 100.0}
    monkeypatch.setattr(yh_access.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(yh_access, "_quote_session", state)
    calls = []

    async def transport(fn, *args):
        if fn is yh_access._cookie_session:
            return await yh_access._cookie_session()
        opener, params = args
        calls.append((opener, params["crumb"]))
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                "https://query1.finance.yahoo.com", 401, "expired", {}, None
            )
        return {"quoteResponse": {"result": [{}], "error": None}}

    async def cookie_session():
        return "two", second

    async def immediate(_provider, fn):
        return await fn()

    monkeypatch.setattr(yh_access.blocking_pool, "run", transport)
    monkeypatch.setattr(yh_access, "_cookie_session", cookie_session)
    monkeypatch.setattr(yh_access, "call", immediate)
    result = await yh_access._yahoo_quote_request(lambda opener, params: {})
    assert result["quoteResponse"]["error"] is None
    assert calls == [(first, "one"), (second, "two")]
    assert state == {"opener": second, "crumb": "two", "created": 100.0}


@pytest.mark.asyncio
async def test_yahoo_quote_limiter_exhaustion_is_a_typed_rate_limit(monkeypatch):
    """The quote header reports limiter exhaustion as UPSTREAM_RATE_LIMIT."""
    from tapebasis import yh_access
    from tapebasis.providers_state import ProviderError
    from tapebasis.ratelimit import RateLimitError

    async def exhausted(_provider, _fn):
        raise RateLimitError("YAHOO", 5.0)

    monkeypatch.setattr(yh_access, "_quote_session_credentials", lambda: _async_value((object(), "x")))
    monkeypatch.setattr(yh_access, "call", exhausted)
    with pytest.raises(ProviderError) as exc:
        await yh_access._yahoo_quote_request(lambda opener, params: {})
    assert exc.value.code == "UPSTREAM_RATE_LIMIT"


@pytest.mark.asyncio
async def test_yahoo_429_enters_the_shared_limiter(monkeypatch):
    """The real quote-page path records cooldown and reports a typed failure."""
    from tapebasis import yh_access
    from tapebasis.providers_state import ProviderError

    class Opener:
        def open(self, request, timeout):
            """Reject this synthetic request without reaching Yahoo."""
            assert timeout == 15.0
            raise urllib.error.HTTPError(
                request.full_url, 429, "throttled", {}, None
            )

    paced = yh_access.limiter("YAHOO")
    monkeypatch.setattr(paced, "_cooldown_until", 0.0)
    monkeypatch.setattr(paced, "max_retries", 0)
    monkeypatch.setattr(yh_access, "_quote_session", {
        "opener": Opener(), "crumb": "guest", "created": yh_access.time.monotonic(),
    })
    with pytest.raises(ProviderError) as exc:
        await yh_access._yahoo_quote_request(yh_access._quote_page)
    assert exc.value.code == "UPSTREAM_RATE_LIMIT"
    assert paced._cooldown_until > yh_access.time.monotonic()


# -- Yahoo's chart shape ------------------------------------------------------


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
