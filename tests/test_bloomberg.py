"""Bloomberg provider tests (recorded payloads, no network).

The important properties pinned here:

* Bloomberg is a full leg: it is in ``PROVIDER_ORDER``, so it can
  contribute to ``ALL`` / ``MULTI_SOURCE``, and last in the tie-break order
  because its prints can be structurally older.
* The print time comes from the intraday series, never from ``lastUpdate``,
  which is a session sentinel on equity pages.
* A delayed print is reported as *not comparable* rather than as a
  disagreement, and the reason names the delay.
* A page that exists but carries no price is ``NONE`` with a reason, not a
  number.
"""
from __future__ import annotations

import pytest

from tapebasis import bb_access, tools_bloomberg
from tapebasis.providers_state import DataProvider, PROVIDER_ORDER, Verification
from tapebasis.reconcile import DEFAULT_ORDER, compare_values


def _equity_quote(**overrides):
    """A trimmed bloomberg.com/quote/AAPL:US ``pageProps.quote`` object."""
    payload = {
        "id": "AAPL:US",
        "name": "APPLE INC",
        "price": "349.51",
        "prevClose": "331.90",
        "percentChange1Day": 5.305815,
        "volume": "89,637,749.00",
        "dayRange": ["340.99", "354.50"],
        "fiftyTwoWeekRange": ["243.42", "354.50"],
        "priceEarningsRatio": "38.96",
        "earningsPerShare": "8.98",
        "issuedCurrency": "USD",
        "primaryExchange": "NASDAQ GS",
        "marketStatus": "ACTV",
        "isOpen": False,
        "isAfterHours": True,
        "isExchangeDelayed": True,
        "exchangeDelay": "15 Minutes",
        "tradingDate": "2026-11-05",
        "tradingDayClose": "2026-11-04T21:30:00.000Z",
        # The sentinel that must never be read as the print time.
        "lastUpdate": "2026-11-05T01:00:00.000Z",
        "priceMovements1Day": [
            {"dateTime": "2026-11-04T20:54:00Z", "value": 349.565},
            {"dateTime": "2026-11-04T20:56:00Z", "value": 349.1},
            {"dateTime": "2026-11-04T20:58:00Z", "value": 349.51},
        ],
    }
    payload.update(overrides)
    return payload


def _board():
    return {
        "tickerbar": [
            {"ticker": "SPX:IND", "name": "S&P 500", "price": 7688.62, "percentChange1Day": 1.581467},
            {"ticker": "GT10:GOV", "name": "US 10 Yr", "price": 4.8777106, "percentChange1Day": -0.0102},
            {"ticker": "GTGBP10Y:GOV", "name": "UK 10 Yr", "price": 5.1136, "percentChange1Day": -0.0145},
            {"ticker": "CL1:COM", "name": "Crude Oil", "price": 88.63, "percentChange1Day": 0.5787},
            {"ticker": "EURUSD:CUR", "name": "Euro", "price": 1.1229, "percentChange1Day": 0.0089},
            {"ticker": "WHAT:XYZ", "name": "ignored", "price": 1.0, "percentChange1Day": 0.0},
        ]
    }


# ── the label contract ───────────────────────────────────────────────────────


def test_bloomberg_is_the_fourth_leg_and_loses_any_tie_break():
    assert DataProvider.BLOOMBERG.value == "BLOOMBERG"
    assert "BLOOMBERG" in PROVIDER_ORDER
    # Last, because a delayed page must never outrank a live feed on a tie.
    assert PROVIDER_ORDER[-1] == "BLOOMBERG"
    assert DEFAULT_ORDER[-1] == "BLOOMBERG"


def test_a_delayed_print_is_not_comparable_not_a_disagreement():
    """15 minutes apart is a different observation, and the reason says why."""
    row = compare_values(
        {"TRADINGVIEW": 349.51, "BLOOMBERG": 348.2},
        times={
            "TRADINGVIEW": "2026-11-05T14:00:00+00:00",
            "BLOOMBERG": "2026-11-05T13:45:00+00:00",
        },
        max_skew_seconds=900.0,
        session_boundary=True,
    )
    assert row["match"] is None
    assert row["not_comparable"] is True
    reason = row["pairs"][0]["not_comparable"]
    assert "do not describe the same observation" in reason
    assert "exchange-delayed" in reason
    # Both readings stay visible: the delay hides neither number.
    assert row["values"] == {"TRADINGVIEW": 349.51, "BLOOMBERG": 348.2}


def test_a_closed_market_lets_bloomberg_agree_with_the_others():
    """At the close there is one print instant, so the leg is comparable."""
    row = compare_values(
        {"TRADINGVIEW": 349.51, "BLOOMBERG": 349.51},
        times={
            "TRADINGVIEW": "2026-11-04T20:58:30+00:00",
            "BLOOMBERG": "2026-11-04T20:58:00+00:00",
        },
        max_skew_seconds=900.0,
        session_boundary=True,
    )
    assert row["match"] is True
    assert not row.get("not_comparable")


# ── symbol resolution ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("AAPL", "AAPL:US"),
        ("aapl", "AAPL:US"),
        ("NASDAQ:AAPL", "AAPL:US"),
        ("BRK.B", "BRK/B:US"),
        ("BRK/B:US", "BRK/B:US"),
        ("SPX", "SPX:IND"),
        ("DJI", "INDU:IND"),
        ("COMP", "CCMP:IND"),
        ("VIX", "VIX:IND"),
        ("EURUSD", "EURUSD:CUR"),
        ("GBPUSD", "GBPUSD:CUR"),
        ("XAUUSD", "XAUUSD:CUR"),
        ("BTCUSD", "XBTUSD:CUR"),
        ("CL1", "CL1:COM"),
        ("GC", "GC1:COM"),
        ("AAPL:US", "AAPL:US"),
    ],
)
def test_symbol_mapping(requested, expected):
    assert bb_access.to_bloomberg(requested) == expected


def test_empty_symbol_is_not_resolved():
    with pytest.raises(Exception):
        bb_access.to_bloomberg("  ")


# ── shaping ──────────────────────────────────────────────────────────────────


def test_print_time_comes_from_the_intraday_series_not_last_update():
    data = bb_access.shape_quote(_equity_quote(), requested="AAPL")
    assert data["print_time"] == "2026-11-04T20:58:00Z"
    assert data["print_time_source"] == "priceMovements1Day[-1].dateTime"
    # The sentinel is still visible, but only as provider metadata.
    assert data["provider_last_update"] == "2026-11-05T01:00:00.000Z"
    assert data["print_time"] != data["provider_last_update"]


def test_formatted_numbers_are_parsed():
    data = bb_access.shape_quote(_equity_quote(), requested="AAPL")
    assert data["price"] == 349.51
    assert data["previous_close"] == 331.9
    assert data["volume"] == 89_637_749.0
    assert data["pe_ratio"] == 38.96
    assert data["day_range"] == [340.99, 354.5]
    assert data["week_52_range"] == [243.42, 354.5]
    # Already a percentage upstream, so it is not multiplied by 100.
    assert data["change_percent"] == pytest.approx(5.305815)
    assert data["exchange_delay"] == "15 Minutes"
    assert data["is_exchange_delayed"] is True


def test_series_that_does_not_match_the_price_gives_no_print_time():
    payload = _equity_quote(
        priceMovements1Day=[{"dateTime": "2026-11-04T20:58:00Z", "value": 300.0}]
    )
    data = bb_access.shape_quote(payload, requested="AAPL")
    assert data["print_time"] is None
    assert "does not describe the quoted print" in data["print_time_missing_reason"]


def test_missing_series_gives_no_print_time():
    data = bb_access.shape_quote(_equity_quote(priceMovements1Day=[]), requested="AAPL")
    assert data["print_time"] is None
    assert data["print_time_source"] is None


def test_page_without_a_price_is_no_data():
    with pytest.raises(Exception) as excinfo:
        bb_access.shape_quote(_equity_quote(price=None), requested="ZZZZ")
    assert "no price" in str(excinfo.value)


def test_board_groups_by_instrument_class():
    data = bb_access.shape_board(_board())
    assert [row["symbol"] for row in data["indices"]] == ["SPX:IND"]
    assert [row["symbol"] for row in data["government_yields"]] == ["GT10:GOV", "GTGBP10Y:GOV"]
    assert [row["symbol"] for row in data["commodities"]] == ["CL1:COM"]
    assert [row["symbol"] for row in data["fx"]] == ["EURUSD:CUR"]
    # Unknown classes are dropped rather than invented into a group.
    assert all(
        row["symbol"] != "WHAT:XYZ"
        for rows in data.values()
        for row in rows
    )


def test_board_without_rows_is_no_data():
    with pytest.raises(Exception):
        bb_access.shape_board({"tickerbar": []})


# ── envelope ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quote_envelope_is_single_source_bloomberg(monkeypatch):
    async def fake_quote(symbol):
        return bb_access.shape_quote(_equity_quote(), requested=symbol), "https://example.test/AAPL:US"

    monkeypatch.setattr(bb_access, "quote", fake_quote)
    response = await tools_bloomberg.bloomberg_quote("AAPL")

    assert response["data_provider"] == "BLOOMBERG"
    assert response["verification"] == Verification.SINGLE_SOURCE.value
    assert response["providers_answered"] == ["BLOOMBERG"]
    assert response["cross_checked"] is False
    # False describes this call (one provider asked), not the provider's
    # standing: stock_quote does compare Bloomberg with the other three.
    assert response["reconciliation_leg"] is False
    assert "single-source" in response["notice"].lower()
    assert response["data"]["price"] == 349.51
    assert any("exchange-delayed" in warning for warning in response["warnings"])


@pytest.mark.asyncio
async def test_markets_envelope_carries_the_yield_curve(monkeypatch):
    async def fake_board():
        return bb_access.shape_board(_board()), "https://example.test/markets"

    monkeypatch.setattr(bb_access, "board", fake_board)
    response = await tools_bloomberg.bloomberg_markets()

    assert response["data_provider"] == "BLOOMBERG"
    assert response["verification"] == Verification.SINGLE_SOURCE.value
    assert response["print_time"] is None
    assert any("no per-instrument print time" in warning for warning in response["warnings"])
    assert response["data"]["government_yields"][0]["price"] == pytest.approx(4.8777106)


@pytest.mark.asyncio
async def test_failure_is_labelled_none_with_the_reason(monkeypatch):
    async def failing(symbol):
        raise RuntimeError("boom")

    monkeypatch.setattr(bb_access, "quote", failing)
    response = await tools_bloomberg.bloomberg_quote("AAPL")

    assert response["data_provider"] == "NONE"
    assert response["data"] is None
    assert response["errors"][0]["provider"] == "BLOOMBERG"
    assert "boom" in response["warnings"][0]


# ── page decoding ────────────────────────────────────────────────────────────


def _html(payload: dict) -> str:
    import json as _json

    body = _json.dumps({"props": {"pageProps": payload}})
    return (
        "<html><body><script id=\"__NEXT_DATA__\" type=\"application/json\">"
        f"{body}</script></body></html>"
    )


def test_payload_is_extracted_from_the_rendered_page():
    html = _html({"quote": _equity_quote()})
    assert bb_access._payload(html)["props"]["pageProps"]["quote"]["id"] == "AAPL:US"


def test_page_without_next_data_is_schema_drift():
    with pytest.raises(Exception) as excinfo:
        bb_access._payload("<html><body>Are you a robot?</body></html>")
    assert excinfo.value.code == "SCHEMA_DRIFT"


@pytest.mark.asyncio
async def test_quote_end_to_end_from_a_rendered_page(monkeypatch):
    """The fetch is faked; the decode, shape, label and URL are not."""
    seen: dict[str, str] = {}

    async def fake_fetch(path, cache_key):
        seen["path"] = path
        return _html({"quote": _equity_quote()})

    monkeypatch.setattr(bb_access, "_fetch_html", fake_fetch)

    response = await tools_bloomberg.bloomberg_quote("AAPL")
    assert seen["path"] == "/quote/AAPL:US"
    assert response["data_provider"] == "BLOOMBERG"
    assert response["data"]["print_time"] == "2026-11-04T20:58:00Z"
    assert response["sources"] == {"BLOOMBERG": "https://www.bloomberg.com/quote/AAPL:US"}


@pytest.mark.asyncio
async def test_ticker_page_without_a_quote_object_is_no_data(monkeypatch):
    async def fake_fetch(path, cache_key):
        return _html({})

    monkeypatch.setattr(bb_access, "_fetch_html", fake_fetch)
    response = await tools_bloomberg.bloomberg_quote("ZZZZ")
    assert response["data_provider"] == "NONE"
    assert response["errors"][0]["code"] == "NO_DATA"
