"""Shared fixtures for the hermetic test suite.

No test in this directory touches a live upstream: provider calls are replaced
with deterministic fakes, and the health state is redirected to a temp directory.

Each fixture is shaped the way its *own* provider actually answers, not the way
another one does, a shared shape would hide exactly the mapping bugs these
tests exist to catch.
"""
from __future__ import annotations

import os

import pytest

# Health state must never be written to the real home directory from tests.
os.environ.setdefault("TAPEBASIS_HEALTH_STATE", "/tmp/tapebasis-test/health.json")
os.environ.setdefault("TAPEBASIS_HEALTH_ENABLED", "false")

#: 2026-11-03 21:00:01 UTC, the US close, used across fixtures so freshness
#: arbitration has real, comparable instants to order.
CLOSE_EPOCH = 1793739601
CLOSE_ISO = "2026-11-03T21:00:01+00:00"


@pytest.fixture(autouse=True)
def _isolate_extended_session_upstreams(monkeypatch):
    """Stub session endpoints and return real ones for focused unit tests."""
    from tapebasis import tv_access, yh_access

    real_overnight = yh_access.overnight
    real_live_quotes = tv_access.live_session_quotes

    async def no_overnight(_symbol):
        return None

    async def no_socket(_tickers, **_kwargs):
        return {}

    monkeypatch.setattr(yh_access, "overnight", no_overnight)
    monkeypatch.setattr(tv_access, "live_session_quotes", no_socket)
    return real_overnight, real_live_quotes


@pytest.fixture(autouse=True)
def _isolate_health_state(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPEBASIS_HEALTH_STATE", str(tmp_path / "health.json"))
    from tapebasis import health

    monitor = health.HealthMonitor()
    monkeypatch.setattr(health, "HealthMonitor", lambda *a, **k: monitor)

    from tapebasis import tools_market, tools_finviz, tools_tradingview

    for module in (tools_market, tools_finviz, tools_tradingview):
        monkeypatch.setattr(module, "MONITOR", monitor, raising=False)
    yield monitor


@pytest.fixture(autouse=True)
def _no_bloomberg_network(monkeypatch):
    """Fail loudly if any test reaches bloomberg.com.

    Bloomberg is asked by ``stock_quote`` and ``stock_prices``, so a fixture
    that forgets to fake it would otherwise hit the live site (and the bot
    wall) from the test suite. Tests that exercise the page decoder patch
    ``_fetch_html`` themselves, which overrides this.
    """
    from tapebasis import bb_access

    async def refuse(path, cache_key):
        raise AssertionError(f"test attempted a live bloomberg.com fetch of {path}")

    monkeypatch.setattr(bb_access, "_fetch_html", refuse)
    yield


@pytest.fixture(autouse=True)
def _no_stockanalysis_network(monkeypatch):
    """Fail loudly if any test reaches stockanalysis.com.

    StockAnalysis is now a leg of ``stock_quote``, ``stock_prices`` and
    ``stock_extended_hours``, so a fixture that forgets to fake it would
    otherwise spend a live request per quote. Tests that exercise the real
    transport request this fixture by name and pass the returned original back
    into ``sa_access._fetch``, so the guard keeps refusing accidental live calls
    everywhere else without blocking the code under test.
    """
    from tapebasis import sa_access

    real_fetch = sa_access._fetch

    async def refuse(path, cache_key):
        raise AssertionError(
            f"test attempted a live stockanalysis.com fetch of {path}"
        )

    monkeypatch.setattr(sa_access, "_fetch", refuse)
    # The tests that exercise the real transport ask for this fixture by name
    # and pass the original back in, so the guard never blocks the code under
    # test while still refusing an accidental live call everywhere else.
    yield real_fetch


@pytest.fixture
def tv_quote():
    """A TradingView scanner row, as ``native.scan`` returns it."""
    return {
        "ticker": "NASDAQ:AAPL",
        "name": "AAPL",
        "description": "Apple Inc.",
        "close": 331.9,
        "change": -1.9,
        "open": 337.1,
        "high": 338.0,
        "low": 330.5,
        "volume": 63160515,
        "update_time": CLOSE_EPOCH,
        "update_mode": "delayed_streaming_900",
        "currency": "USD",
        "exchange": "NASDAQ",
        "type": "stock",
        "subtype": "common",
        "market_cap_basic": 4.84381e12,
        "price_earnings_ttm": 36.98,
        "earnings_per_share_basic_ttm": 8.97,
        "dividends_yield_current": 0.42,
        "sector": "Technology Services",
        "industry": "Computers",
        "price_52_week_high": 351.73,
        "price_52_week_low": 243.42,
        "beta_1_year": 1.19,
        "relative_volume_10d_calc": 0.94,
        "RSI": 41.7,
        "ATR": 7.44,
        "earnings_release_next_date": 1801742400,
        "earnings_release_date": 1793655000,
        "premarket_close": 332.47,
        "premarket_change": 0.17,
        "premarket_volume": 67876,
        "postmarket_close": None,
        "postmarket_change": None,
        "postmarket_volume": None,
        "prev_close_price": None,
    }


@pytest.fixture
def yh_quote():
    """A Yahoo chart-API quote, as ``yh_access.quote`` returns it."""
    return {
        "symbol": "AAPL",
        "price": 331.9,
        "change_pct": -1.9,
        "previous_close": 338.32,
        "currency": "USD",
        "exchange": "NMS",
        "market_state": "CLOSED",
        "market_time": CLOSE_EPOCH,
        "earnings_timestamp": 1801742400,
        "52w_high": 351.73,
        "52w_low": 243.42,
        "day_open": 337.1,
        "day_high": 338.0,
        "day_low": 330.5,
        "volume": 63160515,
        "company": "Apple Inc.",
        "quote_stale": False,
        "source": "Yahoo Finance chart API",
    }


@pytest.fixture
def sa_quote():
    """A StockAnalysis shaped quote, as ``sa_access.quote`` returns it.

    Note the tape is the same consolidated one Yahoo serves: price, previous
    close, day range and the 52-week range are penny-identical to ``yh_quote``
    on purpose, because that is what the live feeds do. ``price_timestamp`` is
    already ISO: ``sa_access`` converts the endpoint's epoch milliseconds.
    """
    return {
        "symbol": "AAPL",
        "requested": "AAPL",
        "price": 331.9,
        "change": -6.42,
        "change_percent": -1.9,
        "previous_close": 338.32,
        "day_open": 337.1,
        "day_high": 338.0,
        "day_low": 330.5,
        "volume": 63160515.0,
        "week_52_high": 351.73,
        "week_52_low": 243.42,
        "exchange": "NASDAQ",
        "market_state": "closed",
        "session": "post",
        "price_date": "2026-11-03",
        "price_timestamp": CLOSE_ISO,
        "price_timestamp_source": "ts (epoch ms)",
        "extended_hours": {
            "session": "Post-market",
            "price": 329.8,
            "change": -2.1,
            "change_percent": -0.63,
            "previous_close": 331.9,
            "volume": 120_000.0,
            "price_timestamp": CLOSE_ISO,
            "price_date": "2026-11-03",
        },
        "has_extended_hours": True,
        "source": "stockanalysis.com consolidated quote API",
    }


@pytest.fixture
def fv_quote():
    """A representative Finviz ``get_quote`` payload (trimmed to what matters)."""
    return {
        "ticker": "AAPL",
        "company": "Apple Inc",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "country": "USA",
        "last_close": {
            "label": "Last Close",
            "price": 331.9,
            "date": "Nov 03 • 3:59 PM ET",
            "change": -6.42,
            "change_percent": -1.9,
        },
        "after_hours": {"price": 329.8, "change_percent": -0.63},
        "snapshot": {},
        "snapshot_numeric": {
            "Prev Close": 338.32,
            "Market Cap": 4.84381e12,
            "P/E": 36.98,
            "RSI (14)": 41.7,
            "Volume": 63160515.0,
            "52W High": 351.73,
            "52W Low": 243.42,
            "ATR (14)": 7.44,
        },
        "profile": "Apple Inc. designs and sells consumer electronics.",
        "peers": [{"ticker": "MSFT", "company": "Microsoft Corp"}],
    }
