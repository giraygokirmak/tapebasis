"""Tests for the upstream health monitor (mocked HTTP, no network)."""
from __future__ import annotations

import httpx
import pytest

from tapebasis import health
from tapebasis.health import (
    FINVIZ,
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
    assert providers == {TRADINGVIEW, FINVIZ, health.YAHOO, health.SA}


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
        TRADINGVIEW, FINVIZ, health.YAHOO, health.SA,
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
