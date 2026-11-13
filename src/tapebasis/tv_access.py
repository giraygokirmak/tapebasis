"""Thin, typed access to TradingView's own data.

Every function here goes to TradingView. Nothing in this module delegates to
Yahoo Finance or Finviz: the point of a separate provider is that each leg is
genuinely independent, and a leg that quietly proxies another one is worth
nothing as a cross-check.

Two upstreams are used:

* ``scanner.tradingview.com`` for spot quotes, fundamentals and whole-market
  screens (any asset class, one POST).
* ``data.tradingview.com`` (chart websocket) for OHLCV history, which the
  scanner does not expose.
"""
from __future__ import annotations

from typing import Any

from . import blocking_pool
from .providers.tradingview import native
from .providers.tradingview.core.services import screener_service, stock_screener_service
from .providers_state import NoDataError, ProviderError
from .ratelimit import RateLimited, RateLimitError

PROVIDER = "TRADINGVIEW"

#: Scanner columns the quote compares on.
_QUOTE_COLUMNS = native.QUOTE_COLUMNS

#: Narrower column set for bulk price lookups.
_PRICE_COLUMNS = (
    "name",
    "description",
    "close",
    "change",
    "volume",
    "currency",
    "update_time",
    "market_cap_basic",
    # The session the row is in, and that session's own print. Without these a
    # bulk lookup served ``close``, which stops moving the moment the regular
    # feed's last trade is behind the market, and called it the price.
    "current_session",
    "premarket_close",
    "premarket_change",
    "postmarket_close",
    "postmarket_change",
)


def _raise_provider_error(exc: BaseException, context: str) -> None:
    if isinstance(exc, native.SymbolNotFound):
        raise NoDataError(PROVIDER, str(exc)) from exc
    if isinstance(exc, (RateLimited, RateLimitError)):
        raise ProviderError(
            PROVIDER,
            f"{context}: TradingView is rate limiting this server; retry later",
            code="UPSTREAM_RATE_LIMIT",
        ) from exc
    raise ProviderError(
        PROVIDER,
        f"{context}: {type(exc).__name__}: {exc}",
        code="PROVIDER_ERROR",
    ) from exc


async def quote(ticker: str) -> dict[str, Any]:
    """Scanner quote for one ``EXCHANGE:SYMBOL`` ticker.

    ``ticker`` must already be a TradingView pair, use
    :func:`tapebasis.symbols.resolve_tradingview` to get one.
    """
    try:
        return await native.quote(ticker)
    except (native.SymbolNotFound, NoDataError):
        raise
    except Exception as exc:  # noqa: BLE001
        _raise_provider_error(exc, "scanner quote")


async def quotes(tickers: list[str]) -> dict[str, dict[str, Any]]:
    """Scanner rows for several tickers, keyed by bare symbol."""
    try:
        rows = await native.scan(tickers, columns=_PRICE_COLUMNS)
    except Exception as exc:  # noqa: BLE001
        _raise_provider_error(exc, "scanner bulk quote")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("name") or "").upper()
        if name:
            out[name] = row
    return out


async def history(
    ticker: str,
    *,
    period: str = "1y",
    interval: str = "1d",
) -> dict[str, Any]:
    """OHLCV history straight from TradingView's chart feed."""
    try:
        return await native.history(ticker, period=period, interval=interval)
    except (native.SymbolNotFound, NoDataError):
        raise
    except Exception as exc:  # noqa: BLE001
        _raise_provider_error(exc, "chart history")


async def history_candles(
    ticker: str,
    *,
    period: str = "1y",
    interval: str = "1d",
) -> dict[str, Any]:
    """TradingView history shaped as the backtest engine's candle list.

    The engine compares strings for trade dates and expects ascending bars, so
    the epoch timestamps are rendered in the same format the engine's own
    fallback uses (``%Y-%m-%d`` daily, ``%Y-%m-%d %H:%M`` intraday).
    """
    from datetime import datetime, timezone

    payload = await history(ticker, period=period, interval=interval)
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
        raise NoDataError(PROVIDER, f"TradingView returned no usable bars for {ticker}")
    return {"candles": candles, "symbol": payload.get("symbol"), "source": "tradingview"}


async def stock_screen(
    *,
    country: str = "america",
    stock_type: str = "common",
    limit: int = 50,
    exclude_otc: bool = True,
    sort_by: str = "market_cap",
) -> dict[str, Any]:
    """Whole-market stock screen (TradingView scanner).

    ``screen_stocks`` is a blocking scraper (pandas + requests), so it runs in a
    worker thread. Awaiting it directly fails with ``object dict can't be used
    in 'await' expression`` and silently demotes the whole screener to
    Finviz-only, which is exactly what it did before this was fixed.
    """
    try:
        return await blocking_pool.run(
            stock_screener_service.screen_stocks,
            country=country,
            stock_type=stock_type,
            limit=limit,
            exclude_otc=exclude_otc,
            sort_by=sort_by,
        )
    except Exception as exc:  # noqa: BLE001
        _raise_provider_error(exc, "stock screen")


async def technical_analysis(
    symbol: str, exchange: str = "NASDAQ", timeframe: str = "1D"
) -> dict[str, Any]:
    """TradingView's technical-analysis engine for one symbol."""
    try:
        return await blocking_pool.run(
            screener_service.analyze_coin, symbol, exchange=exchange, timeframe=timeframe
        )
    except Exception as exc:  # noqa: BLE001
        _raise_provider_error(exc, "technical analysis")


async def news(symbol: str | None = None, *, limit: int = 20) -> dict[str, Any]:
    """Headlines from the provider's licensed news feed.

    Returns ``{"items": [...], "symbol": ...}``. Without
    ``MARKETAUX_API_TOKEN`` the feed has nothing, which is reported as
    ``NoDataError`` rather than as an empty success.
    """
    from .providers.tradingview.core.services.marketaux_service import (
        fetch_news_summary,
    )

    data = await blocking_pool.run(fetch_news_summary, symbol, limit=limit)
    if not isinstance(data, dict):
        raise ProviderError(PROVIDER, "news feed returned a non-dict payload")
    if data.get("error"):
        if "not configured" in str(data["error"]).lower():
            raise NoDataError(PROVIDER, str(data["error"]))
        raise ProviderError(PROVIDER, f"news failed: {data['error']}", code="UPSTREAM_ERROR")
    if not data.get("items"):
        raise NoDataError(PROVIDER, f"news feed has no headlines for {symbol}")
    return data


async def index_snapshot() -> dict[str, Any]:
    """Level and day change for the major US indices, from the scanner."""
    try:
        return await native.index_snapshot()
    except (native.SymbolNotFound, NoDataError):
        raise
    except Exception as exc:  # noqa: BLE001
        _raise_provider_error(exc, "index snapshot")


async def market_snapshot() -> dict[str, Any]:
    """Broad snapshot (indices, crypto, FX, ETFs) from TradingView's scanner.

    Exposed as its own access function because the composite tool calls it by
    name: the missing wrapper used to surface as an ``AttributeError`` swallowed
    by the reconciler, so ``market_snapshot`` reported Yahoo-only coverage with
    TradingView silently absent.
    """
    try:
        return await native.market_snapshot()
    except (native.SymbolNotFound, NoDataError):
        raise
    except Exception as exc:  # noqa: BLE001
        _raise_provider_error(exc, "market snapshot")


async def earnings(symbol: str) -> dict[str, Any]:
    """Next/last earnings timestamps from the scanner.

    ``symbol`` may be a bare ticker or an ``EXCHANGE:SYMBOL`` pair; a bare
    ticker is resolved through TradingView's own symbol search first so a
    non-US listing is not silently looked for on NASDAQ.
    """
    from .symbols import resolve_tradingview

    resolution = await resolve_tradingview(symbol, asset_class="stock")
    if not resolution.found:
        raise NoDataError(PROVIDER, resolution.note or f"no TradingView symbol for {symbol}")
    try:
        row = await native.quote(resolution.symbol)
    except (native.SymbolNotFound, NoDataError):
        raise
    except Exception as exc:  # noqa: BLE001
        _raise_provider_error(exc, "earnings calendar")
    if row.get("earnings_release_next_date") is None and row.get("earnings_release_date") is None:
        raise NoDataError(PROVIDER, f"scanner has no earnings dates for {resolution.symbol}")
    return row


def limiter_state() -> dict[str, Any]:
    return native.limiter_state()


async def live_session_quotes(
    tickers: list[str], *, timeout: float = 20.0
) -> dict[str, dict[str, Any]]:
    """Live prints from TradingView's quote socket, by symbol.

    This is the feed the public web chart streams from. Unlike the scanner it
    resolves the overnight venues (``BOATS:AAPL`` and peers), and it states the
    session each print belongs to, which the scanner only does per row and only
    for the session it happens to be in.

    Args:
        tickers: TradingView symbols. The scanner's spelling and the overnight
            venue's both resolve here.
        timeout: Overall socket timeout in seconds.

    Returns:
        Each resolved ticker mapped to its value dict. Symbols the upstream
        refused are absent rather than fabricated.

    Raises:
        NoDataError: When the socket resolved none of the tickers.
        ProviderError: On a transport failure or an IP-scoped throttle.
    """
    from .providers.tradingview import quote_socket

    try:
        rows = await quote_socket.quotes(tickers, timeout=timeout)
    except (RateLimited, RateLimitError) as exc:
        raise ProviderError(
            PROVIDER,
            "TradingView is rate limiting the quote socket; retry later",
            code="UPSTREAM_RATE_LIMIT",
        ) from exc
    except quote_socket.QuoteSocketError as exc:
        raise ProviderError(
            PROVIDER, f"quote socket: {exc}", code="PROVIDER_ERROR"
        ) from exc
    if not rows:
        raise NoDataError(PROVIDER, f"quote socket resolved none of {tickers}")
    return rows
