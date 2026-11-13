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
