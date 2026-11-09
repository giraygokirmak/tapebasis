"""Providers, their capabilities and the shared response envelope.

Every tool in tapebasis returns a :class:`dict` shaped by :func:`envelope`.
The first-class field is ``data_provider``: an LLM reading the tool result
must always be able to tell which provider(s) actually supplied the numbers it
is about to quote.

Providers are first-class peers, asked in parallel:

``TRADINGVIEW``  TradingView's scanner and chart websocket.
``FINVIZ``       finviz.com HTML and JSON islands.
``YAHOO``        query1.finance.yahoo.com chart API.
``SA``           stockanalysis.com's consolidated quote API, US equities/ETFs.
``BLOOMBERG``    bloomberg.com public quote pages, a leg with a known delay.

``ALL`` means **every provider that was asked answered**. It is a statement
about coverage, not about agreement. Agreement is a separate axis: it lives in
``comparisons[].match`` and is summarised in ``notice``.

``NONE`` means no provider answered; no value is presented.

Bloomberg is a full leg: it is asked in parallel, its readings appear in
``comparisons[].values``, and it contributes to ``ALL`` / ``providers_answered``.
Two of its properties need saying out loud rather than being hidden by a
tolerance:

* its equity and index prints are exchange-delayed (``exchangeDelay`` is
  ``15 Minutes``), so a pair of prints that is further apart than the skew
  guard allows is reported as **not comparable** rather than as a
  disagreement, and it never wins the freshness tie-break against a live
  print;
* its static fields (previous close, 52-week range, closing price) are
  penny-identical to Yahoo's, so agreement between those two is weak
  corroboration, not two independent witnesses.

Both facts are reported in the payload (``exchange_delay``, ``print_time``,
``comparisons[].pairs[].not_comparable``), so an agent can tell a real
cross-check from a delayed duplicate.

StockAnalysis is a full leg too, on the same terms: asked in parallel on every
US equity/ETF quote, its readings in ``comparisons``, counted in ``ALL``. Its
quote surface is the same consolidated tape Yahoo serves, so the two agree
penny-for-penny by construction rather than by independent measurement; that is
stated rather than presented as two witnesses. It sits immediately before
Bloomberg in the documented order: a live feed, but the narrowest coverage (US
equities and ETFs, no indices, FX, crypto, commodities or foreign listings), so it should not
outrank a broader feed on a tie.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable


class DataProvider(str, Enum):
    """Which provider(s) supplied the data in a response."""

    ALL = "ALL"
    TRADINGVIEW = "TRADINGVIEW"
    FINVIZ = "FINVIZ"
    YAHOO = "YAHOO"
    SA = "SA"
    BLOOMBERG = "BLOOMBERG"
    NONE = "NONE"


class Verification(str, Enum):
    """How strongly the payload is corroborated.

    ``MULTI_SOURCE``  two or more providers answered (``ALL``).
    ``SINGLE_SOURCE`` exactly one provider answered (a provider name).
    ``UNAVAILABLE``   no provider answered (``NONE``).
    """

    MULTI_SOURCE = "MULTI_SOURCE"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    UNAVAILABLE = "UNAVAILABLE"


#: Every provider label that participates in reconciliation, in display order.
#: Bloomberg and StockAnalysis are last because they are the legs whose
#: coverage is narrowest or whose prints can be structurally older: order only
#: matters for display and for the documented tie-break.
PROVIDER_ORDER: tuple[str, ...] = (
    "TRADINGVIEW", "FINVIZ", "YAHOO", "SA", "BLOOMBERG"
)

#: Human-readable name for each provider, used in notices and docs.
PROVIDER_NAMES: dict[str, str] = {
    "TRADINGVIEW": "TradingView",
    "FINVIZ": "Finviz",
    "YAHOO": "Yahoo Finance",
    "SA": "StockAnalysis",
    "BLOOMBERG": "Bloomberg",
}


def verification_for(provider: DataProvider) -> Verification:
    """Map a provider label onto its corroboration strength."""
    if provider is DataProvider.ALL:
        return Verification.MULTI_SOURCE
    if provider is DataProvider.NONE:
        return Verification.UNAVAILABLE
    return Verification.SINGLE_SOURCE


#: Human-readable sentence the LLM is expected to relay to the user.
PROVIDER_MEANING: dict[DataProvider, str] = {
    DataProvider.ALL: (
        "Every provider that was asked answered this request. Coverage is "
        "``ALL``. Agreement is a separate axis: check `comparisons` for "
        "whether the readings match."
    ),
    DataProvider.TRADINGVIEW: (
        "Data came from TRADINGVIEW only. The other providers did not supply "
        "this field, so the value is single-source and NOT corroborated."
    ),
    DataProvider.FINVIZ: (
        "Data came from FINVIZ only. The other providers did not supply this "
        "field, so the value is single-source and NOT corroborated."
    ),
    DataProvider.YAHOO: (
        "Data came from YAHOO only. The other providers did not supply this "
        "field, so the value is single-source and NOT corroborated."
    ),
    DataProvider.SA: (
        "Data came from SA (StockAnalysis) only. The other providers did not "
        "supply this field, so the value is single-source and NOT corroborated. "
        "StockAnalysis covers US equities and ETFs; its quote surface is the same "
        "consolidated tape Yahoo serves, so read agreement between those two as "
        "weak corroboration, not two independent witnesses."
    ),
    DataProvider.BLOOMBERG: (
        "Data came from BLOOMBERG only. The other providers did not supply this "
        "field, so the value is single-source and NOT corroborated. Bloomberg's "
        "equity and index quotes are exchange-delayed; check `exchange_delay` and "
        "`print_time` before calling a price live."
    ),
    DataProvider.NONE: (
        "No provider could supply this data. Do not present any value for it."
    ),
}


class ProviderError(Exception):
    """A single provider failed for a single call."""

    def __init__(self, provider: str, message: str, *, code: str = "PROVIDER_ERROR", **extra: Any):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message
        self.code = code
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "code": self.code,
            "message": self.message,
            **({"detail": self.extra} if self.extra else {}),
        }


def error_code(exc: BaseException, default: str = "PROVIDER_ERROR") -> str:
    """Extract a stable error code from any provider exception.

    Provider errors carry either an ``ErrorCode`` enum or a plain string; both
    must survive to the envelope unchanged.
    """
    code = getattr(exc, "code", None)
    if code is None:
        return default
    value = getattr(code, "value", None)
    return str(value if value is not None else code)


class NoDataError(Exception):
    """A provider answered but had nothing for this request (not a failure)."""

    def __init__(self, provider: str, message: str):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message


class NotApplicable(Exception):
    """This provider does not serve this instrument class at all.

    Distinct from :class:`NoDataError`: "Finviz has no spot-gold page" is not a
    failure and must not appear in ``errors`` nor drag the response toward
    ``NONE``. The reconciler records it as ``NOT_ATTEMPTED``.
    """

    def __init__(self, provider: str, message: str):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def envelope(
    data: Any,
    *,
    provider: DataProvider,
    verification: Verification | None = None,
    fields: dict[str, DataProvider] | None = None,
    comparisons: Iterable[dict[str, Any]] = (),
    sources: dict[str, str] | None = None,
    errors: Iterable[dict[str, Any]] | dict[str, Any] = (),
    warnings: Iterable[str] | str = (),
    degraded: bool = False,
    providers_answered: Iterable[str] = (),
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical response envelope.

    Args:
        data: The payload itself (already reconciled).
        provider: Overall :class:`DataProvider` for the response.
        verification: Defaults to the documented value for ``provider``.
        fields: Per-field provider map, e.g. ``{"price": DataProvider.ALL}``.
        comparisons: Per-field comparison rows from the reconciler.
        sources: Provider -> upstream URL/identifier that produced the data.
        errors: One or more provider error dicts.
        warnings: Human-readable caution strings (promoted into ``notice``).
        degraded: True when the health monitor reports an upstream schema drift
            or an outage relevant to this call.
        providers_answered: Provider labels that actually produced data.
        extra: Additional top-level keys to merge into the envelope.

    Returns:
        ``dict`` carrying ``data_provider``, ``verification``, ``notice``,
        ``data`` plus diagnostics.
    """
    verification = verification or verification_for(provider)
    if isinstance(errors, dict):
        errors = [errors]
    if isinstance(warnings, str):
        warnings = [warnings]

    answered = list(providers_answered)
    notice = PROVIDER_MEANING[provider]
    if provider is not DataProvider.ALL and provider is not DataProvider.NONE:
        notice += " Treat this as single-source data and say so when reporting it."
    if degraded:
        notice += (
            " WARNING: the provider health monitor reports an upstream change/outage, "
            "see tapebasis_health."
        )

    payload: dict[str, Any] = {
        "data_provider": provider.value,
        "verification": verification.value,
        "providers_answered": answered,
        "notice": notice,
        "data": data,
        "fields": {k: v.value for k, v in (fields or {}).items()},
        "comparisons": list(comparisons),
        "sources": sources or {},
        "errors": list(errors),
        "warnings": list(warnings),
        "degraded": degraded,
        "generated_at": _utcnow(),
    }
    if extra:
        payload.update(extra)
    return payload


def provider_from_answered(answered: Iterable[str]) -> DataProvider:
    """Map the set of providers that answered onto a :class:`DataProvider`.

    ``ALL`` is coverage: it means every provider that was *asked* answered.
    Callers pass every label that answered here.
    """
    present = {str(p).upper() for p in answered if p}
    if not present:
        return DataProvider.NONE
    if len(present) >= 2:
        return DataProvider.ALL
    return DataProvider(next(iter(present)))
