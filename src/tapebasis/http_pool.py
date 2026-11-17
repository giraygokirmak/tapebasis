"""Process-wide HTTP connection pools, one per upstream.

Every provider used to build a fresh ``httpx.AsyncClient`` per request, so each
call paid a new TCP and TLS handshake. Measured against the live upstreams, that
handshake was the largest single term in a warm response: a Yahoo chart request
took 1324-2019 ms with a fresh client and 62-70 ms on a reused connection,
TradingView's symbol search 5555 ms versus 80-284 ms, and Yahoo's symbol search
5508 ms versus 56-61 ms.

One client per upstream is also what the limiter already assumed: pacing bounds
how often this process knocks, so there is no reason to throw the connection
away in between.

Clients are keyed by upstream name and by the running event loop. The loop key is
weak, so a closed loop's pools are dropped with it: the hermetic tests run one
loop per test and must never inherit a connection from another test, and a
process that starts a second loop (a script, a re-entrant server start) gets
pools that its loop actually owns. ``aclose_all`` closes the current loop's
pools, which is what the server lifespan does at shutdown.

Nothing here retries, caches or paces. Those stay in :mod:`tapebasis.ratelimit`
and in each provider's access layer.
"""
from __future__ import annotations

import asyncio
import socket
import weakref
from typing import Any

import httpx

#: Default timeout for a pooled client. Every call site passes its own timeout on
#: the request, because the upstreams differ (15 s for a JSON endpoint, 25-30 s
#: for a scanner POST or an HTML page); this value only covers a call that forgot
#: to. It is deliberately not the shortest anywhere: a pooled client that timed
#: out earlier than the caller asked would turn a slow page into a false failure.
DEFAULT_TIMEOUT = 30.0

_CLIENTS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, httpx.AsyncClient]]" = (
    weakref.WeakKeyDictionary()
)

#: Upstreams the health monitor and the tools reach over ``httpx``. Bloomberg is
#: absent on purpose: it is fetched with ``curl_cffi``, whose resolver is libcurl,
#: so an ``getaddrinfo`` warm-up here does nothing for it.
_WARM_ORIGINS: tuple[str, ...] = (
    "scanner.tradingview.com",
    "symbol-search.tradingview.com",
    "finviz.com",
    "query1.finance.yahoo.com",
    "query2.finance.yahoo.com",
    "stockanalysis.com",
)

#: Strong references to the in-flight warm-up tasks. A bare ``create_task``
#: result can be collected before it runs, which would silently drop the warm-up.
_WARMING: set[asyncio.Task[Any]] = set()


def shared_client(
    key: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    follow_redirects: bool = True,
) -> httpx.AsyncClient:
    """The pooled client for *key* on the running loop, created on first use.

    Args:
        key: Upstream name (``"yahoo"``, ``"tradingview"``, ...). Providers that
            share an origin share a key on purpose, so one pool serves them.
        timeout: Client default timeout. A call site that needs a different one
            passes ``timeout=`` on the request instead of making a second pool.
        follow_redirects: Whether the pool follows redirects, as ``httpx`` does
            per client.

    Returns:
        A client owned by the current event loop. The caller must not close it:
        the pool is closed by :func:`aclose_all` when the server shuts down.
    """
    loop = asyncio.get_running_loop()
    pools = _CLIENTS.get(loop)
    if pools is None:
        pools = {}
        _CLIENTS[loop] = pools
    client = pools.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=follow_redirects,
        )
        pools[key] = client
    return client


async def aclose_all() -> None:
    """Close every pooled client of the running loop.

    Called from the server lifespan. A transport that never runs the lifespan
    (FastMCP's streamable HTTP) simply lets the loop's pools go with the process,
    which is what it did before pooling existed.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    pools = _CLIENTS.pop(loop, None) or {}
    for client in pools.values():
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001 - shutdown must not fail on a dead pool
            pass


def warm_origins() -> None:
    """Start resolving every httpx origin in the background, once per loop.

    Worth a module: on a host whose resolver tries mDNS before DNS, the very
    first ``getaddrinfo`` of a process costs about 5 s while every later one
    costs ~20 ms. Paid on the first tool call, that is a 5 s stall on the first
    user request; paid at startup, it is not on the request path at all. The task
    is fire-and-forget so a slow resolver never delays readiness, and it is
    idempotent so the lifespan and ``/health`` can both ask for it.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _is_warmed(loop):
        return

    async def _resolve() -> None:
        await asyncio.gather(
            *(
                loop.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
                for host in _WARM_ORIGINS
            ),
            return_exceptions=True,
        )

    task = loop.create_task(_resolve())
    _WARMING.add(task)
    task.add_done_callback(_WARMING.discard)


_WARMED: "weakref.WeakSet[asyncio.AbstractEventLoop]" = weakref.WeakSet()


def _is_warmed(loop: asyncio.AbstractEventLoop) -> bool:
    """Record the loop and report whether a warm-up was already started for it."""
    if loop in _WARMED:
        return True
    _WARMED.add(loop)
    return False


__all__ = ["DEFAULT_TIMEOUT", "aclose_all", "shared_client", "warm_origins"]
