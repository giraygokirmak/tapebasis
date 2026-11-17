"""Yahoo chart-API shaping: fields that arrived in ``meta`` and were dropped.

``meta`` carries the session's own open / high / low / volume. ``_format_quote``
used to shape only price, change, previous close and the 52-week range, so the
day range was downloaded on every request and thrown away before it could reach
a comparison.
"""
from __future__ import annotations

from tapebasis import yh_access


def _chart_result(**meta_overrides):
    """A minimal ``chart.result[0]`` with a real 5-day candle series."""
    meta = {
        "currency": "USD",
        "symbol": "AAPL",
        "exchangeName": "NMS",
        "fullExchangeName": "NasdaqGS",
        "instrumentType": "EQUITY",
        "regularMarketTime": 1793739601,
        "regularMarketPrice": 342.37,
        "regularMarketDayHigh": 345.79,
        "regularMarketDayLow": 338.3,
        "regularMarketOpen": 338.73,
        "regularMarketVolume": 44703806,
        "fiftyTwoWeekHigh": 355.38,
        "fiftyTwoWeekLow": 243.42,
        "shortName": "Apple Inc.",
        "longName": "Apple Inc.",
        "chartPreviousClose": 344.63,
        "marketState": "CLOSED",
    }
    meta.update(meta_overrides)
    return {
        "meta": meta,
        "timestamp": [1793479800, 1793566200, 1793652600, 1793739601],
        "indicators": {
            "quote": [
                {
                    "close": [339.1, 341.2, 344.17, 342.37],
                    "open": [337.5, 339.4, 342.0, 338.73],
                    "high": [340.2, 342.0, 345.0, 345.79],
                    "low": [336.8, 338.9, 341.5, 338.3],
                    "volume": [50_000_000, 48_000_000, 46_000_000, 44_703_806],
                }
            ]
        },
    }


def test_day_range_is_shaped_from_meta():
    data = yh_access._format_quote("AAPL", _chart_result())
    assert data["day_open"] == 338.73
    assert data["day_high"] == 345.79
    assert data["day_low"] == 338.3


def test_volume_is_shaped_from_meta():
    data = yh_access._format_quote("AAPL", _chart_result())
    assert data["volume"] == 44703806


def test_company_name_is_shaped():
    data = yh_access._format_quote("AAPL", _chart_result())
    assert data["company"] == "Apple Inc."


def test_absent_day_open_is_none_not_an_error():
    """``regularMarketOpen`` is genuinely absent on some symbols and ranges."""
    result = _chart_result(regularMarketOpen=None)
    data = yh_access._format_quote("AAPL", result)
    assert data["day_open"] is None
    # The rest of the range is still served.
    assert data["day_high"] == 345.79


def test_day_range_survives_a_missing_price():
    """The price is derived from candles when needed; the range does not depend on it."""
    result = _chart_result(regularMarketPrice=None)
    data = yh_access._format_quote("AAPL", result)
    assert data["price"] == 342.37  # last valid close
    assert data["day_high"] == 345.79


def test_previous_close_still_comes_from_the_candle_series():
    """The new fields must not disturb the derivation this module exists for."""
    data = yh_access._format_quote("AAPL", _chart_result())
    assert data["previous_close"] == 344.17
    assert data["change_pct"] == -0.523
