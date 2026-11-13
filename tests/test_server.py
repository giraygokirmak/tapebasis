"""Regression tests for server wiring.

The important one: FastMCP's streamable-HTTP app hardcodes its own Starlette
lifespan, so the ``lifespan=`` passed to ``FastMCP()`` is never run on that
transport. If the health monitor only started from the lifespan, the Docker
deployment would silently never probe its upstreams and every response would
claim ``UNKNOWN`` health. These tests pin the self-starting behaviour.
"""
from __future__ import annotations

import asyncio

import pytest

from tapebasis import server


def test_all_tools_are_registered():
    tools = asyncio.run(server.mcp.list_tools())
    names = {tool.name for tool in tools}
    expected = {
        "stock_quote",
        "stock_prices",
        "stock_screener",
        "market_indices",
        "stock_news",
        "stock_options_chain",
        "stock_earnings",
        "stock_extended_hours",
        "technical_analysis",
        "stock_filings",
        "stock_ownership",
        "stock_peers",
        "stock_why_moving",
        "stock_chart",
        "stock_dilution",
        "stock_screener_filters",
        "crypto_top_movers",
        "crypto_bollinger_scan",
        "crypto_volume_breakout",
        "crypto_multi_timeframe",
        "crypto_multi_agent",
        "futures_market_overview",
        "futures_top_movers",
        "futures_watchlist",
        "stock_backtest",
        "stock_backtest_compare",
        "market_snapshot",
        "bitcoin_market_pulse",
        "market_sentiment",
        "egx_market_overview",
        "combined_analysis",
        "bloomberg_quote",
        "bloomberg_markets",
        "tapebasis_health",
        "tapebasis_tool_map",
    }
    assert names == expected
    assert len(names) == 35


def test_every_tool_has_a_description():
    tools = asyncio.run(server.mcp.list_tools())
    undocumented = [tool.name for tool in tools if not (tool.description or "").strip()]
    assert not undocumented, f"tools without a description: {undocumented}"


def test_server_instructions_document_the_provider_contract():
    instructions = server.INSTRUCTIONS
    for value in ("ALL", "TRADINGVIEW", "FINVIZ", "YAHOO", "BLOOMBERG", "NONE"):
        assert value in instructions
    assert "single-source" in instructions.lower()
    # ``ALL`` must be described as coverage, not as agreement.
    assert "coverage" in instructions.lower()


@pytest.mark.asyncio
async def test_monitor_self_starts_without_the_lifespan(monkeypatch, _isolate_health_state):
    """The HTTP transport never runs our lifespan; reading the monitor must start it."""

    monitor = _isolate_health_state
    monitor._task = None
    # conftest disables the monitor for the suite by default; this test is
    # specifically about the enabled case.
    monitor.enabled = True

    async def no_network(*, force: bool = False):
        return {}

    monkeypatch.setattr(monitor, "run_once", no_network)

    monitor.summary()  # what a tool call / /health route does
    await asyncio.sleep(0)  # let the created task begin

    assert monitor._task is not None, "monitor was not started by summary()"
    assert not monitor._task.done()
    monitor._task.cancel()


@pytest.mark.asyncio
async def test_monitor_respects_the_disable_switch(monkeypatch, _isolate_health_state):
    monitor = _isolate_health_state
    monitor._task = None
    monitor.enabled = False

    monitor.warnings_for(("TRADINGVIEW",))
    await asyncio.sleep(0)

    assert monitor._task is None, "disabled monitor must not start a background task"


def test_ensure_started_is_safe_without_a_running_loop(_isolate_health_state):
    monitor = _isolate_health_state
    monitor._task = None
    monitor.ensure_started()  # sync context: must be a silent no-op, not a crash
    assert monitor._task is None


def test_tool_map_enumerates_every_registered_tool():
    from tapebasis.catalog import TOOL_CATALOG

    catalogued = {row["name"] for row in TOOL_CATALOG}
    registered = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    missing = registered - catalogued
    assert not missing, f"tools missing from the catalog: {sorted(missing)}"
    stale = catalogued - registered
    assert not stale, f"catalog lists tools that do not exist: {sorted(stale)}"


@pytest.mark.asyncio
async def test_tool_map_names_one_source_per_tool():
    """The map's per-tool provenance is the catalogue's declared provider set.

    ``fields`` there follows the response contract, so each entry names the
    single provider that backs the tool; the map never presents a tool as a
    joint product of several providers.
    """
    from tapebasis.tools_health import tapebasis_tool_map

    response = await tapebasis_tool_map()
    fields = response["fields"]
    assert fields["bloomberg_quote"] == {
        "source": "BLOOMBERG",
        "supplied": ["BLOOMBERG"],
        "compared": [],
        "agreement": None,
    }
    assert fields["bloomberg_markets"]["source"] == "BLOOMBERG"
    assert fields["stock_quote"]["source"] == "ALL"
    # Bloomberg is a leg of the quote tools, but it has no health probe, and
    # the map says so rather than implying it was probed.
    assert "BLOOMBERG" in response["providers_answered"]
    assert any("no health probe" in warning for warning in response["warnings"])
