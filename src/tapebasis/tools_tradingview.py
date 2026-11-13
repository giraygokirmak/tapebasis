"""TradingView-native tools, served, and explicitly labelled single-source.

These capabilities exist only on the TradingView side of this stack: crypto
screening, futures, EGX coverage, strategy backtests, news sentiment and the
global FX/crypto snapshot. Finviz and Yahoo have no equivalent dataset, so the
reconciler's ``single()`` helper marks them ``NOT_ATTEMPTED`` and the envelope
reads ``TRADINGVIEW`` with a notice that the data is not cross-verified.

Two exceptions genuinely combine providers:

* ``market_snapshot`` asks TradingView's scanner and Yahoo's chart API
  independently, so the broad FX/crypto/index/ETF read is multi-source.
* ``combined_analysis`` adds Finviz and Yahoo price confirmation to the
  TradingView technical read.
"""
from __future__ import annotations

from typing import Any

from . import blocking_pool, fv_access, sentiment, tv_access, yh_access
from .health import FINVIZ, MONITOR, TRADINGVIEW, YAHOO
from .providers_state import (
    DataProvider,
    NotApplicable,
    ProviderError,
    envelope,
    error_code,
    provider_from_answered,
)
from .reconcile import ask, field_source, finalize, providers_in, single
from .providers.tradingview.core.services import (
    bitcoin_market_service,
    futures_service,
    marketaux_service,
    multi_agent_service,
    scanner_service,
    screener_service,
)
from .symbols import resolve_tradingview, strip_exchange, to_finviz

#: Blocking provider work goes to its own bounded pool, not the loop's default
#: executor, so a slow screener or backtest cannot starve a fast path that needs
#: a thread (see :mod:`tapebasis.blocking_pool`).
_OFFLOAD = blocking_pool.run


async def _run(fn, /, *args, **kwargs):
    """Run a blocking provider function in a worker thread (keeps the loop free)."""
    return await _OFFLOAD(fn, *args, **kwargs)


async def _yahoo_resolution(symbol: str):
    """Resolve a user symbol to Yahoo's spelling, for tools that need its feed."""
    from .symbols import resolve

    return await resolve(symbol, YAHOO)


def _single_response(
    data: Any,
    *,
    source: str,
    warnings: list[str] | None = None,
    extra: dict[str, Any] | None = None,
    provider: str = TRADINGVIEW,
) -> dict[str, Any]:
    """Wrap a single-provider payload in the standard envelope.

    Every top-level key of ``data`` is labelled with a field descriptor whose
    ``source`` is the provider, so the response states per item where each
    value came from rather than relying on the response-level label alone.
    """
    MONITOR.ensure_started()
    pair = single(provider, data)
    fields = None
    if isinstance(data, dict):
        fields = {key: field_source(provider, [provider], None) for key in data}
    return finalize(
        pair,
        sources={provider: source},
        warnings=warnings or [],
        data=data,
        provider=DataProvider(provider),
        fields=fields,
        health_warn=MONITOR.warnings_for((provider,)),
        degraded=any(issue["provider"] == provider for issue in MONITOR.issues()),
        extra=extra,
    )


def _failed(exc: BaseException, **extra: Any) -> dict[str, Any]:
    if isinstance(exc, dict):
        message = str(exc.get("error") or exc)
        code = "PROVIDER_ERROR"
    else:
        message = getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}"
        code = error_code(exc)
    return envelope(
        None,
        provider=DataProvider.NONE,
        errors=[{"provider": TRADINGVIEW, "code": code, "message": message}],
        warnings=[f"TradingView could not serve this request: {message}"],
        extra=extra,
    )


async def _offload_result(fn, *args, source: str, **kwargs) -> dict[str, Any]:
    try:
        data = await _run(fn, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return _failed(exc)
    if isinstance(data, dict) and data.get("error"):
        return _failed(data)
    return _single_response(data, source=source)


# ── Sentiment (Marketaux when licensed, local otherwise) ─────────────────────


async def _sentiment_payload(ticker: str, *, limit: int = 20) -> dict[str, Any]:
    """Sentiment for one ticker, preferring Marketaux and never requiring a key.

    Order of preference:
      1. ``MARKETAUX_API_TOKEN`` set and usable -> Marketaux entity sentiment.
      2. Marketaux unconfigured, rejected, out of quota or down -> Finviz
         headlines scored locally by :mod:`tapebasis.sentiment`
         (deterministic, offline, free).
      3. Finviz also unusable -> a labelled empty payload, never a fake score.

    The caller cannot tell the difference from the shape alone; ``provider``
    and ``scoring`` inside the payload always name the backend that ran, and a
    licensed-vs-local switch is never silent.
    """
    licensed = await _run(marketaux_service.analyze_sentiment, ticker, limit=limit)
    if (
        isinstance(licensed, dict)
        and not licensed.get("error")
        and licensed.get("sentiment_score") is not None
    ):
        return licensed

    try:
        records = await fv_access.news(to_finviz(ticker), limit=limit, include_reactions=False)
    except Exception as exc:  # noqa: BLE001 - fall back to an explicit gap
        reason = getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}"
        upstream = (licensed or {}).get("error")
        return {
            "symbol": ticker.upper(),
            "sentiment_score": None,
            "sentiment_label": "Unavailable",
            "posts_analyzed": 0,
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "top_posts": [],
            "sources": [],
            "provider": "unavailable",
            "note": (
                "No sentiment could be computed. Marketaux: "
                f"{upstream or 'not configured'}; Finviz headlines: {reason}."
            ),
        }

    scored = sentiment.score_headlines(
        (records or {}).get("news") or [],
        symbol=ticker,
        source_label=f"Finviz headlines (local scoring): {records.get('source') or 'finviz.com'}",
        limit=limit,
    )
    scored["as_of"] = (records or {}).get("as_of")
    # Preserve why the licensed path was skipped, without turning it into an
    # error: falling back is normal when no token is configured.
    upstream_note = (licensed or {}).get("error")
    if upstream_note:
        scored["licensed_path_unavailable"] = upstream_note
    return scored


# ── Crypto ───────────────────────────────────────────────────────────────────


async def crypto_top_movers(
    movement: str = "gainers", exchange: str = "KUCOIN", timeframe: str = "15m", limit: int = 25
) -> dict[str, Any]:
    """Top crypto gainers or losers on an exchange (TradingView-only).

    Args:
        movement: ``gainers`` or ``losers``.
        exchange: TradingView venue (``KUCOIN``, ``BINANCE``, ``BYBIT``, …).
        timeframe: ``5m``, ``15m``, ``1h``, ``4h``, ``1D``, ``1W``, ``1M``.
        limit: Rows to return.

    Returns:
        Envelope labelled ``TRADINGVIEW`` with the ranked rows.
    """
    direction = movement.lower().strip()
    fn = screener_service.fetch_trending_analysis
    return await _offload_result(
        fn,
        exchange.upper(),
        timeframe=timeframe,
        sort="desc" if direction == "gainers" else "asc",
        limit=limit,
        source="TradingView scanner (crypto)",
    )


async def crypto_bollinger_scan(
    exchange: str = "KUCOIN", timeframe: str = "4h", bbw_threshold: float = 0.04, limit: int = 50
) -> dict[str, Any]:
    """Bollinger-band squeeze candidates (TradingView-only).

    Args:
        exchange: TradingView venue.
        timeframe: TradingView interval.
        bbw_threshold: Maximum band-width to qualify as a squeeze.
        limit: Rows to return.

    Returns:
        Envelope labelled ``TRADINGVIEW``.
    """
    return await _offload_result(
        screener_service.fetch_bollinger_analysis,
        exchange.upper(),
        timeframe=timeframe,
        limit=limit,
        bbw_filter=bbw_threshold,
        source="TradingView scanner (Bollinger)",
    )


async def crypto_volume_breakout(
    exchange: str = "KUCOIN",
    timeframe: str = "15m",
    volume_multiplier: float = 2.0,
    price_change_min: float = 3.0,
    limit: int = 25,
) -> dict[str, Any]:
    """Volume + price breakout scanner (TradingView-only).

    Args:
        exchange: TradingView venue.
        timeframe: TradingView interval.
        volume_multiplier: Minimum relative volume.
        price_change_min: Minimum absolute % change.
        limit: Rows to return.

    Returns:
        Envelope labelled ``TRADINGVIEW``.
    """
    return await _offload_result(
        scanner_service.volume_breakout_scan,
        exchange.upper(),
        timeframe=timeframe,
        volume_multiplier=volume_multiplier,
        price_change_min=price_change_min,
        limit=limit,
        source="TradingView scanner (volume breakout)",
    )


async def crypto_multi_timeframe(
    symbol: str, exchange: str = "KUCOIN"
) -> dict[str, Any]:
    """Multi-timeframe technical read for a crypto symbol (TradingView-only).

    Args:
        symbol: Coin symbol (``BTC``, ``ETH``).
        exchange: TradingView venue.

    Returns:
        Envelope labelled ``TRADINGVIEW`` with per-timeframe analysis.
    """
    from .providers.tradingview.core.utils.validators import (
        normalize_tradingview_symbol,
    )

    venue = exchange.upper()
    full_symbol = normalize_tradingview_symbol(strip_exchange(symbol).upper(), venue)
    return await _offload_result(
        screener_service.run_multi_timeframe_analysis,
        full_symbol,
        venue,
        source="TradingView technical analysis (multi-timeframe)",
    )


async def crypto_multi_agent(symbol: str, exchange: str = "KUCOIN", timeframe: str = "15m") -> dict[str, Any]:
    """Multi-agent bull/bear debate over a crypto symbol (TradingView-only).

    Args:
        symbol: Coin symbol.
        exchange: TradingView venue.
        timeframe: TradingView interval.

    Returns:
        Envelope labelled ``TRADINGVIEW``.
    """
    from .providers.tradingview.core.utils.validators import (
        normalize_tradingview_symbol,
    )

    venue = exchange.upper()
    full_symbol = normalize_tradingview_symbol(strip_exchange(symbol).upper(), venue)
    return await _offload_result(
        multi_agent_service.run_multi_agent_analysis,
        full_symbol,
        venue,
        timeframe=timeframe,
        source="TradingView multi-agent analysis",
    )


# ── Futures ──────────────────────────────────────────────────────────────────


async def futures_market_overview(
    category: str = "all", exchanges: str = "us", limit: int = 30
) -> dict[str, Any]:
    """Futures contracts ranked by volume (TradingView-only).

    Args:
        category: ``all``, ``equity_index``, ``energy``, ``metals``,
            ``agriculture``, ``rates``, ``forex`` or ``crypto_futures``.
        exchanges: ``us`` or ``global``.
        limit: Rows to return.

    Returns:
        Envelope labelled ``TRADINGVIEW``.
    """
    return await _offload_result(
        futures_service.get_futures_overview,
        category=category,
        exchanges=exchanges,
        limit=limit,
        source="TradingView scanner (futures)",
    )


async def futures_top_movers(
    movement: str = "gainers", exchanges: str = "us", limit: int = 20
) -> dict[str, Any]:
    """Futures gainers/losers by percent change (TradingView-only).

    Args:
        movement: ``gainers`` or ``losers``.
        exchanges: ``us`` or ``global``.
        limit: Rows to return.

    Returns:
        Envelope labelled ``TRADINGVIEW``.
    """
    return await _offload_result(
        futures_service.get_futures_movers,
        direction=movement,
        exchanges=exchanges,
        limit=limit,
        source="TradingView scanner (futures movers)",
    )


async def futures_watchlist() -> dict[str, Any]:
    """Curated futures watchlist with levels (TradingView-only).

    Returns:
        Envelope labelled ``TRADINGVIEW``.
    """
    return await _offload_result(
        futures_service.get_futures_watchlist,
        source="TradingView scanner (futures watchlist)",
    )


# ── Backtests ────────────────────────────────────────────────────────────────


async def stock_backtest(
    symbol: str,
    strategy: str,
    period: str = "1y",
    initial_capital: float = 10000.0,
    interval: str = "1d",
    include_trade_log: bool = False,
    include_equity_curve: bool = False,
) -> dict[str, Any]:
    """Backtest a strategy on a symbol, using each provider's own history.

    The history is fetched from TradingView's chart feed and from Yahoo's chart
    API independently, and the strategy is run on each. The two results are
    compared metric by metric, if the OHLCV bars differ materially, the
    backtest is only as trustworthy as the feed it came from, and the response
    says which one produced the numbers shown.

    Args:
        symbol: Ticker or coin (any instrument either provider quotes).
        strategy: One of ``rsi``, ``bollinger``, ``macd``, ``ema_cross``,
            ``supertrend``, ``donchian``, ``rsi_pullback``, ``keltner_breakout``,
            ``triple_ema``.
        period: ``6mo``, ``1y``, ``2y``, ``5y``, …
        initial_capital: Starting cash.
        interval: ``1d`` or ``1h``.
        include_trade_log: Include the per-trade log.
        include_equity_curve: Include the equity curve.

    Returns:
        Envelope whose ``data_provider`` is ``ALL`` when both feeds answered,
        ``TRADINGVIEW``/``YAHOO`` when only one did (single-source), or ``NONE``.
        ``comparisons`` holds the metric-by-metric agreement.
    """
    from .providers.tradingview.core.services import backtest_service

    tv_res = await resolve_tradingview(symbol)
    yh_res = await _yahoo_resolution(symbol)
    ticker = strip_exchange(symbol).upper()

    def _run(candles: list[dict], source: str) -> dict[str, Any]:
        return backtest_service.run_backtest(
            ticker,
            strategy,
            period=period,
            initial_capital=initial_capital,
            interval=interval,
            include_trade_log=include_trade_log,
            include_equity_curve=include_equity_curve,
            candles=candles,
            data_source=source,
        )

    async def tv_call() -> dict[str, Any]:
        if not tv_res.found:
            raise NotApplicable(TRADINGVIEW, tv_res.note or f"no TradingView symbol for {symbol}")
        payload = await tv_access.history_candles(
            tv_res.symbol, period=period, interval=interval
        )
        result = await _OFFLOAD(_run, payload["candles"], "TradingView")
        if result.get("error"):
            raise ProviderError(TRADINGVIEW, str(result["error"]))
        return result

    async def yh_call() -> dict[str, Any]:
        if not yh_res.found:
            raise NotApplicable(YAHOO, yh_res.note or f"no Yahoo symbol for {symbol}")
        payload = await yh_access.history_candles(
            yh_res.symbol, period=period, interval=interval
        )
        result = await _OFFLOAD(_run, payload["candles"], "Yahoo Finance")
        if result.get("error"):
            raise ProviderError(YAHOO, str(result["error"]))
        return result

    pair = await ask(tv_call, None, yh_call)

    from .reconcile import compare_values

    specs = (
        ("total_return_pct", 1.0),
        ("win_rate_pct", 2.0),
        ("total_trades", 0.0),
        ("max_drawdown_pct", 2.0),
        ("sharpe_ratio", 5.0),
        ("buy_and_hold_return_pct", 1.0),
    )
    tv_data = pair.tv.payload or {}
    yh_data = pair.yh.payload or {}
    comparisons = []
    for field, tolerance in specs:
        row = compare_values(
            {TRADINGVIEW: tv_data.get(field), YAHOO: yh_data.get(field)},
            tolerance_pct=tolerance,
            absolute_floor=0.05,
        )
        row["field"] = field
        comparisons.append(row)

    answered = pair.answered
    chosen = answered[0] if answered else None
    data = tv_data or yh_data
    if data:
        data = dict(data)
        data["providers_answered"] = answered

    return finalize(
        pair,
        specs=(),
        sources={
            TRADINGVIEW: "TradingView chart websocket OHLCV",
            YAHOO: "query1.finance.yahoo.com/v8/finance/chart OHLCV",
        },
        extra={
            "backtest": data,
            "metric_comparison": comparisons,
            "chosen_backtest": chosen,
        },
        data=data,
        health_warn=MONITOR.warnings_for(providers_in(pair) or (TRADINGVIEW, YAHOO)),
        degraded=any(
            issue["provider"] in providers_in(pair) for issue in MONITOR.issues()
        ),
    )


async def stock_backtest_compare(
    symbol: str, period: str = "1y", initial_capital: float = 10000.0
) -> dict[str, Any]:
    """Compare every strategy under the returned ``execution_model`` timing.

    Args:
        symbol: Ticker.
        period: Lookback period.
        initial_capital: Starting cash.

    Returns:
        Envelope with the strategy leaderboard per provider and the winning
        strategy they agree on (or a stated disagreement).
    """
    from .providers.tradingview.core.services import backtest_service

    tv_res = await resolve_tradingview(symbol)
    yh_res = await _yahoo_resolution(symbol)
    ticker = strip_exchange(symbol).upper()

    async def tv_call() -> dict[str, Any]:
        if not tv_res.found:
            raise NotApplicable(TRADINGVIEW, tv_res.note or f"no TradingView symbol for {symbol}")
        payload = await tv_access.history_candles(tv_res.symbol, period=period)
        result = await _OFFLOAD(
            backtest_service.compare_strategies,
            ticker,
            period=period,
            initial_capital=initial_capital,
            candles=payload["candles"],
            data_source="TradingView",
        )
        if result.get("error"):
            raise ProviderError(TRADINGVIEW, str(result["error"]))
        return result

    async def yh_call() -> dict[str, Any]:
        if not yh_res.found:
            raise NotApplicable(YAHOO, yh_res.note or f"no Yahoo symbol for {symbol}")
        payload = await yh_access.history_candles(yh_res.symbol, period=period)
        result = await _OFFLOAD(
            backtest_service.compare_strategies,
            ticker,
            period=period,
            initial_capital=initial_capital,
            candles=payload["candles"],
            data_source="Yahoo Finance",
        )
        if result.get("error"):
            raise ProviderError(YAHOO, str(result["error"]))
        return result

    pair = await ask(tv_call, None, yh_call)
    tv_data = pair.tv.payload or {}
    yh_data = pair.yh.payload or {}
    data = tv_data or yh_data
    if data:
        data = dict(data)
        data["tradingview"] = tv_data
        data["yahoo"] = yh_data
        data["winner_comparison"] = {
            "tradingview": tv_data.get("winner"),
            "yahoo": yh_data.get("winner"),
            "agree": (
                None
                if not (tv_data.get("winner") and yh_data.get("winner"))
                else tv_data.get("winner") == yh_data.get("winner")
            ),
        }

    return finalize(
        pair,
        specs=(),
        sources={
            TRADINGVIEW: "TradingView chart websocket OHLCV",
            YAHOO: "query1.finance.yahoo.com/v8/finance/chart OHLCV",
        },
        extra={"backtest_compare": data},
        data=data,
        health_warn=MONITOR.warnings_for(providers_in(pair) or (TRADINGVIEW, YAHOO)),
        degraded=any(
            issue["provider"] in providers_in(pair) for issue in MONITOR.issues()
        ),
    )


# ── Market-wide ──────────────────────────────────────────────────────────────


async def market_snapshot() -> dict[str, Any]:
    """Global FX, crypto, index and ETF snapshot from two independent providers.

    TradingView's scanner and Yahoo's chart API are asked separately, so the
    groups that both carry (indices, major crypto, FX, ETFs) are genuinely
    cross-checked. Finviz has no equivalent breadth, so it is not asked.

    Returns:
        Envelope grouped by asset class, each group labelled with whether every
        asked provider answered it.
    """
    return await _snapshot_impl()


async def _snapshot_impl() -> dict[str, Any]:
    """Ask TradingView's scanner and Yahoo's chart API for the same broad groups."""
    from .reconcile import compare_values

    async def tv_call() -> dict[str, Any]:
        return await tv_access.market_snapshot()

    async def yh_call() -> dict[str, Any]:
        return {"groups": await yh_access.market_snapshot()}

    pair = await ask(tv_call, None, yh_call)
    tv_groups = (pair.tv.payload or {}).get("groups") or {}
    yh_groups = (pair.yh.payload or {}).get("groups") or {}

    groups: dict[str, Any] = {}
    agree_all = True
    compared_any = False
    for group in ("indices", "crypto", "fx", "etfs"):
        tv_rows = {str(r.get("symbol") or "").upper(): r for r in tv_groups.get(group) or []}
        yh_rows = {str(r.get("symbol") or "").upper(): r for r in yh_groups.get(group) or []}
        rows = []
        for symbol in sorted(set(tv_rows) | set(yh_rows)):
            tv_row = tv_rows.get(symbol)
            yh_row = yh_rows.get(symbol)
            cmp_row = compare_values(
                {
                    TRADINGVIEW: (tv_row or {}).get("price"),
                    YAHOO: (yh_row or {}).get("price"),
                },
                # VIX moves percent-level in seconds; the index-level 0.5 %
                # tolerance would report a fast market as a data conflict.
                tolerance_pct=3.0 if symbol == "^VIX" else 0.5,
            )
            if cmp_row["match"] is not None:
                compared_any = True
                if cmp_row["match"] is False:
                    agree_all = False
            row_answered = [
                p
                for p, row in ((TRADINGVIEW, tv_row), (YAHOO, yh_row))
                if row
            ]
            rows.append(
                {
                    "symbol": symbol,
                    "price": (tv_row or yh_row or {}).get("price"),
                    "change_pct": (tv_row or yh_row or {}).get("change_pct"),
                    # Row coverage from the providers that supplied this row, so
                    # a leg that answered for this symbol never has to be spelled
                    # out as a literal ALL: the label is derived, the same way the
                    # envelope derives its own.
                    "data_provider": provider_from_answered(row_answered).value,
                    "tradingview_price": (tv_row or {}).get("price"),
                    "yahoo_price": (yh_row or {}).get("price"),
                    "agree": cmp_row["match"],
                    "comparison": cmp_row,
                }
            )
        groups[group] = rows

    data = {"groups": groups, "all_groups_agree": agree_all if compared_any else None}
    return finalize(
        pair,
        specs=(),
        sources={
            TRADINGVIEW: "scanner.tradingview.com (global snapshot)",
            YAHOO: "query1.finance.yahoo.com/v8/finance/chart",
        },
        extra={"snapshot": data},
        data=data,
        health_warn=MONITOR.warnings_for(providers_in(pair) or (TRADINGVIEW, YAHOO)),
        degraded=any(
            issue["provider"] in providers_in(pair) for issue in MONITOR.issues()
        ),
    )


async def bitcoin_market_pulse() -> dict[str, Any]:
    """Bitcoin market health: trend, dominance proxies and volatility.

    Returns:
        Envelope labelled ``TRADINGVIEW``.
    """
    return await _offload_result(
        bitcoin_market_service.get_bitcoin_market_pulse,
        source="TradingView/Yahoo bitcoin pulse",
    )


async def market_sentiment(symbol: str, category: str = "all", limit: int = 20) -> dict[str, Any]:
    """News-based sentiment for a symbol, with no API key required.

    Prefers the licensed Marketaux entity sentiment when ``MARKETAUX_API_TOKEN``
    is set. Without a token it scores Finviz headlines locally (VADER with a
    financial lexicon), deterministic, offline and free. Either way the payload
    names the backend in ``provider``/``scoring`` and never fabricates a score
    when there is no material to score.

    Args:
        symbol: Ticker.
        category: News category (used by the Marketaux path only).
        limit: Headlines to analyse.

    Returns:
        Envelope labelled ``TRADINGVIEW`` whose ``data`` carries
        ``sentiment_score``, ``sentiment_label``, the bullish/bearish/neutral
        counts and the strongest headlines.
    """
    ticker = strip_exchange(symbol).upper()
    try:
        data = await _sentiment_payload(ticker, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return _failed(exc)
    if data.get("sentiment_score") is None:
        return _single_response(
            data,
            source="No sentiment backend available",
            warnings=[data.get("note", "Sentiment unavailable.")],
        )
    if data.get("provider") == "marketaux":
        return _single_response(
            data, source="Marketaux entity sentiment (via TradingView provider)"
        )
    # The numbers are Finviz headlines; only the scoring is ours. Labelling this
    # TRADINGVIEW would claim a provenance the data does not have.
    return _single_response(
        data,
        source="Finviz headlines scored locally (VADER)",
        provider=FINVIZ,
    )


async def egx_market_overview(timeframe: str = "1D", limit: int = 10) -> dict[str, Any]:
    """Egyptian Exchange overview (TradingView-only).

    Returns:
        Envelope labelled ``TRADINGVIEW``.
    """
    from .providers.tradingview.core.services.egx_service import get_egx_market_overview

    return await _offload_result(
        get_egx_market_overview,
        timeframe=timeframe,
        limit=limit,
        source="TradingView scanner (EGX)",
    )


# ── Dual/cross-checked composite ─────────────────────────────────────────────


async def combined_analysis(symbol: str, exchange: str = "NASDAQ", timeframe: str = "1D") -> dict[str, Any]:
    """Technical analysis, news and sentiment in one call, price cross-checked.

    Runs the TradingView technical read plus news sentiment, then asks Finviz and
    Yahoo independently for the latest price to confirm the value the analysis
    was built on. This composite can legitimately return ``ALL``: the price leg
    is multi-source, while the analysis and sentiment legs remain single-source
    and are labelled per field.

    Sentiment needs no API key: Marketaux is used when ``MARKETAUX_API_TOKEN`` is
    set, otherwise Finviz headlines are scored locally. The ``data.news`` leg
    stays Marketaux-only, so it is empty (and says why) without a token.

    Args:
        symbol: Ticker.
        exchange: TradingView exchange prefix.
        timeframe: TradingView interval.

    Returns:
        Envelope with ``data.analysis``, ``data.sentiment``, ``data.news`` and
        ``data.price_cross_check``.
    """
    ticker = strip_exchange(symbol).upper()
    yh_res = await _yahoo_resolution(symbol)

    async def tv_call() -> dict[str, Any]:
        analysis = await tv_access.technical_analysis(
            ticker, exchange=exchange, timeframe=timeframe
        )
        sentiment_data = await _sentiment_payload(ticker, limit=20)
        news = await _run(
            marketaux_service.fetch_news_summary, ticker, limit=10
        )
        return {"analysis": analysis, "sentiment": sentiment_data, "news": news}

    async def fv_call() -> dict[str, Any]:
        return await fv_access.snapshot(to_finviz(ticker))

    async def yh_call() -> dict[str, Any]:
        if not yh_res.found:
            raise NotApplicable(YAHOO, yh_res.note or f"no Yahoo symbol for {symbol}")
        return await yh_access.quote(yh_res.symbol)

    pair = await ask(tv_call, fv_call, yh_call)

    from .reconcile import compare_values

    tv_payload = pair.tv.payload or {}
    fv_payload = pair.fv.payload or {}
    yh_payload = pair.yh.payload or {}
    analysis = tv_payload.get("analysis") or {}
    tv_price = (analysis.get("price_data") or {}).get("current_price")
    fv_price = (fv_payload.get("numeric") or {}).get("Price")
    yh_price = yh_payload.get("price")

    sentiment_data = tv_payload.get("sentiment") or {}
    sentiment_source = (
        "Marketaux entity sentiment (via TradingView provider)"
        if sentiment_data.get("provider") == "marketaux"
        else "Finviz headlines scored locally (VADER)"
    )
    data = {
        "symbol": ticker,
        "analysis": analysis,
        "sentiment": tv_payload.get("sentiment"),
        "news": tv_payload.get("news"),
        "price_cross_check": compare_values(
            {TRADINGVIEW: tv_price, FINVIZ: fv_price, YAHOO: yh_price},
            tolerance_pct=0.5,
        ),
    }
    return finalize(
        pair,
        sources={
            TRADINGVIEW: "TradingView technical analysis",
            FINVIZ: f"https://finviz.com/stock?t={to_finviz(ticker)}",
            YAHOO: f"https://query1.finance.yahoo.com/v8/finance/chart/{yh_res.symbol}",
        },
        extra={"sentiment_source": sentiment_source},
        data=data,
        health_warn=MONITOR.warnings_for(providers_in(pair) or (TRADINGVIEW, FINVIZ)),
        degraded=any(
            issue["provider"] in providers_in(pair) for issue in MONITOR.issues()
        ),
    )


_TOOLS = (
    (crypto_top_movers, "TradingView-only: crypto gainers/losers"),
    (crypto_bollinger_scan, "TradingView-only: Bollinger squeeze scan"),
    (crypto_volume_breakout, "TradingView-only: volume breakout scan"),
    (crypto_multi_timeframe, "TradingView-only: multi-timeframe crypto analysis"),
    (crypto_multi_agent, "TradingView-only: multi-agent debate"),
    (futures_market_overview, "TradingView-only: futures overview"),
    (futures_top_movers, "TradingView-only: futures movers"),
    (futures_watchlist, "TradingView-only: futures watchlist"),
    (stock_backtest, "TradingView-only: strategy backtest"),
    (stock_backtest_compare, "TradingView-only: strategy comparison"),
    (market_snapshot, "TradingView-only: global market snapshot"),
    (bitcoin_market_pulse, "TradingView-only: bitcoin pulse"),
    (market_sentiment, "TradingView-only: news sentiment"),
    (egx_market_overview, "TradingView-only: EGX overview"),
    (combined_analysis, "Cross-checked: TA + sentiment + price"),
)


def register(mcp) -> int:
    for fn, title in _TOOLS:
        mcp.add_tool(fn, name=fn.__name__, title=title, description=fn.__doc__)
    return len(_TOOLS)
