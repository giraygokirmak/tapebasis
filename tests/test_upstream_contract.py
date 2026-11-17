"""Regression tests for upstream-contract bugs found by live probing.

Every test here corresponds to a failure that the hermetic suite did not catch
because the fakes were shaped like the *expected* response rather than the real
one. Each one costs a user a wrong answer when it regresses:

* the scanner silently dropping tickers from a mixed batch,
* symbol resolution inventing a ticker that returns HTTP 404,
* Finviz being credited with an index it has no page for,
* a blocking scraper being awaited (and swallowed),
* a missing access-layer wrapper hiding a whole provider,
* two providers' rows never joining because they rank different universes,
* a session-boundary difference being reported as a data conflict.
"""
from __future__ import annotations

import pytest

from tapebasis.providers.tradingview import native
from tapebasis.symbols import (
    resolve_finviz,
    resolve_yahoo,
)


# ── scanner market partitioning ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mixed_batch_is_partitioned_by_market(monkeypatch):
    """``/america/scan`` drops non-US tickers; the batch must not lose them.

    Verified live: one POST to ``/america/scan`` containing ``NASDAQ:AAPL`` and
    ``OANDA:XAUUSD`` returns only the Apple row. Before partitioning, that
    silently turned a real TradingView gold quote into "no data".
    """
    calls: list[tuple[str, tuple[str, ...]]] = []

    async def fake_scan_market(market, tickers, columns, paced):
        calls.append((market, tuple(tickers)))
        # Emulate the real endpoint: /america only knows US venues.
        if market == "america":
            return [
                {"ticker": t, "close": 1.0}
                for t in tickers
                if t.split(":", 1)[0] in {"NASDAQ", "NYSE", "AMEX"}
            ]
        return [{"ticker": t, "close": 1.0} for t in tickers]

    monkeypatch.setattr(native, "_scan_market", fake_scan_market)
    native.limiter("TRADINGVIEW").cache_clear()

    rows = await native.scan(["NASDAQ:AAPL", "OANDA:XAUUSD", "BITSTAMP:BTCUSD"])
    tickers = {row["ticker"] for row in rows}
    assert tickers == {"NASDAQ:AAPL", "OANDA:XAUUSD", "BITSTAMP:BTCUSD"}
    # One request per market, not one request total.
    assert {market for market, _ in calls} == {"america", "global"}


@pytest.mark.asyncio
async def test_single_market_batch_makes_one_request(monkeypatch):
    calls: list[str] = []

    async def fake_scan_market(market, tickers, columns, paced):
        calls.append(market)
        return [{"ticker": t, "close": 1.0} for t in tickers]

    monkeypatch.setattr(native, "_scan_market", fake_scan_market)
    native.limiter("TRADINGVIEW").cache_clear()

    await native.scan(["NASDAQ:AAPL", "NYSE:IBM"])
    assert calls == ["america"]


# ── symbol resolution must not fabricate tickers ────────────────────────────


@pytest.mark.asyncio
async def test_yahoo_does_not_invent_a_spot_gold_pair():
    """``XAUUSD=X`` returns HTTP 404 on Yahoo; it must never be produced."""
    resolution = await resolve_yahoo("XAUUSD")
    assert resolution.symbol is None
    assert "no spot gold" in resolution.note
    # The note must not present futures as an equivalent quote.
    assert "different instrument" in resolution.note


@pytest.mark.asyncio
async def test_yahoo_metals_resolve_to_nothing_rather_than_a_dead_ticker():
    for symbol in ("XAGUSD", "XPTUSD", "XPDUSD"):
        assert (await resolve_yahoo(symbol)).symbol is None


@pytest.mark.asyncio
async def test_yahoo_fx_suffix_needs_real_currency_codes():
    """A six-letter equity ticker must not be rewritten into a fake FX pair."""
    assert (await resolve_yahoo("EURUSD")).symbol == "EURUSD=X"
    assert (await resolve_yahoo("USDJPY")).symbol == "USDJPY=X"
    # GOOGLX is six letters but not a pair of currencies; it must not be
    # rewritten into a ticker that cannot exist.
    assert (await resolve_yahoo("GOOGLX")).symbol != "GOOGLX=X"


@pytest.mark.asyncio
async def test_yahoo_crypto_uses_a_dash():
    assert (await resolve_yahoo("BTCUSD")).symbol == "BTC-USD"
    assert (await resolve_yahoo("ETHUSD")).symbol == "ETH-USD"


@pytest.mark.asyncio
async def test_yahoo_index_aliases_still_work():
    assert (await resolve_yahoo("SPX")).symbol == "^GSPC"
    assert (await resolve_yahoo("COMP")).symbol == "^IXIC"


def test_finviz_never_claims_an_index():
    """Finviz 404s ``/stock?t=SPX`` and ``COMP`` is Compass Inc, not the index."""
    for symbol in ("SPX", "DJI", "COMP", "RUT", "VIX", "^GSPC"):
        assert resolve_finviz(symbol).symbol is None
    # A real equity is still resolved.
    assert resolve_finviz("AAPL").symbol == "AAPL"


@pytest.mark.asyncio
async def test_tradingview_resolution_verifies_against_the_scanner(monkeypatch):
    """Search offers ``OANDA:BTCUSD``; the scanner quotes ``BITSTAMP:BTCUSD``.

    Resolution that trusts search hands the quote path a ticker that cannot be
    quoted, so a real instrument is reported as unavailable.
    """
    from tapebasis import symbols

    async def fake_search(query):
        return [
            symbols.Candidate(symbol="BTCUSD", venue="OANDA", asset_class="spot"),
            symbols.Candidate(symbol="BTCUSD", venue="BITSTAMP", asset_class="spot"),
        ]

    async def fake_quotes(tickers):
        return {"BITSTAMP:BTCUSD"}  # the only venue that actually has a row

    monkeypatch.setattr(symbols, "_tradingview_search", fake_search)
    monkeypatch.setattr(symbols, "_tradingview_quotes", fake_quotes)

    resolution = await symbols.resolve_tradingview("BTCUSD")
    assert resolution.symbol == "BITSTAMP:BTCUSD"


@pytest.mark.asyncio
async def test_tradingview_resolution_refuses_a_ticker_the_scanner_lacks(monkeypatch):
    from tapebasis import symbols

    async def fake_search(query):
        return [symbols.Candidate(symbol="BTCUSD", venue="OANDA", asset_class="spot")]

    async def fake_quotes(tickers):
        return set()

    monkeypatch.setattr(symbols, "_tradingview_search", fake_search)
    monkeypatch.setattr(symbols, "_tradingview_quotes", fake_quotes)

    resolution = await symbols.resolve_tradingview("BTCUSD")
    assert resolution.symbol is None
    assert "scanner quotes none" in resolution.note


# ── access-layer completeness ──────────────────────────────────────────────


def test_tv_access_exposes_market_snapshot():
    """The composite called ``tv_access.market_snapshot``, which did not exist.

    The resulting ``AttributeError`` was swallowed by the reconciler, so the
    snapshot reported Yahoo-only coverage with TradingView silently missing.
    """
    from tapebasis import tv_access

    assert hasattr(tv_access, "market_snapshot")


def test_blocking_scraper_is_not_awaited():
    """``screen_stocks`` is synchronous; awaiting it yields a TypeError."""
    import inspect

    from tapebasis.providers.tradingview.core.services import stock_screener_service

    assert not inspect.iscoroutinefunction(stock_screener_service.screen_stocks)


# ── comparison semantics ───────────────────────────────────────────────────


def test_session_relative_field_is_not_a_conflict_across_sessions():
    """A day change from yesterday's close vs today's is a freshness gap."""
    from tapebasis.reconcile import FINVIZ, TRADINGVIEW, compare_values

    row = compare_values(
        {TRADINGVIEW: -1.9, FINVIZ: 0.27},
        tolerance_pct=2.0,
        times={
            TRADINGVIEW: "2026-11-04T00:59:53+00:00",
            FINVIZ: "2026-11-04T10:28:00+00:00",
        },
        max_skew_seconds=900.0,
    )
    assert row["match"] is None
    assert row["not_comparable"] is True
    # Both readings survive for the reader.
    assert row["values"] == {TRADINGVIEW: -1.9, FINVIZ: 0.27}


def test_same_session_readings_are_still_compared():
    from tapebasis.reconcile import FINVIZ, TRADINGVIEW, compare_values

    row = compare_values(
        {TRADINGVIEW: -1.9, FINVIZ: -1.88},
        tolerance_pct=2.0,
        times={
            TRADINGVIEW: "2026-11-03T20:59:00+00:00",
            FINVIZ: "2026-11-03T21:00:00+00:00",
        },
        max_skew_seconds=900.0,
    )
    assert row["match"] is True


def test_price_is_compared_across_minutes():
    """A price stays comparable when timestamps are close; skew only guards
    session-relative fields, which opt in per FieldSpec."""
    from tapebasis.reconcile import FINVIZ, TRADINGVIEW, compare_values

    row = compare_values(
        {TRADINGVIEW: 331.9, FINVIZ: 331.8},
        tolerance_pct=0.5,
        times={
            TRADINGVIEW: "2026-11-03T20:59:00+00:00",
            FINVIZ: "2026-11-03T21:00:00+00:00",
        },
        max_skew_seconds=900.0,
    )
    assert row["match"] is True


def test_require_all_times_refuses_to_assert_agreement_without_proof():
    """Finviz screener rows carry no print time; a match cannot be claimed."""
    from tapebasis.reconcile import FINVIZ, TRADINGVIEW, compare_values

    row = compare_values(
        {TRADINGVIEW: 331.9, FINVIZ: 331.9},
        tolerance_pct=0.5,
        times={TRADINGVIEW: "2026-11-04T00:59:53+00:00", FINVIZ: None},
        require_all_times=True,
    )
    assert row["match"] is None
    assert row["not_comparable"] is True
    assert "no print time" in row["pairs"][0]["not_comparable"]


def test_not_comparable_is_reported_but_not_counted_as_disagreement():
    from tapebasis.reconcile import (
        FINVIZ,
        TRADINGVIEW,
        FieldSpec,
        merge_many,
    )

    merged = merge_many(
        {TRADINGVIEW: {"change_percent": -1.9}, FINVIZ: {"change_percent": 0.27}},
        (
            FieldSpec(
                "change_percent",
                lambda p: p["change_percent"],
                lambda p: p["change_percent"],
                max_skew_seconds=900.0,
            ),
        ),
        times={
            TRADINGVIEW: "2026-11-04T00:59:53+00:00",
            FINVIZ: "2026-11-04T10:28:00+00:00",
        },
    )
    assert merged.mismatches == []       # not a conflict
    assert merged.not_comparable == ["change_percent"]
    # The newest provider's value is still the one served.
    assert merged.data["change_percent"] == 0.27


def test_session_roll_is_caught_even_when_prints_are_seconds_apart():
    """Seconds-based skew cannot see a session roll; the session date can.

    Two prints 30 seconds apart across midnight US/Eastern are a whole session
    apart in meaning for a day change, and pass any ``max_skew_seconds`` test.
    """
    from tapebasis.reconcile import FINVIZ, TRADINGVIEW, compare_values

    row = compare_values(
        # 2026-11-04T04:59:40Z == 23:59:40 ET on Nov 3
        # 2026-11-04T05:00:10Z == 00:00:10 ET on Nov 4
        {TRADINGVIEW: -1.9, FINVIZ: -1.88},
        tolerance_pct=2.0,
        times={
            TRADINGVIEW: "2026-11-04T04:59:40+00:00",
            FINVIZ: "2026-11-04T05:00:10+00:00",
        },
        max_skew_seconds=900.0,
        session_boundary=True,
    )
    assert row["match"] is None
    assert row["not_comparable"] is True
    assert "different sessions" in row["pairs"][0]["not_comparable"]


def test_session_boundary_is_one_way_and_never_invents_a_conflict():
    """Within one session the same readings are compared normally.

    The guard may lose a comparison, it may never turn agreement into a
    reported conflict.
    """
    from tapebasis.reconcile import FINVIZ, TRADINGVIEW, compare_values

    row = compare_values(
        {TRADINGVIEW: -1.9, FINVIZ: -1.9},
        tolerance_pct=2.0,
        times={
            TRADINGVIEW: "2026-11-03T20:59:00+00:00",
            FINVIZ: "2026-11-03T21:00:00+00:00",
        },
        max_skew_seconds=900.0,
        session_boundary=True,
    )
    assert row["match"] is True
    assert not row.get("not_comparable")


def test_frozen_feed_is_caught_against_the_clock_not_against_a_peer():
    """Skew compares providers to each other; only the clock sees both frozen."""
    from datetime import datetime, timezone

    from tapebasis.reconcile import FINVIZ, TRADINGVIEW, FieldSpec, merge_many

    spec = FieldSpec(
        "change_percent",
        lambda p: p["change_percent"],
        lambda p: p["change_percent"],
        max_skew_seconds=900.0,
        session_boundary=True,
        max_age_seconds=8 * 3600.0,
    )
    # Both providers agree and print at the same instant: skew is zero. The
    # prints are 23 hours old yet still on the same ET session date, so the
    # clock catches what the peer comparison structurally cannot.
    merged = merge_many(
        {TRADINGVIEW: {"change_percent": -1.9}, FINVIZ: {"change_percent": -1.9}},
        (spec,),
        times={
            TRADINGVIEW: "2026-11-03T05:00:00+00:00",  # 00:00 ET Nov 3
            FINVIZ: "2026-11-03T05:00:05+00:00",
        },
        now=datetime(2026, 11, 4, 4, 0, tzinfo=timezone.utc),  # 23:00 ET Nov 3
    )
    assert merged.mismatches == []
    assert merged.not_comparable == ["change_percent"]
    assert "frozen" in merged.comparisons[0]["pairs"][0]["not_comparable"]


def test_age_ceiling_is_inert_across_a_session_boundary():
    """A quote legitimately ages overnight; a wall-clock ceiling must not fire."""
    from datetime import datetime, timezone

    from tapebasis.reconcile import FINVIZ, TRADINGVIEW, FieldSpec, merge_many

    spec = FieldSpec(
        "change_percent",
        lambda p: p["change_percent"],
        lambda p: p["change_percent"],
        max_skew_seconds=900.0,
        session_boundary=True,
        max_age_seconds=8 * 3600.0,
    )
    # Friday's close read on Sunday: 40 hours old, and correct.
    merged = merge_many(
        {TRADINGVIEW: {"change_percent": -1.9}, FINVIZ: {"change_percent": -1.9}},
        (spec,),
        times={
            TRADINGVIEW: "2026-11-06T21:00:00+00:00",
            FINVIZ: "2026-11-06T21:00:00+00:00",
        },
        now=datetime(2026, 11, 8, 13, 0, tzinfo=timezone.utc),
    )
    assert merged.not_comparable == []
    assert merged.comparisons[0]["match"] is True


def test_field_without_a_shared_definition_is_never_a_conflict():
    """FX day change: no single official previous close, so no comparison.

    The readings are kept, the pair is marked not comparable, and the field is
    never counted as a provider conflict, at any timestamp.
    """
    from tapebasis.reconcile import FINVIZ, TRADINGVIEW, compare_values

    row = compare_values(
        {TRADINGVIEW: 0.0935, FINVIZ: 0.3101},
        tolerance_pct=2.0,
        absolute_floor=0.05,
        times={
            TRADINGVIEW: "2026-11-05T09:40:28+00:00",
            FINVIZ: "2026-11-05T09:40:29+00:00",
        },
        max_skew_seconds=900.0,
        session_boundary=True,
        not_comparable_reason="spot FX has no single official previous close",
    )
    assert row["match"] is None
    assert row["not_comparable"] is True
    assert row["values"] == {TRADINGVIEW: 0.0935, FINVIZ: 0.3101}
    assert "previous close" in row["pairs"][0]["not_comparable"]


def test_fx_is_detected_from_any_providers_asset_class():
    from tapebasis.tools_market import _is_fx, _quote_specs
    from tapebasis.symbols import Resolution

    fx = Resolution(query="EURUSD", provider="TRADINGVIEW", asset_class="forex")
    yahoo_fx = Resolution(query="EURUSD=X", provider="YAHOO", asset_class="currency")
    stock = Resolution(query="AAPL", provider="TRADINGVIEW", asset_class="stock")

    assert _is_fx(fx) is True
    assert _is_fx(stock, yahoo_fx) is True   # Finviz never carries FX
    assert _is_fx(stock) is False

    fx_spec = next(s for s in _quote_specs(spot_fx=True)
                   if s.name == "change_percent")
    equity_spec = next(s for s in _quote_specs() if s.name == "change_percent")
    assert fx_spec.not_comparable_reason
    assert equity_spec.not_comparable_reason is None


def test_fx_previous_close_and_volume_are_the_same_structural_boundary():
    """The FX rule must cover the close the change is measured from, and volume.

    Refusing to compare an FX day change while still calling the previous close
    a disagreement is the tool contradicting itself: the close *is* the baseline
    the day change lacks. Volume has no exchange session to accumulate over, and
    Yahoo reports 0 for every pair, so the 1 % tolerance scored a 100 % conflict
    on every FX quote. All three are reported, none is a conflict, and an
    equity keeps all three compared.
    """
    from tapebasis.tools_market import _quote_specs

    fx = {s.name: s for s in _quote_specs(spot_fx=True)}
    equity = {s.name: s for s in _quote_specs()}

    for name in ("change_percent", "previous_close", "volume"):
        assert fx[name].not_comparable_reason, name
        assert equity[name].not_comparable_reason is None, name

    # The reasons are distinct facts, not one sentence reused three times.
    reasons = {
        name: fx[name].not_comparable_reason
        for name in ("change_percent", "previous_close", "volume")
    }
    assert len(set(reasons.values())) == 3

    # Fields that do have a shared definition on FX stay comparable.
    for name in ("price", "week_52_high", "day_high", "day_low"):
        assert fx[name].not_comparable_reason is None, name


# ── snapshot join keys ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_fx_rows_join_instead_of_duplicating(monkeypatch):
    """``FX:USDJPY`` and Yahoo's ``JPY=X`` are one instrument, not two."""
    from tapebasis import yh_access
    from tapebasis.providers.tradingview import native as tv_native

    assert tv_native.SNAPSHOT_YAHOO_EQUIVALENT["FX:USDJPY"] == "JPY=X"

    async def fake_quote(symbol):
        # Yahoo reports JPY=X even when asked for USDJPY=X.
        return {
            "symbol": "JPY=X",
            "price": 158.4,
            "change_pct": 0.1,
            "currency": "JPY",
            "market_time": 1793739601,
        }

    monkeypatch.setattr(yh_access, "quote", fake_quote)
    snapshot = await yh_access.market_snapshot()
    fx_symbols = [row["symbol"] for row in snapshot["fx"]]
    assert "JPY=X" in fx_symbols
    assert "USDJPY=X" not in fx_symbols
