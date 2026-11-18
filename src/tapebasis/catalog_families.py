"""Static-catalogue MCP metadata for grouped Equibles routes."""
from __future__ import annotations

from .eq_catalog import CATALOG as _EQUIBLES_DATASETS
from .tools_equibles_families import _TOOLS as _EQUIBLES_FAMILY_TOOLS

_EQUIBLES_FAMILY_CAPABILITIES = {
    "company": "company profile, financial reports, estimates, debt, valuation and disclosures",
    "filings": "filing directories, passages, document lines and full-text search",
    "investor_events": "earnings calls, live transcripts, IR materials, events and IPOs",
    "ownership": "insider, institutional, beneficial-owner and supply-chain disclosures",
    "institutions": "13F filers, portfolios, consensus holdings and market activity",
    "positioning": "FINRA short positions and volume, FTD, off-exchange and provider scores",
    "options": "raw option chains and contracts, expirations, sessions and provider calculations",
    "market_data": "quotes, stored OHLCV, intraday bars, technicals and corporate actions",
    "funds": "fund and ETF directories, holdings, profiles and annual operations",
    "macro": "FRED and Canadian series, releases and CFTC positioning",
    "market_context": "listings, indexes, advisors, screeners, calendars and market observations",
    "public_policy": "congressional disclosures and government contract awards",
    "international": "international filings, ownership and native-report disclosures",
    "crypto": "crypto directory, quotes, historical prices and intraday bars",
}
rows = (
    {
        "name": function.__name__,
        "capability": _EQUIBLES_FAMILY_CAPABILITIES[function.__name__.removeprefix("equibles_")],
        "providers": "EQUIBLES",
        "comparison": "single-source, isolated raw JSON, no fallback or price arbitration",
        "arguments": {
            "dataset": "one exact key from datasets; no free-form endpoint",
            "filters": "only the documented path/query names in the selected dataset",
        },
        "datasets": _EQUIBLES_DATASETS[function.__name__.removeprefix("equibles_")],
        "notes": (
            "One dataset performs exactly one GET with no automatic pagination. "
            "Requires TAPEBASIS_EQUIBLES_API_KEY; actual 401 and 403 responses "
            "control access. Provider analytics stay provider-labelled. Options "
            "require Plus or Pro. Live transcripts bypass cache."
        ),
    }
    for function, _title in _EQUIBLES_FAMILY_TOOLS
)
