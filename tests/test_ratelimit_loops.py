"""Per-loop limiter primitives and the symbol cache cap.

Two bugs motivate this file.

An ``asyncio.Semaphore`` or ``asyncio.Lock`` built at import time belongs to no
loop; it binds to the first loop that *contends* it, and the second loop to
contend raises ``RuntimeError: ... is bound to a different event loop``. That is
invisible in a single-loop server and breaks the moment anything starts a second
loop: a test runner, a script, a re-entrant start. The limiters now create their
primitives per loop, keyed weakly, the same pattern ``http_pool`` uses.

The symbol cache had no ceiling. A long-lived server sees an unbounded stream of
arbitrary queries, and 3000 distinct queries used to mean 3000 entries that never
left.
"""
from __future__ import annotations

import asyncio

import pytest

from tapebasis.ratelimit import limiter


def test_cross_loop_contention_does_not_raise(monkeypatch):
    """Two loops contending one limiter must not inherit each other's lock.

    Before the per-loop primitives, the second loop raised
    ``RuntimeError: <asyncio.locks.Lock ...> is bound to a different event loop``.
    """
    paced = limiter("YAHOO")

    async def no_wait() -> None:
        return None

    # The YAHOO limiter is process-wide, so the stub must be undone: leaking it
    # into another test turns ``call`` into "await None".
    monkeypatch.setattr(paced, "wait_turn", no_wait)
    results: list[str] = []

    async def contend() -> None:
        semaphore = paced._semaphore
        lock = paced._interval_lock
        async with semaphore:
            async with lock:
                results.append("ran")

    asyncio.run(contend())
    asyncio.run(contend())
    assert results == ["ran", "ran"]


def test_each_loop_gets_its_own_primitives():
    """The primitives are per loop, so no loop can hand one to another."""
    paced = limiter("YAHOO")
    seen: list[tuple[object, object]] = []

    async def grab() -> None:
        seen.append((paced._semaphore, paced._interval_lock))

    asyncio.run(grab())
    asyncio.run(grab())
    assert seen[0][0] is not seen[1][0]
    assert seen[0][1] is not seen[1][1]


def test_the_same_loop_reuses_its_primitives():
    """Created once per loop on first use, not per request."""
    paced = limiter("YAHOO")
    seen: list[object] = []

    async def grab() -> None:
        seen.append(paced._semaphore)
        seen.append(paced._semaphore)

    asyncio.run(grab())
    assert seen[0] is seen[1]


@pytest.mark.asyncio
async def test_limiter_primitives_come_from_the_running_loop():
    """The primitives are created inside the loop that will use them."""
    paced = limiter("TRADINGVIEW")
    loop = asyncio.get_running_loop()
    assert paced._semaphore is not None
    assert loop in paced._per_loop


def test_symbol_cache_is_capped():
    """3000 distinct queries must not mean 3000 permanent entries."""
    from tapebasis import symbols

    symbols.clear_cache()
    for index in range(symbols._CACHE_MAX_ENTRIES + 40):
        symbols._cache_put(
            ("TRADINGVIEW", f"Q{index}|"),
            symbols.Resolution(query=f"Q{index}", provider="TRADINGVIEW"),
        )
    assert len(symbols._CACHE) == symbols._CACHE_MAX_ENTRIES
    symbols.clear_cache()


def test_symbol_cache_evicts_oldest_first():
    """The newest entries are the ones worth keeping."""
    from tapebasis import symbols

    symbols.clear_cache()
    for index in range(symbols._CACHE_MAX_ENTRIES):
        symbols._cache_put(
            ("TRADINGVIEW", f"Q{index}|"),
            symbols.Resolution(query=f"Q{index}", provider="TRADINGVIEW"),
        )
    symbols._cache_put(
        ("TRADINGVIEW", "NEWEST|"),
        symbols.Resolution(query="NEWEST", provider="TRADINGVIEW"),
    )
    assert ("TRADINGVIEW", "NEWEST|") in symbols._CACHE
    assert ("TRADINGVIEW", "Q0|") not in symbols._CACHE
    assert len(symbols._CACHE) == symbols._CACHE_MAX_ENTRIES
    symbols.clear_cache()
