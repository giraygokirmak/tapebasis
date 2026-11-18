"""Authenticated, read-only access to Equibles' documented REST API.

Equibles is a separate single-provider surface, not a price-reconciliation leg.
Only the official ``https://api.equibles.com/v1`` routes are used; this module
never reads an Equibles web page. The API key stays in the ``Authorization``
header and neither the key nor upstream error text appears in an exception.

There is no local paid-plan assertion or preflight tier: the documented route
and the account's real API response decide access. A paid-plan dataset
that responds 403 becomes ``PLAN_REQUIRED``, never an empty or reduced result.

Only routes named in :data:`ROUTES` may be requested. Redirects are refused so
a bearer header can never follow a location to another origin.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
import weakref
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping
from urllib.parse import quote, unquote

import httpx

from . import __version__
from .http_pool import shared_client
from .providers_state import NoDataError, ProviderError
from .ratelimit import call, limiter

PROVIDER = "EQUIBLES"
BASE_URL = "https://api.equibles.com/v1"
ATTRIBUTION = "Data by Equibles"
_POOL = "equibles"
# Only the quota check plus the corresponding one HTTP call is serialized.
# This is deliberately per event loop, like http_pool/ratelimit's own locks.
# Ordinary transport pacing remains in the shared ProviderLimiter, so this lock
# does not replace its cooldown, inflight or configured retry behavior.
_QUOTA_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = (
    weakref.WeakKeyDictionary()
)
_TIMEOUT = float(os.environ.get("TAPEBASIS_EQUIBLES_TIMEOUT", "30"))
_CACHE_TTL = float(os.environ.get("TAPEBASIS_EQUIBLES_CACHE_TTL", "900"))

#: Every documented JSON read route this server may call. The set is the
#: allowlist: a route outside it is refused before transport. Account-owned
#: portfolio, organization, tracker and binary-asset routes are not exposed.
ROUTES: frozenset[str] = frozenset({
    "/stocks/{ticker}/analyst-estimates",
    "/stocks/{ticker}/buyback-programs",
    "/stocks/{ticker}/atm-programs",
    "/stocks/{exchange}/{ticker}/filings",
    "/stocks/{exchange}/{ticker}/canadian-fund-holdings",
    "/stocks/{exchange}/{ticker}/insider-transactions",
    "/stocks/{exchange}/{ticker}/short-positions",
    "/fda/catalysts",
    "/cftc/contracts",
    "/cftc/contracts/{marketCode}/positions",
    "/cftc/positions/latest",
    "/congress/members",
    "/congress/trades",
    "/congress/members/{id}/net-worth",
    "/congress/market-activity",
    "/stocks/{ticker}/correlated",
    "/crypto",
    "/crypto/{symbol}/quote",
    "/crypto/quotes",
    "/crypto/{symbol}/prices",
    "/crypto/{symbol}/bars",
    "/stocks/{ticker}/debt-profile",
    "/stocks/{ticker}/debt-instruments/{instrumentId}",
    "/stocks/{ticker}/dividends",
    "/stocks/{ticker}/investor-events",
    "/investor-events/recent",
    "/stocks/{ticker}/earnings-calls/{fiscalYear}/{fiscalQuarter}",
    "/stocks/{ticker}/earnings-calls/{fiscalYear}/{fiscalQuarter}/speakers",
    "/investor-events/{eventId}/speakers",
    "/stocks/{ticker}/earnings-calls/{fiscalYear}/{fiscalQuarter}/live-transcript",
    "/investor-events/{eventId}/live-transcript",
    "/stocks/{ticker}/earnings-calls/{fiscalYear}/{fiscalQuarter}/questions",
    "/investor-events/{eventId}/questions",
    "/stocks/{ticker}/earnings-calls/phrase-trend",
    "/stocks/{ticker}/earnings-briefs",
    "/stocks/{ticker}/call-insights",
    "/stocks/{ticker}/call-themes/history",
    "/investor-events/{eventId}/slides",
    "/etfs",
    "/etfs/{ticker}",
    "/etfs/{ticker}/holdings",
    "/stocks/{exchange}/{ticker}/director-transactions",
    "/stocks/{exchange}/{ticker}/financial-reports",
    "/stocks/{exchange}/{ticker}/financial-reports/native",
    "/stocks/{exchange}/{ticker}/financial-reports/native/{reportId}",
    "/stocks/{exchange}/{ticker}/european-fund-holdings",
    "/stocks/{ticker}/filings",
    "/filings",
    "/filings/{documentId}/lines",
    "/filings/{documentId}/keyword-search",
    "/stocks/{ticker}/fails-to-deliver",
    "/securities/{ticker}/fails-to-deliver",
    "/stocks/{ticker}/exempt-offerings",
    "/stocks/{ticker}/financial-statements/{statement}",
    "/stocks/{ticker}/financial-facts/{concept}",
    "/fred/series",
    "/fred/series/{seriesId}/observations",
    "/fred/latest",
    "/fred/calendar",
    "/stocks/{ticker}/revenue-breakdown",
    "/stocks/{ticker}/customer-concentration",
    "/stocks/{ticker}/going-concern",
    "/funds",
    "/funds/{ticker}/holdings",
    "/funds/{ticker}/operations",
    "/stocks/{ticker}/fund-owners",
    "/securities/{ticker}/fund-owners",
    "/investment-advisers",
    "/investment-advisers/{crd}",
    "/stocks/{ticker}/government-contracts",
    "/stocks/{exchange}/{ticker}/government-contracts",
    "/government-contracts/top",
    "/stocks/{ticker}/guidance",
    "/13f/flows",
    "/stocks/{ticker}/ownership-signals",
    "/securities/{ticker}/ownership-signals",
    "/stocks/{ticker}/holder-targets",
    "/securities/{ticker}/holder-targets",
    "/stocks/{ticker}/institutional-holders",
    "/securities/{ticker}/institutional-holders",
    "/stocks/{ticker}/institutional-ownership",
    "/securities/{ticker}/institutional-ownership",
    "/stocks/{ticker}/holder-mix",
    "/securities/{ticker}/holder-mix",
    "/stocks/{ticker}/institutional-activity",
    "/securities/{ticker}/institutional-activity",
    "/13f/market-activity",
    "/13f/most-held",
    "/indexes",
    "/indexes/{index}",
    "/indexes/{index}/changes",
    "/indexes/{index}/forecast",
    "/indexes/{index}/fund-flows",
    "/stocks/{ticker}/insider-transactions",
    "/stocks/{ticker}/insider-ownership",
    "/stocks/{ticker}/proposed-sales",
    "/insiders",
    "/insider-sentiment-scores",
    "/institutions",
    "/institutions/{cik}/portfolio",
    "/institutions/{cik}/summary",
    "/institutions/{cik}/profile",
    "/institutions/{cik}/style-history",
    "/institutions/{cik}/sector-allocation",
    "/institutions/{cik}/activity",
    "/institutions/{cik}/beneficial-ownership",
    "/stocks/{ticker}/ir-news",
    "/stocks/{ticker}/ir-events",
    "/stocks/{ticker}/shareholder-votes",
    "/super-investors",
    "/consensus-holdings",
    "/ipos",
    "/ipos/{cik}",
    "/stocks/{ticker}/kpis",
    "/stocks/{ticker}/non-gaap-bridge",
    "/listings",
    "/markets",
    "/stocks/{ticker}",
    "/stocks/{exchange}/{ticker}/major-holdings",
    "/market/put-call-ratios",
    "/market/vix",
    "/market/status",
    "/market/calendar",
    "/stocks/{ticker}/valuation-multiples",
    "/stocks/{ticker}/valuation-multiples/history",
    "/stocks/{ticker}/options/expirations",
    "/securities/{ticker}/options/expirations",
    "/stocks/{ticker}/options/chain",
    "/securities/{ticker}/options/chain",
    "/stocks/{ticker}/options/contract",
    "/securities/{ticker}/options/contract",
    "/stocks/{ticker}/options/contract/bars",
    "/securities/{ticker}/options/contract/bars",
    "/stocks/{ticker}/options/contract/trades",
    "/securities/{ticker}/options/contract/trades",
    "/stocks/{ticker}/options/session",
    "/securities/{ticker}/options/session",
    "/stocks/{ticker}/options/summary",
    "/securities/{ticker}/options/summary",
    "/stocks/{ticker}/options/term-structure",
    "/securities/{ticker}/options/term-structure",
    "/stocks/{ticker}/options/volatility",
    "/securities/{ticker}/options/volatility",
    "/stocks/{ticker}/options/strategy",
    "/securities/{ticker}/options/strategy",
    "/stocks/{ticker}/executive-changes",
    "/stocks/{ticker}/executive-compensation",
    "/stocks/{exchange}/{ticker}/public-short-positions",
    "/stocks/{ticker}/quote",
    "/securities/{ticker}/quote",
    "/quotes",
    "/screener/stocks",
    "/filings/search",
    "/stocks/{ticker}/filings/search",
    "/filings/{documentId}/search",
    "/stocks/{ticker}/short-volume",
    "/securities/{ticker}/short-volume",
    "/stocks/{ticker}/short-interest",
    "/securities/{ticker}/short-interest",
    "/stocks/{ticker}/short-interest/forecast",
    "/stocks/{ticker}/off-exchange-volume",
    "/securities/{ticker}/off-exchange-volume",
    "/short-interest/snapshot",
    "/short-volume/largest",
    "/short-squeeze-scores",
    "/stocks/{exchange}/{ticker}/short-disclosures",
    "/stocks/{ticker}/bars",
    "/securities/{ticker}/bars",
    "/stocks/{ticker}/holders",
    "/securities/{ticker}/holders",
    "/stocks/{ticker}/ownership-summary",
    "/securities/{ticker}/ownership-summary",
    "/stocks/{ticker}/beneficial-ownership",
    "/securities/{ticker}/beneficial-ownership",
    "/stocks/{ticker}/prices",
    "/securities/{ticker}/prices",
    "/prices/latest",
    "/stocks/{ticker}/technicals/atr",
    "/securities/{ticker}/technicals/atr",
    "/stocks/{ticker}/technicals/bollinger-bands",
    "/securities/{ticker}/technicals/bollinger-bands",
    "/stocks/{ticker}/technicals/obv",
    "/securities/{ticker}/technicals/obv",
    "/stocks/{ticker}/technicals/stochastic",
    "/securities/{ticker}/technicals/stochastic",
    "/stocks/{ticker}/splits",
    "/stocks/{ticker}/supply-chain",
    "/stocks/{ticker}/supply-chain/overlap",
})

_ROUTE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(
        "^"
        + "/".join(
            r"[^/]+" if part.startswith("{") else re.escape(part)
            for part in template.strip("/").split("/")
        )
        + "$"
    )
    for template in ROUTES
)

_US_TICKER = re.compile(r"[A-Z]{1,5}(?:[.-][A-Z])?")


def _env_number(name: str, default: float) -> float:
    """Read a non-negative environment override, or return its default."""
    try:
        return max(0.0, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _quota_lock() -> asyncio.Lock:
    """Return the loop-local lock that makes a quota observation and send atomic.

    Callers waiting behind the lock re-read the shared daily reset deadline
    before transport. A 429 observed by one caller therefore prevents all
    queued callers from spending more of an exhausted daily allowance, even if
    another component raised the ordinary shared limiter's inflight setting.
    """
    loop = asyncio.get_running_loop()
    lock = _QUOTA_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _QUOTA_LOCKS[loop] = lock
    return lock


def api_key() -> str:
    """Return the key without exposing it in logs or payloads."""
    return os.environ.get("TAPEBASIS_EQUIBLES_API_KEY", "").strip()


def route_allowed(path: str) -> bool:
    """Return whether a safely encoded relative route is on the allowlist.

    ``get`` percent-encodes the colon in a MIC:TICKER path value. That single
    encoding is equivalent to a literal colon and is safe to normalize before
    matching. Every other percent encoding, including a second encoding pass,
    stays invalid so a path cannot change meaning after the allowlist check.
    """
    normalized = re.sub(r"%3a", ":", path, flags=re.IGNORECASE)
    if unquote(normalized) != normalized:
        return False
    if re.search(r"(?:^|%)(?:2f|5c|3f|23)|[?#\\]|\.\.", path, re.IGNORECASE):
        return False
    return any(pattern.match(normalized.strip("/")) for pattern in _ROUTE_PATTERNS)


def ticker_for(symbol: str) -> str:
    """Normalize a US ticker without resolving it through another provider.

    Args:
        symbol: Bare US ticker, optionally with a conventional exchange prefix.

    Returns:
        The Equibles spelling of the symbol, with share classes using a dash.

    Raises:
        NoDataError: For an FX pair, a non-US venue, an unsafe path fragment or
            any other query that is not a mechanical US-listed ticker.
    """
    raw = (symbol or "").strip().upper().replace(" ", "")
    if ":" in raw:
        exchange, _, candidate = raw.rpartition(":")
        if exchange not in {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS", "NASDAQGS", "NASDAQGM", "NASDAQCM"}:
            raise NoDataError(PROVIDER, "these tools accept US-listed tickers only")
        raw = candidate
    if not _US_TICKER.fullmatch(raw):
        raise NoDataError(
            PROVIDER,
            f"{symbol!r} is not a mechanical US ticker; FX pairs, crypto symbols "
            "and foreign venues are not accepted",
        )
    return raw.replace(".", "-")


def _path(fragment: str) -> str:
    """Quote each path segment and return an API-relative route."""
    return "/" + "/".join(quote(part, safe="") for part in fragment.strip("/").split("/"))


def source_url(path: str) -> str:
    """Return the credential-free upstream URL for response provenance."""
    return f"{BASE_URL}{path}"


def _iso_parts(value: Any) -> tuple[str | None, bool]:
    """Convert a provider timestamp to UTC ISO and report whether it was date-only."""
    if value is None or isinstance(value, bool):
        return None, False
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(), False
        except (OverflowError, OSError, ValueError):
            return None, False
    text = str(value).strip()
    if not text:
        return None, False
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return _iso_parts(float(text))
    date_only = len(text) == 10
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return (text if date_only else None), date_only
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(), date_only


def _iso(value: Any) -> str | None:
    """Convert one provider timestamp to UTC ISO, preserving unknown values as null."""
    return _iso_parts(value)[0]


def _first(payload: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    """Return the first present, non-null field from an upstream mapping."""
    for name in names:
        if payload.get(name) is not None:
            return payload[name]
    return None


def _record_times(value: Any, date_keys: tuple[str, ...]) -> list[tuple[str, bool]]:
    """Collect observation dates from every nested record, not only top-level keys."""
    found: list[tuple[str, bool]] = []
    if isinstance(value, dict):
        for key in date_keys:
            stamp, date_only = _iso_parts(value.get(key))
            if stamp:
                found.append((stamp, date_only))
        for item in value.values():
            if isinstance(item, (dict, list)):
                found.extend(_record_times(item, date_keys))
    elif isinstance(value, list):
        for item in value:
            found.extend(_record_times(item, date_keys))
    return found


# Observation fields differ by legal/economic meaning. Choosing one global
# maximum across all of them would make an insider filing date displace the
# transaction date, or a statement filing date displace its fiscal period.
# Guidance is an event about disclosure, so its filedDate is the relevant event
# time; for statements it is retained separately as publication_at instead.
_OBSERVATION_FIELDS: dict[str, tuple[str, ...]] = {
    "profile": (),
    "financial_statement": ("periodEnd", "reportPeriodDate", "asOfDate"),
    "revenue_breakdown": ("periodEnd", "reportPeriodDate", "asOfDate"),
    "debt_profile": ("asOfDate", "periodEnd", "reportPeriodDate"),
    "guidance": ("filedDate",),
    "proposed_sales": ("filingDate",),
    "insider_transactions": ("transactionDate",),
    "institutional_ownership": ("reportPeriodDate", "periodEnd", "asOfDate"),
    "institutional_activity": ("reportPeriodDate", "periodEnd", "asOfDate"),
    "fund_owners": ("reportPeriodDate", "periodEnd", "asOfDate"),
    "analyst_estimates": ("capturedAt", "verifiedAt"),
    "short_interest": ("settlementDate",),
    "short_volume": ("volumeSession", "date"),
    "fails_to_deliver": ("settlementDate", "date"),
    "off_exchange_volume": ("weekStartDate",),
    "options_summary": ("underlyingCloseDate", "openInterestDate"),
    "options_term_structure": ("underlyingCloseDate", "openInterestDate"),
    "price_history": ("date",),
}
_FALLBACK_OBSERVATION_FIELDS = (
    "asOf", "capturedAt", "verifiedAt", "periodEnd", "asOfDate",
    "reportDate", "reportPeriodDate", "settlementDate", "weekStartDate",
    "underlyingCloseDate", "volumeSession", "openInterestDate", "date",
)
_PUBLICATION_FIELDS = ("filedDate", "filingDate")


def freshness_for(
    payloads: Mapping[str, Any],
    *,
    delayed: Any = None,
    date_keys: tuple[str, ...] = _FALLBACK_OBSERVATION_FIELDS,
) -> dict[str, Any]:
    """Describe per-dataset observation times without mixing date semantics.

    The timestamp comes from provider observations, never from local cache or
    MCP response time. Known datasets use their own observation fields: fiscal
    periods for statements, transactionDate for insiders, filedDate for
    guidance, settlementDate for short interest and underlying close/open
    interest dates for options. Filing/publication dates remain visible in a
    separate ``publication_at`` field and never displace those observations.
    Missing dates stay null. An option ``expiration`` is a schedule, not an
    observation. A false delayed flag is not proof of real-time access.

    Args:
        payloads: Named raw Equibles response bodies for this tool call.
        delayed: Upstream delay flag, used only to retain a stated delay.
        date_keys: Fallback observation fields for an unknown dataset name.

    Returns:
        Serializable freshness metadata, including per-dataset observation and
        publication timestamps and whether the chosen observation was date-only.
    """
    stamps: dict[str, Any] = {}
    observations: dict[str, bool] = {}
    for name, payload in payloads.items():
        if not isinstance(payload, (dict, list)):
            continue
        fields = _OBSERVATION_FIELDS.get(name, date_keys)
        rows = _record_times(payload, fields) if fields else []
        publication_rows = _record_times(payload, _PUBLICATION_FIELDS)
        for stamp, date_only in rows:
            observations[stamp] = observations.get(stamp, True) and date_only
        latest = max((stamp for stamp, _ in rows), default=None)
        stamps[name] = {
            "as_of": latest,
            "as_of_date_only": observations.get(latest, False) if latest else None,
            "latest_observation_at": latest,
            "earliest_observation_at": min((stamp for stamp, _ in rows), default=None),
            "publication_at": max((stamp for stamp, _ in publication_rows), default=None),
            "observation_fields": list(fields),
            "basis": "dataset-specific provider observations; publication is separate",
        }
        if isinstance(payload, dict) and payload.get("delayed") is True:
            stamps[name]["delayed"] = True
            stamps[name]["delay_status"] = "delayed indicative quotes reported by Equibles"
    latest = max(observations, default=None)
    return {
        "as_of": latest,
        "as_of_date_only": observations.get(latest, False) if latest else None,
        "basis": "provider observations; filing availability can be later than the observation date",
        "datasets": stamps,
        "delayed": delayed is True,
        "delay_status": (
            "delayed indicative quotes reported by Equibles"
            if delayed is True else "not stated as delayed by Equibles; not a real-time claim"
        ),
        "note": (
            "For historical observations, as_of describes the values, not when they became public "
            "or how old they are at retrieval. Preserve each dataset's own reporting delay."
        ),
    }


def _retry_delay(response: httpx.Response) -> float | None:
    """Extract a bounded Retry-After duration without inspecting message text."""
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _quota(response: httpx.Response) -> dict[str, Any]:
    """Extract public quota counters, excluding credentials and upstream prose."""
    limit = response.headers.get("X-RateLimit-Limit")
    remaining = response.headers.get("X-RateLimit-Remaining")
    reset = response.headers.get("X-RateLimit-Reset")
    return {
        "daily_limit": int(limit) if limit and limit.isdigit() else None,
        "remaining": int(remaining) if remaining and remaining.isdigit() else None,
        "reset_at": _iso(reset),
    }


def _blocked_until(response: httpx.Response) -> float:
    """Return the epoch when a quota-blocked account may be asked again."""
    delayed = _retry_delay(response)
    if delayed is not None:
        return time.time() + delayed
    reset = response.headers.get("X-RateLimit-Reset")
    if reset and reset.isdigit():
        return float(reset)
    return time.time() + 60.0


def _cache_identity(path: str, query: Mapping[str, Any]) -> str:
    """Return a cache key that changes with the key fingerprint.

    The raw credential is never part of the key: a rotating key must not reuse a
    previous key's cached payload, but the key itself must not be retained in a
    dict that a diagnostic could print.
    """
    identity = repr(sorted(query.items()))
    fingerprint = hashlib.sha256(api_key().encode()).hexdigest()[:16]
    return f"{path}?{identity}&key={fingerprint}"


async def request(
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    cache: bool = True,
) -> dict[str, Any]:
    """Read one official Equibles API route with pacing and a bounded cache.

    Args:
        path: Route relative to ``/v1``, supplied by this package, not a URL.
        params: Optional query parameters. Credentials are never accepted here.
        cache: Use the key-scoped cached result when true. Live transcripts pass
            false so an incrementally changing text is never served stale.
    Returns:
        The decoded JSON object. Response objects stay intact so units, filing
        provenance and partial coverage remain the provider's own statements.

    Raises:
        ProviderError: With stable ``NOT_CONFIGURED``, ``PLAN_REQUIRED``,
            ``UPSTREAM_RATE_LIMIT``, ``UPSTREAM_ERROR`` or ``SCHEMA_DRIFT`` code.
        NoDataError: For a missing listing or period.
    """
    if not route_allowed(path):
        raise ProviderError(
            PROVIDER,
            "this route is not on the documented Equibles allowlist; no request was made",
            code="PROVIDER_ERROR",
        )
    key = api_key()
    if not key:
        raise ProviderError(
            PROVIDER,
            "Set TAPEBASIS_EQUIBLES_API_KEY to use Equibles' REST API; no request was made.",
            code="NOT_CONFIGURED",
        )
    query = {name: value for name, value in (params or {}).items() if value is not None}
    forbidden = {
        name for name in query
        if re.search(r"(?:authorization|api.?key|access.?token|bearer|secret)", name, re.IGNORECASE)
    }
    if forbidden:
        raise ProviderError(
            PROVIDER, "credentials are accepted only from TAPEBASIS_EQUIBLES_API_KEY",
            code="PROVIDER_ERROR",
        )
    if any(str(value).lower() == "csv" for name, value in query.items() if name == "format"):
        raise ProviderError(PROVIDER, "only JSON responses are supported", code="PROVIDER_ERROR")
    paced = limiter(PROVIDER)
    cache_key = _cache_identity(path, query)
    cached = paced.cache_get(cache_key, _env_number("TAPEBASIS_EQUIBLES_CACHE_TTL", _CACHE_TTL))
    if cache and isinstance(cached, dict):
        return cached
    blocked = float(getattr(paced, "equibles_blocked_until", 0.0) or 0.0)
    if blocked > time.time():
        raise ProviderError(
            PROVIDER,
            "Equibles daily request quota is exhausted; no new request was made. "
            "The reset is reported in health quota.",
            code="UPSTREAM_RATE_LIMIT",
        )

    async def _once() -> dict[str, Any]:
        # This check is inside the limiter-protected operation as well as before
        # it. The general inflight/cooldown/retry settings are untouched, while
        # this narrower lock prevents two concurrent Equibles calls from both
        # crossing the gate before either has observed the other's daily 429.
        async with _quota_lock():
            blocked = float(getattr(paced, "equibles_blocked_until", 0.0) or 0.0)
            if blocked > time.time():
                raise ProviderError(
                    PROVIDER,
                    "Equibles daily request quota is exhausted; no new request was made. "
                    "The reset is reported in health quota.",
                    code="UPSTREAM_RATE_LIMIT",
                )

            client = shared_client(
                _POOL,
                timeout=_env_number("TAPEBASIS_EQUIBLES_TIMEOUT", _TIMEOUT),
                follow_redirects=False,
            )
            headers = {
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
                "User-Agent": f"tapebasis/{__version__} (official Equibles REST API)",
            }
            try:
                response = await client.get(
                    source_url(path), params=query, headers=headers,
                    timeout=_env_number("TAPEBASIS_EQUIBLES_TIMEOUT", _TIMEOUT),
                )
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    PROVIDER, "Equibles REST API timed out", code="UPSTREAM_TIMEOUT"
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(
                    PROVIDER, f"Equibles REST API transport failed: {type(exc).__name__}",
                    code="UPSTREAM_ERROR",
                ) from exc
            paced.equibles_quota = _quota(response)
            if response.status_code == 429:
                paced.equibles_blocked_until = _blocked_until(response)
                raise ProviderError(
                    PROVIDER,
                    "Equibles daily request quota exhausted; no retry was made. "
                    "The reset is reported in health quota.",
                    code="UPSTREAM_RATE_LIMIT",
                )
            if response.is_redirect:
                raise ProviderError(
                    PROVIDER,
                    "Equibles answered with a redirect; refusing to forward the credential",
                    code="UPSTREAM_ERROR",
                )
            if response.status_code == 401:
                paced.equibles_blocked_until = 0.0
                raise ProviderError(
                    PROVIDER, "Equibles rejected the configured API key; check or replace it",
                    code="NOT_CONFIGURED",
                )
            if response.status_code == 403:
                raise ProviderError(
                    PROVIDER,
                    "The Equibles plan does not include this dataset; upgrade the plan or "
                    "remove the dataset from this call. No result was downgraded.",
                    code="PLAN_REQUIRED",
                )
            if response.status_code == 404:
                raise NoDataError(PROVIDER, "Equibles has no matching listing or period")
            if response.status_code >= 400:
                raise ProviderError(
                    PROVIDER,
                    f"Equibles REST API answered HTTP {response.status_code}",
                    code="UPSTREAM_ERROR",
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderError(
                    PROVIDER, "Equibles returned invalid JSON", code="SCHEMA_DRIFT"
                ) from exc
            if not isinstance(payload, dict):
                raise ProviderError(
                    PROVIDER, "Equibles response was not a JSON object", code="SCHEMA_DRIFT"
                )
            paced.equibles_blocked_until = 0.0
            if cache:
                paced.cache_set(cache_key, payload)
            return payload

    # One request per call. ``attempts=0`` prevents the shared limiter from
    # retrying after a 429, which would spend a second request on a daily quota
    # that is already exhausted.
    return await call(PROVIDER, _once, attempts=0)


async def get(
    fragment: str,
    *,
    params: Mapping[str, Any] | None = None,
    cache: bool = True,
) -> dict[str, Any]:
    """Read an allowlisted relative JSON route and return its decoded object."""
    return await request(_path(fragment), params=params, cache=cache)


__all__ = [
    "ATTRIBUTION",
    "BASE_URL",
    "PROVIDER",
    "ROUTES",
    "api_key",
    "freshness_for",
    "get",
    "request",
    "route_allowed",
    "source_url",
    "ticker_for",
]
