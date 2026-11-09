"""Tests for the reconciliation engine (no network)."""
from __future__ import annotations

import pytest

from tapebasis.providers_state import (
    DataProvider,
    Verification,
    envelope,
    provider_from_answered,
)
from tapebasis.reconcile import (
    DEFAULT_ORDER,
    FINVIZ,
    TRADINGVIEW,
    YAHOO,
    Attempt,
    FieldSpec,
    Pair,
    ask,
    compare_numeric,
    compare_symbol,
    compare_values,
    finalize,
    merge,
    merge_many,
    single,
)


def _ok(provider, value):
    return Attempt(provider, True, value=value)


def _fail(provider, message="boom"):
    return Attempt(
        provider,
        False,
        error={"provider": provider, "code": "PROVIDER_ERROR", "message": message},
    )


# ── provider state ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "answered,expected",
    [
        ((), DataProvider.NONE),
        (("TRADINGVIEW",), DataProvider.TRADINGVIEW),
        (("FINVIZ",), DataProvider.FINVIZ),
        (("YAHOO",), DataProvider.YAHOO),
        (("TRADINGVIEW", "FINVIZ"), DataProvider.ALL),
        (("TRADINGVIEW", "YAHOO"), DataProvider.ALL),
        (("FINVIZ", "YAHOO"), DataProvider.ALL),
        (("TRADINGVIEW", "FINVIZ", "YAHOO"), DataProvider.ALL),
    ],
)
def test_provider_from_answered(answered, expected):
    assert provider_from_answered(answered) is expected


def test_all_means_coverage_not_agreement():
    """A subset answering is still ALL; it says nothing about agreement."""
    assert provider_from_answered(["FINVIZ", "YAHOO"]) is DataProvider.ALL
    assert provider_from_answered(["FINVIZ"]) is DataProvider.FINVIZ


def test_envelope_notice_is_explicit_for_single_source():
    body = envelope({"price": 1}, provider=DataProvider.TRADINGVIEW)
    assert body["data_provider"] == "TRADINGVIEW"
    assert body["verification"] == Verification.SINGLE_SOURCE.value
    assert "single-source" in body["notice"].lower()


def test_envelope_all_does_not_claim_verification():
    body = envelope({"price": 1}, provider=DataProvider.ALL, providers_answered=["FINVIZ", "YAHOO"])
    assert body["verification"] == Verification.MULTI_SOURCE.value
    assert "agreement is a separate axis" in body["notice"].lower()
    assert body["providers_answered"] == ["FINVIZ", "YAHOO"]


def test_envelope_none_says_do_not_present():
    body = envelope(None, provider=DataProvider.NONE)
    assert body["verification"] == Verification.UNAVAILABLE.value
    assert "Do not present" in body["notice"]


# ── comparison ──────────────────────────────────────────────────────────────


def test_compare_numeric_within_tolerance():
    row = compare_numeric(331.90, 331.89, tolerance_pct=0.5)
    assert row["match"] is True
    assert row["diff_pct"] < 0.5


def test_compare_numeric_outside_tolerance():
    row = compare_numeric(100.0, 110.0, tolerance_pct=0.5)
    assert row["match"] is False


def test_compare_numeric_coerces_annotated_strings():
    # Finviz cells like "351.73 -5.64%" must still parse.
    row = compare_numeric(351.73, "351.73 -5.64%", tolerance_pct=0.5)
    assert row["fv"] == "351.73 -5.64%"
    assert row["match"] is True


def test_compare_numeric_non_numeric_is_unknown():
    row = compare_numeric("n/a", 1.0)
    assert row["match"] is None


def test_compare_numeric_absolute_floor_protects_small_values():
    # A 0.01 vs 0.02 difference is 50% relative but trivial in absolute terms.
    strict = compare_numeric(0.01, 0.02, tolerance_pct=5.0)
    floored = compare_numeric(0.01, 0.02, tolerance_pct=5.0, absolute_floor=0.5)
    assert strict["match"] is False
    assert floored["match"] is True


def test_compare_symbol_normalises_case():
    assert compare_symbol("NASDAQ:AAPL", "aapl")["match"] is False
    assert compare_symbol("AAPL", "aapl")["match"] is True


def test_compare_values_is_pairwise_across_three_providers():
    row = compare_values(
        {TRADINGVIEW: 100.0, FINVIZ: 100.1, YAHOO: 100.2}, tolerance_pct=0.5
    )
    assert row["match"] is True
    assert {tuple(p["between"]) for p in row["pairs"]} == {
        (TRADINGVIEW, FINVIZ),
        (TRADINGVIEW, YAHOO),
        (FINVIZ, YAHOO),
    }
    assert row["values"] == {TRADINGVIEW: 100.0, FINVIZ: 100.1, YAHOO: 100.2}


def test_compare_values_flags_any_disagreeing_pair():
    row = compare_values({TRADINGVIEW: 100.0, FINVIZ: 100.1, YAHOO: 150.0})
    assert row["match"] is False
    disagreeing = [p for p in row["pairs"] if p["match"] is False]
    assert len(disagreeing) == 2  # YAHOO against each of the other two


def test_compare_values_single_reading_is_unknown():
    row = compare_values({TRADINGVIEW: 100.0, FINVIZ: None})
    assert row["match"] is None
    assert row["values"] == {TRADINGVIEW: 100.0}


# ── merge ───────────────────────────────────────────────────────────────────


def test_merge_reports_agreement_and_mismatch():
    specs = (
        FieldSpec("price", lambda p: p["price"], lambda p: p["price"]),
        FieldSpec("rsi", lambda p: p["rsi"], lambda p: p["rsi"]),
    )
    merged = merge({"price": 10.0, "rsi": 50.0}, {"price": 10.05, "rsi": 70.0}, specs)
    assert merged.provider is DataProvider.ALL
    assert merged.mismatches == ["rsi"]
    # No timestamps on either side, so the documented Finviz default applies.
    assert merged.data["price"] == 10.05
    assert {c["field"]: c["match"] for c in merged.comparisons} == {
        "price": True,
        "rsi": False,
    }


def test_merge_three_providers_resolves_to_freshest_print():
    specs = (
        FieldSpec(
            "price",
            lambda p: p["price"],
            lambda p: p["price"],
            yh_get=lambda p: p["price"],
        ),
    )
    merged = merge_many(
        {
            TRADINGVIEW: {"price": 10.0},
            FINVIZ: {"price": 10.1},
            YAHOO: {"price": 10.2},
        },
        specs,
        times={
            TRADINGVIEW: "2026-11-03T20:00:00+00:00",
            FINVIZ: "2026-11-03T20:30:00+00:00",
            YAHOO: "2026-11-03T21:00:00+00:00",
        },
    )
    assert merged.provider is DataProvider.ALL
    assert merged.chosen == YAHOO
    assert merged.data["price"] == 10.2
    assert merged.fields["price"] is DataProvider.ALL


def test_default_order_is_documented_and_stable():
    # Bloomberg is last: a delayed page must never outrank a live feed on a tie.
    # StockAnalysis sits just before it: a live feed, but the narrowest cover.
    assert DEFAULT_ORDER == (FINVIZ, TRADINGVIEW, YAHOO, "SA", "BLOOMBERG")
    merged = merge_many(
        {FINVIZ: {"price": 10.1}, TRADINGVIEW: {"price": 10.0}, YAHOO: {"price": 10.2}},
        (FieldSpec("price", lambda p: p["price"], lambda p: p["price"]),),
    )
    assert merged.chosen == FINVIZ
    assert merged.data["price"] == 10.1


def test_merge_falls_back_to_single_provider():
    specs = (FieldSpec("price", lambda p: p["price"], lambda p: p["price"]),)
    merged = merge(None, {"price": 10.0}, specs)
    assert merged.provider is DataProvider.FINVIZ
    assert merged.data == {"price": 10.0}
    assert merged.fields["price"] is DataProvider.FINVIZ


def test_merge_none_when_all_empty():
    merged = merge(None, None, ())
    assert merged.provider is DataProvider.NONE


def test_merge_keeps_fields_only_one_side_offers():
    merged = merge(
        {"price": 10.0, "tv_only": "x"},
        {"price": 10.0, "fv_only": "y"},
        (FieldSpec("price", lambda p: p["price"], lambda p: p["price"]),),
        tv_shape=lambda p: {"tv_only": p["tv_only"]},
        fv_shape=lambda p: {"fv_only": p["fv_only"]},
    )
    assert merged.data["tv_only"] == "x"
    assert merged.data["fv_only"] == "y"
    assert merged.fields["tv_only"] is DataProvider.TRADINGVIEW
    assert merged.fields["fv_only"] is DataProvider.FINVIZ


def test_merge_carries_yahoo_only_fields():
    merged = merge_many(
        {TRADINGVIEW: {"price": 10.0}, FINVIZ: {"price": 10.0}, YAHOO: {"price": 10.0, "yh_only": "z"}},
        (FieldSpec("price", lambda p: p["price"], lambda p: p["price"]),),
        shapes={YAHOO: lambda p: {"yh_only": p["yh_only"]}},
    )
    assert merged.data["yh_only"] == "z"
    assert merged.fields["yh_only"] is DataProvider.YAHOO


def test_uncontested_field_comes_from_the_freshest_provider():
    """``setdefault`` makes the first writer win, so the order has to be newest first.

    This iterated ``reversed(order)`` while claiming the opposite, which let the
    stalest provider fill every field the spec list did not compare. Live, that
    served a 4-day-old TradingView sector over a fresh Finviz one.
    """
    merged = merge_many(
        {
            TRADINGVIEW: {"price": 10.0, "sector": "stale-sector"},
            FINVIZ: {"price": 10.0, "sector": "fresh-sector"},
        },
        (FieldSpec("price", lambda p: p["price"], lambda p: p["price"]),),
        shapes={
            TRADINGVIEW: lambda p: {"sector": p["sector"]},
            FINVIZ: lambda p: {"sector": p["sector"]},
        },
        times={
            TRADINGVIEW: "2026-11-03T20:00:00+00:00",
            FINVIZ: "2026-11-03T21:00:00+00:00",
        },
    )
    assert merged.chosen == FINVIZ
    assert merged.data["sector"] == "fresh-sector"
    assert merged.fields["sector"] is DataProvider.FINVIZ


def test_uncontested_field_falls_back_to_the_documented_order_on_a_tie():
    """With no print-time difference, DEFAULT_ORDER decides, not iteration order."""
    merged = merge_many(
        {TRADINGVIEW: {"price": 10.0, "sector": "tv"}, FINVIZ: {"price": 10.0, "sector": "fv"}},
        (FieldSpec("price", lambda p: p["price"], lambda p: p["price"]),),
        shapes={
            TRADINGVIEW: lambda p: {"sector": p["sector"]},
            FINVIZ: lambda p: {"sector": p["sector"]},
        },
    )
    assert merged.chosen == FINVIZ
    assert merged.data["sector"] == "fv"


# ── pair semantics ──────────────────────────────────────────────────────────


def test_not_attempted_is_not_reported_as_an_error():
    pair = single(FINVIZ, {"a": 1})
    assert pair.provider is DataProvider.FINVIZ
    # Finviz-only capability: the other two were never attempted -> no error noise.
    assert pair.errors == []
    assert pair.tv.error["code"] == "NOT_ATTEMPTED"
    assert pair.yh.error["code"] == "NOT_ATTEMPTED"


def test_single_tradingview_marks_others_not_attempted():
    pair = single(TRADINGVIEW, {"a": 1})
    assert pair.provider is DataProvider.TRADINGVIEW
    assert pair.fv.error["code"] == "NOT_ATTEMPTED"
    assert pair.yh.error["code"] == "NOT_ATTEMPTED"


@pytest.mark.asyncio
async def test_ask_runs_all_and_survives_one_failure():
    async def good():
        return {"v": 1}

    async def bad():
        raise RuntimeError("nope")

    pair = await ask(good, bad, good)
    assert pair.tv.ok and not pair.fv.ok and pair.yh.ok
    assert pair.provider is DataProvider.ALL
    assert pair.errors[0]["provider"] == FINVIZ


@pytest.mark.asyncio
async def test_ask_with_missing_provider_is_not_an_error():
    async def good():
        return {"v": 1}

    pair = await ask(good, None)
    assert pair.provider is DataProvider.TRADINGVIEW
    assert pair.errors == []
    assert pair.yh.error["code"] == "NOT_ATTEMPTED"


@pytest.mark.asyncio
async def test_ask_reports_not_applicable_without_an_error():
    from tapebasis.providers_state import NotApplicable

    async def good():
        return {"v": 1}

    async def not_carried():
        raise NotApplicable(FINVIZ, "Finviz does not carry spot gold")

    pair = await ask(good, not_carried, good)
    assert pair.provider is DataProvider.ALL
    assert pair.errors == []
    assert pair.fv.error["code"] == "NOT_ATTEMPTED"


def test_finalize_override_data_and_provider():
    pair = Pair(
        attempts={
            TRADINGVIEW: _ok(TRADINGVIEW, {"a": 1}),
            FINVIZ: _ok(FINVIZ, {"a": 1}),
        }
    )
    body = finalize(pair, data={"custom": True}, provider=DataProvider.ALL)
    assert body["data"] == {"custom": True}
    assert body["data_provider"] == "ALL"
