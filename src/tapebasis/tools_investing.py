"""Investing.com's direct quote tool with explicit single-source provenance.

The ordinary market tools include Investing only after exact native identity
verification. This direct tool shares those accessors but asks no other provider.
Analyst targets belong to Investing's forecast population, and technical labels
belong to its daily model; they are never promoted to cross-provider consensus.
"""
from __future__ import annotations

from typing import Any

from . import investing_access
from .health import MONITOR
from .providers_state import (
    DataProvider,
    NoDataError,
    ProviderError,
    error_code,
)
from .reconcile import Attempt, Pair, field_source, finalize
from .symbols import resolve


async def investing_quote(symbol: str, exchange: str = "") -> dict[str, Any]:
    """Read one exact Investing.com equity or ETF, explicitly single-source.

    ``exchange`` can disambiguate a symbol listed on multiple venues (for
    example ``NASDAQ`` or ``NYSE``). Otherwise only an unambiguous primary
    listing is accepted. Instrument id, symbol, exchange, currency and class must
    agree between native search and the quote page. This tool never guesses an
    ``/equities/`` slug, substitutes another listing, or substitutes another
    provider for a failed Investing request.

    Investing's ``lastClose`` is not mapped to previous close because its
    baseline meaning is unverified. Explicitly unsupported previous-close data
    is visible in ``investing_previous_close_excluded``. Analyst counts remain a
    separate Investing population and daily technical verdicts remain a separate
    Investing model, never Tapebasis ``technical_analysis`` or a combined count.

    Args:
        symbol: Equity or ETF ticker, including share-class spellings such as
            ``BRK.B``. ``EXCHANGE:TICKER`` is accepted as an explicit venue.
        exchange: Optional exact exchange constraint, e.g. ``NASDAQ``.

    Returns:
        Envelope labelled ``INVESTING`` / ``SINGLE_SOURCE`` whose ``data``
        carries the verified regular or extended quote, timestamps and
        provider-only analyst and technical extras, all with ``INVESTING``
        per-field provenance. A miss or provider failure returns ``NONE`` with
        the typed error instead of borrowing a number from another provider.
    """
    MONITOR.ensure_started()
    query = f"{exchange}:{symbol}" if exchange and ":" not in symbol else symbol
    source = "Investing.com native instrument search"
    resolution = None
    try:
        resolution = await resolve(query, investing_access.PROVIDER)
        resolution.require()
        data, source = await investing_access.quote_with_resolution(resolution)
    except Exception as exc:  # noqa: BLE001 - preserve the provider boundary
        if isinstance(exc, (NoDataError, ProviderError)):
            code = "NO_DATA" if isinstance(exc, NoDataError) else exc.code
            message = exc.message
        else:
            code = error_code(exc)
            message = f"{type(exc).__name__}: {exc}"
        attempt = Attempt(
            investing_access.PROVIDER,
            False,
            error={
                "provider": investing_access.PROVIDER,
                "code": code,
                "message": message,
            },
        )
        return finalize(
            Pair({investing_access.PROVIDER: attempt}),
            data=None,
            provider=DataProvider.NONE,
            answered=[],
            comparisons=[],
            fields={},
            sources={investing_access.PROVIDER: source},
            health_warn=MONITOR.warnings_for([investing_access.PROVIDER]),
            extra={
                "symbol": symbol,
                "resolution": resolution.to_dict() if resolution else None,
                "cross_checked": False,
                "_empty_data_none": True,
            },
        )
    fields = {
        key: field_source(
            investing_access.PROVIDER, (), None,
            supplied=[investing_access.PROVIDER],
        )
        for key in data
    }
    pair = Pair({
        investing_access.PROVIDER: Attempt(investing_access.PROVIDER, True, data),
    })
    return finalize(
        pair,
        data=data,
        provider=DataProvider.INVESTING,
        answered=[investing_access.PROVIDER],
        comparisons=[],
        fields=fields,
        sources={investing_access.PROVIDER: source},
        health_warn=MONITOR.warnings_for([investing_access.PROVIDER]),
        extra={
            "symbol": data.get("symbol"),
            "resolution": resolution.to_dict(),
            "cross_checked": False,
        },
    )


_TOOLS = ((
    investing_quote,
    "Investing.com: exact native instrument quote and provider-only extras",
),)


def register(mcp) -> int:
    """Register the direct Investing tool and return the number added."""
    for fn, title in _TOOLS:
        mcp.add_tool(fn, name=fn.__name__, title=title, description=fn.__doc__)
    return len(_TOOLS)
