"""Hermetic coverage and validation tests for every grouped Equibles route."""
from __future__ import annotations

import pytest

from tapebasis import eq_access, eq_catalog, tools_equibles_families as families
from tapebasis.providers_state import ProviderError


REQUIRED_VALUES = {
    "ticker": "NVDA",
    "exchange": "XTSE",
    "documentId": "123e4567-e89b-12d3-a456-426614174000",
    "eventId": "123e4567-e89b-12d3-a456-426614174100",
    "snapshotId": "123e4567-e89b-12d3-a456-426614174200",
    "startDate": "2026-01-01",
    "endDate": "2026-11-17",
    "expiration": "2026-12-18",
    "reportDate": "2026-09-30",
    "statement": "income",
    "concept": "Assets",
    "instrumentId": "123e4567-e89b-12d3-a456-426614174300",
    "contract": "NVDA261218C00150000",
    "marketCode": "088691",
    "seriesId": "CPIAUCSL",
    "symbol": "BTCUSD",
    "bucket": "top-buys",
    "phrase": "artificial intelligence",
    "index": "sp500",
    "cik": "1318605",
    "crd": 12345,
    "id": "123e4567-e89b-12d3-a456-426614174400",
    "reportId": "123e4567-e89b-12d3-a456-426614174500",
    "startLine": 1,
    "endLine": 100,
    "fiscalYear": 2026,
    "fiscalQuarter": 3,
    "query": "risk",
}


def _required_filters(parameters):
    """Return the smallest valid typed filter object for a route."""
    result = {}
    for name, item in parameters.items():
        if not item["required"]:
            continue
        assert name in REQUIRED_VALUES, f"add a deterministic required value for {name}"
        result[name] = REQUIRED_VALUES[name]
    return result


@pytest.fixture(autouse=True)
def _keyless(monkeypatch):
    """Keep all family tests keyless except explicit authenticated calls."""
    monkeypatch.delenv("TAPEBASIS_EQUIBLES_API_KEY", raising=False)
    monkeypatch.delenv("TAPEBASIS_EQUIBLES_ENTITLEMENT", raising=False)


def test_all_188_selected_routes_are_mapped_once_and_registered():
    """Every selected route is reachable through exactly one family and dataset."""
    functions = {function.__name__: function for function, _title in families._TOOLS}
    assert len(functions) == 14
    paths = []
    for family, datasets in eq_catalog.CATALOG.items():
        assert f"equibles_{family}" in functions
        assert len(datasets) == len(set(datasets))
        for dataset, entry in datasets.items():
            assert entry["name"] == dataset
            paths.append(entry["path"])
            route = eq_catalog.compile_call(family, dataset, _required_filters(entry["parameters"]))
            assert "{" not in route["path"] and "}" not in route["path"]
            assert eq_access.route_allowed(route["path"]), route
    assert len(paths) == 188
    assert len(set(paths)) == 188
    assert set(paths) == set(eq_access.ROUTES)


def test_every_documented_uuid_filter_rejects_malformed_values():
    """All official UUID path and query filters are enforced, not only required ones."""
    checked = set()
    for family, datasets in eq_catalog.CATALOG.items():
        for dataset, entry in datasets.items():
            for name, item in entry["parameters"].items():
                if item.get("format") != "uuid":
                    continue
                filters = _required_filters(entry["parameters"])
                filters[name] = "not-a-uuid"
                with pytest.raises(ValueError, match="UUID"):
                    eq_catalog.compile_call(family, dataset, filters)
                checked.add(name)
    assert checked == {"documentId", "eventId", "snapshotId", "memberId", "id", "reportId", "instrumentId"}


@pytest.mark.asyncio
async def test_each_route_invokes_exactly_one_authenticated_hermetic_get(monkeypatch):
    """All 188 wrappers each produce one real GET at the mocked HTTP boundary."""
    import httpx
    from tapebasis import ratelimit

    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")
    calls = []

    async def fake_get(url, *, params=None, headers=None, timeout=None, **_kwargs):
        calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        return httpx.Response(
            200, json={"route": url, "raw": True},
            request=httpx.Request("GET", url, params=params, headers=headers),
        )

    class Client:
        async def get(self, url, **kwargs):
            """Capture one request rather than contacting Equibles."""
            return await fake_get(url, **kwargs)

    async def one_attempt(_provider, operation, **kwargs):
        """Assert the transport explicitly disables retries."""
        assert kwargs["attempts"] == 0
        return await operation()

    paced = ratelimit.limiter("EQUIBLES")
    paced.cache_clear()
    paced.equibles_blocked_until = 0.0
    paced.equibles_quota = {}
    monkeypatch.setattr(eq_access, "call", one_attempt)
    monkeypatch.setattr(eq_access, "shared_client", lambda *_a, **_k: Client())
    for family, datasets in eq_catalog.CATALOG.items():
        function = getattr(families, f"equibles_{family}")
        for dataset, entry in datasets.items():
            expected = eq_catalog.compile_call(
                family, dataset, _required_filters(entry["parameters"]),
            )
            before = len(calls)
            before_cache = len(paced._cache)
            response = await function(dataset, _required_filters(entry["parameters"]))
            assert len(calls) == before + 1, (family, dataset, response.get("errors"))
            request = calls[-1]
            assert request["url"] == eq_access.source_url(expected["path"])
            assert request["params"] == expected["params"]
            assert request["headers"]["Authorization"] == "Bearer eq_test"
            assert request["headers"]["Accept"] == "application/json"
            assert "eq_test" not in request["url"]
            assert response["data_provider"] == "EQUIBLES"
            assert response["data"][dataset]["raw"] is True
            assert response["access"]["status"] == "configured"
            assert response["params_applied"][dataset] == expected["params"]
            expected_cached = 0 if entry["live"] else 1
            assert len(paced._cache) - before_cache == expected_cached, (family, dataset)
            for name in ("instrumentId", "reportId", "snapshotId", "memberId", "id"):
                if name in entry["parameters"] and entry["parameters"][name]["location"] == "path":
                    assert entry["parameters"][name]["format"] == "uuid"
    assert len(calls) == 188
    assert len({call["url"] for call in calls}) == 188
    expected_cached = sum(
        not entry["live"]
        for datasets in eq_catalog.CATALOG.values() for entry in datasets.values()
    )
    assert len(paced._cache) == expected_cached
    paced.cache_clear()


@pytest.mark.asyncio
async def test_no_key_means_no_transport_for_every_family(monkeypatch):
    """All grouped tools fail before transport without an API key."""
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("keyless Equibles transport must not be reached")

    monkeypatch.setattr(eq_access, "shared_client", forbidden)
    for function, _title in families._TOOLS:
        family = function.__name__.removeprefix("equibles_")
        dataset = next(iter(eq_catalog.CATALOG[family]))
        entry = eq_catalog.CATALOG[family][dataset]
        response = await function(dataset, _required_filters(entry["parameters"]))
        assert response["data_provider"] == "NONE"
        assert response["errors"][0]["code"] == "NOT_CONFIGURED"
        assert response["access"]["status"] == "not_configured"


@pytest.mark.asyncio
async def test_raw_options_chain_and_plan_required(monkeypatch):
    """Plus/Pro options remain raw JSON and a Free refusal is explicit."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")

    async def chain(path, *, params=None, cache=True):
        assert path == "/stocks/NVDA/options/chain"
        assert params == {"expiration": "2026-12-18"}
        return {"delayed": True, "options": [{"strike": 155, "bid": 2.1, "ask": 2.4}]}

    monkeypatch.setattr(eq_access, "get", chain)
    result = await families.equibles_options("chain", {
        "ticker": "NVDA", "expiration": "2026-12-18",
    })
    assert result["data"]["chain"]["options"][0]["strike"] == 155
    assert result["freshness"]["delayed"] is True

    async def denied(*_args, **_kwargs):
        raise ProviderError("EQUIBLES", "plan not included", code="PLAN_REQUIRED")

    monkeypatch.setattr(eq_access, "get", denied)
    result = await families.equibles_options("chain", {"ticker": "NVDA"})
    assert result["data_provider"] == "NONE"
    assert result["data"] is None
    assert result["errors"][0]["code"] == "PLAN_REQUIRED"
    assert result["access"]["status"] == "plan_required"
    assert result["access"]["plan_required_datasets"] == ["chain"]


@pytest.mark.asyncio
async def test_auth_rejection_and_single_dataset_partial_state(monkeypatch):
    """401 does not claim a configured account; 403 never becomes empty rows."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_bad")

    async def denied(*_args, **_kwargs):
        raise ProviderError("EQUIBLES", "rejected", code="NOT_CONFIGURED")

    monkeypatch.setattr(eq_access, "get", denied)
    result = await families.equibles_company("profile", {"ticker": "NVDA"})
    assert result["access"]["status"] == "auth_rejected"
    assert result["access"]["configured"] is False
    assert result["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filters,match",
    [
        ({}, "missing required"),
        ({"ticker": "NVDA", "notDocumented": 1}, "unsupported filters"),
        ({"ticker": "BRK/B"}, "single path segment"),
        ({"ticker": "../admin"}, "single path segment"),
        ({"ticker": "%2f..%2fadmin"}, "single path segment"),
        ({"ticker": "NVDA", "expiration": "11/17/2026"}, "YYYY-MM-DD"),
    ],
)
async def test_unknown_or_unsafe_chain_filters_do_not_reach_transport(
    monkeypatch, filters, match
):
    """Typed dataset/filter validation occurs before any transport access."""
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid filters must not reach transport")

    monkeypatch.setattr(eq_access, "get", forbidden)
    with pytest.raises(ValueError, match=match):
        await families.equibles_options("chain", filters)


@pytest.mark.asyncio
async def test_unknown_dataset_csv_and_query_text_rules(monkeypatch):
    """Search strings can contain slashes, but arbitrary paths and CSV cannot."""
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid requests must not reach transport")

    monkeypatch.setattr(eq_access, "get", forbidden)
    with pytest.raises(ValueError, match="dataset must"):
        await families.equibles_company("free-form-url", {"ticker": "NVDA"})
    with pytest.raises(ValueError, match="CSV"):
        await families.equibles_market_data("bars", {"ticker": "NVDA", "format": "CSV"})
    with pytest.raises(ValueError, match="unsupported filters"):
        await families.equibles_company("profile", {"ticker": "NVDA", "apiKey": "x"})
    search = eq_catalog.compile_call("filings", "filing_search", {"query": "risk / reward"})
    assert search["params"] == {"query": "risk / reward"}


@pytest.mark.asyncio
async def test_live_transcript_bypasses_cache_on_two_calls(monkeypatch):
    """Incremental live text cannot be reused through the general REST cache."""
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")
    caches = []

    async def live(*_args, **kwargs):
        caches.append(kwargs["cache"])
        return {"text": "opening remarks"}

    monkeypatch.setattr(eq_access, "get", live)
    datasets = eq_catalog.CATALOG["investor_events"]
    live_names = [name for name, entry in datasets.items() if entry["live"]]
    assert live_names
    dataset = live_names[0]
    filters = _required_filters(datasets[dataset]["parameters"])
    await families.equibles_investor_events(dataset, filters)
    await families.equibles_investor_events(dataset, filters)
    assert caches == [False, False]


def test_cache_false_disables_both_read_and_write_on_live_transcript(monkeypatch):
    """The transport itself does not reuse a previous response for live text."""
    import asyncio

    calls = []
    monkeypatch.setenv("TAPEBASIS_EQUIBLES_API_KEY", "eq_test")
    from tapebasis import ratelimit
    paced = ratelimit.limiter("EQUIBLES")
    paced.cache_clear()
    paced.equibles_blocked_until = 0.0
    paced.equibles_quota = {}

    import httpx

    class Client:
        async def get(self, url, **_kwargs):
            calls.append(url)
            return httpx.Response(
                200, json={"text": len(calls)},
                request=httpx.Request("GET", url),
            )

    async def scenario():
        monkeypatch.setattr(eq_access, "shared_client", lambda *_a, **_k: Client())
        paced.min_interval = 0.0
        path = "stocks/NVDA/earnings-calls/2026/3/live-transcript"
        first = await eq_access.get(path, cache=False)
        second = await eq_access.get(path, cache=False)
        assert first == {"text": 1}
        assert second == {"text": 2}
        assert len(calls) == 2
        paced.cache_clear()

    asyncio.run(scenario())
