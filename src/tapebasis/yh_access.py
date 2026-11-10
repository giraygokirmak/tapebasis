"""Thin, typed access to the Yahoo Finance chart API.

Yahoo is a first-class provider here, not a fallback hidden inside another one.
It is the only provider here that will quote a spot gold pair with a single
unambiguous ticker (``XAUUSD=X``), and its history endpoint is stable and
documented by a decade of use.

Everything goes through :mod:`tapebasis.ratelimit`: Yahoo starts answering
``429`` after a short burst and then stays angry, so the limiter enforces one
request at a time with a shared cooldown, and a short TTL cache absorbs the
duplicate asks an agent naturally makes.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .providers_state import NoDataError, ProviderError
from .ratelimit import RateLimited, call, limiter
from .symbols import INSTRUMENTS

PROVIDER = "YAHOO"
_CHART = "https://query1.finance.yahoo.com/v8/finance/chart"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)

#: 5 days (not 2): when the newest session has no trades yet its close is None,
#: and a 2-day window then leaves only ONE usable close, too few to derive a
#: previous close, which used to fall back to the same bar and report a 0% move.
_QUOTE_RANGE = "5d"

#: How far ``meta.regularMarketTime`` may lag the newest candle before the whole
#: quote block is treated as stale. One day covers normal intraday lag.
_STALE_QUOTE_SECONDS = 86_400


class _YahooError(ProviderError):
    pass


async def _get(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    paced = limiter(PROVIDER)

    async def _once() -> dict[str, Any]:
        await paced.wait_turn()
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0), follow_redirects=True
        ) as client:
            response = await client.get(
                url, params=params, headers={"User-Agent": _UA, "Accept": "application/json"}
            )
        if response.status_code == 429:
            raise RateLimited(PROVIDER, "chart HTTP 429")
        if response.status_code == 404:
            raise NoDataError(PROVIDER, f"Yahoo has no chart for {url.rsplit('/', 1)[-1]}")
        response.raise_for_status()
        return response.json()

    try:
        return await call(PROVIDER, _once)
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
        "quote_stale": _quote_is_stale(result),
        "source": "Yahoo Finance chart API",
    }


async def quote(symbol: str) -> dict[str, Any]:
    """Latest quote for one Yahoo symbol (``AAPL``, ``XAUUSD=X``, ``^GSPC``)."""
    payload = await _get(
        f"{_CHART}/{symbol}", params={"interval": "1d", "range": _QUOTE_RANGE}
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
#: Derived from the instrument registry, so the Yahoo spellings of the indices
#: live in one place only: :data:`tapebasis.symbols.INSTRUMENTS`.
INDEX_SYMBOLS: dict[str, str] = {
    canonical: str(row["yahoo"])
    for canonical, row in INSTRUMENTS.items()
    if row["asset_class"] == "index"
}


async def index_snapshot() -> dict[str, Any]:
    """Level and day change for the major US indices, from Yahoo's chart API."""
    indices: list[dict[str, Any]] = []
    for canonical, symbol in INDEX_SYMBOLS.items():
        try:
            data = await quote(symbol)
        except (ProviderError, NoDataError):
            continue
        indices.append(
            {
                "symbol": symbol,
                "canonical": canonical,
                "name": canonical,
                "price": data.get("price"),
                "change_pct": data.get("change_pct"),
                "currency": data.get("currency"),
                "price_timestamp": data.get("market_time"),
            }
        )
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

    paced = limiter(PROVIDER)

    async def _once() -> dict[str, Any]:
        await paced.wait_turn()
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0), follow_redirects=True
        ) as client:
            response = await client.get(
                f"{_CHART}/{symbol}",
                params={"interval": "1m", "range": "1d", "includePrePost": "true"},
                headers={"User-Agent": _UA, "Accept": "application/json"},
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


async def options(symbol: str, expiry: str | None = None) -> dict[str, Any]:
    """Options chain for one expiry, from Yahoo's options endpoint.

    Yahoo gates ``/v7/finance/options`` behind a crumb+cookie handshake, so the
    provider service is reused for the session dance, but the request is still
    serialised through this provider's limiter, and the payload is labelled
    YAHOO because that is whose feed it is.
    """
    from .providers.tradingview.core.services.options_service import get_options_chain

    paced = limiter(PROVIDER)

    async def _once() -> dict[str, Any]:
        await paced.wait_turn()
        return await asyncio.to_thread(get_options_chain, symbol, expiry)

    data = await call(PROVIDER, _once)
    if not isinstance(data, dict):
        raise ProviderError(PROVIDER, "options endpoint returned a non-dict payload")
    if data.get("error"):
        raise NoDataError(PROVIDER, str(data["error"]))
    return data


async def news(symbol: str, limit: int = 20) -> dict[str, Any]:
    """Yahoo's own headline feed for one symbol (``/v1/finance/search``)."""
    url = "https://query1.finance.yahoo.com/v1/finance/search"
    paced = limiter(PROVIDER)

    async def _once() -> dict[str, Any]:
        await paced.wait_turn()
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0), follow_redirects=True
        ) as client:
            response = await client.get(
                url,
                params={
                    "q": symbol,
                    "quotesCount": 0,
                    "newsCount": max(1, min(int(limit), 50)),
                },
                headers={"User-Agent": _UA, "Accept": "application/json"},
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
