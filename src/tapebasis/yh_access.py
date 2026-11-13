"""Thin, typed access to the Yahoo Finance chart API.

Yahoo is a first-class provider here, not a fallback hidden inside another one.
It is the only provider here that will quote a spot gold pair with a single
unambiguous ticker (``XAUUSD=X``), and its history endpoint is stable and
documented by a decade of use.

Everything goes through :mod:`tapebasis.ratelimit`: Yahoo starts answering
``429`` after a short burst and then stays angry, so the limiter enforces one
request at a time with a shared cooldown, and a short TTL cache absorbs the
duplicate asks an agent naturally makes.

Transport is a pooled client from :mod:`tapebasis.http_pool`, not a client per
request: the TLS handshake to Yahoo cost 1324-2019 ms per call against 62-70 ms
on a reused connection, which was the dominant term in a warm ``stock_quote``.
Pacing still bounds the request rate, so the connection is safe to keep.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
import weakref
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from . import blocking_pool, singleflight
from .http_pool import shared_client
from .providers_state import NoDataError, ProviderError
from .ratelimit import RateLimited, RateLimitError, call, limiter
from .symbols import INSTRUMENTS, INDEX_SNAPSHOT
from .utils import BROWSER_UA

PROVIDER = "YAHOO"
_POOL = "yahoo"

#: How long a shaped response may be served from memory. Yahoo's chart endpoint
#: answers with a quote that moves within the minute, so this is deliberately
#: short: it exists to absorb the duplicate asks one agent turn makes (a quote,
#: then a comparison of the same quote) and to make a repeated ``market_indices``
#: free, not to serve a stale price. The other providers carry the same kind of
#: cache (TradingView 15 s, Finviz 30 s, StockAnalysis 20 s, Bloomberg 60 s);
#: Yahoo was the only one without it.
_CACHE_TTL = float(os.environ.get("TAPEBASIS_YAHOO_CACHE_TTL", "15"))
_CHART = "https://query1.finance.yahoo.com/v8/finance/chart"
#: Yahoo's chart API serves the same browser identity the other legs present;
#: the string lives in :mod:`tapebasis.utils` so refreshing it is one edit.
_UA = BROWSER_UA

#: 5 days (not 2): when the newest session has no trades yet its close is None,
#: and a 2-day window then leaves only ONE usable close, too few to derive a
#: previous close, which used to fall back to the same bar and report a 0% move.
_QUOTE_RANGE = "5d"

#: How far ``meta.regularMarketTime`` may lag the newest candle before the whole
#: quote block is treated as stale. One day covers normal intraday lag.
_STALE_QUOTE_SECONDS = 86_400

#: Yahoo's public quote endpoint requires the same cookie-bound crumb as its
#: options endpoint. The cookie session retains the identity the crumb belongs
#: to; a lock prevents two handshakes from crossing those identities.
_QUOTE = "https://query1.finance.yahoo.com/v7/finance/quote"
_QUOTE_SESSION_TTL = 1500.0
_quote_session: dict[str, Any] = {"opener": None, "crumb": None, "created": 0.0}
_quote_session_locks: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, asyncio.Lock
] = weakref.WeakKeyDictionary()


def _cookie_session() -> Any:
    """Return a parser-independent cookie opener for Yahoo's session callback.

    Isolated here so tests can replace the remote handshake without exposing a
    parser from another provider as this access layer's credentials.
    """
    from .providers.tradingview.core.services.options_service import _get_session

    return _get_session()


def _session_lock() -> asyncio.Lock:
    """Return a credential lock owned by the running event loop."""
    loop = asyncio.get_running_loop()
    lock = _quote_session_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _quote_session_locks[loop] = lock
    return lock


async def _quote_session_credentials() -> tuple[Any, str]:
    """Return a fresh Yahoo opener and its cookie-bound crumb.

    The remote handshake runs only outside ``ratelimit.call``: a caller already
    holding Yahoo's single request slot must not wait for a second paced call.
    """
    async with _session_lock():
        now = time.monotonic()
        if (
            _quote_session["opener"] is not None
            and _quote_session["crumb"]
            and now - _quote_session["created"] < _QUOTE_SESSION_TTL
        ):
            return _quote_session["opener"], _quote_session["crumb"]
        crumb, opener = await blocking_pool.run(_cookie_session)
        if not crumb:
            raise ProviderError(PROVIDER, "Yahoo returned no session crumb")
        _quote_session.update(opener=opener, crumb=crumb, created=now)
        return opener, crumb


def _quote_page(opener: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Fetch one quote through Yahoo's cookie session with its own timeouts."""
    url = f"{_QUOTE}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "application/json"}
    )
    with opener.open(request, timeout=15.0) as response:
        status = getattr(response, "status", 200)
        if status == 429:
            raise RateLimited(PROVIDER, "quote HTTP 429")
        return _json_load(response)


def _json_load(response: Any) -> Any:
    """Decode Yahoo's JSON response for an already-opened HTTP connection."""
    return json.loads(response.read().decode("utf-8"))


async def _yahoo_quote_request(
    fetcher: Callable[[Any, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Run a prepared Yahoo quote request outside the active provider limiter.

    ``fetcher`` receives the authenticated opener and the request parameters.
    Authentication recovery repeats the outer request only after the inner call
    has released its slot. The prepared network callable therefore never waits
    on a lock owned by its own retry path.
    """
    attempt = 0
    while True:
        opener, crumb = await _quote_session_credentials()
        params = {"formatted": "true", "overnightPrice": "true", "crumb": crumb}

        async def _once() -> dict[str, Any]:
            try:
                return await blocking_pool.run(fetcher, opener, params)
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    # ``call`` owns cooldown and retries. Let it observe the
                    # throttle instead of converting it after it has exited.
                    raise RateLimited(PROVIDER, "quote HTTP 429") from exc
                raise

        try:
            return await call(PROVIDER, _once)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                # urllib raises before the status check in _quote_page; preserve
                # the shared limiter protocol instead of retrying a burst here.
                raise RateLimited(PROVIDER, "quote HTTP 429") from exc
            if exc.code not in (401, 403) or attempt:
                raise ProviderError(
                    PROVIDER, f"Yahoo quote HTTP {exc.code}", code="UPSTREAM_HTTP_ERROR"
                ) from exc
            async with _session_lock():
                # A concurrent refreshed session supersedes this failed opener.
                if _quote_session.get("opener") is opener:
                    _quote_session.update(opener=None, crumb=None, created=0.0)
            attempt += 1
        except RateLimitError as exc:
            raise ProviderError(
                PROVIDER,
                "Yahoo Finance is rate limiting this server; retry later",
                code="UPSTREAM_RATE_LIMIT",
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderError(
                PROVIDER,
                f"Yahoo quote transport failed: {exc.reason}",
                code="PROVIDER_ERROR",
            ) from exc


async def _get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    cache_key: str | None = None,
) -> dict[str, Any]:
    """Fetch one Yahoo JSON endpoint under the limiter, with a short TTL cache.

    Args:
        url: Absolute endpoint URL.
        params: Query parameters.
        cache_key: Cache identity. Defaults to the URL plus its parameters, so a
            second identical ask within ``_CACHE_TTL`` never reaches the network.

    Returns:
        The decoded JSON payload.

    Raises:
        NoDataError: Yahoo answered 404 for the symbol.
        ProviderError: Yahoo rate limited this server, or the request failed.
    """
    paced = limiter(PROVIDER)
    key = cache_key or f"get|{url}|{sorted((params or {}).items())}"
    cached = paced.cache_get(key, _CACHE_TTL)
    if isinstance(cached, dict):
        return cached

    async def _once() -> dict[str, Any]:
        # ``call`` already waited its turn, so waiting again here would spend a
        # second ``min_interval`` on every single request.
        client = shared_client(_POOL)
        response = await client.get(
            url,
            params=params,
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=15.0,
        )
        if response.status_code == 429:
            raise RateLimited(PROVIDER, "chart HTTP 429")
        if response.status_code == 404:
            raise NoDataError(PROVIDER, f"Yahoo has no chart for {url.rsplit('/', 1)[-1]}")
        response.raise_for_status()
        payload = response.json()
        paced.cache_set(key, payload)
        return payload

    async def _fetch_once() -> dict[str, Any]:
        # Two identical questions in the same instant used to be two requests,
        # serialised behind ``max_inflight=1``: five concurrent identical
        # ``stock_quote`` calls made five Yahoo requests. The limiter is what
        # paces this upstream, so the duplicate must not reach it at all.
        cached_now = paced.cache_get(key, _CACHE_TTL)
        if isinstance(cached_now, dict):
            return cached_now
        return await call(PROVIDER, _once)

    try:
        return await singleflight.run(("yahoo", key), _fetch_once)
    except RateLimited as exc:
        raise ProviderError(
            PROVIDER,
            "Yahoo Finance is rate limiting this server; retry later",
            code="UPSTREAM_RATE_LIMIT",
        ) from exc


def _first_result(payload: dict[str, Any]) -> dict[str, Any]:
    chart = payload.get("chart") or {}
    error = chart.get("error")
    if error:
        raise NoDataError(PROVIDER, str(error.get("description") or error))
    results = chart.get("result") or []
    if not results:
        raise NoDataError(PROVIDER, "Yahoo returned no chart result")
    return results[0]


def _valid_closes(result: dict[str, Any]) -> list[float]:
    try:
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        return [c for c in closes if c is not None]
    except (IndexError, TypeError, KeyError):
        return []


def _quote_is_stale(result: dict[str, Any]) -> bool:
    meta = result.get("meta") or {}
    market_time = meta.get("regularMarketTime")
    stamps = result.get("timestamp") or []
    if not market_time or not stamps:
        return False
    newest = max(stamps)
    return (newest - market_time) > _STALE_QUOTE_SECONDS


def _previous_close(result: dict[str, Any], price: float | None) -> float | None:
    """Previous close from the candle series, not from ``chartPreviousClose``.

    ``chartPreviousClose`` is the close *before the requested range*, which for
    a 5-day window is a week old, comparing today's price to it produces a
    plausible-looking but wrong day change. The last-two-closes derivation is
    correct whenever the current session has a print.
    """
    closes = _valid_closes(result)
    if len(closes) >= 2:
        return closes[-2]
    if price is not None:
        return closes[-1] if closes else None
    return (result.get("meta") or {}).get("chartPreviousClose")


def _format_quote(symbol: str, result: dict[str, Any]) -> dict[str, Any]:
    meta = result.get("meta") or {}
    price = meta.get("regularMarketPrice")
    if price is None:
        closes = _valid_closes(result)
        price = closes[-1] if closes else None
    previous = _previous_close(result, price)
    change_pct = None
    if price is not None and previous:
        change_pct = round((price - previous) / previous * 100, 4)
    return {
        "symbol": meta.get("symbol") or symbol,
        "price": price,
        "change_pct": change_pct,
        "previous_close": previous,
        "currency": meta.get("currency"),
        "exchange": meta.get("exchangeName") or meta.get("fullExchangeName"),
        "market_state": meta.get("marketState"),
        # The market print time, in epoch seconds. This is what freshness
        # arbitration compares, never the fetch time.
        "market_time": meta.get("regularMarketTime"),
        "earnings_timestamp": meta.get("earningsTimestamp")
        or meta.get("earningsTimestampStart"),
        "52w_high": meta.get("fiftyTwoWeekHigh"),
        "52w_low": meta.get("fiftyTwoWeekLow"),
        # The session's own range. These were always in ``meta`` and were never
        # shaped, so the day's high/low arrived in every request and was thrown
        # away before any tool could see it. ``regularMarketOpen`` is absent on
        # some symbols and some ranges, hence the optional read.
        "day_open": meta.get("regularMarketOpen"),
        "day_high": meta.get("regularMarketDayHigh"),
        "day_low": meta.get("regularMarketDayLow"),
        "volume": meta.get("regularMarketVolume"),
        "company": meta.get("shortName") or meta.get("longName"),
        # Yahoo's own statement of the session, and the session-inclusive price
        # it publishes beside the regular one. ``regularMarketPrice`` freezes
        # when the regular session ends, so before the open it is the previous
        # close while ``fulldayPrice`` is the live pre-market print. Both are
        # Yahoo's, read off the same response; the session field is what lets a
        # caller tell which one it is holding.
        "fullday_price": meta.get("fulldayPrice"),
        "fullday_change_percent": meta.get("fulldayChangePercent"),
        "has_pre_post": meta.get("hasPrePostMarketData"),
        "quote_stale": _quote_is_stale(result),
        "source": "Yahoo Finance chart API",
    }


async def quote(symbol: str) -> dict[str, Any]:
    """Latest quote for one Yahoo symbol (``AAPL``, ``XAUUSD=X``, ``^GSPC``)."""
    payload = await _get(
        f"{_CHART}/{symbol}",
        params={"interval": "1d", "range": _QUOTE_RANGE},
        cache_key=f"quote|{symbol}",
    )
    return _format_quote(symbol, _first_result(payload))


async def history(
    symbol: str,
    *,
    period: str = "1y",
    interval: str = "1d",
) -> dict[str, Any]:
    """OHLCV history for one symbol."""
    payload = await _get(
        f"{_CHART}/{symbol}",
        params={
            "interval": interval,
            "range": period,
            "includeAdjustedClose": "true",
        },
        cache_key=f"history|{symbol}|{interval}|{period}",
    )
    result = _first_result(payload)
    stamps = result.get("timestamp") or []
    quote_block = (result.get("indicators", {}).get("quote") or [{}])[0]
    opens = quote_block.get("open") or []
    highs = quote_block.get("high") or []
    lows = quote_block.get("low") or []
    closes = quote_block.get("close") or []
    volumes = quote_block.get("volume") or []
    bars = []
    for index, stamp in enumerate(stamps):
        close = closes[index] if index < len(closes) else None
        if close is None:
            continue
        bars.append(
            {
                "timestamp": stamp,
                "open": opens[index] if index < len(opens) else None,
                "high": highs[index] if index < len(highs) else None,
                "low": lows[index] if index < len(lows) else None,
                "close": close,
                "volume": volumes[index] if index < len(volumes) else None,
            }
        )
    if not bars:
        raise NoDataError(PROVIDER, f"Yahoo returned no usable bars for {symbol}")
    return {
        "symbol": symbol,
        "interval": interval,
        "period": period,
        "bars": bars,
        "source": "yahoo",
        "price_timestamp": bars[-1]["timestamp"],
    }


#: Index groups the market snapshot reports.
_SNAPSHOT_GROUPS: dict[str, tuple[str, ...]] = {
    "indices": ("^GSPC", "^DJI", "^IXIC", "^VIX"),
    "crypto": ("BTC-USD", "ETH-USD", "SOL-USD"),
    "fx": ("EURUSD=X", "GBPUSD=X", "JPY=X"),
    "etfs": ("SPY", "QQQ", "GLD"),
}


async def market_snapshot() -> dict[str, Any]:
    """Quotes for the major indices, crypto pairs, FX pairs and ETFs.

    Sequential rather than concurrent: the Yahoo limiter allows one request in
    flight, so a gather would only queue behind the same semaphore while making
    the failure attribution harder to read.
    """
    result: dict[str, list[dict[str, Any]]] = {}
    for group, symbols in _SNAPSHOT_GROUPS.items():
        rows: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                data = await quote(symbol)
            except (ProviderError, NoDataError):
                continue
            rows.append(
                {
                    # Key on the ticker we asked for, not on ``meta.symbol``:
                    # Yahoo reports ``JPY=X`` and ``USDJPY=X`` interchangeably
                    # in the metadata, which split one instrument into two
                    # snapshot rows (one per provider) instead of joining them.
                    "symbol": symbol,
                    "requested_symbol": symbol,
                    "yahoo_symbol": data.get("symbol"),
                    "price": data["price"],
                    "change_pct": data["change_pct"],
                    "currency": data["currency"],
                    "market_time": data.get("market_time"),
                }
            )
        result[group] = rows
    if not any(result.values()):
        raise NoDataError(PROVIDER, "Yahoo returned no snapshot rows")
    return result


#: The index symbols the ``market_indices`` tool compares, keyed to the
#: canonical short name the other two providers use.
#: Canonical index name -> the Yahoo chart-API symbol that carries it.
#: Derived from the instrument registry, restricted to the documented snapshot
#: list, so the Yahoo spellings of the indices live in one place only
#: (:data:`tapebasis.symbols.INSTRUMENTS`) and a broader registry row (NDX,
#: addressable through single-instrument quotes) cannot silently join the
#: snapshot loop.
INDEX_SYMBOLS: dict[str, str] = {
    canonical: str(row["yahoo"])
    for canonical, row in INSTRUMENTS.items()
    if canonical in INDEX_SNAPSHOT and row["asset_class"] == "index"
}


async def index_snapshot() -> dict[str, Any]:
    """Level and day change for the major US indices, from Yahoo's chart API.

    The six quotes are asked concurrently: they share one limiter, so the pacing
    that protects Yahoo still applies, but the per-request handshake and latency
    no longer add up. Measured sequentially this loop was 11.3 s and was the
    whole cost of ``market_indices``.

    A multi-symbol endpoint was evaluated instead and rejected: Yahoo's
    ``/v7/finance/quote`` reports ``regularMarketPreviousClose`` equal to the
    current price for ``^VIX`` (a 0.0 % day change where the chart path reports
    -2.31 %), and ``/v8/finance/spark`` reported 281.88 for ``IWM`` where the
    chart path reports 280.58. One request is not worth a wrong day change.

    Returns:
        ``{"indices": [...]}`` in the registry's snapshot order, one row per
        index that answered.
    """

    async def _one(canonical: str, symbol: str) -> dict[str, Any] | None:
        try:
            data = await quote(symbol)
        except (ProviderError, NoDataError):
            return None
        return {
            "symbol": symbol,
            "canonical": canonical,
            "name": canonical,
            "price": data.get("price"),
            "change_pct": data.get("change_pct"),
            "currency": data.get("currency"),
            "price_timestamp": data.get("market_time"),
        }

    rows = await asyncio.gather(
        *(_one(canonical, symbol) for canonical, symbol in INDEX_SYMBOLS.items())
    )
    indices = [row for row in rows if row is not None]
    if not indices:
        raise NoDataError(PROVIDER, "Yahoo returned no index rows")
    return {"indices": indices}


async def extended_hours(symbol: str) -> dict[str, Any]:
    """Pre-market / regular / post-market prices from Yahoo's 1-minute candles.

    The response shaper is Yahoo's own session-window logic (the boundaries come
    from the upstream payload), so this is genuinely Yahoo data, labelled as
    such, not a hidden leg of another provider.
    """
    from .providers.tradingview.core.services.extended_hours_service import (
        _shape_extended_hours,
    )

    async def _once() -> dict[str, Any]:
        # ``call`` did the pacing; see ``_get`` for why not to wait twice.
        client = shared_client(_POOL)
        response = await client.get(
            f"{_CHART}/{symbol}",
            params={"interval": "1m", "range": "2d", "includePrePost": "true"},
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=20.0,
        )
        if response.status_code == 429:
            raise RateLimited(PROVIDER, "extended-hours HTTP 429")
        response.raise_for_status()
        return response.json()

    try:
        payload = await call(PROVIDER, _once)
    except RateLimited as exc:
        raise ProviderError(
            PROVIDER,
            "Yahoo Finance is rate limiting this server; retry later",
            code="UPSTREAM_RATE_LIMIT",
        ) from exc
    shaped = _shape_extended_hours(symbol, payload)
    if shaped.get("error"):
        raise NoDataError(PROVIDER, str(shaped["error"]))
    return shaped


_OVERNIGHT_QUOTE_FIELDS = (
    "symbol",
    "regularMarketPrice",
    "overnightMarketPrice",
    "overnightMarketChange",
    "overnightMarketChangePercent",
    "overnightMarketTime",
)


def _quote_number(value: Any) -> float | None:
    """Return a finite Yahoo numeric field, accepting its ``raw`` object form."""
    if isinstance(value, dict):
        value = value.get("raw")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _shape_overnight(symbol: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Map Yahoo's quote-header Blue Ocean fields to one overnight observation.

    The printed change refers to the last regular close, not the previous
    regular session's own previous close and not the separate fullday value.
    No reference is inferred when ``regularMarketPrice`` is absent. A missing
    price or print time returns ``None`` rather than substituting the
    20:00 after-hours print for an overnight observation.
    """
    response = payload.get("quoteResponse") or {}
    if response.get("error"):
        raise ProviderError(PROVIDER, f"Yahoo quote error: {response['error']}")
    rows = response.get("result") or []
    if not rows or not isinstance(rows[0], dict):
        raise NoDataError(PROVIDER, f"Yahoo has no quote-header row for {symbol}")
    row = rows[0]
    price = _quote_number(row.get("overnightMarketPrice"))
    stamp = _quote_number(row.get("overnightMarketTime"))
    if price is None or stamp is None:
        return None
    change = _quote_number(row.get("overnightMarketChange"))
    reference = _quote_number(row.get("regularMarketPrice"))
    return {
        "session": "overnight",
        "price": price,
        "change": change,
        "change_percent": _quote_number(row.get("overnightMarketChangePercent")),
        "reference_close": reference,
        "print_time": stamp,
        "volume": None,
        "exchange": "Blue Ocean ATS",
        "feed_mode": "Yahoo overnight quote header",
        "source": "Yahoo Finance quote header, Blue Ocean ATS",
    }


async def overnight(symbol: str) -> dict[str, Any] | None:
    """Return Yahoo's latest Blue Ocean ATS print, or ``None`` when unpublished.

    This reads ``/v7/finance/quote`` with ``overnightPrice=true``. Its
    ``overnightMarket*`` fields are a separate feed, never inferred from Yahoo's
    1-minute chart, which covers only pre-market, regular and post-market bars.

    Returns:
        A normalised overnight block with its own price, change and print time.
        ``None`` means the symbol resolved but Yahoo published no overnight
        observation; transport and authentication failures remain exceptions.

    Raises:
        ProviderError: The request, crumb session or upstream contract failed.
        NoDataError: Yahoo returned no symbol row at all.
    """
    def _request(opener: Any, params: dict[str, Any]) -> dict[str, Any]:
        params.update(symbols=symbol, fields=",".join(_OVERNIGHT_QUOTE_FIELDS))
        return _quote_page(opener, params)

    payload = await _yahoo_quote_request(_request)
    return _shape_overnight(symbol, payload)


async def options(symbol: str, expiry: str | None = None) -> dict[str, Any]:
    """Options chain for one expiry, from Yahoo's options endpoint.

    Yahoo gates ``/v7/finance/options`` behind a crumb+cookie handshake, so the
    provider service is reused for the session dance, but the request is still
    serialised through this provider's limiter, and the payload is labelled
    YAHOO because that is whose feed it is.
    """
    from .providers.tradingview.core.services.options_service import get_options_chain

    async def _once() -> dict[str, Any]:
        # ``call`` did the pacing; the handshake is inside the thread, not here.
        return await blocking_pool.run(get_options_chain, symbol, expiry)

    data = await call(PROVIDER, _once)
    if not isinstance(data, dict):
        raise ProviderError(PROVIDER, "options endpoint returned a non-dict payload")
    if data.get("error"):
        raise NoDataError(PROVIDER, str(data["error"]))
    return data


async def news(symbol: str, limit: int = 20) -> dict[str, Any]:
    """Yahoo's own headline feed for one symbol (``/v1/finance/search``)."""
    url = "https://query1.finance.yahoo.com/v1/finance/search"

    async def _once() -> dict[str, Any]:
        # ``call`` did the pacing; see ``_get`` for why not to wait twice.
        client = shared_client(_POOL)
        response = await client.get(
            url,
            params={
                "q": symbol,
                "quotesCount": 0,
                "newsCount": max(1, min(int(limit), 50)),
            },
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=15.0,
        )
        if response.status_code == 429:
            raise RateLimited(PROVIDER, "news search HTTP 429")
        response.raise_for_status()
        return response.json()

    try:
        payload = await call(PROVIDER, _once)
    except RateLimited as exc:
        raise ProviderError(
            PROVIDER,
            "Yahoo Finance is rate limiting this server; retry later",
            code="UPSTREAM_RATE_LIMIT",
        ) from exc

    items = []
    for entry in payload.get("news") or []:
        title = entry.get("title")
        if not title:
            continue
        items.append(
            {
                "title": title,
                "source": entry.get("publisher"),
                "published": entry.get("providerPublishTime"),
                "url": entry.get("link"),
                "summary": entry.get("summary"),
                "tickers": entry.get("relatedTickers") or [],
            }
        )
    if not items:
        raise NoDataError(PROVIDER, f"Yahoo returned no headlines for {symbol}")
    return {"symbol": symbol, "items": items, "count": len(items)}


async def history_candles(
    symbol: str,
    *,
    period: str = "1y",
    interval: str = "1d",
) -> dict[str, Any]:
    """Yahoo history shaped as the backtest engine's candle list."""
    from datetime import datetime, timezone

    payload = await history(symbol, period=period, interval=interval)
    date_format = "%Y-%m-%d %H:%M" if interval.endswith("h") or interval.endswith("m") else "%Y-%m-%d"
    candles = [
        {
            "date": datetime.fromtimestamp(bar["timestamp"], tz=timezone.utc).strftime(date_format),
            "open": bar.get("open"),
            "high": bar.get("high"),
            "low": bar.get("low"),
            "close": bar.get("close"),
            "volume": bar.get("volume") or 0,
        }
        for bar in payload.get("bars") or []
        if bar.get("close") is not None
    ]
    if not candles:
        raise NoDataError(PROVIDER, f"Yahoo returned no usable bars for {symbol}")
    return {"candles": candles, "symbol": payload.get("symbol"), "source": "yahoo"}


def limiter_state() -> dict[str, Any]:
    return limiter(PROVIDER).snapshot()
