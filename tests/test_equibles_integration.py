"""Hermetic tests for optional Equibles participation in shared tools.

Two properties matter more than the payload details.

Without ``TAPEBASIS_EQUIBLES_API_KEY`` an adapter is never called, so no request, no
provider scope and no coverage change can appear. With a key, only an observation
whose meaning, period, unit and basis provably match enters a comparison. A
same-named number describing another period or another population is declined,
not reported as agreement or as a conflict.

No live Equibles access is exercised here: the adapter's transport is faked, and
the global test fixture additionally refuses any real request.
"""
from __future__ import annotations

import pytest

from tapebasis import equibles_reconcile, tools_finviz, tools_market
from tapebasis.symbols import Resolution


def _resolution(symbol: str = "AAPL") -> dict:
    """Resolve every market leg locally so no symbol search is requested."""
    return {
        "query": symbol,
        "ticker": symbol,
        "TRADINGVIEW": Resolution(
            query=symbol, provider="TRADINGVIEW", symbol=f"NASDAQ:{symbol}"
        ),
        "FINVIZ": Resolution(query=symbol, provider="FINVIZ", symbol=symbol),
        "YAHOO": Resolution(query=symbol, provider="YAHOO", symbol=symbol),
        "SA": Resolution(query=symbol, provider="SA", symbol=symbol.lower()),
        "BLOOMBERG": Resolution(query=symbol, provider="BLOOMBERG", symbol=symbol),
        "resolutions": {},
    }


@pytest.fixture
def earnings_legs(monkeypatch):
    """Fake the three ordinary earnings legs and freeze symbol resolution."""
    from tapebasis import fv_access, tv_access, yh_access

    async def fake_symbols(symbol):
        return _resolution(symbol)

    async def tv_earnings(_symbol):
        return {"earnings_release_next_date": 1793664000, "earnings_release_date": None}

    async def yahoo_quote(_symbol):
        return {"earnings_timestamp": None}

    monkeypatch.setattr(tools_market, "_symbols_for", fake_symbols)
    monkeypatch.setattr(tv_access, "earnings", tv_earnings)
    monkeypatch.setattr(yh_access, "quote", yahoo_quote)
    return fv_access


def _fv_earnings_row(**extra):
    """A Finviz quarterly estimate row with only the fields Finviz publishes."""
    return {
        "epsActual": 1.52,
        "epsEstimate": 1.45,
        "fiscalPeriod": "2026Q3",
        **extra,
    }


def _eq_payload(*rows):
    """Build the adapter payload, deriving counts exactly as the fetch does."""
    observations = equibles_reconcile.analyst_observations({"data": list(rows)})
    return {
        "observations": observations,
        "eps_estimate_analyst_counts": equibles_reconcile.analyst_counts(observations),
    }


def _eq_estimate(**extra):
    """An Equibles EPS estimate observation with explicit source metadata."""
    return {
        "metric": "EPS",
        "period": "2026Q3",
        "statistic": "mean",
        "unit": "USD",
        "basis": "diluted",
        "dimensions": ["consensus"],
        "value": 1.45,
        "dimAnalystCount": 12,
        "analyst": "52 analysts",
        "capturedAt": "2026-11-01T00:00:00Z",
        **extra,
    }


@pytest.fixture(autouse=True)
def _keyless(monkeypatch):
    """Keep Equibles unconfigured unless a test opts in explicitly."""
    monkeypatch.delenv("TAPEBASIS_EQUIBLES_API_KEY", raising=False)
    monkeypatch.delenv("TAPEBASIS_EQUIBLES_ENTITLEMENT", raising=False)


def test_estimates_reject_an_unproven_context():
    """The raw Finviz row has no unit or basis, so no consensus is invented."""
    reconciled = equibles_reconcile.compare_earnings(
        {"quarterly": [_fv_earnings_row()]},
        _eq_payload(_eq_estimate()),
    )
    assert reconciled["data"] == {}
    assert reconciled["fields"] == {}
    assert reconciled["comparisons"] == []
    assert reconciled["declined_comparisons"] == [
        {
            "field": "eps_estimate_2026Q3",
            "reason": (
                "Finviz supplies no explicit EPS statistic, unit, basis "
                "and dimensions for this period"
            ),
        }
    ]


def test_estimates_compare_only_a_fully_evidenced_match():
    """An exact context is compared; a near lookalike period is declined."""
    explicit = _fv_earnings_row(
        statistic="mean", unit="USD", basis="diluted", dimensions=["consensus"]
    )
    matched = equibles_reconcile.compare_earnings(
        {"quarterly": [explicit]}, _eq_payload(_eq_estimate())
    )
    comparison = matched["comparisons"][0]
    assert matched["data"] == {"eps_estimate_2026Q3": 1.45}
    assert comparison["values"] == {"FINVIZ": 1.45, "EQUIBLES": 1.45}
    assert comparison["match"] is True
    assert matched["fields"]["eps_estimate_2026Q3"]["compared"] == [
        "FINVIZ", "EQUIBLES"
    ]
    assert matched["fields"]["eps_estimate_2026Q3"]["agreement"] is True
    assert matched["eps_estimate_analyst_counts"]["eps_estimate_2026Q3"][
        "analyst_count"
    ] == 12

    # Same metric and same value, but a different reporting period and unit.
    declined = equibles_reconcile.compare_earnings(
        {"quarterly": [_fv_earnings_row(
            statistic="mean", unit="EUR", basis="diluted", dimensions=["consensus"]
        )]},
        _eq_payload(_eq_estimate()),
    )
    assert declined["comparisons"] == []
    assert len(declined["declined_comparisons"]) == 1


def test_analyst_count_is_never_parsed_from_display_text():
    """``52 analysts`` is prose, not a supplied categorical count."""
    rows = equibles_reconcile.analyst_observations({
        "data": [_eq_estimate(dimAnalystCount=None)]
    })
    counts = equibles_reconcile.analyst_counts(rows)
    record = counts["2026Q3"]
    assert record["analyst_count"] is None
    assert record["analyst_count_source"] is None
    assert record["analyst_display"] == "52 analysts"
    assert record["single_source"] is True

    # Zero is a real supplied count and must not collapse into the null case.
    zero = equibles_reconcile.analyst_counts(
        equibles_reconcile.analyst_observations({"data": [_eq_estimate(dimAnalystCount=0)]})
    )
    assert zero["2026Q3"]["analyst_count"] == 0


@pytest.mark.asyncio
async def test_keyless_earnings_never_calls_equibles(earnings_legs, monkeypatch):
    """No key means no adapter call, no scope change and no coverage change."""
    called = False

    async def refuse(_ticker):
        nonlocal called
        called = True
        raise AssertionError("keyless call must not reach the Equibles adapter")

    async def fv_earnings(_symbol):
        return {"quarterly": [_fv_earnings_row()]}

    monkeypatch.setattr(equibles_reconcile, "fetch_analyst_observations", refuse)
    monkeypatch.setattr(earnings_legs, "earnings", fv_earnings)
    result = await tools_market.stock_earnings("AAPL")

    assert called is False
    assert result["providers_answered"] == ["TRADINGVIEW", "FINVIZ", "YAHOO"]
    assert result["data_provider"] == "ALL"
    assert all(error["provider"] != "EQUIBLES" for error in result["errors"])
    assert result["data"]["eps_estimate_analyst_counts"] == {}
    assert "EQUIBLES" not in result["sources"]


@pytest.mark.asyncio
async def test_configured_earnings_keeps_consensus_out_of_unproven_rows(
    earnings_legs, monkeypatch
):
    """The configured leg answers, but an unproven context is only declined."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")

    async def fetch(_ticker):
        return {
            "observations": [_eq_estimate(period="FY2028")],
            "eps_estimate_analyst_counts": {},
            "source": "https://api.equibles.com/v1/stocks/AAPL/analyst-estimates",
            "freshness": {},
        }

    async def fv_earnings(_symbol):
        return {"quarterly": [_fv_earnings_row()]}

    monkeypatch.setattr(equibles_reconcile, "fetch_analyst_observations", fetch)
    monkeypatch.setattr(earnings_legs, "earnings", fv_earnings)
    result = await tools_market.stock_earnings("AAPL")

    assert "EQUIBLES" in result["providers_answered"]
    assert result["data"]["eps_estimate_analyst_counts"] == {}
    assert result["data"]["declined_comparisons"] == [
        {
            "field": "eps_estimate_2026Q3",
            "reason": (
                "Finviz supplies no explicit EPS statistic, unit, basis "
                "and dimensions for this period"
            ),
        }
    ]
    # No Finviz candidate carried a proven context, so no EPS value was compared.
    assert not any(
        row["field"].startswith("eps_estimate_") for row in result["comparisons"]
    )
    assert result["data"]["latest_eps_estimate"] == 1.45


@pytest.mark.asyncio
async def test_configured_earnings_reports_eps_observation_and_count(
    earnings_legs, monkeypatch
):
    """A real match adds a comparison without merging analyst populations."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")
    observations = equibles_reconcile.analyst_observations({"data": [_eq_estimate()]})

    async def fetch(_ticker):
        return {
            **_eq_payload(*observations),
            "source": "https://api.equibles.com/v1/stocks/AAPL/analyst-estimates",
            "freshness": {},
        }

    async def fv_earnings(_symbol):
        return {"quarterly": [_fv_earnings_row(
            statistic="mean", unit="USD", basis="diluted", dimensions=["consensus"]
        )]}

    monkeypatch.setattr(equibles_reconcile, "fetch_analyst_observations", fetch)
    monkeypatch.setattr(earnings_legs, "earnings", fv_earnings)
    result = await tools_market.stock_earnings("AAPL")

    assert result["data"]["eps_estimate_2026Q3"] == 1.45
    assert result["fields"]["eps_estimate_2026Q3"]["compared"] == ["FINVIZ", "EQUIBLES"]
    record = result["data"]["eps_estimate_analyst_counts"]["eps_estimate_2026Q3"]
    assert record["analyst_count"] == 12
    assert record["analyst_count_source"] == "EQUIBLES"
    assert record["population"] == "eps_estimate_contributors"
    assert result["sources"]["EQUIBLES"].startswith("https://api.equibles.com/")


def _short_history():
    return {
        "history": [
            {"date": "2026-10-15", "short_interest_shares_k": 1000.0},
            {"date": "2026-10-31", "short_interest_shares_k": 1100.5},
        ]
    }


def test_short_interest_compares_the_same_settlement_date_only():
    """Thousands convert once to shares; another settlement is not a match."""
    equibles = {
        "observations": [
            {"settlementDate": "2026-10-15", "shortPosition": 999_000},
            {"settlementDate": "2026-10-31", "shortPosition": 1_100_500},
        ]
    }
    result = equibles_reconcile.compare_short_interest(_short_history(), equibles)
    comparison = result["comparisons"][0]
    assert result["status"] == "compared"
    assert comparison["observation_date"] == "2026-10-31"
    assert comparison["unit"] == "shares"
    assert comparison["values"] == {"FINVIZ": 1_100_500, "EQUIBLES": 1_100_500}
    assert comparison["match"] is True
    assert result["fields"]["short_interest_shares"]["compared"] == [
        "FINVIZ", "EQUIBLES"
    ]

    # The only Equibles row belongs to an earlier FINRA settlement. Both dates
    # stay visible and no agreement or disagreement verdict is produced.
    older = equibles_reconcile.compare_short_interest(
        _short_history(),
        {"observations": [{"settlementDate": "2026-10-15", "shortPosition": 999_000}]},
    )
    row = older["comparisons"][0]
    assert older["status"] == "not_comparable"
    assert row["not_comparable"] is True
    assert row["match"] is None
    assert row["settlement_dates"]["FINVIZ"] == "2026-10-31"
    assert row["settlement_dates"]["EQUIBLES"] == ["2026-10-15"]
    assert older["fields"] == {}


@pytest.mark.asyncio
async def test_keyless_ownership_makes_no_equibles_request(monkeypatch):
    """No key and no Enterprise assertion means no short-interest request."""
    from tapebasis import fv_access

    called = False

    async def refuse(_ticker):
        nonlocal called
        called = True
        raise AssertionError("keyless ownership must not ask Equibles")

    async def insider(_symbol, **_kwargs):
        return {"rows": [], "count": 0}

    monkeypatch.setattr(equibles_reconcile, "fetch_short_interest_observations", refuse)
    monkeypatch.setattr(fv_access, "insider", insider)
    monkeypatch.setattr(fv_access, "institutional", insider)
    monkeypatch.setattr(fv_access, "short_interest", insider)

    result = await tools_finviz.stock_ownership("AAPL")
    assert called is False
    assert result["data_provider"] == "FINVIZ"
    assert result["providers_answered"] == ["FINVIZ"]
    assert all(error["provider"] != "EQUIBLES" for error in result["errors"])
    assert result["data"]["short_interest_consensus"]["comparisons"] == []


@pytest.mark.asyncio
async def test_ownership_short_consensus_does_not_claim_filing_ownership(
    monkeypatch,
):
    """An optional same-date cross-check leaves the envelope FINVIZ."""
    from tapebasis import fv_access

    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_ENTITLEMENT", "enterprise")

    async def insider(_symbol, **_kwargs):
        return {"rows": [], "count": 0}

    async def short_interest(_symbol, **_kwargs):
        return _short_history()

    async def fetch(_ticker):
        return {
            "observations": [
                {"settlementDate": "2026-10-31", "shortPosition": 1_100_500}
            ],
            "source": "https://api.equibles.com/v1/securities/AAPL/short-interest",
            "freshness": {},
        }

    monkeypatch.setattr(fv_access, "insider", insider)
    monkeypatch.setattr(fv_access, "institutional", insider)
    monkeypatch.setattr(fv_access, "short_interest", short_interest)
    monkeypatch.setattr(equibles_reconcile, "fetch_short_interest_observations", fetch)

    result = await tools_finviz.stock_ownership("AAPL")
    assert result["data_provider"] == "FINVIZ"
    assert result["providers_answered"] == ["FINVIZ"]
    assert result["data"]["short_interest_consensus"]["status"] == "compared"
    assert result["fields"]["short_interest_shares"]["agreement"] is True
    assert result["sources"]["EQUIBLES"].endswith("/short-interest")
