"""Typed access to stockanalysis.com's public quote API.

StockAnalysis is a reconciliation leg: ``stock_quote``, ``stock_prices`` and
``stock_extended_hours`` ask it in parallel with the other providers, its
readings appear in ``comparisons``, and it contributes to ``ALL``.

Three properties of the feed are handled here rather than hidden:

* it is a **US** feed. ``/api/quotes/s/<ticker>`` answers US-listed equities and
  ETFs and 404s on indices, FX, crypto, commodities and foreign listings, so a symbol that
  is not a US slug is reported as not carried instead of being sent to a page
  that cannot exist (see :mod:`tapebasis.symbols`),
* its quote surface is the **same consolidated tape** Yahoo serves (measured
  penny-identical on price, previous close, day range, volume and the 52-week
  range), so agreement between those two is weak corroboration rather than two
  independent witnesses. The docs say so; the payload is not inflated to hide
  it,
* ``ts`` is epoch **milliseconds**, not seconds. It is converted to ISO here;
  passing it through would date a print to the year 56828 and look newer than
  every other provider.

Transport is plain ``httpx``: unlike bloomberg.com this host is not gated on the
TLS fingerprint, so no browser impersonation is needed. The endpoint advertises
``cache-control: s-maxage=3`` and sits behind Cloudflare, so a short TTL cache
absorbs duplicate asks within one agent turn without serving a stale price.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from .providers_state import NoDataError, ProviderError
from .ratelimit import RateLimited, call, limiter

PROVIDER = "SA"

_BASE = "https://stockanalysis.com"
_TIMEOUT = float(os.environ.get("TAPEBASIS_SA_TIMEOUT", "20"))
#: The upstream itself advertises a 3 s shared cache; 20 s absorbs an agent
#: asking for the same quote twice in one turn without ever serving a price
#: that a live feed would disagree with.
_CACHE_TTL = float(os.environ.get("TAPEBASIS_SA_CACHE_TTL", "20"))

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

#: Instruments the quote API does not carry are reported by
#: :func:`tapebasis.symbols.resolve_sa` as *not carried* before any request is
#: made. The endpoint answers 404 for every one of them, so treating a 404 as a
#: provider failure would blame the leg for a coverage boundary it declares.
#: The table itself lives in :mod:`tapebasis.symbols`, next to the rule that
#: consults it, rather than being duplicated here.


def to_stockanalysis(symbol: str) -> str:
    """Resolve a caller's symbol to a StockAnalysis quote slug.

    Mechanical, because the site has no quote search API:

    * the venue is dropped (``NASDAQ:AAPL`` -> ``AAPL``),
    * a share-class dash becomes a dot, the site's own spelling
      (``BRK-B`` -> ``brk.b``),
    * the result is lowercased.

    A wrong guess is cheap: the endpoint answers 404 and the caller reports the
    leg as not carrying the instrument.
    """
    raw = (symbol or "").strip()
    if not raw:
        raise NoDataError(PROVIDER, "empty symbol")

    bare = raw.upper().split(":", 1)[-1].replace(" ", "")
    if not bare:
        raise NoDataError(PROVIDER, f"{symbol!r} has no ticker part")

    if "-" in bare and not bare.endswith("-USD"):
        head, _, tail = bare.partition("-")
        if head.isalpha() and tail.isalpha() and len(tail) <= 2:
            bare = f"{head}.{tail}"
    return bare.lower()


# ── transport ───────────────────────────────────────────────────────────────


async def _fetch(path: str, cache_key: str) -> dict[str, Any]:
    """Fetch one JSON endpoint under the provider limiter, with a short cache."""
    paced = limiter(PROVIDER)
    cached = paced.cache_get(cache_key, _CACHE_TTL)
    if isinstance(cached, dict):
        return cached

    async def _once() -> dict[str, Any]:
        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
        ) as client:
            response = await client.get(f"{_BASE}{path}")
        status = response.status_code
        if status == 429:
            raise RateLimited(PROVIDER, "HTTP 429 from stockanalysis.com")
        if status in (401, 403):
            # The bot wall, not a missing instrument: back off so a caller that
            # keeps asking does not deepen the block.
            paced.note_rate_limited()
            raise ProviderError(
                PROVIDER,
                f"stockanalysis.com refused the request with HTTP {status}; the "
                "provider is cooling down",
                code="UPSTREAM_BLOCKED",
            )
        if status in (400, 404):
            # 400 is how the endpoint answers an instrument class it has no
            # route for; 404 is an unknown ticker. Neither is an outage.
            raise NoDataError(
                PROVIDER, f"stockanalysis.com has no quote for {path}"
            )
        if status != 200:
            raise ProviderError(
                PROVIDER,
                f"stockanalysis.com answered HTTP {status}",
                code="UPSTREAM_ERROR",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(
                PROVIDER,
                "the quote endpoint returned no valid JSON; the route may have moved",
                code="SCHEMA_DRIFT",
            ) from exc
        paced.cache_set(cache_key, payload)
        return payload

    return await call(PROVIDER, _once, attempts=1)


# ── shaping ─────────────────────────────────────────────────────────────────


def _number(value: Any) -> float | None:
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


def _iso_from_ms(value: Any) -> str | None:
    """Epoch **milliseconds** -> ISO-8601 UTC.

    ``ts`` and ``ets`` are milliseconds. Handing them to the freshness parser
    unconverted dates the print to a century no provider trades in, which would
    make the leg look freshly printed and win every arbitration.
    """
    number = _number(value)
    if number is None:
        return None
    seconds = number / 1000.0 if number > 1e11 else number
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def shape_quote(payload: dict[str, Any], *, requested: str) -> dict[str, Any]:
    """Normalise StockAnalysis's quote object into this server's vocabulary."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or data.get("p") is None:
        raise NoDataError(
            PROVIDER,
            f"stockanalysis.com has a response for {requested} but no price in it",
        )
    price = _number(data.get("p"))
    if price is None:
        raise NoDataError(
            PROVIDER, f"stockanalysis.com has no usable price for {requested}"
        )

    # ``cl`` is the close the change is measured against, which is exactly what
    # ``previous_close`` means here. ``pd`` duplicates the current price, so it
    # is not the previous close despite the name.
    previous_close = _number(data.get("cl"))
    change_percent = _number(data.get("cp"))
    if change_percent is None:
        change = _number(data.get("c"))
        if change is not None and previous_close:
            change_percent = round(change / previous_close * 100, 4)

    extended = None
    extended_price = _number(data.get("ep"))
    if data.get("e") and extended_price is not None:
        extended = {
            "session": data.get("es"),
            "price": extended_price,
            "change": _number(data.get("ec")),
            "change_percent": _number(data.get("ecp")),
            # ``epd`` is not the baseline: like ``pd`` on the regular side it
            # merely repeats the extended price (measured identical on every
            # symbol). The extended change is measured against the regular
            # session's price, which is ``p``: ``ep - ec == p`` holds on every
            # instrument, so that is the baseline reported here.
            "previous_close": price,
            "volume": _number(data.get("epv")),
            "price_timestamp": _iso_from_ms(data.get("ets")),
            "price_date": data.get("etd"),
        }

    return {
        "symbol": data.get("symbol") or requested.upper(),
        "requested": requested,
        "price": price,
        "change": _number(data.get("c")),
        "change_percent": change_percent,
        "previous_close": previous_close,
        "day_open": _number(data.get("o")),
        "day_high": _number(data.get("h")),
        "day_low": _number(data.get("l")),
        "volume": _number(data.get("v")),
        "week_52_high": _number(data.get("h52")),
        "week_52_low": _number(data.get("l52")),
        "exchange": data.get("ex"),
        "market_state": data.get("ms"),
        "session": data.get("fms"),
        "price_date": data.get("td"),
        # ``ts`` is milliseconds; see ``_iso_from_ms``.
        "price_timestamp": _iso_from_ms(data.get("ts")),
        "price_timestamp_source": "ts (epoch ms)",
        "extended_hours": extended,
        "has_extended_hours": bool(data.get("e")),
        "source": "stockanalysis.com consolidated quote API",
    }


# ── public accessors ────────────────────────────────────────────────────────


async def quote(symbol: str) -> dict[str, Any]:
    """StockAnalysis's quote for *symbol*, shaped.

    US equities and ETFs only; anything else is reported by
    :func:`tapebasis.symbols.resolve_sa` as not carried rather than requested.
    """
    slug = to_stockanalysis(symbol)
    payload = await _fetch(f"/api/quotes/s/{slug}", f"quote:{slug}")
    return shape_quote(payload, requested=symbol)


__all__ = [
    "PROVIDER",
    "quote",
    "shape_quote",
    "to_stockanalysis",
]
