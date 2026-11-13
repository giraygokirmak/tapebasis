"""Hermetic end-to-end tests of the multi-source tools with faked providers.

These assert the *contract* the server promises: multi-source (``ALL``) when
every provider asked answers, single-source (explicitly labelled) when only one
does, ``NONE`` when none do, one price per field, and drift warnings propagated
into ordinary tool responses.
"""
from __future__ import annotations

from types import SimpleNamespace

import time

import pytest

from tapebasis import tools_finviz, tools_market
from tapebasis.symbols import Resolution


def _resolved(provider: str, symbol: str | None, *, query: str = "AAPL") -> Resolution:
    """A synthetic resolution so no test ever touches a symbol-search endpoint."""
    return Resolution(
        query=query,
        provider=provider,
        symbol=symbol,
        method="explicit" if symbol else "none",
        confidence=1.0 if symbol else 0.0,
        note="" if symbol else f"{provider} does not carry {query}",
    )


@pytest.fixture
def fake_providers(monkeypatch, tv_quote, fv_quote, yh_quote, sa_quote):
    """Patch every access layer with deterministic in-memory providers.

    ``state["bb"]`` is ``None`` by default: Bloomberg answered, but had no
    quote for the fixture. That records ``NOT_ATTEMPTED`` rather than a
    failure, so the assertions about the other legs stay meaningful; tests that
    want the Bloomberg leg set it to a payload. ``state["sa"]`` behaves the
    same way for StockAnalysis.
    """
    from tapebasis import bb_access, fv_access, sa_access, tv_access, yh_access
    from tapebasis.providers_state import NoDataError

    state = {"tv": tv_quote, "fv": fv_quote, "yh": yh_quote, "bb": None, "sa": None}

    async def tv_quote_call(symbol):
        if isinstance(state["tv"], Exception):
            raise state["tv"]
        return state["tv"]

    async def fv_quote_call(symbol):
        if isinstance(state["fv"], Exception):
            raise state["fv"]
        return state["fv"]

    async def yh_quote_call(symbol):
        if isinstance(state["yh"], Exception):
            raise state["yh"]
        return state["yh"]

    async def sa_quote_call(symbol):
        if state["sa"] is None:
            raise NoDataError("SA", "StockAnalysis has no quote in this fixture")
        if isinstance(state["sa"], Exception):
            raise state["sa"]
        return state["sa"]

    async def bb_quote_call(symbol):
        if state["bb"] is None:
            raise NoDataError("BLOOMBERG", "Bloomberg has no quote in this fixture")
        if isinstance(state["bb"], Exception):
            raise state["bb"]
        return state["bb"], f"https://www.bloomberg.com/quote/{symbol}"

    async def fake_resolve(query, provider, **kwargs):
        symbol = {"TRADINGVIEW": "NASDAQ:AAPL", "FINVIZ": "AAPL", "YAHOO": "AAPL"}.get(provider)
        return _resolved(provider, symbol, query=query)

    monkeypatch.setattr(tv_access, "quote", tv_quote_call)
    monkeypatch.setattr(fv_access, "quote", fv_quote_call)
    monkeypatch.setattr(yh_access, "quote", yh_quote_call)
    monkeypatch.setattr(sa_access, "quote", sa_quote_call)
    monkeypatch.setattr(bb_access, "quote", bb_quote_call)
    monkeypatch.setattr(tools_market, "resolve", fake_resolve)
    monkeypatch.setattr(
        tools_market,
        "resolve_sa",
        lambda query, **kwargs: _resolved("SA", "aapl", query=query),
    )
    return state


def _bloomberg_quote(*, price=331.9, print_time="2026-11-03T21:00:01+00:00"):
    """Bloomberg's shaped quote, as ``bb_access.shape_quote`` would return it."""
    return {
        "symbol": "AAPL:US",
        "requested": "AAPL",
        "name": "APPLE INC",
        "price": price,
        "change_percent": -1.9,
        "previous_close": 338.32,
        "currency": "USD",
        "exchange": "NASDAQ GS",
        "day_range": [330.5, 338.0],
        "week_52_range": [243.42, 351.73],
        "volume": 63160515.0,
        "pe_ratio": 36.5,
        "eps": 8.98,
        "market_status": "ACTV",
        "is_open": False,
        "is_after_hours": True,
        "is_exchange_delayed": True,
        "exchange_delay": "15 Minutes",
        "trading_date": "2026-11-03",
        "trading_day_close": "2026-11-03T21:00:00.000Z",
        "print_time": print_time,
        "print_time_source": "priceMovements1Day[-1].dateTime",
        "print_time_missing_reason": None,
        "provider_last_update": "2026-11-04T01:00:00.000Z",
    }


@pytest.mark.asyncio
async def test_quote_all_when_every_provider_answers(fake_providers):
    result = await tools_market.stock_quote("AAPL")
    assert result["data_provider"] == "PARTIAL"
    assert result["verification"] == "MULTI_SOURCE"
    assert result["providers_answered"] == ["TRADINGVIEW", "FINVIZ", "YAHOO"]
    assert {e["provider"] for e in result["errors"]} == {"SA", "BLOOMBERG"}
    assert all(e["code"] == "NO_DATA" for e in result["errors"])
    fields = {row["field"]: row["match"] for row in result["comparisons"]}
    assert fields["price"] is True
    assert result["data"]["price"] == pytest.approx(331.9)


@pytest.mark.asyncio
async def test_all_is_reported_for_two_of_three(fake_providers):
    """A leg that was asked and failed makes coverage PARTIAL, never ALL.

    This used to assert ``ALL`` with a Yahoo error in the same response, which
    told the reader every provider asked had answered. Coverage is a claim about
    the ask set, and Yahoo was in it.
    """
    fake_providers["yh"] = RuntimeError("yahoo outage")
    result = await tools_market.stock_quote("AAPL")
    assert result["data_provider"] == "PARTIAL"
    assert result["verification"] == "MULTI_SOURCE"
    assert result["providers_answered"] == ["TRADINGVIEW", "FINVIZ"]
    assert [e["provider"] for e in result["errors"]] == ["YAHOO", "SA", "BLOOMBERG"]
    assert "PARTIAL" in result["notice"]


@pytest.mark.asyncio
async def test_quote_labels_single_source_when_finviz_and_yahoo_fail(fake_providers):
    fake_providers["fv"] = RuntimeError("finviz outage")
    fake_providers["yh"] = RuntimeError("yahoo outage")
    result = await tools_market.stock_quote("AAPL")
    assert result["data_provider"] == "TRADINGVIEW"
    assert result["verification"] == "SINGLE_SOURCE"
    assert "single-source" in result["notice"].lower()
    assert {e["provider"] for e in result["errors"]} == {
        "FINVIZ", "YAHOO", "SA", "BLOOMBERG"
    }
    # The surviving provider's value is still served.
    assert result["data"]["price"] == pytest.approx(331.9)


@pytest.mark.asyncio
async def test_quote_can_label_yahoo_as_the_only_source(fake_providers):
    fake_providers["tv"] = RuntimeError("tradingview outage")
    fake_providers["fv"] = RuntimeError("finviz outage")
    result = await tools_market.stock_quote("AAPL")
    assert result["data_provider"] == "YAHOO"
    assert result["verification"] == "SINGLE_SOURCE"
    assert result["data"]["price"] == pytest.approx(331.9)


@pytest.mark.asyncio
async def test_quote_none_when_every_provider_fails(fake_providers):
    for key in ("tv", "fv", "yh"):
        fake_providers[key] = RuntimeError("down")
    result = await tools_market.stock_quote("AAPL")
    assert result["data_provider"] == "NONE"
    assert result["verification"] == "UNAVAILABLE"
    assert result["data"] == {}
    assert {e["provider"] for e in result["errors"]} == {
        "TRADINGVIEW",
        "FINVIZ",
        "YAHOO",
        "SA",
        "BLOOMBERG",
    }


@pytest.mark.asyncio
async def test_quote_reports_no_data_after_resolution(fake_providers):
    from tapebasis.providers_state import NoDataError

    for key in ("tv", "fv", "yh"):
        fake_providers[key] = NoDataError(
            {"tv": "TRADINGVIEW", "fv": "FINVIZ", "yh": "YAHOO"}[key],
            "resolved symbol has empty payload",
        )
    fake_providers["bb"] = _bloomberg_quote()

    result = await tools_market.stock_quote("AAPL")

    assert result["data_provider"] == "BLOOMBERG"
    errors = {e["provider"]: e for e in result["errors"]}
    for provider in ("TRADINGVIEW", "FINVIZ", "YAHOO"):
        assert errors[provider]["code"] == "NO_DATA"
        assert "empty payload" in errors[provider]["message"]


@pytest.mark.asyncio
async def test_quote_flags_a_real_mismatch_instead_of_hiding_it(fake_providers):
    fake_providers["tv"]["close"] = 300.0  # 10% off the other two
    result = await tools_market.stock_quote("AAPL")
    assert result["data_provider"] == "PARTIAL"  # every resolved request is in the ask set
    price_row = next(r for r in result["comparisons"] if r["field"] == "price")
    assert price_row["match"] is False  # ...but they do not agree
    assert "disagree" in result["notice"]
    assert any("disagree" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_symbol_finviz_does_not_carry_is_not_an_error(
    monkeypatch, tv_quote, yh_quote
):
    """XAUUSD: TradingView and Yahoo answer, Finviz has no page. Not a failure."""
    from tapebasis import bb_access, tv_access, yh_access
    from tapebasis.providers_state import NoDataError

    async def tv_quote_call(symbol):
        return {**tv_quote, "close": 4046.42}

    async def yh_quote_call(symbol):
        return {**yh_quote, "price": 4046.42}

    async def bb_unavailable(symbol):
        raise NoDataError("BLOOMBERG", "no page in this fixture")

    async def fake_resolve(query, provider, **kwargs):
        return {
            "TRADINGVIEW": _resolved(provider, "OANDA:XAUUSD", query=query),
            "FINVIZ": _resolved(provider, None, query=query),
            "YAHOO": _resolved(provider, "XAUUSD=X", query=query),
        }[provider]

    monkeypatch.setattr(tv_access, "quote", tv_quote_call)
    monkeypatch.setattr(yh_access, "quote", yh_quote_call)
    monkeypatch.setattr(bb_access, "quote", bb_unavailable)
    monkeypatch.setattr(tools_market, "resolve", fake_resolve)

    result = await tools_market.stock_quote("XAUUSD")
    assert result["data_provider"] == "PARTIAL"
    # StockAnalysis does not carry this instrument, so it was never asked.
    assert [e["provider"] for e in result["errors"]] == ["BLOOMBERG"]
    assert result["errors"][0]["code"] == "NO_DATA"
    assert result["providers_answered"] == ["TRADINGVIEW", "YAHOO"]
    assert result["resolutions"]["FINVIZ"]["symbol"] is None
    assert result["resolutions"]["TRADINGVIEW"]["symbol"] == "OANDA:XAUUSD"
    assert result["resolutions"]["YAHOO"]["symbol"] == "XAUUSD=X"


@pytest.mark.asyncio
async def test_finviz_only_tool_is_explicitly_single_source(monkeypatch):
    from tapebasis import fv_access

    async def fake_why(symbol):
        return {"ticker": "AAPL", "headline": "AAPL rises on product news"}

    monkeypatch.setattr(fv_access, "why_moving", fake_why)
    result = await tools_finviz.stock_why_moving("AAPL")
    assert result["data_provider"] == "FINVIZ"
    assert result["verification"] == "SINGLE_SOURCE"
    assert "single-source" in result["notice"].lower()
    assert result["data"]["headline"].startswith("AAPL rises")


@pytest.mark.asyncio
async def test_finviz_only_tool_reports_none_on_failure(monkeypatch):
    from tapebasis import fv_access
    from tapebasis.providers_state import ProviderError

    async def broken(symbol):
        raise ProviderError("FINVIZ", "upstream blocked", code="UPSTREAM_BLOCKED")

    monkeypatch.setattr(fv_access, "why_moving", broken)
    result = await tools_finviz.stock_why_moving("AAPL")
    assert result["data_provider"] == "NONE"
    assert result["errors"][0]["code"] == "UPSTREAM_BLOCKED"


@pytest.mark.asyncio
async def test_drift_warning_reaches_normal_tool_responses(fake_providers, _isolate_health_state):
    from tapebasis import health

    _isolate_health_state.results = {
        "p": health.ProbeResult(
            id="p",
            provider="TRADINGVIEW",
            description="scanner",
            url="https://scanner",
            status=health.STATUS_DRIFT,
            message="payload shape changed",
        )
    }
    result = await tools_market.stock_quote("AAPL")
    assert result["degraded"] is True
    assert any("DRIFT" in warning for warning in result["warnings"])
    assert "WARNING" in result["notice"]


# ── one price, freshest print ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quote_returns_a_single_price_and_explains_which(fake_providers):
    """One price, and the reason it is that one, in the notice."""
    result = await tools_market.stock_quote("AAPL")
    assert isinstance(result["data"]["price"], (int, float))
    # TradingView and Yahoo print at the close instant; Finviz renders 3:59 PM,
    # one minute earlier, so the newest instant is a two-way tie.
    assert result["freshness"]["chosen"] == "TRADINGVIEW"
    assert result["freshness"]["decision"] == "tie"
    assert result["freshness"]["finviz"] == "2026-11-03T20:59:00+00:00"
    assert "same instant" in result["notice"]


@pytest.mark.asyncio
async def test_quote_prefers_the_provider_that_printed_last(fake_providers):
    """Freshness, not provider identity, decides."""
    fake_providers["tv"]["update_time"] = "2026-11-03T20:00:00+00:00"
    fake_providers["yh"]["market_time"] = "2026-11-03T20:30:00+00:00"
    result = await tools_market.stock_quote("AAPL")
    assert result["freshness"]["chosen"] == "FINVIZ"
    assert result["freshness"]["decision"] == "newest"
    assert "printed more recently" in result["notice"]

    fake_providers["fv"]["last_close"]["date"] = "Nov 03 • 3:00 PM ET"
    result = await tools_market.stock_quote("AAPL")
    assert result["freshness"]["chosen"] == "YAHOO"


@pytest.mark.asyncio
async def test_every_value_survives_in_comparisons_after_selection(fake_providers):
    """Selecting one value must not discard the audit trail."""
    fake_providers["fv"]["last_close"]["price"] = 340.0
    result = await tools_market.stock_quote("AAPL")
    row = next(c for c in result["comparisons"] if c["field"] == "price")
    assert row["values"]["TRADINGVIEW"] == pytest.approx(331.9)
    assert row["values"]["FINVIZ"] == pytest.approx(340.0)
    assert row["values"]["YAHOO"] == pytest.approx(331.9)
    assert row["match"] is False
    assert row["chosen"] == "TRADINGVIEW"
    assert "Providers disagree on: price" in result["warnings"]


# ── Bloomberg as a reconciliation leg ───────────────────────────────────────


@pytest.mark.asyncio
async def test_quote_counts_bloomberg_when_it_answers(fake_providers):
    """Bloomberg answered: its reading is named, while StockAnalysis's miss is explicit."""
    fake_providers["bb"] = _bloomberg_quote()
    result = await tools_market.stock_quote("AAPL")
    assert result["data_provider"] == "PARTIAL"
    assert result["providers_answered"] == [
        "TRADINGVIEW",
        "FINVIZ",
        "YAHOO",
        "BLOOMBERG",
    ]
    assert [e["provider"] for e in result["errors"]] == ["SA"]
    assert result["errors"][0]["code"] == "NO_DATA"
    price_row = next(c for c in result["comparisons"] if c["field"] == "price")
    assert price_row["values"]["BLOOMBERG"] == pytest.approx(331.9)
    # The delay travels with the payload, not only inside the comparison block.
    assert result["data"]["exchange_delay"] == "15 Minutes"
    assert result["data"]["print_time"] == "2026-11-03T21:00:01+00:00"


@pytest.mark.asyncio
async def test_quote_reports_a_delayed_bloomberg_print_as_not_comparable(fake_providers):
    """15 minutes behind is a different observation, never a disagreement."""
    fake_providers["bb"] = _bloomberg_quote(print_time="2026-11-03T20:30:00+00:00")
    result = await tools_market.stock_quote("AAPL")
    price_row = next(c for c in result["comparisons"] if c["field"] == "price")
    pairs = {tuple(p["between"]): p for p in price_row["pairs"]}
    for other in ("TRADINGVIEW", "FINVIZ", "YAHOO"):
        pair = pairs[(other, "BLOOMBERG")]
        assert pair["match"] is None
        assert "exchange-delayed" in pair["not_comparable"]
    # The delayed reading is still visible, and it did not become a conflict.
    assert price_row["values"]["BLOOMBERG"] == pytest.approx(331.9)
    assert "disagree" not in result["notice"]


@pytest.mark.asyncio
async def test_bloomberg_never_wins_the_freshness_tie_break(fake_providers):
    """On a tied instant the live feed is shown, not the delayed page."""
    fake_providers["bb"] = _bloomberg_quote()
    result = await tools_market.stock_quote("AAPL")
    assert result["freshness"]["chosen"] != "BLOOMBERG"


@pytest.mark.asyncio
async def test_bloomberg_failure_is_an_error_not_a_lost_response(fake_providers):
    """A blocked Bloomberg leg is reported, and it costs the ALL claim.

    Bloomberg was asked, Bloomberg failed, so the response is PARTIAL. Calling
    that ``ALL`` would claim complete coverage while listing the failure in the
    same payload.
    """
    from tapebasis.providers_state import ProviderError

    # The fixture raises whatever exception object the state holds.
    fake_providers["bb"] = ProviderError(
        "BLOOMBERG", "HTTP 403 bot wall", code="UPSTREAM_BLOCKED"
    )
    result = await tools_market.stock_quote("AAPL")
    assert result["data_provider"] == "PARTIAL"
    assert result["providers_answered"] == ["TRADINGVIEW", "FINVIZ", "YAHOO"]
    assert [e["provider"] for e in result["errors"]] == ["SA", "BLOOMBERG"]
    assert result["data"]["price"] == pytest.approx(331.9)


@pytest.mark.asyncio
async def test_prices_ask_bloomberg_and_keep_the_delay_visible(fake_providers, monkeypatch):
    from tapebasis import fv_access, tv_access

    async def tv_quotes(symbols):
        # ``tv_access.quotes`` returns rows keyed by bare ticker.
        return {
            "AAPL": {
                "ticker": "NASDAQ:AAPL",
                "close": 331.9,
                "change": -1.9,
                "volume": 63160515,
                "update_time": "2026-11-03T21:00:01+00:00",
            }
        }

    async def fv_rows(symbols):
        return [
            {
                "ticker": "AAPL",
                "price": 331.9,
                "change": -1.9,
                "prevClose": 338.32,
                "last_update": "2026-11-03T20:59:00+00:00",
            }
        ]

    async def yh_quote(symbol):
        return {
            "price": 331.9,
            "change_pct": -1.9,
            "previous_close": 338.32,
            "market_time": "2026-11-03T21:00:01+00:00",
            "shortName": "Apple Inc.",
        }

    monkeypatch.setattr(tv_access, "quotes", tv_quotes)
    monkeypatch.setattr(fv_access, "screener_rows", fv_rows)
    from tapebasis import yh_access

    monkeypatch.setattr(yh_access, "quote", yh_quote)
    fake_providers["bb"] = _bloomberg_quote()

    monkeypatch.setattr(tools_market, "resolve_sa", lambda query, **kwargs: _resolved("SA", None))
    result = await tools_market.stock_prices("AAPL")
    row = result["data"][0]
    assert row["data_provider"] == "ALL"
    assert row["providers_answered"] == [
        "TRADINGVIEW",
        "FINVIZ",
        "YAHOO",
        "BLOOMBERG",
    ]
    assert row["exchange_delay"] == "15 Minutes"
    assert row["comparisons"]["price"]["values"]["BLOOMBERG"] == pytest.approx(331.9)


@pytest.mark.asyncio
async def test_prices_expose_symbol_errors_and_keep_other_rows(
    fake_providers, monkeypatch
):
    from tapebasis import fv_access, tv_access, yh_access
    from tapebasis.providers_state import NoDataError, ProviderError

    async def fake_resolve(query, provider, **kwargs):
        if provider == "SA":
            return _resolved(provider, None, query=query)
        if provider == "BLOOMBERG":
            return _resolved(provider, "AAPL:US" if query == "AAPL" else None, query=query)
        return _resolved(
            provider,
            {"TRADINGVIEW": f"NASDAQ:{query}", "FINVIZ": query, "YAHOO": query}[provider],
            query=query,
        )

    async def tv_quotes(symbols):
        return {"AAPL": {
            "ticker": "NASDAQ:AAPL", "close": 100.0, "change": 1.0,
            "update_time": "2026-11-03T21:00:00+00:00",
        }}

    async def fv_rows(symbols):
        return [
            {"ticker": "AAPL", "price": 100.0, "change": 1.0,
             "last_update": "2026-11-03T21:00:00+00:00"},
            {"ticker": "MSFT", "price": 200.0, "change": 1.0,
             "last_update": "2026-11-03T21:00:00+00:00"},
        ]

    async def yh_quote(symbol):
        if symbol == "MSFT":
            raise NoDataError("YAHOO", "chart for MSFT is empty")
        if symbol == "IBM":
            raise ProviderError("YAHOO", "IBM transport failed", code="UPSTREAM_ERROR")
        return {
            "price": 100.0, "change_pct": 1.0,
            "market_time": "2026-11-03T21:00:00+00:00",
        }

    monkeypatch.setattr(tools_market, "resolve", fake_resolve)
    monkeypatch.setattr(tv_access, "quotes", tv_quotes)
    monkeypatch.setattr(fv_access, "screener_rows", fv_rows)
    monkeypatch.setattr(yh_access, "quote", yh_quote)

    result = await tools_market.stock_prices("AAPL,MSFT,IBM")
    msft, ibm = result["data"][1], result["data"][2]

    assert msft["misses"]["YAHOO"] == "chart for MSFT is empty"
    assert msft["errors"][0]["code"] == "NO_DATA"
    assert msft["errors"][0]["symbol"] == "MSFT"
    assert msft["data_provider"] == "FINVIZ"

    assert "no TradingView row returned for IBM" in ibm["misses"]["TRADINGVIEW"]
    errors_by_provider = {error["provider"]: error for error in ibm["errors"]}
    assert errors_by_provider["YAHOO"]["code"] == "UPSTREAM_ERROR"
    assert errors_by_provider["YAHOO"]["symbol"] == "IBM"
    assert ibm["misses"]["YAHOO"] == "IBM transport failed"
    assert ibm["misses"]["FINVIZ"] == "no Finviz row returned for IBM"
    assert ibm["providers_answered"] == []
    assert "YAHOO" in [error["provider"] for error in result["errors"]]
    assert any(error["symbol"] == "IBM" for error in result["errors"])
    assert result["data_provider"] == "PARTIAL"


@pytest.mark.asyncio
async def test_prices_state_the_source_of_every_field(fake_providers, monkeypatch):
    """A row can read ``ALL`` while ``previous_close`` came from one provider.

    ``data_provider`` describes the row, not each number in it. Only ``price``
    and ``change_percent`` are compared, so those two carry the agreement
    verdict; ``previous_close`` and ``volume`` are shaped by one provider and say
    so, which stops a single print being read as a cross-check.
    """
    from tapebasis import fv_access, tv_access, yh_access

    async def tv_quotes(symbols):
        return {
            "AAPL": {
                "ticker": "NASDAQ:AAPL",
                "close": 331.9,
                "change": -1.9,
                "volume": 63160515,
                "update_time": "2026-11-03T21:00:01+00:00",
            }
        }

    async def fv_rows(symbols):
        return [
            {
                "ticker": "AAPL",
                "price": 331.9,
                "change": -1.9,
                "prevClose": 338.32,
                "last_update": "2026-11-03T20:59:00+00:00",
            }
        ]

    async def yh_quote(symbol):
        return {
            "price": 331.9,
            "change_pct": -1.9,
            "previous_close": 338.32,
            "market_time": "2026-11-03T21:00:01+00:00",
            "shortName": "Apple Inc.",
        }

    monkeypatch.setattr(tv_access, "quotes", tv_quotes)
    monkeypatch.setattr(fv_access, "screener_rows", fv_rows)
    monkeypatch.setattr(tools_market, "resolve_sa", lambda query, **kwargs: _resolved("SA", None))
    monkeypatch.setattr(tools_market, "_bloomberg_resolution", lambda symbol: _resolved("BLOOMBERG", None))
    monkeypatch.setattr(yh_access, "quote", yh_quote)

    result = await tools_market.stock_prices("AAPL")
    row = result["data"][0]
    fields = row["fields"]

    assert row["data_provider"] == "ALL"
    # ``supplied`` is who answered; ``compared`` is who was actually judged.
    assert set(fields["price"]["supplied"]) == {"TRADINGVIEW", "FINVIZ", "YAHOO"}
    assert set(fields["price"]["compared"]) == {"TRADINGVIEW", "FINVIZ", "YAHOO"}
    assert fields["price"]["agreement"] is True
    assert fields["price"]["source"] == row["price_source"]
    # A field this tool does not compare says who supplied a reading and claims
    # no cross-check, because none ran. ``previous_close`` is shaped by more than
    # one provider, which is exactly why ``supplied`` had to be separate from
    # ``source``: the value is one print, the coverage is wider.
    for name in ("previous_close", "volume"):
        assert fields[name]["source"] in fields[name]["supplied"]
        assert fields[name]["compared"] == []
        assert fields[name]["agreement"] is None
    # TradingView supplies a previous close too: it recovers the baseline from
    # the change beside its own print rather than borrowing the stale ``close``
    # column, so it is a supplier of this field and not only of the price.
    assert fields["previous_close"]["supplied"] == ["TRADINGVIEW", "FINVIZ", "YAHOO"]
    assert set(fields) == {"price", "change_percent", "previous_close", "volume"}


@pytest.mark.asyncio
async def test_prices_fill_an_uncontested_field_from_a_provider_that_has_it(
    fake_providers, monkeypatch
):
    """Reading extras off the winning provider dropped data every row.

    TradingView prints most recently here and its row omits ``change``, so it
    carries no recoverable baseline; every row reported ``null`` for a number
    three other providers had shaped.
    """
    from tapebasis import fv_access, tv_access, yh_access

    async def tv_quotes(symbols):
        return {
            "AAPL": {
                "ticker": "NASDAQ:AAPL",
                "close": 331.9,
                "volume": 63160515,
                "update_time": "2026-11-03T21:00:01+00:00",
            }
        }

    async def fv_rows(symbols):
        return [
            {
                "ticker": "AAPL",
                "price": 331.9,
                "change": -1.9,
                "prevClose": 338.32,
                "last_update": "2026-11-03T20:59:00+00:00",
            }
        ]

    async def yh_quote(symbol):
        return {
            "price": 331.9,
            "change_pct": -1.9,
            "previous_close": 338.32,
            "market_time": "2026-11-03T21:00:01+00:00",
        }

    monkeypatch.setattr(tv_access, "quotes", tv_quotes)
    monkeypatch.setattr(fv_access, "screener_rows", fv_rows)
    monkeypatch.setattr(yh_access, "quote", yh_quote)

    row = (await tools_market.stock_prices("AAPL"))["data"][0]
    assert row["price_source"] == "TRADINGVIEW"
    assert row["previous_close"] == pytest.approx(338.32)
    # Yahoo printed at 21:00:01 and Finviz at 20:59:00, so the newer print
    # supplies the uncontested field even though Finviz comes first in the
    # documented order. Display order only breaks a tie on the same instant.
    assert row["fields"]["previous_close"]["source"] == "YAHOO"
    assert row["volume"] == 63160515
    assert row["fields"]["volume"]["source"] == "TRADINGVIEW"


@pytest.mark.asyncio
async def test_prices_fill_ignores_a_provider_with_no_print_time(
    fake_providers, monkeypatch
):
    """A provider that cannot date its reading must not outrank one that can."""
    from tapebasis import fv_access, tv_access, yh_access

    async def tv_quotes(symbols):
        return {
            "AAPL": {
                "ticker": "NASDAQ:AAPL",
                "close": 331.9,
                "change": -1.9,
                "update_time": "2026-11-03T21:00:01+00:00",
            }
        }

    async def fv_rows(symbols):
        return [
            {
                "ticker": "AAPL",
                "price": 331.9,
                "change": -1.9,
                "prevClose": 338.32,
                # No ``last_update``: an undated screener row.
            }
        ]

    async def yh_quote(symbol):
        return {
            "price": 331.9,
            "change_pct": -1.9,
            "previous_close": 338.32,
            "market_time": "2026-11-03T21:00:01+00:00",
        }

    monkeypatch.setattr(tv_access, "quotes", tv_quotes)
    monkeypatch.setattr(fv_access, "screener_rows", fv_rows)
    monkeypatch.setattr(yh_access, "quote", yh_quote)

    row = (await tools_market.stock_prices("AAPL"))["data"][0]
    # The undated Finviz row must not win. TradingView and Yahoo both carry the
    # print instant here, so the documented order breaks that tie; what matters
    # is that the provider which published no time at all is not credited with
    # being current.
    assert row["fields"]["previous_close"]["source"] in ("TRADINGVIEW", "YAHOO")
    assert row["fields"]["previous_close"]["source"] != "FINVIZ"


# ── StockAnalysis as the fifth leg ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_quote_counts_stockanalysis_when_it_answers(fake_providers, monkeypatch):
    """StockAnalysis is a leg, not a side channel: it names itself in coverage."""
    fake_providers["sa"] = _stockanalysis_quote()
    monkeypatch.setattr(tools_market, "_bloomberg_resolution", lambda symbol: _resolved("BLOOMBERG", None))
    result = await tools_market.stock_quote("AAPL")
    assert result["data_provider"] == "ALL"
    assert result["providers_answered"] == [
        "TRADINGVIEW",
        "FINVIZ",
        "YAHOO",
        "SA",
    ]
    assert result["errors"] == []
    price_row = next(c for c in result["comparisons"] if c["field"] == "price")
    # StockAnalysis says ``session: post`` and puts the post-market print in
    # ``extended_hours``. That is the number it calls the price right now, so it
    # is what the comparison judges; the regular close it also keeps is a
    # different session's observation and comparing it would pit a stale print
    # against live ones.
    assert price_row["values"]["SA"] == pytest.approx(329.8)


@pytest.mark.asyncio
async def test_stockanalysis_disagreement_is_reported_like_any_other(fake_providers):
    """The fifth vote counts both ways: a divergent reading is a real conflict."""
    fake_providers["sa"] = _stockanalysis_quote(price=331.9 * 1.05)
    result = await tools_market.stock_quote("AAPL")
    price_row = next(c for c in result["comparisons"] if c["field"] == "price")
    assert price_row["match"] is False
    # The warning names every field that disagreed, so asserting the exact string
    # would break on an unrelated field joining the list.
    assert any(
        w.startswith("Providers disagree on:") and "price" in w
        for w in result["warnings"]
    )


@pytest.mark.asyncio
async def test_quote_carries_the_stockanalysis_extended_hours_block(fake_providers):
    fake_providers["sa"] = fake_providers["sa"] or _stockanalysis_quote()
    result = await tools_market.stock_quote("AAPL")
    extended = result["data"]["stockanalysis_extended_hours"]
    assert extended["session"] == "Post-market"
    assert extended["price"] == pytest.approx(329.8)


@pytest.mark.asyncio
async def test_prices_ask_stockanalysis_and_keep_its_row(fake_providers, monkeypatch):
    from tapebasis import fv_access, sa_access, tv_access, yh_access

    async def tv_quotes(symbols):
        return {
            "AAPL": {
                "ticker": "NASDAQ:AAPL",
                "close": 331.9,
                "change": -1.9,
                "volume": 63160515,
                "update_time": "2026-11-03T21:00:01+00:00",
            }
        }

    async def fv_rows(symbols):
        return [
            {
                "ticker": "AAPL",
                "price": 331.9,
                "change": -1.9,
                "prevClose": 338.32,
                "last_update": "2026-11-03T20:59:00+00:00",
            }
        ]

    async def yh_quote_call(symbol):
        return {
            "price": 331.9,
            "change_pct": -1.9,
            "previous_close": 338.32,
            "market_time": "2026-11-03T21:00:01+00:00",
            "shortName": "Apple Inc.",
        }

    async def sa_quote_call(symbol):
        return _stockanalysis_quote()

    monkeypatch.setattr(tv_access, "quotes", tv_quotes)
    monkeypatch.setattr(fv_access, "screener_rows", fv_rows)
    monkeypatch.setattr(yh_access, "quote", yh_quote_call)
    monkeypatch.setattr(sa_access, "quote", sa_quote_call)

    result = await tools_market.stock_prices("AAPL")
    row = result["data"][0]
    assert row["providers_answered"] == ["TRADINGVIEW", "FINVIZ", "YAHOO", "SA"]
    # StockAnalysis names its own session (``post``) and carries that session's
    # print in ``extended_hours``. The comparison has to judge the number the
    # provider calls the price right now, which is the post-market print, not
    # the regular close it also keeps. Serving the regular close here made this
    # provider look hours stale on every extended-hours request.
    assert row["comparisons"]["price"]["values"]["SA"] == pytest.approx(329.8)


@pytest.mark.asyncio
async def test_prices_use_the_session_print_and_keep_the_row_coherent(
    fake_providers, monkeypatch
):
    """A pre-market row states its session and measures against its own base.

    Before this, a row could hold TradingView's regular-session ``close`` as its
    price, label no session at all, and take ``previous_close`` from a provider
    looking at a different day, so the row implied a day change that neither the
    ``change_percent`` beside it nor any provider reported.
    """
    from tapebasis import fv_access, sa_access, tv_access, yh_access

    async def tv_quotes(symbols):
        return {
            "AAPL": {
                "ticker": "NASDAQ:AAPL",
                "close": 331.9,
                "change": -1.9,
                "volume": 63160515,
                "update_time": "2026-11-04T12:30:00+00:00",
                # The scanner says which session it is in, and where that
                # session's own print is. ``premarket_change`` is sent at full
                # float precision, so its arithmetic recovers the baseline
                # exactly; the fixture uses the same precision as the feed.
                "current_session": "pre_market",
                "premarket_close": 335.0,
                "premarket_change": (335.0 / 331.9 - 1) * 100,
            }
        }

    async def fv_rows(symbols):
        return []

    async def yh_quote_call(symbol):
        return {
            "price": 331.9,
            "change_pct": -1.9,
            "previous_close": 338.32,
            "market_time": "2026-11-03T21:00:01+00:00",
            "shortName": "Apple Inc.",
            "fullday_price": 335.0,
            "fullday_change_percent": (335.0 / 331.9 - 1) * 100,
        }

    async def sa_quote_call(symbol):
        return _stockanalysis_quote()

    monkeypatch.setattr(tv_access, "quotes", tv_quotes)
    monkeypatch.setattr(fv_access, "screener_rows", fv_rows)
    monkeypatch.setattr(yh_access, "quote", yh_quote_call)
    monkeypatch.setattr(sa_access, "quote", sa_quote_call)

    row = (await tools_market.stock_prices("AAPL"))["data"][0]
    assert row["session"] == "pre_market"
    assert row["price"] == pytest.approx(335.0)
    # The field the price was read from is stated, not implied: the swap from
    # the regular ``close`` to the extended print is the whole point of the row.
    assert row["price_field"] == "premarket_close"
    # The same session's own baseline, not another provider's older close.
    assert row["previous_close"] == pytest.approx(331.9)
    # The invariant that was broken: the row's own three numbers describe one
    # session, so the day change they imply is the day change reported.
    implied = (row["price"] - row["previous_close"]) / row["previous_close"] * 100
    assert row["change_percent"] == pytest.approx(implied, abs=1e-3)
    assert row["change_percent"] > 0.5
    # Yahoo publishes the session-inclusive print beside its regular one.
    assert row["comparisons"]["price"]["values"]["YAHOO"] == pytest.approx(335.0)


@pytest.mark.asyncio
async def test_quote_labels_the_session_of_the_print_it_serves(fake_providers, monkeypatch):
    """A delayed leg's session label must not describe another leg's print.

    Measured live at 09:39 ET: TradingView's scanner said ``pre_market`` because
    its feed was 15 minutes delayed (``delayed_streaming_900``), while the
    winning print was Yahoo's regular-session one. Labelling the row from the
    scanner made ``stock_quote`` and ``stock_prices`` disagree about the same
    symbol at the same moment.
    """
    from tapebasis import fv_access, tv_access, yh_access

    async def tv_quote_call(symbol):
        # The scanner is still on the pre-market window and carries a stale
        # regular close; its label is honest about itself, not about Yahoo.
        return {
            "close": 331.9,
            "change": -1.9,
            "premarket_close": 335.0,
            "premarket_change": (335.0 / 331.9 - 1) * 100,
            "current_session": "pre_market",
            "update_time": "2026-11-03T13:00:00+00:00",
            "volume": 1000,
        }

    async def fv_quote_call(symbol):
        # An older print than Yahoo's, so it cannot win the freshness race.
        return {
            "ticker": "AAPL",
            "last_close": {
                "price": 340.0,
                "date": "Nov 03 • 12:55 PM ET",
                "change_percent": 1.285,
            },
            "snapshot_numeric": {"Prev Close": 335.683},
        }

    async def yh_quote_call(symbol):
        # Yahoo's print is a regular-session one and it is the newest, so it
        # wins; the row has to say ``regular``, not ``pre_market``.
        return {
            "price": 340.0,
            "change_pct": 1.285,
            "previous_close": 335.683,
            # 18:00 UTC on 2026-11-03 is 13:00 ET, inside the regular session.
            "market_time": "2026-11-03T18:00:00+00:00",
        }

    monkeypatch.setattr(tv_access, "quote", tv_quote_call)
    monkeypatch.setattr(fv_access, "quote", fv_quote_call)
    monkeypatch.setattr(yh_access, "quote", yh_quote_call)

    result = await tools_market.stock_quote("AAPL")
    assert (result.get("fields", {}).get("price") or {}).get("source") == "YAHOO"
    assert result["session"] == "regular"
    assert result["data"]["session"] == "regular"


@pytest.mark.asyncio
async def test_extended_hours_counts_stockanalysis_when_it_answers(
    fake_providers, monkeypatch
):
    from tapebasis import fv_access, tv_access, yh_access

    async def tv_quote_call(symbol):
        return {**fake_providers["tv"], "postmarket_close": 329.8}

    async def fv_quote_call(symbol):
        return fake_providers["fv"]

    async def yh_hours(symbol):
        return None

    monkeypatch.setattr(tv_access, "quote", tv_quote_call)
    monkeypatch.setattr(fv_access, "quote", fv_quote_call)
    monkeypatch.setattr(yh_access, "extended_hours", yh_hours)
    fake_providers["sa"] = _stockanalysis_quote()

    result = await tools_market.stock_extended_hours("AAPL")
    data = result["data"]
    assert data["after_hours_readings"]["SA"]["price"] == pytest.approx(329.8)
    assert data["stockanalysis_extended_hours"]["session"] == "Post-market"
    # The after-hours comparison is a coverage statement over the legs that
    # actually printed an extended session.
    assert "SA" in data["after_hours_comparison"]["values"]


def _stockanalysis_quote(*, price=331.9, extended_price=329.8):
    """StockAnalysis's shaped quote, as ``sa_access.quote`` returns it."""
    return {
        "symbol": "AAPL",
        "requested": "AAPL",
        "price": price,
        "change": -1.9,
        "change_percent": -1.9,
        "previous_close": 338.32,
        "day_open": 337.1,
        "day_high": 338.0,
        "day_low": 330.5,
        "volume": 63160515.0,
        "week_52_high": 351.73,
        "week_52_low": 243.42,
        "exchange": "NASDAQ",
        "market_state": "closed",
        "session": "post",
        "price_date": "2026-11-03",
        "price_timestamp": "2026-11-03T21:00:01+00:00",
        "price_timestamp_source": "ts (epoch ms)",
        "extended_hours": {
            "session": "Post-market",
            "price": extended_price,
            "change": -2.1,
            "change_percent": -0.63,
            "previous_close": price,
            "volume": 120_000.0,
            "price_timestamp": "2026-11-03T21:00:01+00:00",
            "price_date": "2026-11-03",
        },
        "has_extended_hours": True,
        "source": "stockanalysis.com consolidated quote API",
    }


# ── session range and feed mode: data that arrived and was dropped ───────────


@pytest.mark.asyncio
async def test_quote_compares_the_session_range_from_every_provider(fake_providers):
    """Day high/low arrive on every leg; they must reach the comparison, not stop.

    TradingView returns them on each scanner row, Yahoo in each chart ``meta``,
    Bloomberg in its ``dayRange`` pair. Finviz has no Open/High/Low row at all,
    so it is absent by capability rather than by omission.
    """
    fake_providers["bb"] = _bloomberg_quote()
    result = await tools_market.stock_quote("AAPL")
    rows = {r["field"]: r for r in result["comparisons"]}

    for field in ("day_high", "day_low"):
        row = rows[field]
        assert row["match"] is True
        assert set(row["values"]) == {
            "TRADINGVIEW",
            "YAHOO",
            "BLOOMBERG",
        }
        assert "FINVIZ" not in row["values"]
    assert rows["day_high"]["values"]["TRADINGVIEW"] == pytest.approx(338.0)
    assert rows["day_low"]["values"]["BLOOMBERG"] == pytest.approx(330.5)
    assert result["data"]["day_high"] == pytest.approx(338.0)
    assert result["data"]["day_low"] == pytest.approx(330.5)


@pytest.mark.asyncio
async def test_day_open_is_compared_only_where_both_sides_report_it(fake_providers):
    """Two providers publish the open; the other two have no field to compare."""
    result = await tools_market.stock_quote("AAPL")
    row = next(r for r in result["comparisons"] if r["field"] == "day_open")
    assert set(row["values"]) == {"TRADINGVIEW", "YAHOO"}
    assert row["match"] is True
    assert result["data"]["day_open"] == pytest.approx(337.1)


@pytest.mark.asyncio
async def test_yahoo_volume_joins_the_comparison(fake_providers):
    """Yahoo's volume was downloaded and dropped, so the field was 3-way at best."""
    fake_providers["bb"] = _bloomberg_quote()
    result = await tools_market.stock_quote("AAPL")
    row = next(r for r in result["comparisons"] if r["field"] == "volume")
    assert set(row["values"]) == {
        "TRADINGVIEW",
        "FINVIZ",
        "YAHOO",
        "BLOOMBERG",
    }
    assert row["values"]["YAHOO"] == 63160515
    assert row["match"] is True


@pytest.mark.asyncio
async def test_yahoo_volume_disagreement_is_reported(fake_providers):
    """Reading the fourth provider only counts if it can also contradict."""
    fake_providers["yh"]["volume"] = 1
    result = await tools_market.stock_quote("AAPL")
    row = next(r for r in result["comparisons"] if r["field"] == "volume")
    assert row["match"] is False
    assert any("volume" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_tradingview_states_its_own_feed_delay(fake_providers):
    """``update_mode`` says whether the scanner feed is live or delayed."""
    result = await tools_market.stock_quote("AAPL")
    assert result["data"]["feed_mode"] == "delayed_streaming_900"
    assert result["data"]["instrument_type"] == "stock"
    assert result["data"]["instrument_subtype"] == "common"
    # It rides along labelled with the provider that shaped it, not as ALL.
    assert result["fields"]["feed_mode"] == {
        "source": "TRADINGVIEW",
        "supplied": ["TRADINGVIEW"],
        "compared": [],
        "agreement": None,
    }


@pytest.mark.asyncio
async def test_finviz_identity_fields_survive_the_shaper(fake_providers):
    """website/logo_url/market_cap_class were parsed then dropped by the shaper."""
    fake_providers["fv"].update(
        {
            "website": "http://www.apple.com",
            "logo_url": "https://logo.finviz.com/AAPL.svg",
            "market_cap_class": "Mega",
            "etf_type": None,
        }
    )
    result = await tools_market.stock_quote("AAPL")
    assert result["data"]["website"] == "http://www.apple.com"
    assert result["data"]["logo_url"] == "https://logo.finviz.com/AAPL.svg"
    assert result["data"]["market_cap_class"] == "Mega"


@pytest.mark.asyncio
async def test_quote_carries_the_income_breakdown_finviz_already_downloaded(
    fake_providers,
):
    """The breakdown island is on the same page the quote fetched."""
    fake_providers["fv"]["income_breakdown"] = {
        "statement": {
            "currency": "USD",
            "scale_applied": 1_000_000.0,
            "periods": ["2026FY"],
            "rows": [{"label": "Total Revenue", "values": [478_834_000_000.0]}],
        },
        "revenue": {"years": ["2026"], "axes": {}},
    }
    result = await tools_market.stock_quote("AAPL")
    breakdown = result["data"]["income_breakdown"]
    assert breakdown["statement"]["scale_applied"] == 1_000_000.0
    assert result["fields"]["income_breakdown"] == {
        "source": "FINVIZ",
        "supplied": ["FINVIZ"],
        "compared": [],
        "agreement": None,
    }


# ── coverage and the supplied/compared split ────────────────────────────────


@pytest.mark.asyncio
async def test_a_leg_that_was_asked_and_errored_is_partial_not_all(fake_providers):
    """The measured bug: ``ALL`` served beside a provider error.

    A live response reported ``data_provider: ALL`` while listing a Yahoo error
    and only three answers. Coverage is a claim about the providers that were
    asked, and Yahoo was one of them, so the honest label is ``PARTIAL``.
    """
    fake_providers["yh"] = RuntimeError("yahoo outage")
    result = await tools_market.stock_quote("AAPL")

    assert result["data_provider"] == "PARTIAL"
    assert result["verification"] == "MULTI_SOURCE"
    assert result["providers_answered"] == ["TRADINGVIEW", "FINVIZ"]
    # The failure is still explained rather than hidden behind the label.
    assert [e["provider"] for e in result["errors"]] == ["YAHOO", "SA", "BLOOMBERG"]
    assert "PARTIAL" in result["notice"]


@pytest.mark.asyncio
async def test_an_unasked_leg_does_not_turn_coverage_partial(fake_providers, monkeypatch):
    """``NOT_ATTEMPTED`` means the provider was never asked, so ALL still holds.

    This is the difference the ask set exists for: a provider with no endpoint
    for the request, or one that does not carry the instrument, must not be
    counted as a failure that downgrades the response. These resolutions are
    uncarried, unlike the shared fixture's asked-but-empty legs.
    """
    monkeypatch.setattr(tools_market, "resolve_sa", lambda query, **kwargs: _resolved("SA", None))
    monkeypatch.setattr(tools_market, "_bloomberg_resolution", lambda symbol: _resolved("BLOOMBERG", None))
    result = await tools_market.stock_quote("AAPL")

    assert result["data_provider"] == "ALL"
    assert result["providers_answered"] == ["TRADINGVIEW", "FINVIZ", "YAHOO"]
    assert "BLOOMBERG" not in result["providers_answered"]
    # Nothing was reported as a failed leg, because none was asked and failed.
    assert [e for e in result["errors"] if e["code"] != "NOT_ATTEMPTED"] == []


@pytest.mark.asyncio
async def test_compared_is_narrower_than_supplied_when_pairs_were_not_judged():
    """``supplied`` names who answered; ``compared`` only who was judged.

    Two prints a session apart are two observations, so the pair reached no
    verdict. Reading ``agreement`` as "every provider agreed" is the mistake the
    split exists to stop, so the field must say every supplier and fewer
    comparands.
    """
    from tapebasis.reconcile import (
        FINVIZ,
        TRADINGVIEW,
        YAHOO,
        compare_values,
        compared_providers,
    )

    row = compare_values(
        {TRADINGVIEW: 10.0, FINVIZ: 10.0, YAHOO: 10.0},
        times={
            TRADINGVIEW: "2026-11-03T20:00:00+00:00",
            FINVIZ: "2026-11-03T20:00:00+00:00",
            YAHOO: "2026-11-04T20:00:00+00:00",
        },
        session_boundary=True,
    )
    assert row["match"] is True
    compared = compared_providers(row)
    assert compared == [TRADINGVIEW, FINVIZ]
    assert YAHOO in row["values"]


@pytest.mark.asyncio
async def test_the_two_quote_tools_reach_the_same_verdict(fake_providers, monkeypatch):
    """One symbol, one answer: an undatable print is not a disagreement.

    Finviz's screener row carries no print time (its quote page does), so the
    session guard used to never fire for that leg and the two tools reported
    different verdicts on the same three readings: ``stock_quote`` said "not
    comparable", ``stock_prices`` said ``agrees: false``.
    """
    from tapebasis import fv_access, tv_access, yh_access

    async def tv_quotes(symbols):
        return {
            "AAPL": {
                "ticker": "NASDAQ:AAPL",
                "close": 348.51,
                "change": -0.62,
                "volume": 29756060,
                "update_time": "2026-11-10T21:00:00+00:00",
            }
        }

    async def fv_rows(symbols):
        # No ``last_update``: the screener endpoint omits it, and that omission
        # is the whole point of the test. The price is also a session stale,
        # which is exactly what an undatable reading looks like.
        return [{"ticker": "AAPL", "price": 346.82, "change": -0.62, "prevClose": 349.0}]

    async def yh_quote(symbol):
        return {
            "price": 348.51,
            "change_pct": -0.62,
            "previous_close": 350.69,
            "market_time": "2026-11-10T21:00:00+00:00",
            "shortName": "Apple Inc.",
        }

    monkeypatch.setattr(tv_access, "quotes", tv_quotes)
    monkeypatch.setattr(fv_access, "screener_rows", fv_rows)
    monkeypatch.setattr(yh_access, "quote", yh_quote)

    prices = (await tools_market.stock_prices("AAPL"))["data"][0]
    quote = await tools_market.stock_quote("AAPL")

    prices_match = prices["comparisons"]["price"]["match"]
    quote_match = next(
        row["match"] for row in quote["comparisons"] if row["field"] == "price"
    )

    # Neither tool may call this a conflict, and both must reach that conclusion
    # from the same readings: a print with no timestamp cannot be shown to be
    # the same observation as one with a timestamp, so the Finviz pair is not
    # judged while the two dated readings still corroborate each other.
    assert prices_match is not False
    assert quote_match is not False
    assert prices_match is quote_match
    assert prices["agrees"] is True
    # The undated leg still appears in ``supplied``: it answered, it just could
    # not be judged, which is a different fact from silence.
    assert "FINVIZ" in prices["fields"]["price"]["supplied"]


@pytest.mark.asyncio
async def test_prices_keep_provider_wide_empty_batch_as_no_data(
    fake_providers, monkeypatch
):
    """An attempted provider with no rows is NO_DATA, never NOT_ATTEMPTED."""
    from tapebasis import fv_access, tv_access, yh_access
    from tapebasis.providers_state import NoDataError

    async def empty_tv(symbols):
        return {}

    async def empty_yahoo(symbol):
        raise NoDataError("YAHOO", f"{symbol} has no quote")

    async def empty_finviz(symbols, **kwargs):
        raise NoDataError("FINVIZ", "Finviz returned no rows")

    monkeypatch.setattr(fv_access, "screener_rows", empty_finviz)
    fake_providers["sa"] = NoDataError("SA", "StockAnalysis returned no rows")
    fake_providers["bb"] = NoDataError("BLOOMBERG", "Bloomberg returned no rows")
    monkeypatch.setattr(tv_access, "quotes", empty_tv)
    monkeypatch.setattr(yh_access, "quote", empty_yahoo)

    result = await tools_market.stock_prices("AAPL")
    row = result["data"][0]

    assert result["data_provider"] == "NONE"
    assert row["data_provider"] == "NONE"
    assert set(row["misses"]) == {
        "TRADINGVIEW", "FINVIZ", "YAHOO", "SA", "BLOOMBERG"
    }
    row_errors = {(error["provider"], error["symbol"]): error for error in row["errors"]}
    envelope_errors = {
        (error["provider"], error["symbol"]): error for error in result["errors"]
    }
    for provider in ("TRADINGVIEW", "FINVIZ", "YAHOO", "SA", "BLOOMBERG"):
        error = row_errors[(provider, "AAPL")]
        assert error["code"] == "NO_DATA"
        assert envelope_errors[(provider, "AAPL")] == error
    assert row_errors[("YAHOO", "AAPL")]["message"] == "AAPL has no quote"


@pytest.mark.asyncio
async def test_batch_coverage_and_notices_follow_each_symbol(
    fake_providers, monkeypatch
):
    """A miss on symbol X cannot split complete coverage for symbol Y."""
    from tapebasis import fv_access, tv_access, yh_access

    async def resolve(query, provider, **kwargs):
        symbols = {
            "TRADINGVIEW": f"NASDAQ:{query}",
            "FINVIZ": query,
            "YAHOO": query,
        }
        return _resolved(provider, symbols.get(provider), query=query)

    async def tv_rows(symbols):
        return {"AAPL": {
            "close": 100, "change": 1,
            "update_time": "2026-11-03T21:00:00+00:00",
        }}

    async def fv_rows(symbols):
        return [{"ticker": "AAPL", "price": 100, "change": 1,
                 "last_update": "2026-11-03T21:00:00+00:00"}]

    async def yh_quote(symbol):
        if symbol == "MSFT":
            return {"price": None, "change_pct": None, "market_time": None}
        return {"price": 100, "change_pct": 1,
                "market_time": "2026-11-03T21:00:00+00:00"}

    monkeypatch.setattr(tools_market, "resolve", resolve)
    monkeypatch.setattr(tools_market, "resolve_sa", lambda query, **kwargs: _resolved("SA", None))
    monkeypatch.setattr(tools_market, "_bloomberg_resolution", lambda query: _resolved("BLOOMBERG", None))
    monkeypatch.setattr(tv_access, "quotes", tv_rows)
    monkeypatch.setattr(fv_access, "screener_rows", fv_rows)
    monkeypatch.setattr(yh_access, "quote", yh_quote)

    result = await tools_market.stock_prices("AAPL,MSFT")
    apple, microsoft = result["data"]

    assert apple["asked"] == ["TRADINGVIEW", "FINVIZ", "YAHOO"]
    assert apple["data_provider"] == "ALL"
    assert apple["agrees"] is True
    assert result["data_provider"] == "PARTIAL"
    assert {error["symbol"] for error in result["errors"]} == {"MSFT"}
    assert all(comparison["symbol"] for comparison in result["comparisons"])
    assert "Compared fields agree within tolerance" in result["notice"]

    async def undated_tv(symbols):
        return {"AAPL": {"close": 100.0, "change": 1.0}}

    async def undated_yahoo(symbol):
        return {"price": 100.0, "change_pct": 1.0}

    monkeypatch.setattr(tools_market, "resolve_sa", lambda query, **kwargs: _resolved("SA", None))
    monkeypatch.setattr(tools_market, "_bloomberg_resolution", lambda query: _resolved("BLOOMBERG", None))
    monkeypatch.setattr(tv_access, "quotes", undated_tv)
    monkeypatch.setattr(yh_access, "quote", undated_yahoo)
    result = await tools_market.stock_prices("AAPL")
    row = result["data"][0]

    assert row["agrees"] is None
    assert "Compared fields agree within tolerance" not in result["notice"]
    assert result["notice"].count("Not cross-checked") == 1
    assert "AAPL.price" in result["notice"]
    assert "AAPL.change_percent" in result["notice"]


async def test_batch_budget_cutoff_is_not_an_attempted_failure(
    fake_providers, monkeypatch
):
    """A cutoff before the request leaves Bloomberg out of that row's ask set."""
    budget_clock = iter([0.0, 0.0, tools_market.BLOOMBERG_BATCH_BUDGET_SECONDS + 1.0])

    async def tv_rows(symbols):
        return {"AAPL": {
            "close": 100.0, "change": 1.0,
            "update_time": "2026-11-03T21:00:00+00:00",
        }}

    async def fv_rows(symbols):
        return [{"ticker": "AAPL", "price": 100.0, "change": 1.0,
                 "last_update": "2026-11-03T21:00:00+00:00"}]

    # This module owns the batch budget clock. Patching the shared ``time``
    # module also patches pytest's timing and fixture teardown.
    def monotonic() -> float:
        """Advance the batch clock, delegating framework timing to the real clock."""
        return next(budget_clock, time.monotonic())

    monkeypatch.setattr(tools_market, "time", SimpleNamespace(monotonic=monotonic))
    monkeypatch.setattr(tools_market, "resolve_sa", lambda query, **kwargs: _resolved("SA", None))
    monkeypatch.setattr(
        tools_market, "_bloomberg_resolution",
        lambda query: _resolved("BLOOMBERG", f"{query}:US", query=query),
    )

    async def resolve(query, provider, **kwargs):
        """Leave MSFT to the Bloomberg cutoff rather than another provider."""
        symbols = {
            "TRADINGVIEW": "NASDAQ:AAPL",
            "FINVIZ": "AAPL",
            "YAHOO": "AAPL",
        }
        return _resolved(
            provider, symbols.get(provider) if query == "AAPL" else None, query=query,
        )

    monkeypatch.setattr(tools_market, "resolve", resolve)
    from tapebasis import tv_access

    monkeypatch.setattr(tv_access, "quotes", tv_rows)
    from tapebasis import fv_access

    monkeypatch.setattr(fv_access, "screener_rows", fv_rows)
    result = await tools_market.stock_prices("AAPL,MSFT")
    apple, microsoft = result["data"]

    assert apple["data_provider"] == "PARTIAL"
    assert {error["provider"] for error in apple["errors"]} == {"BLOOMBERG"}
    assert "BLOOMBERG" not in microsoft["asked"]
    assert microsoft["asked"] == []
    assert microsoft["data_provider"] == "NONE"
    assert not microsoft["errors"]
    assert "not asked" in microsoft["misses"]["BLOOMBERG"]
    assert any("MSFT" in warning and "budget" in warning for warning in result["warnings"])
    assert {error["symbol"] for error in result["errors"]} == {"AAPL"}


@pytest.mark.asyncio
async def test_session_precedence_and_notice_override_are_explicit():
    """An adapter exposes batch verdicts only once, named by symbol."""
    from tapebasis.providers_state import DataProvider
    from tapebasis.reconcile import Attempt, Pair, finalize

    pair = Pair(attempts={
        "AA": Attempt("AA", True, value={}),
        "BB": Attempt("BB", True, value={}),
    })
    row = {"match": None, "not_comparable": True}
    result = finalize(
        pair,
        provider=DataProvider.ALL,
        answered=["AA", "BB"],
        data=[{"symbol": "AA"}, {"symbol": "BB"}],
        comparisons=[
            {"symbol": "AA", "field": "price", **row},
            {"symbol": "AA", "field": "change_percent", **row},
            {"symbol": "BB", "field": "price", **row},
        ],
    )

    assert result["notice"].count("Not cross-checked") == 1
    assert result["notice"].split(": ")[-1] == (
        "AA.price, AA.change_percent, BB.price."
    )
    assert "Compared fields agree within tolerance" not in result["notice"]


@pytest.mark.asyncio
async def test_screener_applies_finviz_filters_to_the_selected_tickers(monkeypatch):
    """Finviz filters narrow the shared universe instead of being ignored."""
    from tapebasis import fv_access, tv_access
    from tapebasis.symbols import Resolution

    calls = {}

    async def tv_screen(**kwargs):
        return {
            "rows": [
                {"symbol": "NASDAQ:MSFT", "description": "Microsoft", "price": 500.0},
                {"symbol": "NASDAQ:AAPL", "description": "Apple", "price": 300.0},
            ],
            "as_of": "2026-11-03T21:00:00+00:00",
        }

    async def fv_rows(tickers, **kwargs):
        calls["tickers"] = tickers
        calls.update(kwargs)
        return [{"ticker": "AAPL", "price": 300.0}]

    async def fake_resolve(query, provider, **kwargs):
        return Resolution(
            query=query,
            provider=provider,
            symbol=None,
            note=f"{provider} is not asked by this fixture",
        )

    monkeypatch.setattr(tv_access, "stock_screen", tv_screen)
    monkeypatch.setattr(fv_access, "screener_rows", fv_rows)
    monkeypatch.setattr(tools_market, "resolve", fake_resolve)

    result = await tools_market.stock_screener(
        finviz_filters="cap_largeover,sec_technology"
    )

    assert calls == {
        "tickers": ["MSFT", "AAPL"],
        "filters": "cap_largeover,sec_technology",
    }
    assert len(result["data"]["rows"]) == 2


@pytest.mark.asyncio
async def test_earnings_does_not_promote_finviz_last_report_to_next(
    fake_providers, monkeypatch
):
    """A historical Finviz report cannot masquerade as the next release."""
    from tapebasis import fv_access, tv_access, yh_access

    async def tv_earnings(symbol):
        return {
            "earnings_release_next_date": None,
            "earnings_release_date": 1793655000,
        }

    async def fv_earnings(symbol):
        return {"earnings_date": "2026-11-03T20:00:00+00:00"}

    async def yahoo_quote(symbol):
        return {}

    monkeypatch.setattr(tv_access, "earnings", tv_earnings)
    monkeypatch.setattr(fv_access, "earnings", fv_earnings)
    monkeypatch.setattr(yh_access, "quote", yahoo_quote)

    result = await tools_market.stock_earnings("AAPL")

    assert result["data"]["next_earnings_date"] is None
    assert result["data"]["finviz_earnings_date"] == "2026-11-03T20:00:00+00:00"
    assert result["data"]["tradingview_next_earnings"] is None
    assert result["data"]["yahoo_next_earnings"] is None
    assert "last *reported*" in result["data"]["finviz_note"]


@pytest.mark.asyncio
async def test_technical_analysis_uses_the_resolved_tradingview_identity(
    fake_providers, monkeypatch
):
    """The exchange argument cannot send a resolved ticker to another venue."""
    from tapebasis import tv_access
    from tapebasis.symbols import Resolution

    calls = {}

    async def analysis(symbol, exchange="NASDAQ", timeframe="1D"):
        calls.update(symbol=symbol, exchange=exchange, timeframe=timeframe)
        return {"price_data": {"current_price": 500.0}}

    async def fake_resolve(query, provider, **kwargs):
        symbols = {
            "TRADINGVIEW": "NYSE:XYZ",
            "FINVIZ": "XYZ",
            "YAHOO": "XYZ",
        }
        return Resolution(
            query=query,
            provider=provider,
            symbol=symbols[provider],
            venue="NYSE" if provider == "TRADINGVIEW" else "",
        )

    monkeypatch.setattr(tv_access, "technical_analysis", analysis)
    monkeypatch.setattr(tools_market, "resolve", fake_resolve)

    await tools_market.technical_analysis("XYZ", exchange="NASDAQ")

    assert calls == {"symbol": "NYSE:XYZ", "exchange": "NYSE", "timeframe": "1D"}


# ── options chains ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_options_chain_marks_different_nearest_expiries_not_comparable(monkeypatch):
    """Different expiry dates never agree, while a shared date compares normally."""
    from tapebasis import fv_access, tv_access, yh_access

    yahoo_payload = {
        "requested_expiry": "2026-12-18",
        "available_expiries": ["2026-12-18", "2027-01-15"],
        "underlying_price": 100,
        "calls": [
            {
                "strike": 100,
                "expiration": "2026-12-18",
                "volume": 0,
                "open_interest": 0,
            }
        ],
        "puts": [],
        "call_count": 1,
        "put_count": 0,
    }

    async def fake_resolve(query, provider, **kwargs):
        symbol = {"TRADINGVIEW": "NASDAQ:AAPL", "FINVIZ": "AAPL", "YAHOO": "AAPL"}[provider]
        return _resolved(provider, symbol, query=query)

    async def tv_quote(symbol):
        return {"close": 100}

    async def fv_options(symbol, expiry):
        return {
            "expiry": "2026-11-20",
            "expiries": ["2026-11-20", "2026-12-18"],
            "last_close": 100,
            "contracts": [
                {
                    "type": "call",
                    "strike": 100,
                    "expiry": "2026-11-20",
                    "lastVolume": 0,
                    "openInterest": 0,
                }
            ],
            "count": 1,
        }

    async def yh_options(symbol, expiry):
        assert expiry is None
        return yahoo_payload

    monkeypatch.setattr(tools_market, "resolve", fake_resolve)
    monkeypatch.setattr(tv_access, "quote", tv_quote)
    monkeypatch.setattr(fv_access, "options", fv_options)
    monkeypatch.setattr(yh_access, "options", yh_options)

    result = await tools_market.stock_options_chain("AAPL")
    overlap = result["data"]["overlap"]
    assert overlap["not_comparable"] is True
    assert "2026-11-20" in overlap["reason"]
    assert "2026-12-18" in overlap["reason"]
    assert result["data"]["expiry"] is None
    assert result["data"]["expiries"] == {
        "FINVIZ": ["2026-11-20", "2026-12-18"],
        "YAHOO": ["2026-12-18", "2027-01-15"],
    }

    yahoo_payload["requested_expiry"] = "2026-11-20"
    yahoo_payload["calls"][0]["expiration"] = "2026-11-20"

    async def yh_same_options(symbol, expiry):
        assert expiry == "2026-11-20"
        return yahoo_payload

    monkeypatch.setattr(yh_access, "options", yh_same_options)
    same = await tools_market.stock_options_chain("AAPL", expiry="2026-11-20")
    assert same["data"]["expiry"] == "2026-11-20"
    assert same["data"]["overlap"]["calls"]["matched_contracts"] == 1
    assert same["data"]["overlap"]["calls"]["volume_agreeing"] == 1
