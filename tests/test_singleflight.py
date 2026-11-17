"""Single-flight tests: identical concurrent work makes one upstream call.

The cache answers "have I done this already". It cannot answer "am I doing this
right now", so two identical questions that arrive in the same instant both miss
it and both go to the network. Measured before :mod:`tapebasis.singleflight`
existed, on the live upstreams:

* 8 concurrent ``resolve("AAPL", "TRADINGVIEW")`` calls made 8 requests,
* 5 concurrent identical ``stock_quote`` calls made 5 Yahoo requests, serialised
  behind ``max_inflight=1``.

An agent asking for one quote and then for a batch of quotes in the same turn
does exactly that, so the duplication is the normal case.

What these tests pin:

* waiters share one call and all receive its value,
* distinct keys are not merged,
* one waiter being cancelled does not cancel the shared work,
* the entry disappears once the work finishes, so a later ask is a real ask.
"""
from __future__ import annotations

import asyncio

import pytest

from tapebasis import singleflight


@pytest.mark.asyncio
async def test_identical_concurrent_work_runs_once():
    calls = 0

    async def factory() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return 42

    results = await asyncio.gather(
        *(singleflight.run(("k", 1), factory) for _ in range(8))
    )
    assert results == [42] * 8
    assert calls == 1


@pytest.mark.asyncio
async def test_distinct_keys_are_not_merged():
    calls: list[str] = []

    def make(key: str):
        async def factory() -> str:
            calls.append(key)
            await asyncio.sleep(0.01)
            return key

        return factory

    results = await asyncio.gather(
        singleflight.run(("k", "a"), make("a")),
        singleflight.run(("k", "b"), make("b")),
    )
    assert results == ["a", "b"]
    assert sorted(calls) == ["a", "b"]


@pytest.mark.asyncio
async def test_a_later_ask_after_completion_is_a_real_ask():
    """Nothing is cached here: that stays each provider's short TTL cache."""
    calls = 0

    async def factory() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert await singleflight.run(("k", "ttl"), factory) == 1
    assert await singleflight.run(("k", "ttl"), factory) == 2
    assert singleflight.in_flight() == 0


@pytest.mark.asyncio
async def test_a_cancelled_waiter_does_not_cancel_the_shared_work():
    """The other waiters did nothing wrong, so their request must survive."""
    calls = 0
    release = asyncio.Event()

    async def factory() -> str:
        nonlocal calls
        calls += 1
        await release.wait()
        return "done"

    first = asyncio.ensure_future(singleflight.run(("k", "cancel"), factory))
    second = asyncio.ensure_future(singleflight.run(("k", "cancel"), factory))
    await asyncio.sleep(0.01)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    release.set()
    assert await second == "done"
    assert calls == 1


@pytest.mark.asyncio
async def test_exceptions_reach_every_waiter():
    """Every waiter asked the same question, so the same failure is the answer."""

    async def factory() -> int:
        await asyncio.sleep(0.01)
        raise ValueError("upstream said no")

    results = await asyncio.gather(
        *(singleflight.run(("k", "boom"), factory) for _ in range(3)),
        return_exceptions=True,
    )
    assert all(isinstance(r, ValueError) for r in results)


@pytest.mark.asyncio
async def test_symbol_resolution_asks_the_upstream_once(monkeypatch):
    """8 concurrent identical resolutions used to make 8 upstream searches."""
    from tapebasis import symbols

    symbols.clear_cache()
    calls: list[str] = []

    async def fake_search(query: str, *, asset_class: str = "") -> symbols.Resolution:
        calls.append(query)
        await asyncio.sleep(0.02)
        return symbols.Resolution(
            query=query,
            provider="TRADINGVIEW",
            symbol="NASDAQ:AAPL",
            method="search",
        )

    monkeypatch.setattr(symbols, "resolve_tradingview", fake_search)

    results = await asyncio.gather(
        *(symbols.resolve("AAPL", "TRADINGVIEW") for _ in range(8))
    )
    assert {r.symbol for r in results} == {"NASDAQ:AAPL"}
    assert len(calls) == 1
    symbols.clear_cache()


@pytest.mark.asyncio
async def test_identical_quotes_share_one_yahoo_request(monkeypatch):
    """5 concurrent identical ``stock_quote`` calls made 5 Yahoo requests."""
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
                                "shortName": "Apple Inc.",
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
            await asyncio.sleep(0.02)
            return _Response()

    monkeypatch.setattr(yh_access, "shared_client", lambda *_a, **_k: _Client())
    yh_access.limiter("YAHOO").cache_clear()

    results = await asyncio.gather(*(yh_access.quote("AAPL") for _ in range(5)))
    assert all(r["price"] == pytest.approx(331.9) for r in results)
    assert len(calls) == 1
    yh_access.limiter("YAHOO").cache_clear()
