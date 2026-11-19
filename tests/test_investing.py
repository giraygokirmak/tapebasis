"""Hermetic Investing.com identity, quote, merge and direct-tool contracts."""
from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from tapebasis import investing_access, tools_investing, tools_market
from tapebasis.investing_access import (
    choose_instrument,
    instrument_identity,
    shape_quote,
)
from tapebasis.providers_state import NoDataError, ProviderError
from tapebasis.ratelimit import RateLimited
from tapebasis.sessions import live_print
from tapebasis.symbols import resolve_investing
from tests.test_tools_merge import fake_providers


def _search_row(symbol="NVDA", instrument_id=6497, **overrides):
    """Return one complete raw search listing, with no guessed quote path."""
    row = {
        "id": instrument_id,
        "symbol": symbol,
        "display_symbol": symbol,
        "exchange_short_name": "NASDAQ",
        "currency_code": "USD",
        "client_type": "stock",
        "type": "equities",
        "link": "/equities/nvidia-corp",
        "long_name": "NVIDIA Corporation",
        "parent_id": 0,
    }
    row.update(overrides)
    return row


def _state(symbol="NVDA", instrument_id=6497, **overrides):
    """Return a compact observed equity/ETF SSR shape for decoder tests."""
    kind = "etf" if instrument_id == 525 else "equity"
    instrument = {
        "base": {
            "id": instrument_id,
            "type": kind,
            "path": "/etfs/spdr-sp-500" if kind == "etf" else "/equities/nvidia-corp",
        },
        "name": {"symbol": symbol, "fullName": "NVIDIA Corporation"},
        "exchange": {"exchange": "NASDAQ" if kind != "etf" else "NYSE Arca"},
        "price": {
            "currency": "USD",
            "last": 150.96,
            "change": -4.5,
            "changePcr": -2.89,
            "lastClose": 150.96,
            "lastUpdateTime": 1795118400000,
            "open": 151.0,
            "high": 152.0,
            "low": 150.0,
            "fiftyTwoWeekHigh": 212.0,
            "fiftyTwoWeekLow": 100.0,
            "volume": 123456,
            "showExtendedHours": "Aftermarket",
            "afterHoursPrice": 151.0,
            "afterHoursChange": 0.04,
            "afterHoursChangePercent": 0.03,
            "extendedUpdateTimeUnix": 1795123200000,
        },
        "fundamental": {"marketCapRaw": 3690000000000},
    }
    state = {f"{kind}Store": {"instrumentId": instrument_id, "instrument": instrument}}
    for key, value in overrides.items():
        if key == "price":
            instrument["price"].update(value)
        else:
            state[key] = value
    return state


def _identity(symbol="NVDA", instrument_id=6497, **overrides):
    """Return a verified search identity supplied by Investing, not a slug guess."""
    identity = instrument_identity(_search_row(symbol, instrument_id, **overrides))
    assert identity is not None
    return identity


def _html(state):
    """Return a next-data script carrying a complete provider state."""
    payload = json.dumps({"props": {"pageProps": {"state": state}}})
    return f'<html><script id="__NEXT_DATA__">{payload}</script></html>'


class _Response:
    """One local HTTP response for the TLS-aware access boundary."""

    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        """Decode the stored payload, or imitate an invalid JSON body."""
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Upstream:
    """Record upstream calls while serving only search and quote fixtures."""

    def __init__(self, search_response, path="/equities/nvidia-corp", html=None):
        self.search_response = search_response
        self.path = path
        self.html = html or _html(_state())
        self.calls = []

    async def get(self, url, **_kwargs):
        """Return the local response and never construct a listing slug."""
        self.calls.append(url)
        if "instruments/search" in url:
            if isinstance(self.search_response, Exception):
                raise self.search_response
            return self.search_response
        assert url == f"https://www.investing.com{self.path}"
        return _Response(200, text=self.html)


def _install_upstream(monkeypatch, upstream):
    """Route both provider endpoints to one local fake with no pacing delay."""
    monkeypatch.setattr(investing_access, "_session", lambda: upstream)
    paced = SimpleNamespace(
        cache_get=lambda _key, _ttl: None,
        cache_set=lambda _key, _value: None,
        note_rate_limited=lambda: None,
    )
    monkeypatch.setattr(investing_access, "limiter", lambda _provider: paced)

    async def immediate(_provider, function, **_kwargs):
        """Run the fake request without sleeping in a hermetic test."""
        return await function()

    monkeypatch.setattr(investing_access, "call", immediate)


def test_identity_and_choice_reject_ambiguous_and_foreign_listings():
    """Bare symbols accept one supported primary, never the first same-symbol row."""
    primary = _identity()
    assert instrument_identity(primary) == primary
    assert primary["instrument_id"] == 6497
    assert primary["link"] == "/equities/nvidia-corp"

    listings = [
        _search_row("MSFT", 252, parent_id=0),
        _search_row(
            "MSFT", 1226440, parent_id=252, exchange_short_name="Toronto",
            currency_code="CAD", link="/equities/microsoft-corp-cad",
        ),
    ]
    chosen = choose_instrument(listings, "MSFT")
    assert chosen["instrument_id"] == 252
    assert chosen["currency"] == "USD"
    assert choose_instrument(
        [_search_row("MSFT", 252), _search_row(
            "MSFT", 1226440, parent_id=0, exchange_short_name="Toronto",
            link="/equities/microsoft-corp-cad",
        )],
        "MSFT",
    ) is None
    assert choose_instrument(listings, "MSFT", exchange="Toronto")["instrument_id"] == 1226440

    assert choose_instrument([_identity()], "NVDA", asset_class="equity")["instrument_id"] == 6497
    unsupported = _search_row("SPX", 166, client_type="index", type="indices")
    assert instrument_identity(unsupported) is None
    assert choose_instrument([unsupported], "SPX") is None


@pytest.mark.asyncio
async def test_search_follows_cursor_before_matching_a_later_primary(monkeypatch):
    """Cursor-linked listings are all considered before exact identity selection."""
    responses = [
        _Response(200, payload={"instruments": [], "next_page_cursor": "next"}),
        _Response(200, payload={"instruments": [_search_row()], "next_page_cursor": None}),
    ]
    upstream = _Upstream(responses[0])
    upstream.get = lambda url, **_kwargs: _paged_get(upstream, responses, url)
    _install_upstream(monkeypatch, upstream)
    rows = await investing_access.search("NVDA")
    assert rows == [_search_row()]
    assert choose_instrument(rows, "NVDA")["instrument_id"] == 6497
    assert len(upstream.calls) == 2
    cursor_query = parse_qs(urlsplit(upstream.calls[1]).query)
    assert cursor_query == {"domain_id": ["1"], "query": ["NVDA"], "cursor": ["next"]}


async def _paged_get(upstream, responses, url):
    """Return the next local search page without external transport."""
    upstream.calls.append(url)
    return responses[len(upstream.calls) - 1]


def test_nvda_separates_regular_extended_and_excludes_unverified_last_close():
    """The real shaper retains independent clocks without calling lastClose prevClose."""
    shaped = shape_quote(_state(), _identity())
    assert shaped["instrument_id"] == 6497
    assert shaped["price"] == 150.96
    assert shaped["previous_close"] is None
    assert shaped["investing_last_close_value"] == 150.96
    assert "lastClose" in shaped["investing_previous_close_excluded"]
    assert shaped["price_timestamp"] == "2026-11-19T20:00:00Z"
    assert shaped["extended_hours"]["price"] == 151.0
    assert shaped["extended_hours"]["price_timestamp"] == "2026-11-19T21:20:00Z"
    live = live_print("INVESTING", shaped)
    assert live["price"] == 151.0
    assert live["session"] == "post_market"
    assert live["reference_close"] == 150.96


def test_etf_uses_explicit_prev_close_and_page_class_mismatch_is_drift():
    """ETF statistics can provide a verified baseline, while wrong pages cannot."""
    identity = _identity(
        "SPY", 525, type="etf", client_type="etf",
        link="/etfs/spdr-sp-500", exchange_short_name="NYSE Arca",
    )
    state = _state("SPY", 525, price={"afterHoursPrice": None, "showExtendedHours": ""})
    state["etfStore"]["instrument"]["keyStatistics"] = {"prevClose": 149.1}
    shaped = shape_quote(state, identity)
    assert shaped["asset_class"] == "etf"
    assert shaped["previous_close"] == 149.1
    assert shaped["market_cap"] == 3690000000000

    state["etfStore"]["instrument"]["base"]["path"] = "/equities/wrong-listing"
    with pytest.raises(ProviderError) as error:
        shape_quote(state, identity)
    assert error.value.code == "SCHEMA_DRIFT"
    assert "path" in error.value.message


@pytest.mark.parametrize("field,value", [
    ("symbol", "AAPL"),
    ("exchange", "NYSE"),
    ("currency", "CAD"),
    ("instrument_id", 6408),
])
def test_page_identity_mismatch_is_never_joined(field, value):
    """An intact quote for the requested symbol cannot redeem a wrong identity."""
    state = _state()
    instrument = state["equityStore"]["instrument"]
    if field == "symbol":
        instrument["name"]["symbol"] = value
    elif field == "exchange":
        instrument["exchange"]["exchange"] = value
    elif field == "currency":
        instrument["price"]["currency"] = value
    else:
        instrument["base"]["id"] = value
    with pytest.raises(ProviderError) as error:
        shape_quote(state, _identity())
    assert error.value.code == "SCHEMA_DRIFT"
    assert error.value.to_dict()["detail"]["expected_identity"]["instrument_id"] == 6497


@pytest.mark.asyncio
async def test_native_search_and_page_envelope_preserve_verified_provenance(monkeypatch):
    """The direct tool asks native search first and labels only Investing readings."""
    upstream = _Upstream(None, html=_html(_state(
        forecastStore={"forecast": {
            "instrument_id": 6497, "target_price_consensus_mean": 200,
            "number_of_estimates": 62, "number_of_analysts_buy": 45,
            "number_of_analysts_hold": 15, "number_of_analysts_sell": 2,
        }},
    )))

    async def search(query):
        assert query == "NVDA"
        return [_search_row()]

    async def fetch_html(path, _cache_key):
        upstream.calls.append(path)
        return upstream.html

    monkeypatch.setattr(investing_access, "search", search)
    monkeypatch.setattr(investing_access, "_fetch_html", fetch_html)
    from tapebasis import symbols
    symbols.clear_cache()
    result = await tools_investing.investing_quote("NVDA")
    assert result["data_provider"] == "INVESTING"
    assert result["verification"] == "SINGLE_SOURCE"
    assert result["providers_answered"] == ["INVESTING"]
    assert result["cross_checked"] is False
    assert result["sources"]["INVESTING"].endswith("/equities/nvidia-corp")
    assert result["data"]["instrument_id"] == 6497
    assert result["data"]["investing_analyst"]["rating_analyst_count"] == 62
    assert result["fields"]["investing_analyst"] == {
        "source": "INVESTING", "supplied": ["INVESTING"], "compared": [],
        "agreement": None,
    }
    assert upstream.calls == ["https://www.investing.com/equities/nvidia-corp"]


@pytest.mark.asyncio
async def test_direct_tool_reports_resolution_miss_without_another_provider(monkeypatch):
    """Ambiguity and unsupported identities are NONE/NO_DATA, not substituted data."""
    from tapebasis import symbols
    symbols.clear_cache()

    async def search(_query):
        return [_search_row("MSFT", 252), _search_row(
            "MSFT", 1226440, exchange_short_name="Toronto", link="/equities/microsoft-cad",
        )]

    monkeypatch.setattr(investing_access, "search", search)
    result = await tools_investing.investing_quote("MSFT")
    assert result["data"] is None
    assert result["data_provider"] == "NONE"
    assert result["providers_answered"] == []
    assert result["cross_checked"] is False
    assert result["errors"][0]["provider"] == "INVESTING"
    assert result["errors"][0]["code"] == "NO_DATA"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [
    (403, "UPSTREAM_BLOCKED"),
    (429, "RATE_LIMITED"),
    (503, "UPSTREAM_ERROR"),
])
async def test_search_http_failures_keep_distinct_provider_codes(monkeypatch, status, code):
    """A robot wall or rate limit is a failure, never an empty search."""
    upstream = _Upstream(_Response(status, payload={}))
    _install_upstream(monkeypatch, upstream)
    with pytest.raises((ProviderError, RateLimited)) as error:
        await investing_access.search("NVDA")
    if isinstance(error.value, RateLimited):
        assert code == "RATE_LIMITED"
    else:
        assert error.value.code == code
    query = parse_qs(urlsplit(upstream.calls[0]).query)
    assert query == {"domain_id": ["1"], "query": ["NVDA"]}


@pytest.mark.asyncio
async def test_search_schema_drift_and_transport_failure_are_typed(monkeypatch):
    """Invalid payloads and curl errors have stable error codes."""
    _install_upstream(monkeypatch, _Upstream(_Response(200, payload={"quotes": []})))
    with pytest.raises(ProviderError) as drift:
        await investing_access.search("NVDA")
    assert drift.value.code == "SCHEMA_DRIFT"

    _install_upstream(monkeypatch, _Upstream(RuntimeError("connection reset")))
    with pytest.raises(ProviderError) as transport:
        await investing_access.search("NVDA")
    assert transport.value.code == "UPSTREAM_ERROR"


@pytest.mark.asyncio
async def test_exploration_quote_uses_exact_verified_listing(monkeypatch):
    """Facade resolution preserves native id, class, exchange, currency and path."""
    async def search(_query):
        return [_search_row(), _search_row("NVDA", 6408, parent_id=0)]

    monkeypatch.setattr(investing_access, "search", search)
    ambiguous = await resolve_investing("NVDA")
    assert not ambiguous.found

    async def one(_query):
        return [_search_row()]

    monkeypatch.setattr(investing_access, "search", one)
    found = await resolve_investing("NVDA")
    assert found.symbol == "6497"
    assert found.native["exchange"] == "NASDAQ"
    assert found.native["currency"] == "USD"
    assert found.native["link"] == "/equities/nvidia-corp"


def test_extended_timestamp_does_not_borrow_regular_time():
    """An undated extended print cannot paradoxically be the freshest fresh print."""
    undated = _state(price={"extendedUpdateTimeUnix": None})
    shaped = shape_quote(undated, _identity())
    assert shaped["investing_extended_sessions"]["Aftermarket"]["price_timestamp"] is None
    live = live_print("INVESTING", shaped)
    assert live["price"] == 151.0
    assert live["timestamp"] is None
    assert live["session"] == "post_market"


def _aapl_investing_quote():
    """Return one independently shaped AAPL listing for merge assertions."""
    return {
        "symbol": "AAPL", "instrument_id": 6408, "asset_class": "stock",
        "exchange": "NASDAQ", "currency": "USD", "price": 331.9,
        "change_percent": -1.9, "previous_close": None,
        "day_open": 338.1, "day_high": 338.2, "day_low": 330.5,
        "week_52_high": 351.73, "week_52_low": 243.42,
        "volume": 63160515, "market_cap": 4900000000000, "pe_ratio": 36.5,
        "price_timestamp": "2026-11-03T21:00:01+00:00",
        "investing_last_close_value": 333,
        "investing_technical_1d": {"summary": {"label": "Buy", "score": 1}},
        "investing_analyst": {
            "price_target_average": 360, "price_target_estimate_count": 48,
            "rating_analyst_count": 50,
            "rating_distribution": {"buy": 30, "hold": 15, "sell": 5},
            "rating_distribution_method": "investing_forecast_store_buckets",
        },
    }


@pytest.mark.asyncio
async def test_stock_quote_counts_investing_and_keeps_extras_single_source(fake_providers):
    """Shared prices compare while Investing-only populations and models stay named."""
    from tests.conftest import CLOSE_EPOCH, CLOSE_ISO
    from tapebasis.investing_access import _timestamp
    assert _timestamp(CLOSE_EPOCH * 1000 + 1000) == "2026-11-03T21:00:02Z"
    assert _timestamp(CLOSE_EPOCH * 1000) == CLOSE_ISO.replace("+00:00", "Z")

    fake_providers["iw"] = _aapl_investing_quote()
    result = await tools_market.stock_quote("AAPL")
    assert result["data_provider"] == "PARTIAL"
    assert result["providers_answered"] == [
        "TRADINGVIEW", "FINVIZ", "YAHOO", "INVESTING",
    ]
    price = next(row for row in result["comparisons"] if row["field"] == "price")
    assert price["values"]["INVESTING"] == 331.9
    provenance = result["fields"]["investing_technical_1d"]
    assert provenance == {
        "source": "INVESTING", "supplied": ["INVESTING"], "compared": [],
        "agreement": None,
    }
    assert result["data"]["investing_rating_analyst_count"] == 50
    assert result["fields"]["rating_analyst_count"]["supplied"] == ["TRADINGVIEW"]
    assert result["analyst_targets"]["INVESTING"]["rating_analyst_count"] == 50
    assert result["fields"]["investing_rating_analyst_count"]["supplied"] == ["INVESTING"]
    assert not any(row["field"] == "price_target_average" and "INVESTING" in row["values"]
                   for row in result["comparisons"])
    assert "previous_close" in result["comparisons"][2]["field"]
    assert "INVESTING" not in next(
        row["values"] for row in result["comparisons"] if row["field"] == "previous_close"
    )
    assert all(row["match"] is None for row in result["comparisons"]
               if row["field"] == "market_cap")


@pytest.mark.asyncio
async def test_investing_resolution_error_keeps_other_quotes_visible(
    monkeypatch, fake_providers,
):
    """HTTP refusal while resolving is one failed leg, not a collapsed fan-out."""
    original = tools_market.resolve

    async def resolve(query, provider, **kwargs):
        if provider == "INVESTING":
            raise ProviderError("INVESTING", "search HTTP 403", code="UPSTREAM_BLOCKED")
        return await original(query, provider, **kwargs)

    monkeypatch.setattr(tools_market, "resolve", resolve)
    result = await tools_market.stock_quote("AAPL")
    assert result["data_provider"] == "PARTIAL"
    assert result["data"]["price"] == 331.9
    error = next(error for error in result["errors"] if error["provider"] == "INVESTING")
    assert error["code"] == "UPSTREAM_BLOCKED"
    assert result["resolutions"]["INVESTING"]["error"]["code"] == "UPSTREAM_BLOCKED"


@pytest.mark.asyncio
async def test_stock_prices_keeps_verified_investing_alongside_other_rows(fake_providers):
    """The batch's ordinary readings carry the same identity and independent extras."""
    fake_providers["iw"] = _aapl_investing_quote()
    result = await tools_market.stock_prices("AAPL")
    row = result["data"][0]
    assert row["providers_answered"] == [
        "TRADINGVIEW", "FINVIZ", "YAHOO", "INVESTING",
    ]
    assert row["investing_instrument_id"] == 6408
    assert row["fields"]["investing_instrument_id"] == {
        "source": "INVESTING", "supplied": ["INVESTING"], "compared": [],
        "agreement": None,
    }
    assert row["comparisons"]["price"]["values"]["INVESTING"] == 331.9
