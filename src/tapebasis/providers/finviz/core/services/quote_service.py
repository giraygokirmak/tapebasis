"""
Quote + fundamentals services, the ``/stock?t={ticker}`` document route.

finviz has no JSON endpoint for a single ticker's quote (``/api/quote`` answers
``{"error":"invalid quote query"}`` for every parameter spelling), so this is
the one place where the server must read the rendered page. A single fetch of
``/stock?t=VCIG&ta=1&p=d`` carries all of it:

* the ticker header (last close / after-hours, sector/industry/country chips),
* the 84-field snapshot table (6 ``table.js-snapshot-table`` blocks),
* the company profile paragraph,
* the Peers row,
* ``why-stock-moving-init-data`` / ``institutional-ownership-init-data`` blocks.

The tab routes layer on the same page with ``ty=``:

======================  ==========================================
``ty=si``               Short interest history (route-init-data)
``ty=ea``               Earnings history + revisions + FA series
``ty=oc``               Options chain (route-init-data)
``ty=lf``               Latest filings (route-init-data)
``ty=di``               Dilution risk model (route-init-data)
======================  ==========================================
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tapebasis.providers.finviz.core.errors import ErrorCode, FinvizServiceError
from tapebasis.providers.finviz.core.services import finviz_client
from tapebasis.providers.finviz.core.services.html_utils import (
    extract_script_json,
    parse_peers,
    parse_profile,
    parse_quote_header,
    parse_snapshot,
)
from tapebasis.providers.finviz.core.utils.validators import validate_ticker

#: Snapshot labels that are genuinely numeric. Everything else stays a string
#: because finviz renders ranges ("-25.75% 32.62%") and suffixes ("0.56M") that
#: do not survive a blind float() cast.
_NUMERIC_SUFFIXES = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def _stock_url(ticker: str, *, tab: str | None = None) -> str:
    url = f"{finviz_client.BASE_URL}/stock?t={ticker}&ta=1&p=d"
    if tab:
        url += f"&ty={tab}"
    return url


def coerce_snapshot_value(raw: str) -> Any:
    """Best-effort numeric coercion for one snapshot cell.

    Rules, in order:
        * ``-`` / ``--`` / empty          → ``None``
        * ``0.56M``, ``1.2B``, ``12K``    → scaled float
        * ``-25.75%``                     → float (percent, sign preserved)
        * ``-25.75% 32.62%``              → list of floats (past 3Y / 5Y cells)
        * ``Nov 02 3:45 PM``              → untouched string
    """
    if raw is None:
        return None
    text = raw.strip()
    if text in {"", "-", "--", "N/A", "n/a"}:
        return None

    def _one(token: str) -> Any:
        token = token.strip()
        if token in {"", "-", "--"}:
            return None
        negative = token.startswith("(") and token.endswith(")")
        if negative:
            token = token[1:-1]
        if token.endswith("%"):
            token = token[:-1]
        multiplier = 1.0
        if token and token[-1].upper() in _NUMERIC_SUFFIXES and token[:-1].replace(
            ".", "", 1
        ).replace("-", "", 1).replace(",", "").isdigit():
            multiplier = _NUMERIC_SUFFIXES[token[-1].upper()]
            token = token[:-1]
        try:
            value = float(token.replace(",", "")) * multiplier
        except ValueError:
            return text
        return -value if negative else value

    parts = text.split()
    if len(parts) > 1 and all(
        p.endswith("%") or p in {"-", "--"} for p in parts
    ):
        coerced = [_one(p) for p in parts]
        return coerced
    return _one(text)


def _numbers(fields: dict[str, str]) -> dict[str, Any]:
    return {label: coerce_snapshot_value(value) for label, value in fields.items()}


def _resolved_warning(requested: str, header: dict[str, Any]) -> dict[str, Any] | None:
    """finviz silently redirects delisted/renamed symbols (XXXX → SPYU)."""
    actual = (header.get("ticker") or "").upper()
    if actual and actual != requested:
        return {
            "requested_ticker": requested,
            "resolved_ticker": actual,
            "note": "finviz resolved this symbol to a different instrument "
            "(renamed, merged or reused ticker)",
        }
    return None


#: The three revenue axes finviz publishes under ``revenue``, keyed to the
#: vocabulary the payload uses. The meaning of each axis is company-specific
#: (Apple's ``segment`` is geographic, NVIDIA's is operating segments), so the
#: keys stay as finviz sends them instead of being relabelled into something
#: that would be wrong for half the market.
_REVENUE_AXES = ("products_and_services", "regions", "segment")

#: The island's two blocks do not share a scale. ``statement`` publishes
#: millions (``"478,834.00"`` for Apple's $478.834bn) while ``revenue`` publishes
#: absolute dollars (``37929000000`` for a $37.929bn product line). Verified
#: against the page's own ``Sales`` snapshot field across large caps, banks,
#: foreign filers and sub-million-revenue companies: statement x 1e6 lines up
#: with it every time, the axis totals line up with the statement. Serving the
#: raw strings would hand an agent two numbers for the same company that differ
#: by six orders of magnitude, so the statement is scaled here and the applied
#: factor is reported alongside.
_STATEMENT_SCALE = 1_000_000.0


def _parse_money(text: Any) -> float | None:
    """``"1,234.50"`` / ``""`` / ``"-"`` -> float or None.

    The breakdown island formats every amount as a comma-grouped string with no
    currency symbol and no scaling suffix, so this is deliberately narrower than
    :func:`coerce_snapshot_value`: a suffix here would be a formatting change
    worth surfacing, not silently guessing.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    cleaned = str(text).strip().replace(",", "")
    if cleaned in {"", "-", "--", "n/a", "N/A"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def shape_income_breakdown(payload: Any) -> dict[str, Any] | None:
    """Normalise the ``income-breakdown-init-data-0`` island.

    The island carries two things the rest of the quote page does not:

    * ``statement``: the "Revenue & Expenses Breakdown" table, up to two fiscal
      years of revenue / gross profit / operating income / net income plus the
      expense lines between them. Bank-shaped filers swap the row set (interest
      income, loan loss provision, ...) because that is what they report.
    * ``revenue``: up to three annual revenue axes (product line, geographic
      region, reported segment). Which axes exist varies by company and some
      filers have only one.

    Two traps are handled explicitly rather than left to the caller:

    * **Scale.** ``statement`` is published in millions, ``revenue`` in absolute
      currency units (see :data:`_STATEMENT_SCALE`). The statement is multiplied
      out so every amount in the response is in the same unit, and
      ``statement.scale_applied`` states the factor that was used.
    * **Currency.** ``converted`` is true when finviz FX-converted the axis
      amounts into the filing currency; ``currency`` and ``unit`` are reported
      next to the numbers, and ``converted`` stays visible, so a caller never has
      to assume either.

    Returns ``None`` when the island is absent or holds neither block, so the
    caller can tell "finviz has no breakdown" from "the breakdown was empty".
    """
    if not isinstance(payload, dict):
        return None

    statement = payload.get("statement")
    out: dict[str, Any] = {}
    if isinstance(statement, dict) and isinstance(statement.get("data"), dict):
        raw_rows = statement["data"]
        periods = raw_rows.get("Period") or []
        rows: list[dict[str, Any]] = []
        for label, values in raw_rows.items():
            if label == "Period" or not isinstance(values, list):
                continue
            amounts = [_parse_money(value) for value in values]
            rows.append(
                {
                    "label": label,
                    "values": [
                        None if amount is None else amount * _STATEMENT_SCALE
                        for amount in amounts
                    ],
                }
            )
        if periods and rows:
            out["statement"] = {
                "currency": statement.get("currency"),
                # Every amount below is absolute currency units; the source
                # table is in millions and was multiplied by this factor.
                "scale_applied": _STATEMENT_SCALE,
                "periods": list(periods),
                "rows": rows,
            }

    revenue = payload.get("revenue")
    if isinstance(revenue, dict):
        axes: dict[str, Any] = {}
        for axis in _REVENUE_AXES:
            block = revenue.get(axis)
            if not isinstance(block, dict):
                continue
            series: dict[str, dict[str, float | None]] = {}
            years: list[str] = []
            for name, points in (block.get("revenues") or {}).items():
                if not isinstance(points, list):
                    continue
                by_year: dict[str, float | None] = {}
                for point in points:
                    if not isinstance(point, dict):
                        continue
                    year = str(point.get("fiscal_year") or "")
                    if not year:
                        continue
                    by_year[year] = _parse_money(point.get("value"))
                    if year not in years:
                        years.append(year)
                if by_year:
                    series[str(name)] = by_year
            if not series:
                continue
            axes[axis] = {
                "unit": block.get("unit"),
                "converted": block.get("converted"),
                "series": series,
            }
        if axes:
            # Newest fiscal year first, the same direction finviz's own table
            # reads, so the two blocks line up without the caller re-sorting.
            years = sorted(
                {
                    year
                    for axis in axes.values()
                    for by_year in axis["series"].values()
                    for year in by_year
                },
                reverse=True,
            )
            out["revenue"] = {"years": years, "axes": axes}

    return out or None


async def get_quote(ticker: str) -> dict[str, Any]:
    """Full overview for one ticker: header + snapshot + profile + peers.

    Costs exactly one upstream page fetch (cached for ``FINVIZ_CACHE_TTL``s).

    Raises:
        FinvizServiceError: ``INVALID_TICKER`` or ``NO_DATA`` for unknown symbols.
    """
    symbol = validate_ticker(ticker)
    html = await finviz_client.fetch_html(_stock_url(symbol), elite_check=False)

    header = parse_quote_header(html)
    snapshot = parse_snapshot(html)
    profile = parse_profile(html)
    peers = parse_peers(html)
    # The revenue/expense breakdown ships as a JSON island on this same page, so
    # reading it costs no extra request. It used to be dropped entirely: the
    # page was fetched, the island was in the HTML, and nothing downstream could
    # see the segment or geographic revenue split because of it.
    income_breakdown = shape_income_breakdown(
        extract_script_json(html, "income-breakdown-init-data-0")
    )

    if not header.get("ticker") or not snapshot["fields"]:
        raise FinvizServiceError(
            ErrorCode.NO_DATA,
            f"finviz.com returned no quote data for {symbol}",
            ticker=symbol,
        )

    payload: dict[str, Any] = {
        "ticker": header["ticker"],
        "company": header.get("company"),
        "website": header.get("website"),
        "logo_url": header.get("logo_url"),
        "exchange": header.get("exchange"),
        "sector": header.get("sector"),
        "industry": header.get("industry"),
        "country": header.get("country"),
        "market_cap_class": header.get("market_cap_class"),
        "etf_type": header.get("etf_type"),
        "last_close": header.get("last_close"),
        "after_hours": header.get("after_hours"),
        "snapshot": snapshot["fields"],
        "snapshot_numeric": _numbers(snapshot["fields"]),
        "snapshot_pairs": snapshot["pairs"],
        "descriptions": snapshot["descriptions"],
        "income_breakdown": income_breakdown,
        "profile": profile,
        "peers": peers,
        "source": _stock_url(symbol),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    warning = _resolved_warning(symbol, header)
    if warning:
        payload["ticker_warning"] = warning
    return payload


async def get_snapshot(ticker: str) -> dict[str, Any]:
    """The 84 snapshot metrics only, with finviz's own metric descriptions.

    Use this when an agent needs fundamentals but not prices/peers; the
    payload is a third of :func:`get_quote` and far easier to reason about.
    """
    symbol = validate_ticker(ticker)
    html = await finviz_client.fetch_html(_stock_url(symbol))
    snapshot = parse_snapshot(html)
    if not snapshot["fields"]:
        raise FinvizServiceError(
            ErrorCode.NO_DATA, f"No snapshot table for {symbol}", ticker=symbol
        )
    return {
        "ticker": symbol,
        "fields": snapshot["fields"],
        "numeric": _numbers(snapshot["fields"]),
        "pairs": snapshot["pairs"],
        "descriptions": snapshot["descriptions"],
        # Same island, same page: reading it here adds no request and makes the
        # fundamentals-only tool able to answer "which segment earned the
        # revenue" instead of only reporting the consolidated total.
        "income_breakdown": shape_income_breakdown(
            extract_script_json(html, "income-breakdown-init-data-0")
        ),
        "field_count": len(snapshot["fields"]),
    }


async def get_peers(ticker: str, limit: int = 12) -> dict[str, Any]:
    """Peer group from the page's Peers row.

    Note: ``/api/related-tickers`` is **not** used here. That endpoint ignores
    its ``ticker`` parameter and returns the same mega-cap list (AAPL, NVDA,
    MSFT, ...) for every symbol, so it is useless as a peer source.
    """
    symbol = validate_ticker(ticker)
    html = await finviz_client.fetch_html(_stock_url(symbol))
    peers = parse_peers(html)[: max(1, limit)]
    if not peers:
        raise FinvizServiceError(
            ErrorCode.NO_DATA, f"finviz.com lists no peers for {symbol}", ticker=symbol
        )
    return {"ticker": symbol, "peers": peers, "count": len(peers)}


async def get_short_interest(ticker: str, limit: int = 60) -> dict[str, Any]:
    """Short-interest history from the ``ty=si`` tab's ``route-init-data`` block.

    Each series point is a bi-weekly FINRA settlement snapshot:
    ``shortInterest`` (shares short, in thousands), ``sharesFloat`` (thousands)
    and ``averageVolume``. Take the last element for the current reading.

    Raises:
        FinvizServiceError: ``NO_DATA`` when the tab carries no series (common
            for very recent IPOs).
    """
    symbol = validate_ticker(ticker)
    html = await finviz_client.fetch_html(_stock_url(symbol, tab="si"))
    series = extract_script_json(html, "route-init-data")
    if not isinstance(series, list) or not series:
        raise FinvizServiceError(
            ErrorCode.NO_DATA,
            f"No short-interest series for {symbol} (tab may be empty for recent IPOs)",
            ticker=symbol,
        )

    points = []
    for row in series[-max(1, limit) :]:
        stamp = row.get("timestamp")
        points.append(
            {
                "date": datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%Y-%m-%d")
                if isinstance(stamp, (int, float))
                else None,
                "short_interest_shares_k": row.get("shortInterest"),
                "shares_float_k": row.get("sharesFloat"),
                "average_volume_k": row.get("averageVolume"),
            }
        )

    latest = points[-1] if points else None
    floats = latest["shares_float_k"] if latest else None
    short_pct = None
    if latest and latest["short_interest_shares_k"] and floats:
        short_pct = round(latest["short_interest_shares_k"] / floats * 100, 2)

    return {
        "ticker": symbol,
        "latest": latest,
        "short_float_percent": short_pct,
        "history": points,
        "points": len(points),
        "source": _stock_url(symbol, tab="si"),
    }


def _has_fundamental_series(fa: Any) -> bool:
    """True when the FA chart island actually carries points.

    finviz renders an empty island (``{"annual": {"values": [[],[],[]]}, ...}``)
    for tickers with no reported statements, common for recent IPOs and
    foreign issuers filing 6-K only. That shape is truthy but meaningless, so it
    is rejected explicitly instead of returning zeros.
    """
    if not isinstance(fa, dict):
        return False
    for period in fa.values():
        if not isinstance(period, dict):
            continue
        for series in period.get("values") or []:
            if isinstance(series, list) and series:
                return True
    return False


async def get_earnings(ticker: str) -> dict[str, Any]:
    """Earnings calendar + reported results + estimate revisions (``ty=ea``).

    The page carries a 2 MB ``route-init-data`` island for large caps; the
    payload is trimmed here to the parts an agent actually uses:

    * ``next_earnings_date`` / ``earnings_date``
    * ``reported``, last 12 quarterly rows (actual vs estimate)
    * ``annual``, annual history
    * ``revisions``, most recent 200 estimate-revision rows
    * ``price_reactions``, post-earnings moves
    * ``fundamental_series``, the ``fa-init-data-0`` chart series
    """
    symbol = validate_ticker(ticker)
    html = await finviz_client.fetch_html(_stock_url(symbol, tab="ea"))
    data = extract_script_json(html, "route-init-data")
    fa = extract_script_json(html, "fa-init-data-0")
    if not isinstance(data, dict):
        raise FinvizServiceError(
            ErrorCode.NO_DATA, f"No earnings data for {symbol}", ticker=symbol
        )

    quarterly = data.get("earningsData") or []
    annual = data.get("earningsAnnualData") or []
    revisions = data.get("earningsRevisionsData") or []
    if isinstance(revisions, dict):  # legacy shape
        revisions = []
    reactions = data.get("priceReactionData") or []

    if not quarterly and not annual and not _has_fundamental_series(fa):
        raise FinvizServiceError(
            ErrorCode.NO_DATA,
            f"finviz.com has no earnings history for {symbol} "
            "(no reported quarters, no annual history and an empty "
            "fundamental series, typical for a recent IPO or a foreign "
            "private issuer that only files 6-K)",
            ticker=symbol,
        )

    return {
        "ticker": symbol,
        "earnings_date": data.get("earningsDate"),
        "quarterly": quarterly[-12:],
        "annual": annual,
        "revisions": revisions[-200:],
        "price_reactions": reactions,
        "fundamental_series": fa if _has_fundamental_series(fa) else None,
        "counts": {
            "quarterly": len(quarterly),
            "annual": len(annual),
            "revisions": len(revisions),
        },
        "source": _stock_url(symbol, tab="ea"),
    }


async def get_dilution(ticker: str) -> dict[str, Any]:
    """Dilution-risk model from the ``ty=di`` tab (share count, float, cash runway).

    Finviz ships this as a versioned JSON island (``schema_version: 1``) aimed
    at the Dilution page, but only for companies whose share count Finviz
    considers dilution-prone: large caps return ``null`` for the island and
    render the *income statement breakdown* instead
    (``income-breakdown-init-data-0``).

    That breakdown is not dilution data, and it used to be returned from here
    anyway, which made a tool named ``stock_dilution`` answer with an income
    statement and ``model_available: false`` for 29 of 30 tickers. It is now
    served where it belongs (``stock_quote`` and the Finviz snapshot carry it
    from the same page), so this function raises ``NO_DATA`` instead of
    substituting a different dataset.
    """
    symbol = validate_ticker(ticker)
    html = await finviz_client.fetch_html(_stock_url(symbol, tab="di"))
    data = extract_script_json(html, "route-init-data")

    if isinstance(data, dict) and "company" in data:
        data.setdefault("source", _stock_url(symbol, tab="di"))
        data.setdefault("model_available", True)
        return data

    raise FinvizServiceError(
        ErrorCode.NO_DATA,
        f"finviz.com has no dilution model for {symbol}: it only builds one for "
        "companies whose share count it considers dilution-prone. The tab does "
        "render an income-statement breakdown, but that is revenue/expense data, "
        "not dilution; it is served by stock_quote under `income_breakdown`.",
        ticker=symbol,
    )
