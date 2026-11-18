"""Hermetic contract tests for the isolated, authenticated Equibles tools."""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from tapebasis import eq_access, tools_equibles
from tapebasis.providers_state import NoDataError, ProviderError


@pytest.fixture(autouse=True)
def _unconfigured_equibles(monkeypatch):
    """Keep every test keyless unless it explicitly exercises configuration."""
    monkeypatch.delenv("TAPEBASIS_EQUIBLES_API_KEY", raising=False)
    monkeypatch.delenv("TAPEBASIS_EQUIBLES_ENTITLEMENT", raising=False)
    from tapebasis import ratelimit

    paced = ratelimit.limiter("EQUIBLES")
    original_inflight = paced.max_inflight
    original_interval = paced.min_interval
    paced.cache_clear()
    paced.equibles_blocked_until = 0.0
    paced.equibles_quota = {}
    yield
    paced.max_inflight = original_inflight
    paced.min_interval = original_interval


def _client(handler):
    """Return a fake pooled client whose ``get`` is a plain callable."""
    return type("Client", (), {"get": staticmethod(handler)})()


def _no_call(*_args, **_kwargs):
    raise AssertionError("transport must not be reached")


def test_equibles_is_a_provider_but_never_a_market_fanout_leg():
    """A narrow licensed provider must not silently join live price arbitration."""
    from tapebasis import tools_market
    from tapebasis.providers_state import (
        DataProvider,
        PROVIDER_MEANING,
        PROVIDER_ORDER,
        RECONCILIATION_PROVIDER_ORDER,
    )

    assert DataProvider.EQUIBLES.value == "EQUIBLES"
    assert "EQUIBLES" not in tools_market.ALL_PROVIDERS
    assert "EQUIBLES" not in PROVIDER_ORDER
    # Capability adapters may reconcile it explicitly; the general market and
    # health fan-out lists stay free of it either way.
    assert RECONCILIATION_PROVIDER_ORDER == (*PROVIDER_ORDER, "EQUIBLES")
    assert "single-source" in PROVIDER_MEANING[DataProvider.EQUIBLES]


@pytest.mark.parametrize(
    "query,expected",
    [("NVDA", "NVDA"), (" NASDAQ:BRK.B ", "BRK-B"), ("NYSE:BRK-B", "BRK-B")],
)
def test_symbol_mapping_keeps_us_share_classes(query, expected):
    """Only mechanical US tickers are accepted, without another provider lookup."""
    assert eq_access.ticker_for(query) == expected


@pytest.mark.parametrize("query", ["EURUSD", "XETR:SIE", "", "BTC-USD/spot", "BTC-USD", "SPY500X"])
def test_non_us_or_unsafe_tickers_are_rejected(query):
    """An unsupported ticker is no data, never an unsafe concatenated URL."""
    with pytest.raises(NoDataError):
        eq_access.ticker_for(query)


def test_documented_route_allowlist_is_the_only_route_authority():
    """Only documented routes are callable; there is no local tier switch."""
    assert eq_access.route_allowed("/stocks/NVDA") is True
    assert eq_access.route_allowed("/securities/NVDA/options/summary") is True
    assert eq_access.route_allowed("/stocks/XTSE%3AWDO/prices") is True
    assert eq_access.route_allowed("/admin/keys") is False
    assert eq_access.route_allowed("/stocks/A%2FB/prices") is False
    for attack in (
        "/stocks/XTSE%253AWDO/prices", "/stocks/XTSE%3aWDO/prices%2fadmin",
        "/stocks/XTSE%3AWDO%5cadmin/prices", "/stocks/XTSE%3AWDO%3fadmin/prices",
        "/stocks/XTSE%3AWDO%23admin/prices",
    ):
        assert eq_access.route_allowed(attack) is False


@pytest.mark.asyncio
async def test_missing_key_is_not_configured_with_no_network(monkeypatch):
    """No key means a clear error before any API request."""
    monkeypatch.setattr(eq_access, "shared_client", _no_call)
    with pytest.raises(ProviderError) as caught:
        await eq_access.get("stocks/NVDA")
    assert caught.value.code == "NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_unknown_route_and_credential_query_reused(monkeypatch):
    """A caller cannot add an undocumented route, legacy flag or credential."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test_only")
    monkeypatch.setattr(eq_access, "shared_client", _no_call)
    with pytest.raises(ProviderError) as unknown:
        await eq_access.get("admin/keys")
    assert unknown.value.code == "PROVIDER_ERROR"
    with pytest.raises(ProviderError) as credential:
        await eq_access.get("securities/NVDA/options/summary", params={"apiKey": "bad"})
    assert credential.value.code == "PROVIDER_ERROR"
    with pytest.raises(ProviderError) as csv:
        await eq_access.get("securities/NVDA/prices", params={"format": "CSV"})
    assert csv.value.code == "PROVIDER_ERROR"


def test_legacy_entitlement_is_not_an_authority():
    """The removed environment switch cannot expose an entitlement API."""
    assert not hasattr(eq_access, "entitlement")
    assert not hasattr(eq_access, "has_enterprise_entitlement")


@pytest.mark.asyncio
async def test_keyless_paid_plan_tools_return_not_configured(monkeypatch):
    """No local entitlement denial is synthesized and no request is made."""
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("restricted transport was reached")

    monkeypatch.setattr(eq_access, "shared_client", forbidden)
    for function in (
        tools_equibles.stock_short_positioning,
        tools_equibles.stock_options_analytics,
        tools_equibles.stock_price_history,
    ):
        response = await function("NVDA")
        assert response["data_provider"] == "NONE"
        assert response["data"] is None
        assert response["access"]["status"] == "not_configured"
        assert response["access"]["status"] == "not_configured"
        assert "plan_required_datasets" not in response["access"]
        assert response["errors"][0]["code"] == "NOT_CONFIGURED"
        assert response["attribution"] == "Data by Equibles"
        assert "as_of" in response and "reporting_delay" in response
        assert not response["providers_answered"]


@pytest.mark.asyncio
async def test_standard_fundamentals_require_a_key_but_preserve_contract(monkeypatch):
    """An absent key is visible instead of substituting an existing provider."""
    response = await tools_equibles.stock_fundamentals(
        "NVDA", include_segments=False, include_debt=False, include_guidance=False,
    )
    assert response["data_provider"] == "NONE"
    assert response["errors"][0]["code"] == "NOT_CONFIGURED"
    assert response["access"]["status"] == "not_configured"
    assert response["access"]["configured"] is False
    assert response["comparison_policy"] == "no Equibles value is merged with another provider"
    # Every requested dataset still names its delay when no data arrived.
    assert set(response["reporting_delay"]) == {"profile", "financial_statement"}


@pytest.mark.asyncio
async def test_official_rest_transport_auth_paths_and_quota(monkeypatch):
    """Bearer auth stays in headers while path, query and quota are retained."""
    from tapebasis import ratelimit

    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test_only")
    ratelimit.limiter("EQUIBLES").cache_clear()
    captured = {}

    async def fake_client_get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(
            200,
            json={"ticker": "BRK-B", "cik": "12345", "cusip": "x"},
            headers={
                "X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "99",
                "X-RateLimit-Reset": "1794950400", "Retry-After": "20",
            },
        )

    async def fake_limiter_call(_provider, operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(eq_access, "call", fake_limiter_call)
    monkeypatch.setattr(eq_access, "shared_client", lambda *_args, **_kwargs: _client(fake_client_get))
    result = await eq_access.get("stocks/BRK-B", params={"limit": 5})
    assert result["cik"] == "12345"
    assert captured["url"] == "https://api.equibles.com/v1/stocks/BRK-B"
    assert captured["params"] == {"limit": 5}
    assert captured["headers"]["Authorization"] == "Bearer eq_test_only"
    assert "eq_test_only" not in captured["url"]
    quota = ratelimit.limiter("EQUIBLES").equibles_quota
    assert quota["remaining"] == 99
    assert quota["reset_at"].startswith("2026-")
    assert quota["reset_at"] != "1794950400"


@pytest.mark.asyncio
async def test_redirects_are_not_followed_and_cache_keys_hide_the_key(monkeypatch):
    """A bearer header never follows a redirect, and a rotated key misses cache."""
    from tapebasis import ratelimit

    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test_only")
    paced = ratelimit.limiter("EQUIBLES")
    paced.cache_clear()
    seen = {"calls": 0, "follow": None}

    async def fake_client_get(_url, **_kwargs):
        seen["calls"] += 1
        return httpx.Response(
            200, json={"ticker": "NVDA"},
            request=httpx.Request("GET", "https://api.equibles.com/v1/stocks/NVDA"),
        )

    async def fake_limiter_call(_provider, operation, **_kwargs):
        return await operation()

    def shared(_key, **kwargs):
        seen["follow"] = kwargs.get("follow_redirects")
        return _client(fake_client_get)

    monkeypatch.setattr(eq_access, "call", fake_limiter_call)
    monkeypatch.setattr(eq_access, "shared_client", shared)
    await eq_access.get("stocks/NVDA")
    assert seen["follow"] is False
    assert all("eq_test_only" not in key for key in paced._cache)
    # Same key: served from cache, no second request.
    await eq_access.get("stocks/NVDA")
    assert seen["calls"] == 1
    # Rotating the key must not serve the previous key's payload.
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_rotated_test")
    await eq_access.get("stocks/NVDA")
    assert seen["calls"] == 2


@pytest.mark.asyncio
async def test_redirect_response_is_refused(monkeypatch):
    """A 3xx answer becomes a sanitized error instead of a forwarded request."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")

    async def fake_client_get(_url, **_kwargs):
        return httpx.Response(
            302, headers={"Location": "https://example.test/steal"},
            request=httpx.Request("GET", "https://api.equibles.com/v1/stocks/NVDA"),
        )

    async def fake_limiter_call(_provider, operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(eq_access, "call", fake_limiter_call)
    monkeypatch.setattr(eq_access, "shared_client", lambda *_a, **_k: _client(fake_client_get))
    with pytest.raises(ProviderError) as caught:
        await eq_access.get("stocks/NVDA")
    assert caught.value.code == "UPSTREAM_ERROR"
    assert "credential" in caught.value.message


@pytest.mark.asyncio
async def test_a_daily_quota_429_spends_one_request_and_then_stops(monkeypatch):
    """The daily reset is never retried and later calls make no request."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")
    calls = {"count": 0}

    async def fake_client_get(_url, **_kwargs):
        calls["count"] += 1
        return httpx.Response(
            429,
            json={"error": {"message": "quota"}},
            headers={"Retry-After": "3600", "X-RateLimit-Remaining": "0"},
            request=httpx.Request("GET", "https://api.equibles.com/v1/stocks/NVDA"),
        )

    monkeypatch.setattr(eq_access, "shared_client", lambda *_a, **_k: _client(fake_client_get))
    with pytest.raises(ProviderError) as first:
        await eq_access.get("stocks/NVDA")
    assert first.value.code == "UPSTREAM_RATE_LIMIT"
    assert calls["count"] == 1
    with pytest.raises(ProviderError) as second:
        await eq_access.get("stocks/NVDA")
    assert second.value.code == "UPSTREAM_RATE_LIMIT"
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_concurrent_callers_cannot_cross_the_daily_quota_wall(monkeypatch):
    """A queued caller rechecks quota after the leading request sees its 429."""
    from tapebasis import ratelimit

    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")
    paced = ratelimit.limiter("EQUIBLES")
    paced.max_inflight = 2  # reproduce the audit's permissive configuration
    paced.min_interval = 0.0
    first_started = asyncio.Event()
    allow_first_to_finish = asyncio.Event()
    calls = {"count": 0}

    async def fake_client_get(_url, **_kwargs):
        calls["count"] += 1
        first_started.set()
        await allow_first_to_finish.wait()
        return httpx.Response(
            429,
            headers={"Retry-After": "3600"},
            request=httpx.Request("GET", "https://api.equibles.com/v1/stocks/NVDA"),
        )

    monkeypatch.setattr(eq_access, "shared_client", lambda *_a, **_k: _client(fake_client_get))
    first = asyncio.create_task(eq_access.get("stocks/NVDA"))
    await first_started.wait()
    second = asyncio.create_task(eq_access.get("stocks/NVDA"))
    await asyncio.sleep(0)
    allow_first_to_finish.set()
    results = await asyncio.gather(first, second, return_exceptions=True)
    assert calls["count"] == 1
    assert all(isinstance(result, ProviderError) for result in results)
    assert all(result.code == "UPSTREAM_RATE_LIMIT" for result in results)


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "NOT_CONFIGURED"), (403, "PLAN_REQUIRED"),
        (429, "UPSTREAM_RATE_LIMIT"), (500, "UPSTREAM_ERROR"),
        (503, "UPSTREAM_ERROR"),
    ],
)
@pytest.mark.asyncio
async def test_errors_are_stable_and_sanitized(monkeypatch, status, code):
    """A secret-bearing upstream message never escapes into tool diagnostics."""
    from tapebasis import ratelimit

    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_secret_test")
    ratelimit.limiter("EQUIBLES").cache_clear()

    async def fake_get(*_args, **_kwargs):
        return httpx.Response(
            status, json={"error": {"message": "eq_secret_test must not leak", "code": "bad"}},
            request=httpx.Request("GET", "https://api.equibles.com/v1/stocks/NVDA"),
        )

    async def fake_limiter_call(_provider, operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(eq_access, "call", fake_limiter_call)
    monkeypatch.setattr(eq_access, "shared_client", lambda *_a, **_k: _client(fake_get))
    with pytest.raises(ProviderError) as caught:
        await eq_access.get("stocks/NVDA")
    assert caught.value.code == code
    assert "eq_secret_test" not in str(caught.value)
    assert "eq_secret_test" not in json.dumps(caught.value.to_dict())


def test_freshness_uses_provider_dates_and_keeps_delay_explicit():
    """No local receipt timestamp can masquerade as a 13F observation date."""
    raw = {"data": [{"reportPeriodDate": "2026-09-30", "percentOfNetAssets": 4.2}]}
    freshness = eq_access.freshness_for({"fund_owners": raw})
    assert freshness["as_of"] == "2026-09-30T00:00:00+00:00"
    assert freshness["as_of_date_only"] is True
    assert freshness["datasets"]["fund_owners"]["as_of"] == "2026-09-30T00:00:00+00:00"
    assert "not when they became public" in freshness["note"]
    delayed = eq_access.freshness_for({"options_summary": {"delayed": True}}, delayed=True)
    assert delayed["delayed"] is True
    assert "indicative" in delayed["delay_status"]


def test_freshness_separates_observation_from_filing_publication():
    """Each legal dataset uses its own observation date, not the latest date."""
    snapshots = eq_access.freshness_for({
        "guidance": {"data": [{"filedDate": "2026-11-17"}]},
        "insider_transactions": {"data": [{
            "transactionDate": "2026-11-10", "filingDate": "2026-11-12",
        }]},
        "financial_statement": {"data": [{
            "periodEnd": "2026-09-30", "filedDate": "2026-11-02",
        }]},
    })
    assert snapshots["as_of"] == "2026-11-17T00:00:00+00:00"
    assert snapshots["datasets"]["insider_transactions"]["as_of"] == (
        "2026-11-10T00:00:00+00:00"
    )
    assert snapshots["datasets"]["insider_transactions"]["publication_at"] == (
        "2026-11-12T00:00:00+00:00"
    )
    assert snapshots["datasets"]["financial_statement"]["as_of"] == (
        "2026-09-30T00:00:00+00:00"
    )
    assert snapshots["datasets"]["financial_statement"]["publication_at"] == (
        "2026-11-02T00:00:00+00:00"
    )


def test_option_expiration_is_a_schedule_not_an_observation():
    """A future expiry must never become the block's as_of timestamp."""
    freshness = eq_access.freshness_for({
        "options_summary": {
            "expiration": "2030-01-18",
            "underlyingCloseDate": "2026-11-17",
            "openInterestDate": "2026-11-17",
        },
    })
    assert freshness["as_of"] == "2026-11-17T00:00:00+00:00"


@pytest.mark.asyncio
async def test_fundamentals_preserve_raw_blocks_and_filing_provenance(monkeypatch):
    """Source fields are not re-mapped or merged into Finviz-style fields."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")
    paths = []

    async def fake_get(fragment, *, params=None, enterprise=False):
        paths.append((fragment, params, enterprise))
        if fragment == "stocks/NVDA":
            return {"ticker": "NVDA", "cik": "1045810", "cusip": "67066G104"}
        if fragment.endswith("financial-statements/income"):
            return {
                "ticker": "NVDA", "fiscalYear": 2026, "fiscalPeriod": "FY",
                "data": [{
                    "lineItem": "Revenue", "value": 215940000000, "unit": "USD",
                    "periodEnd": "2026-01-25", "filedDate": "2026-02-25",
                    "accessionNumber": "0001045810-26-000010",
                }],
            }
        if fragment.endswith("revenue-breakdown"):
            return {"segments": {"members": []}, "consolidatedRevenue": [{"fiscalYear": 2026}]}
        if fragment.endswith("debt-profile"):
            return {"reportedBalances": [{"label": "Notes", "amount": 8500000000, "asOfDate": "2026-01-25"}]}
        if fragment.endswith("guidance"):
            return {"data": [{"metric": "Revenue", "low": 1000000000, "actual": 1100000000,
                              "actualVerdict": "above", "filedDate": "2026-11-17"}]}
        raise AssertionError(fragment)

    monkeypatch.setattr(eq_access, "get", fake_get)
    response = await tools_equibles.stock_fundamentals("NVDA")
    assert response["data_provider"] == "EQUIBLES"
    assert response["verification"] == "SINGLE_SOURCE"
    assert response["data"]["profile"]["cik"] == "1045810"
    assert response["data"]["financial_statement"]["data"][0]["accessionNumber"]
    assert response["data"]["guidance"]["data"][0]["actualVerdict"] == "above"
    assert response["comparisons"] == []
    assert response["fields"]["profile"]["supplied"] == ["EQUIBLES"]
    assert all(len(path) == 3 and path[2] is False for path in paths)
    assert len(paths) == 5
    assert set(response["reporting_delay"]) == {
        "profile", "financial_statement", "revenue_breakdown", "debt_profile", "guidance",
    }


@pytest.mark.asyncio
async def test_analyst_filter_bounds_and_raw_snapshot_are_kept(monkeypatch):
    """Analyst data is not replaced by a proprietary rating or summary."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")
    seen = {}

    async def fake_get(fragment, *, params=None, enterprise=False):
        seen.update(fragment=fragment, params=params, enterprise=enterprise)
        return {
            "capturedAt": "2026-11-17T12:00:00Z", "verifiedAt": "2026-11-17T12:01:00Z",
            "stale": False, "data": [{
                "publicationLabel": "Source consensus", "metric": "EPS",
                "period": "FY2028", "statistic": "mean", "value": "15.84",
                "analyst": "52 analysts",
            }],
        }

    monkeypatch.setattr(eq_access, "get", fake_get)
    response = await tools_equibles.stock_analyst_estimates(
        "NVDA", metric="EPS", limit=200, offset=-10,
    )
    assert seen["params"]["limit"] == 100
    assert seen["params"]["offset"] == 0
    assert response["data"]["analyst_estimates"]["data"][0]["value"] == "15.84"
    assert response["params_applied"]["analyst_estimates"]["limit"] == 100
    assert any("clamped" in warning for warning in response["warnings"])
    assert "not_entitled" not in json.dumps(response)


@pytest.mark.asyncio
async def test_invalid_dates_and_snapshot_ids_are_refused_before_transport(monkeypatch):
    """Malformed filters are a caller error, not an upstream request."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_ENTITLEMENT", "enterprise")
    monkeypatch.setattr(eq_access, "get", _no_call)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        await tools_equibles.stock_price_history("NVDA", start_date="11/17/2026")
    with pytest.raises(ValueError, match="expiration"):
        await tools_equibles.stock_options_analytics("NVDA", expiration="2026-13-40")
    with pytest.raises(ValueError, match="UUID"):
        await tools_equibles.stock_analyst_estimates("NVDA", snapshot_id="not-a-uuid")


@pytest.mark.asyncio
async def test_actual_plan_success_and_partial_403_are_explicit(monkeypatch):
    """A plan denial cannot hide another dataset's real successful response."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")

    async def fake_get(fragment, *, params=None, **kwargs):
        assert kwargs.get("cache", True) is True
        if "short-interest" in fragment:
            return {"data": [{"settlementDate": "2026-10-30", "shortPosition": 279600000,
                              "daysToCover": 2.8}]}
        raise ProviderError("EQUIBLES", "plan not included", code="PLAN_REQUIRED")

    monkeypatch.setattr(eq_access, "get", fake_get)
    response = await tools_equibles.stock_short_positioning("NVDA")
    assert response["data_provider"] == "EQUIBLES"
    assert response["data"]["short_interest"]["data"][0]["shortPosition"] == 279600000
    assert {error["code"] for error in response["errors"]} == {"PLAN_REQUIRED"}
    assert "short_volume" not in response["data"]
    assert response["access"]["status"] == "partially_available"
    assert set(response["access"]["plan_required_datasets"]) == {
        "short_volume", "fails_to_deliver", "off_exchange_volume",
    }
    assert response["data"]["attribution"] == "Data by Equibles"
    assert response["reporting_delay"]["short_interest"]["schedule"].startswith("published twice")
    assert response["reporting_delay"]["short_volume"]["source"] == "FINRA facility volume"


@pytest.mark.asyncio
async def test_auth_rejection_does_not_advertise_a_configured_account(monkeypatch):
    """A 401 is visible as an unusable key, not as working configuration."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")

    async def fake_get(*_args, **_kwargs):
        raise ProviderError("EQUIBLES", "rejected", code="NOT_CONFIGURED")

    monkeypatch.setattr(eq_access, "get", fake_get)
    response = await tools_equibles.stock_fundamentals(
        "NVDA", include_segments=False, include_debt=False, include_guidance=False,
    )
    assert response["data_provider"] == "NONE"
    assert response["access"]["configured"] is False
    assert response["access"]["status"] == "auth_rejected"
    assert set(response["reporting_delay"]) == {"profile", "financial_statement"}


@pytest.mark.asyncio
async def test_options_and_prices_use_their_restricted_routes(monkeypatch):
    """Restricted calculations and prices remain distinct from live quote tools."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_ENTITLEMENT", "enterprise")
    requested = []

    async def fake_get(fragment, *, params=None, **kwargs):
        requested.append((fragment, params, kwargs.get("cache", True)))
        if "options" in fragment:
            return {"underlyingCloseDate": "2026-11-17", "delayed": True,
                    "maxPainStrike": 155, "expectedMove": {"absolute": 5.2}}
        return {"currency": "USD", "data": [{"date": "2026-11-17", "open": 156.9,
                                           "close": 155.46, "adjustedClose": 155.46}]}

    monkeypatch.setattr(eq_access, "get", fake_get)
    options = await tools_equibles.stock_options_analytics("NVDA", max_expirations=30)
    prices = await tools_equibles.stock_price_history("NVDA", limit=600, interval="weekly")
    assert options["data"]["options_summary"]["maxPainStrike"] == 155
    assert options["freshness"]["delayed"] is True
    assert prices["data"]["price_history"]["data"][0]["adjustedClose"] == 155.46
    assert requested[-1][1]["limit"] == 500
    assert requested[1][1]["maxExpirations"] == 12
    assert all(row[2] for row in requested)


def test_the_transport_works_in_two_event_loops(monkeypatch):
    """No module-level asyncio primitive may bind the limiter to one loop."""
    from tapebasis import ratelimit

    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")
    paced = ratelimit.limiter("EQUIBLES")
    paced.min_interval = 0.0
    pace = {"count": 0}

    async def fake_client_get(_url, **_kwargs):
        pace["count"] += 1
        return httpx.Response(
            200, json={"ticker": "NVDA"},
            request=httpx.Request("GET", "https://api.equibles.com/v1/stocks/NVDA"),
        )

    monkeypatch.setattr(eq_access, "shared_client", lambda *_a, **_k: _client(fake_client_get))
    paced.cache_clear()
    asyncio.run(eq_access.get("stocks/NVDA"))
    paced.cache_clear()
    asyncio.run(eq_access.get("stocks/NVDA"))
    assert pace["count"] == 2
    assert not hasattr(eq_access, "_CACHE_LOCK")


@pytest.mark.asyncio
async def test_health_exposes_quota_reset_and_active_block(monkeypatch):
    """A real 429 becomes structured operational state without a health call."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")
    reset = int(time.time()) + 3600

    async def fake_client_get(_url, **_kwargs):
        return httpx.Response(
            429,
            headers={
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset),
            },
            request=httpx.Request("GET", "https://api.equibles.com/v1/stocks/NVDA"),
        )

    monkeypatch.setattr(eq_access, "shared_client", lambda *_a, **_k: _client(fake_client_get))
    with pytest.raises(ProviderError, match="quota"):
        await eq_access.get("stocks/NVDA")

    from tapebasis import tools_health
    from tapebasis import ratelimit

    snapshot = ratelimit.limiter("EQUIBLES").snapshot()
    assert snapshot["quota"]["daily_limit"] == 100
    assert snapshot["quota"]["remaining"] == 0
    assert snapshot["quota_blocked_until_epoch"] == reset
    assert snapshot["quota_block_active"] is True
    # Evaluate the report wrapper independently of unrelated network probes.
    class SummaryMonitor:
        results = {"equibles.api_key": object()}

        def ensure_started(self):
            return None

        async def run_once(self, **_kwargs):
            return {}

        def summary(self):
            return {
                "providers": {"EQUIBLES": "OK"}, "issues": [], "degraded": False,
                "rate_limits": {"EQUIBLES": snapshot},
            }

    monkeypatch.setattr(tools_health, "MONITOR", SummaryMonitor())
    report = await tools_health.tapebasis_health()
    assert report["data"]["rate_limits"]["EQUIBLES"] == snapshot
    assert any("quota is exhausted" in warning for warning in report["warnings"])


def test_excluded_scores_and_ai_brief_are_not_implemented_or_requested():
    """The chosen restriction is structural, not just an omission in documentation."""
    import inspect

    source = inspect.getsource(tools_equibles)
    assert all(name not in source for name in (
        "short-squeeze-scores", "insider-sentiment-scores", "ai-brief", "equibles-rating",
    ))
    assert not any("rating" in function.__name__ for function, _ in tools_equibles._TOOLS)
