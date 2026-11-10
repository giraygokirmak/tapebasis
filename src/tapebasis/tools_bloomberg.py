"""Bloomberg-only tools: one provider answered, and the response says so.

Bloomberg is also a full reconciliation leg: ``stock_quote`` and ``stock_prices``
ask it in parallel with every other provider, and its readings appear
in their ``comparisons``. These two tools are the other case: a caller asks
Bloomberg directly, nobody else is queried, so the envelope is labelled
``BLOOMBERG`` with ``verification: SINGLE_SOURCE`` and ``cross_checked: false``.

The two properties that shape the payload:

* equity and index quotes are exchange-delayed (``exchangeDelay`` is
  ``15 Minutes``), so ``exchange_delay`` travels with the number and the
  notice warns against presenting it as a live price,
* ``lastUpdate`` is a session sentinel, so ``print_time`` is derived from the
  last intraday point and is null when that point does not match the price.

What these tools add beyond the cross-checked ones is the government benchmark
yield curve, which no other provider here publishes.
"""
from __future__ import annotations

from typing import Any

from . import bb_access
from .health import MONITOR
from .providers_state import DataProvider, NoDataError, envelope, error_code
from .reconcile import field_source

#: There is no health probe for Bloomberg: httpx cannot reproduce the TLS
#: fingerprint that gets past the bot wall, so a probe would report a false
#: outage. Callers are told that, instead of being handed a silent "OK".
_NO_PROBE = (
    "Bloomberg is not covered by the upstream health monitor: its site gates "
    "plain HTTP clients on the TLS fingerprint, so an httpx probe would report a "
    "false outage. This response is the availability signal."
)


def _label(
    data: Any,
    *,
    source: str,
    warnings: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap a Bloomberg payload in the standard envelope, labelled BLOOMBERG.

    Every top-level key of ``data`` is labelled with a field descriptor whose
    ``source`` is Bloomberg, so the response states per item where each value
    came from rather than relying on the response-level label alone.
    """
    MONITOR.ensure_started()
    fields = None
    if isinstance(data, dict):
        fields = {key: field_source(bb_access.PROVIDER, [bb_access.PROVIDER], None) for key in data}
    return envelope(
        data,
        provider=DataProvider.BLOOMBERG,
        fields=fields,
        sources={bb_access.PROVIDER: source},
        warnings=[_NO_PROBE, *(warnings or [])],
        providers_answered=[bb_access.PROVIDER],
        extra={
            # This *response* was not reconciled with another provider. The
            # provider itself does join the comparison inside ``stock_quote``;
            # these fields describe the call, not the provider's standing.
            "cross_checked": False,
            "reconciliation_leg": False,
            **(extra or {}),
        },
    )


def _failed(exc: BaseException, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    code = error_code(exc)
    if isinstance(exc, NoDataError):
        # ``NoDataError`` carries no code attribute; a page that exists but has
        # nothing to quote is "no data", not a provider failure.
        code = "NO_DATA"
    message = getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}"
    return envelope(
        None,
        provider=DataProvider.NONE,
        errors=[{"provider": bb_access.PROVIDER, "code": code, "message": message}],
        warnings=[f"Bloomberg could not serve this request: {message}"],
        extra={"cross_checked": False, "reconciliation_leg": False, **(extra or {})},
    )


async def bloomberg_quote(symbol: str) -> dict[str, Any]:
    """Bloomberg's own quote page for one instrument (single-source).

    This tool asks only Bloomberg, so the response is single-source even though
    the provider is a full leg of ``stock_quote``. Ask for it when the caller
    wants Bloomberg's reading specifically, or a figure only Bloomberg carries.

    ``print_time`` comes from the last intraday point, never from
    ``lastUpdate``, which is a session sentinel on equity pages. When the
    intraday series does not end at the quoted price, ``print_time`` is null
    with the reason in ``print_time_missing_reason``, rather than a timestamp
    that describes a different number.

    Args:
        symbol: Anything the instrument is commonly called (``AAPL``, ``BRK.B``,
            ``SPX``, ``EURUSD``, ``CL1``, ``BTCUSD``, ``XAUUSD``) or an id in
            Bloomberg's own spelling (``AAPL:US``, ``SPX:IND``).

    Returns:
        Envelope labelled ``BLOOMBERG`` / ``SINGLE_SOURCE`` whose ``data``
        carries the price, day change, ranges, volume, ratios, the derived
        ``print_time`` and the delay fields ``exchange_delay`` /
        ``is_exchange_delayed``.
    """
    try:
        data, source = await bb_access.quote(symbol)
    except Exception as exc:  # noqa: BLE001
        return _failed(exc, extra={"symbol": symbol})
    warnings = []
    if data.get("print_time") is None and data.get("print_time_missing_reason"):
        warnings.append(
            "No usable print time: " + str(data["print_time_missing_reason"])
        )
    if data.get("is_exchange_delayed"):
        warnings.append(
            "Bloomberg marks this quote as exchange-delayed"
            + (f" ({data['exchange_delay']})" if data.get("exchange_delay") else "")
            + "; do not present it as a live price."
        )
    return _label(data, source=source, warnings=warnings, extra={"symbol": symbol})


async def bloomberg_markets() -> dict[str, Any]:
    """Bloomberg's market board: index levels, government yields, commodities, FX.

    The government benchmark yields are the reason this tool exists: no other
    provider in this server publishes a yield curve. Index, commodity and FX
    levels ride along as context and are labelled single-source like the rest.

    The board carries no per-instrument print time, so the response reports
    ``print_time: null`` rather than implying a live tape, and no level here is
    aged or ordered.

    Returns:
        Envelope labelled ``BLOOMBERG`` / ``SINGLE_SOURCE`` whose ``data`` holds
        ``indices``, ``government_yields``, ``commodities`` and ``fx`` lists.
    """
    try:
        data, source = await bb_access.board()
    except Exception as exc:  # noqa: BLE001
        return _failed(exc)
    return _label(
        data,
        source=source,
        warnings=[
            "Bloomberg's market board carries no per-instrument print time, so no "
            "reading here is aged or ordered; treat every level as a snapshot."
        ],
        extra={"print_time": None},
    )


_TOOLS = (
    (bloomberg_quote, "Bloomberg-only: quote page (single-source call, delay-labelled)"),
    (bloomberg_markets, "Bloomberg-only: index, government yield, commodity and FX board"),
)


def register(mcp) -> int:
    for fn, title in _TOOLS:
        mcp.add_tool(fn, name=fn.__name__, title=title, description=fn.__doc__)
    return len(_TOOLS)
