"""Typed access to bloomberg.com's public quote pages.

Bloomberg is a reconciliation leg: ``stock_quote`` and ``stock_prices`` ask it
in parallel with every other provider, its readings appear in
``comparisons``, and it contributes to ``ALL``. Three properties of the feed are
handled here rather than hidden by a tolerance:

* its equity and index quotes are delayed (``exchangeDelay`` is
  ``15 Minutes``), so the print time is reported truthfully and the reconciler
  treats a pair that far apart as *not comparable* instead of as a disagreement,
* its static fields are penny-identical to Yahoo's, so agreement between those
  two is weak corroboration, not two independent witnesses; the docs say so,
* ``lastUpdate`` is a session sentinel (``...T01:00:00Z``), not a print time.
  Using it would make a stale page look newer than a live print.

Access is not cookie-based. The site gates plain HTTP clients on the TLS
fingerprint, so ``curl_cffi`` with a specific browser impersonation is required;
``httpx`` gets a 403 robot page no matter what headers it sends. That is also
why the health monitor cannot probe this provider over httpx: a probe that
cannot reach the page would report a false outage. The tool surfaces its own
failures instead.

Two paths exist and only one is used:

``/bazaar/api/quote/...``  burns after roughly ten rapid requests and then
                          answers 403 for many minutes, even while the HTML page
                          still answers 200 from the same session.
``/quote/<id>``           the HTML page, which is a strict superset: the whole
                          quote object is embedded in ``__NEXT_DATA__``.

So every request goes through the HTML page, paced slowly by
:mod:`tapebasis.ratelimit`, with a short TTL cache to absorb duplicate asks.

The ``curl_cffi`` session is pooled per event loop through
:mod:`tapebasis.http_pool`. Measured against the live page, a fresh session cost
325-725 ms per fetch against 176 ms on a reused one, and the reuse changes
nothing about the TLS fingerprint that gets past the wall.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import weakref
from typing import Any

from .providers_state import NoDataError, ProviderError
from .ratelimit import RateLimited, call, limiter

PROVIDER = "BLOOMBERG"
_POOL = "bloomberg"

_BASE = "https://www.bloomberg.com"
#: Recorded from live traffic: this version's fingerprint is accepted, while
#: the newest ``chrome`` alias is not. Overridable for a deployment that needs
#: to track a different accepted version.
_IMPERSONATE = os.environ.get("TAPEBASIS_BLOOMBERG_IMPERSONATE", "chrome124")
_TIMEOUT = float(os.environ.get("TAPEBASIS_BLOOMBERG_TIMEOUT", "30"))
#: The page is ~460 KB of HTML; 60 s absorbs an agent asking twice in one turn
#: without ever serving a materially stale price.
_CACHE_TTL = float(os.environ.get("TAPEBASIS_BLOOMBERG_CACHE_TTL", "60"))

_NEXT_DATA = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(?P<body>.*?)</script>',
    re.S,
)

#: Suffixes that mean "this already is a Bloomberg id", not "EXCHANGE:TICKER".
_SUFFIXES = {"US", "IND", "CUR", "COM", "GOV", "INDEX", "EQ"}

#: Extra spellings Bloomberg resolves mechanically but the instrument registry
#: has no row for (platinum, palladium, Nasdaq-100, foreign indices, bare
#: commodity roots). The registry rows themselves (indices, commodities, FX
#: pairs) are answered from :data:`tapebasis.symbols.INSTRUMENTS`, which is the
#: single home for every spelling; this table only holds what no registry row
#: covers.
_ALIASES: dict[str, str] = {
    # Foreign equity indices (no registry row: this server reports US majors)
    "DAX": "DAX:IND",
    "FTSE": "UKX:IND",
    "UKX": "UKX:IND",
    "NKY": "NKY:IND",
    "NIKKEI": "NKY:IND",
    "HSI": "HSI:IND",
    # Nasdaq-100 is a registry row; platinum/palladium spot pairs are not
    "XPTUSD": "XPTUSD:CUR",
    "XPDUSD": "XPDUSD:CUR",
    # Bare commodity roots (``GC1!`` is the registry row; ``GC`` alone is not)
    "GC": "GC1:COM",
    "SI": "SI1:COM",
    "CL": "CL1:COM",
    "BZ": "BZ1:COM",
    "NG": "NG1:COM",
    "HG": "HG1:COM",
    # Crypto pairs quoted as currencies
    "XBTUSD": "XBTUSD:CUR",
    "BTC": "XBTUSD:CUR",
    "BTCUSD": "XBTUSD:CUR",
}


def _registry_bloomberg_id(symbol: str) -> str | None:
    """Bloomberg's id for *symbol* from the instrument registry, or ``None``.

    Imports lazily so :mod:`tapebasis.symbols` (which imports nothing from
    this module) stays free of a cycle.
    """
    from .symbols import instrument_row

    row = instrument_row(symbol)
    if row is None:
        return None
    bloomberg = row.get("bloomberg")
    return str(bloomberg) if bloomberg else None


def to_bloomberg(symbol: str) -> str:
    """Resolve a caller's symbol to a Bloomberg quote id.

    Bloomberg spells the same instrument differently from every other provider
    (``AAPL:US``, ``SPX:IND``, ``EURUSD:CUR``, ``CL1:COM``), and its quote URL
    returns a 403 robot page rather than a 404 for an id it does not like. So
    resolution is the instrument registry plus a small alias table plus a
    mechanical rule, never a search:

    * a registry instrument wins (``SPX`` -> ``SPX:IND``, ``XAUUSD`` ->
      ``XAUUSD:CUR``, ``CL1!`` -> ``CL1:COM``),
    * a known alias wins (``DAX`` -> ``DAX:IND``),
    * an id that already carries a Bloomberg suffix is kept (``BRK/B:US``),
    * ``EXCHANGE:TICKER`` drops the exchange (``NASDAQ:AAPL`` -> ``AAPL:US``),
    * a six-letter currency pair becomes ``PAIR:CUR`` (``GBPUSD`` -> ``GBPUSD:CUR``),
    * anything else is a US equity (``BRK.B`` -> ``BRK/B:US``).

    A wrong guess is cheap: the parser reports that Bloomberg has no quote
    object for the page instead of presenting a number.
    """
    raw = (symbol or "").strip()
    if not raw:
        raise NoDataError(PROVIDER, "empty symbol")

    upper = raw.upper().replace(" ", "")
    # Registry first: one canonical home for every instrument spelling.
    registry_id = _registry_bloomberg_id(upper)
    if registry_id:
        return registry_id
    alias = _ALIASES.get(upper)
    if alias:
        return alias

    if ":" in upper:
        head, _, suffix = upper.rpartition(":")
        if suffix in _SUFFIXES:
            # Already a Bloomberg id; normalise the class suffix and keep the
            # rest verbatim, including a share-class slash.
            return f"{head}:{suffix}"
        # EXCHANGE:TICKER from another provider's vocabulary: keep the ticker.
        upper = suffix

    if not upper:
        raise NoDataError(PROVIDER, f"{symbol!r} has no ticker part")

    compact = upper.replace("/", "").replace(".", "")
    if len(compact) == 6 and compact.isalpha():
        return f"{compact}:CUR"

    if upper.endswith(":US") or upper.endswith(":CUR"):
        return upper
    return f"{upper.replace('.', '/')}:US"


# ── transport ───────────────────────────────────────────────────────────────


def _client() -> Any:
    """Import ``curl_cffi`` lazily, with an actionable error when it is absent."""
    try:
        from curl_cffi.requests import AsyncSession
    except Exception as exc:  # noqa: BLE001 - the package is the only requirement
        raise ProviderError(
            PROVIDER,
            "curl_cffi is not installed. Bloomberg gates plain HTTP clients on the "
            "TLS fingerprint, so this provider needs curl_cffi (pip install curl_cffi)",
            code="NOT_CONFIGURED",
        ) from exc
    return AsyncSession


#: One pooled ``curl_cffi`` session per event loop. The loop key is weak, so a
#: closed loop's session goes with it: the hermetic suite runs one loop per test
#: and must never inherit a socket from another test.
_SESSIONS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any]" = (
    weakref.WeakKeyDictionary()
)


def _session() -> Any:
    """The pooled ``curl_cffi`` session for the running loop, created on first use.

    The session carries the browser impersonation that gets past bloomberg.com's
    bot wall, so it is created with the same options a per-request session was.

    Returns:
        A reusable ``curl_cffi`` ``AsyncSession``. Callers must not close it;
        :func:`aclose` does that when the server shuts down.
    """
    AsyncSession = _client()
    loop = asyncio.get_running_loop()
    session = _SESSIONS.get(loop)
    if session is None:
        session = AsyncSession(
            impersonate=_IMPERSONATE,
            timeout=_TIMEOUT,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        _SESSIONS[loop] = session
    return session


async def aclose() -> None:
    """Close the pooled session of the running loop, if there is one."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    session = _SESSIONS.pop(loop, None)
    if session is None:
        return
    try:
        await session.close()
    except Exception:  # noqa: BLE001 - shutdown must not fail on a dead session
        pass


async def _fetch_html(path: str, cache_key: str) -> str:
    """Fetch one page under the provider limiter, with a short TTL cache."""
    paced = limiter(PROVIDER)
    cached = paced.cache_get(cache_key, _CACHE_TTL)
    if isinstance(cached, str):
        return cached

    async def _once() -> str:
        session = _session()
        response = await session.get(f"{_BASE}{path}")
        status = response.status_code
        body = response.text
        if status == 429:
            raise RateLimited(PROVIDER, "HTTP 429 from bloomberg.com")
        if status in (401, 403):
            # The bot wall, not a missing instrument: back off, so a caller that
            # keeps asking does not deepen the block.
            paced.note_rate_limited()
            raise ProviderError(
                PROVIDER,
                f"bloomberg.com refused the request with HTTP {status}. This is the "
                "anti-bot wall, usually because too many requests arrived too fast; "
                "the provider is cooling down",
                code="UPSTREAM_BLOCKED",
            )
        if status == 404:
            raise NoDataError(PROVIDER, f"bloomberg.com has no quote page for {path}")
        if status != 200:
            raise ProviderError(
                PROVIDER,
                f"bloomberg.com answered HTTP {status}",
                code="UPSTREAM_ERROR",
            )
        paced.cache_set(cache_key, body)
        return body

    return await call(PROVIDER, _once, attempts=1)


def _payload(html: str) -> dict[str, Any]:
    """Decode ``__NEXT_DATA__`` out of a rendered quote page."""
    match = _NEXT_DATA.search(html)
    if not match:
        raise ProviderError(
            PROVIDER,
            "quote page no longer contains __NEXT_DATA__; the page was "
            "restructured or an interstitial was served",
            code="SCHEMA_DRIFT",
        )
    try:
        return json.loads(match.group("body"))
    except ValueError as exc:
        raise ProviderError(
            PROVIDER,
            f"__NEXT_DATA__ is not valid JSON: {exc}",
            code="SCHEMA_DRIFT",
        ) from exc


# ── shaping ─────────────────────────────────────────────────────────────────


def _number(value: Any) -> float | None:
    """Parse Bloomberg's formatted numbers (``"89,637,749.00"``, ``"1.1230"``)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("%", "").strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _pair(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    low, high = _number(value[0]), _number(value[1])
    if low is None or high is None:
        return None
    return [low, high]


def _print_time(payload: dict[str, Any], price: float | None) -> tuple[str | None, str | None]:
    """The real print time, taken from the intraday series, never ``lastUpdate``.

    ``lastUpdate`` on an equity page is a session sentinel such as
    ``2026-11-05T01:00:00.000Z`` while the actual print is hours earlier, so
    using it would make a stale page win a freshness comparison against a live
    one. The last intraday point is the print, and it is only trusted when its
    value matches the quoted price: if the series ends somewhere else, its
    timestamp describes a different number.

    Returns ``(iso_timestamp, reason_when_missing)``.
    """
    series = payload.get("priceMovements1Day")
    if not isinstance(series, list) or not series:
        return None, "the page carries no intraday series, so the print time is unknown"
    last = series[-1] if isinstance(series[-1], dict) else None
    if not last or not last.get("dateTime"):
        return None, "the last intraday point carries no timestamp"
    last_value = _number(last.get("value"))
    if price is not None and last_value is not None:
        tolerance = max(abs(price) * 0.001, 1e-9)
        if abs(last_value - price) > tolerance:
            return (
                None,
                "the intraday series ends at "
                f"{last_value} while the quoted price is {price}, so the series "
                "timestamp does not describe the quoted print",
            )
    return str(last["dateTime"]), None


def shape_quote(payload: dict[str, Any], *, requested: str) -> dict[str, Any]:
    """Normalise Bloomberg's quote object into this server's vocabulary."""
    price = _number(payload.get("price"))
    if price is None:
        raise NoDataError(
            PROVIDER,
            f"bloomberg.com has a page for {payload.get('id') or requested} but no "
            "price for it",
        )
    print_time, print_time_reason = _print_time(payload, price)
    percentage = _number(payload.get("percentChange1Day"))
    return {
        "symbol": payload.get("id") or requested,
        "requested": requested,
        "name": payload.get("name") or payload.get("shortName"),
        "price": price,
        "change_percent": percentage,
        "previous_close": _number(payload.get("prevClose")),
        "currency": payload.get("issuedCurrency"),
        "exchange": payload.get("primaryExchange"),
        "day_range": _pair(payload.get("dayRange")),
        "week_52_range": _pair(payload.get("fiftyTwoWeekRange")),
        "volume": _number(payload.get("volume")),
        "pe_ratio": _number(payload.get("priceEarningsRatio")),
        "eps": _number(payload.get("earningsPerShare")),
        "market_status": payload.get("marketStatus"),
        "is_open": payload.get("isOpen"),
        "is_after_hours": payload.get("isAfterHours"),
        "is_exchange_delayed": payload.get("isExchangeDelayed"),
        "exchange_delay": payload.get("exchangeDelay"),
        "trading_date": payload.get("tradingDate"),
        "trading_day_close": payload.get("tradingDayClose"),
        "print_time": print_time,
        "print_time_source": "priceMovements1Day[-1].dateTime" if print_time else None,
        "print_time_missing_reason": print_time_reason,
        # Kept visible, never used as the print time: see ``_print_time``.
        "provider_last_update": payload.get("lastUpdate"),
    }


_BOARD_GROUPS: tuple[tuple[str, str], ...] = (
    ("IND", "indices"),
    ("GOV", "government_yields"),
    ("COM", "commodities"),
    ("CUR", "fx"),
)


def shape_board(payload: dict[str, Any]) -> dict[str, Any]:
    """Group Bloomberg's market board (``tickerbar``) by instrument class.

    The board is where Bloomberg earns its place: it carries the government
    benchmark curve, which no other provider here publishes. It also carries
    index levels, commodities and FX, kept as context. The board has no
    per-instrument print time, so nothing here can be aged or ordered, and the
    response says so instead of implying a live tape.
    """
    rows = payload.get("tickerbar")
    if not isinstance(rows, list) or not rows:
        raise NoDataError(PROVIDER, "the market board carried no tickerbar rows")

    groups: dict[str, list[dict[str, Any]]] = {name: [] for _, name in _BOARD_GROUPS}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "")
        _, _, suffix = ticker.rpartition(":")
        for class_suffix, group_name in _BOARD_GROUPS:
            if suffix == class_suffix:
                groups[group_name].append(
                    {
                        "symbol": ticker,
                        "name": row.get("name"),
                        "price": _number(row.get("price")),
                        "change_percent": _number(row.get("percentChange1Day")),
                    }
                )
                break
    if not any(groups.values()):
        raise NoDataError(PROVIDER, "the market board carried no usable rows")
    return groups


# ── public accessors ────────────────────────────────────────────────────────


async def quote(symbol: str) -> tuple[dict[str, Any], str]:
    """Bloomberg's quote page for *symbol*, shaped and labelled.

    Returns the shaped payload plus the upstream URL it came from.
    """
    bloomberg_id = to_bloomberg(symbol)
    path = f"/quote/{bloomberg_id}"
    html = await _fetch_html(path, f"quote:{bloomberg_id}")
    payload = _payload(html).get("props", {}).get("pageProps", {})
    quote_payload = payload.get("quote")
    if not isinstance(quote_payload, dict):
        raise NoDataError(
            PROVIDER,
            f"bloomberg.com has no quote for {bloomberg_id}",
        )
    return shape_quote(quote_payload, requested=symbol), f"{_BASE}{path}"


async def board() -> tuple[dict[str, Any], str]:
    """Bloomberg's market board (indices, government yields, commodities, FX)."""
    path = "/markets/rates-bonds"
    html = await _fetch_html(path, "board:markets")
    payload = _payload(html).get("props", {}).get("pageProps", {})
    return shape_board(payload), f"{_BASE}{path}"


__all__ = ["PROVIDER", "board", "quote", "shape_board", "shape_quote", "to_bloomberg"]
