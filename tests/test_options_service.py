"""Option contract null and zero semantics."""
from __future__ import annotations

import pytest

from tapebasis.providers.tradingview.core.services.options_service import _normalize_contract


@pytest.mark.parametrize("value", [None, 0])
@pytest.mark.parametrize("field", ["volume", "openInterest"])
def test_normalize_contract_preserves_null_and_zero(field, value):
    contract = _normalize_contract({field: value}, "call")
    output_key = "open_interest" if field == "openInterest" else field
    assert contract[output_key] == value


@pytest.mark.parametrize("field", ["volume", "openInterest"])
def test_normalize_contract_leaves_absent_activity_unreported(field):
    contract = _normalize_contract({}, "put")
    output_key = "open_interest" if field == "openInterest" else field
    assert contract[output_key] is None


def test_unusual_activity_leaves_missing_activity_out_of_totals(monkeypatch):
    monkeypatch.setattr(
        "tapebasis.providers.tradingview.core.services.options_service._fmt_expiry",
        lambda timestamp: "2026-11-20",
    )

    def fake_fetch(url):
        block = {"calls": [{"strike": 100}], "puts": [{"strike": 100}]}
        return {
            "optionChain": {
                "result": [
                    {
                        "quote": {"regularMarketPrice": 100},
                        "expirationDates": [1],
                        "options": [block],
                    }
                ]
            }
        }

    monkeypatch.setattr(
        "tapebasis.providers.tradingview.core.services.options_service._fetch",
        fake_fetch,
    )
    from tapebasis.providers.tradingview.core.services.options_service import (
        get_unusual_options_activity,
    )

    result = get_unusual_options_activity("TEST")
    assert result["total_call_volume"] == 0
    assert result["total_put_volume"] == 0
    assert result["unusual"] == []
