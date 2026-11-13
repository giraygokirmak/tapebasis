"""Tests for the provider payload shapers (pure mapping, no network)."""
from __future__ import annotations

import pytest

from tapebasis.merge_helpers import (
    fv_earnings_fields,
    fv_indices_fields,
    fv_news_fields,
    fv_options_fields,
    fv_quote_fields,
    news_overlap,
    option_overlap,
    _option_contract_key,
    tv_indices_fields,
    tv_options_fields,
)


def test_finviz_quote_snapshot_annotations_are_coerced(fv_quote):
    fv_quote["snapshot_numeric"]["52W High"] = "351.73 -5.64%"
    fields = fv_quote_fields(fv_quote)
    # The leading level must survive the annotation, or it can never be compared.
    assert fields["week_52_high"] == 351.73
    assert fields["company"] == "Apple Inc"
    assert fields["after_hours_price"] == 329.8


def test_finviz_indices_map_to_canonical_names():
    payload = {
        "indices": [
            {"ticker": "DJI", "last": 51786.7, "change_percent": -0.38},
            {"ticker": "SPX", "last": 7568.9, "change_percent": 0.36},
            {"ticker": "COMP", "last": 25372.0, "change_percent": 0.83},
        ]
    }
    mapped = fv_indices_fields(payload)["indices"]
    assert set(mapped) == {"DJI", "SPX", "COMP"}
    assert mapped["SPX"]["level"] == 7568.9


def test_tradingview_snapshot_maps_to_canonical_names():
    payload = {
        "indices": [
            {"symbol": "^GSPC", "price": 7568.92, "change_pct": 0.36},
            {"symbol": "^IXIC", "price": 25372.01, "change_pct": 0.83},
        ]
    }
    mapped = tv_indices_fields(payload)["indices"]
    assert set(mapped) == {"SPX", "COMP"}
    assert mapped["SPX"]["level"] == 7568.92


def test_finviz_news_fields_use_real_key_names():
    payload = {
        "ticker": "AAPL",
        "news": [
            {
                "datetime": "Today 12:45AM",
                "headline": "Apple AI tools come to China",
                "source": "AFP",
                "url": "https://example.test/a",
                "reaction_day_percent": 1.2,
            }
        ],
    }
    fields = fv_news_fields(payload)
    assert fields["count"] == 1
    item = fields["items"][0]
    assert item["title"] == "Apple AI tools come to China"
    assert item["reaction_day_percent"] == 1.2
    assert item["titles_key"] == "apple ai tools come to china"


def test_news_overlap_counts_shared_headlines():
    overlap = news_overlap(
        [{"titles_key": "alpha"}, {"titles_key": "beta"}],
        [{"titles_key": "beta"}, {"titles_key": "gamma"}],
    )
    assert overlap["shared"] == 1
    assert overlap["overlap_pct"] == 50.0


def test_finviz_options_split_by_type():
    payload = {
        "expiry": "2026-11-04",
        "expiries": ["2026-11-04", "2026-11-06"],
        "contracts": [
            {"type": "call", "strike": 330, "lastVolume": 10, "openInterest": 100},
            {"type": "put", "strike": 330, "lastVolume": 20, "openInterest": 200},
        ],
        "count": 2,
    }
    fields = fv_options_fields(payload)
    assert len(fields["calls"]) == 1
    assert len(fields["puts"]) == 1
    assert fields["calls"][0]["volume"] == 10
    assert fields["puts"][0]["open_interest"] == 200


def test_tradingview_options_use_normalised_keys():
    payload = {
        "requested_expiry": "2026-11-04",
        "available_expiries": ["2026-11-04"],
        "underlying_price": 331.9,
        "calls": [
            {"strike": 330, "volume": 10, "open_interest": 0, "last_price": 2.5, "iv": 0.4}
        ],
        "puts": [],
        "call_count": 1,
        "put_count": 0,
    }
    fields = tv_options_fields(payload)
    assert fields["calls"][0]["last"] == 2.5
    assert fields["calls"][0]["iv"] == 0.4


def test_option_rows_preserve_zero_and_missing_values():
    fields = tv_options_fields(
        {
            "calls": [
                {
                    "strike": 100,
                    "lastVolume": None,
                    "volume": 0,
                    "openInterest": 0,
                    "open_interest": 50,
                    "iv": 0,
                    "implied_volatility": 0.4,
                    "last_price": 0,
                    "lastPrice": 42,
                    "bidPrice": 0,
                    "bid": 3,
                    "askPrice": 0,
                    "ask": 3,
                },
                {"strike": 101},
            ]
        }
    )
    zero, missing = fields["calls"]
    for key in ("volume", "open_interest", "iv", "last", "bid", "ask"):
        assert zero[key] == 0
        assert missing[key] is None


def test_chain_level_expiry_is_explicit_not_invented_as_a_wildcard():
    fields = fv_options_fields(
        {"expiry": "2026-11-04", "contracts": [{"type": "call", "strike": 100}]}
    )
    assert fields["calls"][0]["expiry"] == "2026-11-04"
    assert _option_contract_key(fields["calls"][0]) == ("call", "2026-11-04", 100.0)


def test_option_overlap_compares_volume_and_skips_zero_open_interest():
    tv = [
        {
            "side": "call",
            "expiry": "2026-11-04",
            "strike": 330.0,
            "volume": 10,
            "open_interest": 0,
        }
    ]
    fv = [
        {
            "side": "call",
            "expiry": "2026-11-04",
            "strike": 330.0,
            "volume": 10,
            "open_interest": 500,
        }
    ]
    overlap = option_overlap(tv, fv)
    assert overlap["volume_agreeing"] == 1
    # Yahoo zeroes OI on same-day expiries: a convention, not a conflict.
    assert overlap["open_interest_compared"] == 0
    assert overlap["open_interest_unavailable"] == 1


@pytest.mark.parametrize(
    "different_field, tv_value, fv_value",
    [
        ("side", "call", "put"),
        ("expiry", "2026-11-04", "2026-11-06"),
        ("side", None, "call"),
    ],
)
def test_option_overlap_never_agrees_on_a_different_contract(
    different_field, tv_value, fv_value
):
    tv = [{"side": "call", "expiry": "2026-11-04", "strike": 330.0, "volume": 10}]
    fv = [{"side": "call", "expiry": "2026-11-04", "strike": 330.0, "volume": 10}]
    tv[0][different_field] = tv_value
    fv[0][different_field] = fv_value
    overlap = option_overlap(tv, fv)
    assert overlap["matched_contracts"] == 0
    assert overlap["volume_compared"] == 0
    assert overlap["volume_agreeing"] == 0


def test_earnings_fields_use_real_key_names():
    payload = {
        "earnings_date": "2026-11-02T16:30:00",
        "quarterly": [
            {"epsActual": 1.5, "epsEstimate": 1.4, "fiscalPeriod": "2026Q3"}
        ],
        "annual": [],
        "revisions": [],
        "price_reactions": [],
        "counts": {"quarterly": 1},
    }
    fields = fv_earnings_fields(payload)
    assert fields["latest_eps_actual"] == 1.5
    assert fields["latest_eps_estimate"] == 1.4
