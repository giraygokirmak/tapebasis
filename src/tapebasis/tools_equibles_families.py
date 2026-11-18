"""Family-based access to selected official Equibles REST JSON GET routes.

Each tool accepts an exact dataset and documented filters. Every call performs
one read: no automatic pagination, arbitrary URL or provider fallback. Provider
analytics remain source-labelled rather than Tapebasis conclusions.
"""
from __future__ import annotations

from typing import Any, Mapping
import inspect

from . import eq_access, eq_catalog
from .equibles_surface import response as surface_response
from .providers_state import NoDataError, ProviderError, error_code

EQUIBLES = "EQUIBLES"
_ARGS = """Args:
    dataset: Exact operation listed by ``tapebasis_tool_map``.
    filters: JSON object restricted to that operation's documented path and
        query parameter names. Non-US listings use MIC:TICKER where documented.

Returns:
    Single-source EQUIBLES envelope containing the raw JSON under ``dataset``,
    with ``params_applied``, Data by Equibles, freshness and reporting delay.
    No key returns ``NOT_CONFIGURED`` before transport. An upstream plan denial
    returns ``PLAN_REQUIRED``, never a fabricated or substituted result.
"""


async def _family(
    family: str, dataset: str, filters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one frozen route, then fetch exactly one raw provider dataset."""
    call = eq_catalog.compile_call(family, dataset, filters)
    tool = f"equibles_{family}"
    try:
        payload = await eq_access.get(
            call["path"], params=call["params"], cache=not call["live"],
        )
        if not isinstance(payload, dict):
            raise ProviderError(
                EQUIBLES, "Equibles response was not a JSON object", code="SCHEMA_DRIFT",
            )
    except Exception as exc:  # noqa: BLE001 - the safe provider error is returned
        code = "NO_DATA" if isinstance(exc, NoDataError) else error_code(exc)
        error = {
            "provider": EQUIBLES,
            "code": code,
            "dataset": dataset,
            "message": getattr(exc, "message", None) or type(exc).__name__,
        }
        return surface_response(
            tool,
            {"family": family, "dataset": dataset},
            errors=[error],
            paths={dataset: call["path"]},
            dataset_names=(dataset,),
            params_applied={dataset: call["params"]},
        )
    return surface_response(
        tool,
        {"family": family, "dataset": dataset},
        datasets={dataset: payload},
        paths={dataset: call["path"]},
        dataset_names=(dataset,),
        params_applied={dataset: call["params"]},
    )


def _document(function, summary: str, extra_elements: str = "") -> None:
    """Attach the runtime docstring that FastMCP exposes as tool description."""
    function.__doc__ = summary + extra_elements + "\n\n" + _ARGS


async def equibles_company(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles company dataset using documented filters."""
    return await _family("company", dataset, filters)


async def equibles_filings(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles filing dataset using documented filters."""
    return await _family("filings", dataset, filters)


async def equibles_investor_events(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles investor-event dataset using documented filters."""
    return await _family("investor_events", dataset, filters)


async def equibles_ownership(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles ownership dataset using documented filters."""
    return await _family("ownership", dataset, filters)


async def equibles_institutions(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles institution dataset using documented filters."""
    return await _family("institutions", dataset, filters)


async def equibles_positioning(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles positioning dataset using documented filters."""
    return await _family("positioning", dataset, filters)


async def equibles_options(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles options dataset using documented filters."""
    return await _family("options", dataset, filters)


async def equibles_market_data(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles market-data dataset using documented filters."""
    return await _family("market_data", dataset, filters)


async def equibles_funds(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles fund dataset using documented filters."""
    return await _family("funds", dataset, filters)


async def equibles_macro(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles macro dataset using documented filters."""
    return await _family("macro", dataset, filters)


async def equibles_market_context(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles market-context dataset using documented filters."""
    return await _family("market_context", dataset, filters)


async def equibles_public_policy(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles public-policy dataset using documented filters."""
    return await _family("public_policy", dataset, filters)


async def equibles_international(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles international dataset using documented filters."""
    return await _family("international", dataset, filters)


async def equibles_crypto(dataset: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one raw Equibles crypto dataset using documented filters."""
    return await _family("crypto", dataset, filters)


_TOOLS = (
    (equibles_company, "Equibles: company fundamentals, disclosures, estimates and valuation"),
    (equibles_filings, "Equibles: filings, document text and filings search"),
    (equibles_investor_events, "Equibles: calls, transcripts, IR materials and IPOs"),
    (equibles_ownership, "Equibles: disclosed ownership, insiders and supply chains"),
    (equibles_institutions, "Equibles: institutions and 13F portfolio analytics"),
    (equibles_positioning, "Equibles: short interest, FTD, off-exchange and model scores"),
    (equibles_options, "Equibles paid-plan: raw chains, contracts and option analytics"),
    (equibles_market_data, "Equibles: quotes, price history, intraday bars and technicals"),
    (equibles_funds, "Equibles: funds, ETFs, portfolios and annual operations"),
    (equibles_macro, "Equibles: FRED, Canadian macro calendars and CFTC positioning"),
    (equibles_market_context, "Equibles: listings, indexes, sentiment and market context"),
    (equibles_public_policy, "Equibles: congressional disclosures and government contracts"),
    (equibles_international, "Equibles: international disclosure and native fund reports"),
    (equibles_crypto, "Equibles: crypto directory, quotes and historical bars"),
)
for _function, _title in _TOOLS:
    _document(_function, _title)
del _function, _title


def register(mcp) -> int:
    """Attach all grouped Equibles tools with nonempty MCP documentation."""
    for function, title in _TOOLS:
        if not inspect.getdoc(function):
            raise RuntimeError(f"missing MCP documentation for {function.__name__}")
        mcp.add_tool(function, name=function.__name__, title=title)
    return len(_TOOLS)


__all__ = ["register", *(function.__name__ for function, _ in _TOOLS)]
