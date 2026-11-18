"""Admit only equivalent Equibles observations into shared reconciliation.

No network call is made without ``TAPEBASIS_EQUIBLES_API_KEY``. Short interest
additionally requires the explicit Enterprise redistribution assertion. These
adapters never supply live prices, option contracts or ownership populations.
"""
from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Iterable, Mapping

from . import eq_access
from .reconcile import EQUIBLES, FINVIZ

_EPS_METRICS = {"eps", "earningspershare"}


def configured() -> bool:
    """Return whether an authenticated Equibles adapter may be asked."""
    return bool(eq_access.api_key())


def _number(value: Any) -> int | float | None:
    """Return a finite number, preserving zero and rejecting booleans."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return int(result) if result.is_integer() else result


def _date(value: Any) -> str | None:
    """Return a valid ISO date, never inferring a missing settlement date."""
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _dimension(value: Any) -> str:
    """Return a stable serialized dimension signature for exact comparison."""
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def analyst_observations(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return documented EPS means with unmodified source observations.

    Comparison requires an explicit metric, quarter, mean statistic, currency
    unit, basis and dimension values. ``dimAnalystCount`` is numeric only when
    supplied as a number. The ``analyst`` display string is never parsed into
    a contributor count, and it is unrelated to rating or target populations.
    """
    observations: list[dict[str, Any]] = []
    for row in payload.get("data") or []:
        if not isinstance(row, dict) or metric_label(row.get("metric")) not in _EPS_METRICS:
            continue
        observations.append({
            **row,
            "dimAnalystCount": _number(row.get("dimAnalystCount")),
        })
    return observations


def analyst_counts(observations: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return EPS-estimate contributor counts keyed by their explicit period."""
    counts: dict[str, dict[str, Any]] = {}
    for row in observations:
        period = row.get("period")
        if not period:
            continue
        counts[str(period)] = {
            "population": "eps_estimate_contributors",
            "statistic": row.get("statistic"),
            "analyst_count": row.get("dimAnalystCount"),
            "analyst_count_source": (
                "EQUIBLES" if row.get("dimAnalystCount") is not None else None
            ),
            "analyst_display": row.get("analyst"),
            "captured_at": row.get("capturedAt"),
            "verified_at": row.get("verifiedAt"),
            "source": "Data by Equibles",
            "single_source": True,
        }
    return counts


async def fetch_analyst_observations(ticker: str) -> dict[str, Any]:
    """Return one authenticated analyst page and its actual supplied counts."""
    ticker = eq_access.ticker_for(ticker)
    path = f"stocks/{ticker}/analyst-estimates"
    payload = await eq_access.get(
        path, params={"metric": "EPS", "limit": 100, "offset": 0},
    )
    observations = analyst_observations(payload)
    return {
        "observations": observations,
        "eps_estimate_analyst_counts": analyst_counts(observations),
        "attribution": eq_access.ATTRIBUTION,
        "freshness": eq_access.freshness_for({"analyst_estimates": payload}),
        "source": eq_access.source_url("/" + path),
    }


def short_interest_observations(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return dated FINRA ``shortPosition`` shares, excluding all other metrics."""
    rows = []
    for row in payload.get("data") or []:
        if not isinstance(row, dict):
            continue
        settlement = _date(row.get("settlementDate"))
        shares = _number(row.get("shortPosition"))
        if settlement is not None and shares is not None:
            rows.append({
                **row, "settlement_date": settlement,
                "short_interest_shares": shares, "unit": "shares",
            })
    return rows


async def fetch_short_interest_observations(ticker: str) -> dict[str, Any]:
    """Return same-date candidates after both key and Enterprise gates pass."""
    ticker = eq_access.ticker_for(ticker)
    path = f"securities/{ticker}/short-interest"
    payload = await eq_access.get(
        path, params={"limit": 500, "offset": 0}, enterprise=True,
    )
    return {
        "observations": short_interest_observations(payload),
        "attribution": eq_access.ATTRIBUTION,
        "freshness": eq_access.freshness_for({"short_interest": payload}),
        "source": eq_access.source_url("/" + path),
    }


def allocate_analyst_counts(
    finviz_payload: Mapping[str, Any] | None,
    equibles_payload: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Attach counts only to exactly labelled Finviz periods, not EPS consensus."""
    allocations: dict[str, dict[str, Any]] = {}
    counts = (equibles_payload or {}).get("eps_estimate_analyst_counts") or {}
    for row in (finviz_payload or {}).get("quarterly") or []:
        if not isinstance(row, dict):
            continue
        period = row.get("fiscalPeriod")
        if period in counts:
            allocations[f"eps_estimate_{period}"] = counts[period]
    return allocations


def metric_label(value: Any) -> str:
    """Return a normalized metric identifier without matching period aliases."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def estimate_context(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return exact EPS context, or no context when a required dimension is absent."""
    statistic = row.get("statistic")
    unit = row.get("unit")
    basis = row.get("basis")
    period = row.get("period")
    if any(not isinstance(value, str) or not value.strip() for value in (statistic, unit, basis, period)):
        return None
    return {
        "metric": "EPS", "period": period, "statistic": statistic,
        "unit": unit, "basis": basis, "dimensions": _dimension(row.get("dimensions")),
    }


def compare_earnings(
    finviz_payload: Mapping[str, Any] | None,
    equibles_payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare only exact, unique, fully evidenced EPS estimate contexts.

    Finviz supplies a current row's explicit context through normalization. A
    conventional provider meaning is not treated as evidence of a unit or basis.
    Every candidate stays visible in its own row; declined comparisons never
    acquire an agreement or disagreement verdict, and count sidecars remain
    separate from rating or price-target analyst populations.
    """
    from .reconcile import compare_values, compared_providers, field_source

    candidates = []
    for row in (finviz_payload or {}).get("quarterly") or []:
        if not isinstance(row, dict) or _number(row.get("epsEstimate")) is None:
            continue
        period = row.get("fiscalPeriod")
        if not isinstance(period, str) or not period:
            continue
        # Finviz names its period ``fiscalPeriod``; give the shared context
        # reader that exact label rather than silently borrowing a quarter.
        context = estimate_context({**row, "period": period})
        candidates.append({
            "period": period,
            "value": _number(row["epsEstimate"]),
            "context": context,
        })

    observations = (equibles_payload or {}).get("observations") or []
    contexts = [(row, estimate_context(row)) for row in observations]
    data: dict[str, Any] = {}
    fields: dict[str, dict[str, Any]] = {}
    comparisons: list[dict[str, Any]] = []
    declined: list[dict[str, Any]] = []
    for candidate in candidates:
        name = f"eps_estimate_{candidate['period']}"
        context = candidate["context"]
        if context is None:
            # The Finviz row publishes no unit, basis or dimensions of its own.
            # Declining is the honest outcome: treating its conventional
            # meaning as evidence would manufacture a consensus.
            declined.append({
                "field": name,
                "reason": (
                    "Finviz supplies no explicit EPS statistic, unit, basis "
                    "and dimensions for this period"
                ),
            })
            continue
        matched = [
            (row, other) for row, other in contexts
            if other == context and _number(row.get("value")) is not None
        ]
        if len(matched) != 1:
            declined.append({
                "field": name,
                "reason": "no unique exact metric, period, statistic, unit, basis and dimensions match",
            })
            continue
        row, matched_context = matched[0]
        values = {FINVIZ: candidate["value"], EQUIBLES: _number(row.get("value"))}
        comparison = compare_values(values, tolerance_pct=0.1)
        comparison.update({
            "field": name, "observation_context": matched_context,
            "equibles_captured_at": row.get("capturedAt"),
            "equibles_verified_at": row.get("verifiedAt"),
            "chosen": FINVIZ,
        })
        data[name] = candidate["value"]
        fields[name] = field_source(
            FINVIZ, compared_providers(comparison), comparison.get("match"), supplied=list(values),
        )
        comparisons.append(comparison)
    return {
        "data": data, "fields": fields, "comparisons": comparisons,
        "eps_estimate_analyst_counts": allocate_analyst_counts(finviz_payload, equibles_payload),
        "declined_comparisons": declined,
        "attribution": (equibles_payload or {}).get("attribution"),
        "freshness": (equibles_payload or {}).get("freshness"),
    }


def _finviz_short_rows(payload: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    """Return Finviz thousands converted once to settlement-date shares."""
    for row in payload.get("history") or []:
        if not isinstance(row, dict):
            continue
        settlement = _date(row.get("date"))
        thousands = _number(row.get("short_interest_shares_k"))
        if settlement is not None and thousands is not None:
            yield {
                **row, "settlement_date": settlement,
                "short_interest_shares": thousands * 1000,
                "conversion": "short_interest_shares_k * 1000", "unit": "shares",
            }


def compare_short_interest(
    finviz_payload: Mapping[str, Any] | None,
    equibles_payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare Finviz's latest share count with the same Equibles settlement date."""
    from .reconcile import compare_values, compared_providers, field_source

    rows = list(_finviz_short_rows(finviz_payload or {}))
    eq_rows = short_interest_observations({
        "data": (equibles_payload or {}).get("observations") or [],
    })
    if not rows:
        return {"data": {}, "fields": {}, "comparisons": [], "status": "no_finviz_reading"}
    latest = rows[-1]
    matched = [row for row in eq_rows if row["settlement_date"] == latest["settlement_date"]]
    if len(matched) != 1:
        comparison = {
            "field": "short_interest_shares",
            "values": {FINVIZ: latest["short_interest_shares"]},
            "match": None, "not_comparable": True,
            "reason": "no unique Equibles shortPosition reading with the same FINRA settlementDate",
            "settlement_dates": {
                FINVIZ: latest["settlement_date"],
                EQUIBLES: sorted({row["settlement_date"] for row in eq_rows}),
            },
            "pairs": [],
        }
        return {"data": {}, "fields": {}, "comparisons": [comparison], "status": "not_comparable"}
    values = {
        FINVIZ: latest["short_interest_shares"],
        EQUIBLES: matched[0]["short_interest_shares"],
    }
    comparison = compare_values(values, tolerance_pct=0.01)
    comparison.update({
        "field": "short_interest_shares", "observation_date": latest["settlement_date"],
        "unit": "shares", "basis": "FINRA settlement-date short position",
        "chosen": FINVIZ, "finviz_conversion": latest["conversion"],
    })
    return {
        "data": {"short_interest_shares": latest["short_interest_shares"]},
        "fields": {"short_interest_shares": field_source(
            FINVIZ, compared_providers(comparison), comparison.get("match"), supplied=list(values),
        )},
        "comparisons": [comparison], "status": "compared",
    }
