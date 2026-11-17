"""Provider constants are derived, and blocking work has its own bounded pool.

Two properties.

``health.PROVIDERS`` and ``tools_market.ALL_PROVIDERS`` were two independent
literals over the same five labels. Adding a leg to one silently left it
unprobed (or unasked), and nothing failed. They now derive from the single
``PROVIDER_ORDER`` list, with Bloomberg excluded from the probe list for the one
stated reason: its site gates plain HTTP clients on the TLS fingerprint.

Blocking provider work used ``asyncio.to_thread``, which runs on the loop's
default executor, shared with everything else that pool serves. A whole-market
screen can occupy every worker for seconds and a fast ``urllib`` read then queues
behind it. Blocking work gets its own bounded pool so the slow lane cannot starve
the fast one.
"""
from __future__ import annotations

import asyncio

import pytest

from tapebasis import blocking_pool
from tapebasis.providers_state import PROVIDER_ORDER


def test_the_market_tools_ask_exactly_the_reconciliation_order():
    """A second literal let a tool ask a provider the reconciler does not order."""
    from tapebasis import tools_market

    assert tools_market.ALL_PROVIDERS == PROVIDER_ORDER


def test_the_health_monitor_probes_every_leg_it_can_reach():
    """Bloomberg is the one leg with no HTTP probe, and only for its TLS gate."""
    from tapebasis import health

    assert set(health.PROVIDERS) == set(PROVIDER_ORDER) - {"BLOOMBERG"}
    assert "BLOOMBERG" not in health.PROVIDERS


def test_error_codes_are_stated_once():
    """The codes this layer emits are listed, so a client can branch on them."""
    from tapebasis.providers_state import ERROR_CODES, ProviderError

    raised = ProviderError("X", "y")
    assert raised.code in ERROR_CODES
    assert "TIMEOUT" in ERROR_CODES and "UPSTREAM_TIMEOUT" in ERROR_CODES


@pytest.mark.asyncio
async def test_blocking_work_runs_off_the_event_loop():
    """A blocking callable must not block the loop that awaits it."""
    import threading

    main = threading.current_thread()
    seen: list[threading.Thread] = []

    def blocking() -> str:
        seen.append(threading.current_thread())
        return "done"

    assert await blocking_pool.run(blocking) == "done"
    assert seen and seen[0] is not main


@pytest.mark.asyncio
async def test_the_pool_is_bounded_and_reused():
    """One executor per loop, with a stated ceiling."""
    first = blocking_pool.executor()
    second = blocking_pool.executor()
    assert first is second
    assert first._max_workers == blocking_pool.MAX_WORKERS


@pytest.mark.asyncio
async def test_more_callers_than_workers_still_all_complete():
    """A ceiling bounds concurrency; it must not drop or deadlock work."""
    results = await asyncio.gather(
        *(
            blocking_pool.run(lambda n=n: n * 2)
            for n in range(blocking_pool.MAX_WORKERS * 4)
        )
    )
    assert results == [n * 2 for n in range(blocking_pool.MAX_WORKERS * 4)]


def test_the_pool_does_not_cross_event_loops():
    """A closed loop's threads must not be inherited by the next loop."""
    held: list[object] = []

    async def grab() -> object:
        pool = blocking_pool.executor()
        held.append(pool)
        blocking_pool.shutdown()
        return pool

    first = asyncio.run(grab())
    second = asyncio.run(grab())
    assert first is not second
