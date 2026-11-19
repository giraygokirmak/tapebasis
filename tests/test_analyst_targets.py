"""Recorded-provider tests for analyst targets and their distinct count scopes.

The live AAPL and NVDA readings were reduced to small fixtures. Finviz's firm
count and separate row distribution come from its ratings SSR. TradingView's
scanner publishes its target range and five rating buckets; forecast SSR
supplies the distinct target-estimate population. No test contacts either upstream.
"""
from __future__ import annotations

import json

import pytest

from tapebasis import tools_tradingview
from tapebasis.providers.finviz.core.services import quote_service
from tapebasis.providers.finviz.core.services.html_utils import (
    parse_analyst_ratings,
)
from tapebasis.providers.tradingview import native
from tapebasis.symbols import Resolution


def _finviz_ratings_html() -> str:
    """Return a quote-page fragment with repeated firms in its ratings island."""
    props = {
        "ratings": [
            {
                "date": "2026-11-11",
                "firm": "China Renaissance",
                "rating": "Hold to Buy",
                "priceTarget": "$300 -> $400",
            },
            {
                "date": "2026-10-01",
                "firm": "Morgan Stanley",
                "rating": "Overweight → Mkt Perform",
                "priceTarget": "",
            },
            {
                "date": "2026-09-23",
                "firm": "Morgan Stanley",
                "rating": "Special New Rating",
                "priceTarget": "$0",
            },
        ],
        "lastClose": 352.1199951171875,
        "recom": 2.22,
        "targetPrice": 348.52,
        "today": "2026-11-17",
    }
    return (
        '<table class="js-snapshot-table"><tr>'
        '<td data-boxover-html="Analysts mean target price">Target Price</td>'
        "<td>348.52</td></tr></table>"
        '<script type="application/json" data-ssr-props="ssr-island-analyst-ratings-0">'
        + json.dumps(props)
        + "</script>"
    )


def test_finviz_counts_distinct_visible_firms_not_rating_rows():
    """Twenty visible Finviz rows produce sixteen firms when repeats collapse."""
    props = {
        "ratings": [
            {"date": "2026-11-11", "firm": "China Renaissance"},
            {"date": "2026-11-04", "firm": "DZ Bank"},
            {"date": "2026-10-20", "firm": "Loop Capital"},
            {"date": "2026-10-01", "firm": "Morgan Stanley"},
            {"date": "2026-09-18", "firm": "Evercore ISI"},
            {"date": "2026-09-01", "firm": "Rosenblatt"},
            {"date": "2026-08-17", "firm": "Rothschild & Co Redburn"},
            {"date": "2026-08-10", "firm": "Jefferies"},
            {"date": "2026-08-04", "firm": "DZ Bank"},
            {"date": "2026-08-04", "firm": "China Renaissance"},
            {"date": "2026-07-31", "firm": "Wells Fargo"},
            {"date": "2026-07-31", "firm": "TD Cowen"},
            {"date": "2026-07-31", "firm": "Morgan Stanley"},
            {"date": "2026-07-31", "firm": "JPMorgan"},
            {"date": "2026-07-31", "firm": "Goldman"},
            {"date": "2026-07-31", "firm": "Barclays"},
            {"date": "2026-07-24", "firm": "Robert W. Baird"},
            {"date": "2026-07-23", "firm": "Morgan Stanley"},
            {"date": "2026-07-17", "firm": "HSBC Securities"},
            {"date": "2026-07-14", "firm": "KeyBanc Capital Markets"},
        ],
        "targetPrice": 348.52,
        "recom": 2.22,
        "today": "2026-11-17",
    }
    markup = (
        '<script type="application/json" data-ssr-props="ssr-island-analyst-ratings-0">'
        + json.dumps(props)
        + "</script>"
    )
    shaped = parse_analyst_ratings(markup)
    assert shaped["ratings_included"] == 20
    assert shaped["rating_firms"] == 16
    assert shaped["includes_previous_ratings"] is True
    assert shaped["price_target_average"] == 348.52


def test_finviz_rating_rows_need_no_firm_or_analyst_identity():
    """Missing identities do not reduce row totals or hide their exact labels."""
    shaped = parse_analyst_ratings(_ratings_markup({
        "ratings": [
            {"rating": "Overweight", "analyst": "Visible identity is not required"},
            {"firm": "", "rating": None},
        ],
        "lastClose": 100,
    }))
    assert shaped["rating_firms"] == 0
    assert shaped["ratings_included"] == 2
    assert shaped["rating_distribution"] == {
        "buy": 1,
        "hold": 0,
        "sell": 0,
        "no_rating": 0,
        "unclassified": 1,
    }
    assert shaped["rating_label_counts"] == {"Overweight": 1}
    assert shaped["unlabeled_row_count"] == 1
    assert sum(shaped["rating_label_counts"].values()) + shaped["unlabeled_row_count"] == 2


def test_finviz_observed_rating_collection_can_have_zero_rows():
    """An observed empty list is zero, not the null returned for absent data."""
    shaped = parse_analyst_ratings(_ratings_markup({"ratings": []}))
    assert shaped["rating_firms"] == 0
    assert shaped["ratings_included"] == 0
    assert shaped["rating_distribution"] == {
        "buy": 0, "hold": 0, "sell": 0, "no_rating": 0, "unclassified": 0,
    }
    assert shaped["rating_label_counts"] == {}
    assert shaped["unlabeled_row_count"] == 0
    assert shaped["ratings"] == []


@pytest.mark.asyncio
async def test_finviz_analyst_block_uses_the_same_quote_fetch(monkeypatch):
    """The ratings island costs no extra Finviz page request."""
    calls = []

    async def fetch_html(url, **_kwargs):
        calls.append(url)
        return (
            '<h1 class="js-recent-quote-ticker" data-ticker="AAPL"></h1>'
            + _finviz_ratings_html()
        )

    from tapebasis.providers.finviz.core.services import finviz_client

    monkeypatch.setattr(finviz_client, "fetch_html", fetch_html)
    payload = await quote_service.get_quote("AAPL")
    assert len(calls) == 1
    assert payload["analyst_targets"]["rating_firms"] == 2
    assert payload["analyst_targets"]["ratings_included"] == 3


def test_finviz_normalizes_transitions_and_keeps_auditable_source_text():
    """Final labels drive row buckets and target upside without erasing originals."""
    shaped = parse_analyst_ratings(_finviz_ratings_html())
    assert shaped["rating_distribution"] == {
        "buy": 1,
        "hold": 1,
        "sell": 0,
        "no_rating": 0,
        "unclassified": 1,
    }
    assert shaped["rating_label_counts"] == {
        "Buy": 1, "Mkt Perform": 1, "Special New Rating": 1,
    }
    assert shaped["unlabeled_row_count"] == 0
    first, second, third = shaped["ratings"]
    assert first["rating"] == "Hold to Buy"
    assert first["rating_from"] == "Hold"
    assert first["rating_to"] == "Buy"
    assert first["rating_category"] == "Buy"
    assert first["rating_category_match"] == "known_phrase"
    assert first["priceTarget"] == "$300 -> $400"
    assert first["price_target_from"] == 300.0
    assert first["price_target_to"] == 400.0
    assert first["implied_upside"] == pytest.approx(400 / 352.1199951171875 - 1)
    assert second["rating_from"] == "Overweight"
    assert second["rating_to"] == "Mkt Perform"
    assert second["rating_category"] == "Hold"
    assert second["price_target_from"] is None
    assert second["price_target_to"] is None
    assert second["implied_upside"] is None
    assert third["rating_category"] is None
    assert third["price_target_to"] is None
    assert shaped["implied_upside_reference_price"] == 352.1199951171875
    assert shaped["implied_upside_unit"] == "decimal_ratio"


def test_finviz_classification_uses_final_label_and_audited_qualifiers():
    """Reverse transitions and novel labels cannot inherit a broad Buy fallback."""
    props = {
        "ratings": [
            {"firm": "Bank A", "rating": "Buy to Hold", "priceTarget": "$90 to $100"},
            {"firm": "Bank B", "rating": "Speculative Buy", "priceTarget": None},
            {"firm": "Bank C", "rating": "High Conviction Outperform"},
            {"firm": "Bank D", "rating": None},
        ],
        "lastClose": 100,
    }
    markup = (
        '<script type="application/json" '
        'data-ssr-props="ssr-island-analyst-ratings-0">'
        + json.dumps(props)
        + "</script>"
    )
    rows = parse_analyst_ratings(markup)["ratings"]
    assert rows[0]["rating_from"] == "Buy"
    assert rows[0]["rating_to"] == "Hold"
    assert rows[0]["rating_category"] == "Hold"
    assert rows[0]["price_target_from"] is None
    assert rows[0]["price_target_to"] is None
    assert rows[1]["rating"] == "Speculative Buy"
    assert rows[1]["rating_category"] is None
    assert rows[1]["rating_category_match"] == "unclassified"
    assert rows[1]["price_target_from"] is None
    assert rows[1]["price_target_to"] is None
    assert rows[1]["implied_upside"] is None
    assert rows[2]["rating_category"] == "Buy"
    assert rows[2]["rating_category_match"] == "known_qualifier"
    assert rows[3]["rating_from"] is None
    assert rows[3]["rating_to"] is None
    assert rows[3]["rating_category_match"] is None


@pytest.mark.parametrize(
    ("label", "category"),
    [
        ("High Conviction Strong Buy", "Buy"),
        ("Long Term Market Perform", "Hold"),
        ("High Conviction Underweight", "Sell"),
    ],
)
def test_finviz_known_qualifiers_accept_complete_multiword_cores(label, category):
    """Audited modifiers retain multiword phrases, not just one-word labels."""
    shaped = parse_analyst_ratings(_ratings_markup({
        "ratings": [{"firm": "Bank", "rating": label}],
        "lastClose": 100,
    }))
    assert shaped["ratings"][0]["rating_category"] == category
    assert shaped["ratings"][0]["rating_category_match"] == "known_qualifier"


def _ratings_markup(props: dict) -> str:
    """Return a ratings island for a focused parser input fixture."""
    return (
        '<script type="application/json" '
        'data-ssr-props="ssr-island-analyst-ratings-0">'
        + json.dumps(props)
        + "</script>"
    )


@pytest.mark.parametrize("target", [None, "", "NaN", "Infinity", "-Infinity", 200])
def test_finviz_rejects_missing_and_non_finite_targets(target):
    """Targets cannot become non-finite values or leak through numeric SSR text."""
    markup = _ratings_markup({
        "ratings": [{"firm": "Bank", "rating": "Buy", "priceTarget": target}],
        "lastClose": 100,
    })
    row = parse_analyst_ratings(markup)["ratings"][0]
    assert row["price_target_from"] is None
    assert row["price_target_to"] is None
    assert row["implied_upside"] is None
    assert parse_analyst_ratings(markup)["implied_upside_reference_price"] == 100.0


def test_finviz_upside_uses_only_the_same_ssr_price_and_positive_target():
    """A missing, invalid or non-finite reference cannot invent a target upside."""
    props = {
        "ratings": [{
            "firm": "CLSA",
            "rating": "High Conviction Outperform → Outperform",
            "priceTarget": "$425 → $255",
        }],
        "lastClose": 100.0,
    }
    markup = _ratings_markup(props)
    row = parse_analyst_ratings(markup)["ratings"][0]
    assert row["rating_from"] == "High Conviction Outperform"
    assert row["rating_to"] == "Outperform"
    assert row["rating_category"] == "Buy"
    assert row["price_target_from"] == 425.0
    assert row["price_target_to"] == 255.0
    assert row["implied_upside"] == pytest.approx(1.55)
    for invalid in (None, 0, -100, "100", True, float("nan"), float("inf")):
        shaped = parse_analyst_ratings(_ratings_markup({**props, "lastClose": invalid}))
        row = shaped["ratings"][0]
        assert row["price_target_from"] == 425.0
        assert row["price_target_to"] == 255.0
        assert row["implied_upside"] is None
        assert shaped["implied_upside_reference_price"] is None
    for tiny_close in (5e-324, 1e-323):
        shaped = parse_analyst_ratings(_ratings_markup({**props, "lastClose": tiny_close}))
        assert shaped["ratings"][0]["implied_upside"] is None


@pytest.mark.parametrize(
    "markup",
    [
        "",
        '<script data-ssr-props="ssr-island-analyst-ratings-0">bad json</script>',
        '<script data-ssr-props="another-island">{"ratings": [{"firm": "Bank"}]}</script>',
    ],
)
def test_finviz_missing_or_malformed_analyst_block_returns_none(markup):
    """An unreadable optional analyst island cannot invent a firm count."""
    assert parse_analyst_ratings(markup) is None


def _forecast_html() -> str:
    """Return the live page's forecast block with both analyst populations."""
    payload = {
        "page": {
            "symbol": "NASDAQ:AAPL",
            "initForecastQuotes": {
                "price_target_average": 348.519916,
                "recommendation_mark": 1.61,
                "price_target_estimates_num": 39,
                "last_report_frequency": 4,
                "recommendation_total": 50,
            },
        }
    }
    return '<script type="application/prs.init-data+json">' + json.dumps(payload) + "</script>"


def test_tradingview_forecast_reader_preserves_two_count_populations():
    """Price-target contributors and rating contributors are not interchangeable."""
    shaped = native.shape_analyst_forecasts(_forecast_html())
    assert shaped["price_target_estimates_num"] == 39
    assert shaped["recommendation_total"] == 50
    assert shaped["price_target_average"] == 348.519916
    assert shaped["recommendation_mark"] == 1.61


@pytest.mark.parametrize(
    "markup",
    [
        "",
        '<script type="application/prs.init-data+json">bad json</script>',
        '<script type="application/prs.init-data+json">{"page": {"symbol": "AAPL"}}</script>',
    ],
)
def test_tradingview_missing_forecast_block_returns_none(markup):
    """A page revision or wrong symbol does not fabricate an analyst count."""
    assert native.shape_analyst_forecasts(markup) is None


@pytest.mark.asyncio
async def test_tradingview_forecast_uses_the_resolved_symbol(monkeypatch):
    """The accessor requests the resolved TV symbol and decodes its actual JSON."""
    calls = []
    native.limiter("TRADINGVIEW").cache_clear()

    class Response:
        status_code = 200
        text = _forecast_html()

        def raise_for_status(self):
            return None

    class Client:
        async def get(self, url, **_kwargs):
            calls.append(url)
            return Response()

    monkeypatch.setattr(native, "shared_client", lambda *_args, **_kwargs: Client())
    payload = await native.analyst_forecasts("NASDAQ:AAPL")
    assert calls == [
        "https://www.tradingview.com/symbols/NASDAQ-AAPL/forecast-price-target/"
    ]
    assert payload["price_target_estimates_num"] == 39
    assert payload["recommendation_total"] == 50


@pytest.mark.asyncio
async def test_tradingview_forecast_rate_limit_uses_the_shared_guard(
    monkeypatch, _isolate_analyst_forecast_upstreams
):
    """A 429 is classified for shared provider cooldown, never as an empty count."""
    native.limiter("TRADINGVIEW").cache_clear()

    class Response:
        status_code = 429

    class Client:
        async def get(self, _url, **_kwargs):
            return Response()

    from tapebasis import ratelimit, tv_access
    from tapebasis.providers_state import ProviderError
    from tapebasis.ratelimit import RateLimitError

    async def no_sleep(_seconds):
        return None

    paced = native.limiter("TRADINGVIEW")
    paced._cooldown_until = 0.0
    paced._block_streak = 0
    monkeypatch.setattr(paced, "max_retries", 0)
    monkeypatch.setattr(paced, "min_interval", 0.0)
    monkeypatch.setattr(ratelimit.asyncio, "sleep", no_sleep)

    monkeypatch.setattr(native, "shared_client", lambda *_args, **_kwargs: Client())
    monkeypatch.setattr(
        tv_access, "analyst_forecasts", _isolate_analyst_forecast_upstreams
    )
    with pytest.raises(RateLimitError):
        await native.analyst_forecasts("NASDAQ:AAPL")
    # Isolate the access-layer translation from the previous call's intentional
    # cooldown; only the 429 classification is under test, not a timed wait.
    paced._cooldown_until = 0.0
    paced._block_streak = 0
    with pytest.raises(ProviderError) as error:
        await tv_access.analyst_forecasts("NASDAQ:AAPL")
    assert error.value.code == "UPSTREAM_RATE_LIMIT"


@pytest.mark.asyncio
async def test_access_marks_absent_forecast_coverage_as_no_data(
    monkeypatch, _isolate_analyst_forecast_upstreams
):
    """An unavailable forecast population is not a scanner symbol-resolution failure."""
    from tapebasis import tv_access
    from tapebasis.providers_state import NoDataError
    from tapebasis.reconcile import _error_dict

    async def missing(_ticker):
        raise native.SymbolNotFound("this resolved symbol has no forecast block")

    monkeypatch.setattr(native, "analyst_forecasts", missing)
    monkeypatch.setattr(
        tv_access, "analyst_forecasts", _isolate_analyst_forecast_upstreams
    )
    with pytest.raises(NoDataError) as error:
        await tv_access.analyst_forecasts("NASDAQ:AAPL")
    assert _error_dict("TRADINGVIEW", error.value)["code"] == "NO_DATA"


def test_scanner_target_count_is_not_replaced_by_rating_buckets():
    """The observed scanner null does not become a guessed forecast population."""
    assert "price_target_estimates_num" not in native.QUOTE_COLUMNS
    assert "recommendation_total" in native.QUOTE_COLUMNS


def test_scanner_columns_use_the_forecast_page_rating_field_mapping():
    """Strong Buy/Buy and Sell/Strong Sell use the frontend's exact raw fields."""
    expected = {
        "recommendation_buy": 50,
        "recommendation_over": 6,
        "recommendation_hold": 15,
        "recommendation_under": 0,
        "recommendation_sell": 1,
    }
    assert set(expected).issubset(native.QUOTE_COLUMNS)
    assert {"price_target_low", "price_target_high"}.issubset(native.QUOTE_COLUMNS)
    assert sum(expected.values()) == 72
    assert "recommendation_strong_buy" not in native.QUOTE_COLUMNS
    assert "recommendation_strong_sell" not in native.QUOTE_COLUMNS


async def _combined_analysis_fixture(monkeypatch, quote, forecast):
    """Return a combined_analysis envelope with hermetic provider payloads."""
    from tapebasis import fv_access, news, tv_access, yh_access

    async def technical(symbol, exchange="NASDAQ", timeframe="1D"):
        """Return a minimal technical analysis payload."""
        return {"symbol": symbol, "price_data": {"current_price": 331.9}}

    async def local_sentiment(symbol, limit=20):
        """Return a locally scored sentiment payload."""
        return {"provider": "local-vader", "sentiment_score": 0.3}

    async def snapshot(symbol):
        """Return a Finviz price snapshot."""
        return {"numeric": {"Price": 331.9}}

    async def yahoo_quote(symbol):
        """Return a Yahoo price quote."""
        return {"price": 331.9}

    async def resolve_yahoo(symbol):
        """Return a resolved Yahoo symbol without discovery requests."""
        return Resolution(
            query=symbol,
            provider="YAHOO",
            symbol="AAPL",
            method="explicit",
            confidence=1.0,
        )

    async def scanner_quote(symbol):
        """Return the supplied scanner row keyed by its resolved symbol."""
        return {**quote, "ticker": symbol}

    async def forecasts(symbol):
        """Return the supplied forecast row or raise its test failure."""
        if isinstance(forecast, BaseException):
            raise forecast
        return forecast

    async def empty_news(symbol, **kwargs):
        """Return an empty news envelope without contacting a news provider."""
        return {"block": {
            "items": [],
            "count": 0,
            "limit": 10,
            "unique_stories": 0,
            "errors": [],
            "data_provider": "NONE",
            "providers_answered": [],
            "endpoints": {},
            "shortfall_reason": "",
        }}

    monkeypatch.setattr(tv_access, "technical_analysis", technical)
    monkeypatch.setattr(tv_access, "quote", scanner_quote)
    monkeypatch.setattr(tv_access, "analyst_forecasts", forecasts)
    monkeypatch.setattr(tools_tradingview, "_sentiment_payload", local_sentiment)
    monkeypatch.setattr(tools_tradingview, "_yahoo_resolution", resolve_yahoo)
    monkeypatch.setattr(fv_access, "snapshot", snapshot)
    monkeypatch.setattr(yh_access, "quote", yahoo_quote)
    monkeypatch.setattr(news, "fetch_news", empty_news)
    return await tools_tradingview.combined_analysis("AAPL")


@pytest.mark.asyncio
async def test_combined_analysis_preserves_distinct_analyst_populations(monkeypatch):
    """The composite exposes real scanner buckets and the forecast target count."""
    quote = {
        "currency": "USD",
        "price_target_average": 348.519916,
        "price_target_low": 240.0,
        "price_target_high": 500.0,
        "recommendation_total": 50,
        "recommendation_mark": 1.61,
        "recommendation_buy": 25,
        "recommendation_over": 12,
        "recommendation_hold": 10,
        "recommendation_under": 1,
        "recommendation_sell": 2,
    }
    forecast = {
        "price_target_estimates_num": 39,
        "recommendation_total": 99,
        "recommendation_mark": 4.99,
        "source": "https://www.tradingview.com/symbols/NASDAQ-AAPL/forecast-price-target/",
    }
    result = await _combined_analysis_fixture(monkeypatch, quote, forecast)
    block = result["analyst_targets"]["TRADINGVIEW"]
    assert block["price_target_estimate_count"] == 39
    assert block["rating_analyst_count"] == 50
    assert block["mean_recommendation"] == 1.61
    assert block["rating_distribution"] == {
        "strong_buy": 25,
        "buy": 12,
        "hold": 10,
        "sell": 1,
        "strong_sell": 2,
    }
    assert block["rating_distribution_method"] == "scanner_rating_buckets"
    assert block["source"] == "scanner.tradingview.com"
    assert block["price_target_period"] == "1 year"
    assert block["rating_period"] == "past 3 months"
    assert block["forecast_source"] == forecast["source"]
    assert result["data"]["analysis"]["price_data"]["current_price"] == 331.9

    # The payload mirrors the same counts for a caller that reads only ``data``.
    assert result["data"]["analyst_targets"] == block
    assert result["data"]["tradingview_price_target_estimate_count"] == 39
    assert result["data"]["tradingview_rating_analyst_count"] == 50
    assert result["data"]["tradingview_rating_buy_count"] == 12
    assert result["data"]["tradingview_rating_hold_count"] == 10
    assert result["data"]["tradingview_rating_sell_count"] == 1
    assert result["data"]["tradingview_rating_distribution"] == {
        "strong_buy": 25, "buy": 12, "hold": 10, "sell": 1, "strong_sell": 2,
    }
    assert result["data"]["tradingview_rating_summary"] == {
        "total": 50,
        "population": "past_three_month_rating_analysts",
        "distribution": {
            "strong_buy": 25, "buy": 12, "hold": 10, "sell": 1, "strong_sell": 2,
        },
        "label_counts": {
            "strong_buy": 25, "buy": 12, "hold": 10, "sell": 1, "strong_sell": 2,
        },
        "unlabeled_row_count": None,
        "rating_period": "past 3 months",
        "includes_previous_ratings": None,
        "rating_distribution_method": "scanner_rating_buckets",
    }
    assert result["fields"]["tradingview_rating_summary"]["source"] == "TRADINGVIEW"


@pytest.mark.asyncio
async def test_combined_analysis_all_null_ratings_have_no_summary_provenance(monkeypatch):
    """A scanner row with no ratings cannot create a zero-filled summary."""
    result = await _combined_analysis_fixture(
        monkeypatch,
        {"currency": "USD"},
        {"price_target_estimates_num": 39},
    )
    summary = result["data"]["tradingview_rating_summary"]
    assert summary is None
    assert "tradingview_rating_summary" not in result["fields"]
    assert result["analyst_targets"]["TRADINGVIEW"]["price_target_estimate_count"] == 39


@pytest.mark.asyncio
async def test_combined_analysis_forecast_failure_keeps_zero_and_null_distinct(monkeypatch):
    """A real zero Sell bucket survives while an unavailable target count is null."""
    from tapebasis.providers_state import ProviderError

    quote = {
        "recommendation_total": 4,
        "recommendation_buy": 2,
        "recommendation_over": 1,
        "recommendation_hold": 1,
        "recommendation_under": 0,
        "recommendation_sell": 0,
    }
    failure = ProviderError("TRADINGVIEW", "forecast unavailable", code="UPSTREAM_ERROR")
    result = await _combined_analysis_fixture(monkeypatch, quote, failure)
    block = result["analyst_targets"]["TRADINGVIEW"]
    assert block["price_target_estimate_count"] is None
    assert block["rating_analyst_count"] == 4
    assert block["rating_distribution"]["sell"] == 0
    assert block["forecast_source"] is None
    assert result["data"]["sentiment"]["sentiment_score"] == 0.3
    error = next(error for error in result["errors"] if error["provider"] == "TRADINGVIEW")
    assert error["detail"]["capability"] == "analyst_forecasts"
    assert result["data_provider"] == "ALL"
    assert result["data"]["tradingview_price_target_estimate_count"] is None
    assert result["data"]["tradingview_rating_analyst_count"] == 4
    assert result["data"]["tradingview_rating_sell_count"] == 0
