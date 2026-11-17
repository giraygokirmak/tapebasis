"""
Screener service, ``/screener/stocks`` server-rendered island.

Finviz's screener was rebuilt as a React island: the HTML document ships a
``<script type="application/json" data-ssr-props="ssr-island-1">`` payload with
the *entire* result page already resolved server-side. No XHR is needed, which
is why this server reads the island instead of driving an internal API (there is
no ``/api/screener`` route; the front end only calls
``/api/screener-chart-settings/*`` and ``/api/screener-filters``).

Island shape::

    {"url", "screenerType", "today", "settings", "filters", "presets",
     "portfolios", "selectedColumns", "flags", "ads",
     "data": {"rows": [{"text": {...}, "numbers": {...}}],
              "totalCount": 3439, "firstRow": 0, "pageSize": 20}}

Query parameters that matter
----------------------------
``t``  comma-separated explicit tickers (overrides ``f`` sorting rules)
``f``  filter expression, e.g. ``cap_smallover,sec_technology,sh_avgvol_o500``
``o``  sort column with optional ``-`` for descending (``-change``)
``r``  0-based offset of the first row (``r=21`` → page 2)
``c``  column selector: finviz returns the first N optional columns in its own
       fixed order, so ``c=0,1,...,10`` yields the 11 default columns and longer
       lists progressively add PE/PEG/PS/.../RSI/recom.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tapebasis.providers.finviz.core.errors import ErrorCode, FinvizServiceError
from tapebasis.providers.finviz.core.services import finviz_client
from tapebasis.providers.finviz.core.services.html_utils import extract_ssr_island
from tapebasis.providers.finviz.core.utils.validators import (
    validate_columns,
    validate_filters,
    validate_order,
    validate_tickers,
    validate_view,
)

#: finviz caps the island at 20 rows per page regardless of what you ask for.
ROWS_PER_PAGE = 20


def _build_url(
    *, tickers: str | None, filters: str, order: str, view: str, offset: int, columns: str
) -> str:
    url = f"{finviz_client.BASE_URL}/screener/stocks?v={view}"
    if tickers:
        url += f"&t={tickers}"
    if filters:
        url += f"&f={filters}"
    url += f"&o={order}"
    if offset:
        url += f"&r={offset}"
    if columns:
        url += f"&c={columns}"
    return url


def _flatten_row(row: dict[str, Any]) -> dict[str, Any]:
    """Merge the island's ``text`` and ``numbers`` halves into one flat record."""
    flat: dict[str, Any] = {}
    for key, value in (row.get("text") or {}).items():
        if key in {"type", "cardIndustry"}:
            continue
        flat[key] = value
    for key, value in (row.get("numbers") or {}).items():
        if key == "order":
            continue
        flat[key] = value
    return flat


async def screen(
    tickers: str | None = None,
    filters: str | None = None,
    order: str = "-change",
    view: str = "111",
    page: int = 1,
    columns: str | None = None,
) -> dict[str, Any]:
    """Run one screener page.

    Args:
        tickers: Optional explicit ticker list (comma separated).
        filters: Optional filter expression (keys from ``finviz_screener_filters``).
        order: Sort column, ``-`` prefix for descending.
        view: View id (111 overview … 171 custom).
        page: 1-based page number; each page is 20 rows upstream.
        columns: Column selector string, e.g. ``"0,1,2,3"``. Longer lists add
            PE, PEG, PS, PB, ... up to 67 numeric fields.

    Returns:
        ``{"rows", "count", "page", "page_size", "total_count", "total_pages",
        "selected_columns"}`` plus filters echoed back for reproducibility.

    Raises:
        FinvizServiceError: ``NO_DATA`` when the screen matched zero tickers.
    """
    order = validate_order(order)
    view = validate_view(view)
    filter_expr = validate_filters(filters)
    column_expr = validate_columns(columns)
    page = max(1, int(page))
    offset = (page - 1) * ROWS_PER_PAGE

    ticker_expr = None
    if tickers:
        ticker_expr = ",".join(validate_tickers(tickers))

    url = _build_url(
        tickers=ticker_expr,
        filters=filter_expr,
        order=order,
        view=view,
        offset=offset,
        columns=column_expr,
    )
    html = await finviz_client.fetch_html(url, elite_check=False)
    island = extract_ssr_island(html)
    if not isinstance(island, dict) or "data" not in island:
        raise FinvizServiceError(
            ErrorCode.PARSE_ERROR,
            "Screener island not found in the returned document "
            "(finviz may have changed its markup)",
            url=url,
        )

    data = island.get("data") or {}
    rows = [_flatten_row(row) for row in (data.get("rows") or [])]
    total = data.get("totalCount") or 0

    if not rows:
        raise FinvizServiceError(
            ErrorCode.NO_DATA,
            "Screener returned zero rows: the filter combination matches nothing"
            if filter_expr
            else "Screener returned zero rows",
            filters=filter_expr or None,
            page=page,
        )

    total_pages = (total + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE if total else 0
    return {
        "rows": rows,
        "count": len(rows),
        "page": page,
        "page_size": data.get("pageSize", ROWS_PER_PAGE),
        "first_row": data.get("firstRow", offset),
        "total_count": total,
        "total_pages": total_pages,
        "has_more": page < total_pages if total_pages else False,
        "selected_columns": island.get("selectedColumns") or [],
        "applied": {
            "tickers": ticker_expr,
            "filters": filter_expr or None,
            "order": order,
            "view": view,
            "columns": column_expr or None,
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": url,
    }


async def get_screener_filters() -> dict[str, Any]:
    """Return the machine-readable filter catalogue (``/api/screener-filters``).

    The payload is large (~150 KB) and changes rarely, so it is cached for an
    hour and trimmed to the fields a caller needs to construct a screen:
    ``key``, ``tab``, ``uiType``, ``title``, ``screenerTypes`` and ``options``.

    Raises:
        FinvizServiceError: ``PARSE_ERROR`` if the catalogue shape changes.
    """
    url = f"{finviz_client.BASE_URL}/api/screener-filters?type=stocks"
    payload = await finviz_client.fetch_json(url, ttl=3600)
    if not isinstance(payload, dict) or "filters" not in payload:
        raise FinvizServiceError(
            ErrorCode.PARSE_ERROR, "Unexpected screener filter catalogue shape", url=url
        )

    trimmed = []
    for item in payload.get("filters") or []:
        if not isinstance(item, dict):
            continue
        options = item.get("options") or []
        key = item.get("key")

        def _filter_value(opt_value: str) -> str:
            """Build the screener token a caller actually passes to ``f=``.

            The catalogue splits a filter into a ``key`` and option ``value``s;
            finviz accepts their concatenation (``sec`` + ``technology`` →
            ``sec_technology``). Options that already carry the key prefix, or
            that are the "Any" (empty) entry, are passed through unchanged.
            """
            if not opt_value or not key:
                return opt_value or ""
            if opt_value.startswith(f"{key}_") or opt_value.startswith("-"):
                return opt_value
            return f"{key}_{opt_value}"

        trimmed.append(
            {
                "key": key,
                "tab": item.get("tab"),
                "uiType": item.get("uiType"),
                "title": item.get("title"),
                "screenerTypes": item.get("screenerTypes"),
                "options": [
                    {
                        "value": opt.get("value"),
                        "filter": _filter_value(opt.get("value") or ""),
                        "label": opt.get("label"),
                    }
                    for opt in options
                    if isinstance(opt, dict)
                ][:120],
                "option_count": len(options),
            }
        )

    return {
        "filters": trimmed,
        "count": len(trimmed),
        "tab_order": payload.get("tabOrder"),
        "usage": "Pass a token from options[].filter to finviz_screener(filters=...). "
        "Combine with ',' (AND) or '|' (OR) and prefix '-' to exclude.",
        "source": url,
    }


async def get_screener_presets() -> list[str]:
    """Return the view ids this server accepts, with their labels."""
    from tapebasis.providers.finviz.core.utils.validators import SCREENER_VIEWS

    return [f"{key}={label}" for key, label in sorted(SCREENER_VIEWS.items())]
