"""Per-provider request pacing, caching and back-pressure.

Every upstream this server talks to is undocumented and rate-limited by its
owner. Two of them are aggressive about it:

* ``query1.finance.yahoo.com`` starts answering ``429 Too Many Requests`` after
  a short burst and then stays angry for a while.
* ``data.tradingview.com`` drops the chart websocket, or resolves symbols to
  ``invalid symbol``, when connections arrive too fast from one IP.

Retrying harder is the wrong reaction: it deepens the block. What actually
helps, and what this module provides:

``min_interval``   A hard floor between two requests to one provider, so a
                   fan-out over 30 tickers does not become a 30-request burst.
``max_inflight``   Bounds concurrent requests per provider.
``cooldown``       A shared, exponentially growing pause after a ``429`` (or a
                   websocket ``invalid symbol``). Every caller waits it out, so
                   one rate-limited request protects the whole process instead
                   of each caller discovering the block separately.
``cache``          A short TTL cache so repeat questions (a quote asked twice in
                   one agent turn) never reach the network twice.

State is per process and per provider. Nothing here is persisted: a restart
should start optimistic.

The ``asyncio`` primitives that enforce ``min_interval``/``max_inflight`` are
created per event loop, on first use, and held in a weak table keyed by the
loop. An ``asyncio.Semaphore`` or ``asyncio.Lock`` built at import time belongs
to no loop and binds to the first one that *contends* it, so the second loop to
contend raises ``RuntimeError: ... is bound to a different event loop``. That
never shows up in a single-loop server, and it breaks the moment anything starts
a second loop: a test runner, a script, a re-entrant start. ``http_pool`` grew
the same weak loop key for the same reason; the limiters now match it.
"""
from __future__ import annotations

import asyncio
import os
import random
import time
import weakref
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

#: Base cooldown applied the first time a provider answers 429. Doubles on each
#: consecutive block up to ``max_cooldown``, and decays back after a success.
BASE_COOLDOWN = 5.0
MAX_COOLDOWN = 120.0


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class ProviderLimiter:
    """Pacing state for one upstream."""

    provider: str
    min_interval: float
    max_inflight: int
    max_retries: int = 2
    _last_call: float = field(default=0.0, init=False, repr=False)
    _cooldown_until: float = field(default=0.0, init=False, repr=False)
    _block_streak: int = field(default=0, init=False, repr=False)
    _cache: dict[str, tuple[float, Any]] = field(default_factory=dict, init=False, repr=False)
    #: loop -> the primitives that loop owns. Weak, so a closed loop's
    #: semaphore and lock go with it instead of binding the next loop to a
    #: primitive it does not own.
    _per_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, tuple[asyncio.Semaphore, asyncio.Lock]]" = (
        field(default_factory=weakref.WeakKeyDictionary, init=False, repr=False)
    )

    # ── per-loop primitives ─────────────────────────────────────────────────
    def _primitives(self) -> tuple[asyncio.Semaphore, asyncio.Lock]:
        """The (semaphore, interval lock) pair belonging to the running loop.

        Created on first use in each loop, so a limiter shared by two loops
        never hands one loop's primitive to the other.

        Returns:
            The semaphore that bounds concurrency and the lock that serialises
            the ``min_interval`` wait, both owned by the current loop.
        """
        loop = asyncio.get_running_loop()
        pair = self._per_loop.get(loop)
        if pair is None:
            pair = (
                asyncio.Semaphore(max(1, self.max_inflight)),
                asyncio.Lock(),
            )
            self._per_loop[loop] = pair
        return pair

    @property
    def _semaphore(self) -> asyncio.Semaphore:
        """The concurrency gate for the running loop."""
        return self._primitives()[0]

    @property
    def _interval_lock(self) -> asyncio.Lock:
        """The lock that serialises ``min_interval`` spacing for this loop."""
        return self._primitives()[1]

    # ── cooldown ────────────────────────────────────────────────────────────
    def note_rate_limited(self) -> float:
        """Record a ``429``/block and return how long callers should now wait."""
        self._block_streak = min(self._block_streak + 1, 6)
        delay = min(BASE_COOLDOWN * (2 ** (self._block_streak - 1)), MAX_COOLDOWN)
        delay += random.uniform(0, delay * 0.2)  # jitter, so retries spread out
        self._cooldown_until = max(self._cooldown_until, time.monotonic() + delay)
        return delay

    def note_success(self) -> None:
        """A good response decays the block streak so a blip does not linger."""
        self._block_streak = max(0, self._block_streak - 1)
        if self._block_streak == 0:
            self._cooldown_until = 0.0

    async def wait_turn(self) -> None:
        """Block until this provider may be called again."""
        pause = self._cooldown_until - time.monotonic()
        if pause > 0:
            await asyncio.sleep(pause)
        async with self._interval_lock:
            gap = time.monotonic() - self._last_call
            if gap < self.min_interval:
                await asyncio.sleep(self.min_interval - gap)
            self._last_call = time.monotonic()

    # ── cache ───────────────────────────────────────────────────────────────
    def cache_get(self, key: str, ttl: float) -> Any | None:
        if ttl <= 0:
            return None
        hit = self._cache.get(key)
        if not hit:
            return None
        stamped, value = hit
        if time.monotonic() - stamped > ttl:
            self._cache.pop(key, None)
            return None
        return value

    def cache_set(self, key: str, value: Any) -> None:
        # Bounded: this cache only exists to absorb duplicates within a turn.
        if len(self._cache) > 512:
            self._cache.clear()
        self._cache[key] = (time.monotonic(), value)

    def cache_clear(self) -> None:
        self._cache.clear()

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        return {
            "provider": self.provider,
            "min_interval_s": self.min_interval,
            "max_inflight": self.max_inflight,
            "cooling_down_s": round(max(0.0, self._cooldown_until - now), 1),
            "block_streak": self._block_streak,
            "cached_entries": len(self._cache),
        }


class RateLimitError(Exception):
    """Raised when a provider is in cooldown and the caller opted to skip."""

    def __init__(self, provider: str, wait_s: float):
        super().__init__(f"{provider} is cooling down for another {wait_s:.1f}s")
        self.provider = provider
        self.wait_s = wait_s


LIMITERS: dict[str, ProviderLimiter] = {
    "TRADINGVIEW": ProviderLimiter(
        provider="TRADINGVIEW",
        min_interval=_env_float("TAPEBASIS_TV_MIN_INTERVAL", 0.5),
        max_inflight=_env_int("TAPEBASIS_TV_MAX_INFLIGHT", 2),
        max_retries=_env_int("TAPEBASIS_TV_MAX_RETRIES", 2),
    ),
    "FINVIZ": ProviderLimiter(
        provider="FINVIZ",
        min_interval=_env_float("TAPEBASIS_FINVIZ_MIN_INTERVAL", 0.35),
        max_inflight=_env_int("TAPEBASIS_FINVIZ_MAX_INFLIGHT", 2),
        max_retries=_env_int("TAPEBASIS_FINVIZ_MAX_RETRIES", 2),
    ),
    "YAHOO": ProviderLimiter(
        provider="YAHOO",
        # Yahoo is the most short-tempered of the providers.
        min_interval=_env_float("TAPEBASIS_YAHOO_MIN_INTERVAL", 1.0),
        max_inflight=_env_int("TAPEBASIS_YAHOO_MAX_INFLIGHT", 1),
        max_retries=_env_int("TAPEBASIS_YAHOO_MAX_RETRIES", 2),
    ),
    # StockAnalysis fronts its API with Cloudflare and advertises a 3 s shared
    # cache, so it tolerates a normal pace; it still punishes a burst from one
    # IP, and the batch tools fan out over a ticker list.
    "SA": ProviderLimiter(
        provider="SA",
        min_interval=_env_float("TAPEBASIS_SA_MIN_INTERVAL", 0.5),
        max_inflight=_env_int("TAPEBASIS_SA_MAX_INFLIGHT", 2),
        max_retries=_env_int("TAPEBASIS_SA_MAX_RETRIES", 2),
    ),
    # Bloomberg is a reconciliation leg now, and it still has an upstream that
    # punishes bursts. Its HTML path tolerated ~5 requests 10 s apart while its
    # separate API bucket burned after ~10 rapid calls and stayed 403 for
    # minutes, so this is deliberately the slowest limiter here. ``stock_quote``
    # bounds the wait with a deadline instead of holding the response open, and
    # ``stock_prices`` caps how many tickers it asks about per call.
    "BLOOMBERG": ProviderLimiter(
        provider="BLOOMBERG",
        min_interval=_env_float("TAPEBASIS_BLOOMBERG_MIN_INTERVAL", 10.0),
        max_inflight=_env_int("TAPEBASIS_BLOOMBERG_MAX_INFLIGHT", 1),
        max_retries=_env_int("TAPEBASIS_BLOOMBERG_MAX_RETRIES", 1),
    ),
}


def limiter(provider: str) -> ProviderLimiter:
    return LIMITERS[str(provider).upper()]


async def call(
    provider: str,
    fn: Callable[[], Awaitable[Any]],
    *,
    attempts: int | None = None,
) -> Any:
    """Run one provider request under its limiter, retrying on ``429``.

    ``fn`` should raise :class:`RateLimited` when the upstream says ``429`` so
    this wrapper can apply the shared cooldown instead of a private sleep.
    """
    paced = limiter(provider)
    tries = paced.max_retries if attempts is None else attempts
    last: BaseException | None = None
    for attempt in range(tries + 1):
        await paced.wait_turn()
        async with paced._semaphore:  # noqa: SLF001 - intentional, same module family
            try:
                value = await fn()
                paced.note_success()
                return value
            except RateLimited as exc:
                delay = paced.note_rate_limited()
                last = exc
                if attempt >= tries:
                    break
                await asyncio.sleep(min(delay, MAX_COOLDOWN))
            except Exception as exc:  # noqa: BLE001 - retry only transport-ish errors
                if not _is_transient(exc) or attempt >= tries:
                    raise
                last = exc
                await asyncio.sleep(min(0.5 * (2 ** attempt), 8.0))
    raise RateLimitError(provider, max(0.0, paced._cooldown_until - time.monotonic())) from last  # noqa: SLF001


class RateLimited(Exception):
    """Provider signalled a rate limit (HTTP 429, or a websocket block)."""

    def __init__(self, provider: str, detail: str = "", *, retry_after: float | None = None):
        super().__init__(f"{provider} rate limited: {detail or 'HTTP 429'}")
        self.provider = provider
        self.detail = detail
        self.retry_after = retry_after


def _is_transient(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    return any(token in name for token in ("timeout", "connect", "transport", "closed"))


def snapshot() -> dict[str, Any]:
    """Per-provider limiter state, for ``tapebasis_health``."""
    return {name: l.snapshot() for name, l in LIMITERS.items()}
