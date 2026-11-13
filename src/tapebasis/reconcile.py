"""Fan-out, comparison and fallback engine across N providers.

The rule this module implements:

* Ask every provider that can serve the field, in parallel.
* Compare the answers within a documented tolerance.
* Two or more answered -> ``ALL`` (coverage), agreement reported separately.
* Exactly one answered -> serve it, label it with that provider's name and say
  in the notice that it is single-source.
* A provider raised -> the other answers still go out; the failure is attached
  under ``errors``.
* Only when every provider fails is the response ``NONE``.

``ALL`` is a *coverage* statement, every provider that was asked answered. It
is not a claim that they agree; disagreement lives in ``comparisons[].match``
and is named in the notice.

Three entry points:

``ask``       run provider coroutines concurrently, never raise.
``merge``     compare provider payloads field-by-field into a ``Merged`` result.
``finalize``  build the public envelope from attempts plus shapers.
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence

from .providers_state import (
    DataProvider,
    NoDataError,
    NotApplicable,
    PROVIDER_MEANING,
    PROVIDER_NAMES,
    PROVIDER_ORDER,
    ProviderError,
    envelope,
    provider_from_answered,
)

__all__ = [
    "Attempt",
    "DEFAULT_ORDER",
    "FieldSpec",
    "KNOWN_REPORTING_LAG",
    "Merged",
    "Pair",
    "ask",
    "compare_numeric",
    "compare_symbol",
    "compare_values",
    "compared_providers",
    "field_source",
    "finalize",
    "merge",
    "merge_many",
    "notice_for",
    "providers_in",
    "single",
]

TRADINGVIEW = "TRADINGVIEW"
FINVIZ = "FINVIZ"
YAHOO = "YAHOO"
SA = "SA"
BLOOMBERG = "BLOOMBERG"

#: Tie-break order when no provider reports a usable print time, or two report
#: the identical instant. Fixed and documented rather than "whichever was asked
#: first", so the same inputs always resolve to the same number. Bloomberg is
#: last: when its delayed page ties with a live feed on the same instant, the
#: live feed is the reading to show. StockAnalysis sits just before it: it is a
#: live feed like the others, but its coverage is the narrowest (US equities and
#: ETFs), so it should never be preferred over a leg that carries the same
#: instrument more broadly when the two tie.
DEFAULT_ORDER: tuple[str, ...] = (FINVIZ, TRADINGVIEW, YAHOO, SA, BLOOMBERG)

#: Providers whose prints can be structurally older than a live feed's, with
#: the delay they declare and the sentence that explains it.
#:
#: This is a *comparability* rule, not a tolerance. Two prints one delay-length
#: apart are not "close enough": the older one describes the market as it was
#: then, and calling the difference a disagreement would blame the provider for
#: a delay it states. So a pair that includes such a provider is not comparable
#: as soon as the gap reaches the declared delay, and comparable below it (a
#: closed market prints both at the same instant, which is a real agreement).
KNOWN_REPORTING_LAG: dict[str, tuple[float, str]] = {
    BLOOMBERG: (
        900.0,
        "Bloomberg states that its equity and index quotes are exchange-delayed "
        "(15 Minutes), so the older print is the intended lag, not a conflict",
    ),
}


# ── Attempts ─────────────────────────────────────────────────────────────────


@dataclass
class Attempt:
    """Outcome of asking one provider one question."""

    provider: str
    ok: bool
    value: Any = None
    error: dict[str, Any] | None = None
    elapsed_ms: float = 0.0

    @property
    def failed(self) -> bool:
        return not self.ok

    @property
    def payload(self) -> dict[str, Any] | None:
        return self.value if self.ok and isinstance(self.value, dict) else None


@dataclass
class Pair:
    """The attempts that make up one reconciled response.

    Named ``Pair`` for historical reasons; it carries any number of providers.
    ``tv``/``fv``/``yh`` are convenience accessors so a two-provider tool reads
    naturally.
    """

    attempts: dict[str, Attempt] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Back-compat: Pair(tv=..., fv=...) is still accepted by callers that
        # build it positionally in tests.
        pass

    @property
    def tv(self) -> Attempt:
        return self._get(TRADINGVIEW)

    @property
    def fv(self) -> Attempt:
        return self._get(FINVIZ)

    @property
    def yh(self) -> Attempt:
        return self._get(YAHOO)

    @property
    def sa(self) -> Attempt:
        return self._get(SA)

    @property
    def bb(self) -> Attempt:
        return self._get(BLOOMBERG)

    def _get(self, provider: str) -> Attempt:
        return self.attempts.get(
            provider,
            Attempt(
                provider,
                False,
                error={
                    "provider": provider,
                    "code": "NOT_ATTEMPTED",
                    "message": f"{provider} was not asked",
                },
            ),
        )

    def payload(self, provider: str) -> dict[str, Any] | None:
        return self._get(provider).payload

    @property
    def answered(self) -> list[str]:
        """Provider labels that actually produced a value, in display order."""
        present = [p for p, a in self.attempts.items() if a.ok]
        return sorted(present, key=lambda p: PROVIDER_ORDER.index(p) if p in PROVIDER_ORDER else 99)

    @property
    def asked(self) -> list[str]:
        """Provider labels this call actually asked, in display order.

        ``NOT_ATTEMPTED`` is excluded because it means "not asked": either the
        tool has no endpoint for this provider on this request, or the provider
        does not carry the instrument. A provider that *was* asked and failed
        (``NO_DATA``, ``PROVIDER_ERROR``, an upstream timeout) stays in this
        list, which is what makes the difference between ``ALL`` and
        ``PARTIAL`` visible.
        """
        asked = [
            p
            for p, a in self.attempts.items()
            if (a.error or {}).get("code") != "NOT_ATTEMPTED"
        ]
        return sorted(
            asked,
            key=lambda p: PROVIDER_ORDER.index(p) if p in PROVIDER_ORDER else 99,
        )

    @property
    def provider(self) -> DataProvider:
        return provider_from_answered(self.answered, self.asked)

    @property
    def errors(self) -> list[dict[str, Any]]:
        """Real failures only.

        ``NOT_ATTEMPTED`` means the provider has no endpoint for this
        capability at all (e.g. Finviz has no futures feed), that is not an
        error and must not be reported as one.
        """
        return [
            attempt.error
            for attempt in self.attempts.values()
            if attempt.failed
            and attempt.error
            and attempt.error.get("code") != "NOT_ATTEMPTED"
        ]


def _error_dict(provider: str, exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, ProviderError):
        return exc.to_dict()
    if isinstance(exc, NotApplicable):
        # Not a failure: this provider has no page/feed for this instrument.
        return {"provider": provider, "code": "NOT_ATTEMPTED", "message": exc.message}
    if isinstance(exc, NoDataError):
        return {"provider": provider, "code": "NO_DATA", "message": exc.message}
    return {
        "provider": provider,
        "code": "PROVIDER_ERROR",
        "message": f"{type(exc).__name__}: {exc}",
    }


async def _run(provider: str, fn: Callable[[], Awaitable[Any]]) -> Attempt:
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        value = await fn()
        elapsed = round((loop.time() - started) * 1000, 1)
        if value is None:
            return Attempt(
                provider,
                False,
                error={
                    "provider": provider,
                    "code": "NO_DATA",
                    "message": "provider returned no value",
                },
                elapsed_ms=elapsed,
            )
        return Attempt(provider, True, value=value, elapsed_ms=elapsed)
    except Exception as exc:  # noqa: BLE001 - the boundary must never leak
        return Attempt(
            provider,
            False,
            error=_error_dict(provider, exc),
            elapsed_ms=round((loop.time() - started) * 1000, 1),
        )


async def ask(
    tv_fn: Callable[[], Awaitable[Any]] | None = None,
    fv_fn: Callable[[], Awaitable[Any]] | None = None,
    yahoo_fn: Callable[[], Awaitable[Any]] | None = None,
    bb_fn: Callable[[], Awaitable[Any]] | None = None,
    sa_fn: Callable[[], Awaitable[Any]] | None = None,
) -> Pair:
    """Run every supplied provider call concurrently.

    A ``None`` callable means "this provider has no endpoint for this request"
    and is recorded as ``NOT_ATTEMPTED`` rather than as a failure, so it never
    shows up in ``errors`` or drags the response down to ``NONE``.
    """

    def _skip(provider: str) -> Attempt:
        return Attempt(
            provider,
            False,
            error={
                "provider": provider,
                "code": "NOT_ATTEMPTED",
                "message": f"{provider} has no endpoint for this request",
            },
        )

    plans: list[tuple[str, Callable[[], Awaitable[Any]] | None]] = [
        (TRADINGVIEW, tv_fn),
        (FINVIZ, fv_fn),
        (YAHOO, yahoo_fn),
        (SA, sa_fn),
        (BLOOMBERG, bb_fn),
    ]

    async def _plan(label: str, fn: Callable[[], Awaitable[Any]] | None) -> Attempt:
        # Wrapped in a coroutine so every gather argument is awaitable; a
        # skipped provider must not be passed to gather as a bare Attempt.
        if fn is None:
            return _skip(label)
        return await _run(label, fn)

    outcomes = await asyncio.gather(*(_plan(label, fn) for label, fn in plans))
    return Pair(attempts={attempt.provider: attempt for attempt in outcomes})


def single(provider: str, value: Any = None, *, error: dict[str, Any] | None = None) -> Pair:
    """Build a single-source pair (the other providers are NOT_ATTEMPTED)."""
    ok = error is None
    attempts: dict[str, Attempt] = {}
    for label in PROVIDER_ORDER:
        if label == provider:
            attempts[label] = Attempt(provider, ok, value=value, error=error)
        else:
            attempts[label] = Attempt(
                label,
                False,
                error={
                    "provider": label,
                    "code": "NOT_ATTEMPTED",
                    "message": f"{label} does not serve this capability",
                },
            )
    return Pair(attempts=attempts)


# ── Numeric comparison ───────────────────────────────────────────────────────


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if math.isnan(number) or math.isinf(number) else number
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "")
        if not text:
            return None
        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1]
        if text.endswith("%"):
            text = text[:-1]
        multiplier = 1.0
        if text and text[-1].upper() in {"K", "M", "B", "T"}:
            multiplier = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[text[-1].upper()]
            text = text[:-1]
        try:
            number = float(text) * multiplier
        except ValueError:
            # Finviz annotates some cells ("351.73 -5.64%", "1.2M (3.4%)").
            # The leading token is the value; the rest is distance/context.
            head = text.split(" ", 1)[0]
            try:
                number = float(head) * multiplier
            except ValueError:
                return None
        return -number if negative else number
    return None


def compare_numeric(
    tv_value: Any,
    fv_value: Any,
    *,
    tolerance_pct: float = 0.5,
    absolute_floor: float = 0.0,
) -> dict[str, Any]:
    """Compare two numeric values within a relative tolerance.

    ``absolute_floor`` raises the denominator so small readings (a 0.01 move)
    are not flagged over rounding noise.
    """
    tv_number, fv_number = _as_float(tv_value), _as_float(fv_value)
    row: dict[str, Any] = {
        "tv": tv_value,
        "fv": fv_value,
        "match": None,
        "diff": None,
        "diff_pct": None,
        "tolerance_pct": tolerance_pct,
    }
    if tv_number is None or fv_number is None:
        return row
    difference = abs(tv_number - fv_number)
    denominator = max(abs(tv_number), abs(fv_number), absolute_floor, 1e-12)
    difference_pct = difference / denominator * 100
    row.update(
        match=difference_pct <= tolerance_pct,
        diff=round(difference, 6),
        diff_pct=round(difference_pct, 4),
    )
    return row


def compare_symbol(tv_value: Any, fv_value: Any) -> dict[str, Any]:
    """Compare symbols case-insensitively, rejecting blank values."""
    tv_norm = str(tv_value).strip().upper() if tv_value is not None else None
    fv_norm = str(fv_value).strip().upper() if fv_value is not None else None
    tv_norm = tv_norm or None
    fv_norm = fv_norm or None
    match = None if tv_norm is None or fv_norm is None else tv_norm == fv_norm
    return {"tv": tv_value, "fv": fv_value, "match": match}


def compare_values(
    values: Mapping[str, Any],
    *,
    kind: str = "numeric",
    tolerance_pct: float = 0.5,
    absolute_floor: float = 0.0,
    times: Mapping[str, Any] | None = None,
    max_skew_seconds: float | None = None,
    session_boundary: bool = False,
    max_age_seconds: float | None = None,
    now: datetime | None = None,
    not_comparable_reason: str | None = None,
    require_all_times: bool = False,
    sessions: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    """Compare the same field across N providers.

    Produces ``values`` (provider -> raw reading), pairwise ``diff`` rows, and a
    single ``match``: ``True`` when every pair of readings that can be compared
    agrees, ``False`` when any pair disagrees, ``None`` when no pair reached a
    verdict, including when fewer than two providers reported a usable value.

    ``times`` + ``max_skew_seconds`` exist because some fields are only
    comparable when the readings describe the *same* observation. A day
    change percentage is quoted against the previous close of the session the
    print belongs to, so Finviz's pre-market reading and Yahoo's regular-close
    reading legitimately differ, flagging that as a provider conflict would be
    a false alarm. Such a pair is recorded as not comparable (``match: None``
    with a ``reason``) and left out of the agreement decision, while every
    reading stays visible in ``values``.

    Four independent checks narrow what may be compared, in increasing order of
    what they can see:

    * ``max_skew_seconds``: distance between the two prints. Blind to a session
      roll, and blind to every provider freezing together.
    * ``KNOWN_REPORTING_LAG``: a delay the provider itself declares (Bloomberg
      states 15 minutes on equities and indices). At that distance the pair is
      two observations, and the reason names the delay instead of blaming the
      provider for a lag it documents.
    * ``session_boundary``: different US/Eastern session date. Catches a roll
      that a seconds-based ceiling cannot, and is deliberately one-way: it can
      lose a comparison, never manufacture a conflict.
    * ``max_age_seconds`` + ``now``: the only check that looks at the clock, so
      the only one that can see a feed that froze mid-session. Inert when no
      reference clock is passed, which keeps tests and replays deterministic.

    ``not_comparable_reason`` is for a field that has no shared definition in the
    first place, where no amount of timestamp checking helps: FX has no single
    official previous close, so each provider derives its own roll and the day
    changes are answers to different questions. The readings are kept and the
    pair is reported as not comparable with that reason. ``sessions`` names the
    trading session each reading came from. Different named sessions are never
    a conflict between providers. Undated session reads cannot establish that
    they describe the same observation.
    """
    from .freshness import parse_market_timestamp, session_date

    present = {p: v for p, v in values.items() if v is not None}
    row: dict[str, Any] = {
        "values": present,
        "match": None,
        "diff": None,
        "diff_pct": None,
        "tolerance_pct": tolerance_pct,
        "pairs": [],
    }
    labels = [p for p in PROVIDER_ORDER if p in present]
    if len(labels) < 2:
        return row
    if not_comparable_reason is not None:
        # Structurally not the same measurement, at any timestamp. Say so once
        # and leave the numbers visible rather than pretending they disagree.
        for index, left in enumerate(labels):
            for right in labels[index + 1:]:
                row["pairs"].append(
                    {
                        "between": [left, right],
                        "tv": present.get(left),
                        "fv": present.get(right),
                        "match": None,
                        "diff": None,
                        "diff_pct": None,
                        "tolerance_pct": tolerance_pct,
                        "not_comparable": not_comparable_reason,
                    }
                )
        row["not_comparable"] = True
        return row

    stamps: dict[str, Any] = {}
    if times and (
        max_skew_seconds is not None
        or require_all_times
        or session_boundary
        or (max_age_seconds is not None and now is not None)
    ):
        stamps = {p: parse_market_timestamp(times.get(p)) for p in labels}

    def _skew_reason(left: str, right: str) -> str | None:
        if not stamps:
            return None
        a, b = stamps.get(left), stamps.get(right)
        if a is None or b is None:
            if require_all_times:
                return (
                    "at least one provider reported no print time, so the "
                    "readings cannot be shown to describe the same observation"
                )
            return None
        if session_boundary:
            day_a, day_b = session_date(a), session_date(b)
            if day_a is not None and day_b is not None and day_a != day_b:
                return (
                    f"prints belong to different sessions ({day_a} and {day_b}), "
                    f"so the readings are not the same observation"
                )
        if max_age_seconds is not None and now is not None:
            for label, stamp in ((left, a), (right, b)):
                # Only inside one session date: a quote legitimately ages
                # overnight and across a long weekend, so a wall-clock ceiling
                # applied across a boundary would fire on correct data.
                if session_date(stamp) != session_date(now):
                    continue
                age = (now - stamp).total_seconds()
                if age > max_age_seconds:
                    return (
                        f"{label}'s print is {age / 60:.0f}m old within the same "
                        f"session, past the {max_age_seconds / 60:.0f}m ceiling; "
                        f"the feed looks frozen, so agreement cannot be asserted"
                    )
        gap = abs((a - b).total_seconds())
        # A declared feed delay is a comparability boundary of its own: at one
        # delay-length apart the two prints are the same market at two instants.
        for label in (left, right):
            declared = KNOWN_REPORTING_LAG.get(label)
            if declared and gap >= declared[0]:
                return (
                    f"prints are {gap / 60:.0f}m apart, at least the "
                    f"{declared[0] / 60:.0f}m delay this provider declares for the "
                    f"feed, so the readings do not describe the same observation. "
                    f"{declared[1]}"
                )
        if max_skew_seconds is None:
            return None
        if gap <= max_skew_seconds:
            return None
        return (
            f"prints are {gap / 60:.0f}m apart, past the "
            f"{max_skew_seconds / 60:.0f}m window, so the readings do not "
            f"describe the same observation"
        )

    matches: list[bool] = []
    max_diff = 0.0
    max_diff_pct = 0.0
    for i, left in enumerate(labels):
        for right in labels[i + 1:]:
            if kind == "symbol":
                pair = compare_symbol(present[left], present[right])
            else:
                pair = compare_numeric(
                    present[left],
                    present[right],
                    tolerance_pct=tolerance_pct,
                    absolute_floor=absolute_floor,
                )
            reason = None
            if sessions is not None:
                # Session labels are evidence of a different observation, or
                # of a missing proof, not an extra guard after timestamp skew.
                left_session = sessions.get(left)
                right_session = sessions.get(right)
                if left_session is not None or right_session is not None:
                    if left_session != right_session:
                        reason = (
                            f"prints belong to different trading sessions "
                            f"({left_session!r} and {right_session!r}), so the "
                            "readings are not the same observation"
                        )
                    elif stamps.get(left) is None or stamps.get(right) is None:
                        reason = (
                            f"the shared {left_session!r} session has no dated print "
                            "from every provider, so the readings cannot be shown "
                            "to describe the same observation"
                        )
            if reason is None:
                reason = _skew_reason(left, right)
            if reason is not None:
                pair = {
                    **pair,
                    "match": None,
                    "not_comparable": reason,
                }
            if pair["match"] is None:
                if reason is None:
                    if kind == "symbol":
                        reason = (
                            "at least one reading has no usable symbol value, so "
                            "the readings cannot be compared"
                        )
                    else:
                        reason = (
                            f"at least one reading is non-numeric "
                            f"({present[left]!r} or {present[right]!r}), so no "
                            "numeric pair can be compared"
                        )
                pair["not_comparable"] = reason
                row["pairs"].append({"between": [left, right], **pair})
                continue
            matches.append(pair["match"])
            if pair.get("diff") is not None:
                max_diff = max(max_diff, pair["diff"])
                max_diff_pct = max(max_diff_pct, pair["diff_pct"])
            row["pairs"].append({"between": [left, right], **pair})

    if matches:
        row["match"] = all(matches)
        row["diff"] = round(max_diff, 6)
        row["diff_pct"] = round(max_diff_pct, 4)
    elif row["pairs"]:
        row["not_comparable"] = True
    return row


# ── Field reconciliation ─────────────────────────────────────────────────────


@dataclass
class FieldSpec:
    """One comparable field: name, extractor on each side, comparison rule."""

    name: str
    tv_get: Callable[[dict[str, Any]], Any] | None = None
    fv_get: Callable[[dict[str, Any]], Any] | None = None
    kind: str = "numeric"
    tolerance_pct: float = 0.5
    absolute_floor: float = 0.0
    yh_get: Callable[[dict[str, Any]], Any] | None = None
    bb_get: Callable[[dict[str, Any]], Any] | None = None
    sa_get: Callable[[dict[str, Any]], Any] | None = None
    #: When set, readings whose observation times differ by more than this many
    #: seconds are reported as *not comparable* instead of as a disagreement.
    #: Applies to a session-relative field (a day change, a volume) and to a
    #: price: a price points at an instant, so two prints minutes apart are two
    #: observations rather than one number reported twice.
    #:
    #: The floor is the natural skew of two *live* endpoints, not zero: measured
    #: across TradingView and Yahoo it reaches ~600s on thin futures, so a
    #: tighter ceiling would throw away valid comparisons to look rigorous.
    max_skew_seconds: float | None = None
    #: Compare the US/Eastern session *date* of the two prints, not just their
    #: distance. A fixed ceiling cannot see the hazard this exists for: two
    #: prints 30 seconds apart that straddle a session roll are a whole session
    #: apart in meaning, and pass any seconds-based test.
    session_boundary: bool = False
    #: Absolute age ceiling, applied only when a reference clock is supplied and
    #: only within one session date. ``max_skew_seconds`` compares providers to
    #: each other, so a feed that froze while every provider froze passes it;
    #: this is the only check that looks at the clock. It is inert across a
    #: session boundary because a quote legitimately ages overnight and over a
    #: long weekend, which is why it cannot be a plain wall-clock test.
    max_age_seconds: float | None = None
    #: Set when the field has no shared definition across providers at all, so
    #: no timestamp check can make it comparable. FX day change is the case:
    #: there is no single official previous close, each provider picks its own
    #: roll, and the readings answer different questions.
    not_comparable_reason: str | None = None

    def extract(self, provider: str, payload: dict[str, Any]) -> Any:
        getter = {
            TRADINGVIEW: self.tv_get,
            FINVIZ: self.fv_get,
            YAHOO: self.yh_get,
            SA: self.sa_get,
            BLOOMBERG: self.bb_get,
        }.get(provider)
        return getter(payload) if getter else None


@dataclass
class Merged:
    """Result of comparing provider payloads field-by-field."""

    data: dict[str, Any] = field(default_factory=dict)
    #: Per-field provenance. Each key names the provider whose reading is in
    #: ``data``, every provider that supplied a reading for that field, and
    #: whether those readings agreed. Deliberately never a single ``ALL``
    #: label: ``data`` holds one value per field, so a field has one source.
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    comparisons: list[dict[str, Any]] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    provider: DataProvider = DataProvider.NONE
    answered: list[str] = field(default_factory=list)
    #: Fields whose readings were not judged at all, so comparing them would
    #: invent a conflict or an unprovable agreement. Reported, never counted as
    #: a disagreement. The reason is in ``comparisons[].pairs[].not_comparable``.
    not_comparable: list[str] = field(default_factory=list)
    #: Which provider supplied the resolved values, and why. ``None`` when the
    #: resolution was not a freshness decision (single-source, or no timestamps).
    chosen: str | None = None
    freshness: dict[str, Any] = field(default_factory=dict)


def compared_providers(comparison: Mapping[str, Any] | None) -> list[str]:
    """Providers whose reading was actually judged against another one.

    A comparison row records every pair it looked at under ``pairs``. A pair
    carries ``match: None`` plus a ``not_comparable`` reason when the two prints
    could not be judged (different sessions, a declared feed delay, no print
    time, no shared definition). Those pairs are *not* comparisons: nothing was
    concluded from them.

    Reading ``values`` instead answers a different question, and that is the
    mistake this function exists to stop. Five providers can supply a price
    while only three of the ten pairs are actually comparable, and then
    ``agreement: true`` would read as "all five agreed" when two of them were
    never judged.

    Args:
        comparison: A ``compare_values`` row, or ``None``.

    Returns:
        Every provider on a side of a pair that reached a verdict, in the
        comparison's own order, deduplicated. Empty when nothing was judged.
    """
    if not comparison:
        return []
    labels: list[str] = []
    for pair in comparison.get("pairs") or []:
        if pair.get("match") is None:
            continue
        for provider in pair.get("between") or ():
            if provider not in labels:
                labels.append(provider)
    return labels


def field_source(
    source: str,
    compared: Iterable[str] = (),
    agreement: bool | None = None,
    *,
    supplied: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Describe where one field's value came from.

    ``source`` is the provider whose reading was placed in ``data``. It is a
    single label, always: a response holds one value per field, so naming two or
    more providers there would imply the number is a joint product when it is
    one provider's print.

    ``supplied`` is every provider that returned a reading for the field, in
    display order. It answers "who answered", not "who was checked".

    ``compared`` is every provider whose reading was actually judged against
    another one. It is never wider than ``supplied``, and it is narrower when a
    pair could not be compared: two prints from different sessions are two
    observations, so nothing was concluded about them. ``agreement`` describes
    exactly that set: ``True`` every compared pair agrees, ``False`` a real
    disagreement, ``None`` nothing was judged (one reading, or no shared basis).

    The two lists exist because collapsing them made ``agreement: true`` read as
    "all five providers agreed" when only three of the ten pairs had been
    comparable at all. A caller that wants "who answered" reads ``supplied``; a
    caller that wants "who corroborated this number" reads ``compared``.

    For backwards compatibility ``compared`` also accepts the supplied set as
    its positional argument, which is what every caller meant before the split:
    pass ``supplied=`` explicitly when the two differ.

    A reader who wants the losing readings finds them in ``comparisons[].values``
    keyed by provider; a reader who wants the upstream finds it in
    ``sources[field_source()["source"]]``.
    """
    supplied_labels = [p for p in PROVIDER_ORDER if p in set(supplied or compared)]
    extra_supplied = [
        p for p in (supplied or compared) if p not in PROVIDER_ORDER
    ]
    supplied_labels.extend(p for p in extra_supplied if p not in supplied_labels)
    compared_labels = [p for p in PROVIDER_ORDER if p in set(compared)]
    compared_labels.extend(
        p for p in compared if p not in PROVIDER_ORDER and p not in compared_labels
    )
    if source and source not in supplied_labels:
        supplied_labels.insert(0, source)
    return {
        "source": source,
        "supplied": supplied_labels,
        "compared": compared_labels,
        "agreement": agreement,
    }


def _resolved_label(times: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Decide which provider's values to resolve to when several answered.

    The rule: whichever provider printed more recently wins. When several
    report the *same newest* instant, the documented default order breaks the
    tie, a fixed choice rather than an arbitrary one. Only the providers that
    share the newest instant are eligible, so a stale provider can never win a
    tie against fresher ones.

    ``freshness["decision"]`` is the machine-readable outcome
    (``newest`` / ``tie`` / ``no_timestamp``) so callers never have to parse
    the human sentence.
    """
    from .freshness import parse_market_timestamp

    parsed = {p: parse_market_timestamp(t) for p, t in times.items()}
    known = {p: m for p, m in parsed.items() if m is not None}
    order_text = ", ".join(DEFAULT_ORDER)
    stamps = {p.lower(): (parsed[p].isoformat() if parsed.get(p) else None) for p in times}

    if not known:
        fallback = next((p for p in DEFAULT_ORDER if p in times), DEFAULT_ORDER[0])
        return fallback, {
            **stamps,
            "chosen": fallback,
            "decision": "no_timestamp",
            "reason": (
                f"no provider reported a usable market timestamp; value taken from "
                f"{fallback}, first available in the documented order ({order_text})"
            ),
        }

    newest = max(known.values())
    leaders = [p for p, m in known.items() if m == newest]

    if len(leaders) == 1:
        winner = leaders[0]
        return winner, {
            **stamps,
            "chosen": winner,
            "decision": "newest",
            "newest_print": newest.isoformat(),
            "reason": f"{winner} printed most recently ({newest.isoformat()})",
        }

    winner = next(
        (p for p in DEFAULT_ORDER if p in leaders),
        sorted(leaders)[0],
    )
    tied = ", ".join(sorted(leaders, key=lambda p: DEFAULT_ORDER.index(p)))
    return winner, {
        **stamps,
        "chosen": winner,
        "decision": "tie",
        "newest_print": newest.isoformat(),
        "tied": sorted(leaders, key=lambda p: DEFAULT_ORDER.index(p)),
        "reason": (
            f"{tied} printed at the same instant ({newest.isoformat()}); "
            f"{winner} wins the documented order ({order_text})"
        ),
    }


def _pick(value_for: Callable[[str], Any], order: Sequence[str]) -> tuple[Any, str | None]:
    """First provider in ``order`` that has a value for this field."""
    for provider in order:
        value = value_for(provider)
        if value is not None:
            return value, provider
    return None, None


def merge_many(
    payloads: Mapping[str, dict[str, Any] | None],
    specs: Sequence[FieldSpec],
    *,
    shapes: Mapping[str, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
    times: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> Merged:
    """Compare N provider payloads; resolve each field to a single value.

    When two or more providers answered, every compared field resolves to **one**
    value: the reading from whichever provider printed more recently. All raw
    readings stay in ``comparisons``, so the choice is auditable but the caller
    never has to reconcile several numbers to answer "what is the price".

    Agreement is a separate axis. A field the providers disagree on is listed in
    ``mismatches`` and named in the notice; it is still resolved to one value,
    because a response with several prices for one instrument is a worse answer
    than one price plus a stated conflict.
    """
    present = {p: v for p, v in payloads.items() if v is not None}
    answered = [
        p for p in PROVIDER_ORDER if p in present
    ]
    if not present:
        return Merged(provider=DataProvider.NONE)

    if len(present) == 1:
        provider = answered[0]
        shape = (shapes or {}).get(provider)
        payload = present[provider]
        shaped = shape(payload) if shape else dict(payload)
        return Merged(
            data=shaped,
            fields={
                key: field_source(provider, (), None, supplied=[provider])
                for key in shaped
            },
            provider=DataProvider(provider),
            answered=[provider],
        )

    out = Merged(provider=DataProvider.ALL, answered=answered)
    chosen, freshness = _resolved_label(times or {})
    if chosen not in present:
        # A provider can resolve as the freshest name but still not have a
        # payload; fall back to the first answered provider in default order.
        chosen = next(
            (p for p in DEFAULT_ORDER if p in present),
            answered[0],
        )
        freshness["chosen"] = chosen
    out.chosen = chosen
    out.freshness = freshness
    order = [chosen] + [
        p for p in DEFAULT_ORDER if p != chosen and p in present
    ]

    for spec in specs:
        values = {p: spec.extract(p, present[p]) for p in answered}
        row = compare_values(
            values,
            kind=spec.kind,
            tolerance_pct=spec.tolerance_pct,
            absolute_floor=spec.absolute_floor,
            times=times,
            max_skew_seconds=spec.max_skew_seconds,
            session_boundary=spec.session_boundary,
            max_age_seconds=spec.max_age_seconds,
            now=now,
            not_comparable_reason=spec.not_comparable_reason,
        )
        row["field"] = spec.name
        out.comparisons.append(row)

        value, source = _pick(lambda p: values.get(p), order)
        if value is not None:
            out.data[spec.name] = value
            supplied = [p for p, reading in values.items() if reading is not None]
            # The value is one provider's reading, so ``source`` names that one
            # provider. ``supplied`` is who answered, ``compared`` is who was
            # actually checked against whom, and ``agreement`` describes that
            # second set. Collapsing the two made ``agreement: true`` read as
            # "every provider agreed" when most pairs could not be judged: five
            # prices, ten pairs, three comparable.
            out.fields[spec.name] = field_source(
                str(source),
                compared_providers(row),
                row.get("match"),
                supplied=supplied,
            )
            row["chosen"] = source
        if row["match"] is False:
            out.mismatches.append(spec.name)
        elif row.get("not_comparable"):
            out.not_comparable.append(spec.name)

    # Everything a provider shaped but the spec list did not cover, freshest
    # provider first so its own extras are not overwritten by a stale provider.
    # ``setdefault`` means the first writer wins, so this iterates ``order``
    # (chosen first) rather than its reverse: reversing it let the *stalest*
    # provider fill every uncontested field, which is how a fresh Finviz
    # industry ended up replaced by a stale TradingView one.
    for provider in order:
        shape = (shapes or {}).get(provider)
        if not shape:
            continue
        for key, value in shape(present[provider]).items():
            out.data.setdefault(key, value)
            out.fields.setdefault(
                key, field_source(provider, (), None, supplied=[provider])
            )
    return out


def merge(
    tv_payload: dict[str, Any] | None,
    fv_payload: dict[str, Any] | None,
    specs: Sequence[FieldSpec],
    *,
    tv_shape: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    fv_shape: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    tv_time: Any = None,
    fv_time: Any = None,
    yahoo_payload: dict[str, Any] | None = None,
    yh_shape: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    yahoo_time: Any = None,
) -> Merged:
    """Partial :func:`merge_many`, for calls where some providers were not asked."""
    return merge_many(
        {TRADINGVIEW: tv_payload, FINVIZ: fv_payload, YAHOO: yahoo_payload},
        specs,
        shapes={
            TRADINGVIEW: tv_shape or (lambda p: dict(p)),
            FINVIZ: fv_shape or (lambda p: dict(p)),
            YAHOO: yh_shape or (lambda p: dict(p)),
        },
        times={
            TRADINGVIEW: tv_time,
            FINVIZ: fv_time,
            YAHOO: yahoo_time,
        },
    )


# ── Envelope assembly ────────────────────────────────────────────────────────


def _provider_phrase(answered: Iterable[str]) -> str:
    labels = [PROVIDER_NAMES.get(p, p) for p in answered]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def notice_for(merged: Merged) -> str:
    """Provider notice, extended with agreement and freshness explanation."""
    base = PROVIDER_MEANING[merged.provider]
    if merged.provider in (DataProvider.ALL, DataProvider.PARTIAL):
        if merged.provider is DataProvider.ALL:
            base = (
                f"Every provider asked answered ({_provider_phrase(merged.answered)}). "
                "Coverage is ALL; agreement is a separate axis."
            )
        else:
            base = (
                f"Not every provider asked answered; these did: "
                f"{_provider_phrase(merged.answered)}. Coverage is PARTIAL, not "
                "ALL; the failures are listed in `errors`. Agreement is a "
                "separate axis."
            )
    else:
        return base

    chosen = merged.chosen or DEFAULT_ORDER[0]
    freshness = merged.freshness or {}
    decision = freshness.get("decision")

    if merged.mismatches:
        if decision == "newest":
            why = f" The value shown is {chosen}'s because it printed more recently."
        elif decision == "tie":
            why = (
                f" The showing providers printed at the same instant, so the value "
                f"shown is {chosen}'s (documented order)."
            )
        else:
            why = ""
        base += (
            " NOTE: the providers disagree on "
            + ", ".join(merged.mismatches)
            + "; every reading appears in `comparisons` and the response holds a "
            f"single value.{why} The conflict is reported, not silently resolved."
        )
    else:
        if merged.comparisons:
            if any(row.get("match") is True for row in merged.comparisons):
                base += " Compared fields agree within tolerance."
            elif all(row.get("match") is None for row in merged.comparisons):
                base += " No compared fields reached an agreement verdict."
        if decision == "newest":
            base += (
                f" The value shown is {chosen}'s because it printed more recently "
                "than the other providers'."
            )
        elif decision == "tie":
            base += (
                f" The showing providers printed at the same instant, so the value "
                f"shown is {chosen}'s (documented order)."
            )
    if merged.not_comparable:
        base += (
            " Not cross-checked, because the providers' readings have no shared "
            "basis for comparison: " + ", ".join(merged.not_comparable) + "."
        )
    return base


def _identity(payload: dict[str, Any]) -> dict[str, Any]:
    return payload


def _comparison_label(row: Mapping[str, Any]) -> str:
    """Name a comparison row by symbol when a batch has repeated fields."""
    symbol = row.get("symbol")
    field = str(row.get("field") or "")
    return f"{symbol}.{field}" if symbol else field


def finalize(
    pair: Pair,
    *,
    specs: Sequence[FieldSpec] = (),
    tv_norm: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    fv_norm: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    yh_norm: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    sa_norm: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    bb_norm: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    tv_shape: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    fv_shape: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    yh_shape: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    sa_shape: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    bb_shape: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    tv_time: Any = None,
    fv_time: Any = None,
    yahoo_time: Any = None,
    sa_time: Any = None,
    bb_time: Any = None,
    now: datetime | None = None,
    sources: dict[str, str] | None = None,
    warnings: Iterable[str] = (),
    degraded: bool = False,
    extra: dict[str, Any] | None = None,
    additional_errors: Iterable[dict[str, Any]] = (),
    health_warn: Iterable[str] | None = None,
    data: Any = None,
    provider: DataProvider | None = None,
    answered: Iterable[str] | None = None,
    comparisons: list[dict[str, Any]] | None = None,
    fields: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reconcile attempts and wrap the result in the public envelope.

    ``additional_errors`` appends capability-specific failures to
    ``pair.errors`` rather than replacing those primary-provider failures.
    Other extra keys are merged into the envelope as before.

    ``tv_norm``/``fv_norm``/``yh_norm``/``sa_norm``/``bb_norm`` map a raw
    provider payload into the normalised field dict that ``specs`` read from;
    when given, every remaining normalised field is attached to the output
    labelled with its source provider.

    ``tv_time``/``fv_time``/``yahoo_time``/``sa_time``/``bb_time`` are the
    **market print** timestamps (not fetch times). When providers answered, every
    compared field resolves to the freshest provider's reading; all originals
    stay in ``comparisons``. ``bb_time`` is passed explicitly because Bloomberg's
    print time is derived from the intraday series, never from ``lastUpdate``.

    ``now`` is the reference clock for a field's absolute-age ceiling. Pass it
    when the tool can observe the real time: without it the frozen-feed guard is
    inert, which keeps test fixtures (dated in the past) deterministic.

    ``data``/``provider``/``answered``/``comparisons``/``fields`` override the
    reconciled payload, label, comparison verdicts and per-field provenance;
    tools that compose a richer payload
    than the field list use them, and the notice is rebuilt so it still states
    the true providers and any mismatches.
    """
    payloads: dict[str, dict[str, Any] | None] = {}
    shapes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
    for label, attempt, norm, shape in (
        (TRADINGVIEW, pair.tv, tv_norm, tv_shape),
        (FINVIZ, pair.fv, fv_norm, fv_shape),
        (YAHOO, pair.yh, yh_norm, yh_shape),
        (SA, pair.sa, sa_norm, sa_shape),
        (BLOOMBERG, pair.bb, bb_norm, bb_shape),
    ):
        payload = attempt.payload
        if payload is not None and norm is not None:
            payload = norm(payload)
            shape = shape or _identity
        payloads[label] = payload
        if shape is not None:
            shapes[label] = shape

    times: dict[str, Any] = {}
    for label, explicit, payload in (
        (TRADINGVIEW, tv_time, payloads.get(TRADINGVIEW)),
        (FINVIZ, fv_time, payloads.get(FINVIZ)),
        (YAHOO, yahoo_time, payloads.get(YAHOO)),
        (SA, sa_time, payloads.get(SA)),
        (BLOOMBERG, bb_time, payloads.get(BLOOMBERG)),
    ):
        stamp = explicit
        if stamp is None and payload is not None:
            stamp = payload.get("price_timestamp")
        if stamp is not None:
            times[label] = stamp

    merged = merge_many(payloads, specs, shapes=shapes, times=times, now=now)
    if data is not None:
        merged.data = data
    if answered is not None:
        merged.answered = list(answered)
    if comparisons is not None:
        merged.comparisons = comparisons
        merged.mismatches = list(dict.fromkeys(
            _comparison_label(row)
            for row in comparisons
            if row.get("match") is False
        ))
        merged.not_comparable = list(dict.fromkeys(
            _comparison_label(row)
            for row in comparisons
            if row.get("not_comparable")
        ))
    if fields is not None:
        merged.fields = fields
    if provider is not None:
        merged.provider = provider
    elif merged.answered:
        # ``merge_many`` only sees payloads, so it cannot tell "this provider was
        # never asked" from "it was asked and failed". The pair can. Coverage is
        # therefore recomputed from it, so an unasked leg (``NOT_ATTEMPTED``)
        # stays silent while a leg that was asked and produced nothing turns
        # ``ALL`` into ``PARTIAL`` rather than claiming complete coverage.
        merged.provider = provider_from_answered(merged.answered, pair.asked)
    else:
        merged.provider = pair.provider

    warn_list = list(warnings)
    if health_warn:
        warn_list.extend(health_warn)
    if degraded:
        warn_list.append(
            "Provider health monitor reports an upstream change/outage; run "
            "tapebasis_health for details."
        )
    if merged.provider is not DataProvider.NONE and merged.mismatches:
        warn_list.append(
            "Providers disagree on: " + ", ".join(merged.mismatches)
        )
    if merged.provider is not DataProvider.NONE and merged.not_comparable:
        warn_list.append(
            "Not cross-checked (no shared basis for comparison): "
            + ", ".join(merged.not_comparable)
        )

    merged_extra = dict(extra or {})
    # Only publish the freshness block when a real comparison happened. Tools
    # that compare non-price fields (index levels, counts) have no print time
    # on either side, and reporting "no usable timestamp" there is noise about
    # a decision that was never in question.
    if merged.freshness and any(
        merged.freshness.get(p.lower()) for p in PROVIDER_ORDER
    ):
        merged_extra.setdefault("freshness", merged.freshness)

    body = envelope(
        merged.data,
        provider=merged.provider,
        fields=merged.fields,
        comparisons=merged.comparisons,
        sources=sources or {},
        errors=pair.errors + list(additional_errors),
        warnings=warn_list,
        degraded=degraded,
        providers_answered=merged.answered,
        extra=merged_extra,
    )
    body["notice"] = notice_for(merged)
    if degraded:
        body["notice"] += (
            " WARNING: the provider health monitor reports an upstream change or "
            "outage, see tapebasis_health."
        )
    return body


def providers_in(pair: Pair) -> tuple[str, ...]:
    """Provider labels that actually answered (used for health-warning scoping)."""
    return tuple(pair.answered)
