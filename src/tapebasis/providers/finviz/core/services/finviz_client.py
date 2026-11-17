"""
HTTP transport for the Finviz provider, one place that knows how to talk to finviz.com.

Why this module exists
----------------------
finviz.com is a server-rendered site. Almost nothing it shows is available from
a documented API: the quote header, the 84-field snapshot table, the news table
and the insider table only exist as HTML. The handful of JSON endpoints that do
exist (filings, why-moving, news, indices, screener filters) are the ones the
site's own React islands call, and they are undocumented and unversioned.

So the transport has to behave like the site's own front end:

* a real Chrome User-Agent (a bare ``python-httpx/x`` UA gets a Cloudflare
  interstitial), verified against finviz.com with plain urllib, so no browser
  is required;
* ``Accept: text/html`` for document routes and ``application/json`` for the
  API routes, because the CDN varies on them;
* ``follow_redirects`` because ``/chart.ashx`` 302s to
  ``charts2-node.finviz.com`` and ``/screener.ashx`` → ``/screener/stocks``;
* retries on 429/5xx only: a 404 means "no such tab for this ticker" and
  retrying it just burns rate limit.

Caching
-------
A short TTL cache (default 30s) is not an optimisation here, it is a
correctness feature: a single ``finviz_quote`` call fans out to 3 upstream
requests, and an agent asking for quote + snapshot + peers would otherwise
re-download the same 240 KB page three times in a row. Stale entries are kept
and served when upstream fails, so a rate-limited client still gets numbers.

No proxy layer
--------------
Requests go straight to finviz.com. There is no proxy configuration: the
server is designed to run as-is in a container on a normal egress IP.
"""
from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from tapebasis.http_pool import shared_client
from tapebasis.providers.finviz.core.errors import ErrorCode, FinvizServiceError
from tapebasis.utils import BROWSER_UA

BASE_URL = "https://finviz.com"

#: Chrome UA that finviz.com serves without a Cloudflare challenge. The string
#: has one home in :mod:`tapebasis.utils`; this name stays because Finviz service
#: modules import it.
DEFAULT_USER_AGENT = BROWSER_UA

DEFAULT_TIMEOUT = float(os.environ.get("FINVIZ_TIMEOUT", "25"))
DEFAULT_TTL = float(os.environ.get("FINVIZ_CACHE_TTL", "30"))
MAX_RETRIES = int(os.environ.get("FINVIZ_MAX_RETRIES", "2"))

#: Pool name for the shared client. finviz.com is the only host this layer
#: fetches, so all of its requests share one connection.
_POOL = "finviz"

#: Markers Cloudflare injects into its interstitial / JS challenge page.
_CHALLENGE_MARKERS = (
    "Just a moment",
    "cf-browser-verification",
    "Enable JavaScript and cookies to continue",
    "Attention Required! | Cloudflare",
)


@dataclass
class CacheEntry:
    """One cached upstream response with its own expiry."""

    body: Any
    expires_at: float
    stored_at: float = field(default_factory=time.monotonic)

    def is_fresh(self) -> bool:
        return time.monotonic() < self.expires_at


class _TTLCache:
    """Tiny asyncio-safe TTL cache with stale fallback.

    Not an LRU: entries are bounded by key cardinality (tickers and filter
    combinations in flight), and stale entries are deliberately retained so a
    failed refresh can still answer.
    """

    def __init__(self, max_entries: int = 512) -> None:
        self._data: dict[str, CacheEntry] = {}
        self._max_entries = max_entries
        self._lock = asyncio.Lock()

    async def get(self, key: str, *, allow_stale: bool = False) -> Optional[Any]:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry.is_fresh() or allow_stale:
                return entry.body
            return None

    async def set(self, key: str, body: Any, ttl: float) -> None:
        async with self._lock:
            if len(self._data) >= self._max_entries:
                # Drop the entry with the earliest expiry, cheap, good enough.
                oldest = min(self._data, key=lambda k: self._data[k].expires_at)
                self._data.pop(oldest, None)
            self._data[key] = CacheEntry(body=body, expires_at=time.monotonic() + ttl)

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


_HTML_CACHE = _TTLCache()
_JSON_CACHE = _TTLCache()


def _headers(accept: str) -> dict[str, str]:
    return {
        "User-Agent": os.environ.get("FINVIZ_USER_AGENT", DEFAULT_USER_AGENT),
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": BASE_URL + "/",
        # Ask intermediaries not to hand us a brotli stream we cannot decode.
        "Accept-Encoding": "gzip, deflate",
    }


def _looks_like_challenge(body: str) -> bool:
    head = body[:4000]
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def _looks_like_elite(body: str) -> bool:
    """Detect Finviz Elite paywall redirects returned with HTTP 200."""
    head = body[:3000]
    if "<title>Finviz Elite</title>" in head:
        return True
    return 'href="/login"' in head and "/elite" in head


async def _request_once(
    client: httpx.AsyncClient, url: str, *, accept: str
) -> httpx.Response:
    return await client.get(url, headers=_headers(accept))


async def fetch_text(
    url: str,
    *,
    accept: str = "text/html,application/xhtml+xml",
    ttl: Optional[float] = None,
    cache: Optional[_TTLCache] = None,
    elite_check: bool = False,
) -> str:
    """GET *url* and return decoded text, with cache + retry + error mapping.

    Args:
        url: Absolute URL.
        accept: ``Accept`` header to send.
        ttl: Cache lifetime in seconds; ``0`` disables caching.
        cache: Which cache bucket to use (HTML vs JSON).
        elite_check: Treat a 200 response that is actually the Elite paywall as
            :attr:`ErrorCode.ELITE_ONLY`.

    Raises:
        FinvizServiceError: on timeout, rate limit, block, 4xx/5xx, or a
            Cloudflare challenge page.
    """
    bucket = cache if cache is not None else _JSON_CACHE
    ttl = DEFAULT_TTL if ttl is None else ttl
    key = f"{accept}|{url}"

    if ttl > 0:
        cached = await bucket.get(key)
        if cached is not None:
            return cached

    last_error: Optional[BaseException] = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            client = shared_client(_POOL, timeout=DEFAULT_TIMEOUT)
            response = await _request_once(client, url, accept=accept)

            status = response.status_code

            if status == 429:
                last_error = FinvizServiceError(
                    ErrorCode.UPSTREAM_RATE_LIMIT,
                    "finviz.com rate limited the request (HTTP 429); retry shortly",
                    status=429,
                    retryable=True,
                    url=url,
                )
                await _sleep_backoff(attempt)
                continue

            if status >= 500:
                last_error = FinvizServiceError(
                    ErrorCode.UPSTREAM_ERROR,
                    f"finviz.com returned HTTP {status}",
                    status=status,
                    retryable=True,
                    url=url,
                )
                await _sleep_backoff(attempt)
                continue

            if status == 404:
                raise FinvizServiceError(
                    ErrorCode.NO_DATA,
                    f"finviz.com returned HTTP 404 for {url}",
                    status=404,
                    retryable=False,
                    url=url,
                )

            if status >= 400:
                raise FinvizServiceError(
                    ErrorCode.UPSTREAM_ERROR,
                    f"finviz.com returned HTTP {status} for {url}",
                    status=status,
                    retryable=False,
                    url=url,
                )

            text = response.text
            if _looks_like_challenge(text):
                raise FinvizServiceError(
                    ErrorCode.UPSTREAM_BLOCKED,
                    "finviz.com served a Cloudflare challenge instead of data; "
                    "retry later; the challenge is usually temporary",
                    retryable=True,
                    url=url,
                )
            if elite_check and _looks_like_elite(text):
                raise FinvizServiceError(
                    ErrorCode.ELITE_ONLY,
                    "This data is gated behind a Finviz Elite subscription",
                    retryable=False,
                    url=url,
                )

            if ttl > 0:
                await bucket.set(key, text, ttl)
            return text

        except FinvizServiceError:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            await _sleep_backoff(attempt)
        except Exception as exc:  # pragma: no cover - defensive
            raise FinvizServiceError(
                ErrorCode.INTERNAL_ERROR, f"Unexpected transport failure: {exc!r}", url=url
            ) from exc

    # Every attempt failed: serve stale data if we have any.
    stale = await bucket.get(key, allow_stale=True)
    if stale is not None:
        return stale

    if isinstance(last_error, httpx.TimeoutException):
        raise FinvizServiceError(
            ErrorCode.UPSTREAM_TIMEOUT,
            f"finviz.com did not respond within {DEFAULT_TIMEOUT:.0f}s",
            retryable=True,
            url=url,
        )
    if isinstance(last_error, FinvizServiceError):
        raise last_error
    raise FinvizServiceError(
        ErrorCode.UPSTREAM_ERROR,
        f"finviz.com request failed: {last_error!r}",
        retryable=True,
        url=url,
    )


async def fetch_html(url: str, *, ttl: Optional[float] = None, elite_check: bool = False) -> str:
    """GET an HTML document from finviz.com."""
    return await fetch_text(
        url,
        accept="text/html,application/xhtml+xml",
        ttl=ttl,
        cache=_HTML_CACHE,
        elite_check=elite_check,
    )


async def fetch_json(
    url: str, *, ttl: Optional[float] = None, elite_check: bool = False
) -> Any:
    """GET a JSON document from finviz.com and decode it.

    Raises:
        FinvizServiceError: ``PARSE_ERROR`` when the body is not valid JSON
            (finviz returns an HTML 404 page for unknown API routes).
    """
    import json

    text = await fetch_text(
        url,
        accept="application/json, text/plain, */*",
        ttl=ttl,
        cache=_JSON_CACHE,
        elite_check=elite_check,
    )
    try:
        return json.loads(text)
    except ValueError as exc:
        raise FinvizServiceError(
            ErrorCode.PARSE_ERROR,
            f"finviz.com returned non-JSON content for {url}",
            url=url,
            preview=text[:200],
        ) from exc


async def fetch_bytes(url: str, *, ttl: Optional[float] = None) -> bytes:
    """GET a binary resource (the chart PNG) without content sniffing."""
    last_error: Optional[BaseException] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            client = shared_client(_POOL, timeout=DEFAULT_TIMEOUT)
            response = await client.get(
                url,
                headers=_headers("image/png,image/*,*/*"),
                timeout=DEFAULT_TIMEOUT,
            )
            if response.status_code == 200:
                return response.content
            last_error = FinvizServiceError(
                ErrorCode.UPSTREAM_ERROR,
                f"chart endpoint returned HTTP {response.status_code}",
                status=response.status_code,
                retryable=response.status_code >= 500 or response.status_code == 429,
                url=url,
            )
            if response.status_code < 500 and response.status_code != 429:
                raise last_error
        except FinvizServiceError:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
        await _sleep_backoff(attempt)

    if isinstance(last_error, httpx.TimeoutException):
        raise FinvizServiceError(
            ErrorCode.UPSTREAM_TIMEOUT,
            f"chart endpoint did not respond within {DEFAULT_TIMEOUT:.0f}s",
            retryable=True,
            url=url,
        )
    if isinstance(last_error, FinvizServiceError):
        raise last_error
    raise FinvizServiceError(
        ErrorCode.UPSTREAM_ERROR, f"chart download failed: {last_error!r}", retryable=True
    )


async def _sleep_backoff(attempt: int) -> None:
    """Exponential backoff with jitter, capped so tools stay responsive."""
    if attempt >= MAX_RETRIES:
        return
    delay = min(0.6 * (2**attempt), 4.0) * (0.75 + random.random() * 0.5)
    await asyncio.sleep(delay)


async def clear_cache() -> None:
    """Drop every cached response (used by the health/debug tooling and tests)."""
    await _HTML_CACHE.clear()
    await _JSON_CACHE.clear()


def cache_size() -> dict[str, int]:
    """Return the number of cached HTML and JSON entries."""
    return {"html": len(_HTML_CACHE), "json": len(_JSON_CACHE)}
