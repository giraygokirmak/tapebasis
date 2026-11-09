"""tapebasis, one MCP server that cross-checks multiple market-data providers.

Run over stdio (default) or streamable HTTP::

    tapebasis                       # stdio
    tapebasis streamable-http --host 0.0.0.0 --port 8000

Every tool response carries ``data_provider`` ∈ ``ALL`` / ``TRADINGVIEW`` /
``FINVIZ`` / ``YAHOO`` / ``SA`` / ``BLOOMBERG`` / ``NONE``, and any upstream
schema drift detected by the health monitor is reported inside the same response.
Bloomberg is a reconciliation leg whose equity quotes are exchange-delayed;
StockAnalysis is one whose coverage is US-only. Both are reported rather than
counted as disagreements or as missing data.
"""
from __future__ import annotations

import argparse
import logging
import os
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from . import __version__
from .health import MONITOR
from .providers_state import PROVIDER_MEANING

logger = logging.getLogger("tapebasis")

INSTRUCTIONS = (
    "Market data from multiple independent providers (TradingView, Finviz, Yahoo "
    "Finance, StockAnalysis and Bloomberg), each fetched natively and asked in "
    "parallel. Every tool result includes `data_provider`, one of ALL, TRADINGVIEW, "
    "FINVIZ, YAHOO, SA, BLOOMBERG or NONE.\n\n"
    "HOW TO READ IT:\n"
    "- ALL: every provider that was asked answered. This is COVERAGE, not agreement. "
    "Check `comparisons` for whether the readings match, and `providers_answered` for "
    "exactly which providers contributed.\n"
    "- TRADINGVIEW, FINVIZ, YAHOO, SA or BLOOMBERG: only that provider had the data. "
    "You MUST tell the user this figure is single-source and not cross-verified.\n"
    "- BLOOMBERG readings can be structurally older: its equity and index quotes are "
    "exchange-delayed (typically 15 minutes). Check `exchange_delay` and `print_time` "
    "before calling such a price live, and relay a `not_comparable` reason instead of "
    "calling it a provider disagreement.\n"
    "- SA is StockAnalysis. It covers US equities and ETFs only (no indices, FX, crypto, commodities "
    "or foreign listings), and its quote surface is the same consolidated tape Yahoo "
    "serves, so SA/YAHOO agreement is weak corroboration, not two independent witnesses.\n"
    "- NONE: no data; do not present a value.\n\n"
    "Only one value is ever returned per field (the newest market print). Every "
    "provider's raw reading stays in `comparisons`, and disagreements are named in "
    "`notice`, never silently resolved. Fields that could not be judged are reported as "
    "`not_comparable` with the reason instead of being called a disagreement: the prints "
    "describe different sessions, one is past the staleness ceiling, or the field has no "
    "shared definition at all (an FX day change, since spot FX has no single official "
    "previous close). Symbols are resolved per provider, so `XAUUSD` "
    "reaches TradingView as OANDA:XAUUSD while Yahoo and Finviz report that they do "
    "not carry it; `resolutions` records how each ticker was derived.\n\n"
    "Per-field provenance is in `fields`, raw side-by-side values in `comparisons`, and "
    "provider failures in `errors`. If `degraded` is true or `warnings` names an upstream "
    "change, relay that warning: the provider health monitor detected an API/schema "
    "change or outage. Call `tapebasis_health` for details and for per-provider rate-limit "
    "state.\n\n"
    "TOOLS: stock_quote, stock_prices, stock_screener, market_indices, stock_news, "
    "stock_options_chain, stock_earnings, stock_extended_hours, technical_analysis, "
    "stock_filings, stock_ownership, stock_peers, stock_why_moving, stock_chart, "
    "stock_dilution, stock_screener_filters, crypto_*, futures_*, stock_backtest*, "
    "market_snapshot, market_sentiment, egx_market_overview, combined_analysis, "
    "bloomberg_quote, bloomberg_markets, tapebasis_health, tapebasis_tool_map."
)


@asynccontextmanager
async def lifespan(_server: FastMCP):
    """Start the health monitor on transports that honour the lifespan (stdio)."""
    if os.environ.get("TAPEBASIS_HEALTH_ENABLED", "true").lower() != "false":
        await MONITOR.start()
        logger.info(
            "health monitor started (interval=%ss, ttl=%ss)",
            MONITOR.interval,
            MONITOR.ttl,
        )
    try:
        yield {}
    finally:
        await MONITOR.stop()


mcp = FastMCP(
    name="Tapebasis, TradingView + Finviz + Yahoo + StockAnalysis (+ Bloomberg single-source)",
    instructions=INSTRUCTIONS,
    lifespan=lifespan,
)


def _register_all() -> dict[str, int]:
    """Attach every tool family to the server."""
    from . import (
        tools_bloomberg,
        tools_finviz,
        tools_health,
        tools_market,
        tools_tradingview,
    )

    counts = {
        "market": tools_market.register(mcp),
        "finviz": tools_finviz.register(mcp),
        "tradingview": tools_tradingview.register(mcp),
        "bloomberg": tools_bloomberg.register(mcp),
        "health": tools_health.register(mcp),
    }
    return counts


TOOL_COUNTS = _register_all()


@mcp.resource("tapebasis://providers")
def providers_resource() -> str:
    """Explain what each data_provider value means for a caller."""
    return "\n".join(
        f"{provider.value}: {meaning}"
        for provider, meaning in PROVIDER_MEANING.items()
    )


@mcp.resource("tapebasis://health")
async def health_resource() -> str:
    """Cached provider health verdict (no upstream call)."""
    MONITOR.ensure_started()
    summary = MONITOR.summary()
    lines = [
        f"Providers: {summary['providers']}",
        f"Degraded: {summary['degraded']}",
    ]
    for issue in summary["issues"]:
        lines.append(
            f"- {issue['provider']} {issue['status']} {issue['probe']}: {issue['message']}"
        )
    for name, state in (summary.get("rate_limits") or {}).items():
        if state.get("cooling_down_s", 0) > 0:
            lines.append(
                f"- {name} rate-limit cooldown: {state['cooling_down_s']}s left "
                f"(block streak {state.get('block_streak')})"
            )
    return "\n".join(lines)


@mcp.custom_route("/health", methods=["GET"])
async def _health(_request):
    """Liveness probe for the Docker HEALTHCHECK (cheap, no upstream call)."""
    from starlette.responses import JSONResponse

    # FastMCP's streamable-HTTP app ignores the lifespan passed to FastMCP, so
    # the monitor is started on first request instead of at startup.
    MONITOR.ensure_started()
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "tools": TOOL_COUNTS,
            "providers": MONITOR.summary()["providers"],
            "rate_limits": MONITOR.summary().get("rate_limits", {}),
            "degraded": MONITOR.degraded(),
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="tapebasis server")
    parser.add_argument(
        "transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        nargs="?",
        help="Transport (default stdio)",
    )
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()

    if os.environ.get("DEBUG_MCP"):
        import sys

        print(
            f"[DEBUG_MCP] pkg cwd={os.getcwd()} argv={sys.argv} file={__file__}",
            file=sys.stderr,
            flush=True,
        )

    if args.transport == "stdio":
        mcp.run()
        return

    from mcp.server.transport_security import TransportSecuritySettings

    mcp.settings.host = args.host
    mcp.settings.port = args.port
    # Binds to 0.0.0.0 inside a container; DNS-rebinding protection would
    # reject the container's own hostname on the first request.
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    )
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
