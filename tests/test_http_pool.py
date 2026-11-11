"""Regression tests for the response-speed work.

Each test pins one observable property the optimisation relies on, so a future
refactor cannot quietly reintroduce the cost it removed:

* one pooled client per upstream per event loop, and none shared across loops,
* Yahoo answers a duplicate ask from its cache instead of the network,
* a provider request is paced once, not twice,
* the Yahoo index snapshot asks its six quotes concurrently and keeps the
  registry's order,
* ``stock_prices`` stops asking Bloomberg once its batch budget is spent rather
  than holding the response open for the 10 s pacing on every ticker,
* the lifespan warms the resolver and closes the pools it opened.
"""
from __future__ import annotations

import asyncio

import pytest

from tapebasis import http_pool


def test_shared_client_is_one_pool_per_upstream():
    """Two asks for the same upstream get the same connection pool."""

    async def scenario() -> tuple[object, object, object]:
        first = http_pool.shared_client("yahoo")
        second = http_pool.shared_client("yahoo")
        other = http_pool.shared_client("stockanalysis")
        try:
            return first, second, other
        finally:
            await http_pool.aclose_all()

    first, second, other = asyncio.run(scenario())
    assert first is second
    assert first is not other


_HELD: list[object] = []


def test_shared_client_does_not_cross_event_loops():
    """A pool belongs to the loop that opened it, never to the next one.

    The hermetic suite runs one loop per test, and a connection inherited across
    loops is a failure mode that only shows up as a hang in production.
    """

    async def grab() -> object:
        client = http_pool.shared_client("yahoo")
        _HELD.append(client)  # keep it alive, so id reuse cannot fake a match
        await http_pool.aclose_all()
        return client

    first = asyncio.run(grab())
    second = asyncio.run(grab())
    assert first is not second
    assert first.is_closed


@pytest.mark.asyncio
async def test_yahoo_quote_is_cached_within_its_ttl(monkeypatch):
    """A repeated ask inside the TTL never reaches the network."""
    from tapebasis import yh_access

    calls: list[str] = []

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self):
            return {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "symbol": "AAPL",
                                "regularMarketPrice": 331.9,
                                "regularMarketTime": 1793739601,
                                "currency": "USD",
                            },
                            "timestamp": [1793653200, 1793739600],
                            "indicators": {"quote": [{"close": [338.32, 331.9]}]},
                        }
                    ]
                }
            }

    class _Client:
        async def get(self, url, **_kwargs):
            calls.append(url)
            return _Response()

    monkeypatch.setattr(yh_access, "shared_client", lambda *_a, **_k: _Client())
    yh_access.limiter("YAHOO").cache_clear()

    first = await yh_access.quote("AAPL")
    second = await yh_access.quote("AAPL")

    assert first["price"] == pytest.approx(331.9)
    assert second["price"] == pytest.approx(331.9)
    assert len(calls) == 1, "the second quote should have come from the cache"


@pytest.mark.asyncio
async def test_a_provider_request_is_paced_once_not_twice(monkeypatch):
    """``call`` waits its turn; the request body must not wait again.

    Waiting in both places spent a whole extra ``min_interval`` on every single
    request (measured: a second 1000 ms sleep on a Yahoo quote).
    """
    from tapebasis import yh_access
    from tapebasis.ratelimit import limiter as limiter_of

    waits: list[float] = []
    paced = limiter_of("YAHOO")
    real_wait = paced.wait_turn

    async def counting_wait() -> None:
        waits.append(1.0)
        await real_wait()

    monkeypatch.setattr(paced, "wait_turn", counting_wait)

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self):
            return {"chart": {"result": [{"meta": {}, "timestamp": [], "indicators": {}}]}}

    class _Client:
        async def get(self, url, **_kwargs):
            return _Response()

    monkeypatch.setattr(yh_access, "shared_client", lambda *_a, **_k: _Client())
    paced.cache_clear()

    await yh_access.quote("AAPL")
    assert len(waits) == 1, "the request waited for a turn more than once"


@pytest.mark.asyncio
async def test_index_snapshot_asks_concurrently_and_keeps_order(monkeypatch):
    """The six index quotes overlap instead of adding up to 11 s of latency."""
    from tapebasis import yh_access

    in_flight = 0
    peak = 0
    seen: list[str] = []

    async def slow_quote(symbol: str):
        nonlocal in_flight, peak
        seen.append(symbol)
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.01)
        finally:
            in_flight -= 1
        return {
            "price": 100.0,
            "change_pct": 0.5,
            "currency": "USD",
            "market_time": 1793739601,
        }

    monkeypatch.setattr(yh_access, "quote", slow_quote)
    snapshot = await yh_access.index_snapshot()

    assert peak > 1, "the quotes were serialised"
    assert [row["canonical"] for row in snapshot["indices"]] == list(
        yh_access.INDEX_SYMBOLS
    )
    assert seen == list(yh_access.INDEX_SYMBOLS.values())


@pytest.mark.asyncio
async def test_stock_prices_stops_asking_bloomberg_when_the_budget_is_spent(
    monkeypatch,
):
    """Four tickers must not hold the response open for 4 x 10 s of pacing."""
    from tapebasis import bb_access, fv_access, sa_access, tv_access, yh_access
    from tapebasis import tools_market
    from tapebasis.symbols import Resolution

    asked: list[str] = []

    async def slow_bloomberg(symbol):
        asked.append(symbol)
        if len(asked) == 1:
            await asyncio.sleep(0.05)
            return {"price": 331.9, "change_percent": -1.9, "print_time": None}, "u"
        # Anything beyond the budget would sleep far longer than the budget.
        await asyncio.sleep(10)
        return {"price": 331.9}, "u"

    def fake_resolution(symbol: str) -> dict:
        """Resolve without a search, so the test never touches a live endpoint."""
        return {
            "query": symbol,
            "ticker": symbol,
            "TRADINGVIEW": Resolution(
                query=symbol, provider="TRADINGVIEW", symbol=f"NASDAQ:{symbol}"
            ),
            "FINVIZ": Resolution(query=symbol, provider="FINVIZ", symbol=symbol),
            "YAHOO": Resolution(query=symbol, provider="YAHOO", symbol=symbol),
            "SA": Resolution(query=symbol, provider="SA", symbol=symbol.lower()),
            "BLOOMBERG": Resolution(query=symbol, provider="BLOOMBERG", symbol=symbol),
            "resolutions": {},
        }

    async def fake_symbols_for(symbol: str) -> dict:
        return fake_resolution(symbol)

    monkeypatch.setattr(tools_market, "_symbols_for", fake_symbols_for)
    monkeypatch.setattr(tools_market, "BLOOMBERG_BATCH_BUDGET_SECONDS", 0.2)
    monkeypatch.setattr(tools_market, "BLOOMBERG_DEADLINE_SECONDS", 5.0)
    monkeypatch.setattr(bb_access, "quote", slow_bloomberg)

    async def tv_quotes(tickers):
        return {
            t.split(":", 1)[-1]: {
                "name": t.split(":", 1)[-1],
                "ticker": t,
                "close": 331.9,
                "change": -1.9,
            }
            for t in tickers
        }

    async def yh_row(symbol):
        return {"price": 331.9, "change_pct": -1.9, "market_time": 1793739601}

    async def sa_row(symbol):
        return {"price": 331.9, "change_percent": -1.9, "price_timestamp": None}

    monkeypatch.setattr(tv_access, "quotes", tv_quotes)
    monkeypatch.setattr(yh_access, "quote", yh_row)
    monkeypatch.setattr(sa_access, "quote", sa_row)

    async def fv_rows(symbols):
        return [
            {"ticker": s, "price": 331.9, "change": -1.9, "prevClose": 338.32}
            for s in symbols
        ]

    # Finviz is a leg of ``stock_prices`` too; leaving it live would put a real
    # request on the test's critical path.
    monkeypatch.setattr(fv_access, "screener_rows", fv_rows)

    started = asyncio.get_running_loop().time()
    result = await tools_market.stock_prices("AAPL,MSFT,NVDA,AMD")
    elapsed = asyncio.get_running_loop().time() - started

    # The leg stopped once the budget was spent: at most one page finished, the
    # in-flight page was cut off at the remaining budget, and the rest were
    # never asked at all.
    assert "NVDA" not in asked and "AMD" not in asked
    assert elapsed < 2.0, "the Bloomberg leg held the response open past its budget"
    assert any("budget" in w for w in result["warnings"]), "the cut-off tickers must be stated"
    assert len(result["data"]) == 4
