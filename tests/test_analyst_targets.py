"""Recorded-provider tests for analyst targets and their distinct count scopes.

The live AAPL readings were reduced to small fixtures. Finviz's firm count is
derived from its visible ratings rows; TradingView publishes both populations
in the forecast page's JSON. No test contacts either upstream.
"""
from __future__ import annotations

import json

import pytest

from tapebasis.providers.finviz.core.services import quote_service
from tapebasis.providers.finviz.core.services.html_utils import (
    parse_analyst_ratings,
)
from tapebasis.providers.tradingview import native


def _finviz_ratings_html() -> str:
    """Return a quote-page fragment with repeated firms in its ratings island."""
    props = {
        "ratings": [
            {"date": "2026-11-11", "firm": "China Renaissance", "rating": "Hold to Buy"},
            {"date": "2026-10-01", "firm": "Morgan Stanley", "rating": "Overweight"},
            {"date": "2026-09-23", "firm": "Morgan Stanley", "rating": "Overweight"},
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


@pytest.mark.parametrize(
    "markup",
    [
        "",
        '<script data-ssr-props="ssr-island-analyst-ratings-0">bad json</script>',
        '<script data-ssr-props="ssr-island-analyst-ratings-0">{"ratings": []}</script>',
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
