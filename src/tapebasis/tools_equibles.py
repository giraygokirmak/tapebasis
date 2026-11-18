"""Separate Equibles tools for fundamental data and licensed positioning.

Every successful response is explicitly ``EQUIBLES`` and single-source. Raw
REST response bodies stay in isolated named datasets: no value is merged with
another provider. ``attribution``, ``as_of`` and ``reporting_delay`` accompany
both successful and failed responses, because an error must not turn into a
silent license or freshness downgrade.

Analyst estimates are kept as source-labelled observations without turning
them into a Tapebasis rating. Source-labelled provider analytics in the grouped
REST families remain provider claims, not conclusions synthesized here.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Callable, Coroutine, Mapping

from . import eq_access
from .providers_state import NoDataError, error_code
from .equibles_surface import response as surface_response

EQUIBLES = "EQUIBLES"
_CORO = Callable[[], Coroutine[Any, Any, Any]]


def _response(
    tool: str,
    symbol: str,
    *,
    datasets: Mapping[str, Any] | None = None,
    paths: Mapping[str, str] | None = None,
    errors: list[dict[str, Any]] | None = None,
    freshness: Mapping[str, Any] | None = None,
    dataset_names: tuple[str, ...] | None = None,
    params_applied: Mapping[str, Any] | None = None,
    adjustments: list[str] | None = None,
) -> dict[str, Any]:
    """Build one Equibles response with actual key and plan access state."""
    return surface_response(
        tool, {"symbol": symbol}, datasets=datasets, paths=paths, errors=errors,
        freshness=freshness, dataset_names=dataset_names, params_applied=params_applied,
        adjustments=adjustments,
    )


async def _fetch(
    symbol: str,
    tool: str,
    blocks: Mapping[str, tuple[str, Mapping[str, Any] | None]],
    *,
    adjustments: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch a fixed set of REST blocks concurrently, preserving partial errors.

    The fixed fan-out spends one request per named block. There is no hidden
    pagination, alternative provider, restricted-score request or retry loop.
    """
    ticker = eq_access.ticker_for(symbol)
    params_applied = {name: dict(params or {}) for name, (_, params) in blocks.items()}
    names = tuple(blocks)
    coroutines = []
    for name in names:
        fragment, params = blocks[name]
        coroutines.append(eq_access.get(fragment, params=params))

    async def guard(name: str, operation: _CORO) -> Any:
        """Return one dataset or its sanitized error without cancelling peers."""
        try:
            payload = await operation
            if not isinstance(payload, dict):
                raise ValueError("non-object provider response")
            # A 200 with no provider rows is still a successful, empty dataset.
            # It never triggers another provider or a fabricated fill.
            return {"payload": payload}
        except Exception as exc:  # noqa: BLE001 - error is part of the response contract
            code = "NO_DATA" if isinstance(exc, NoDataError) else error_code(exc)
            message = getattr(exc, "message", None) or type(exc).__name__
            return {"error": {"provider": EQUIBLES, "code": code, "message": message, "dataset": name}}

    results = await asyncio.gather(*(guard(name, coro) for name, coro in zip(names, coroutines)))
    payloads = {
        name: result["payload"] for name, result in zip(names, results) if "payload" in result
    }
    errors = [result["error"] for result in results if "error" in result]
    return _response(
        tool, ticker, datasets=payloads,
        paths={name: f"/{blocks[name][0]}" for name in names}, errors=errors,
        dataset_names=names, params_applied=params_applied, adjustments=adjustments,
    )


def _bounded(value: int, low: int, high: int, name: str, adjustments: list[str]) -> int:
    """Clamp a page bound and record the adjustment for the response warnings."""
    applied = max(low, min(high, value))
    if applied != value:
        adjustments.append(f"{name} was clamped from {value} to {applied}")
    return applied


def _date(value: str | None, name: str) -> str | None:
    """Validate an optional ISO date filter and return its unchanged text."""
    if value is None:
        return None
    text = str(value).strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD") from exc
    return text


def _snapshot_id(value: str | None) -> str | None:
    """Validate an optional snapshot UUID filter before any request is made."""
    if value is None:
        return None
    text = str(value).strip()
    try:
        uuid.UUID(text)
    except ValueError as exc:
        raise ValueError("snapshot_id must be a UUID returned in snapshots") from exc
    return text


def _period(year: int | None, period: str | None) -> dict[str, Any] | None:
    """Build one optional fiscal-period query without fetching all periods."""
    if period is not None and period.upper() not in {"FY", "Q1", "Q2", "Q3", "Q4"}:
        raise ValueError("period must be FY, Q1, Q2, Q3 or Q4")
    if year is None and period is None:
        return None
    return {"year": year, "period": period.upper() if period else None}


async def stock_fundamentals(
    symbol: str,
    statement: str = "income",
    year: int | None = None,
    period: str | None = None,
    include_segments: bool = True,
    include_debt: bool = True,
    include_guidance: bool = True,
) -> dict[str, Any]:
    """Read Equibles company identity, SEC fundamentals and guidance separately.

    Args:
        symbol: US-listed ticker; share classes may use a dot or dash.
        statement: ``income``, ``balance`` or ``cashflow``.
        year: Optional fiscal year for the one statement read.
        period: Optional ``FY``, ``Q1``, ``Q2``, ``Q3`` or ``Q4``.
        include_segments: Fetch annual revenue breakdown when true.
        include_debt: Fetch reported debt, instruments and covenant coverage when true.
        include_guidance: Fetch management guidance and reported actuals when true.

    Returns:
        Envelope with isolated ``profile``, ``financial_statement`` and the
        selected ``revenue_breakdown``, ``debt_profile`` and ``guidance`` blocks.
        No Equibles value is combined with Finviz, TradingView or Yahoo.
    """
    normalized = statement.strip().lower()
    if normalized not in {"income", "balance", "cashflow"}:
        raise ValueError("statement must be income, balance or cashflow")
    ticker = eq_access.ticker_for(symbol)
    blocks: dict[str, tuple[str, Mapping[str, Any] | None]] = {
        "profile": (f"stocks/{ticker}", None),
        "financial_statement": (
            f"stocks/{ticker}/financial-statements/{normalized}",
            _period(year, period),
        ),
    }
    if include_segments:
        blocks["revenue_breakdown"] = (f"stocks/{ticker}/revenue-breakdown", None)
    if include_debt:
        blocks["debt_profile"] = (
            f"stocks/{ticker}/debt-profile",
            {"instrumentLimit": 25, "reportedTotalLimit": 25},
        )
    if include_guidance:
        blocks["guidance"] = (f"stocks/{ticker}/guidance", {"maxReleases": 20})
    return await _fetch(ticker, "stock_fundamentals", blocks)


async def stock_analyst_estimates(
    symbol: str,
    metric: str | None = None,
    period: str | None = None,
    dimensions: str | None = None,
    snapshot_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Read verified analyst estimates and snapshots without adding a rating.

    Source metric, period, dimensions, unit, basis, statistic, analyst and
    numeric string remain as supplied by Equibles. Revision observations are
    not recast into a score or mixed with another provider's target population.

    Args:
        symbol: US-listed ticker.
        metric: Optional exact upstream metric label.
        period: Optional exact upstream period label.
        dimensions: Optional exact upstream dimension labels.
        snapshot_id: Optional snapshot identifier returned by a previous call.
        limit: Observation page size, clamped to 1 through 100.
        offset: Zero-based observation offset, clamped to 0 through 100000.

    Returns:
        Envelope containing the complete Equibles ``analyst_estimates`` block.
    """
    ticker = eq_access.ticker_for(symbol)
    adjustments: list[str] = []
    for text, name, maximum in (
        (metric, "metric", 512), (period, "period", 256), (dimensions, "dimensions", 1024),
    ):
        if text is not None and len(text) > maximum:
            raise ValueError(f"{name} must be at most {maximum} characters")
    params = {
        "metric": metric,
        "period": period,
        "dimensions": dimensions,
        "snapshotId": _snapshot_id(snapshot_id),
        "limit": _bounded(limit, 1, 100, "limit", adjustments),
        "offset": _bounded(offset, 0, 100000, "offset", adjustments),
    }
    return await _fetch(
        ticker, "stock_analyst_estimates",
        {"analyst_estimates": (f"stocks/{ticker}/analyst-estimates", params)},
        adjustments=adjustments,
    )


async def stock_ownership_flows(
    symbol: str,
    limit: int = 25,
    periods: int = 8,
    include_insiders: bool = True,
    include_fund_owners: bool = True,
) -> dict[str, Any]:
    """Read separate 13F, N-PORT, insider and Form 144 ownership observations.

    Args:
        symbol: US-listed stock or ETF ticker.
        limit: Cap for each activity, fund, insider and proposed-sale page,
            clamped to 1 through 500.
        periods: Number of 13F reporting periods, clamped to 1 through 500.
        include_insiders: Fetch filed insider transactions when true.
        include_fund_owners: Fetch current N-PORT fund positions when true.

    Returns:
        Envelope with 13F ownership and movement, N-PORT fund ownership, Form
        144 proposed sales, and optional insider activity in separate blocks.
    """
    ticker = eq_access.ticker_for(symbol)
    adjustments: list[str] = []
    capped = _bounded(limit, 1, 500, "limit", adjustments)
    blocks: dict[str, tuple[str, Mapping[str, Any] | None]] = {
        "institutional_ownership": (
            f"securities/{ticker}/institutional-ownership",
            {"periods": _bounded(periods, 1, 500, "periods", adjustments)},
        ),
        "institutional_activity": (
            f"securities/{ticker}/institutional-activity", {"limit": capped},
        ),
        "proposed_sales": (f"stocks/{ticker}/proposed-sales", {"limit": capped, "offset": 0}),
    }
    if include_insiders:
        blocks["insider_transactions"] = (
            f"stocks/{ticker}/insider-transactions", {"limit": capped, "offset": 0},
        )
    if include_fund_owners:
        blocks["fund_owners"] = (
            f"securities/{ticker}/fund-owners", {"limit": capped, "offset": 0},
        )
    return await _fetch(ticker, "stock_ownership_flows", blocks, adjustments=adjustments)


async def stock_short_positioning(
    symbol: str,
    limit: int = 30,
    start_date: str | None = None,
    end_date: str | None = None,
    include_fails_to_deliver: bool = True,
    include_off_exchange: bool = True,
) -> dict[str, Any]:
    """Read short, FTD and off-exchange history with an ordinary API key.

    An account that lacks a dataset receives an explicit provider error; no
    provider fallback or empty downgrade occurs.

    Args:
        symbol: US-listed stock or ETF ticker.
        limit: Rows per dataset, clamped to 1 through 500.
        start_date: Optional inclusive ISO date filter.
        end_date: Optional inclusive ISO date filter.
        include_fails_to_deliver: Fetch SEC fails-to-deliver balances when true.
        include_off_exchange: Fetch weekly FINRA ATS and OTC volume when true.

    Returns:
        Envelope with unchanged short-interest, short-volume and selected FTD
        and off-exchange datasets, each retaining its distinct reporting delay.
    """
    ticker = eq_access.ticker_for(symbol)
    adjustments: list[str] = []
    query = {
        "limit": _bounded(limit, 1, 500, "limit", adjustments), "offset": 0,
        "startDate": _date(start_date, "start_date"), "endDate": _date(end_date, "end_date"),
    }
    blocks: dict[str, tuple[str, Mapping[str, Any] | None]] = {
        "short_interest": (f"securities/{ticker}/short-interest", query),
        "short_volume": (f"securities/{ticker}/short-volume", query),
    }
    if include_fails_to_deliver:
        blocks["fails_to_deliver"] = (f"securities/{ticker}/fails-to-deliver", query)
    if include_off_exchange:
        blocks["off_exchange_volume"] = (f"securities/{ticker}/off-exchange-volume", query)
    return await _fetch(
        ticker, "stock_short_positioning", blocks, adjustments=adjustments,
    )


async def stock_options_analytics(
    symbol: str,
    expiration: str | None = None,
    max_expirations: int = 8,
) -> dict[str, Any]:
    """Read paid-plan option summary and term structure with an API key.

    Equibles requires Plus or Pro for option data. Max pain and expected move
    remain source calculations, not price forecasts or a new consensus. A Free
    account receives ``PLAN_REQUIRED`` after the documented upstream refusal.

    Args:
        symbol: US-listed optionable stock or ETF ticker.
        expiration: Optional ``YYYY-MM-DD`` expiration for the summary.
        max_expirations: Term-structure cap, clamped to 1 through 12.

    Returns:
        Envelope with separate option summary and term-structure blocks.
    """
    ticker = eq_access.ticker_for(symbol)
    adjustments: list[str] = []
    return await _fetch(
        ticker, "stock_options_analytics",
        {
            "options_summary": (
                f"securities/{ticker}/options/summary",
                {"expiration": _date(expiration, "expiration")},
            ),
            "options_term_structure": (
                f"securities/{ticker}/options/term-structure",
                {"maxExpirations": _bounded(max_expirations, 1, 12, "max_expirations", adjustments)},
            ),
        },
        adjustments=adjustments,
    )


async def stock_price_history(
    symbol: str,
    limit: int = 100,
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str = "daily",
) -> dict[str, Any]:
    """Read stored Equibles OHLCV with an API key, never as a live quote.

    Args:
        symbol: US-listed ticker.
        limit: Bar count, clamped to 1 through 500.
        start_date: Optional inclusive ISO session-date filter.
        end_date: Optional inclusive ISO session-date filter.
        interval: ``daily``, ``weekly`` or ``monthly``.

    Returns:
        Envelope with the complete provider ``price_history`` block. Its stored
        adjustment and currency semantics are not combined with other feeds.
    """
    if interval not in {"daily", "weekly", "monthly"}:
        raise ValueError("interval must be daily, weekly or monthly")
    ticker = eq_access.ticker_for(symbol)
    adjustments: list[str] = []
    return await _fetch(
        ticker, "stock_price_history",
        {
            "price_history": (
                f"securities/{ticker}/prices",
                {
                    "limit": _bounded(limit, 1, 500, "limit", adjustments), "offset": 0,
                    "startDate": _date(start_date, "start_date"),
                    "endDate": _date(end_date, "end_date"), "interval": interval,
                },
            ),
        },
        adjustments=adjustments,
    )


_TOOLS = (
    (stock_fundamentals, "Equibles-only: company identity, SEC fundamentals, debt and guidance"),
    (stock_analyst_estimates, "Equibles-only: verified analyst estimates and snapshot observations"),
    (stock_ownership_flows, "Equibles-only: 13F flows, N-PORT funds and insider sales"),
    (stock_short_positioning, "Equibles-only: short, FTD and off-exchange observations"),
    (stock_options_analytics, "Equibles paid-plan: option summary and term structure"),
    (stock_price_history, "Equibles-only: stored OHLCV history, not a live quote"),
)


def register(mcp) -> int:
    """Register the isolated Equibles tools and return the number added."""
    for function, title in _TOOLS:
        mcp.add_tool(
            function, name=function.__name__, title=title, description=function.__doc__,
        )
    return len(_TOOLS)
