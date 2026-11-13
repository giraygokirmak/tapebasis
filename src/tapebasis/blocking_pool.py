"""A bounded thread pool for blocking provider work, separate from the default.

Half of this server's provider layer is synchronous: TradingView's screener
posts with ``requests`` and sleeps through its own backoff, its history path
opens ``urllib``, the EGX and backtest services do the same, and Yahoo's options
chain is a blocking call. Each of those has to be moved off the event loop, and
they all used ``asyncio.to_thread``, which runs on the loop's default executor:
twelve workers on an eight-core host, shared with everything else that thread
pool serves.

That sharing is the problem. A backtest or a whole-market screen can occupy
every worker for seconds, and a fast path that happens to need one thread, such
as a small ``urllib`` read, then queues behind it. The slow work is not more
urgent for being slower; it is less urgent.

So blocking provider work gets its own pool with its own ceiling. The default
executor stays available for anything that is genuinely incidental, and the
heavy, high-latency paths cannot starve it.

One executor per event loop, keyed weakly, for the same reason
:mod:`tapebasis.http_pool` and the limiters are: a closed loop's threads must
not be inherited by the next loop a test or a script starts.
"""
from __future__ import annotations

import asyncio
import os
import weakref
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

_T = TypeVar("_T")

#: Ceiling on concurrent blocking provider calls. Deliberately smaller than the
#: default executor's ``min(32, cpu + 4)``: this pool exists to be the *slow*
#: lane, and a large ceiling would let a fan-out flood the upstreams the limiters
#: are pacing anyway. The limiter, not this number, is what controls the rate;
#: this only bounds how many slow calls can sit in flight at once.
MAX_WORKERS = max(1, int(os.environ.get("TAPEBASIS_BLOCKING_THREADS", "4")))

_EXECUTORS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, ThreadPoolExecutor]" = (
    weakref.WeakKeyDictionary()
)


def executor() -> ThreadPoolExecutor:
    """The blocking-work thread pool for the running event loop.

    Created once per loop with ``MAX_WORKERS`` threads. Daemon-ish by
    construction: CPython joins executor threads at interpreter exit, and a
    provider call is expected to finish on its own timeout.

    Returns:
        The pool this loop uses for blocking provider work. Callers must not
        shut it down; :func:`shutdown` does that for the current loop.
    """
    loop = asyncio.get_running_loop()
    pool = _EXECUTORS.get(loop)
    if pool is None:
        pool = ThreadPoolExecutor(
            max_workers=MAX_WORKERS,
            thread_name_prefix="tapebasis-blocking",
        )
        _EXECUTORS[loop] = pool
    return pool


async def run(fn: Callable[..., _T], /, *args: Any, **kwargs: Any) -> _T:
    """Run a blocking callable in this loop's provider thread pool.

    Args:
        fn: The blocking function. It is called in a worker thread, so it must
            not touch the event loop.
        *args: Positional arguments for *fn*.
        **kwargs: Keyword arguments for *fn*.

    Returns:
        Whatever *fn* returned, back on the event loop.
    """
    loop = asyncio.get_running_loop()
    call = lambda: fn(*args, **kwargs)  # noqa: E731 - one-shot partial
    return await loop.run_in_executor(executor(), call)


def shutdown() -> None:
    """Stop the current loop's pool without waiting for running calls.

    Called from the server lifespan. ``wait=False`` is deliberate: a provider
    call in flight has its own timeout, and a shutdown that waited on it would
    hang the process for as long as the slowest upstream.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    pool = _EXECUTORS.pop(loop, None)
    if pool is not None:
        pool.shutdown(wait=False)


__all__ = ["MAX_WORKERS", "executor", "run", "shutdown"]
