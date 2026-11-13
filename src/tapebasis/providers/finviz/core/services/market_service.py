"""
Market-wide services, index snapshot, why-is-it-moving, options chain.

The three live together because they answer "what is the state of the market
right now" rather than "profile one ticker":

* ``/api/indices_data``     : DJI, COMP, SPX, IWM intraday OHLCV series.
* ``/api/stocks-why-moving/{t}``, Finviz's own AI explainer for the day's move
  (also available as the ``why-stock-moving-init-data-0`` island on the quote
  page; the API is preferred because it is fetched without the page).
* ``/stock?t={t}&ty=oc``    : options chain inside ``route-init-data``.

The why-moving endpoint has two spellings: ``/api/stocks-why-moving/{t}``
returns one record, and ``/api/stocks-why-moving/boxover/{t}`` returns the same
record (the ``boxover`` variant is what the hover card requests). Both are 404
for tickers with no explainer entry, which is reported as ``NO_DATA``, not as
an error the caller should retry.
"""
from __future__ import annotations

from typing import Any

from tapebasis.providers.finviz.core.errors import ErrorCode, FinvizServiceError
from tapebasis.providers.finviz.core.services import finviz_client
from tapebasis.providers.finviz.core.services.html_utils import extract_script_json
from tapebasis.providers.finviz.core.utils.validators import validate_ticker
from tapebasis.symbols import INSTRUMENTS, INDEX_SNAPSHOT

#: Finviz index ticker -> display name. Derived from the instrument registry,
#: restricted to the documented snapshot list, so the names live in one place
#: and a broader registry row (NDX, addressable through single-instrument
#: quotes) cannot silently join the snapshot loop.
INDEX_TICKERS = {
    canonical: str(row["name"])
    for canonical, row in INSTRUMENTS.items()
    if (canonical in INDEX_SNAPSHOT and row["asset_class"] == "index")
    or canonical == "IWM"
}


async def get_market_indices() -> dict[str, Any]:
    """Return the latest level and day change for the four finviz indices.

    The upstream payload is a ~10 KB map of full intraday series per index. It
    is trimmed here to the fields an agent reports on, with the intraday series
    available under ``intraday`` for callers that want to chart it.

    Raises:
        FinvizServiceError: ``PARSE_ERROR`` when the payload is not the
            expected index map.
    """
    url = f"{finviz_client.BASE_URL}/api/indices_data"
    payload = await finviz_client.fetch_json(url, ttl=15)
    if not isinstance(payload, dict) or not payload:
        raise FinvizServiceError(
            ErrorCode.PARSE_ERROR, "Unexpected indices payload from finviz.com", url=url
        )

    indices = []
    for symbol, entry in payload.items():
        if not isinstance(entry, dict):
            continue
        indices.append(
            {
                "ticker": symbol,
                "name": INDEX_TICKERS.get(symbol, symbol),
                "last": entry.get("lastClose"),
                "prev_close": entry.get("prevClose"),
                "change": entry.get("perfDayUsd"),
                "change_percent": entry.get("perfDayPct"),
                "day_open": entry.get("lastOpen"),
                "day_high": entry.get("lastHigh"),
                "day_low": entry.get("lastLow"),
                "after_close": entry.get("afterClose"),
                "after_change": entry.get("afterChange"),
                "last_update": entry.get("lastDate"),
                "intraday": {
                    "timestamps": entry.get("date") or [],
                    "open": entry.get("open") or [],
                    "high": entry.get("high") or [],
                    "low": entry.get("low") or [],
                    "close": entry.get("close") or [],
                    "volume": entry.get("volume") or [],
                },
            }
        )

    indices.sort(key=lambda row: list(INDEX_TICKERS).index(row["ticker"])
                 if row["ticker"] in INDEX_TICKERS else 99)
    return {"indices": indices, "count": len(indices), "source": url}


async def get_why_moving(ticker: str) -> dict[str, Any]:
    """Return finviz's explainer for the ticker's most recent move.

    Response fields: ``headline``, ``summary`` (markdown bullet list),
    ``source`` (``detective``), ``sentiment`` (``good``/``bad``/``neutral``),
    ``catalyst`` (bool), ``dateTime``.

    Raises:
        FinvizServiceError: ``NO_DATA`` when finviz has no explainer entry for
            the symbol (a 404 upstream), or ``PARSE_ERROR`` for a malformed body.
    """
    symbol = validate_ticker(ticker)
    url = f"{finviz_client.BASE_URL}/api/stocks-why-moving/{symbol}"
    payload = await finviz_client.fetch_json(url)
    if not isinstance(payload, dict) or "headline" not in payload:
        raise FinvizServiceError(
            ErrorCode.NO_DATA,
            f"finviz.com has no 'why is it moving' entry for {symbol}",
            ticker=symbol,
        )
    return {
        "ticker": symbol,
        "headline": payload.get("headline"),
        "summary": payload.get("summary"),
        "sentiment": payload.get("sentiment"),
        "catalyst": payload.get("catalyst"),
        "datetime": payload.get("dateTime"),
        "source": url,
    }


async def get_options_chain(ticker: str, expiry: str | None = None) -> dict[str, Any]:
    """Return the options chain for one expiry (``ty=oc`` island).

    Args:
        ticker: Underlying symbol.
        expiry: ``YYYY-MM-DD``. ``None`` uses the nearest expiry finviz picks.

    Returns:
        ``{"ticker", "expiry", "expiries", "contracts": [...], "count",
        "last_close"}``. Each contract carries strike, bid/ask, IV, greeks,
        open interest and volume as finviz computes them.

    Raises:
        FinvizServiceError: ``NO_DATA`` when the chain is empty (no listed
            options), ``INVALID_PARAMETER`` for a malformed expiry.
    """
    symbol = validate_ticker(ticker)
    url = f"{finviz_client.BASE_URL}/stock?t={symbol}&ty=oc&ta=1&p=d"
    if expiry:
        if len(expiry) != 10 or expiry.count("-") != 2:
            raise FinvizServiceError(
                ErrorCode.INVALID_PARAMETER,
                f"Invalid expiry {expiry!r}; expected YYYY-MM-DD",
                expiry=expiry,
            )
        url += f"&e={expiry}"

    html = await finviz_client.fetch_html(url)
    data = extract_script_json(html, "route-init-data")
    if not isinstance(data, dict):
        raise FinvizServiceError(
            ErrorCode.NO_DATA, f"No options data for {symbol}", ticker=symbol
        )

    contracts = data.get("options") or []
    if not contracts:
        raise FinvizServiceError(
            ErrorCode.NO_DATA,
            f"finviz.com lists no option contracts for {symbol}"
            + (f" expiring {expiry}" if expiry else ""),
            ticker=symbol,
            expiry=expiry,
        )

    return {
        "ticker": symbol,
        "expiry": data.get("currentExpiry"),
        "expiries": data.get("expiries") or [],
        "last_close": data.get("lastClose"),
        "contracts": contracts,
        "count": len(contracts),
        "source": url,
    }
