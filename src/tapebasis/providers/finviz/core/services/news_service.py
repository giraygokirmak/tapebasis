"""
News service, headlines from ``/api/news/quote/{ticker}``.

That endpoint returns ``{"html": "<table rows>", "timestamp": "..."}``: the
server renders the same 100-row table into JSON for the React island. Parsing
the rows (rather than the page's ``table.news-table``) is preferable because:

* it is one small request instead of a 240 KB document,
* it always carries the full 100-row window regardless of what the page
  paginated to,
* the payload includes the server-side render timestamp.

Each row carries the day-of-headline reaction and, when the headline broke
after the close, the next session's reaction as a second labelled span.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from tapebasis.providers.finviz.core.errors import ErrorCode, FinvizServiceError
from tapebasis.providers.finviz.core.services import finviz_client
from tapebasis.providers.finviz.core.services.html_utils import parse_news_rows
from tapebasis.providers.finviz.core.utils.validators import validate_ticker

#: News changes fast; a 60s cache keeps a chatty agent from hammering the API
#: while still surfacing a fresh headline within a minute.
NEWS_TTL = float(os.environ.get("FINVIZ_NEWS_TTL", "60"))


async def get_news(
    ticker: str,
    limit: int = 30,
    *,
    include_reactions: bool = True,
) -> dict[str, Any]:
    """Return the latest headlines for one ticker.

    Args:
        ticker: Symbol to fetch (e.g. ``VCIG``).
        limit: Maximum rows to return (1-100). Rows are newest-first.
        include_reactions: Keep the day / next-day percentage reactions.

    Returns:
        ``{"ticker", "news": [...], "count", "as_of"}`` where each item has
        ``datetime``, ``headline``, ``source``, ``url`` and the two reaction
        fields.

    Raises:
        FinvizServiceError: ``NO_DATA`` when the API returns no parseable rows
            (finviz does this for tickers with no coverage), or ``PARSE_ERROR``
            when the payload is not the documented ``{"html": ...}`` shape.
    """
    symbol = validate_ticker(ticker)
    limit = max(1, min(int(limit), 100))
    url = f"{finviz_client.BASE_URL}/api/news/quote/{symbol}"

    payload = await finviz_client.fetch_json(url)

    if isinstance(payload, dict) and "html" in payload:
        markup = payload.get("html") or ""
        as_of = payload.get("timestamp")
    elif isinstance(payload, str):  # defensive: some edges return bare HTML
        markup = payload
        as_of = None
    else:
        raise FinvizServiceError(
            ErrorCode.PARSE_ERROR,
            "Unexpected news payload shape from finviz.com",
            ticker=symbol,
            keys=list(payload)[:10] if isinstance(payload, dict) else type(payload).__name__,
        )

    rows = parse_news_rows(markup)
    if not rows:
        raise FinvizServiceError(
            ErrorCode.NO_DATA,
            f"finviz.com has no recent headlines for {symbol}",
            ticker=symbol,
        )

    if not include_reactions:
        for row in rows:
            row.pop("reaction_day_percent", None)
            row.pop("reaction_next_day_percent", None)

    return {
        "ticker": symbol,
        "news": rows[:limit],
        "count": min(len(rows), limit),
        "total_available": len(rows),
        "as_of": as_of or datetime.now(timezone.utc).isoformat(),
        "source": url,
    }
