"""Shared response contract for the isolated Equibles REST tools.

Every tool keeps the provider's raw JSON objects in separately named datasets.
Nothing is merged with another provider or silently substituted after an error.
The caller's ordinary API key and actual Equibles plan response decide access;
there is no local paid-plan assertion or pre-request plan denial.

The helpers in this module perform no implicit pagination and no alternate
provider fallback. One selected dataset means one documented REST request.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Mapping

from . import eq_access
from .health import MONITOR
from .providers_state import DataProvider, NoDataError, envelope, error_code
from .reconcile import field_source

EQUIBLES = "EQUIBLES"
_API = "https://api.equibles.com/v1"
_CONTRACT = "https://equibles.com/legal/terms"
_CORO = Callable[[], Coroutine[Any, Any, Any]]

#: Reporting meaning, not a fabricated freshness timestamp. Unknown datasets
#: receive the conservative generic definition below.
LAGS: dict[str, dict[str, str]] = {
    "profile": {"source": "company and listing identity", "schedule": "reference data, not a dated market observation"},
    "financial_statement": {"source": "SEC filings", "schedule": "fiscal-period statements; filedDate identifies when each line became public"},
    "financial_facts": {"source": "SEC XBRL facts", "schedule": "fiscal-period facts; each row retains its own filing evidence"},
    "revenue_breakdown": {"source": "SEC filings", "schedule": "annual segment, geography and product disclosures; periodEnd identifies the period"},
    "debt_profile": {"source": "SEC filings", "schedule": "reported balances and instruments as filed; asOfDate identifies the balance date"},
    "debt_instrument": {"source": "SEC filings", "schedule": "instrument terms as filed, with exact source evidence"},
    "proposed_sales": {"source": "SEC Form 144", "schedule": "filed intentions to sell, not completed transactions"},
    "insider_transactions": {"source": "SEC Forms 3, 4 and 5", "schedule": "event-driven regulatory filings, not a live feed"},
    "insider_ownership": {"source": "SEC Forms 3, 4 and 5", "schedule": "ownership balances derived from filed reports"},
    "institutional_ownership": {"source": "SEC Form 13F", "schedule": "quarterly filings, commonly available up to 45 days after quarter end"},
    "institutional_activity": {"source": "SEC Form 13F", "schedule": "quarterly filings, commonly available up to 45 days after quarter end"},
    "institution_portfolio": {"source": "SEC Form 13F", "schedule": "one reported quarter; filing lag and valuing conventions remain in the response"},
    "institution_activity": {"source": "SEC Form 13F", "schedule": "changes against the immediately prior reported quarter"},
    "institution_sector_allocation": {"source": "SEC Form 13F", "schedule": "allocation for one actual reported quarter"},
    "institution_style_history": {"source": "SEC Form 13F", "schedule": "measured closed quarters, not current holdings"},
    "fund_owners": {"source": "SEC Form N-PORT", "schedule": "one row per fund fiscal reporting period; dates differ between funds"},
    "fund_profile": {"source": "SEC Form N-PORT", "schedule": "latest stored report, whose date and coverage are supplied by the provider"},
    "fund_holdings": {"source": "SEC Form N-PORT", "schedule": "fund fiscal reporting period, not a live portfolio"},
    "fund_operations": {"source": "SEC Form N-CEN", "schedule": "annual fund reports"},
    "etf_profile": {"source": "fund disclosures and market data", "schedule": "report and market observation dates remain separate"},
    "etf_holdings": {"source": "fund portfolio disclosures", "schedule": "published portfolio date, not a live portfolio"},
    "short_interest": {"source": "FINRA short interest", "schedule": "published twice monthly, so readings are not live"},
    "short_volume": {"source": "FINRA facility volume", "schedule": "daily facility-reported subset of volume, not consolidated tape volume"},
    "fails_to_deliver": {"source": "SEC fails-to-deliver", "schedule": "half-month publication batches with approximately two weeks of delay"},
    "off_exchange_volume": {"source": "FINRA OTC and ATS transparency", "schedule": "weekly observations, typically released with approximately two weeks of delay"},
    "options_summary": {"source": "Equibles option calculations over a dated chain", "schedule": "paid plan; quote timing follows the account's plan"},
    "options_term_structure": {"source": "Equibles option calculations over dated chains", "schedule": "paid plan; quote timing follows the account's plan"},
    "option_chain": {"source": "OPRA or the relevant listing exchange", "schedule": "paid plan; a snapshot, not an options-history store"},
    "option_expirations": {"source": "listed option expirations", "schedule": "future expiration schedules are not observation timestamps"},
    "option_contract": {"source": "OPRA or the relevant listing exchange", "schedule": "paid plan; contract snapshot with its own session and quote timing"},
    "option_contract_bars": {"source": "stored option trades", "schedule": "paid plan; bars are observations of their own sessions"},
    "option_contract_trades": {"source": "option trade tape", "schedule": "paid plan; historical prints, not a live consolidated quote"},
    "option_session": {"source": "stored option session", "schedule": "paid plan; session availability differs between Plus and Pro"},
    "option_volatility": {"source": "Equibles option calculations", "schedule": "daily derived implied-volatility observations"},
    "option_strategy": {"source": "Equibles option arithmetic", "schedule": "reference calculation over the returned quotes, not a recommendation"},
    "price_history": {"source": "Equibles stored traded OHLCV history", "schedule": "historical bars, not live prices; Free receives the latest session after a delay"},
    "live_quote": {"source": "consolidated or exchange quote feed", "schedule": "paid plan; the provider states real-time or delayed status"},
    "intraday_bars": {"source": "exchange trade feed", "schedule": "paid plan; delayed on Plus and forming on Pro where stated"},
    "technical_indicator": {"source": "Equibles calculations over daily bars", "schedule": "derived from settled daily bars; latest-session availability depends on plan"},
    "correlations": {"source": "Equibles calculations over comparable daily closes", "schedule": "historical return correlations, not price forecasts"},
    "analyst_estimates": {"source": "Equibles verified analyst-estimate snapshots", "schedule": "as captured and verified in the returned snapshot, not a real-time feed"},
    "guidance": {"source": "equities filings and earnings calls", "schedule": "event-driven disclosure; filedDate identifies the disclosure"},
    "filings": {"source": "SEC EDGAR and captured transcripts", "schedule": "filedDate, acceptedAt and ingestedAt describe distinct events"},
    "filing_search": {"source": "SEC documents and captured transcripts", "schedule": "passages retain their document filing date and line references"},
    "filing_document": {"source": "one stored filing or transcript", "schedule": "verbatim stored text; its filedDate is the document date"},
    "earnings_call": {"source": "company webcast and earnings release", "schedule": "capture depends on the issuer; callDate and fiscal period are supplied"},
    "call_transcript": {"source": "company webcast or filed call record", "schedule": "captured after the call; speaker identity and corrections remain source-labelled"},
    "call_questions": {"source": "company webcast or filed call record", "schedule": "captured Q&A, not an analyst-estimate population"},
    "call_briefs": {"source": "Equibles verifier-approved AI briefs", "schedule": "published for scored calls only; provider analysis, not Tapebasis synthesis"},
    "call_insights": {"source": "Equibles verifier-approved AI scores", "schedule": "published for scored calls only; provider scores, not Tapebasis synthesis"},
    "call_themes": {"source": "Equibles scored call themes", "schedule": "one row per scored fiscal quarter; unscored quarters are not zero"},
    "phrase_trend": {"source": "Equibles deterministic transcript counts", "schedule": "whole-word counts over captured calls, not an editorial score"},
    "investor_events": {"source": "company investor-relations sites and webcasts", "schedule": "issuer-site dependent; materials state their own capture status"},
    "ir_news": {"source": "company investor-relations sites", "schedule": "company publication schedule, not a consolidated newswire"},
    "ir_events": {"source": "company investor-relations calendars", "schedule": "scheduled and past company events"},
    "kpis": {"source": "company filings and investor materials", "schedule": "company-defined metrics with their reported periods"},
    "non_gaap_bridge": {"source": "SEC filings", "schedule": "reported reconciliation periods; not accounting-standardized by Tapebasis"},
    "customer_concentration": {"source": "SEC filings", "schedule": "disclosed customer shares with filing evidence"},
    "going_concern": {"source": "SEC filings", "schedule": "management and auditor disclosures as filed, not a solvency prediction"},
    "buyback_programs": {"source": "SEC filings, XBRL and issuer releases", "schedule": "authorization and repurchase dates remain separate"},
    "atm_programs": {"source": "SEC filings", "schedule": "verified extraction over the coverage window stated by Equibles"},
    "exempt_offerings": {"source": "SEC Form D", "schedule": "filed notices; amendments restate earlier offerings"},
    "executive_changes": {"source": "SEC Form 8-K Item 5.02", "schedule": "filed changes; coverage counts describe processed filings"},
    "executive_compensation": {"source": "SEC DEF 14A proxies", "schedule": "fiscal-year proxy disclosures, not current pay"},
    "valuation_multiples": {"source": "Equibles calculations over filings and prices", "schedule": "balance-sheet and price dates can differ and remain identified"},
    "shareholder_votes": {"source": "SEC Form 8-K", "schedule": "meeting results as filed"},
    "holder_mix": {"source": "SEC Form 13F and other ownership filings", "schedule": "each population retains its filing schedule"},
    "ownership_signals": {"source": "Equibles calculations over 13F books", "schedule": "newest measured closed quarter; estimates are labelled"},
    "holder_targets": {"source": "Equibles 13F overlap analysis", "schedule": "newest measured closed quarter, not current intentions"},
    "beneficial_ownership": {"source": "SEC Schedules 13D and 13G", "schedule": "event-driven filings, separate from quarterly 13F positions"},
    "market_13f_activity": {"source": "SEC Form 13F", "schedule": "quarterly market-wide activity, subject to filing lag"},
    "super_investors": {"source": "SEC Form 13F", "schedule": "curated filer views for reported quarters"},
    "congress_trades": {"source": "US congressional financial disclosures", "schedule": "disclosure dates can lag transactions"},
    "congress_net_worth": {"source": "US congressional financial disclosures", "schedule": "reported annual ranges, not exact current assets"},
    "congress_market_activity": {"source": "US congressional financial disclosures", "schedule": "aggregated over the returned disclosure window"},
    "government_contracts": {"source": "USAspending.gov or open.canada.ca", "schedule": "award action dates, not company revenue"},
    "cftc_contracts": {"source": "CFTC contract directory", "schedule": "reference contract metadata"},
    "cftc_positions": {"source": "CFTC Commitments of Traders", "schedule": "weekly report dates, not live positioning"},
    "fred_series": {"source": "FRED, Bank of Canada or Statistics Canada", "schedule": "curated series metadata"},
    "fred_observations": {"source": "FRED, Bank of Canada or Statistics Canada", "schedule": "observation dates and publisher release lag remain distinct"},
    "economic_calendar": {"source": "official statistical-release calendars", "schedule": "scheduled releases, not observations"},
    "insider_sentiment": {"source": "Equibles derived insider-sentiment score", "schedule": "provider score over its stated window; not a Tapebasis rating"},
    "short_squeeze": {"source": "Equibles derived short-squeeze score", "schedule": "provider score tied to its FINRA vintage; not a price forecast"},
    "vix": {"source": "CBOE VIX", "schedule": "daily settled history"},
    "put_call_ratios": {"source": "CBOE", "schedule": "daily market sentiment observations"},
    "market_status": {"source": "exchange calendar", "schedule": "session status at the provider observation time"},
    "market_calendar": {"source": "exchange calendar", "schedule": "scheduled holidays and early closes"},
    "fda_catalysts": {"source": "FDA", "schedule": "scheduled advisory-committee meetings"},
    "ipos": {"source": "SEC EDGAR", "schedule": "daily filing sweep; terms appear only with filing evidence"},
    "indexes": {"source": "tracking-fund and exchange publications", "schedule": "published snapshots; forecasts are rules-based, not index decisions"},
    "listings": {"source": "official exchange and regulator directories", "schedule": "reference identity data"},
    "screener": {"source": "Equibles derived market and filing datasets", "schedule": "mixed-cadence vintages are named in the response"},
    "supply_chain": {"source": "SEC Form 10-K", "schedule": "verified filing extraction; names require Pro"},
    "crypto": {"source": "Equibles crypto market feed", "schedule": "each quote or bar retains its own observation time"},
}


def clock() -> datetime:
    """Return the current UTC clock for response metadata."""
    return datetime.now(timezone.utc)


def age_seconds(as_of: Any) -> float | None:
    """Return observation age in seconds, or null for an unknown timestamp."""
    if not as_of:
        return None
    text = str(as_of)
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if len(text) == 10:
        when = when.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    elif when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (clock() - when.astimezone(timezone.utc)).total_seconds())


def bounded(value: int, low: int, high: int, name: str, adjustments: list[str]) -> int:
    """Clamp an integer page bound and record the adjustment for warnings."""
    applied = max(low, min(high, value))
    if applied != value:
        adjustments.append(f"{name} was clamped from {value} to {applied}")
    return applied


def iso_date(value: str | None, name: str) -> str | None:
    """Validate an optional ISO date filter and return its unchanged text."""
    if value is None:
        return None
    text = str(value).strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD") from exc
    return text


def document_id(value: str) -> str:
    """Validate a filing, transcript or event UUID before transport."""
    text = str(value or "").strip()
    try:
        uuid.UUID(text)
    except ValueError as exc:
        raise ValueError("document_id or event_id must be a UUID returned by Equibles") from exc
    return text


def choice(value: str, name: str, allowed: set[str]) -> str:
    """Validate a documented exact enum without silently substituting another."""
    normalized = str(value or "").strip()
    if normalized not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(sorted(allowed))}")
    return normalized


def access_contract(
    *,
    errors: list[dict[str, Any]],
    datasets: Mapping[str, Any],
    dataset_names: tuple[str, ...],
) -> dict[str, Any]:
    """Describe actual key/plan access without asserting a licence tier."""
    configured = bool(eq_access.api_key())
    if any(error.get("code") == "NOT_CONFIGURED" for error in errors):
        configured = False
    plan_denied = [
        error.get("dataset", "all") for error in errors
        if error.get("code") == "PLAN_REQUIRED"
    ]
    if "all" in plan_denied:
        plan_denied = list(dataset_names)
    if not configured:
        status = "auth_rejected" if eq_access.api_key() else "not_configured"
    elif plan_denied:
        status = "partially_available" if datasets else "plan_required"
    else:
        status = "configured"
    block: dict[str, Any] = {
        "status": status,
        "configured": configured,
        "plan_gate": "The actual Equibles plan response decides access; no local plan is asserted.",
        "requirement": "Use is subject to the operator's Equibles plan and API terms.",
        "terms": _CONTRACT,
    }
    if plan_denied:
        block["plan_required_datasets"] = plan_denied
    if errors:
        block["error_status"] = "no data substituted for an unavailable plan or provider response"
    return block


def response(
    tool: str,
    subject: Mapping[str, Any],
    *,
    datasets: Mapping[str, Any] | None = None,
    paths: Mapping[str, str] | None = None,
    errors: list[dict[str, Any]] | None = None,
    freshness: Mapping[str, Any] | None = None,
    dataset_names: tuple[str, ...] | None = None,
    params_applied: Mapping[str, Any] | None = None,
    adjustments: list[str] | None = None,
) -> dict[str, Any]:
    """Wrap raw provider objects with source, freshness and access metadata."""
    errors = errors or []
    datasets = dict(datasets or {})
    dataset_names = dataset_names or tuple(datasets)
    delayed = any(
        isinstance(value, dict) and value.get("delayed") is True
        for value in datasets.values()
    )
    freshness = dict(freshness or eq_access.freshness_for(datasets, delayed=delayed))
    for name in dataset_names:
        freshness["datasets"].setdefault(name, {
            "as_of": None,
            "latest_observation_at": None,
            "earliest_observation_at": None,
            "basis": "unavailable; no observation timestamp was supplied",
        })
    access = access_contract(errors=errors, datasets=datasets, dataset_names=dataset_names)
    reporting_delay = {
        name: dict(LAGS.get(name, {
            "source": "the returned provider dataset",
            "schedule": "event-driven or period-based; use its own observation timestamps",
        }))
        for name in dataset_names
    }
    data = None if errors and not datasets else {
        **datasets,
        "attribution": eq_access.ATTRIBUTION,
        "provider": EQUIBLES,
        "transport": "official REST API only",
        "as_of": freshness.get("as_of"),
        "freshness": freshness,
        "reporting_delay": reporting_delay,
        "access": access,
    }
    if data is not None:
        data["observation_age_seconds"] = age_seconds(data["as_of"])
        if data["observation_age_seconds"] is not None:
            data["observation_age_is_approximate"] = bool(freshness.get("as_of_date_only"))
    warnings = [
        "Equibles is single-source and not cross-verified. Preserve Data by Equibles attribution "
        "and each dataset's own as_of and reporting delay.",
    ]
    warnings.extend(adjustments or [])
    warnings.extend(
        f"{error.get('dataset', 'Equibles dataset')} unavailable: {error['message']}"
        for error in errors
    )
    return envelope(
        data,
        provider=DataProvider.EQUIBLES if datasets else DataProvider.NONE,
        fields={name: field_source(EQUIBLES, (), None, supplied=[EQUIBLES]) for name in datasets},
        sources={EQUIBLES: _API, **{
            f"EQUIBLES.{name}": eq_access.source_url(path) for name, path in (paths or {}).items()
        }},
        errors=errors,
        warnings=warnings,
        providers_answered=[EQUIBLES] if datasets else [],
        degraded=any(issue["provider"] == EQUIBLES for issue in MONITOR.issues()),
        extra={
            **dict(subject),
            "tool": tool,
            "attribution": eq_access.ATTRIBUTION,
            "as_of": freshness.get("as_of"),
            "reporting_delay": reporting_delay,
            "access": access,
            "freshness": freshness,
            "params_applied": dict(params_applied or {}),
            "comparison_policy": "no Equibles value is merged with another provider",
        },
    )


async def fetch_blocks(
    tool: str,
    subject: Mapping[str, Any],
    blocks: Mapping[str, tuple[str, Mapping[str, Any] | None]],
    *,
    adjustments: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch named REST blocks concurrently while retaining partial failures."""
    params_applied = {name: dict(params or {}) for name, (_, params) in blocks.items()}
    names = tuple(blocks)
    coroutines = [eq_access.get(fragment, params=params) for fragment, params in blocks.values()]

    async def guard(name: str, operation: _CORO) -> Any:
        """Return a raw object or a sanitized dataset error without cancelling peers."""
        try:
            payload = await operation
            if not isinstance(payload, dict):
                raise ValueError("non-object provider response")
            return {"payload": payload}
        except Exception as exc:  # noqa: BLE001 - error is part of the response contract
            code = "NO_DATA" if isinstance(exc, NoDataError) else error_code(exc)
            message = getattr(exc, "message", None) or type(exc).__name__
            return {"error": {"provider": EQUIBLES, "code": code, "message": message, "dataset": name}}

    results = await asyncio.gather(*(guard(name, coro) for name, coro in zip(names, coroutines)))
    payloads = {name: result["payload"] for name, result in zip(names, results) if "payload" in result}
    errors = [result["error"] for result in results if "error" in result]
    return response(
        tool, subject, datasets=payloads,
        paths={name: f"/{blocks[name][0]}" for name in names}, errors=errors,
        dataset_names=names, params_applied=params_applied, adjustments=adjustments,
    )


async def one(
    tool: str,
    subject: Mapping[str, Any],
    dataset: str,
    fragment: str,
    params: Mapping[str, Any] | None = None,
    *,
    adjustments: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch exactly one named dataset with no hidden pagination."""
    return await fetch_blocks(tool, subject, {dataset: (fragment, params)}, adjustments=adjustments)
