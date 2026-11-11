"""Deduplicate identical work that is already in flight.

A cache answers "have I done this already". It cannot answer "am I doing this
right now", so two identical questions that arrive in the same instant both miss
it and both go to the network. Measured before this module existed:

* 8 concurrent ``resolve("AAPL", "TRADINGVIEW")`` calls made 8 upstream
  requests for one symbol,
* 5 concurrent identical ``stock_quote`` calls made 5 Yahoo requests, serialised
  behind ``max_inflight=1``, so the cost grew linearly with the caller count.

An agent that asks for a quote and then for a batch of quotes in the same turn
does exactly that, so the duplication is the normal case, not an edge case.

Only the *waiters* are merged, never the results: the first caller runs the
work, everyone else awaits the same task, and when it finishes the value is
returned to all of them exactly as if each had run it. Nothing is cached here;
that stays each provider's short TTL cache, so a request made a moment later
still makes its own upstream call.

The in-flight table is keyed by the running event loop through a weak
dictionary, the same pattern :mod:`tapebasis.http_pool` uses: the hermetic tests
run one loop per test and must never await a task that belongs to a closed loop.

Cancellation: a waiter that is cancelled is detached (``asyncio.shield``) rather
than cancelling the shared task, because the other waiters did nothing wrong. A
task whose every waiter is gone still completes and then disappears; it is one
request the process was already making.
"""
from __future__ import annotations

import asyncio
import weakref
from typing import Any, Awaitable, Callable, Hashable

#: loop -> key -> the task producing that key's value.
_INFLIGHT: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[Hashable, asyncio.Task[Any]]]" = (
    weakref.WeakKeyDictionary()
)


def _table() -> dict[Hashable, asyncio.Task[Any]]:
    """The in-flight table for the running loop, created on first use."""
    loop = asyncio.get_running_loop()
    table = _INFLIGHT.get(loop)
    if table is None:
        table = {}
        _INFLIGHT[loop] = table
    return table


def in_flight() -> int:
    """How many distinct keys are being computed on the running loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return 0
    return len(_INFLIGHT.get(loop) or {})


async def run(key: Hashable, factory: Callable[[], Awaitable[Any]]) -> Any:
    """Return *factory*'s value, running it once no matter how many callers ask.

    Args:
        key: Identity of the work. Two callers with equal keys share one call,
            so the key must describe the request completely (provider, ticker,
            parameters), never the caller.
        factory: Zero-argument coroutine function that performs the work. It is
            called only by the first caller; the rest await its result.

    Returns:
        The value *factory* produced. Exceptions propagate to every waiter
        unchanged, since they all described the same request.
    """
    table = _table()
    task = table.get(key)
    if task is None:
        task = asyncio.ensure_future(factory())
        table[key] = task

        def _forget(_finished: asyncio.Task[Any]) -> None:
            # Only remove our own entry: a later caller may already have
            # registered a fresh task under the same key.
            if table.get(key) is _finished:
                table.pop(key, None)

        task.add_done_callback(_forget)
    # ``shield`` keeps one cancelled waiter from cancelling the request the
    # others are waiting on.
    return await asyncio.shield(task)


__all__ = ["in_flight", "run"]
