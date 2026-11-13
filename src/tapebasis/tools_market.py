"""Multi-source market data tools.

Every tool here asks **every** provider that can serve the fact, TradingView,
Finviz, Yahoo Finance, StockAnalysis and Bloomberg, compares the answers, and
returns the reconciled payload with an explicit ``data_provider`` label. See
:mod:`tapebasis.reconcile` for the rules.

Providers are addressed through :mod:`tapebasis.tv_access`,
:mod:`tapebasis.fv_access`, :mod:`tapebasis.yh_access`,
:mod:`tapebasis.sa_access` and :mod:`tapebasis.bb_access`, which normalise the
provider service layers. Nothing proxies another provider.
"""
from __future__ import annotations

import asyncio
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

from . import bb_access, fv_access, sa_access, tv_access, yh_access
from .freshness import parse_market_timestamp
from .health import MONITOR
from .merge_helpers import (
    fv_earnings_fields,
    fv_indices_fields,
    fv_news_fields,
    fv_options_fields,
    fv_quote_fields,
    news_overlap,
    option_overlap,
    tv_indices_fields,
    tv_news_fields,
    tv_options_fields,
    yahoo_news_fields,
)
from .providers_state import (
    PROVIDER_ORDER,
    DataProvider,
    NoDataError,
    NotApplicable,
    ProviderError,
    envelope,
    provider_from_answered,
    verification_for,
)
from .sessions import (
    OVERNIGHT,
    PRE_MARKET,
    POST_MARKET,
    REGULAR,
    SESSION_NAMES,
    current_session,
    live_print,
    market_session,
    session_window_start,
)

_SESSION_NAMES = SESSION_NAMES
from .reconcile import (
    BLOOMBERG,
    FINVIZ,
    SA,
    TRADINGVIEW,
    YAHOO,
    FieldSpec,
    Pair,
    ask,
    compared_providers,
    _error_dict,
    field_source,
    finalize,
    providers_in,
)
from .symbols import (
    INDEX_SNAPSHOT,
    Resolution,
    resolve,
    resolve_sa,
    strip_exchange,
    to_finviz,
)

#: Every provider the market tools ask. They are peers, not fallbacks: a tool
#: either asks all of them or records ``NOT_ATTEMPTED`` for the ones that have
#: no endpoint. Bloomberg and StockAnalysis are the other two legs: they are
#: asked in parallel like the rest, and the known delay of the former and the
#: US-only coverage of the latter are handled by the print-time guards and the
#: resolution notes rather than by keeping them out of the comparison.
#:
#: Derived from :data:`tapebasis.providers_state.PROVIDER_ORDER`, which is the
#: single list of provider labels: a second literal here would let a tool ask a
#: provider the reconciler does not order, or order one the tools never ask.
ALL_PROVIDERS = PROVIDER_ORDER

#: Read a numeric environment override without letting a typo crash the import.
def _env_number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


#: Longest a quote call will wait for Bloomberg's page before giving up on it.
#: Its limiter paces requests 10 s apart, so without a deadline one slow hop
#: would hold the whole response; with it, Bloomberg becomes a stated error and
#: the other providers' readings still go out.
BLOOMBERG_DEADLINE_SECONDS = _env_number("TAPEBASIS_BLOOMBERG_QUOTE_DEADLINE", 12.0)

#: Most tickers a single ``stock_prices`` call asks Bloomberg about. Its page
#: path is paced at 10 s per request, so an unbounded fan-out would take
#: minutes; the remainder is reported as skipped rather than silently missing.
BLOOMBERG_BATCH_MAX = max(0, int(_env_number("TAPEBASIS_BLOOMBERG_BATCH_MAX", 4)))

#: Total time one ``stock_prices`` call may spend inside the Bloomberg leg.
#: ``BLOOMBERG_DEADLINE_SECONDS`` bounds a single page; without a batch budget
#: four tickers at the 10 s pacing took 30.5 s, which was the dominant term in a
#: cold 45.5 s call. When the budget runs out the remaining tickers are reported
#: as not answered for this call, exactly like a single-page timeout; the pacing
#: itself is untouched, because it exists to keep the bot wall from closing.
BLOOMBERG_BATCH_BUDGET_SECONDS = _env_number(
    "TAPEBASIS_BLOOMBERG_BATCH_BUDGET", 12.0
)

#: Largest print-time gap still treated as the same observation. Applies to a
#: session-relative field (a day change, a previous close, accumulated volume)
#: and to ``price``: a price points at an instant, so two prints minutes apart
#: are two observations rather than one number reported twice.
#:
#: The floor is empirical, not zero: two *live* endpoints were measured 604s
#: apart on a thin contract (TradingView 09:13:15Z vs Yahoo 09:03:11Z for
#: gold futures), so a tighter ceiling would throw away valid comparisons in
#: order to look strict. The ceiling is one session, which is where the field
#: stops being the same measurement at all.
SKEW_LIMIT_SECONDS = 900.0

#: A print older than this, *within the same US/Eastern session date*, is not
#: accepted as the current observation of a session-relative field.
#:
#: Eight hours is one regular session plus buffers. It is deliberately the
#: point just past a legitimate after-close read: a 16:00 ET print is at most
#: ~8h old before the session date rolls at midnight ET, so a tighter ceiling
#: would flag every evening quote as "frozen" and lose correct comparisons. It
#: still catches a feed that stopped updating for most of a day while the clock
#: kept moving. Applied only when the caller supplies a reference clock, which
#: keeps replays and fixtures deterministic.
MAX_SESSION_AGE_SECONDS = 8 * 3600.0


def _health(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Attach monitor-derived warnings/degraded flag scoped to attempted providers."""
    MONITOR.ensure_started()
    providers = kwargs.get("providers") or ALL_PROVIDERS
    return {
        "health_warn": MONITOR.warnings_for(providers),
        "degraded": any(
            issue["provider"] in providers for issue in MONITOR.issues()
        ),
    }


def _resolution_block(*results) -> dict[str, Any]:
    """How each provider's ticker was arrived at, for the response envelope."""
    return {
        r.provider: r.to_dict()
        for r in results
        if r is not None
    }


async def _symbols_for(symbol: str) -> dict[str, Any]:
    """Resolve one user symbol into a ticker for each provider."""
    ticker = strip_exchange(symbol).upper()
    if ":" in symbol:
        ticker = symbol.strip().upper()
    tv_res, fv_res, yh_res = await asyncio.gather(
        resolve(symbol, TRADINGVIEW),
        resolve(symbol, FINVIZ),
        resolve(symbol, YAHOO),
    )
    bb_res = _bloomberg_resolution(symbol)
    sa_res = resolve_sa(symbol)
    return {
        "query": symbol,
        "ticker": ticker,
        "TRADINGVIEW": tv_res,
        "FINVIZ": fv_res,
        "YAHOO": yh_res,
        "SA": sa_res,
        "BLOOMBERG": bb_res,
        "resolutions": _resolution_block(tv_res, fv_res, yh_res, sa_res, bb_res),
    }


def _bloomberg_resolution(symbol: str) -> Resolution:
    """Bloomberg's id for *symbol*, resolved without a request.

    Delegates to :func:`tapebasis.bb_access.resolve_bloomberg`, the one place
    identity is decided, so this tool and ``bloomberg_quote`` can never disagree
    about what a symbol means. Bloomberg has no usable anonymous search endpoint
    and answers a bad id with a bot-wall 403 rather than a 404, so the decision
    is the instrument registry plus a small alias table plus a mechanical rule.
    A registry row whose Bloomberg cell is ``None`` with a note ("no spot
    series") is resolved as not carried, so the leg is ``NOT_ATTEMPTED`` with the
    stated boundary instead of being sent an id that will answer a robot page.
    """
    return bb_access.resolve_bloomberg(symbol)


def _is_fx(*resolutions: Any) -> bool:
    """True when any provider resolved the instrument to a currency pair.

    TradingView says ``forex``, Yahoo says ``currency``, Finviz never carries
    one. Any positive is enough: the day-change question is structural, not
    provider-specific.
    """
    return any(
        (getattr(r, "asset_class", "") or "").lower() in {"forex", "currency"}
        for r in resolutions
        if r is not None
    )


#: Why an FX day change is not cross-checked, stated as the fact it is.
_FX_DAY_CHANGE_REASON = (
    "spot FX has no single official previous close; each provider derives its "
    "own daily roll, so the day-change figures answer different questions"
)


def _utc_now() -> datetime:
    """Return the response clock, replaceable by deterministic session tests."""
    return datetime.now(timezone.utc)


def _session_now(
    tv: dict[str, Any], yh: dict[str, Any], now: datetime | None = None
) -> str | None:
    """Which session the instrument is in right now, from what the legs said.

    TradingView's scanner names its session directly, so it is preferred: it is
    a statement rather than an inference. Yahoo's payload is next, and its print
    times are the fallback, because a block that exists but is hours old answers
    "which session was that" rather than "which session is this".

    Args:
        tv: The TradingView leg's payload.
        yh: The Yahoo leg's payload.

    Returns:
        ``pre_market``, ``regular``, ``post_market``, ``overnight``, or ``None``
        when no leg said anything usable.
    """
    named = _SESSION_NAMES.get(str(tv.get("current_session") or "").lower())
    if named:
        return named
    # Yahoo's newest block tells us which window last had a print.
    newest: tuple[str, Any] = (None, None)
    for key, name in (
        ("pre_market", PRE_MARKET),
        ("regular", REGULAR),
        ("post_market", "post_market"),
    ):
        block = yh.get(key) or {}
        stamp = parse_market_timestamp(block.get("as_of_utc"))
        if stamp is not None and (newest[1] is None or stamp > newest[1]):
            newest = (name, stamp)
    if newest[0]:
        if now is not None:
            active, _, _ = current_session(newest[1], now, session_name=newest[0])
            if active is None:
                # An older populated block is not a statement of the current
                # window. Do not report whether it is open or closed.
                return None
        return newest[0]
    return market_session(parse_market_timestamp(tv.get("regular_close_time")))


def _shape_overnight(block: dict[str, Any] | None) -> dict[str, Any] | None:
    """The overnight session block, with its print time rendered as ISO.

    The quote socket sends ``lp_time`` as epoch seconds. Converting it here keeps
    every timestamp in the response the same shape, so a caller can order the
    overnight print against the other sessions' without a special case.

    Args:
        block: The raw overnight payload, or ``None``.

    Returns:
        The block with ``as_of_utc`` added, or ``None`` when there was no print.
    """
    if not block:
        return None
    stamp = block.get("print_time")
    shaped = dict(block)
    shaped["as_of_utc"] = (
        datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace("+00:00", "Z")
        if isinstance(stamp, (int, float)) and math.isfinite(stamp)
        else None
    )
    return shaped


def _live_reading(
    provider: str,
    shaped: dict[str, Any],
    raw: dict[str, Any],
) -> dict[str, Any]:
    """One provider's reading, with its price moved to the session's live print.

    This is the bulk-lookup counterpart of :func:`tapebasis.sessions.live_print`.
    Both tools have to serve the same number for the same symbol, so the rule
    lives in one place: *raw* is handed to it untouched, and only the resulting
    price, session, change and baseline are merged onto *shaped*, which already
    carries the rest of the row (volume, company, the 52-week range, and so on).

    The swap happens only when the provider itself names a session other than
    ``regular`` and carries a number for it. A provider that says nothing about
    its session keeps exactly the value it always had, so a row is never credited
    with a print the provider did not send.

    Args:
        provider: The provider label.
        shaped: That provider's reading, normalised to this server's field names.
        raw: That provider's own payload, in the shape its accessor returns.

    Returns:
        The reading, with ``price`` replaced by the session's live print when
        the provider named a different session, that print's own
        ``change_percent`` and reference close, and the session name. A copy is
        always returned; the caller's payload is not mutated.
    """
    reading = dict(shaped)
    live = live_print(provider, raw)
    if live.get("price") is not None:
        reading["price"] = live["price"]
        reading["session"] = live["session"]
        # The print's own clock, which may be ``None``. A live print that the
        # provider publishes without a time (Yahoo's ``fulldayPrice``) stays
        # undated rather than inheriting the regular close's time, which belongs
        # to a different print and would date this one a session early.
        reading["price_timestamp"] = live["timestamp"]
        if live.get("change_percent") is not None:
            reading["change_percent"] = live["change_percent"]
        if live.get("reference_close") is not None:
            reading["previous_close"] = live["reference_close"]
        reading["price_field"] = live.get("field")
    else:
        # No usable price from this provider: keep the session it named, if any,
        # so a row with a missing number still says which window it looked at.
        reading["session"] = _SESSION_NAMES.get(
            str(reading.get("session") or "").lower()
        )
    return reading


#: Why the previous close itself is not cross-checked on spot FX. It is the same
#: structural fact as the day change, one step removed: there is no official
#: close to report, so each provider publishes its own roll.
_FX_PREVIOUS_CLOSE_REASON = (
    "spot FX has no single official previous close; each provider rolls the day "
    "over at its own hour, so the two figures are different baselines"
)

#: Why volume is not cross-checked on spot FX. Spot FX is not traded on an
#: exchange, so there is no session volume to report; a provider that prints a
#: number is quoting tick count or its own feed's activity, which is not the
#: same measurement as another provider's. Yahoo reports 0 for every pair.
_FX_VOLUME_REASON = (
    "spot FX has no exchange session volume; providers report their own tick "
    "counts or zero, which are not the same measurement"
)


def _quote_specs(*, spot_fx: bool = False) -> tuple[FieldSpec, ...]:
    """Fields every provider is asked for, and the tolerance for each.

    Every spec that a provider *can* answer carries a getter for that provider. A
    missing getter would silently exclude that provider from the comparison,
    which would make an ``ALL`` label claim coverage the comparison never
    actually checked. Two gaps are deliberate: ``day_open`` has no Finviz or
    Bloomberg getter (Finviz has no Open row; Bloomberg's page carries it only
    sometimes), and ``pe_ratio`` has no StockAnalysis getter (its quote API
    publishes price, range, volume and the 52-week range, not fundamentals; P/E
    lives on its stock page, a second endpoint that is not fetched here). A
    getter that reads a field nobody asked for would be worse than the gap.

    ``spot_fx=True`` marks the fields that have no shared definition on a spot
    currency pair as structurally not comparable instead of comparing readings
    that answer different questions. There are three of them, and they are the
    same fact seen three ways: spot FX has no official previous close, so the
    day change (which is measured against it) has no shared baseline, the
    previous close itself has none, and volume has no exchange session to
    accumulate over. Every reading is still reported; none of them is counted as
    a provider conflict. A real equity keeps all three under the ordinary guards
    below.
    """
    return (
        FieldSpec(
            "price",
            lambda p: p.get("price"),
            lambda p: p.get("price"),
            yh_get=lambda p: p.get("price"),
            sa_get=lambda p: p.get("price"),
            bb_get=lambda p: p.get("price"),
            tolerance_pct=0.5,
            # A price is only one number if the two prints describe the same
            # instant. Bloomberg's is structurally older (15 minutes on
            # equities), so without this guard every live quote would report a
            # "disagreement" that is really the market moving between two
            # prints. Different sessions are excluded for the same reason: a
            # Friday close and a Thursday close are both "the price" and are
            # not the same observation.
            max_skew_seconds=SKEW_LIMIT_SECONDS,
            session_boundary=True,
        ),
        FieldSpec(
            "change_percent",
            lambda p: p.get("change_percent"),
            lambda p: p.get("change_percent"),
            yh_get=lambda p: p.get("change_percent"),
            sa_get=lambda p: p.get("change_percent"),
            bb_get=lambda p: p.get("change_percent"),
            tolerance_pct=2.0,
            absolute_floor=0.05,
            # A day change is measured against the previous close *of the
            # session the print belongs to*. Two providers looking at different
            # sessions will legitimately differ, so the same session is a
            # precondition, not a detail.
            max_skew_seconds=SKEW_LIMIT_SECONDS,
            session_boundary=True,
            max_age_seconds=MAX_SESSION_AGE_SECONDS,
            not_comparable_reason=(
                _FX_DAY_CHANGE_REASON if spot_fx else None
            ),
        ),
        FieldSpec(
            "previous_close",
            lambda p: p.get("previous_close"),
            lambda p: p.get("previous_close"),
            yh_get=lambda p: p.get("previous_close"),
            sa_get=lambda p: p.get("previous_close"),
            bb_get=lambda p: p.get("previous_close"),
            tolerance_pct=0.5,
            # The same hazard, one step removed: "previous close" itself rolls
            # forward when a new session starts, and two prints 30 seconds
            # apart across that roll are a whole session apart in meaning.
            # No age ceiling here: a previous close is not re-derived from the
            # print, so a quote that is merely old does not make it wrong.
            max_skew_seconds=SKEW_LIMIT_SECONDS,
            session_boundary=True,
            # On spot FX this is the very baseline the day change lacks, so it is
            # not comparable for the identical reason. Reporting it as a
            # disagreement was the tool contradicting its own FX rule: it
            # refused to compare the change, then blamed the providers for
            # disagreeing on the close that change is measured from.
            not_comparable_reason=(
                _FX_PREVIOUS_CLOSE_REASON if spot_fx else None
            ),
        ),
        FieldSpec(
            "week_52_high",
            lambda p: p.get("week_52_high"),
            lambda p: p.get("week_52_high"),
            yh_get=lambda p: p.get("week_52_high"),
            sa_get=lambda p: p.get("week_52_high"),
            bb_get=lambda p: p.get("week_52_high"),
            tolerance_pct=0.5,
        ),
        FieldSpec(
            "week_52_low",
            lambda p: p.get("week_52_low"),
            lambda p: p.get("week_52_low"),
            yh_get=lambda p: p.get("week_52_low"),
            sa_get=lambda p: p.get("week_52_low"),
            bb_get=lambda p: p.get("week_52_low"),
            tolerance_pct=0.5,
        ),
        FieldSpec(
            "pe_ratio",
            lambda p: p.get("pe_ratio"),
            lambda p: p.get("pe_ratio"),
            bb_get=lambda p: p.get("pe_ratio"),
            tolerance_pct=2.0,
        ),
        FieldSpec(
            "rsi_14",
            lambda p: p.get("rsi_14"),
            lambda p: p.get("rsi_14"),
            tolerance_pct=5.0,
            absolute_floor=0.5,
        ),
        FieldSpec(
            "volume",
            lambda p: p.get("volume"),
            lambda p: p.get("volume"),
            yh_get=lambda p: p.get("volume"),
            sa_get=lambda p: p.get("volume"),
            bb_get=lambda p: p.get("volume"),
            tolerance_pct=1.0,
            # Volume accumulates through a session; a partial session and a
            # full one are not the same measurement.
            max_skew_seconds=SKEW_LIMIT_SECONDS,
            session_boundary=True,
            max_age_seconds=MAX_SESSION_AGE_SECONDS,
            # Spot FX has no exchange session, so there is nothing for the
            # number to be. Measured live: Yahoo reports 0 for every pair while
            # TradingView reports its own tick count, which the 1 % tolerance
            # scored as a 100 % conflict on every FX quote asked for.
            not_comparable_reason=_FX_VOLUME_REASON if spot_fx else None,
        ),
        # The session's own high and low. Every price feed here publishes them
        # and none of the tools did: TradingView returned them on each scanner
        # row, Yahoo on each chart ``meta``, StockAnalysis and Bloomberg on
        # their quote endpoints. A session range is a high-water mark for the
        # day, so it is session-relative exactly like volume: two prints from
        # different sessions are two different ranges, not a disagreement.
        FieldSpec(
            "day_high",
            lambda p: p.get("day_high"),
            lambda p: p.get("day_high"),
            yh_get=lambda p: p.get("day_high"),
            sa_get=lambda p: p.get("day_high"),
            bb_get=lambda p: p.get("day_high"),
            tolerance_pct=0.5,
            max_skew_seconds=SKEW_LIMIT_SECONDS,
            session_boundary=True,
            max_age_seconds=MAX_SESSION_AGE_SECONDS,
        ),
        FieldSpec(
            "day_low",
            lambda p: p.get("day_low"),
            lambda p: p.get("day_low"),
            yh_get=lambda p: p.get("day_low"),
            sa_get=lambda p: p.get("day_low"),
            bb_get=lambda p: p.get("day_low"),
            tolerance_pct=0.5,
            max_skew_seconds=SKEW_LIMIT_SECONDS,
            session_boundary=True,
            max_age_seconds=MAX_SESSION_AGE_SECONDS,
        ),
        # The open is reported by TradingView, Yahoo and StockAnalysis; Finviz's
        # snapshot has no Open row and Bloomberg's page carries it only
        # sometimes, so the getters are absent for those two rather than reading
        # ``None`` from a field that was never asked for.
        FieldSpec(
            "day_open",
            lambda p: p.get("day_open"),
            yh_get=lambda p: p.get("day_open"),
            sa_get=lambda p: p.get("day_open"),
            tolerance_pct=0.5,
            max_skew_seconds=SKEW_LIMIT_SECONDS,
            session_boundary=True,
            max_age_seconds=MAX_SESSION_AGE_SECONDS,
        ),
    )


# ── Quote ────────────────────────────────────────────────────────────────────


async def stock_quote(symbol: str) -> dict[str, Any]:
    """Quote and fundamentals for one instrument, asked of every capable provider.

    Each provider is asked independently and natively: TradingView's scanner,
    Finviz's quote page, Yahoo's chart API, StockAnalysis's quote API and
    Bloomberg's quote page, in parallel. Nothing proxies another, so the
    cross-check is real. Price, change, previous close, the session's own
    open/high/low, the 52-week range, P/E, RSI and volume are compared field by
    field; Finviz's deeper fundamentals, the 84-field snapshot, the
    revenue/segment breakdown, company profile, peers and after-hours print,
    ride along, each labelled with the provider that supplied it. A field that
    cannot be shown to describe the same observation is reported as
    ``not_comparable`` rather than as a conflict, and an FX day change is never
    compared because spot FX has no single official previous close. An empty
    response after a symbol resolves remains ``NO_DATA``, not ``NOT_ATTEMPTED``.

    Bloomberg's prints can be structurally older than a live feed's
    (``exchangeDelay`` is ``15 Minutes`` on equities and indices). That is
    handled by the print-time guard, not by hiding the leg: when its print is
    too far from the others to be the same observation, the pair is reported as
    not comparable with that reason, and its delayed reading never wins the
    freshness tie-break. ``exchange_delay`` and ``print_time`` ride along so the
    delay is visible.

    StockAnalysis covers US equities and ETFs only. Its quote surface is the
    same consolidated tape Yahoo serves, so agreement between those two is weak
    corroboration rather than two independent witnesses; that is stated in the
    docs and in the single-source notice. Indices, FX, crypto and foreign
    listings resolve to "not carried" for that leg, which is recorded as
    ``NOT_ATTEMPTED`` rather than as a failure.

    Symbols are resolved dynamically per provider, so ``XAUUSD`` reaches
    TradingView as ``OANDA:XAUUSD``, Yahoo as ``XAUUSD=X``, Bloomberg as
    ``XAUUSD:CUR``, and Finviz and StockAnalysis are told they do not carry spot
    gold (rather than being sent to a 404).

    Args:
        symbol: Anything the instrument is commonly called (``AAPL``, ``BRK.B``,
            ``XAUUSD``, ``SPX``, ``BTCUSD``, ``OANDA:XAUUSD``).

    Returns:
        Envelope whose ``data_provider`` is ``ALL`` when every provider asked
        answered, a provider name when only one did (the notice then states the
        data is single-source), or ``NONE`` when none did. ``resolutions``
        records how each provider's ticker was derived. ``session`` names the
        window the served ``price`` printed in (``pre_market``, ``regular``,
        ``post_market`` or ``overnight``), and it is taken from the winning
        provider's own print rather than from another leg's label, so a delayed
        feed cannot describe a print it did not supply.
    """
    resolved = await _symbols_for(symbol)
    ticker = strip_exchange(resolved["ticker"]).upper()
    tv_res = resolved["TRADINGVIEW"]
    fv_res = resolved["FINVIZ"]
    yh_res = resolved["YAHOO"]
    sa_res = resolved["SA"]
    bb_res = resolved["BLOOMBERG"]

    async def tv_call() -> dict[str, Any]:
        if not tv_res.found:
            raise NotApplicable(TRADINGVIEW, tv_res.note or f"no TradingView symbol for {symbol}")
        # The scanner row is TradingView's own quote and carries open/high/low,
        # volume, the 52-week range and fundamentals in one request.
        return await tv_access.quote(tv_res.symbol)

    async def fv_call() -> dict[str, Any]:
        if not fv_res.found:
            raise NotApplicable(FINVIZ, fv_res.note or f"Finviz does not carry {symbol}")
        return await fv_access.quote(fv_res.symbol)

    async def yh_call() -> dict[str, Any]:
        if not yh_res.found:
            # "Yahoo has no ticker for this" is not an outage. Saying so keeps
            # ``errors`` for real failures, an agent reading the envelope must
            # be able to tell "provider is down" from "provider never had it".
            raise NotApplicable(YAHOO, yh_res.note or f"Yahoo Finance does not carry {symbol}")
        return await yh_access.quote(yh_res.symbol)

    async def sa_call() -> dict[str, Any]:
        if not sa_res.found:
            raise NotApplicable(
                SA, sa_res.note or f"StockAnalysis does not carry {symbol}"
            )
        return await sa_access.quote(sa_res.symbol)

    async def bb_call() -> dict[str, Any]:
        if not bb_res.found:
            raise NotApplicable(
                BLOOMBERG, bb_res.note or f"Bloomberg has no id for {symbol}"
            )
        try:
            data, _source = await asyncio.wait_for(
                bb_access.quote(symbol), timeout=BLOOMBERG_DEADLINE_SECONDS
            )
        except asyncio.TimeoutError as exc:
            # Paced at 10 s per request, so waiting forever is a real option for
            # this leg. A stated timeout is better than a silent omission: the
            # reader can see the leg was asked and did not answer.
            raise ProviderError(
                BLOOMBERG,
                f"Bloomberg did not answer within {BLOOMBERG_DEADLINE_SECONDS:.0f}s; "
                "its page path is paced at 10 s per request, so an interrupted "
                "call is reported rather than waited out",
                code="TIMEOUT",
            ) from exc
        return data

    # The last two legs are named rather than positional: both are optional in
    # ``ask`` and swapping them would mislabel every reading in the response.
    pair = await ask(
        tv_call, fv_call, yh_call, bb_fn=bb_call, sa_fn=sa_call
    )

    def tv_norm(payload: dict[str, Any]) -> dict[str, Any]:
        live = live_print(TRADINGVIEW, payload)
        return {
            "price": live["price"],
            "change_percent": live["change_percent"],
            "previous_close": live["reference_close"] or payload.get("prev_close_price"),
            "week_52_high": payload.get("price_52_week_high"),
            "week_52_low": payload.get("price_52_week_low"),
            "pe_ratio": payload.get("price_earnings_ttm"),
            "rsi_14": payload.get("RSI"),
            "atr_14": payload.get("ATR"),
            "volume": payload.get("volume"),
            "beta": payload.get("beta_1_year"),
            "currency": payload.get("currency"),
            "exchange": payload.get("exchange"),
            "price_timestamp": payload.get("update_time"),
            "description": payload.get("description"),
            "sector": payload.get("sector"),
            "industry": payload.get("industry"),
            "dividend_yield": payload.get("dividends_yield_current"),
            "eps_ttm": payload.get("earnings_per_share_basic_ttm"),
            # The scanner returns the session's own open/high/low on every
            # quote request. They were requested and then dropped, so the day
            # range had to be inferred from another provider or lost.
            "day_open": payload.get("open"),
            "day_high": payload.get("high"),
            "day_low": payload.get("low"),
            # ``update_mode`` is the scanner's own statement of how fresh this
            # feed is (``delayed_streaming_900`` = 15 minutes, ``streaming`` =
            # live). Without it a caller cannot tell a delayed read from a live
            # one, which is exactly the distinction Bloomberg's
            # ``exchange_delay`` already exposes for its leg.
            "feed_mode": payload.get("update_mode"),
            "instrument_type": payload.get("type"),
            "instrument_subtype": payload.get("subtype"),
        }

    def fv_norm(payload: dict[str, Any]) -> dict[str, Any]:
        shaped = fv_quote_fields(payload)
        header = payload.get("last_close") or {}
        shaped["price"] = header.get("price")
        shaped["change_percent"] = header.get("change_percent")
        snapshot = payload.get("snapshot_numeric") or {}
        shaped["previous_close"] = snapshot.get("Prev Close")
        # Finviz renders the print time next to the price ("Nov 03 • 3:59 PM ET").
        shaped["price_timestamp"] = header.get("date")
        return shaped

    def yh_norm(payload: dict[str, Any]) -> dict[str, Any]:
        live = live_print(YAHOO, payload)
        return {
            "price": live["price"],
            "change_percent": live["change_percent"],
            "previous_close": live["reference_close"] or payload.get("previous_close"),
            "week_52_high": payload.get("52w_high"),
            "week_52_low": payload.get("52w_low"),
            # Yahoo reports the session volume in ``meta.regularMarketVolume``
            # and it was being dropped here, so ``volume`` was compared across
            # some providers while another had already been asked and answered.
            # Read it so the comparison covers every provider that actually has
            # the field.
            "volume": payload.get("volume"),
            "day_open": payload.get("day_open"),
            "day_high": payload.get("day_high"),
            "day_low": payload.get("day_low"),
            "currency": payload.get("currency"),
            "exchange": payload.get("exchange"),
            "market_state": payload.get("market_state"),
            # The live print carries its own clock. Yahoo publishes no print
            # time for ``fulldayPrice``, and reusing the regular close's
            # ``market_time`` here dated an extended print to the previous
            # session, which made every comparison against it look like a
            # cross-session pair.
            "price_timestamp": live["timestamp"]
            if live["field"] == "fullday_price"
            else payload.get("market_time"),
            "company": payload.get("company"),
        }

    def sa_norm(payload: dict[str, Any]) -> dict[str, Any]:
        # StockAnalysis's quote endpoint publishes price, the day session, the
        # 52-week range and volume. It has no fundamentals on this route, so
        # ``pe_ratio``/``beta``/``eps`` are not invented here; they live on its
        # stock page, which ``stock_quote`` does not fetch.
        live = live_print(SA, payload)
        return {
            "price": live["price"],
            "change_percent": live["change_percent"],
            "previous_close": live["reference_close"] or payload.get("previous_close"),
            "week_52_high": payload.get("week_52_high"),
            "week_52_low": payload.get("week_52_low"),
            "day_open": payload.get("day_open"),
            "day_high": payload.get("day_high"),
            "day_low": payload.get("day_low"),
            "volume": payload.get("volume"),
            "exchange": payload.get("exchange"),
            "market_state": payload.get("market_state"),
            "price_date": payload.get("price_date"),
            # ``ts`` is epoch milliseconds; ``sa_access`` converts it to ISO so
            # it can be ordered against the other providers' print times. When
            # the live print is the extended block, that block's own timestamp
            # is the one that dates it; the regular ``ts`` belongs to the
            # regular close and would date the extended print a session early.
            "price_timestamp": live["timestamp"]
            if live["field"] == "extended_hours.price"
            else payload.get("price_timestamp"),
            # Prefix the key with its provider, like the other non-compared
            # extras in this payload: a bare ``extended_hours`` would not say
            # whose print it is.
            "stockanalysis_extended_hours": payload.get("extended_hours"),
            "stockanalysis_has_extended_hours": payload.get("has_extended_hours"),
        }

    def bb_norm(payload: dict[str, Any]) -> dict[str, Any]:
        # Bloomberg's print time is already derived from the intraday series by
        # ``bb_access.shape_quote`` and is passed as ``bb_time``, so it is not
        # repeated here: an extra ``price_timestamp`` would be a competing
        # timestamp in the payload.
        week_52 = payload.get("week_52_range") or [None, None]
        # ``dayRange`` is Bloomberg's ``[low, high]`` pair. Splitting it here is
        # what lets its session range join the same comparison the other legs
        # feed; without it the field arrived in every shaped payload and
        # stopped there.
        day_range = payload.get("day_range") or [None, None]
        return {
            "price": payload.get("price"),
            "change_percent": payload.get("change_percent"),
            "previous_close": payload.get("previous_close"),
            "week_52_low": week_52[0] if len(week_52) > 0 else None,
            "week_52_high": week_52[1] if len(week_52) > 1 else None,
            "day_low": day_range[0] if len(day_range) > 0 else None,
            "day_high": day_range[1] if len(day_range) > 1 else None,
            "pe_ratio": payload.get("pe_ratio"),
            "eps_ttm": payload.get("eps"),
            "volume": payload.get("volume"),
            "currency": payload.get("currency"),
            "exchange": payload.get("exchange"),
            "print_time": payload.get("print_time"),
            "exchange_delay": payload.get("exchange_delay"),
            "is_exchange_delayed": payload.get("is_exchange_delayed"),
        }

    # Which session ``data.price`` is a print from. Derived from the winning
    # provider's own print, not from TradingView's label: the scanner states a
    # session, but its feed can be 15 minutes delayed, so at 09:34 ET it still
    # said ``pre_market`` while the served print was a regular-session one. A
    # row that names the wrong session is worse than one that names none, so the
    # label follows the number the caller actually reads.
    served_sessions: dict[str, str | None] = {}
    served_fields: dict[str, str | None] = {}
    for label, payload in (
        (TRADINGVIEW, pair.tv.payload),
        (FINVIZ, pair.fv.payload),
        (YAHOO, pair.yh.payload),
        (SA, pair.sa.payload),
        (BLOOMBERG, pair.bb.payload),
    ):
        if not payload:
            continue
        live = live_print(label, payload)
        served_sessions[label] = live.get("session")
        served_fields[label] = live.get("field")

    result = finalize(
        pair,
        # Spot FX has no official previous close, so the three fields that are
        # defined against it (the day change, the close itself, and a session
        # volume it never accumulates) are reported from every provider but never
        # compared. Everything else is compared.
        specs=_quote_specs(
            spot_fx=_is_fx(tv_res, fv_res, yh_res, sa_res, bb_res)
        ),
        tv_norm=tv_norm,
        fv_norm=fv_norm,
        yh_norm=yh_norm,
        sa_norm=sa_norm,
        bb_norm=bb_norm,
        # Bloomberg's print time is derived, not read off ``lastUpdate``, so it
        # is passed explicitly rather than picked up from the shaped payload.
        bb_time=(pair.bb.payload or {}).get("print_time"),
        # The only tool that compares session-relative fields, so the only one
        # that needs a reference clock for the frozen-feed ceiling.
        now=datetime.now(timezone.utc),
        sources={
            TRADINGVIEW: "scanner.tradingview.com",
            FINVIZ: f"https://finviz.com/stock?t={fv_res.symbol or to_finviz(ticker)}"
            if fv_res.found
            else "not carried by Finviz",
            YAHOO: f"https://query1.finance.yahoo.com/v8/finance/chart/{yh_res.symbol}"
            if yh_res.found
            else "not carried by Yahoo Finance",
            SA: f"https://stockanalysis.com/api/quotes/s/{sa_res.symbol}"
            if sa_res.found
            else "not carried by StockAnalysis",
            BLOOMBERG: f"https://www.bloomberg.com/quote/{bb_res.symbol}"
            if bb_res.found
            else "no Bloomberg id",
        },
        extra={
            "symbol": ticker,
            "resolutions": resolved["resolutions"],
        },
        **_health({"providers": providers_in(pair) or ALL_PROVIDERS}),
    )
    # The session of the print that was actually served, mirrored at the
    # envelope level as well as inside ``data`` so it is visible however the
    # caller walks the response. Without it a caller cannot tell the regular
    # session's last trade from the live pre-market print, and on an active
    # symbol those differ by more than this tool's own comparison tolerance.
    winner_label = (result.get("fields", {}).get("price") or {}).get("source")
    session_now = served_sessions.get(winner_label) if winner_label else None
    if session_now is None and winner_label:
        # A provider that names no session still prints at a time, and the clock
        # of that print is a better answer than no label at all.
        session_now = market_session(
            parse_market_timestamp((result.get("freshness") or {}).get(winner_label))
        )
    # ``None`` rather than an absent key: the contract says a print whose session
    # cannot be determined carries ``session: null`` instead of a guess, and a
    # missing key would read as "this tool has no such field".
    result["session"] = session_now
    if isinstance(result.get("data"), dict) and result["data"]:
        # Only when there is a quote to describe: on the NONE path ``data`` is
        # empty and a ``session`` key would claim a print no provider sent.
        result["data"]["session"] = session_now
        # The provider field the price was read from, so the swap from a stale
        # regular value to a live session print is auditable rather than implied.
        result["data"]["price_field"] = served_fields.get(winner_label) if winner_label else None
    return result


# ── Bulk prices ──────────────────────────────────────────────────────────────


def _batch_no_data(provider: str, symbol: str, message: str) -> dict[str, Any]:
    """Return a typed per-symbol empty result for a batch provider."""
    return {
        "provider": provider,
        "symbol": symbol,
        "code": "NO_DATA",
        "message": message,
    }


def _batch_error(provider: str, symbol: str, exc: BaseException) -> dict[str, Any]:
    """Return a batch failure tagged with the requested symbol.

    Real provider failures keep their code. An unexpected ``NotApplicable``
    inside an already-resolved per-symbol request is not reclassified as an
    unasked leg: the request was attempted, so it remains a visible ``NO_DATA``.
    """
    error = _error_dict(provider, exc)
    error["symbol"] = symbol
    if error["code"] == "NOT_ATTEMPTED":
        error["code"] = "NO_DATA"
    return error


def _batch_error_map(
    provider: str,
    pair: Pair,
    asked_for: dict[str, list[str]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return typed row failures and batch-level failures for one provider.

    A batch endpoint reports a requested key it omitted as ``NO_DATA``. A
    provider error without a symbol applies to every symbol it was resolved to
    fetch. Per-symbol exceptions retain their codes and stay isolated to their
    own rows.
    """
    attempt = pair.attempts.get(provider)
    payload = attempt.payload or {} if attempt else {}
    if attempt is None:
        return {}, {}
    errors = {
        error["symbol"]: error
        for error in payload.get("errors") or []
        if error.get("symbol")
    }
    batch_errors: dict[str, dict[str, Any]] = {}
    if attempt.failed and (attempt.error or {}).get("code") != "NOT_ATTEMPTED":
        error = dict(attempt.error or {})
        batch_errors = {
            symbol: {**error, "symbol": symbol}
            for symbol in asked_for.get(provider, [])
        }
    return errors, batch_errors

# ── Bulk prices ──────────────────────────────────────────────────────────────


async def stock_prices(tickers: str) -> dict[str, Any]:
    """Prices for several instruments at once, from every provider that carries them.

    Each ticker is resolved per provider and looked up natively: TradingView's
    scanner, Finviz's screener, Yahoo's chart API, StockAnalysis's quote API,
    Bloomberg's quote page. The per-row ``data_provider`` says whether that
    particular ticker was answered by every provider asked for that ticker,
    by some of them, by one, or by none; envelope coverage is PARTIAL when
    any symbol missed an attempted provider, even when another row is ALL.
    ``agrees`` says whether the readings matched. Bloomberg is asked about at
    most ``TAPEBASIS_BLOOMBERG_BATCH_MAX`` tickers per call (default 4) because
    its page path is paced at 10 s per request; the rest are reported as skipped
    in ``warnings`` rather than silently missing.

    Args:
        tickers: Comma-separated symbols, e.g. ``"AAPL,MSFT,XAUUSD"``.

    Returns:
        Envelope whose ``data`` is a list of rows, each with ``symbol``,
        ``price``, ``change_percent``, its own ``data_provider``, and a
        ``fields`` map giving each value's provenance. ``price_source`` names
        the provider the row's values were taken from, and ``fields`` states it
        per field, because only ``price`` and ``change_percent`` are compared:
        a row can read ``ALL`` while ``previous_close`` was shaped by one
        provider. ``session`` names the window the row's ``price`` printed in,
        and ``price_field`` names the provider field it was read from, so a swap
        from a stale regular value to a live session print is auditable rather
        than implied. On an FX symbol the day change is reported but not
        compared, because spot FX has no single official previous close.
        Per-symbol ``misses`` and ``errors`` keep attempted empty results and
        original provider error codes visible, with the envelope aggregating
        those failures and the row-derived comparison verdicts.
    """
    requested = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not requested:
        return envelope(
            [],
            provider=DataProvider.NONE,
            warnings=["No tickers supplied."],
            extra={"symbols": []},
        )

    resolved = {
        symbol: entry
        for symbol, entry in zip(
            requested,
            await asyncio.gather(*(_symbols_for(symbol) for symbol in requested)),
        )
    }

    tv_tickers = [
        r["TRADINGVIEW"].symbol
        for r in resolved.values()
        if r["TRADINGVIEW"].found
    ]
    fv_symbols = [
        r["FINVIZ"].symbol for r in resolved.values() if r["FINVIZ"].found
    ]

    async def tv_call() -> dict[str, Any]:
        if not tv_tickers:
            raise NotApplicable(TRADINGVIEW, "no TradingView symbol resolved")
        return {"rows": await tv_access.quotes(tv_tickers)}

    async def fv_call() -> dict[str, Any]:
        if not fv_symbols:
            raise NotApplicable(FINVIZ, "Finviz carries none of these instruments")
        rows = await fv_access.screener_rows(list(fv_symbols))
        return {"rows": {str(r.get("ticker", "")).upper(): r for r in rows}}

    async def yh_call() -> dict[str, Any]:
        """One Yahoo quote per ticker, asked concurrently.

        The limiter still paces Yahoo, so this buys the per-request handshake
        and latency overlap, not a burst. Measured sequentially, four quotes
        spent 7.4 s before the pooling change.
        """
        askable = [
            (symbol, entry["YAHOO"].symbol)
            for symbol, entry in resolved.items()
            if entry["YAHOO"].found
        ]
        misses = {
            symbol: (entry["YAHOO"].note or "no Yahoo ticker")
            for symbol, entry in resolved.items()
            if not entry["YAHOO"].found
        }

        async def _one(symbol: str, ticker: str) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
            """Return one quote, or its typed failure without sinking the batch."""
            try:
                return symbol, await yh_access.quote(ticker), None
            except Exception as exc:  # noqa: BLE001 - a single miss must not sink the batch
                return symbol, None, _batch_error(YAHOO, symbol, exc)

        rows: dict[str, dict[str, Any]] = {}
        errors: list[dict[str, Any]] = []
        for symbol, row, error in await asyncio.gather(
            *(_one(symbol, ticker) for symbol, ticker in askable)
        ):
            if row is not None:
                rows[symbol] = row
            else:
                error = error or _batch_no_data(YAHOO, symbol, "no Yahoo data")
                errors.append(error)
                misses[symbol] = error["message"]
        return {"rows": rows, "misses": misses, "errors": errors}

    bb_symbols = [
        symbol
        for symbol in requested
        if resolved[symbol]["BLOOMBERG"].found
    ]
    bb_asked = bb_symbols[:BLOOMBERG_BATCH_MAX]
    bb_skipped = bb_symbols[BLOOMBERG_BATCH_MAX:]

    sa_slugs = [
        symbol for symbol in requested if resolved[symbol]["SA"].found
    ]

    async def sa_call() -> dict[str, Any]:
        """One StockAnalysis quote per ticker, asked concurrently."""
        if not sa_slugs:
            raise NotApplicable(
                SA, "StockAnalysis carries none of these instruments"
            )

        async def _one(symbol: str, slug: str) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
            """Return one quote, or its typed failure without sinking the batch."""
            try:
                return symbol, await sa_access.quote(slug), None
            except Exception as exc:  # noqa: BLE001 - one miss must not sink the batch
                return symbol, None, _batch_error(SA, symbol, exc)

        found = {
            symbol: resolved[symbol]["SA"].symbol
            for symbol in requested
            if resolved[symbol]["SA"].found
        }
        rows: dict[str, dict[str, Any]] = {}
        misses: dict[str, str] = {}
        errors: list[dict[str, Any]] = []
        for symbol, row, error in await asyncio.gather(
            *(_one(symbol, slug) for symbol, slug in found.items())
        ):
            if row is not None:
                rows[symbol] = row
            else:
                error = error or _batch_no_data(SA, symbol, "no StockAnalysis data")
                errors.append(error)
                misses[symbol] = error["message"]
        return {"rows": rows, "misses": misses, "errors": errors}

    async def bb_call() -> dict[str, Any]:
        if not bb_asked:
            raise NotApplicable(
                BLOOMBERG,
                "no Bloomberg id resolved"
                if not bb_symbols
                else f"Bloomberg is asked about at most {BLOOMBERG_BATCH_MAX} tickers per batch",
            )
        # One budget for the whole leg, not one per page: four tickers at the
        # 10 s pacing used to hold the call open for 30.5 s. Each page keeps its
        # own deadline, but the batch stops asking once the budget is spent and
        # reports the rest as unanswered, so the other providers' readings go out
        # on time. The pacing itself is untouched.
        deadline = time.monotonic() + BLOOMBERG_BATCH_BUDGET_SECONDS
        rows: dict[str, dict[str, Any]] = {}
        misses: dict[str, str] = {}
        errors: list[dict[str, Any]] = []
        for symbol in bb_asked:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                misses[symbol] = (
                    "not asked: the Bloomberg leg's "
                    f"{BLOOMBERG_BATCH_BUDGET_SECONDS:.0f}s batch budget was spent "
                    "on the earlier tickers, and its page path is paced at 10 s"
                )
                continue
            try:
                data, _source = await asyncio.wait_for(
                    bb_access.quote(symbol),
                    timeout=min(remaining, BLOOMBERG_DEADLINE_SECONDS),
                )
                rows[symbol] = data
            except asyncio.TimeoutError:
                error = _batch_no_data(
                    BLOOMBERG,
                    symbol,
                    f"no answer within {min(remaining, BLOOMBERG_DEADLINE_SECONDS):.0f}s",
                )
                errors.append(error)
                misses[symbol] = error["message"]
            except Exception as exc:  # noqa: BLE001 - one miss must not sink the batch
                error = _batch_error(BLOOMBERG, symbol, exc)
                errors.append(error)
                misses[symbol] = error["message"]
        return {"rows": rows, "misses": misses, "errors": errors}

    pair = await ask(
        tv_call, fv_call, yh_call, bb_fn=bb_call, sa_fn=sa_call
    )

    from .reconcile import DEFAULT_ORDER, _resolved_label, compare_values

    tv_rows = (pair.tv.payload or {}).get("rows") or {}
    fv_rows = (pair.fv.payload or {}).get("rows") or {}
    yh_rows = (pair.yh.payload or {}).get("rows") or {}
    sa_rows = (pair.sa.payload or {}).get("rows") or {}
    bb_rows = (pair.bb.payload or {}).get("rows") or {}

    bb_payload = pair.bb.payload or {}
    budget_cutoffs = {
        symbol
        for symbol, reason in (bb_payload.get("misses") or {}).items()
        if "budget" in str(reason)
    }
    row_failures: dict[str, dict[str, dict[str, Any]]] = {
        symbol: {} for symbol in requested
    }
    def asked_for_symbol(symbol: str) -> list[str]:
        """Return providers this batch requested for one symbol."""
        asked: set[str] = set()
        for provider in ALL_PROVIDERS:
            if not resolved[symbol][provider].found:
                continue
            if provider == TRADINGVIEW:
                asked.add(provider)
            elif provider == FINVIZ:
                asked.add(provider)
            elif provider == YAHOO and resolved[symbol][YAHOO].found:
                asked.add(provider)
            elif provider == SA and symbol in sa_slugs:
                asked.add(provider)
            elif provider == BLOOMBERG and symbol in bb_asked:
                if symbol not in budget_cutoffs:
                    asked.add(provider)
        return [provider for provider in ALL_PROVIDERS if provider in asked]

    asked_by_provider = {
        provider: [
            symbol for symbol in requested if provider in asked_for_symbol(symbol)
        ]
        for provider in ALL_PROVIDERS
    }
    for provider in ALL_PROVIDERS:
        symbol_errors, batch_errors = _batch_error_map(provider, pair, asked_by_provider)
        for symbol in requested:
            if symbol in symbol_errors:
                row_failures[symbol][provider] = symbol_errors[symbol]
            elif (
                symbol in batch_errors
                and resolved[symbol][provider].found
                and not (
                    provider == BLOOMBERG
                    and (
                        symbol in bb_skipped
                        or symbol in budget_cutoffs
                    )
                )
            ):
                row_failures[symbol][provider] = batch_errors[symbol]
        if provider not in (TRADINGVIEW, FINVIZ):
            continue
        rows = tv_rows if provider == TRADINGVIEW else fv_rows
        for symbol in requested:
            entry = resolved[symbol]
            if not entry[provider].found or symbol in row_failures[symbol]:
                continue
            if provider == TRADINGVIEW:
                found = bool(tv_rows.get(strip_exchange(entry[provider].symbol or "")))
            else:
                found = bool(
                    fv_rows.get(entry[provider].symbol or "")
                    or fv_rows.get(to_finviz(symbol))
                )
            if not found:
                label = "TradingView" if provider == TRADINGVIEW else "Finviz"
                row_failures[symbol][provider] = _batch_no_data(
                    provider, symbol, f"no {label} row returned for {symbol}"
                )
    out_rows: list[dict[str, Any]] = []
    for symbol in requested:
        entry = resolved[symbol]
        tv_row = tv_rows.get(strip_exchange(entry["TRADINGVIEW"].symbol or ""))
        fv_row = fv_rows.get(entry["FINVIZ"].symbol or "") or fv_rows.get(
            to_finviz(symbol)
        )
        yh_row = yh_rows.get(symbol)
        sa_row = sa_rows.get(symbol)
        readings: dict[str, dict[str, Any]] = {}
        if tv_row:
            readings[TRADINGVIEW] = _live_reading(
                TRADINGVIEW,
                {
                    "volume": tv_row.get("volume"),
                    "company": tv_row.get("description"),
                    "price_timestamp": tv_row.get("update_time"),
                },
                tv_row,
            )
        if fv_row:
            readings[FINVIZ] = _live_reading(
                FINVIZ,
                {
                    "change_percent": fv_row.get("change"),
                    "previous_close": fv_row.get("prevClose"),
                    "volume": fv_row.get("volume"),
                    "company": fv_row.get("company"),
                    # ``fetched_at`` is when the screener was read, not when the
                    # instrument traded. Using it as a print time let a stale
                    # Finviz price claim to be the freshest reading in the row.
                    "price_timestamp": fv_row.get("last_update"),
                },
                # The screener row has no ``last_close`` header, so it is shaped
                # into the one ``live_print`` reads. Its ``price`` is already the
                # live print, extended hours included, and ``prevClose`` is the
                # baseline it is measured against.
                {
                    "last_close": {
                        "price": fv_row.get("price"),
                        "date": fv_row.get("last_update"),
                        "change_percent": fv_row.get("change"),
                    },
                    "snapshot_numeric": {"Prev Close": fv_row.get("prevClose")},
                },
            )
        if yh_row:
            readings[YAHOO] = _live_reading(
                YAHOO,
                {
                    "volume": yh_row.get("volume"),
                    "company": yh_row.get("shortName"),
                    "price_timestamp": yh_row.get("market_time"),
                },
                yh_row,
            )
        if sa_row:
            readings[SA] = _live_reading(
                SA,
                {
                    "volume": sa_row.get("volume"),
                },
                sa_row,
            )
        bb_row = bb_rows.get(symbol)
        if bb_row:
            week_52 = bb_row.get("week_52_range") or [None, None]
            readings[BLOOMBERG] = _live_reading(
                BLOOMBERG,
                {
                    "week_52_low": week_52[0] if len(week_52) > 0 else None,
                    "week_52_high": week_52[1] if len(week_52) > 1 else None,
                    "company": bb_row.get("name"),
                    "exchange_delay": bb_row.get("exchange_delay"),
                },
                bb_row,
            )

        # A returned container is not a quote answer. An attempted payload with
        # no usable price cannot supply this tool's quote row, and it is recorded
        # as NO_DATA rather than counted as an answer.
        # Likewise a row associated with a failed per-symbol attempt contributes
        # no reading and its typed failure remains attached to this symbol.
        for provider in list(readings):
            if (
                readings[provider].get("price") is None
                or provider in row_failures[symbol]
            ):
                del readings[provider]
                if provider not in row_failures[symbol]:
                    row_failures[symbol][provider] = _batch_no_data(
                        provider, symbol, f"no usable {provider} quote row returned for {symbol}"
                    )

        misses = {
            provider: (
                row_failures[symbol][provider]["message"]
                if provider in row_failures[symbol]
                else (entry[provider].note or "no ticker")
            )
            for provider in ALL_PROVIDERS
            if not entry[provider].found or provider in row_failures[symbol]
        }
        if symbol in bb_skipped or symbol in budget_cutoffs:
            misses[BLOOMBERG] = (
                "not asked: the Bloomberg leg's "
                f"{BLOOMBERG_BATCH_BUDGET_SECONDS:.0f}s batch budget was spent "
                "on the earlier tickers"
                if symbol in budget_cutoffs
                else f"not asked: Bloomberg batch cap is {BLOOMBERG_BATCH_MAX} tickers"
            )
        errors = [
            row_failures[symbol][provider]
            for provider in ALL_PROVIDERS
            if provider in row_failures[symbol]
        ]

        if not readings:
            out_rows.append(
                {
                    "symbol": symbol,
                    "data_provider": DataProvider.NONE.value,
                    "verification": "UNAVAILABLE",
                    "resolutions": entry["resolutions"],
                    # Why each provider contributed nothing, so "NONE" is
                    # diagnosable rather than mysterious.
                    "misses": misses,
                    "errors": errors,
                    "providers_answered": [],
                    "asked": asked_for_symbol(symbol),
                }
            )
            continue

        stamps = {p: r.get("price_timestamp") for p, r in readings.items()}
        # Same guards as ``stock_quote``: a delayed print (Bloomberg is 15
        # minutes behind on equities) is a different observation, not a
        # disagreement, and a screener row with no print time cannot prove
        # otherwise.
        #
        # ``require_all_times`` is what makes that last clause real. Finviz's
        # screener row carries no print time at all (``last_update`` is absent,
        # unlike its quote page), so without this flag the session guard simply
        # never fires for that leg and yesterday's Finviz price is compared
        # against today's TradingView one. That produced two different verdicts
        # for one symbol: ``stock_quote`` reported the pair as not comparable
        # while ``stock_prices`` reported ``agrees: false``, on the same data.
        # A reading that cannot be dated cannot be shown to be the same
        # observation, so it is not comparable, not a conflict.
        price_cmp = compare_values(
            {p: r.get("price") for p, r in readings.items()},
            tolerance_pct=0.5,
            times=stamps,
            max_skew_seconds=SKEW_LIMIT_SECONDS,
            session_boundary=True,
            require_all_times=True,
        )
        change_cmp = compare_values(
            {p: r.get("change_percent") for p, r in readings.items()},
            tolerance_pct=2.0,
            absolute_floor=0.05,
            times=stamps,
            max_skew_seconds=SKEW_LIMIT_SECONDS,
            session_boundary=True,
            require_all_times=True,
            # Same rule as ``stock_quote``: an FX day change has no shared
            # baseline, so it is reported but never called a conflict.
            not_comparable_reason=(
                _FX_DAY_CHANGE_REASON
                if _is_fx(
                    entry["TRADINGVIEW"], entry["FINVIZ"], entry["YAHOO"],
                    entry["SA"], entry["BLOOMBERG"],
                )
                else None
            ),
        )
        agree = (
            None
            if price_cmp["match"] is None and change_cmp["match"] is None
            else price_cmp["match"] is not False and change_cmp["match"] is not False
        )

        # Same arbitration rule as ``stock_quote``: newest print wins, ties are
        # broken by the documented default order. Using one rule in both places
        # matters, otherwise the same symbol can report different prices
        # depending on which tool asked.
        winner, freshness = _resolved_label(
            {p: r.get("price_timestamp") for p, r in readings.items()}
        )
        if winner not in readings:
            winner = next(
                (p for p in DEFAULT_ORDER if p in readings),
                next(iter(readings)),
            )
            freshness["chosen"] = winner

        source = readings[winner]
        # The session the served price belongs to, taken from the winning
        # provider. A reading that carried no session label falls back to the
        # clock time of its own print, so the field is populated whenever the
        # print can be dated at all.
        winner_session = source.get("session") or market_session(
            parse_market_timestamp(source.get("price_timestamp"))
        )
        # Per-field provenance, because ``data_provider`` describes the row, not
        # each number in it. A row can read ``ALL`` while ``previous_close`` came
        # from one provider that happened to shape it.
        #
        # ``compared`` means "was judged here", so only the two fields this tool
        # actually cross-checks carry a compared set. The rest say who supplied a
        # reading and leave ``compared`` empty, because listing every provider
        # that happened to have the number would claim a check that never ran.
        def _freshness_rank(provider: str) -> tuple[int, float, int]:
            """Sort key: newest print first, undated providers last.

            A provider with no usable print time cannot argue that its reading is
            current, so it must not outrank a provider that can. Within the same
            print instant the documented order decides, exactly as it does for a
            tie between compared fields.
            """
            stamp = parse_market_timestamp(readings[provider].get("price_timestamp"))
            order_index = DEFAULT_ORDER.index(provider) if provider in DEFAULT_ORDER else 99
            if stamp is None:
                return (1, 0.0, order_index)
            return (0, -stamp.timestamp(), order_index)

        order = sorted(readings, key=_freshness_rank)

        def _fill(name: str) -> tuple[Any, str]:
            """The value and the provider it came from, freshest provider first.

            An uncontested field is filled from whichever provider has it, using
            the same freshness rule the compared fields use. Reading it off
            ``source`` alone dropped data: TradingView usually prints most
            recently and does not carry ``previous_close``, so every row reported
            ``null`` for a number four other providers had shaped.
            """
            for provider in order:
                value = readings[provider].get(name)
                if value is not None:
                    return value, provider
            return None, winner

        def _compared_field(name: str, comparison: dict[str, Any]) -> dict[str, Any]:
            supplied = [p for p, r in readings.items() if r.get(name) is not None]
            return field_source(
                winner,
                compared_providers(comparison),
                comparison.get("match"),
                supplied=supplied or [winner],
            )

        def _uncompared_field(name: str) -> tuple[Any, dict[str, Any] | None]:
            """A field this tool serves but does not judge.

            ``previous_close`` and ``volume`` are not in this tool's comparison
            set: only ``price`` and ``change_percent`` are cross-checked. So
            ``compared`` is empty here, not the list of providers that happened
            to have the number, and ``agreement`` stays ``None``. ``supplied``
            still names everyone who answered, because that is a separate and
            still useful fact.
            """
            value, source = _fill(name)
            if source is None:
                return value, None
            supplied = [p for p, r in readings.items() if r.get(name) is not None]
            return value, field_source(
                source, (), None, supplied=supplied or [source]
            )

        previous_close, previous_close_field = _uncompared_field("previous_close")
        # A row's price, its day change and its previous close have to describe
        # one session. Taking the previous close from whichever provider happens
        # to hold the freshest copy broke that: a pre-market price was paired
        # with a close two sessions old, so the row implied a day change the
        # response never claimed and no provider reported. When the winning
        # provider states the close its own print is measured against, that is
        # the baseline, because it belongs to the same observation as the price.
        reference = source.get("reference_close")
        if reference is not None:
            previous_close = reference
            previous_close_field = field_source(
                winner,
                (),
                None,
                supplied=[p for p, r in readings.items() if r.get("previous_close") is not None]
                or [winner],
            )
        volume, volume_field = _uncompared_field("volume")
        fields = {
            "price": _compared_field("price", price_cmp),
            "change_percent": _compared_field("change_percent", change_cmp),
        }
        if previous_close_field is not None:
            fields["previous_close"] = previous_close_field
        if volume_field is not None:
            fields["volume"] = volume_field
        # What this row's call actually asked. Two filters, both needed:
        #
        # * a provider that resolved as not-carried was never asked
        #   (``NOT_ATTEMPTED``), and neither was a provider whose whole leg
        #   answered ``NOT_ATTEMPTED`` for the batch (no endpoint for this kind
        #   of request, the instrument is not carried). Their silence cannot turn
        #   a row into PARTIAL.
        # * a ticker the Bloomberg batch budget cut off was never asked either.
        #
        # A provider that was asked and produced nothing stays in the set, and
        # then the row honestly reads PARTIAL instead of claiming ALL.
        asked_for = asked_for_symbol(symbol)
        row_provider = provider_from_answered(list(readings), asked_for)
        row: dict[str, Any] = {
            "symbol": symbol,
            "price": source.get("price"),
            "change_percent": source.get("change_percent"),
            "previous_close": previous_close,
            "volume": volume,
            # Which session the price above is a print from. Without it a
            # caller cannot tell the regular session's last trade from a
            # pre-market print, and the two differ by however far the market
            # has moved since, which is the whole reason this field exists.
            "session": winner_session,
            # Which provider field the price was read from. The swap from a
            # stale regular value to a session print is invisible otherwise, so
            # the field name makes the provenance auditable instead of implied.
            "price_field": source.get("price_field"),
            "fields": fields,
            "company": next(
                (r.get("company") for r in readings.values() if r.get("company")), None
            ),
            "data_provider": row_provider.value,
            "verification": verification_for(row_provider).value,
            "asked": asked_for,
            "agrees": agree,
            "price_source": winner,
            "freshness": freshness,
            "providers_answered": [
                p for p in ALL_PROVIDERS if p in readings
            ],
            "misses": misses,
            "errors": errors,
            "comparisons": {"price": price_cmp, "change_percent": change_cmp},
            "resolutions": entry["resolutions"],
        }
        if readings.get(BLOOMBERG, {}).get("exchange_delay"):
            # The delay is a property of the reading, so it travels with it
            # instead of only being visible in ``comparisons``.
            row["exchange_delay"] = readings[BLOOMBERG]["exchange_delay"]
        out_rows.append(row)

    # A provider-wide failure is copied to each affected row. Publish those
    # symbol-tagged copies in the envelope instead of repeating its summary;
    # retain an unscoped failure only when no row represents it.
    envelope_errors = [
        error
        for failures in row_failures.values()
        for error in failures.values()
    ] + [
        error for error in pair.errors
        if error.get("provider") not in {
            provider for failures in row_failures.values() for provider in failures
        }
    ]
    answered = {
        p for r in out_rows for p in r.get("providers_answered", [])
    }
    # Coverage applies to each provider-symbol request. A provider answering
    # AAPL has not also answered an empty MSFT row, so a per-provider union
    # would falsely make this mixed batch ALL.
    any_row_incomplete = any(
        provider in row.get("asked", [])
        and provider not in row.get("providers_answered", [])
        for row in out_rows
        for provider in ALL_PROVIDERS
    )
    overall_provider = provider_from_answered(
        [provider for provider in ALL_PROVIDERS if provider in answered],
        [provider for provider, symbols in asked_by_provider.items() if symbols],
    )
    if any_row_incomplete and len(answered) >= 2:
        overall_provider = DataProvider.PARTIAL
    skip_warnings: list[str] = []
    if bb_skipped:
        skip_warnings.append(
            "Bloomberg was not asked about "
            + ", ".join(bb_skipped)
            + f": its page path is paced at 10 s per request, so a batch asks it "
            f"about at most {BLOOMBERG_BATCH_MAX} tickers. Those rows are not "
            "counted as Bloomberg-answered."
        )
    if budget_cutoffs:
        skip_warnings.append(
            "Bloomberg was not asked about "
            + ", ".join(symbol for symbol in requested if symbol in budget_cutoffs)
            + f" because the {BLOOMBERG_BATCH_BUDGET_SECONDS:.0f}s batch budget "
            "was spent on earlier tickers (its page path is paced at 10 s per "
            "request). Those rows are not counted as Bloomberg-answered; ask "
            "again for a fresh attempt."
        )

    return finalize(
        pair,
        specs=(),
        sources={
            TRADINGVIEW: "scanner.tradingview.com",
            FINVIZ: "finviz.com/screener/stocks",
            YAHOO: "query1.finance.yahoo.com/v8/finance/chart",
            SA: "stockanalysis.com/api/quotes/s/<ticker>",
            BLOOMBERG: "bloomberg.com/quote/<id>",
        },
        extra={"symbols": requested, "errors": envelope_errors},
        warnings=skip_warnings,
        data=out_rows,
        provider=overall_provider,
        answered=[
            provider for provider in ALL_PROVIDERS if provider in answered
        ],
        comparisons=[
            {
                "field": field,
                "symbol": row["symbol"],
                **row["comparisons"][field],
            }
            for row in out_rows
            for field in ("price", "change_percent")
            if field in row.get("comparisons", {})
        ],
        health_warn=MONITOR.warnings_for(providers_in(pair) or ALL_PROVIDERS),
        degraded=any(
            issue["provider"] in providers_in(pair) for issue in MONITOR.issues()
        ),
    )


# ── Screener ─────────────────────────────────────────────────────────────────


async def stock_screener(
    country: str = "america",
    sort_by: str = "market_cap",
    limit: int = 25,
    finviz_filters: str | None = None,
) -> dict[str, Any]:
    """Run the US stock screener on both providers and cross-check the rows.

    TradingView ranks the entire market server-side (``sort_by`` ∈
    ``market_cap``, ``dividend_yield``, ``change``, ``price``); Finviz can be
    narrowed with its own filter language (``finviz_filters``, e.g.
    ``cap_smallover,sec_technology`` or ``t=AAPL,MSFT``).

    The cross-check is only meaningful if both providers describe the *same*
    instruments. Finviz is therefore asked about the tickers TradingView
    ranked, not for an independent ranking of its own: comparing a market-cap
    ranking against a day-%-change ranking yielded zero overlapping rows on
    every call, so the "multi-source" screener was silently single-source.

    Args:
        country: TradingView market (``america``, ``turkey``, …).
        sort_by: TradingView sort key.
        limit: Rows to request from TradingView (≤200 on Finviz).
        finviz_filters: Optional Finviz filter expression.

    Returns:
        Envelope with ``rows`` (TradingView ranking) and a per-row
        ``finviz_match`` showing whether Finviz agreed. Filters narrow that
        same universe rather than requesting a separate Finviz ranking.
    """
    capped = max(1, min(int(limit), 200))

    # TradingView must answer first: its ranking defines the universe both
    # providers are then asked about. The reconciler is still the boundary that
    # turns failures into data, so each leg goes through ``ask`` and the two
    # attempts are merged into one pair.
    tv_pair = await ask(
        lambda: tv_access.stock_screen(
            country=country, limit=capped, sort_by=sort_by
        ),
        None,
        None,
    )
    tv_result = tv_pair.tv.payload or {}
    tv_rows = tv_result.get("rows") or []

    async def fv_call() -> dict[str, Any]:
        # Ask Finviz about the very tickers TradingView returned.
        tickers = [
            to_finviz(str(row.get("symbol") or ""))
            for row in tv_rows
            if row.get("symbol")
        ]
        if not tickers:
            raise NotApplicable(
                FINVIZ,
                "TradingView returned no tickers, so there is nothing to cross-check",
            )
        # Filters narrow the same TradingView-selected universe. They do not
        # replace those tickers with an independent Finviz ranking.
        return {
            "rows": await fv_access.screener_rows(tickers, filters=finviz_filters)
        }

    # Yahoo has no screener endpoint, so it is not asked, ``None`` records
    # that as NOT_ATTEMPTED rather than as a provider failure.
    fv_pair = await ask(None, fv_call if tv_rows else None, None)

    pair = Pair(
        attempts={
            TRADINGVIEW: tv_pair.tv,
            FINVIZ: fv_pair.fv,
            YAHOO: fv_pair.yh,
        }
    )

    fv_rows = (pair.fv.payload or {}).get("rows") or []
    fv_by_symbol = {str(r.get("ticker", "")).upper(): r for r in fv_rows}

    from .reconcile import compare_values
    merged_rows = []
    agreed = compared = not_comparable = 0
    tv_stamp = (pair.tv.payload or {}).get("as_of") or (pair.tv.payload or {}).get(
        "fetched_at"
    )
    for row in tv_rows:
        symbol = str(row.get("symbol") or "").upper()
        # Finviz spells share classes with a dot (BRK.B), TradingView with a
        # dash (BRK-B); normalise before matching or those rows never join.
        fv_row = fv_by_symbol.get(symbol) or fv_by_symbol.get(to_finviz(symbol))
        # Cross-check the *price*. A screener row's day change is measured from
        # the previous close of whichever session the row belongs to, and Finviz
        # screener rows carry no print time to prove the two are the same
        # session, so a change-% "match" would be an unverifiable claim. The
        # price is the instrument's current value on both sides and is directly
        # comparable; both change readings are still reported for the reader.
        comparison = compare_values(
            {
                TRADINGVIEW: row.get("price"),
                FINVIZ: (fv_row or {}).get("price"),
            },
            tolerance_pct=0.5,
            # A screener price is only comparable if both sides describe the
            # same session. The Finviz screener payload has no print time at
            # all, so the match cannot be *proven*: it is reported as not
            # comparable rather than asserted as agreement or as a conflict.
            times={
                TRADINGVIEW: tv_stamp,
                FINVIZ: (fv_row or {}).get("last_update"),
            },
            max_skew_seconds=SKEW_LIMIT_SECONDS if tv_stamp else None,
            require_all_times=True,
        )
        answered = [
            provider
            for provider, value in (
                (TRADINGVIEW, row.get("price")),
                (FINVIZ, (fv_row or {}).get("price")),
            )
            if value is not None
        ]
        entry = {
            "symbol": symbol,
            "company": row.get("description"),
            "price": row.get("price"),
            "change_percent": row.get("change_percent"),
            "market_cap": row.get("market_cap"),
            "ticker": row.get("ticker"),
            "data_provider": provider_from_answered(answered).value,
            "providers_answered": answered,
        }
        if fv_row:
            entry["finviz_price"] = fv_row.get("price")
            entry["finviz_change_percent"] = fv_row.get("change")
            entry["finviz_match"] = comparison["match"]
            entry["comparison"] = comparison
            compared += 1
            if comparison["match"] is True:
                agreed += 1
            elif comparison["match"] is None:
                not_comparable += 1
        merged_rows.append(entry)

    data = {
        "country": country,
        "sort_by": sort_by,
        "tradingview_total_matches": (pair.tv.payload or {}).get("total_matches"),
        "rows": merged_rows,
        "finviz_rows": len(fv_rows),
        "cross_checked_rows": compared,
        # Counted only when the readings genuinely agreed. A row whose two
        # prints straddle a session boundary is *not* evidence of agreement,
        # so it is reported separately rather than inflating this number.
        "agreeing_rows": agreed,
        "not_comparable_rows": not_comparable,
    }
    warnings: list[str] = []
    if compared and agreed == 0 and not_comparable == compared:
        # ``ALL`` here means "both answered", not "both corroborated": the
        # Finviz screener payload has no print time, so no row could be
        # confirmed against TradingView. Say so rather than let coverage read
        # as verification.
        warnings.append(
            "Finviz screener rows carry no print time, so no row could be "
            "confirmed against TradingView; every row is single-source coverage, "
            "not a cross-check."
        )
    return finalize(
        pair,
        specs=(),
        sources={
            TRADINGVIEW: "scanner.tradingview.com",
            FINVIZ: "finviz.com/screener/stocks",
        },
        warnings=warnings,
        extra={"screener": data},
        data=data,
        health_warn=MONITOR.warnings_for(providers_in(pair) or ALL_PROVIDERS),
        degraded=any(
            issue["provider"] in providers_in(pair) for issue in MONITOR.issues()
        ),
    )


# ── Indices ──────────────────────────────────────────────────────────────────


async def market_indices() -> dict[str, Any]:
    """Level and day change for the major US indices, asked of every capable provider.

    Covers the fixed snapshot list (``INDEX_SNAPSHOT``: S&P 500, Dow, Nasdaq
    Composite, Russell 2000, IWM and VIX), not every index the instrument
    registry addresses: ``NDX`` is a registry row too, but it is quoted through
    the single-instrument tools. Every provider spells these differently
    (``SPX`` / ``SP:SPX`` / ``^GSPC``); they are mapped to one canonical name
    before comparison, and the level is compared across all providers that
    answered.

    Returns:
        Envelope whose ``data.indices`` is keyed by canonical index
        (``SPX``, ``DJI``, ``COMP``, ``RUT``, ``IWM``, ``VIX``), each value
        carrying ``level``, ``change_percent``, its own ``data_provider`` and
        the raw readings from every provider that supplied it.
    """

    async def tv_call() -> dict[str, Any]:
        return await tv_access.index_snapshot()

    async def fv_call() -> dict[str, Any]:
        return await fv_access.indices()

    async def yh_call() -> dict[str, Any]:
        return await yh_access.index_snapshot()

    pair = await ask(tv_call, fv_call, yh_call)
    tv_norm = tv_indices_fields(pair.tv.payload) if pair.tv.payload else None
    fv_norm = fv_indices_fields(pair.fv.payload) if pair.fv.payload else None
    yh_norm = tv_indices_fields(pair.yh.payload) if pair.yh.payload else None

    tv_indices = (tv_norm or {}).get("indices") or {}
    fv_indices = (fv_norm or {}).get("indices") or {}
    yh_indices = (yh_norm or {}).get("indices") or {}

    from .freshness import parse_market_timestamp, session_date
    from .reconcile import DEFAULT_ORDER, _resolved_label, compare_values

    indices: dict[str, Any] = {}
    for canonical in INDEX_SNAPSHOT:
        readings = {
            TRADINGVIEW: (tv_indices.get(canonical) or {}).get("level"),
            FINVIZ: (fv_indices.get(canonical) or {}).get("level"),
            YAHOO: (yh_indices.get(canonical) or {}).get("level"),
        }
        present = {p: v for p, v in readings.items() if v is not None}
        if not present:
            continue
        fv_row = fv_indices.get(canonical) or {}
        tv_row = tv_indices.get(canonical) or {}
        yh_row = yh_indices.get(canonical) or {}
        stamps = {
            TRADINGVIEW: tv_row.get("price_timestamp"),
            FINVIZ: fv_row.get("price_timestamp"),
            YAHOO: yh_row.get("price_timestamp"),
        }
        # Same arbitration as single-instrument quotes: newest print wins. A
        # provider that has already rolled into the next session must not be
        # called "wrong", it is simply newer, and its level is the one shown.
        winner, freshness = _resolved_label(
            {p: stamps[p] for p in present if stamps.get(p) is not None}
        )
        if winner not in present:
            winner = next(iter(present))
            freshness["chosen"] = winner
        # Compare levels only between providers looking at the same session.
        # A 1 % "disagreement" between yesterday's close and today's live level
        # is a freshness difference, not a data conflict.
        level_cmp = compare_values(
            readings,
            # VIX is a volatility gauge that moves percent-level within a
            # minute; judging it on the 0.5 % tolerance used for index levels
            # reports a data conflict where there is only a fast market.
            tolerance_pct=3.0 if canonical == "VIX" else 0.5,
            times=stamps,
            max_skew_seconds=SKEW_LIMIT_SECONDS,
            session_boundary=True,
        )
        # The day-quote block resolves as one session, not one provider. A level,
        # its previous close, the day change and the day-change percent are four
        # views of one observation, so reading them off different providers mixes
        # two sessions into a single row and the numbers contradict each other on
        # the page: SPX reported a level 0.74 % above its previous close next to
        # a day change of -0.38 %, because the level and the previous close came
        # from the provider that had rolled into today while the change percent
        # came from whichever row was listed first (yesterday's session).
        #
        # So the block is filled from providers whose print belongs to the
        # *winner's* session date, in freshness order, and a provider from
        # another session never lends a number. This keeps the data the session
        # actually has: TradingView's index rows carry no previous close, so
        # without the same-session fallback a TradingView win would blank a
        # number Finviz had shaped from the same session.
        blocks = {TRADINGVIEW: tv_row, FINVIZ: fv_row, YAHOO: yh_row}
        winner_stamp = parse_market_timestamp(stamps.get(winner))
        winner_day = session_date(winner_stamp)
        # Freshness order, winner first, then the documented order. A provider
        # from another session is excluded outright, not merely ranked last: its
        # previous close belongs to a different observation, and pairing it with
        # the winner's level is the contradiction this block exists to prevent.
        # Only a provider with no print time at all (so no session it can be
        # shown to disagree with) is consulted as a last resort.
        same_session = [
            p for p in [winner] + [q for q in DEFAULT_ORDER if q != winner]
            if p in blocks
            and (
                winner_day is None
                or session_date(parse_market_timestamp(stamps.get(p))) == winner_day
            )
        ]
        undated = [
            p
            for p in [winner] + list(DEFAULT_ORDER)
            if p in blocks
            and p not in same_session
            and parse_market_timestamp(stamps.get(p)) is None
        ]

        def _resolve(name: str) -> tuple[Any, str | None]:
            """The value for one day-quote field and the provider it came from."""
            for provider in same_session + undated:
                value = blocks[provider].get(name)
                if value is not None:
                    return value, provider
            return None, None

        fields: dict[str, dict[str, Any]] = {
            "level": field_source(winner, compared_providers(level_cmp), level_cmp.get("match"), supplied=[winner])
        }
        shaped_values: dict[str, Any] = {}
        for name in ("previous_close", "change", "change_percent"):
            value, provider = _resolve(name)
            shaped_values[name] = value
            if provider is not None:
                fields[name] = field_source(
                    provider, (), None, supplied=[provider]
                )

        indices[canonical] = {
            "name": fv_row.get("name") or tv_row.get("name") or canonical,
            "level": present[winner],
            "level_source": winner,
            "freshness": freshness,
            **shaped_values,
            "fields": fields,
            # Row coverage counts the providers that supplied *this index*. A
            # feed that answered but lists no row for it is read the same way
            # ``resolve`` reads an instrument a provider does not carry: not
            # asked about it, not a failure. Finviz publishes no RUT or VIX row
            # and TradingView no IWM, and those are boundaries, not outages; the
            # provider-level failures would be invisible in a per-index label
            # anyway, and the envelope's own state reports them.
            "data_provider": provider_from_answered(list(present)).value,
            "verification": verification_for(
                provider_from_answered(list(present))
            ).value,
            "providers_answered": [p for p in ALL_PROVIDERS if p in present],
            "readings": present,
            "comparison": {"level": level_cmp},
            "agree": level_cmp["match"] is not False,
        }

    multi = {
        canonical: row for canonical, row in indices.items()
        if row["data_provider"] == DataProvider.ALL.value
    }
    answered = {p for row in indices.values() for p in row["providers_answered"]}
    overall = provider_from_answered(answered, pair.asked)
    return finalize(
        pair,
        specs=(),
        sources={
            TRADINGVIEW: "scanner.tradingview.com (indices)",
            FINVIZ: "https://finviz.com/api/indices_data",
            YAHOO: "query1.finance.yahoo.com/v8/finance/chart",
        },
        extra={"index_set": sorted(indices), "multi_source_indices": sorted(multi)},
        data={"indices": indices},
        provider=overall,
        health_warn=MONITOR.warnings_for(providers_in(pair) or ALL_PROVIDERS),
        degraded=any(
            issue["provider"] in providers_in(pair) for issue in MONITOR.issues()
        ),
    )


# ── News ─────────────────────────────────────────────────────────────────────


async def stock_news(symbol: str, limit: int = 20, include_reactions: bool = True) -> dict[str, Any]:
    """Headlines for one ticker from every provider that publishes them.

    Finviz supplies headlines with the price reaction around each item (the
    day-of move and, when the story broke after the close, the next session's
    move). TradingView's side is the provider's licensed news feed, Yahoo adds
    its search feed. Headline titles are matched across feeds to report overlap.

    Args:
        symbol: Ticker.
        limit: Maximum headlines per provider.
        include_reactions: Ask Finviz for price-reaction columns.

    Returns:
        Envelope with ``data.items`` (Finviz ordering, which carries reactions)
        and ``data.overlap`` describing how many TradingView headlines were also
        present on Finviz.
    """
    ticker = strip_exchange(symbol).upper()
    resolved = await _symbols_for(symbol)

    async def tv_call() -> dict[str, Any]:
        # Headlines are not a price feed, so the licensed news leg is the honest
        # source here; without MARKETAUX_API_TOKEN it has nothing to return.
        return await tv_access.news(resolved["TRADINGVIEW"].symbol or ticker)

    async def fv_call() -> dict[str, Any]:
        if not resolved["FINVIZ"].found:
            raise NotApplicable(FINVIZ, resolved["FINVIZ"].note or "Finviz has no page")
        return await fv_access.news(
            resolved["FINVIZ"].symbol, limit=limit, include_reactions=include_reactions
        )

    async def yh_call() -> dict[str, Any]:
        if not resolved["YAHOO"].found:
            raise NotApplicable(YAHOO, resolved["YAHOO"].note or "no Yahoo symbol")
        return await yh_access.news(resolved["YAHOO"].symbol, limit=limit)

    pair = await ask(tv_call, fv_call, yh_call)
    tv_norm = tv_news_fields(pair.tv.payload) if pair.tv.payload else None
    fv_norm = fv_news_fields(pair.fv.payload) if pair.fv.payload else None
    yh_norm = yahoo_news_fields(pair.yh.payload) if pair.yh.payload else None

    tv_items = (tv_norm or {}).get("items") or []
    fv_items = (fv_norm or {}).get("items") or []
    yh_items = (yh_norm or {}).get("items") or []
    overlap = None
    if tv_items and fv_items:
        overlap = news_overlap(tv_items, fv_items)
    yahoo_overlap = None
    if yh_items and fv_items:
        yahoo_overlap = news_overlap(yh_items, fv_items)

    items = fv_items or yh_items or tv_items
    data = {
        "ticker": ticker,
        "items": items,
        "tradingview_items": tv_items,
        "yahoo_items": yh_items,
        "overlap": overlap,
        "yahoo_overlap": yahoo_overlap,
        "count": len(items),
    }
    return finalize(
        pair,
        specs=(),
        sources={
            TRADINGVIEW: "Marketaux news feed (via TradingView provider)",
            FINVIZ: f"https://finviz.com/api/news/quote/{resolved['FINVIZ'].symbol or ticker}",
            YAHOO: "query1.finance.yahoo.com/v1/finance/search",
        },
        extra={"news": data, "resolutions": resolved["resolutions"]},
        data=data,
        health_warn=MONITOR.warnings_for(providers_in(pair) or ALL_PROVIDERS),
        degraded=any(
            issue["provider"] in providers_in(pair) for issue in MONITOR.issues()
        ),
    )


# ── Options ──────────────────────────────────────────────────────────────────


def _option_chain_expiry(chain: dict[str, Any] | None) -> str | None:
    """Return a chain's single evidenced expiry, not an arbitrary provider's."""
    if not chain:
        return None
    rows = chain["calls"] + chain["puts"]
    dates = {chain.get("expiry")} if chain.get("expiry") is not None else set()
    for row in rows:
        if row.get("expiry") is None:
            return None
        dates.add(row["expiry"])
    return next(iter(dates)) if len(dates) == 1 else None


async def stock_options_chain(symbol: str, expiry: str | None = None) -> dict[str, Any]:
    """Multi-source options chain for one expiry.

    Finviz and Yahoo both publish a chain; contracts are matched by side,
    expiry and strike, then their volume and open interest are compared, so an
    agent can see whether the two chains agree on open positioning. TradingView
    has no chain, but its scanner independently quotes the underlying the
    contracts are priced against.

    Args:
        symbol: Underlying ticker.
        expiry: ``YYYY-MM-DD``; ``None`` uses each provider's nearest expiry.

    Returns:
        Envelope with ``data.calls``/``data.puts`` (Finviz, which carries full
        greeks), the Yahoo chain, and ``data.overlap``.
    """
    resolved = await _symbols_for(symbol)
    ticker = strip_exchange(symbol).upper()

    async def tv_call() -> dict[str, Any]:
        # TradingView publishes no options chain, but its scanner does quote the
        # underlying, so the price the chain is priced against is still
        # independently confirmed.
        if not resolved["TRADINGVIEW"].found:
            raise NotApplicable(
                TRADINGVIEW, resolved["TRADINGVIEW"].note or "no TradingView symbol"
            )
        row = await tv_access.quote(resolved["TRADINGVIEW"].symbol)
        return {"underlying_price": row.get("close"), "scanner": row}

    async def fv_call() -> dict[str, Any]:
        if not resolved["FINVIZ"].found:
            raise NotApplicable(FINVIZ, resolved["FINVIZ"].note or "Finviz has no page")
        return await fv_access.options(resolved["FINVIZ"].symbol, expiry)

    async def yh_call() -> dict[str, Any]:
        if not resolved["YAHOO"].found:
            raise NotApplicable(YAHOO, resolved["YAHOO"].note or "no Yahoo symbol")
        return await yh_access.options(resolved["YAHOO"].symbol, expiry)

    pair = await ask(tv_call, fv_call, yh_call)
    fv_norm = fv_options_fields(pair.fv.payload) if pair.fv.payload else None
    yh_norm = tv_options_fields(pair.yh.payload) if pair.yh.payload else None
    tv_scanner = pair.tv.payload or {}

    fv_calls = (fv_norm or {}).get("calls") or []
    fv_puts = (fv_norm or {}).get("puts") or []
    yh_calls = (yh_norm or {}).get("calls") or []
    yh_puts = (yh_norm or {}).get("puts") or []
    fv_expiry = _option_chain_expiry(fv_norm)
    yh_expiry = _option_chain_expiry(yh_norm)
    if fv_norm and yh_norm:
        shared_expiry = fv_expiry if fv_expiry == yh_expiry else None
    else:
        shared_expiry = fv_expiry or yh_expiry
    fv_expiries = (fv_norm or {}).get("expiries", [])
    yh_expiries = (yh_norm or {}).get("expiries", [])

    warnings = []
    overlap = None
    if fv_expiry is not None and yh_expiry is not None and fv_expiry != yh_expiry:
        overlap = {
            "not_comparable": True,
            "reason": (
                f"Finviz returned expiry {fv_expiry} while Yahoo returned "
                f"{yh_expiry}; contracts from different expiries are not compared."
            ),
            "expiries": {"FINVIZ": fv_expiry, "YAHOO": yh_expiry},
        }
        warnings.append(overlap["reason"])
    elif (fv_calls or fv_puts) and (yh_calls or yh_puts):
        overlap = {
            "calls": option_overlap(yh_calls, fv_calls),
            "puts": option_overlap(yh_puts, fv_puts),
        }
        if shared_expiry is None:
            overlap["not_comparable"] = True
            overlap["reason"] = (
                "Both chains do not identify one shared expiry; rows with missing "
                "proof of the same side, expiry and strike never count as agreement."
            )
            warnings.append(overlap["reason"])

    if fv_expiries == yh_expiries:
        available_expiries = fv_expiries
    elif not fv_expiries or not yh_expiries:
        available_expiries = fv_expiries or yh_expiries
    else:
        available_expiries = {"FINVIZ": fv_expiries, "YAHOO": yh_expiries}

    data = {
        "symbol": ticker,
        "expiry": shared_expiry,
        "expiries": available_expiries,
        "underlying_price": (fv_norm or {}).get("underlying_price")
        or (yh_norm or {}).get("underlying_price")
        or tv_scanner.get("underlying_price"),
        "tradingview_underlying_price": tv_scanner.get("underlying_price"),
        "calls": fv_calls or yh_calls,
        "puts": fv_puts or yh_puts,
        "finviz_calls": fv_calls,
        "finviz_puts": fv_puts,
        "yahoo_calls": yh_calls,
        "yahoo_puts": yh_puts,
        "contract_count": (fv_norm or {}).get("contract_count", 0) + (
            (yh_norm or {}).get("contract_count", 0) if not fv_norm else 0
        ),
        "overlap": overlap,
        "resolutions": resolved["resolutions"],
    }
    return finalize(
        pair,
        warnings=warnings,
        specs=(),
        sources={
            TRADINGVIEW: "scanner.tradingview.com (underlying price only; no chain)",
            FINVIZ: f"https://finviz.com/stock?t={resolved['FINVIZ'].symbol or ticker}&ty=oc",
            YAHOO: f"https://query2.finance.yahoo.com/v7/finance/options/{resolved['YAHOO'].symbol}",
        },
        extra={"options": data},
        data=data,
        health_warn=MONITOR.warnings_for(providers_in(pair) or ALL_PROVIDERS),
        degraded=any(
            issue["provider"] in providers_in(pair) for issue in MONITOR.issues()
        ),
    )


# ── Earnings ─────────────────────────────────────────────────────────────────


def _et_timestamp_to_iso(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


async def stock_earnings(symbol: str) -> dict[str, Any]:
    """Earnings calendar and history for one ticker.

    Finviz owns the detailed tables (reported quarters, estimate revisions,
    fundamental series, post-earnings reactions); TradingView's scanner confirms
    the next/last earnings timestamp from its own calendar. Yahoo supplies the
    next scheduled date on its own feed. The dates are reported; Finviz's last
    reported quarter never becomes ``next_earnings_date``.

    Args:
        symbol: Ticker.

    Returns:
        Envelope with ``data.next_earnings_date``, the Finviz tables and a
        ``date_comparison`` block.
    """
    resolved = await _symbols_for(symbol)
    ticker = strip_exchange(symbol).upper()

    async def tv_call() -> dict[str, Any]:
        if not resolved["TRADINGVIEW"].found:
            raise NotApplicable(
                TRADINGVIEW, resolved["TRADINGVIEW"].note or "no TradingView symbol"
            )
        return await tv_access.earnings(resolved["TRADINGVIEW"].symbol)

    async def fv_call() -> dict[str, Any]:
        if not resolved["FINVIZ"].found:
            raise NotApplicable(FINVIZ, resolved["FINVIZ"].note or "Finviz has no page")
        return await fv_access.earnings(resolved["FINVIZ"].symbol)

    async def yh_call() -> dict[str, Any]:
        # Yahoo's chart meta carries the next scheduled earnings timestamp.
        if not resolved["YAHOO"].found:
            raise NotApplicable(YAHOO, resolved["YAHOO"].note or "no Yahoo symbol")
        return await yh_access.quote(resolved["YAHOO"].symbol)

    pair = await ask(tv_call, fv_call, yh_call)

    fv_data = fv_earnings_fields(pair.fv.payload) if pair.fv.payload else {}
    tv_row = pair.tv.payload or {}
    tv_next = _et_timestamp_to_iso(tv_row.get("earnings_release_next_date"))
    tv_last = _et_timestamp_to_iso(tv_row.get("earnings_release_date"))
    yh_row = pair.yh.payload or {}
    yh_next = _et_timestamp_to_iso(yh_row.get("earnings_timestamp"))

    comparison = None
    if fv_data.get("earnings_date") or tv_next or yh_next:
        comparison = {
            "tradingview_next_earnings": tv_next,
            "yahoo_next_earnings": yh_next,
            "finviz_earnings_date": fv_data.get("earnings_date"),
            "note": "Dates come from different schedules; compare by day, not by exact timestamp.",
        }

    data = {
        "symbol": ticker,
        "finviz_earnings_date": fv_data.get("earnings_date"),
        # Finviz's date anchors the last reported quarter, never an upcoming one.
        "next_earnings_date": tv_next or yh_next,
        "finviz_note": (
            "finviz_earnings_date is the last *reported* quarter's release "
            "timestamp (the anchor for its results tables); next_earnings_date "
            "is the upcoming release from the TradingView/Yahoo calendars."
        ),
        "tradingview_last_earnings": tv_last,
        "tradingview_next_earnings": tv_next,
        "yahoo_next_earnings": yh_next,
        "latest_quarter": fv_data.get("latest_quarter"),
        "latest_eps_actual": fv_data.get("latest_eps_actual"),
        "latest_eps_estimate": fv_data.get("latest_eps_estimate"),
        "quarterly": fv_data.get("quarterly") or [],
        "annual": fv_data.get("annual") or [],
        "revisions": fv_data.get("revisions") or [],
        "price_reactions": fv_data.get("price_reactions") or [],
        "date_comparison": comparison,
        "resolutions": resolved["resolutions"],
    }
    return finalize(
        pair,
        specs=(),
        sources={
            TRADINGVIEW: "scanner.tradingview.com earnings calendar",
            FINVIZ: f"https://finviz.com/stock?t={resolved['FINVIZ'].symbol or ticker}&ty=ea",
            YAHOO: f"https://query1.finance.yahoo.com/v8/finance/chart/{resolved['YAHOO'].symbol}",
        },
        extra={"earnings": data},
        data=data,
        health_warn=MONITOR.warnings_for(providers_in(pair) or ALL_PROVIDERS),
        degraded=any(
            issue["provider"] in providers_in(pair) for issue in MONITOR.issues()
        ),
    )


# ── Extended hours ───────────────────────────────────────────────────────────


async def stock_extended_hours(symbol: str) -> dict[str, Any]:
    """Pre-/post-market and overnight prices, with per-session comparisons.

    Finviz exposes the after-hours print on the quote page; Yahoo derives
    pre/regular/post prices from its own 1-minute candles; TradingView's scanner
    carries its own pre/post prints; StockAnalysis returns an extended-hours
    block next to the regular quote. Only like pre/post sessions with usable
    print times are compared, and every raw reading and session block is returned.

    Args:
        symbol: Ticker.

    Returns:
        Envelope with ``data`` carrying ``pre_market``, ``regular``,
        ``post_market``, the Finviz after-hours block, and reconciled overnight
        readings from TradingView's BOATS socket and Yahoo's quote header.
    """
    resolved = await _symbols_for(symbol)
    ticker = strip_exchange(symbol).upper()

    async def tv_call() -> dict[str, Any]:
        # TradingView's scanner exposes pre/post prints as fields on the quote
        # row (premarket_close / postmarket_close), not as a session timeline.
        if not resolved["TRADINGVIEW"].found:
            raise NotApplicable(
                TRADINGVIEW, resolved["TRADINGVIEW"].note or "no TradingView symbol"
            )
        row = await tv_access.quote(resolved["TRADINGVIEW"].symbol)
        return {
            "premarket_close": row.get("premarket_close"),
            "premarket_change": row.get("premarket_change"),
            # The scanner returns the size of each extended session too. It was
            # requested on every quote and never read, so a pre-market print
            # arrived with no way to tell a liquid session from a single lot.
            "premarket_volume": row.get("premarket_volume"),
            "postmarket_close": row.get("postmarket_close"),
            "postmarket_change": row.get("postmarket_change"),
            "postmarket_volume": row.get("postmarket_volume"),
            "regular_close": row.get("close"),
            "regular_close_time": row.get("update_time"),
            "current_session": row.get("current_session"),
        }

    async def overnight_call() -> dict[str, Any]:
        """The overnight venue's own print, from TradingView's quote socket.

        The scanner has no row for the overnight venues at all. Its chart quote
        socket resolves BOATS independently of Yahoo's overnight quote field.
        A failed socket remains a reported failure, not a missing instrument.
        """
        if not resolved["TRADINGVIEW"].found:
            raise NotApplicable(TRADINGVIEW, "no TradingView symbol")
        bare = strip_exchange(resolved["TRADINGVIEW"].symbol or ticker).upper()
        rows = await tv_access.live_session_quotes([f"BOATS:{bare}"])
        values = rows.get(f"BOATS:{bare}") or {}
        price = values.get("lp")
        if price is None:
            raise NoDataError(TRADINGVIEW, f"overnight venue has no print for {bare}")
        if values.get("lp_time") is None:
            raise NoDataError(TRADINGVIEW, f"overnight venue has no print time for {bare}")
        return {
            "session": "overnight",
            "raw_session": values.get("current_session"),
            "price": price,
            # BOATS uses a venue baseline here, not Yahoo's last regular
            # close. Preserve it as the provider's raw reading, then derive
            # the common-baseline change from Yahoo's explicit reference.
            "reported_change": values.get("ch"),
            "reported_change_percent": values.get("chp"),
            "volume": values.get("volume"),
            "print_time": values.get("lp_time"),
            "exchange": values.get("exchange"),
            "feed_mode": values.get("update_mode"),
            "symbol": values.get("original_name"),
            "description": values.get("description"),
            "asset_class": values.get("type"),
        }

    async def fv_call() -> dict[str, Any]:
        if not resolved["FINVIZ"].found:
            raise NotApplicable(FINVIZ, resolved["FINVIZ"].note or "Finviz has no page")
        return await fv_access.quote(resolved["FINVIZ"].symbol)

    async def yh_call() -> dict[str, Any]:
        if not resolved["YAHOO"].found:
            raise NotApplicable(YAHOO, resolved["YAHOO"].note or "no Yahoo symbol")
        return await yh_access.extended_hours(resolved["YAHOO"].symbol)

    async def sa_call() -> dict[str, Any]:
        if not resolved["SA"].found:
            raise NotApplicable(
                SA, resolved["SA"].note or "StockAnalysis has no quote page"
            )
        try:
            return await sa_access.quote(resolved["SA"].symbol)
        except NoDataError as exc:
            raise NotApplicable(SA, exc.message) from exc

    async def yh_overnight_call() -> dict[str, Any]:
        """Ask Yahoo for the overnight header, preserving attempted no-data."""
        if not resolved["YAHOO"].found:
            raise NotApplicable(YAHOO, resolved["YAHOO"].note or "no Yahoo symbol")
        block = await yh_access.overnight(resolved["YAHOO"].symbol)
        if block is None:
            raise NoDataError(YAHOO, f"Yahoo has no overnight print for {ticker}")
        return block

    async def _overnight(provider: str, call) -> tuple[str, Any, dict[str, Any] | None]:
        """Collect a session reading and its typed failure without hiding either."""
        try:
            return provider, await call(), None
        except NotApplicable as exc:
            return provider, None, {
                "code": "NOT_ATTEMPTED", "message": exc.message,
            }
        except Exception as exc:  # noqa: BLE001 - a secondary endpoint cannot sink the tool
            error = _error_dict(provider, exc)
            error["detail"] = {**(error.get("detail") or {}), "capability": "overnight"}
            return provider, None, error

    # These are separate upstream capabilities, so they cannot share ``Pair``:
    # Yahoo already has the chart leg and TradingView the scanner. Their session
    # results are reconciled independently below and do not change the coverage
    # of these providers' primary pre/post fields.
    pair, overnight_results = await asyncio.gather(
        ask(tv_call, fv_call, yh_call, sa_fn=sa_call),
        asyncio.gather(
            _overnight(TRADINGVIEW, overnight_call),
            _overnight(YAHOO, yh_overnight_call),
        ),
    )

    tv = pair.tv.payload or {}
    fv_quote = pair.fv.payload or {}
    fv_after = fv_quote.get("after_hours") or {}
    yh = pair.yh.payload or {}
    sa = pair.sa.payload or {}
    sa_extended = sa.get("extended_hours") or {}

    from .reconcile import compare_values

    overnight_readings: dict[str, dict[str, Any]] = {}
    overnight_errors: list[dict[str, Any]] = []
    for provider, block, error in overnight_results:
        if error is not None:
            if error["code"] != "NOT_ATTEMPTED":
                overnight_errors.append({"provider": provider, **error})
            continue
        shaped = _shape_overnight(block)
        if shaped is not None:
            overnight_readings[provider] = shaped
    response_now = _utc_now()
    for block in overnight_readings.values():
        active, _, _ = current_session(
            block.get("print_time"), response_now, session_name=OVERNIGHT
        )
        block["is_current"] = active == OVERNIGHT
        # Overnight crosses midnight, so the wall-clock session name alone is
        # insufficient. Derive its occurrence from the print itself, including
        # the final second before 04:00 ET, not from the response clock.
        session_start = session_window_start(block.get("print_time"), OVERNIGHT)
        block["session_window_start_utc"] = (
            session_start.isoformat().replace("+00:00", "Z")
            if session_start is not None
            else None
        )
    yh_overnight_reference = (
        overnight_readings.get(YAHOO) or {}
    ).get("reference_close")
    for block in overnight_readings.values():
        yahoo = overnight_readings.get(YAHOO)
        session_start = block.get("session_window_start_utc")
        same_occurrence = (
            yahoo is not None
            and session_start is not None
            and session_start == yahoo.get("session_window_start_utc")
        )
        if (
            same_occurrence
            and isinstance(yh_overnight_reference, (int, float))
            and math.isfinite(yh_overnight_reference)
            and yh_overnight_reference > 0
            and isinstance(block.get("price"), (int, float))
        ):
            price = block["price"]
            block["change"] = price - yh_overnight_reference
            block["change_percent"] = (
                block["change"] / yh_overnight_reference * 100
            )
            block["reference_close"] = yh_overnight_reference
            block["change_reference"] = "YAHOO.reference_close"
        else:
            # Do not borrow another evening's or session's close merely
            # because the selected primary print served it earlier.
            block["change"] = None
            block["change_percent"] = None
            block["reference_close"] = None
            block["change_reference"] = None
    overnight_comparison = compare_values(
        {provider: block["price"] for provider, block in overnight_readings.items()},
        tolerance_pct=0.5,
        times={provider: block["print_time"] for provider, block in overnight_readings.items()},
        sessions={
            provider: block["session_window_start_utc"]
            for provider, block in overnight_readings.items()
        },
        max_skew_seconds=SKEW_LIMIT_SECONDS,
        session_boundary=False,
        require_all_times=True,
    )
    current_overnight = {
        provider: block for provider, block in overnight_readings.items()
        if block["is_current"]
    }
    candidates = current_overnight or overnight_readings
    dated_candidates = {
        provider: parse_market_timestamp(block.get("print_time"))
        for provider, block in candidates.items()
    }
    if any(stamp is not None for stamp in dated_candidates.values()):
        overnight_source = max(
            candidates,
            key=lambda provider: (
                dated_candidates[provider] is not None,
                dated_candidates[provider] or datetime.min.replace(tzinfo=timezone.utc),
            ),
        )
    else:
        overnight_source = next((p for p in (YAHOO, TRADINGVIEW) if p in candidates), None)

    def _extended_reading(
        price: Any, session: str | None, timestamp: Any,
    ) -> dict[str, Any]:
        """Return one session print with a normalized clock and its own baseline."""
        instant = parse_market_timestamp(timestamp)
        return {
            "price": price,
            "session": session,
            "timestamp": timestamp,
            "as_of_utc": instant.isoformat().replace("+00:00", "Z")
            if instant is not None
            else None,
            "reference_close": None,
            "change": None,
            "change_percent": None,
            "change_reference": None,
        }

    tv_session = _SESSION_NAMES.get(str(tv.get("current_session") or "").lower())
    tv_block = PRE_MARKET if tv_session == PRE_MARKET else "post_market"
    if tv_session not in (PRE_MARKET, "post_market"):
        tv_session = None
    readings = {
        TRADINGVIEW: _extended_reading(
            tv.get("premarket_close" if tv_block == PRE_MARKET else "postmarket_close"),
            tv_session,
            # ``update_time`` belongs to ``close``, not the extended print.
            # The scanner publishes no time for that separate print, so keep
            # it undated instead of dating it to yesterday's regular close.
            None,
        ),
        # Finviz calls this block after-hours even during the pre-market. Its
        # own timestamp, not that label, says which session it printed in.
        FINVIZ: _extended_reading(
            fv_after.get("price"),
            market_session(parse_market_timestamp(fv_after.get("date"))),
            fv_after.get("date"),
        ),
        # StockAnalysis names the extended window even when it supplies no
        # timestamp. Preserve that label without letting an undated print agree.
        SA: _extended_reading(
            sa_extended.get("price"),
            _SESSION_NAMES.get(
                str(sa_extended.get("session") or "").lower().replace("-", "_")
            )
            or market_session(parse_market_timestamp(sa_extended.get("price_timestamp"))),
            sa_extended.get("price_timestamp"),
        ),
    }
    if tv_session is not None:
        yahoo_session = yh.get(tv_session) or {}
        readings[YAHOO] = _extended_reading(
            yahoo_session.get("price"), tv_session,
            yahoo_session.get("as_of_utc") or yahoo_session.get("price_timestamp"),
        )
    else:
        # No active-window statement: use the most recent named extended print,
        # never a pre/post fallback of the opposite session merely because it
        # is populated. Two undated extended reads remain visible but unjudged.
        dated = [
            (name, block, parse_market_timestamp((block or {}).get("as_of_utc")))
            for name, block in (
                (PRE_MARKET, yh.get(PRE_MARKET)),
                (POST_MARKET, yh.get(POST_MARKET)),
            )
        ]
        dated = [(name, block, stamp) for name, block, stamp in dated if block and stamp]
        if dated:
            yahoo_session, yahoo_block, yahoo_stamp = max(dated, key=lambda item: item[2])
            readings[YAHOO] = _extended_reading(
                yahoo_block.get("price"), yahoo_session, yahoo_stamp,
            )
    readings = {
        provider: reading
        for provider, reading in readings.items()
        if reading["price"] is not None
    }
    for provider, reading in readings.items():
        session = reading["session"]
        block = yh.get(session) if provider == YAHOO else None
        reference = None
        reference_source = None
        # Finviz calls its extended block after-hours without proving which
        # named window it belongs to. Keep that session undated, but do not
        # discard an otherwise usable baseline just because the clock is missing.
        if session not in (PRE_MARKET, POST_MARKET) and provider != FINVIZ:
            continue
        if provider == YAHOO and isinstance(block, dict):
            reference = block.get("reference_close")
            reference_source = "YAHOO.reference_close"
            if reference is None and session == POST_MARKET:
                reference = (yh.get(REGULAR) or {}).get("price")
                reference_source = "YAHOO.regular.price"
        elif provider == SA:
            reference = sa_extended.get("previous_close") or sa.get("price")
            reference_source = "SA.extended_hours.previous_close"
        elif provider == FINVIZ:
            reference = (fv_quote.get("snapshot_numeric") or {}).get("Prev Close")
            reference_source = "FINVIZ.snapshot_numeric.Prev Close"
            if reference is None:
                reported = fv_after.get("change_percent")
                if isinstance(reported, (int, float)) and math.isfinite(reported):
                    denominator = 1 + reported / 100
                    if denominator > 0:
                        reference = reading["price"] / denominator
                        reference_source = "FINVIZ.after_hours.change_percent"
        elif provider == TRADINGVIEW:
            reported = tv.get(
                "premarket_change"
                if session == PRE_MARKET
                else "postmarket_change"
            )
            if isinstance(reported, (int, float)) and math.isfinite(reported):
                denominator = 1 + reported / 100
                if denominator > 0:
                    reference = reading["price"] / denominator
                    reference_source = (
                        f"TRADINGVIEW.{session.replace('_market', 'market')}_change"
                    )
        if (
            isinstance(reading["price"], (int, float))
            and not isinstance(reading["price"], bool)
            and math.isfinite(reading["price"])
            and isinstance(reference, (int, float))
            and not isinstance(reference, bool)
            and math.isfinite(reference)
            and reference > 0
        ):
            reading["reference_close"] = reference
            reading["change"] = reading["price"] - reference
            reading["change_percent"] = reading["change"] / reference * 100
            reading["change_reference"] = reference_source

    comparison = compare_values(
        {provider: reading["price"] for provider, reading in readings.items()},
        tolerance_pct=0.5,
        # Feed the normalized reading field: raw Yahoo candle clocks and
        # StockAnalysis epoch milliseconds become one parseable UTC form.
        times={provider: reading["as_of_utc"] for provider, reading in readings.items()},
        sessions={provider: reading["session"] for provider, reading in readings.items()},
        max_skew_seconds=SKEW_LIMIT_SECONDS,
        session_boundary=True,
        require_all_times=True,
    )

    data = {
        "symbol": ticker,
        # The session the instrument is in right now, and which of the blocks
        # below is the live one. A caller asking "pre or post" should not have
        # to infer it from which block happens to be populated.
        "session": (
            OVERNIGHT if current_overnight else _session_now(tv, yh, _utc_now())
        ),
        "pre_market": yh.get("pre_market")
        or (
            {
                "price": tv.get("premarket_close"),
                "change_pct": tv.get("premarket_change"),
                "volume": tv.get("premarket_volume"),
            }
            if tv.get("premarket_close") is not None
            else None
        ),
        "regular": yh.get("regular") or {"price": tv.get("regular_close")},
        "post_market": yh.get("post_market")
        or (
            {
                "price": tv.get("postmarket_close"),
                "change_pct": tv.get("postmarket_change"),
                "volume": tv.get("postmarket_volume"),
            }
            if tv.get("postmarket_close") is not None
            else None
        ),
        "finviz_after_hours": fv_after,
        "finviz_last_close": (fv_quote.get("last_close") or {}).get("price"),
        "tradingview_premarket_close": tv.get("premarket_close"),
        "tradingview_premarket_volume": tv.get("premarket_volume"),
        "tradingview_postmarket_close": tv.get("postmarket_close"),
        "tradingview_postmarket_volume": tv.get("postmarket_volume"),
        "stockanalysis_extended_hours": sa_extended,
        "stockanalysis_regular_close": sa.get("price"),
        # The primary block is the newest BOATS print. Each provider's own
        # observation is retained; both read the same venue rather than acting
        # as independent market venues.
        "overnight": overnight_readings.get(overnight_source),
        "overnight_source": overnight_source,
        "overnight_readings": overnight_readings,
        "overnight_comparison": overnight_comparison,
        "overnight_errors": overnight_errors,
        "overnight_is_current": bool(current_overnight),
        "after_hours_readings": readings,
        "after_hours_comparison": comparison,
        "resolutions": resolved["resolutions"],
    }
    sources = {
        TRADINGVIEW: "scanner.tradingview.com pre/post-market fields",
        FINVIZ: f"https://finviz.com/stock?t={resolved['FINVIZ'].symbol or ticker}",
        YAHOO: "Yahoo 1-minute extended-hours candles",
        SA: f"https://stockanalysis.com/api/quotes/s/{resolved['SA'].symbol}"
        if resolved["SA"].found
        else "not carried by StockAnalysis",
    }
    if TRADINGVIEW in overnight_readings:
        sources[TRADINGVIEW] += "; data.tradingview.com quote websocket, BOATS"
    if YAHOO in overnight_readings:
        sources[YAHOO] += "; /v7/finance/quote overnightPrice=true (Blue Ocean ATS)"
    return finalize(
        pair,
        specs=(),
        sources=sources,
        extra={"extended_hours": data},
        additional_errors=overnight_errors,
        data=data,
        comparisons=[
            {"field": "after_hours_price", **comparison},
            {"field": "overnight_price", **overnight_comparison},
        ],
        fields={
            "overnight.price": field_source(
                overnight_source,
                compared_providers(overnight_comparison),
                overnight_comparison["match"],
                supplied=overnight_readings,
            )
        } if overnight_source else {},
        health_warn=MONITOR.warnings_for(providers_in(pair) or ALL_PROVIDERS),
        degraded=any(
            issue["provider"] in providers_in(pair) for issue in MONITOR.issues()
        ),
    )


# ── Technical analysis ───────────────────────────────────────────────────────


async def technical_analysis(
    symbol: str,
    exchange: str = "NASDAQ",
    timeframe: str = "1D",
) -> dict[str, Any]:
    """Multi-indicator technical analysis, price cross-checked across providers.

    TradingView computes the full indicator stack (RSI, MACD, EMAs, Bollinger,
    ATR, ADX, structure, trade setup). Finviz's snapshot and Yahoo's chart API
    independently provide price, RSI(14), ATR(14) and volume, which are compared
    here, so the numbers the analysis is built on are corroborated rather than
    taken on trust. The TradingView leg uses its resolved symbol and venue,
    never a bare ticker redirected by the caller's default exchange.

    Args:
        symbol: Ticker.
        exchange: TradingView exchange prefix (``NASDAQ``, ``NYSE``, ``BIST``, …).
        timeframe: ``5m``, ``15m``, ``1h``, ``4h``, ``1D``, ``1W``, ``1M``.

    Returns:
        Envelope whose ``data.analysis`` is the TradingView analysis and
        ``data.cross_check`` holds the per-provider comparison.
    """
    resolved = await _symbols_for(symbol)
    ticker = strip_exchange(symbol).upper()

    async def tv_call() -> dict[str, Any]:
        tv_res = resolved["TRADINGVIEW"]
        if not tv_res.found:
            raise NotApplicable(TRADINGVIEW, tv_res.note or "no TradingView symbol")
        # Use the identity resolution actually selected, not the caller's default
        # venue applied to the bare ticker.
        tv_symbol = tv_res.symbol
        resolved_exchange = tv_res.venue or (
            tv_symbol.split(":", 1)[0] if ":" in tv_symbol else exchange
        )
        return await tv_access.technical_analysis(
            tv_symbol, exchange=resolved_exchange, timeframe=timeframe
        )

    async def fv_call() -> dict[str, Any]:
        if not resolved["FINVIZ"].found:
            raise NotApplicable(FINVIZ, resolved["FINVIZ"].note or "Finviz has no page")
        # The quote page, not the snapshot endpoint: it carries the same 84-field
        # snapshot plus the print time this tool needs to prove the reading
        # describes the same observation as the others. Asking for the snapshot
        # alone meant every Finviz pair was undatable, so its price either got
        # compared across sessions or had to be dropped entirely.
        return await fv_access.quote(resolved["FINVIZ"].symbol)

    async def yh_call() -> dict[str, Any]:
        if not resolved["YAHOO"].found:
            raise NotApplicable(YAHOO, resolved["YAHOO"].note or "no Yahoo symbol")
        return await yh_access.quote(resolved["YAHOO"].symbol)

    pair = await ask(tv_call, fv_call, yh_call)

    analysis = pair.tv.payload or {}
    fv_quote = pair.fv.payload or {}
    fv_numeric = fv_quote.get("snapshot_numeric") or {}
    yh = pair.yh.payload or {}

    from .reconcile import compare_values

    tv_price = (analysis.get("price_data") or {}).get("current_price")
    tv_rsi = (analysis.get("rsi") or {}).get("value")
    tv_volume = (analysis.get("price_data") or {}).get("volume")

    # Every price and price-derived field here points at an instant, so the same
    # print-time guards ``stock_quote`` uses apply: two prints from different
    # sessions are two observations, not a disagreement. Finviz's quote page
    # carries a rendered print time ("Nov 11 - 5:09 AM ET"), so all three legs
    # can be dated and the comparison can be asserted rather than skipped.
    stamps = {
        TRADINGVIEW: (pair.tv.payload or {}).get("update_time"),
        FINVIZ: (fv_quote.get("last_close") or {}).get("date"),
        YAHOO: yh.get("market_time"),
    }

    cross_check = None
    if analysis and (fv_numeric or yh):
        cross_check = {
            "price": compare_values(
                {
                    TRADINGVIEW: tv_price,
                    FINVIZ: fv_numeric.get("Price"),
                    YAHOO: yh.get("price"),
                },
                tolerance_pct=0.5,
                times=stamps,
                max_skew_seconds=SKEW_LIMIT_SECONDS,
                session_boundary=True,
            ),
            # RSI and ATR are lookback statistics, not point-in-time prints, so a
            # print-time guard would be the wrong test: two feeds legitimately
            # compute them over slightly different bar counts. Their tolerance is
            # wide for that reason and no timestamp guard applies.
            "rsi_14": compare_values(
                {TRADINGVIEW: tv_rsi, FINVIZ: fv_numeric.get("RSI (14)")},
                tolerance_pct=12.0,
                absolute_floor=1.0,
            ),
            "atr_14": compare_values(
                {
                    TRADINGVIEW: (analysis.get("atr") or {}).get("value"),
                    FINVIZ: fv_numeric.get("ATR (14)"),
                },
                tolerance_pct=10.0,
                absolute_floor=0.1,
            ),
            # Finviz's snapshot ``Volume`` is not the session total the other
            # providers report: measured live, AAPL arrived as 97,520 against
            # 29,756,060 from TradingView and 29,726,781 from Yahoo. It counts
            # the current, partial session (the same number its quote page
            # carries next to a 5:09 AM print), while the consolidated feeds
            # report the last completed one. Comparing them was a guaranteed
            # 100 % "conflict" on every request, so this field is reported and
            # named as a different measurement rather than judged.
            "volume": compare_values(
                {
                    TRADINGVIEW: tv_volume,
                    FINVIZ: fv_numeric.get("Volume"),
                },
                tolerance_pct=2.0,
                not_comparable_reason=(
                    "Finviz's snapshot volume counts the current partial session "
                    "while the consolidated feeds report the last completed one, "
                    "so the two numbers answer different questions"
                ),
            ),
        }

    data = {
        "symbol": ticker,
        "exchange": exchange,
        "timeframe": timeframe,
        "analysis": analysis,
        "finviz_snapshot": fv_numeric,
        "yahoo_quote": {
            "price": yh.get("price"),
            "change_pct": yh.get("change_pct"),
            "market_time": yh.get("market_time"),
        },
        "cross_check": cross_check,
        "resolutions": resolved["resolutions"],
    }
    return finalize(
        pair,
        specs=(),
        sources={
            TRADINGVIEW: "TradingView technical analysis engine",
            FINVIZ: f"https://finviz.com/stock?t={resolved['FINVIZ'].symbol or ticker}",
            YAHOO: f"https://query1.finance.yahoo.com/v8/finance/chart/{resolved['YAHOO'].symbol}",
        },
        extra={"technical_analysis": data},
        data=data,
        health_warn=MONITOR.warnings_for(providers_in(pair) or ALL_PROVIDERS),
        degraded=any(
            issue["provider"] in providers_in(pair) for issue in MONITOR.issues()
        ),
    )


# ── Registration ─────────────────────────────────────────────────────────────

_TOOLS = (
    (stock_quote, "Market data: quote, fundamentals, and a snapshot"),
    (stock_prices, "Market data: batch stock prices"),
    (stock_screener, "Market data: stock screener"),
    (market_indices, "Market data: major market indices"),
    (stock_news, "Market data: stock news"),
    (stock_options_chain, "Market data: options chain"),
    (stock_earnings, "Market data: earnings calendar and history"),
    (stock_extended_hours, "Market data: pre/post-market prices"),
    (technical_analysis, "Market data: technical analysis"),
)


def register(mcp) -> int:
    """Register the multi-source market tools."""
    for fn, title in _TOOLS:
        mcp.add_tool(fn, name=fn.__name__, title=title, description=fn.__doc__)
    return len(_TOOLS)
