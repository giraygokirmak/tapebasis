"""TradingView's own data, scanner and chart websocket.

Two upstreams, both TradingView's, both native:

``scanner.tradingview.com``
    One POST returns a row per symbol with ``close``, ``open``, ``high``,
    ``low``, ``volume``, ``update_time`` and fundamentals for every asset class
    (equities, indices, FX, crypto, commodities). This is TradingView's own
    quote feed and the source of truth for spot prices.

``data.tradingview.com`` (chart websocket)
    The same feed the TradingView charts themselves use. It is the only way to
    get *history*, ``create_series`` returns OHLCV bars for any resolution
    (``1``, ``5``, ``60``, ``1D``, ``1W``, ``1M``) over any range.

Why a websocket and not HTTP: TradingView has no public history endpoint. The
HTTP ``/history`` route is gone; the chart protocol is what remains.

Rate limits are real and IP-scoped: opening many sockets in quick succession
gets the *symbol* rejected as ``invalid symbol`` even though it exists, and the
connection dropped. Every call therefore goes through :mod:`tapebasis.ratelimit`,
one socket at a time, with a shared cooldown. Nothing here retries in a tight
loop, a deeper hole is the failure mode.
"""
from __future__ import annotations

import asyncio
import json
import random
import string
from typing import Any

import httpx

from ...ratelimit import RateLimited, call, limiter
from ...symbols import INSTRUMENTS

PROVIDER = "TRADINGVIEW"

SCANNER_URL = "https://scanner.tradingview.com/{market}/scan"
WS_URL = "wss://data.tradingview.com/socket.io/websocket?from=chart%2F&type=chart"
_UA = "tapebasis/1.0"

#: Scanner columns that map onto our normalised field names.
QUOTE_COLUMNS: tuple[str, ...] = (
    "name",
    "description",
    "close",
    "change",
    "open",
    "high",
    "low",
    "volume",
    "update_time",
    "update_mode",
    "currency",
    "exchange",
    "type",
    "subtype",
    "market_cap_basic",
    "price_earnings_ttm",
    "earnings_per_share_basic_ttm",
    "dividends_yield_current",
    "sector",
    "industry",
    "price_52_week_high",
    "price_52_week_low",
    "beta_1_year",
    "relative_volume_10d_calc",
    "RSI",
    "ATR",
    "earnings_release_next_date",
    "earnings_release_date",
    "premarket_close",
    "premarket_change",
    "premarket_volume",
    "postmarket_close",
    "postmarket_change",
    "postmarket_volume",
)

#: TradingView resolution codes by the interval names our tools accept.
RESOLUTIONS: dict[str, str] = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "45m": "45", "1h": "60", "2h": "120", "4h": "240",
    "1d": "1D", "1w": "1W", "1M": "1M",
}

#: How many bars to request for a period, so "1y daily" means ~252 bars.
_PERIOD_BARS: dict[str, int] = {
    "1d": 2, "5d": 6, "1mo": 24, "3mo": 66, "6mo": 130,
    "1y": 260, "2y": 520, "5y": 1300, "10y": 2600, "max": 5000,
}


class SymbolNotFound(Exception):
    """The scanner or websocket says this symbol does not exist."""


# ── Scanner ──────────────────────────────────────────────────────────────────


def _scanner_market(ticker: str) -> str:
    """Which scanner market a ``EXCHANGE:SYMBOL`` belongs to."""
    exchange = ticker.split(":", 1)[0].upper()
    if exchange in {"NYSE", "NASDAQ", "AMEX", "OTC", "ARCA", "BATS"}:
        return "america"
    return "global"


async def _scan_market(
    market: str,
    tickers: list[str],
    columns: tuple[str, ...],
    paced,
) -> list[dict[str, Any]]:
    """One scanner POST against one market."""
    body = {
        "symbols": {"tickers": tickers, "query": {"types": []}},
        "columns": list(columns),
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(25.0)) as client:
        response = await client.post(
            SCANNER_URL.format(market=market),
            json=body,
            headers={"User-Agent": _UA, "Content-Type": "application/json"},
        )
    if response.status_code == 429:
        raise RateLimited(PROVIDER, "scanner HTTP 429")
    response.raise_for_status()
    payload = response.json()
    rows: list[dict[str, Any]] = []
    for entry in payload.get("data") or []:
        values = entry.get("d") or []
        row = {"ticker": entry.get("s")}
        row.update(dict(zip(columns, values)))
        rows.append(row)
    return rows


async def scan(
    tickers: list[str],
    columns: tuple[str, ...] = QUOTE_COLUMNS,
    *,
    market: str | None = None,
) -> list[dict[str, Any]]:
    """Scanner rows for a list of ``EXCHANGE:SYMBOL`` tickers.

    The market is chosen per ticker, not once per batch. A single POST only
    resolves tickers that belong to that one market: sending
    ``NASDAQ:AAPL`` alongside ``OANDA:XAUUSD`` to ``/america/scan`` silently
    drops the gold row (verified against the live endpoint), which would turn a
    real TradingView quote into "no data". Batches are therefore partitioned by
    market and the results merged.

    A ticker the chosen market does not resolve is retried once in ``global``,
    because that is the superset market; anything still missing is genuinely
    absent from the scanner and simply does not appear in the result.
    """
    if not tickers:
        return []
    tickers = [t.strip().upper() for t in tickers if t and t.strip()]
    if not tickers:
        return []

    paced = limiter(PROVIDER)
    key = (
        "scan|" + str(market or "auto") + "|"
        + ",".join(sorted(tickers)) + "|" + ",".join(columns)
    )
    cached = paced.cache_get(key, ttl=15.0)
    if cached is not None:
        return cached

    async def _once() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        if market is not None:
            # An explicit market is honoured as given: the caller (index
            # snapshot, screener) knows where its tickers live.
            await paced.wait_turn()
            rows = await _scan_market(market, list(tickers), columns, paced)
        else:
            groups: dict[str, list[str]] = {}
            for ticker in tickers:
                groups.setdefault(_scanner_market(ticker), []).append(ticker)
            for group_market, group in groups.items():
                await paced.wait_turn()
                rows.extend(await _scan_market(group_market, group, columns, paced))

            # Whatever the ticker's own market could not resolve gets one more
            # attempt in ``global``, the superset market. Anything still missing
            # is genuinely absent from the scanner, not a market mismatch.
            resolved = {str(r.get("ticker") or "").upper() for r in rows}
            missing = [t for t in tickers if t not in resolved]
            already_global = {t for t in missing if _scanner_market(t) == "global"}
            retry = [t for t in missing if t not in already_global]
            if retry:
                await paced.wait_turn()
                try:
                    got = await _scan_market("global", retry, columns, paced)
                except httpx.HTTPStatusError:
                    got = []
                known = {str(r.get("ticker") or "").upper() for r in rows}
                rows.extend(
                    r for r in got
                    if str(r.get("ticker") or "").upper() not in known
                )

        paced.cache_set(key, rows)
        return rows

    return await call(PROVIDER, _once)


async def quote(ticker: str) -> dict[str, Any]:
    """Scanner quote for one ``EXCHANGE:SYMBOL``."""
    rows = await scan([ticker])
    if not rows:
        raise SymbolNotFound(f"scanner has no row for {ticker}")
    return rows[0]


#: Canonical index name -> the TradingView ticker that carries it. Derived
#: from the instrument registry, so the TradingView spellings of the indices
#: live in one place only: :data:`tapebasis.symbols.INSTRUMENTS`.
INDEX_TICKERS: dict[str, str] = {
    canonical: str(row["tradingview"])
    for canonical, row in INSTRUMENTS.items()
    if row["asset_class"] == "index"
}

_INDEX_COLUMNS = (
    "name", "description", "close", "change", "update_time", "currency", "exchange",
)


async def index_snapshot() -> dict[str, Any]:
    """Level and day change for the major US indices, from the scanner.

    Returns the same ``{"indices": [{"symbol", "price", "change_pct", ...}]}``
    shape the other provider shapers read, so the reconciler can compare index
    levels across providers without a special case.
    """
    rows = await scan(list(INDEX_TICKERS.values()), columns=_INDEX_COLUMNS, market="global")
    by_ticker = {str(row.get("ticker") or "").upper(): row for row in rows}
    indices = []
    for canonical, ticker in INDEX_TICKERS.items():
        row = by_ticker.get(ticker.upper())
        if not row or row.get("close") is None:
            continue
        indices.append(
            {
                "symbol": ticker,
                "canonical": canonical,
                "name": row.get("description") or canonical,
                "price": row.get("close"),
                "change_pct": row.get("change"),
                "currency": row.get("currency"),
                "price_timestamp": row.get("update_time"),
            }
        )
    if not indices:
        raise SymbolNotFound("scanner returned no index rows")
    return {"indices": indices}


#: The broad snapshot's groups, in TradingView's own tickers. Yahoo's groups use
#: its tickers; the shaper below maps both onto the same ``symbol`` keys.
_SNAPSHOT_TICKERS: dict[str, tuple[str, ...]] = {
    "indices": ("SP:SPX", "DJ:DJI", "NASDAQ:IXIC", "TVC:VIX"),
    "crypto": ("BITSTAMP:BTCUSD", "BITSTAMP:ETHUSD", "COINBASE:SOLUSD"),
    "fx": ("FX:EURUSD", "FX:GBPUSD", "FX:USDJPY"),
    "etfs": ("AMEX:SPY", "NASDAQ:QQQ", "AMEX:GLD"),
}

_SNAPSHOT_COLUMNS = ("name", "close", "change", "currency", "update_time")

#: TradingView ticker -> the Yahoo ticker for the same instrument, so the two
#: legs' rows can be matched. Only used for matching, never for pricing.
SNAPSHOT_YAHOO_EQUIVALENT: dict[str, str] = {
    "SP:SPX": "^GSPC",
    "DJ:DJI": "^DJI",
    "NASDAQ:IXIC": "^IXIC",
    "TVC:VIX": "^VIX",
    "BITSTAMP:BTCUSD": "BTC-USD",
    "BITSTAMP:ETHUSD": "ETH-USD",
    "COINBASE:SOLUSD": "SOL-USD",
    "FX:EURUSD": "EURUSD=X",
    "FX:GBPUSD": "GBPUSD=X",
    # Yahoo quotes USD/JPY as ``JPY=X``: the pair is named after the base
    # currency's *counterpart* (a yen-per-dollar quote). Mapping this wrong
    # made the snapshot report ``JPY=X`` and ``USDJPY=X`` as two separate rows
    # for one instrument, one labelled TradingView and one Yahoo.
    "FX:USDJPY": "JPY=X",
    "AMEX:SPY": "SPY",
    "NASDAQ:QQQ": "QQQ",
    "AMEX:GLD": "GLD",
}


async def market_snapshot() -> dict[str, Any]:
    """Quotes for the major indices, crypto pairs, FX pairs and ETFs.

    One scanner POST covers all four groups; rows come back in the same
    ``{"symbol", "price", "change_pct"}`` shape the Yahoo leg uses, so the two
    can be matched row by row.
    """
    tickers = [ticker for group in _SNAPSHOT_TICKERS.values() for ticker in group]
    rows = await scan(tickers, columns=_SNAPSHOT_COLUMNS, market="global")
    by_ticker = {str(row.get("ticker") or "").upper(): row for row in rows}

    result: dict[str, list[dict[str, Any]]] = {}
    for group, group_tickers in _SNAPSHOT_TICKERS.items():
        group_rows = []
        for ticker in group_tickers:
            row = by_ticker.get(ticker.upper())
            if not row or row.get("close") is None:
                continue
            group_rows.append(
                {
                    "symbol": SNAPSHOT_YAHOO_EQUIVALENT.get(ticker, ticker),
                    "tradingview_symbol": ticker,
                    "name": row.get("name"),
                    "price": row.get("close"),
                    "change_pct": row.get("change"),
                    "currency": row.get("currency"),
                    "price_timestamp": row.get("update_time"),
                }
            )
        result[group] = group_rows
    if not any(result.values()):
        raise SymbolNotFound("scanner returned no snapshot rows")
    return {"groups": result}


# ── Chart websocket (history) ────────────────────────────────────────────────


def _token(prefix: str = "cs") -> str:
    return prefix + "_" + "".join(random.choice(string.ascii_uppercase) for _ in range(12))


def _frame(method: str, params: list[Any]) -> str:
    payload = json.dumps({"m": method, "p": params}, separators=(",", ":"))
    return f"~m~{len(payload)}~m~{payload}"


def _bars_for_period(period: str, interval: str) -> int:
    width = _PERIOD_BARS.get(period.lower(), 260)
    minutes = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "45m": 45,
               "1h": 60, "2h": 120, "4h": 240}
    if interval in minutes:
        # Six and a half trading hours per session, plus slack.
        per_day = max(1, 390 // minutes[interval])
        return min(5000, per_day * max(1, width // 260 * 260 if width >= 260 else width))
    if interval == "1w":
        return max(2, width // 5)
    if interval in {"1M"}:
        return max(2, width // 21)
    return max(2, min(5000, width))


async def _history_blocking(
    ticker: str,
    interval: str,
    bars: int,
    timeout: float,
) -> list[dict[str, Any]]:
    """Open one chart socket, ask for *bars* candles, close. Blocking."""
    import websocket  # local import: optional dependency, only needed for history

    resolution = RESOLUTIONS.get(interval.lower(), "1D")
    session, symbol_id, series_id = _token(), _token("sds_sym"), _token("sds")
    connection = websocket.create_connection(
        WS_URL,
        timeout=timeout,
        header=[
            "Origin: https://www.tradingview.com",
            f"User-Agent: {_UA}",
        ],
    )
    try:
        for method, params in (
            ("set_auth_token", ["unauthorized_user_token"]),
            ("chart_create_session", [session, ""]),
            (
                "resolve_symbol",
                [session, symbol_id, json.dumps({"adjustment": "splits", "symbol": ticker})],
            ),
            ("create_series", [session, series_id, "s1", symbol_id, resolution, bars, ""]),
        ):
            connection.send(_frame(method, params))

        collected: list[dict[str, Any]] = []
        while True:
            raw = connection.recv()
            if not raw:
                raise ConnectionError("chart socket closed before series_completed")
            if raw.startswith("~h~"):  # heartbeat
                connection.send(raw)
                continue
            for chunk in raw.split("~m~"):
                if not chunk or chunk.isdigit():
                    continue
                try:
                    message = json.loads(chunk)
                except ValueError:
                    continue
                method = message.get("m")
                if method == "timescale_update":
                    payload = message["p"][1].get(series_id)
                    if payload:
                        collected = [
                            {
                                "timestamp": bar["v"][0],
                                "open": bar["v"][1],
                                "high": bar["v"][2],
                                "low": bar["v"][3],
                                "close": bar["v"][4],
                                "volume": bar["v"][5],
                            }
                            for bar in payload.get("s") or []
                        ]
                elif method == "series_completed":
                    return collected
                elif method in {"symbol_error", "series_error", "critical_error"}:
                    detail = str(message.get("p"))[:200]
                    if "invalid symbol" in detail.lower() or "resolve error" in detail.lower():
                        raise SymbolNotFound(f"{ticker}: {detail}")
                    raise ConnectionError(f"TradingView chart error: {detail}")
    finally:
        try:
            connection.close()
        except Exception:  # noqa: BLE001
            pass


async def history(
    ticker: str,
    *,
    period: str = "1y",
    interval: str = "1d",
    timeout: float = 25.0,
) -> dict[str, Any]:
    """OHLCV history for one symbol, straight from TradingView's chart feed.

    Raises :class:`SymbolNotFound` when TradingView does not know the ticker and
    :class:`tapebasis.ratelimit.RateLimited` when the IP is being throttled.
    """
    bars = _bars_for_period(period, interval)
    paced = limiter(PROVIDER)
    key = f"hist|{ticker}|{interval}|{period}"
    cached = paced.cache_get(key, ttl=120.0)
    if cached is not None:
        return cached

    async def _once() -> dict[str, Any]:
        await paced.wait_turn()
        try:
            rows = await asyncio.to_thread(
                _history_blocking, ticker, interval, bars, timeout
            )
        except SymbolNotFound:
            raise
        except Exception as exc:  # noqa: BLE001
            text = str(exc).lower()
            if "invalid symbol" in text or "resolve error" in text:
                # The socket reports the same line for both "no such ticker" and
                # "this IP is throttled". The deeper cooldown is the safe read.
                raise RateLimited(PROVIDER, "chart socket refused the symbol") from exc
            raise
        payload = {
            "symbol": ticker,
            "interval": interval,
            "period": period,
            "bars": rows,
            "source": "tradingview",
            "price_timestamp": rows[-1]["timestamp"] if rows else None,
        }
        paced.cache_set(key, payload)
        return payload

    return await call(PROVIDER, _once)


def limiter_state() -> dict[str, Any]:
    return limiter(PROVIDER).snapshot()
