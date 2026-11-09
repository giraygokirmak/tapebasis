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
import os
from datetime import datetime, timezone
from typing import Any

from . import bb_access, fv_access, sa_access, tv_access, yh_access
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
    DataProvider,
    NoDataError,
    NotApplicable,
    ProviderError,
    envelope,
    provider_from_answered,
)
from .reconcile import (
    BLOOMBERG,
    FINVIZ,
    SA,
    TRADINGVIEW,
    YAHOO,
    FieldSpec,
    Pair,
    ask,
    finalize,
    providers_in,
)
from .symbols import Resolution, resolve, resolve_sa, strip_exchange, to_finviz

#: Every provider the market tools ask. They are peers, not fallbacks: a tool
#: either asks all of them or records ``NOT_ATTEMPTED`` for the ones that have
#: no endpoint. Bloomberg and StockAnalysis are the other two legs: they are
#: asked in parallel like the rest, and the known delay of the former and the
#: US-only coverage of the latter are handled by the print-time guards and the
#: resolution notes rather than by keeping them out of the comparison.
ALL_PROVIDERS = (TRADINGVIEW, FINVIZ, YAHOO, SA, BLOOMBERG)

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

    Bloomberg has no usable anonymous search endpoint and answers a bad id with
    a bot-wall 403 rather than a 404, so identity is a curated alias table plus
    a mechanical rule (:func:`tapebasis.bb_access.to_bloomberg`). That is a
    resolution, just not a searched one, and the ``method`` says so.
    """
    try:
        bloomberg_id = bb_access.to_bloomberg(symbol)
    except Exception as exc:  # noqa: BLE001 - a bad symbol is not a failure here
        return Resolution(
            query=symbol,
            provider=BLOOMBERG,
            symbol=None,
            method="none",
            note=getattr(exc, "message", None) or str(exc),
        )
    return Resolution(
        query=symbol,
        provider=BLOOMBERG,
        symbol=bloomberg_id,
        venue=bloomberg_id.rpartition(":")[2],
        method="mechanical",
        confidence=0.8,
    )



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


def _quote_specs(*, day_change_comparable: bool = True) -> tuple[FieldSpec, ...]:
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

    ``day_change_comparable=False`` marks the day change as structurally not
    comparable instead of comparing readings that share no baseline. Every
    reading is still reported.
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
            not_comparable_reason=None if day_change_comparable else _FX_DAY_CHANGE_REASON,
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
    compared because spot FX has no single official previous close.

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
        records how each provider's ticker was derived.
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
        try:
            return await tv_access.quote(tv_res.symbol)
        except NoDataError as exc:
            raise NotApplicable(TRADINGVIEW, exc.message) from exc

    async def fv_call() -> dict[str, Any]:
        if not fv_res.found:
            raise NotApplicable(FINVIZ, fv_res.note or f"Finviz does not carry {symbol}")
        try:
            return await fv_access.quote(fv_res.symbol)
        except NoDataError as exc:
            raise NotApplicable(FINVIZ, exc.message) from exc

    async def yh_call() -> dict[str, Any]:
        if not yh_res.found:
            # "Yahoo has no ticker for this" is not an outage. Saying so keeps
            # ``errors`` for real failures, an agent reading the envelope must
            # be able to tell "provider is down" from "provider never had it".
            raise NotApplicable(YAHOO, yh_res.note or f"Yahoo Finance does not carry {symbol}")
        try:
            return await yh_access.quote(yh_res.symbol)
        except NoDataError as exc:
            raise NotApplicable(YAHOO, exc.message) from exc

    async def sa_call() -> dict[str, Any]:
        if not sa_res.found:
            raise NotApplicable(
                SA, sa_res.note or f"StockAnalysis does not carry {symbol}"
            )
        try:
            return await sa_access.quote(sa_res.symbol)
        except NoDataError as exc:
            raise NotApplicable(SA, exc.message) from exc

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
        except NoDataError as exc:
            raise NotApplicable(BLOOMBERG, exc.message) from exc
        return data

    # The last two legs are named rather than positional: both are optional in
    # ``ask`` and swapping them would mislabel every reading in the response.
    pair = await ask(
        tv_call, fv_call, yh_call, bb_fn=bb_call, sa_fn=sa_call
    )

    def tv_norm(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "price": payload.get("close"),
            "change_percent": payload.get("change"),
            "previous_close": payload.get("prev_close_price"),
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
        return {
            "price": payload.get("price"),
            "change_percent": payload.get("change_pct"),
            "previous_close": payload.get("previous_close"),
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
            "price_timestamp": payload.get("market_time"),
            "company": payload.get("company"),
        }

    def sa_norm(payload: dict[str, Any]) -> dict[str, Any]:
        # StockAnalysis's quote endpoint publishes price, the day session, the
        # 52-week range and volume. It has no fundamentals on this route, so
        # ``pe_ratio``/``beta``/``eps`` are not invented here; they live on its
        # stock page, which ``stock_quote`` does not fetch.
        return {
            "price": payload.get("price"),
            "change_percent": payload.get("change_percent"),
            "previous_close": payload.get("previous_close"),
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
            # it can be ordered against the other providers' print times.
            "price_timestamp": payload.get("price_timestamp"),
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

    return finalize(
        pair,
        # FX has no shared previous close, so its day change is reported from
        # every provider but never compared. Everything else is compared.
        specs=_quote_specs(
            day_change_comparable=not _is_fx(tv_res, fv_res, yh_res, sa_res, bb_res)
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
        extra={"symbol": ticker, "resolutions": resolved["resolutions"]},
        **_health({"providers": providers_in(pair) or ALL_PROVIDERS}),
    )



# ── Bulk prices ──────────────────────────────────────────────────────────────


async def stock_prices(tickers: str) -> dict[str, Any]:
    """Prices for several instruments at once, from every provider that carries them.

    Each ticker is resolved per provider and looked up natively: TradingView's
    scanner, Finviz's screener, Yahoo's chart API, StockAnalysis's quote API,
    Bloomberg's quote page. The per-row ``data_provider`` says whether that
    particular ticker was answered by several providers, by one, or by none;
    ``agrees`` says whether the readings matched. Bloomberg is asked about at
    most ``TAPEBASIS_BLOOMBERG_BATCH_MAX`` tickers per call (default 4) because
    its page path is paced at 10 s per request; the rest are reported as skipped
    in ``warnings`` rather than silently missing.

    Args:
        tickers: Comma-separated symbols, e.g. ``"AAPL,MSFT,XAUUSD"``.

    Returns:
        Envelope whose ``data`` is a list of rows, each with ``symbol``,
        ``price``, ``change_percent`` and its own ``data_provider``. On an FX
        symbol the day change is reported but not compared, because spot FX has
        no single official previous close.
    """
    requested = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not requested:
        return envelope(
            [],
            provider=DataProvider.NONE,
            warnings=["No tickers supplied."],
            extra={"symbols": []},
        )

    resolved = {symbol: await _symbols_for(symbol) for symbol in requested}

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
        rows: dict[str, dict[str, Any]] = {}
        misses: dict[str, str] = {}
        for symbol, entry in resolved.items():
            if not entry["YAHOO"].found:
                misses[symbol] = entry["YAHOO"].note or "no Yahoo ticker"
                continue
            try:
                rows[symbol] = await yh_access.quote(entry["YAHOO"].symbol)
            except NoDataError as exc:
                misses[symbol] = exc.message
            except Exception as exc:  # noqa: BLE001 - a single miss must not sink the batch
                misses[symbol] = f"{type(exc).__name__}: {exc}"
        if not rows:
            detail = "; ".join(f"{s}: {m}" for s, m in misses.items())
            raise NotApplicable(YAHOO, f"no Yahoo data ({detail})")
        return {"rows": rows, "misses": misses}

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
        if not sa_slugs:
            raise NotApplicable(
                SA, "StockAnalysis carries none of these instruments"
            )
        rows: dict[str, dict[str, Any]] = {}
        misses: dict[str, str] = {}
        for symbol in sa_slugs:
            try:
                rows[symbol] = await sa_access.quote(
                    resolved[symbol]["SA"].symbol
                )
            except NoDataError as exc:
                misses[symbol] = exc.message
            except Exception as exc:  # noqa: BLE001 - one miss must not sink the batch
                misses[symbol] = getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}"
        if not rows:
            detail = "; ".join(f"{s}: {m}" for s, m in misses.items())
            raise NotApplicable(SA, f"no StockAnalysis data ({detail})")
        return {"rows": rows, "misses": misses}

    async def bb_call() -> dict[str, Any]:
        if not bb_asked:
            raise NotApplicable(
                BLOOMBERG,
                "no Bloomberg id resolved"
                if not bb_symbols
                else f"Bloomberg is asked about at most {BLOOMBERG_BATCH_MAX} tickers per batch",
            )
        rows: dict[str, dict[str, Any]] = {}
        misses: dict[str, str] = {}
        for symbol in bb_asked:
            try:
                data, _source = await asyncio.wait_for(
                    bb_access.quote(symbol), timeout=BLOOMBERG_DEADLINE_SECONDS
                )
                rows[symbol] = data
            except asyncio.TimeoutError:
                misses[symbol] = f"no answer within {BLOOMBERG_DEADLINE_SECONDS:.0f}s"
            except NoDataError as exc:
                misses[symbol] = exc.message
            except Exception as exc:  # noqa: BLE001 - one miss must not sink the batch
                misses[symbol] = getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}"
        if not rows:
            detail = "; ".join(f"{s}: {m}" for s, m in misses.items())
            raise NotApplicable(BLOOMBERG, f"no Bloomberg data ({detail})")
        return {"rows": rows, "misses": misses}

    pair = await ask(
        tv_call, fv_call, yh_call, bb_fn=bb_call, sa_fn=sa_call
    )

    from .reconcile import DEFAULT_ORDER, _resolved_label, compare_values

    tv_rows = (pair.tv.payload or {}).get("rows") or {}
    fv_rows = (pair.fv.payload or {}).get("rows") or {}
    yh_rows = (pair.yh.payload or {}).get("rows") or {}
    sa_rows = (pair.sa.payload or {}).get("rows") or {}
    bb_rows = (pair.bb.payload or {}).get("rows") or {}

    out_rows: list[dict[str, Any]] = []
    for symbol in requested:
        entry = resolved[symbol]
        tv_row = tv_rows.get(strip_exchange(entry["TRADINGVIEW"].symbol or ""))
        fv_row = fv_rows.get(entry["FINVIZ"].symbol or "") or fv_rows.get(
            to_finviz(symbol)
        )
        yh_row = yh_rows.get(symbol)
        sa_row = sa_rows.get(symbol)
        sa_miss = ((pair.sa.payload or {}).get("misses") or {}).get(symbol)
        yh_miss = ((pair.yh.payload or {}).get("misses") or {}).get(symbol)
        bb_miss = ((pair.bb.payload or {}).get("misses") or {}).get(symbol)

        readings: dict[str, dict[str, Any]] = {}
        if tv_row:
            readings[TRADINGVIEW] = {
                "price": tv_row.get("close"),
                "change_percent": tv_row.get("change"),
                "volume": tv_row.get("volume"),
                "company": tv_row.get("description"),
                "price_timestamp": tv_row.get("update_time"),
            }
        if fv_row:
            readings[FINVIZ] = {
                "price": fv_row.get("price"),
                "change_percent": fv_row.get("change"),
                "previous_close": fv_row.get("prevClose"),
                "volume": fv_row.get("volume"),
                "company": fv_row.get("company"),
                "price_timestamp": fv_row.get("last_update") or fv_row.get("fetched_at"),
            }
        if yh_row:
            readings[YAHOO] = {
                "price": yh_row.get("price"),
                "change_percent": yh_row.get("change_pct"),
                "previous_close": yh_row.get("previous_close"),
                "company": yh_row.get("shortName"),
                "price_timestamp": yh_row.get("market_time"),
            }
        if sa_row:
            readings[SA] = {
                "price": sa_row.get("price"),
                "change_percent": sa_row.get("change_percent"),
                "previous_close": sa_row.get("previous_close"),
                "volume": sa_row.get("volume"),
                "price_timestamp": sa_row.get("price_timestamp"),
            }
        bb_row = bb_rows.get(symbol)
        if bb_row:
            week_52 = bb_row.get("week_52_range") or [None, None]
            readings[BLOOMBERG] = {
                "price": bb_row.get("price"),
                "change_percent": bb_row.get("change_percent"),
                "previous_close": bb_row.get("previous_close"),
                "week_52_low": week_52[0] if len(week_52) > 0 else None,
                "week_52_high": week_52[1] if len(week_52) > 1 else None,
                "company": bb_row.get("name"),
                # Derived from the intraday series by ``bb_access``, never the
                # ``lastUpdate`` sentinel, so it can be ordered against the
                # other providers' prints.
                "price_timestamp": bb_row.get("print_time"),
                "exchange_delay": bb_row.get("exchange_delay"),
            }

        if not readings:
            out_rows.append(
                {
                    "symbol": symbol,
                    "data_provider": DataProvider.NONE.value,
                    "verification": "UNAVAILABLE",
                    "resolutions": entry["resolutions"],
                    # Why each provider contributed nothing, so "NONE" is
                    # diagnosable rather than mysterious.
                    "misses": {
                        p: (entry[p].note or "no ticker") if not entry[p].found else None
                        for p in ALL_PROVIDERS
                    }
                    | ({YAHOO: yh_miss} if yh_miss else {})
                    | ({SA: sa_miss} if sa_miss else {})
                    | ({BLOOMBERG: bb_miss} if bb_miss else {}),
                }
            )
            continue

        stamps = {p: r.get("price_timestamp") for p, r in readings.items()}
        # Same guards as ``stock_quote``: a delayed print (Bloomberg is 15
        # minutes behind on equities) is a different observation, not a
        # disagreement, and a screener row with no print time cannot prove
        # otherwise.
        price_cmp = compare_values(
            {p: r.get("price") for p, r in readings.items()},
            tolerance_pct=0.5,
            times=stamps,
            max_skew_seconds=SKEW_LIMIT_SECONDS,
            session_boundary=True,
        )
        change_cmp = compare_values(
            {p: r.get("change_percent") for p, r in readings.items()},
            tolerance_pct=2.0,
            absolute_floor=0.05,
            times=stamps,
            max_skew_seconds=SKEW_LIMIT_SECONDS,
            session_boundary=True,
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
        agree = price_cmp["match"] is not False and change_cmp["match"] is not False

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
        row: dict[str, Any] = {
            "symbol": symbol,
            "price": source.get("price"),
            "change_percent": source.get("change_percent"),
            "previous_close": source.get("previous_close"),
            "volume": source.get("volume"),
            "company": next(
                (r.get("company") for r in readings.values() if r.get("company")), None
            ),
            "data_provider": (
                DataProvider.ALL.value
                if len(readings) >= 2
                else DataProvider(next(iter(readings))).value
            ),
            "verification": (
                "MULTI_SOURCE" if len(readings) >= 2 else "SINGLE_SOURCE"
            ),
            "agrees": agree,
            "price_source": winner,
            "freshness": freshness,
            "providers_answered": [
                p for p in ALL_PROVIDERS if p in readings
            ],
            "comparisons": {"price": price_cmp, "change_percent": change_cmp},
            "resolutions": entry["resolutions"],
        }
        if readings.get(BLOOMBERG, {}).get("exchange_delay"):
            # The delay is a property of the reading, so it travels with it
            # instead of only being visible in ``comparisons``.
            row["exchange_delay"] = readings[BLOOMBERG]["exchange_delay"]
        out_rows.append(row)

    answering_rows = [r for r in out_rows if r["data_provider"] != "NONE"]
    answered = {
        p for r in answering_rows for p in r.get("providers_answered", [])
    }
    overall = provider_from_answered(answered)

    skip_warnings: list[str] = []
    if bb_skipped:
        skip_warnings.append(
            "Bloomberg was not asked about "
            + ", ".join(bb_skipped)
            + f": its page path is paced at 10 s per request, so a batch asks it "
            f"about at most {BLOOMBERG_BATCH_MAX} tickers. Those rows are not "
            "counted as Bloomberg-answered."
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
        extra={"symbols": requested},
        warnings=skip_warnings,
        data=out_rows,
        provider=overall,
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
        ``finviz_match`` showing whether Finviz agreed.
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
        return {"rows": await fv_access.screener_rows(tickers)}

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

    Covers S&P 500, Dow, Nasdaq Composite, Russell 2000 and VIX. Every provider
    spells these differently (``SPX`` / ``SP:SPX`` / ``^GSPC``); they are mapped
    to one canonical name before comparison, and the level is compared across
    all providers that answered.

    Returns:
        Envelope whose ``data.indices`` is keyed by canonical index
        (``SPX``, ``DJI``, ``COMP``, ``RUT``, ``VIX``), each value carrying
        ``level``, ``change_percent``, its own ``data_provider`` and the raw
        readings from every provider that supplied it.
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

    from .reconcile import _resolved_label, compare_values

    indices: dict[str, Any] = {}
    for canonical in ("SPX", "DJI", "COMP", "RUT", "IWM", "VIX"):
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
        indices[canonical] = {
            "name": fv_row.get("name") or tv_row.get("name") or canonical,
            "level": present[winner],
            "level_source": winner,
            "freshness": freshness,
            "previous_close": fv_row.get("previous_close"),
            "change": fv_row.get("change"),
            "change_percent": next(
                (
                    row.get("change_percent")
                    for row in (tv_row, fv_row, yh_row)
                    if row.get("change_percent") is not None
                ),
                None,
            ),
            "data_provider": (
                DataProvider.ALL.value
                if len(present) >= 2
                else DataProvider(next(iter(present))).value
            ),
            "verification": (
                "MULTI_SOURCE" if len(present) >= 2 else "SINGLE_SOURCE"
            ),
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
    overall = provider_from_answered(answered)
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


async def stock_options_chain(symbol: str, expiry: str | None = None) -> dict[str, Any]:
    """Multi-source options chain for one expiry.

    Finviz and Yahoo both publish a chain; contracts are matched by strike and
    their volume/open-interest compared, so an agent can see whether the two
    chains agree on open positioning. TradingView has no chain, but its scanner
    independently quotes the underlying the contracts are priced against.

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

    overlap = None
    if (fv_calls or fv_puts) and (yh_calls or yh_puts):
        overlap = {
            "calls": option_overlap(yh_calls, fv_calls),
            "puts": option_overlap(yh_puts, fv_puts),
        }

    data = {
        "symbol": ticker,
        "expiry": (fv_norm or {}).get("expiry") or (yh_norm or {}).get("expiry"),
        "expiries": (fv_norm or {}).get("expiries") or (yh_norm or {}).get("expiries") or [],
        "underlying_price": (fv_norm or {}).get("underlying_price")
        or (yh_norm or {}).get("underlying_price")
        or tv_scanner.get("underlying_price"),
        "tradingview_underlying_price": tv_scanner.get("underlying_price"),
        "calls": fv_calls or yh_calls,
        "puts": fv_puts or yh_puts,
        "yahoo_calls": yh_calls,
        "yahoo_puts": yh_puts,
        "contract_count": (fv_norm or {}).get("contract_count")
        or (yh_norm or {}).get("contract_count"),
        "overlap": overlap,
        "resolutions": resolved["resolutions"],
    }
    return finalize(
        pair,
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
    next scheduled date on its own feed. The dates are compared and reported.

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
        "next_earnings_date": tv_next or yh_next or fv_data.get("earnings_date"),
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
    """Pre-/post-market price for a US stock, cross-checked across providers.

    Finviz exposes the after-hours print on the quote page; Yahoo derives
    pre/regular/post prices from its own 1-minute candles; TradingView's scanner
    carries its own pre/post prints; StockAnalysis returns an extended-hours
    block next to the regular quote. The after-hours price and change are
    compared, and every session block is returned.

    Args:
        symbol: Ticker.

    Returns:
        Envelope with ``data`` carrying ``pre_market``, ``regular``,
        ``post_market`` and the Finviz after-hours block.
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

    pair = await ask(tv_call, fv_call, yh_call, sa_fn=sa_call)

    tv = pair.tv.payload or {}
    fv_quote = pair.fv.payload or {}
    fv_after = fv_quote.get("after_hours") or {}
    yh = pair.yh.payload or {}
    sa = pair.sa.payload or {}
    sa_extended = sa.get("extended_hours") or {}

    from .reconcile import compare_values

    readings = {
        TRADINGVIEW: tv.get("postmarket_close") or tv.get("premarket_close"),
        FINVIZ: fv_after.get("price"),
        YAHOO: (yh.get("post_market") or {}).get("price")
        or (yh.get("pre_market") or {}).get("price"),
        # StockAnalysis's extended block names its own session; it is a print,
        # not a timeline, so it joins the same comparison.
        SA: sa_extended.get("price"),
    }
    comparison = compare_values(readings, tolerance_pct=0.5)

    data = {
        "symbol": ticker,
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
        "after_hours_readings": {p: v for p, v in readings.items() if v is not None},
        "after_hours_comparison": comparison,
        "resolutions": resolved["resolutions"],
    }
    return finalize(
        pair,
        specs=(),
        sources={
            TRADINGVIEW: "scanner.tradingview.com pre/post-market fields",
            FINVIZ: f"https://finviz.com/stock?t={resolved['FINVIZ'].symbol or ticker}",
            YAHOO: "Yahoo 1-minute extended-hours candles",
            SA: f"https://stockanalysis.com/api/quotes/s/{resolved['SA'].symbol}"
            if resolved["SA"].found
            else "not carried by StockAnalysis",
        },
        extra={"extended_hours": data},
        data=data,
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
    taken on trust.

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
        return await tv_access.technical_analysis(
            ticker, exchange=exchange, timeframe=timeframe
        )

    async def fv_call() -> dict[str, Any]:
        if not resolved["FINVIZ"].found:
            raise NotApplicable(FINVIZ, resolved["FINVIZ"].note or "Finviz has no page")
        return await fv_access.snapshot(resolved["FINVIZ"].symbol)

    async def yh_call() -> dict[str, Any]:
        if not resolved["YAHOO"].found:
            raise NotApplicable(YAHOO, resolved["YAHOO"].note or "no Yahoo symbol")
        return await yh_access.quote(resolved["YAHOO"].symbol)

    pair = await ask(tv_call, fv_call, yh_call)

    analysis = pair.tv.payload or {}
    fv_snapshot = pair.fv.payload or {}
    fv_numeric = fv_snapshot.get("numeric") or {}
    yh = pair.yh.payload or {}

    from .reconcile import compare_values

    tv_price = (analysis.get("price_data") or {}).get("current_price")
    tv_rsi = (analysis.get("rsi") or {}).get("value")

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
            ),
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
            "volume": compare_values(
                {
                    TRADINGVIEW: (analysis.get("price_data") or {}).get("volume"),
                    FINVIZ: fv_numeric.get("Volume"),
                },
                tolerance_pct=2.0,
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
