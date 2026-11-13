"""
Ownership services, insider trades, insider activity chart, institutional holders.

Three distinct data sources share this module because they all answer "who owns
this, and what did they do":

1. ``insidertrading`` table on ``/stock?t={t}``     : the Form-4 row list.
2. ``insider-init-data-0`` JSON island              : 12 monthly buckets of
   aggregated buy/sell value used to draw the mini bar chart. Note the table and
   the island disagree in practice (the table shows the Sep-30 buy as
   ``$313,225`` while the island's latest bucket can still be zero): they are
   refreshed on different schedules, so both are returned with their own
   provenance instead of being merged.
3. ``institutional-ownership-init-data-0`` JSON island, manager + fund
   positions with ``percOwnership`` expressed as a *fraction* (0.277 = 27.7%).

Elite gating: the full institutional-ownership breakdown (13F history, holder
changes) lives behind ``/api/compare-perf/*`` and ``/api/quote/ownership``,
which redirect to ``/elite``. Those are reported as ``ELITE_ONLY`` rather than
faked.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tapebasis.providers.finviz.core.errors import ErrorCode, FinvizServiceError
from tapebasis.providers.finviz.core.services import finviz_client
from tapebasis.providers.finviz.core.services.html_utils import (
    extract_script_json,
    parse_insider_rows,
    parse_quote_header,
)
from tapebasis.providers.finviz.core.utils.validators import validate_ticker


def _month_label(millis: Any) -> str | None:
    if not isinstance(millis, (int, float)):
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).strftime("%Y-%m")


async def get_insider_trading(ticker: str, limit: int = 40) -> dict[str, Any]:
    """Recent insider Form-4 transactions plus the monthly buy/sell aggregates.

    Args:
        ticker: Symbol to fetch.
        limit: Maximum table rows to return (1-200).

    Returns:
        ``{"ticker", "transactions": [...], "activity": [...], "summary": {...}}``
        where ``summary`` aggregates the table rows (total buys/sells, insider
        names involved) and ``activity`` is the monthly chart series.

    Raises:
        FinvizServiceError: ``NO_DATA`` when the ticker has neither rows nor a
            chart series (common for foreign private issuers filing 6-K only).
    """
    symbol = validate_ticker(ticker)
    limit = max(1, min(int(limit), 200))

    html = await finviz_client.fetch_html(
        f"{finviz_client.BASE_URL}/stock?t={symbol}&ta=1&p=d"
    )
    header = parse_quote_header(html)
    rows = parse_insider_rows(html)
    raw_activity = extract_script_json(html, "insider-init-data-0") or []

    activity = []
    if isinstance(raw_activity, list):
        for bucket in raw_activity:
            if not isinstance(bucket, dict):
                continue
            buys = bucket.get("buyAggregated") or 0
            sales = bucket.get("saleAggregated") or 0
            activity.append(
                {
                    "month": _month_label(bucket.get("date")),
                    "buy_count": bucket.get("buyTransactionCount") or 0,
                    "buy_value_usd": round(buys, 2),
                    "sale_count": bucket.get("saleTransactionCount") or 0,
                    "sale_value_usd": round(sales, 2),
                    "net_value_usd": round(buys - sales, 2),
                }
            )

    if not rows and not activity:
        raise FinvizServiceError(
            ErrorCode.NO_DATA,
            f"finviz.com reports no insider transactions for {symbol}",
            ticker=symbol,
        )

    buys = [r for r in rows if (r.get("transaction") or "").lower().startswith("buy")]
    sales = [r for r in rows if (r.get("transaction") or "").lower().startswith("sale")]

    return {
        "ticker": symbol,
        "company": header.get("company"),
        "transactions": rows[:limit],
        "count": min(len(rows), limit),
        "summary": {
            "rows_total": len(rows),
            "buys": len(buys),
            "sales": len(sales),
            "insiders": sorted({r["insider"] for r in rows if r.get("insider")}),
            "latest_trade_date": rows[0]["date"] if rows else None,
        },
        "activity": activity,
        "activity_total_buy_usd": round(
            sum(a["buy_value_usd"] for a in activity), 2
        ),
        "activity_total_sale_usd": round(
            sum(a["sale_value_usd"] for a in activity), 2
        ),
        "source": f"{finviz_client.BASE_URL}/stock?t={symbol}",
    }


async def get_institutional_ownership(ticker: str, limit: int = 20) -> dict[str, Any]:
    """Manager and fund positions from the ``institutional-ownership`` island.

    ``percOwnership`` arrives as a fraction; it is converted to a percentage
    here and both forms are returned so nothing is lost to rounding surprises.

    Raises:
        FinvizServiceError: ``NO_DATA`` when the island is absent or empty.
    """
    symbol = validate_ticker(ticker)
    limit = max(1, min(int(limit), 200))

    html = await finviz_client.fetch_html(
        f"{finviz_client.BASE_URL}/stock?t={symbol}&ta=1&p=d"
    )
    data = extract_script_json(html, "institutional-ownership-init-data-0")
    if not isinstance(data, dict):
        raise FinvizServiceError(
            ErrorCode.NO_DATA,
            f"No institutional ownership data for {symbol}",
            ticker=symbol,
        )

    def _rows(items: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in (items or [])[:limit]:
            if not isinstance(item, dict):
                continue
            fraction = item.get("percOwnership")
            out.append(
                {
                    "investor_id": item.get("investorId"),
                    "name": item.get("name"),
                    "slug": item.get("slug"),
                    "ownership_fraction": fraction,
                    "ownership_percent": round(fraction * 100, 4)
                    if isinstance(fraction, (int, float))
                    else None,
                    "profile_url": f"https://finviz.com/investor/{item.get('slug')}"
                    if item.get("slug")
                    else None,
                }
            )
        return out

    managers = _rows(data.get("managersOwnership"))
    funds = _rows(data.get("fundsOwnership"))
    if not managers and not funds:
        raise FinvizServiceError(
            ErrorCode.NO_DATA,
            f"No institutional holders listed for {symbol}",
            ticker=symbol,
        )

    snapshot = (await _snapshot_hint(symbol)) or {}
    return {
        "ticker": symbol,
        "managers": managers,
        "funds": funds,
        "count": len(managers) + len(funds),
        "institutional_ownership_percent": snapshot.get("Institutional Own"),
        "insider_ownership_percent": snapshot.get("Insider Own"),
        "note": "percOwnership is a fraction of shares outstanding; "
        "the percent field is that fraction ×100.",
        "source": f"{finviz_client.BASE_URL}/stock?t={symbol}",
    }


async def _snapshot_hint(ticker: str) -> dict[str, str] | None:
    """Cheap read of the two ownership rows from the snapshot table.

    Reuses the cached page fetch, so it costs nothing when the caller already
    asked for the quote in the same minute.
    """
    from tapebasis.providers.finviz.core.services.html_utils import parse_snapshot

    try:
        html = await finviz_client.fetch_html(
            f"{finviz_client.BASE_URL}/stock?t={ticker}&ta=1&p=d"
        )
        return parse_snapshot(html)["fields"]
    except Exception:  # pragma: no cover - the snapshot is a nice-to-have
        return None
