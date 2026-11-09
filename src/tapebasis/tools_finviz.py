"""Finviz-only tools, served, but explicitly labelled single-source.

Finviz is the sole provider for these capabilities: SEC filings, ownership
tables, short interest, dilution risk, peers, the "why is it moving" explainer
and rendered chart PNGs. The reconciler's ``single()`` helper marks the
TradingView side ``NOT_ATTEMPTED`` so the envelope reads ``FINVIZ`` and the
notice states plainly that the data is not cross-verified.
"""
from __future__ import annotations

from typing import Any

from . import fv_access
from .health import FINVIZ, MONITOR
from .providers_state import DataProvider, NoDataError, envelope, error_code
from .reconcile import finalize, single
from .symbols import strip_exchange, to_finviz


def _single_response(
    data: Any,
    *,
    symbol: str,
    source: str,
    warnings: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap a Finviz-only payload in the standard envelope."""
    MONITOR.ensure_started()
    pair = single(FINVIZ, data)
    return finalize(
        pair,
        sources={FINVIZ: source},
        warnings=warnings or [],
        data=data,
        provider=DataProvider.FINVIZ,
        health_warn=MONITOR.warnings_for((FINVIZ,)),
        degraded=any(issue["provider"] == FINVIZ for issue in MONITOR.issues()),
        extra={"symbol": symbol, **(extra or {})},
    )


def _failed(symbol: str, exc: BaseException) -> dict[str, Any]:
    code = error_code(exc)
    if isinstance(exc, NoDataError):
        # ``NoDataError`` carries no ``code`` attribute, so ``error_code`` would
        # report ``PROVIDER_ERROR``. "Finviz answered and had nothing" is not a
        # provider failure, and an agent reading ``errors`` must be able to tell
        # the two apart.
        code = "NO_DATA"
    message = getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}"
    return envelope(
        None,
        provider=DataProvider.NONE,
        errors=[{"provider": FINVIZ, "code": code, "message": message}],
        warnings=[f"Finviz could not serve this request: {message}"],
        extra={"symbol": symbol},
    )


async def stock_filings(
    symbol: str,
    page: int = 1,
    page_size: int = 30,
    forms: str | None = None,
) -> dict[str, Any]:
    """SEC filing history for a ticker (Finviz-only, single-source).

    TradingView has no filing feed, so this capability cannot be cross-verified.
    The response is labelled ``FINVIZ`` and the notice says so.

    Args:
        symbol: Ticker.
        page: 1-based page.
        page_size: Rows per page (1-100).
        forms: Optional SEC form filter, e.g. ``"10-K,10-Q"``.

    Returns:
        Envelope with the filing rows plus ``has_more``.
    """
    ticker = strip_exchange(symbol).upper()
    try:
        data = await fv_access.filings(to_finviz(ticker), page=page, page_size=page_size, forms=forms)
    except Exception as exc:  # noqa: BLE001
        return _failed(ticker, exc)
    return _single_response(
        data,
        symbol=ticker,
        source=f"https://finviz.com/stock?t={to_finviz(ticker)}&ty=lf",
    )


async def stock_ownership(symbol: str, limit: int = 40) -> dict[str, Any]:
    """Insider trades, institutional holders and short interest (Finviz-only).

    Combines several Finviz datasets that no other provider here offers:
    Form-4 insider transactions with monthly buy/sell aggregates, institutional
    positions, and FINRA short-interest history.

    Args:
        symbol: Ticker.
        limit: Max rows per table.

    Returns:
        Envelope labelled ``FINVIZ`` with ``insider``, ``institutional`` and
        ``short_interest`` blocks (whichever Finviz could serve).
    """
    ticker = strip_exchange(symbol).upper()
    fv_symbol = to_finviz(ticker)
    blocks: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []

    for name, coro in (
        ("insider", fv_access.insider(fv_symbol, limit=limit)),
        ("institutional", fv_access.institutional(fv_symbol, limit=min(limit, 100))),
        ("short_interest", fv_access.short_interest(fv_symbol, limit=max(limit, 60))),
    ):
        try:
            blocks[name] = await coro
        except Exception as exc:  # noqa: BLE001
            code = error_code(exc)
            message = getattr(exc, "message", None) or str(exc)
            errors.append({"provider": FINVIZ, "code": code, "message": message, "dataset": name})

    if not blocks:
        return envelope(
            None,
            provider=DataProvider.NONE,
            errors=errors,
            warnings=["Finviz returned no ownership data for this ticker."],
            extra={"symbol": ticker},
        )

    response = _single_response(
        blocks,
        symbol=ticker,
        source=f"https://finviz.com/stock?t={fv_symbol}",
        warnings=[
            f"{error.get('dataset', 'dataset')} unavailable: {error['message']}"
            for error in errors
        ],
    )
    response["errors"].extend(errors)
    return response


async def stock_peers(symbol: str, limit: int = 12) -> dict[str, Any]:
    """Finviz peer group for a ticker (Finviz-only, single-source).

    Args:
        symbol: Ticker.
        limit: Maximum peers.

    Returns:
        Envelope labelled ``FINVIZ`` with ``peers``.
    """
    ticker = strip_exchange(symbol).upper()
    try:
        data = await fv_access.peers(to_finviz(ticker), limit=limit)
    except Exception as exc:  # noqa: BLE001
        return _failed(ticker, exc)
    return _single_response(
        data, symbol=ticker, source=f"https://finviz.com/stock?t={to_finviz(ticker)}"
    )


async def stock_why_moving(symbol: str) -> dict[str, Any]:
    """Finviz's own explainer for why a ticker moved (Finviz-only).

    Args:
        symbol: Ticker.

    Returns:
        Envelope labelled ``FINVIZ`` with headline, summary, sentiment and
        catalyst flag.
    """
    ticker = strip_exchange(symbol).upper()
    try:
        data = await fv_access.why_moving(to_finviz(ticker))
    except Exception as exc:  # noqa: BLE001
        return _failed(ticker, exc)
    return _single_response(
        data,
        symbol=ticker,
        source=f"https://finviz.com/api/stocks-why-moving/{to_finviz(ticker)}",
    )


async def stock_chart(
    symbol: str,
    period: str = "d",
    chart_type: str = "c",
    scale: str = "l",
    width: int = 900,
    height: int = 500,
) -> dict[str, Any]:
    """Rendered PNG candlestick chart for a ticker (Finviz-only).

    TradingView's provider computes charts as text analysis, not images, so a
    PNG is Finviz-only and labelled as such.

    Args:
        symbol: Ticker.
        period: ``d`` daily, ``w`` weekly, ``m`` monthly.
        chart_type: ``c`` candle, ``l`` line, ``h`` heikin-ashi.
        scale: ``l`` linear, ``log`` logarithmic.
        width: Pixel width.
        height: Pixel height.

    Returns:
        Envelope labelled ``FINVIZ`` with the saved PNG path and dimensions.
    """
    ticker = strip_exchange(symbol).upper()
    try:
        data = await fv_access.chart(
            to_finviz(ticker),
            period=period,
            chart_type=chart_type,
            scale=scale,
            width=width,
            height=height,
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(ticker, exc)
    return _single_response(
        data,
        symbol=ticker,
        source=f"https://charts2-node.finviz.com/chart?t={to_finviz(ticker)}",
        extra={"image_path": data.get("path")},
    )


async def stock_dilution(symbol: str) -> dict[str, Any]:
    """Dilution-risk model: share count, float and cash runway (Finviz-only).

    Finviz only builds this model for companies whose share count it considers
    dilution-prone, so a large cap legitimately has none. When that happens the
    response is ``NONE`` with the reason, not an income statement wearing the
    dilution label: the revenue/expense breakdown the same tab renders is
    served by ``stock_quote`` and ``stock_dilution`` is not the tool for it.

    Args:
        symbol: Ticker.

    Returns:
        Envelope labelled ``FINVIZ``; ``schema_version`` and ``company``
        describe the model. ``NONE`` with a stated reason when Finviz has no
        model for this company.
    """
    ticker = strip_exchange(symbol).upper()
    try:
        data = await fv_access.dilution(to_finviz(ticker))
    except Exception as exc:  # noqa: BLE001
        return _failed(ticker, exc)
    return _single_response(
        data,
        symbol=ticker,
        source=f"https://finviz.com/stock?t={to_finviz(ticker)}&ty=di",
    )


async def stock_screener_filters() -> dict[str, Any]:
    """Finviz's full screener filter catalogue (Finviz-only).

    Returns:
        Envelope labelled ``FINVIZ`` with the machine-readable filter list.
    """
    try:
        data = await fv_access.screener_filters()
    except Exception as exc:  # noqa: BLE001
        return _failed("", exc)
    return _single_response(
        data,
        symbol="",
        source="https://finviz.com/api/screener-filters?type=stocks",
    )


_TOOLS = (
    (stock_filings, "Finviz-only: SEC filing history"),
    (stock_ownership, "Finviz-only: insider, institutional and short interest"),
    (stock_peers, "Finviz-only: peer group"),
    (stock_why_moving, "Finviz-only: why is it moving"),
    (stock_chart, "Finviz-only: rendered chart PNG"),
    (stock_dilution, "Finviz-only: dilution risk model"),
    (stock_screener_filters, "Finviz-only: screener filter catalogue"),
)


def register(mcp) -> int:
    for fn, title in _TOOLS:
        mcp.add_tool(fn, name=fn.__name__, title=title, description=fn.__doc__)
    return len(_TOOLS)
