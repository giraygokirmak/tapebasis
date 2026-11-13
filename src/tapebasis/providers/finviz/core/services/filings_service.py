"""
Filings service, SEC filings from ``/api/quote/filings``.

This is the one fully structured per-ticker endpoint finviz exposes without
authentication. Parameters (reverse-engineered from the quote page's React
chunk ``main.v1``):

=============  ==========================================================
``t``          ticker
``page``       1-based page number
``pageSize``   rows per page (server default 30)
``o``          sort, default ``-filingDate``
``f``          form filter, e.g. ``10-K`` or ``8-K,6-K``
=============  ==========================================================

Response::

    {"items": [ {form, filingDate, reportDate, accessionNumber, description,
                 document, filing, primaryDocumentUrl, filingRootUrl,
                 interactive} ],
     "page": 1, "pageSize": 30, "totalItemsCount": 206, "totalPages": 7}
"""
from __future__ import annotations

import re
from typing import Any

from tapebasis.providers.finviz.core.errors import ErrorCode, FinvizServiceError
from tapebasis.providers.finviz.core.services import finviz_client
from tapebasis.providers.finviz.core.utils.validators import validate_ticker

_FORM_RE = re.compile(r"^[A-Za-z0-9\-/]{1,16}$")
_SORTS = {"-filingDate", "filingDate", "-reportDate", "reportDate", "form", "-form"}


def validate_form_filter(forms: str | None) -> str:
    """Validate a comma-separated SEC form filter (``8-K,6-K,10-Q``)."""
    if not forms:
        return ""
    tokens = [token.strip().upper() for token in forms.split(",") if token.strip()]
    for token in tokens:
        if not _FORM_RE.match(token):
            raise FinvizServiceError(
                ErrorCode.INVALID_PARAMETER,
                f"Invalid SEC form {token!r} (expected something like 10-K, 8-K, 6-K)",
                form=token,
            )
    return ",".join(tokens)


async def get_filings(
    ticker: str,
    page: int = 1,
    page_size: int = 30,
    forms: str | None = None,
    sort: str = "-filingDate",
) -> dict[str, Any]:
    """Return one page of SEC filings for a ticker.

    Args:
        ticker: Symbol to fetch.
        page: 1-based page index.
        page_size: Rows per page (1-100).
        forms: Optional SEC form filter, comma separated.
        sort: One of ``-filingDate`` (default), ``filingDate``, ``-reportDate``,
            ``reportDate``, ``form``, ``-form``.

    Returns:
        The upstream envelope plus a normalised ``filings`` list and
        ``has_more`` convenience flag.

    Raises:
        FinvizServiceError: ``NO_DATA`` when the ticker has no filings,
            ``INVALID_PARAMETER`` for an unsupported sort or page.
    """
    symbol = validate_ticker(ticker)
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 100))
    if sort not in _SORTS:
        raise FinvizServiceError(
            ErrorCode.INVALID_PARAMETER,
            f"Invalid sort {sort!r}; expected one of {', '.join(sorted(_SORTS))}",
            sort=sort,
            allowed=sorted(_SORTS),
        )

    url = (
        f"{finviz_client.BASE_URL}/api/quote/filings?t={symbol}"
        f"&page={page}&pageSize={page_size}&o={sort}"
    )
    form_filter = validate_form_filter(forms)
    if form_filter:
        url += f"&f={form_filter}"

    payload = await finviz_client.fetch_json(url)
    if not isinstance(payload, dict) or "items" not in payload:
        raise FinvizServiceError(
            ErrorCode.PARSE_ERROR,
            "Unexpected filings payload shape from finviz.com",
            ticker=symbol,
        )

    items = payload.get("items") or []
    if not items:
        raise FinvizServiceError(
            ErrorCode.NO_DATA,
            f"No SEC filings matched for {symbol}"
            + (f" with form filter {form_filter}" if form_filter else ""),
            ticker=symbol,
            page=page,
            forms=form_filter or None,
        )

    total_pages = payload.get("totalPages") or 0
    return {
        "ticker": symbol,
        "filings": items,
        "count": len(items),
        "page": payload.get("page", page),
        "page_size": payload.get("pageSize", page_size),
        "total_items": payload.get("totalItemsCount"),
        "total_pages": total_pages,
        "has_more": bool(total_pages) and payload.get("page", page) < total_pages,
        "source": url,
    }
