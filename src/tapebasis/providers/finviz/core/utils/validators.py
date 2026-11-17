"""Input validation and sanitising helpers.

Every user-supplied string that ends up in a finviz.com URL is validated here
before it is interpolated. Finviz reflects query parameters straight back into
the HTML/JSON it renders, so unvalidated input is both a correctness and an
injection problem; the allow-lists below are deliberately narrow.
"""
from __future__ import annotations

import re
from typing import Iterable

from tapebasis.providers.finviz.core.errors import ErrorCode, FinvizServiceError

# Tickers: letters, digits, and the separators finviz itself uses
# (BRK.B, RDS-A, ^GSPC for indices). Length capped at 12, with an optional
# leading caret for index symbols.
_TICKER_RE = re.compile(r"^\^?[A-Z0-9][A-Z0-9.\-^]{0,11}$")

# Screener filters look like ``cap_smallover`` / ``sec_technology`` and can be
# OR-combined with ``|`` or AND-combined with ``,``. Negative forms use a
# leading ``-`` (e.g. ``-ind_stocksonly``).
_FILTER_RE = re.compile(r"^-?[a-z0-9_]{1,48}$")

# Sort orders are a metric name with an optional leading ``-`` for descending.
_ORDER_RE = re.compile(r"^-?[a-zA-Z0-9_]{1,40}$")

CHART_PERIODS = {"d": "daily", "w": "weekly", "m": "monthly"}
CHART_TYPES = {"c": "candle", "l": "line"}
CHART_SCALES = {"l": "linear", "log": "logarithmic"}

SCREENER_VIEWS = {
    "111": "Overview",
    "121": "Valuation",
    "131": "Financial",
    "141": "Ownership",
    "151": "Performance",
    "161": "Technical",
    "171": "Custom",
    "152": "Custom (all columns)",
}


def validate_ticker(ticker: str) -> str:
    """Normalise and validate a single ticker symbol.

    Raises:
        FinvizServiceError: ``INVALID_TICKER`` when the symbol cannot be a
            finviz ticker (empty, too long, contains URL metacharacters).
    """
    if not isinstance(ticker, str):
        raise FinvizServiceError(
            ErrorCode.INVALID_TICKER, "Ticker must be a string", ticker=repr(ticker)
        )
    clean = ticker.strip().upper()
    if not clean:
        raise FinvizServiceError(ErrorCode.INVALID_TICKER, "Ticker is empty")
    if not _TICKER_RE.match(clean):
        raise FinvizServiceError(
            ErrorCode.INVALID_TICKER,
            f"Invalid ticker {ticker!r}: expected 1-12 characters A-Z, 0-9, '.', '-' or '^'",
            ticker=ticker,
        )
    return clean


def validate_tickers(tickers: str | Iterable[str], *, limit: int = 50) -> list[str]:
    """Normalise a comma-separated ticker list (or an iterable) to unique symbols."""
    if isinstance(tickers, str):
        raw = [part for part in re.split(r"[,\s]+", tickers.strip()) if part]
    else:
        raw = [str(part) for part in tickers]
    seen: list[str] = []
    for item in raw:
        symbol = validate_ticker(item)
        if symbol not in seen:
            seen.append(symbol)
    if not seen:
        raise FinvizServiceError(
            ErrorCode.INVALID_PARAMETER, "At least one ticker is required"
        )
    if len(seen) > limit:
        raise FinvizServiceError(
            ErrorCode.INVALID_PARAMETER,
            f"At most {limit} tickers per request (got {len(seen)})",
            limit=limit,
        )
    return seen


def validate_filters(filters: str | None) -> str:
    """Validate a finviz screener filter expression (``cap_smallover,sec_technology``)."""
    if not filters:
        return ""
    clean = filters.strip().lower()
    if not clean:
        return ""
    for token in re.split(r"[,|]", clean):
        if not token:
            continue
        if not _FILTER_RE.match(token):
            raise FinvizServiceError(
                ErrorCode.INVALID_PARAMETER,
                f"Invalid screener filter {token!r}: use keys from finviz_screener_filters "
                "(letters, digits and underscores, e.g. 'cap_smallover')",
                filter=token,
            )
    return clean


def validate_order(order: str | None, default: str = "-change") -> str:
    """Validate a screener sort order such as ``-change`` (descending)."""
    if not order:
        return default
    clean = order.strip()
    if not _ORDER_RE.match(clean):
        raise FinvizServiceError(
            ErrorCode.INVALID_PARAMETER,
            f"Invalid sort order {order!r}: use a column key with an optional leading '-'",
            order=order,
        )
    return clean


def validate_view(view: str) -> str:
    """Validate the screener view id (111..171, 152 = full custom column set)."""
    clean = str(view).strip()
    if clean not in SCREENER_VIEWS:
        raise FinvizServiceError(
            ErrorCode.INVALID_PARAMETER,
            f"Invalid view {view!r}; expected one of {', '.join(sorted(SCREENER_VIEWS))}",
            view=view,
            allowed=sorted(SCREENER_VIEWS),
        )
    return clean


def validate_period(period: str) -> str:
    clean = (period or "d").strip().lower()
    if clean not in CHART_PERIODS:
        raise FinvizServiceError(
            ErrorCode.INVALID_PARAMETER,
            f"Invalid period {period!r}; expected d (daily), w (weekly) or m (monthly)",
            period=period,
            allowed=sorted(CHART_PERIODS),
        )
    return clean


def validate_chart_type(chart_type: str) -> str:
    clean = (chart_type or "c").strip().lower()
    if clean not in CHART_TYPES:
        raise FinvizServiceError(
            ErrorCode.INVALID_PARAMETER,
            f"Invalid chart type {chart_type!r}; expected c (candle) or l (line)",
            chart_type=chart_type,
            allowed=sorted(CHART_TYPES),
        )
    return clean


def validate_scale(scale: str) -> str:
    clean = (scale or "l").strip().lower()
    if clean not in CHART_SCALES:
        raise FinvizServiceError(
            ErrorCode.INVALID_PARAMETER,
            f"Invalid scale {scale!r}; expected l (linear) or log (logarithmic)",
            scale=scale,
            allowed=sorted(CHART_SCALES),
        )
    return clean


def clamp_int(value: int, *, low: int, high: int, name: str) -> int:
    """Coerce *value* into ``[low, high]``; non-numeric input is a hard error."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise FinvizServiceError(
            ErrorCode.INVALID_PARAMETER, f"{name} must be an integer", **{name: value}
        ) from None
    return max(low, min(parsed, high))


def validate_columns(columns: str | None) -> str:
    """Validate a screener column-count selector (``c=1,2,3``).

    Finviz's ``c`` parameter is a *count-like* selector: the server returns the
    first N optional columns in a fixed order, so passing ``c=0,1,2`` and
    ``c=0,1,2,3,4`` yields different column sets. Anything non-numeric is
    rejected so a caller cannot smuggle an arbitrary query fragment through.
    """
    if columns is None or str(columns).strip() == "":
        return ""
    clean = str(columns).strip()
    if not re.match(r"^\d{1,2}(,\d{1,2}){0,79}$", clean):
        raise FinvizServiceError(
            ErrorCode.INVALID_PARAMETER,
            "columns must be a comma-separated list of small integers, e.g. '0,1,2,3'",
            columns=columns,
        )
    return clean
