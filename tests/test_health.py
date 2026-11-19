"""Tests for the upstream health monitor (mocked HTTP, no network)."""
from __future__ import annotations

import sys

import httpx
import pytest

from tapebasis import health
from tapebasis.providers_state import ProviderError
from tapebasis.health import (
    FINVIZ,
    INVESTING,
    TRADINGVIEW,
    STATUS_DOWN,
    STATUS_DRIFT,
    STATUS_OK,
    HealthMonitor,
    Probe,
    fingerprint,
    key_paths,
)


def test_key_paths_and_fingerprint_are_stable():
    payload = {"a": 1, "b": {"c": 2}, "d": [{"e": 3}]}
    paths = key_paths(payload)
    assert "a" in paths and "b.c" in paths and "d[].e" in paths
    assert fingerprint(paths) == fingerprint(list(reversed(paths)))


async def _noop(*_args, **_kwargs):
    return None


def _monitor(tmp_path, probes):
    import os

    os.environ["TAPEBASIS_HEALTH_STATE"] = str(tmp_path / "health.json")
    return HealthMonitor(probes)


@pytest.mark.asyncio
async def test_probe_ok_records_baseline(tmp_path, monkeypatch):
    monitor = _monitor(
        tmp_path,
        [
            Probe(
                id="p",
                provider=FINVIZ,
                description="d",
                url="https://example.test/api",
                required_keys=("value",),
            )
        ],
    )

    def handler(request):
        return httpx.Response(200, json={"value": 1})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(health.httpx, "AsyncClient", fake_client)
    results = await monitor.run_once(force=True)
    assert results["p"].status == STATUS_OK
    assert monitor.provider_status(FINVIZ) == STATUS_OK
    assert not monitor.degraded()


@pytest.mark.asyncio
async def test_missing_key_is_reported_as_drift(tmp_path, monkeypatch):
    monitor = _monitor(
        tmp_path,
        [
            Probe(
                id="p",
                provider=TRADINGVIEW,
                description="d",
                url="https://example.test/api",
                required_keys=("chart.result",),
            )
        ],
    )

    def handler(request):
        return httpx.Response(200, json={"something_else": True})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    monkeypatch.setattr(
        health.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )
    results = await monitor.run_once(force=True)
    assert results["p"].status == STATUS_DRIFT
    assert results["p"].drift
    assert monitor.degraded()
    assert "chart.result" in results["p"].missing


@pytest.mark.asyncio
async def test_shape_change_against_baseline_is_drift(tmp_path, monkeypatch):
    probe = Probe(
        id="p", provider=FINVIZ, description="d", url="https://example.test/api",
        required_keys=("value",),
    )
    monitor = _monitor(tmp_path, [probe])

    state = {"payload": {"value": 1, "extra": 2}}

    def handler(request):
        return httpx.Response(200, json=state["payload"])

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        health.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )

    await monitor.run_once(force=True)  # records baseline
    assert monitor.provider_status(FINVIZ) == STATUS_OK

    state["payload"] = {"value": 1, "renamed": 2}  # schema drift
    monitor2 = _monitor(tmp_path, [probe])  # new process, same state file
    results = await monitor2.run_once(force=True)
    assert results["p"].status == STATUS_DRIFT
    assert "shape changed" in results["p"].message


@pytest.mark.asyncio
async def test_http_500_is_down_not_drift(tmp_path, monkeypatch):
    monitor = _monitor(
        tmp_path,
        [Probe(id="p", provider=FINVIZ, description="d", url="https://example.test/api")],
    )

    def handler(request):
        return httpx.Response(503, text="unavailable")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        health.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )
    results = await monitor.run_once(force=True)
    assert results["p"].status == STATUS_DOWN
    assert results["p"].http_status == 503


@pytest.mark.asyncio
async def test_transport_error_is_down(tmp_path, monkeypatch):
    monitor = _monitor(
        tmp_path,
        [Probe(id="p", provider=FINVIZ, description="d", url="https://example.test/api")],
    )

    def handler(request):
        raise httpx.ConnectError("dns failure")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        health.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )
    results = await monitor.run_once(force=True)
    assert results["p"].status == STATUS_DOWN


def test_warnings_are_scoped_to_the_provider():
    monitor = HealthMonitor([])
    monitor.results = {
        "x": health.ProbeResult(
            id="x", provider=TRADINGVIEW, description="", url="",
            status=STATUS_DRIFT, message="changed",
        ),
        "y": health.ProbeResult(
            id="y", provider=FINVIZ, description="", url="", status=STATUS_OK,
        ),
    }
    assert monitor.warnings_for((FINVIZ,)) == []
    assert len(monitor.warnings_for((TRADINGVIEW,))) == 1
    # ``ALL`` means "every provider this call touched", so it must surface both.
    assert len(monitor.warnings_for(("ALL",))) == 1
    assert len(monitor.warnings_for(("ALL", FINVIZ))) == 1


def test_every_provider_has_its_own_probe():
    """Yahoo used to be probed under TRADINGVIEW; that hid a whole outage."""
    providers = {probe.provider for probe in health._probes()}
    assert providers == {
        TRADINGVIEW, FINVIZ, health.YAHOO, health.SA, health.EQUIBLES,
        INVESTING,
    }
    assert INVESTING not in health.PROVIDERS
    assert "BLOOMBERG" not in health.PROVIDERS
    assert INVESTING in health.MONITORED_PROVIDERS
    assert next(
        probe for probe in health._probes() if probe.provider == INVESTING
    ).url == "local:investing-quote"


def test_stockanalysis_probes_hit_stockanalysis_only():
    probes = [p for p in health._probes() if p.provider == health.SA]
    assert probes
    assert all("stockanalysis.com" in p.url for p in probes)


def test_tradingview_probes_hit_tradingview_not_yahoo():
    probes = [p for p in health._probes() if p.provider == TRADINGVIEW]
    assert probes
    assert all("finance.yahoo.com" not in p.url for p in probes)
    hosts = {p.url.split("/")[2] for p in probes}
    assert hosts == {"scanner.tradingview.com", "symbol-search.tradingview.com"}


def test_yahoo_probes_hit_yahoo_only():
    probes = [p for p in health._probes() if p.provider == health.YAHOO]
    assert probes
    assert all("finance.yahoo.com" in p.url for p in probes)


def test_summary_includes_rate_limit_state():
    monitor = HealthMonitor([])
    monitor.results = {
        "x": health.ProbeResult(
            id="x", provider=TRADINGVIEW, description="", url="", status=STATUS_OK,
        ),
    }
    summary = monitor.summary()
    assert set(summary["providers"]) == {
        TRADINGVIEW, FINVIZ, health.YAHOO, health.SA, health.EQUIBLES,
        INVESTING,
    }
    assert "rate_limits" in summary
    assert summary["providers"]["YAHOO"] == "UNKNOWN"


def test_stockanalysis_probe_asserts_the_price_field_not_the_status_code():
    """``status`` is an HTTP-style integer; the price lives at ``data.p``.

    Asserting ``status.data.p`` would report permanent DRIFT on a healthy
    endpoint, which is worse than no probe: it trains the reader to ignore the
    warning.
    """
    probe = next(p for p in health._probes() if p.id == "sa.quote_api")
    assert probe.required_keys == ("data.p",)
    assert probe.provider == health.SA
    payload = {"status": 200, "data": {"p": 342.37, "cl": 344.17}}
    assert health._has_key(payload, probe.required_keys[0]) is True
    # A renamed envelope field is what the probe exists to catch.
    assert health._has_key({"status": 200, "quote": {"p": 1.0}}, "data.p") is False


def _investing_access(monkeypatch, shaped, *, link="/equities/nvidia-corp"):
    """Install a controllable Investing access stub and return its call log."""
    import collections.abc

    from tapebasis import investing_access

    calls = {"search": [], "fetch": [], "state": [], "shape": []}

    async def search(symbol):
        calls["search"].append(symbol)
        if link is None:
            return []
        return [{
            "id": 6497,
            "symbol": "NVDA",
            "exchange_short_name": "NASDAQ",
            "currency_code": "USD",
            "client_type": "stock",
            "type": "equities",
            "link": link,
        }]
    async def fetch_html(path, cache_key):
        calls["fetch"].append((path, cache_key))
        return "<html>fixture</html>"

    def state(html):
        calls["state"].append(html)
        return {"props": {"pageProps": {"state": {"fixture": True}}}}

    def shape_quote(state_payload, expected):
        calls["shape"].append((state_payload, expected))
        return dict(shaped)

    monkeypatch.setattr(investing_access, "search", search)
    monkeypatch.setattr(investing_access, "_fetch_html", fetch_html)
    monkeypatch.setattr(investing_access, "_state", state)
    monkeypatch.setattr(investing_access, "shape_quote", shape_quote)
    return calls


def _real_investing_fixture() -> str:
    """Return the smallest complete NVDA SSR page accepted by the real decoder."""
    import json

    state = {
        "equityStore": {
            "instrumentId": 6497,
            "instrument": {
                "base": {
                    "id": 6497,
                    "type": "equity",
                    "path": "/equities/nvidia-corp",
                },
                "name": {"symbol": "NVDA", "fullName": "NVIDIA Corporation"},
                "exchange": {"exchange": "NASDAQ"},
                "price": {
                    "currency": "USD",
                    "last": 100.0,
                    "lastUpdateTime": 1795118400000,
                    "lastClose": 100.0,
                },
            },
        },
    }
    payload = json.dumps({"props": {"pageProps": {"state": state}}})
    return f'<script id="__NEXT_DATA__" type="application/json">{payload}</script>'


@pytest.mark.asyncio
async def test_investing_local_probe_accepts_a_real_decoded_fixture(
    tmp_path, monkeypatch
):
    """The health path works with the real state decoder and quote shaper."""
    from tapebasis import investing_access

    async def search(_symbol):
        return [{
            "id": 6497, "symbol": "NVDA", "exchange_short_name": "NASDAQ",
            "currency_code": "USD", "client_type": "stock", "type": "equities",
            "link": "/equities/nvidia-corp",
        }]

    async def fetch_html(_path, _cache_key):
        return _real_investing_fixture()

    monkeypatch.setattr(investing_access, "search", search)
    monkeypatch.setattr(investing_access, "_fetch_html", fetch_html)
    probe = Probe(
        id="investing.quote_html", provider=INVESTING,
        description="local", url="local:investing-quote",
    )
    result = await _monitor(tmp_path, [])._probe(probe, None)
    assert result.status == STATUS_OK
    assert not result.drift and not result.down


@pytest.mark.asyncio
@pytest.mark.parametrize("timestamp", ["2026-11-19T20:00:00+00:00", None])
async def test_investing_local_probe_checks_identity_and_timestamp(
    tmp_path, monkeypatch, timestamp
):
    """The local route uses no httpx and requires the exact NVDA identity."""
    from types import SimpleNamespace

    shaped = {
        "instrument_id": 6497,
        "symbol": "NVDA",
        "exchange": "NASDAQ",
        "currency": "USD",
        "asset_class": "stock",
        "price": 100.0,
        "price_timestamp": timestamp,
    }
    calls = _investing_access(monkeypatch, shaped)

    class RefusingClient:
        """Expose an async request that fails if generic HTTP is reached."""

        async def request(self, *_args, **_kwargs):
            raise AssertionError("Investing local probe used generic httpx")

    client = RefusingClient()
    monitor = _monitor(tmp_path, [])
    probe = Probe(
        id="investing.quote_html", provider=INVESTING,
        description="local", url="local:investing-quote",
    )
    result = await monitor._probe(probe, client)

    assert calls["search"] == ["NVDA"]
    assert calls["fetch"] == [
        ("https://www.investing.com/equities/nvidia-corp", "quote:6497")
    ]
    assert calls["state"] == ["<html>fixture</html>"]
    identity = calls["shape"][0][1]
    assert {key: identity[key] for key in (
        "instrument_id", "symbol", "exchange", "currency", "asset_class"
    )} == {
        "instrument_id": 6497,
        "symbol": "NVDA",
        "exchange": "NASDAQ",
        "currency": "USD",
        "asset_class": "stock",
    }
    assert identity["link"] == "/equities/nvidia-corp"
    assert identity["source"].endswith("/equities/nvidia-corp")
    if timestamp:
        assert result.status == STATUS_OK
        assert result.checked_at is not None
        assert not result.drift and not result.down
    else:
        assert result.status == STATUS_DRIFT
        assert result.missing == ["price_timestamp"]
        assert "timestamp" in result.message
        assert result.drift and not result.down


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "phrase"),
    [
        ("symbol", "AAPL", "symbol"),
        ("exchange", "NYSE", "exchange"),
        ("currency", "EUR", "currency"),
        ("instrument_id", 1, "instrument_id"),
    ],
)
async def test_investing_local_probe_rejects_another_instrument(
    tmp_path, monkeypatch, field, value, phrase
):
    """A well-formed quote for the wrong listing is drift, never healthy."""
    shaped = {
        "instrument_id": 6497,
        "symbol": "NVDA",
        "exchange": "NASDAQ",
        "currency": "USD",
        "price": 100.0,
        "price_timestamp": "2026-11-19T20:00:00+00:00",
        field: value,
    }
    _investing_access(monkeypatch, shaped)
    monitor = _monitor(tmp_path, [])
    probe = Probe(
        id="investing.quote_html", provider=INVESTING,
        description="local", url="local:investing-quote",
    )
    result = await monitor._probe(probe, None)
    assert result.status == STATUS_DRIFT
    assert result.missing == [phrase]
    assert phrase in result.message
    assert not result.down


@pytest.mark.asyncio
async def test_investing_local_probe_never_reads_the_page_when_search_has_no_link(
    tmp_path, monkeypatch
):
    """A failed identity resolution reports drift without a second page fetch."""
    from tapebasis import investing_access

    calls = []

    async def search(symbol):
        """Return no exact match and preserve the real raw-list interface."""
        calls.append(symbol)
        return []

    async def fetch_html(*_args):
        """Refuse a page read when no exact search identity was found."""
        raise AssertionError("quote page fetched after unresolved identity")

    monkeypatch.setattr(investing_access, "search", search)
    monkeypatch.setattr(investing_access, "_fetch_html", fetch_html)
    monitor = _monitor(tmp_path, [])
    probe = Probe(
        id="investing.quote_html", provider=INVESTING,
        description="local", url="local:investing-quote",
    )
    result = await monitor._probe(probe, None)
    assert calls == ["NVDA"]
    assert result.status == STATUS_DRIFT
    assert "no exact NVDA/NASDAQ/USD/stock" in result.message
    assert not result.down


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            ProviderError(
                "INVESTING", "page keys changed", code="SCHEMA_DRIFT"
            ),
            STATUS_DRIFT,
        ),
        (type("NoDataQuote", (Exception,), {})("no price"), STATUS_DRIFT),
        (RuntimeError("connection reset"), STATUS_DOWN),
    ],
)
async def test_investing_local_probe_classifies_access_failures(
    tmp_path, monkeypatch, error, expected
):
    """Schema and absent-quote errors drift; an unavailable upstream is down."""
    from tapebasis import investing_access

    async def search(_symbol):
        """Raise the injected transport, schema or missing-data failure."""
        raise error

    monkeypatch.setattr(investing_access, "search", search)
    monitor = _monitor(tmp_path, [])
    probe = Probe(
        id="investing.quote_html", provider=INVESTING,
        description="local", url="local:investing-quote",
    )
    result = await monitor._probe(probe, None)
    assert result.status == expected
    assert result.drift == (expected == STATUS_DRIFT)
    assert result.down == (expected == STATUS_DOWN)
    assert result.message


# ── watched-key drift, and accepting a new baseline ─────────────────────────


@pytest.mark.asyncio
async def test_removing_an_unread_key_is_not_drift(tmp_path, monkeypatch):
    """Two cosmetic upstream removals made every response degraded for good.

    ``COMP.premarketProxyTicker`` and ``data.epv`` are keys nothing here reads.
    Comparing the whole payload shape reported their removal as an outage, so
    every tool response carried ``degraded: true`` and three warnings, which
    trains a reader to ignore the warning that matters.
    """
    probe = Probe(
        id="p", provider=FINVIZ, description="d", url="https://example.test/api",
        required_keys=("price",),
        watched_keys=("price", "volume"),
    )
    monitor = _monitor(tmp_path, [probe])
    state = {"payload": {"price": 1.0, "volume": 2.0, "cosmetic": True}}

    def handler(request):
        return httpx.Response(200, json=state["payload"])

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        health.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )

    await monitor.run_once(force=True)
    assert monitor.provider_status(FINVIZ) == STATUS_OK

    # A key nobody reads disappears. The payload still serves every field here.
    state["payload"] = {"price": 1.0, "volume": 2.0}
    results = await monitor.run_once(force=True)
    assert results["p"].status == STATUS_OK
    assert not monitor.degraded()


@pytest.mark.asyncio
async def test_removing_a_watched_key_is_drift(tmp_path, monkeypatch):
    """A field the parser reads going away is this server's outage."""
    probe = Probe(
        id="p", provider=FINVIZ, description="d", url="https://example.test/api",
        required_keys=("price",),
        watched_keys=("price", "volume"),
    )
    monitor = _monitor(tmp_path, [probe])
    state = {"payload": {"price": 1.0, "volume": 2.0}}

    def handler(request):
        return httpx.Response(200, json=state["payload"])

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        health.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )

    await monitor.run_once(force=True)
    state["payload"] = {"price": 1.0}
    results = await monitor.run_once(force=True)
    assert results["p"].status == STATUS_DRIFT
    assert "volume" in results["p"].message
    assert monitor.degraded()


def test_watched_shape_matches_at_any_depth():
    """The same field sits at different depths per endpoint.

    A scanner row is ``data[0].d`` and a quote object is ``data.p``; the check
    answers "is the field this parser reads still somewhere in the payload".
    """
    payload = {
        "data": [{"d": [1, 2], "s": "AAPL"}],
        "chart": {"result": [{"indicators": {"quote": [{"close": [1.0]}]}}]},
    }
    assert health.watched_shape(payload, ("d", "s")) == {"d", "s"}
    assert health.watched_shape(payload, ("close",)) == {"close"}
    # Exact on the key: a renamed field is not a match.
    assert health.watched_shape(payload, ("closes", "chartPreviousClose")) == set()


def test_json_probes_declare_what_they_watch():
    """Every JSON probe names the fields its parser reads."""
    for probe in health._probes():
        if probe.required_keys:
            assert probe.watched_keys, probe.id


@pytest.mark.asyncio
async def test_accept_baseline_clears_drift(tmp_path, monkeypatch):
    """Drift was permanent: the only way out was deleting the state file."""
    probe = Probe(
        id="p", provider=FINVIZ, description="d", url="https://example.test/api",
        required_keys=("price",),
        watched_keys=("price", "volume"),
    )
    monitor = _monitor(tmp_path, [probe])
    state = {"payload": {"price": 1.0, "volume": 2.0}}

    def handler(request):
        return httpx.Response(200, json=state["payload"])

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        health.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )

    await monitor.run_once(force=True)
    state["payload"] = {"price": 1.0}  # volume gone: real drift
    await monitor.run_once(force=True)
    assert monitor.degraded()

    outcome = monitor.accept_baseline()
    assert outcome["accepted"] == ["p"]
    assert not monitor.degraded()

    # The next round agrees with the accepted shape instead of re-reporting it.
    results = await monitor.run_once(force=True)
    assert results["p"].status == STATUS_OK


@pytest.mark.asyncio
async def test_accept_baseline_skips_a_probe_that_is_down(tmp_path, monkeypatch):
    """A ``DOWN`` probe has no shape to record, so it keeps its old baseline."""
    probe = Probe(
        id="p", provider=FINVIZ, description="d", url="https://example.test/api"
    )
    monitor = _monitor(tmp_path, [probe])

    def handler(request):
        raise httpx.ConnectError("dns failure")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        health.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )
    await monitor.run_once(force=True)
    outcome = monitor.accept_baseline()
    assert outcome["accepted"] == []
    assert outcome["skipped"] == ["p"]


@pytest.mark.asyncio
async def test_probes_are_paced_by_their_provider_limiter(tmp_path, monkeypatch):
    """Three Yahoo probes used to fire at once against a one-per-second rule.

    A probe round costs 300 s of wall clock; it has no reason to be fast and
    every reason to look like a well-behaved client on the same upstream the
    rest of the server paces precisely because it answers 429 to a burst.
    """
    from tapebasis.ratelimit import limiter as limiter_of

    probes = [
        Probe(
            id=f"p{index}", provider=health.YAHOO, description="d",
            url=f"https://example.test/{index}",
        )
        for index in range(3)
    ]
    monitor = _monitor(tmp_path, probes)

    waits: list[str] = []
    paced = limiter_of(health.YAHOO)
    real_wait = paced.wait_turn

    async def counting_wait() -> None:
        waits.append("wait")
        await real_wait()

    monkeypatch.setattr(paced, "wait_turn", counting_wait)

    def handler(request):
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        health.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )
    await monitor.run_once(force=True)
    assert len(waits) == 3
