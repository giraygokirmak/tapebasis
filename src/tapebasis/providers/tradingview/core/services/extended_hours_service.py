"""
Extended-hours price service for US stocks.

Why this exists: a paying customer (US Army officer who trades on mobile)
asked "can you pull real-time after/extended hours?". He's tracking stocks
in the pre-market 4:00-9:30am ET and after-hours 4:00-8:00pm ET sessions
where earnings reactions and overnight news land.

Yahoo Finance's chart endpoint with `includePrePost=true` returns 1-minute
candles for the full extended trading day. We walk through the candles,
classify each by which session window it falls in (using the response's
`currentTradingPeriod` boundaries), and report the most recent valid close
for each session.

Behavior across the trading day:
- Pre-market session (4:00-9:30am ET): pre_market populated, post null
- Regular session (9:30am-4:00pm ET): pre + regular populated, post null
- Post-market session (4:00-8:00pm ET): all three populated
- Overnight / weekend: returns whatever's most recent in each window

Returns `null` for whichever session has no data, Claude can quote that
back to the user as "no after-hours print yet" rather than guessing.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
import urllib.request
import urllib.error
from typing import Optional

import httpx

_TIMEOUT = 12
_UA = "tapebasis/1.0"
_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"


def _quote_url(symbol: str) -> str:
    """The chart request for extended hours.

    ``range=1d`` used to return the day's 1-minute candles and no longer does:
    Yahoo answers with ``meta`` alone and no ``timestamp`` array, so there was
    nothing to walk and every call degraded to "unexpected response shape:
    'timestamp'". ``range=2d`` is the narrowest window that still carries
    candles, and it brings two session days with it, which is why the shaper
    classifies each candle against *its own* day's windows rather than against
    the single ``currentTradingPeriod`` block.
    """
    return f"{_BASE}/{symbol}?interval=1m&range=2d&includePrePost=true"


def _change_pct(price: Optional[float], reference: Optional[float]) -> Optional[float]:
    """Percentage change from reference to price; None if either is missing."""
    if price is None or reference is None or reference == 0:
        return None
    return round((price - reference) / reference * 100, 2)


def _fmt_time(ts: Optional[int]) -> Optional[str]:
    """Return a candle's own epoch as parseable, UTC-aware second-precision ISO."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _session_windows(meta: dict) -> list[tuple[str, dict[str, int]]]:
    """Every session window the response covers, as ``(label, window)``.

    ``meta.currentTradingPeriod`` describes one day, so walking a multi-day
    window against it quietly classifies yesterday's candles as today's
    pre-market. ``meta.tradingPeriods`` carries the windows for every day the
    response covers; older payloads only have the single block, which is still
    correct for a one-day window and is used as the fallback.

    Windows are kept flat rather than bucketed per day: a day missing one of its
    three windows would otherwise shift every later day's mapping. Each window
    carries its own ``start``/``end``, which is all the classifier needs.
    """
    periods = meta.get("tradingPeriods")
    if isinstance(periods, dict):
        windows: list[tuple[str, dict[str, int]]] = []
        for label in ("pre", "regular", "post"):
            for block in periods.get(label) or ():
                for window in block if isinstance(block, list) else [block]:
                    if isinstance(window, dict) and window.get("start") is not None:
                        windows.append((label, window))
        if windows:
            return windows
    current = meta.get("currentTradingPeriod")
    if isinstance(current, dict):
        return [
            (label, current[label])
            for label in ("pre", "regular", "post")
            if isinstance(current.get(label), dict)
        ]
    return []


def _window_for(ts: int, windows: list[tuple[str, dict[str, int]]]) -> str | None:
    """Which session a candle belongs to, using the windows that contain it.

    A regular window is fully bounded, so a timestamp inside one identifies the
    session unambiguously; regular windows are therefore tested first across
    every day. Pre and post windows can abut the regular one, and a post window
    ends after midnight UTC, so a candle at 00:30 belongs to the previous
    session's after-hours and must not be filed as the next day's pre-market.
    """
    for label, window in windows:
        if label != "regular":
            continue
        start, end = window.get("start"), window.get("end")
        if start is not None and end is not None and start <= ts <= end:
            return "regular"
    for label, window in windows:
        if label == "regular":
            continue
        start, end = window.get("start"), window.get("end")
        if start is not None and end is not None and start <= ts <= end:
            return label
    return None


def _shape_extended_hours(symbol: str, data: dict) -> dict:
    """Pure formatter for the Yahoo chart response. Shared sync + async.

    Returns:
        One block per session (``pre_market``, ``regular``, ``post_market``),
        each with the most recent print inside that session, or ``None`` for a
        session with no print yet. A payload with no candle array reports the
        reason in ``error`` rather than raising.
    """
    try:
        result = data["chart"]["result"][0]
        meta = result["meta"]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError) as e:
        return {"symbol": symbol.upper(), "error": f"unexpected response shape: {e}"}

    windows = _session_windows(meta)
    current = meta.get("currentTradingPeriod") or {}
    regular_start = (current.get("regular") or {}).get("start")

    pre_price, pre_time = None, None
    regular_price_intraday, regular_time = None, None
    post_price, post_time = None, None

    for ts, c in zip(timestamps, closes):
        if c is None:
            continue
        session = _window_for(ts, windows)
        if session == "pre":
            pre_price, pre_time = c, ts
        elif session == "regular":
            regular_price_intraday, regular_time = c, ts
        elif session == "post":
            post_price, post_time = c, ts

    # Prefer the meta `regularMarketPrice` (consolidated tape); fall back to
    # latest 1m candle if meta missing.
    regular_close = meta.get("regularMarketPrice") or regular_price_intraday

    previous_close = meta.get("previousClose") or meta.get("chartPreviousClose")

    # Before the open, Yahoo's `previousClose`/`chartPreviousClose` still refer to
    # the session before last while the pre-market bars already belong to the new
    # day, so the pre-market change is measured against the last regular close
    # (`regularMarketPrice`) instead. `previous_close` and the regular change keep
    # Yahoo's reference: before the open they describe the last session's own move.
    regular_market_time = meta.get("regularMarketTime")
    pre_open = (
        regular_market_time is not None
        and regular_start is not None
        and regular_market_time < regular_start
    )
    pre_reference = regular_close if pre_open and regular_close is not None else previous_close

    out = {
        "symbol": symbol.upper(),
        "currency": meta.get("currency", "USD"),
        "exchange": meta.get("exchangeName"),
        "market_state": meta.get("marketState"),
        "previous_close": previous_close,
        "pre_market": None,
        "regular": None,
        "post_market": None,
        "source": "Yahoo Finance",
    }

    if pre_price is not None:
        out["pre_market"] = {
            "price": pre_price,
            "as_of_utc": _fmt_time(pre_time),
            "change_vs_previous_close_pct": _change_pct(pre_price, pre_reference),
            "reference_close": pre_reference,
        }

    if regular_close is not None:
        out["regular"] = {
            "price": regular_close,
            "as_of_utc": _fmt_time(meta.get("regularMarketTime") or regular_time),
            "change_pct": _change_pct(regular_close, previous_close),
        }

    if post_price is not None:
        out["post_market"] = {
            "price": post_price,
            "as_of_utc": _fmt_time(post_time),
            "change_vs_regular_close_pct": _change_pct(post_price, regular_close),
        }

    return out


def get_extended_hours_price(symbol: str) -> dict:
    """Fetch latest pre-market, regular-session, and post-market prices (sync).

    Args:
        symbol: US stock symbol (e.g. AAPL, NVDA, SPY, ^GSPC).

    Returns:
        Dict with `pre_market`, `regular`, `post_market` blocks plus computed
        percentage changes. On upstream failure, returns `{symbol, error}`.
    """
    req = urllib.request.Request(
        _quote_url(symbol),
        headers={"User-Agent": _UA, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        return {"symbol": symbol.upper(), "error": f"{type(e).__name__}: {e}"}

    return _shape_extended_hours(symbol, data)


async def get_extended_hours_price_async(symbol: str) -> dict:
    """Async version of :func:`get_extended_hours_price` (uses httpx).

    Same return shape, including the error envelope on failure.
    """
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": _UA, "Accept": "application/json"},
        ) as client:
            resp = await client.get(_quote_url(symbol))
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"symbol": symbol.upper(), "error": f"{type(e).__name__}: {e}"}

    return _shape_extended_hours(symbol, data)
