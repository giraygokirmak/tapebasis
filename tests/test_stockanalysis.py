"""Tests for the StockAnalysis leg: transport shaping, resolution and wiring.

The upstream is faked throughout: the shape asserted here is the live envelope
(``{"status": 200, "data": {...}}`` with ``p``/``cl``/``o``/``h``/``l``/``v``/
``h52``/``l52``/``ts``/``td``), so a renaming upstream shows up as a failure
rather than as a silently empty leg.
"""
from __future__ import annotations

import pytest

from tapebasis import sa_access
from tapebasis.providers_state import NoDataError, ProviderError
from tapebasis.sa_access import shape_quote, to_stockanalysis
from tapebasis.symbols import resolve_sa

#: 2026-11-06 21:00:00 UTC, the US close the live endpoint reported, in the
#: milliseconds the endpoint uses.
CLOSE_TS_MS = 1793998800000
CLOSE_ISO = "2026-11-06T21:00:00+00:00"


def _payload(**overrides):
    """A live-shaped ``/api/quotes/s/<ticker>`` response body."""
    data = {
        "p": 342.37,
        "pd": 342.37,
        "c": -1.8,
        "cp": -0.52,
        "cl": 344.17,
        "cdr": -1,
        "o": 338.73,
        "h": 345.79,
        "l": 338.3,
        "v": 44703806.360675,
        "ts": CLOSE_TS_MS,
        "u": "Nov 6, 2026, 4:00 PM EST",
        "td": "2026-11-06",
        "h52": 355.38,
        "l52": 243.42,
        "ex": "NASDAQ",
        "ms": "closed",
        "fms": "pre",
        "e": True,
        "ep": 344.39,
        "epd": 344.39,
        "ec": 2.02,
        "ecp": 0.59,
        "eu": "Nov 9, 2026, 4:55 AM EST",
        "es": "Pre-market",
        "ets": 1794218130091.4753,
        "etd": "2026-11-09",
        "epv": 97129,
        "days": 2,
        "exp": 1794218377013,
        "symbol": "AAPL",
        "uid": "AAPL",
    }
    data.update(overrides)
    return {"status": 200, "data": data}


# ── shaping ──────────────────────────────────────────────────────────────────


def test_shape_carries_the_whole_quote_surface():
    shaped = shape_quote(_payload(), requested="AAPL")
    assert shaped["price"] == pytest.approx(342.37)
    assert shaped["change_percent"] == pytest.approx(-0.52)
    # ``cl`` is the close the change is measured against. ``pd`` repeats the
    # current price and must never be read as the previous close.
    assert shaped["previous_close"] == pytest.approx(344.17)
    assert shaped["day_open"] == pytest.approx(338.73)
    assert shaped["day_high"] == pytest.approx(345.79)
    assert shaped["day_low"] == pytest.approx(338.3)
    assert shaped["volume"] == pytest.approx(44703806.36)
    assert shaped["week_52_high"] == pytest.approx(355.38)
    assert shaped["week_52_low"] == pytest.approx(243.42)
    assert shaped["exchange"] == "NASDAQ"
    assert shaped["market_state"] == "closed"
    assert shaped["price_date"] == "2026-11-06"


def test_epoch_milliseconds_become_iso():
    """``ts`` is milliseconds; passing it through would date the print to year 56828."""
    shaped = shape_quote(_payload(), requested="AAPL")
    assert shaped["price_timestamp"] == CLOSE_ISO
    parsed = sa_access._iso_from_ms(CLOSE_TS_MS)
    assert parsed == CLOSE_ISO
    # An epoch given in seconds is still read correctly, in case the unit changes.
    assert sa_access._iso_from_ms(CLOSE_TS_MS / 1000) == CLOSE_ISO


def test_extended_hours_block_is_shaped():
    shaped = shape_quote(_payload(), requested="AAPL")
    extended = shaped["extended_hours"]
    assert shaped["has_extended_hours"] is True
    assert extended["session"] == "Pre-market"
    assert extended["price"] == pytest.approx(344.39)
    assert extended["change_percent"] == pytest.approx(0.59)
    assert extended["volume"] == pytest.approx(97129)
    # ``epd`` repeats the extended price (measured identical on every symbol),
    # so it must never be read as the baseline. The extended change is measured
    # against the regular session price, ``p``: ``ep + ec == p`` on live data.
    assert extended["previous_close"] == pytest.approx(342.37)
    assert pytest.approx(shaped["price"]) == extended["price"] - extended["change"]
    # ``ets`` is milliseconds too.
    assert extended["price_timestamp"].startswith("2026-11-09T")


def test_extended_baseline_is_the_regular_price_not_the_repeated_one():
    """``epd`` duplicating ``ep`` is the same trap as ``pd`` duplicating ``p``."""
    shaped = shape_quote(
        _payload(ep=104.0, epd=104.0, ec=4.0, ecp=3.85, p=100.0),
        requested="AAPL",
    )
    extended = shaped["extended_hours"]
    assert extended["previous_close"] == pytest.approx(100.0)
    assert extended["previous_close"] != extended["price"]


def test_no_extended_block_when_the_flag_is_false():
    shaped = shape_quote(_payload(e=False), requested="AAPL")
    assert shaped["extended_hours"] is None
    assert shaped["has_extended_hours"] is False


def test_change_percent_is_derived_when_only_the_absolute_change_arrives():
    shaped = shape_quote(_payload(cp=None, c=-1.8, cl=344.17), requested="AAPL")
    assert shaped["change_percent"] == pytest.approx(-0.523, rel=1e-3)


def test_missing_price_is_no_data_not_a_zero():
    with pytest.raises(NoDataError):
        shape_quote({"status": 200, "data": {"symbol": "AAPL"}}, requested="AAPL")
    with pytest.raises(NoDataError):
        shape_quote({"status": 404}, requested="AAPL")


# ── resolution ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query,expected",
    [
        ("AAPL", "aapl"),
        ("aapl", "aapl"),
        ("NASDAQ:AAPL", "aapl"),
        ("BRK.B", "brk.b"),
        # Yahoo's spelling of the share class, converted to the site's own.
        ("BRK-B", "brk.b"),
        ("SPY", "spy"),
    ],
)
def test_to_stockanalysis_is_mechanical(query, expected):
    assert to_stockanalysis(query) == expected


@pytest.mark.parametrize(
    "query,expected_words",
    [
        ("SPX", "indices"),
        ("^GSPC", "indices"),
        ("DJI", "indices"),
        ("VIX", "indices"),
        # Spot gold ends in ``USD`` exactly like a coin; it must not be told
        # "no crypto", which is a different boundary.
        ("XAUUSD", "commodity"),
        ("XAGUSD", "commodity"),
        ("EURUSD", "FX"),
        ("USDJPY", "FX"),
        ("GBPEUR", "FX"),
        ("BTC-USD", "crypto"),
        ("BTCUSD", "crypto"),
        ("ETHUSDT", "crypto"),
        ("VOD.L", "US listings"),
    ],
)
def test_instruments_the_quote_api_does_not_carry_are_not_sent(
    query, expected_words
):
    """A wrong guess would 404 six layers later; the resolution says it up front.

    The note must also name the boundary, so a caller reading ``resolutions``
    learns *why* StockAnalysis was not asked rather than only that it was not.
    """
    resolution = resolve_sa(query)
    assert not resolution.found
    assert resolution.note
    assert expected_words in resolution.note


def test_asset_class_index_is_reported_without_looking_at_the_symbol():
    resolution = resolve_sa("SPY-ish", asset_class="index")
    assert not resolution.found
    assert "indices" in resolution.note.lower()


def test_resolve_sa_marks_mechanical_resolution():
    resolution = resolve_sa("AAPL")
    assert resolution.found
    assert resolution.symbol == "aapl"
    assert resolution.method == "mechanical"
    assert resolution.provider == "SA"


@pytest.mark.parametrize("query", ["BRK.B", "BRK.A", "BF.B"])
def test_a_domestic_share_class_is_not_a_foreign_suffix(query):
    """``BRK.B`` is Berkshire, ``VOD.L`` is Vodafone London.

    Both are ``TICKER.SUFFIX``; treating the first as a foreign listing would
    silently drop every dual-class US name from the comparison, which is a
    coverage hole nothing in the response would explain.
    """
    resolution = resolve_sa(query)
    assert resolution.found
    assert resolution.symbol == query.lower()


@pytest.mark.parametrize("query", ["VOD.L", "SHOP.TO", "NESN.SW", "THYAO.IS"])
def test_a_foreign_listing_is_not_carried(query):
    resolution = resolve_sa(query)
    assert not resolution.found
    assert "US listings only" in resolution.note


# ── transport ────────────────────────────────────────────────────────────────


class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Client:
    """Minimal stand-in for the pooled ``httpx.AsyncClient`` ``sa_access`` uses."""

    def __init__(self, response):
        self.response = response
        self.urls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, **_kwargs):
        self.urls.append(url)
        return self.response


def _patch_transport(monkeypatch, response, real_fetch):
    """Route the real ``_fetch`` at a fake HTTP client.

    The autouse network guard replaces ``_fetch`` itself, so the real one is
    handed back here by the ``_no_stockanalysis_network`` fixture; only the
    pooled client underneath it is faked.
    """
    client = _Client(response)

    def factory(*_args, **_kwargs):
        return client

    monkeypatch.setattr(sa_access, "_fetch", real_fetch)
    monkeypatch.setattr(sa_access, "shared_client", factory)
    sa_access.limiter("SA").cache_clear()
    return client


@pytest.mark.asyncio
async def test_quote_hits_the_quote_route_for_the_slug(
    monkeypatch, _no_stockanalysis_network
):
    client = _patch_transport(
        monkeypatch, _Response(200, _payload()), _no_stockanalysis_network
    )
    shaped = await sa_access.quote("NASDAQ:AAPL")
    assert client.urls == ["https://stockanalysis.com/api/quotes/s/aapl"]
    assert shaped["price"] == pytest.approx(342.37)


@pytest.mark.asyncio
async def test_404_is_no_data_not_a_provider_failure(
    monkeypatch, _no_stockanalysis_network
):
    _patch_transport(
        monkeypatch, _Response(404, {"status": 404}), _no_stockanalysis_network
    )
    with pytest.raises(NoDataError):
        await sa_access.quote("zzzzzz")


@pytest.mark.asyncio
async def test_400_is_no_data(monkeypatch, _no_stockanalysis_network):
    _patch_transport(
        monkeypatch, _Response(400, {"status": 400}), _no_stockanalysis_network
    )
    with pytest.raises(NoDataError):
        await sa_access.quote("spx")


@pytest.mark.asyncio
async def test_403_is_a_stated_upstream_block(
    monkeypatch, _no_stockanalysis_network
):
    _patch_transport(
        monkeypatch, _Response(403, text="blocked"), _no_stockanalysis_network
    )
    with pytest.raises(ProviderError) as caught:
        await sa_access.quote("AAPL")
    assert caught.value.code == "UPSTREAM_BLOCKED"


@pytest.mark.asyncio
async def test_500_is_an_upstream_error(monkeypatch, _no_stockanalysis_network):
    _patch_transport(
        monkeypatch, _Response(503, text="down"), _no_stockanalysis_network
    )
    with pytest.raises(ProviderError) as caught:
        await sa_access.quote("AAPL")
    assert caught.value.code == "UPSTREAM_ERROR"


@pytest.mark.asyncio
async def test_non_json_is_schema_drift(monkeypatch, _no_stockanalysis_network):
    _patch_transport(
        monkeypatch, _Response(200, None, text="<html>"), _no_stockanalysis_network
    )
    with pytest.raises(ProviderError) as caught:
        await sa_access.quote("AAPL")
    assert caught.value.code == "SCHEMA_DRIFT"
