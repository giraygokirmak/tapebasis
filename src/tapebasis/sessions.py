"""Which session a quote's print belongs to, and which print is the live one.

A price is not a fact on its own. "AAPL is 355.36" is either the regular
session's last trade, a pre-market print, an after-hours print, or an overnight
print on an alternative venue, and those are different observations of the same
instrument. Serving one number without saying which is how a frozen regular
session value gets read as the live price while the market trades elsewhere.

Two things live here:

:func:`market_session`
    Classify an instant into the US equity trading day. The boundaries are the
    extended-hours schedule the venues publish, not a guess: pre-market opens
    04:00 ET, the regular session runs 09:30 to 16:00 ET, after-hours ends
    20:00 ET, and the overnight venues (Blue Ocean ATS among them) trade
    20:00 to 04:00 ET.

:func:`live_print`
    Given one provider's own shaped quote, return the number that provider
    would call "the price right now", together with the instant it printed and
    the session it printed in. Every provider already sends this; it is just
    spread across different field names, and reading the wrong one is what made
    a stale value look current.

Both are pure: no request is made, nothing is inferred that the provider did not
say. When a provider carries no session-specific field the regular value is
returned under the session its own print time implies, so a provider is never
credited with a print it did not send.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import math
from typing import Any
from zoneinfo import ZoneInfo

from .freshness import parse_market_timestamp

_EASTERN = ZoneInfo("America/New_York")

#: Session names. Deliberately the vocabulary an exchange uses, not an invented
#: one: ``overnight`` is the 20:00-04:00 window the alternative venues run, which
#: is a real session with real prints, not "the market is closed".
OVERNIGHT = "overnight"
PRE_MARKET = "pre_market"
REGULAR = "regular"
POST_MARKET = "post_market"

#: Session boundaries in US/Eastern wall-clock time. Half-open: the session
#: that starts at 09:30 owns 09:30:00 and the one that ends at 16:00 does not.
_BOUNDARIES: tuple[tuple[time, time, str], ...] = (
    (time(4, 0), time(9, 30), PRE_MARKET),
    (time(9, 30), time(16, 0), REGULAR),
    (time(16, 0), time(20, 0), POST_MARKET),
    (time(20, 0), time(4, 0), OVERNIGHT),
)


def market_session(moment: datetime | None) -> str | None:
    """The US equity session an instant falls in, or ``None`` without one.

    Args:
        moment: A print time. Naive values are read as UTC.

    Returns:
        ``pre_market``, ``regular``, ``post_market`` or ``overnight``. Weekend
        instants still classify by clock time: some venues do print then, and
        inventing a fifth "weekend" state would hide a real print rather than
        describe it.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    wall = moment.astimezone(_EASTERN).time()
    for start, end, name in _BOUNDARIES:
        if start < end:
            if start <= wall < end:
                return name
        elif wall >= start or wall < end:
            # The overnight window wraps past midnight.
            return name
    return None


def session_window_start(
    print_time: Any, session_name: str = OVERNIGHT
) -> datetime | None:
    """Return the UTC start of the window containing the print itself.

    Overnight crosses midnight, so a print before 04:00 ET belongs to the
    20:00 ET occurrence that started on the preceding calendar date. The
    calculation uses the print, not the response clock, including at 03:59:59.
    """
    stamp = parse_market_timestamp(print_time)
    if stamp is None or market_session(stamp) != session_name:
        return None
    eastern = stamp.astimezone(_EASTERN)
    opening_times = {
        PRE_MARKET: time(4, 0),
        REGULAR: time(9, 30),
        POST_MARKET: time(16, 0),
        OVERNIGHT: time(20, 0),
    }
    opening = opening_times.get(session_name)
    if opening is None:
        return None
    start = eastern.replace(
        hour=opening.hour, minute=opening.minute, second=0, microsecond=0
    )
    if session_name == OVERNIGHT and eastern.hour < 4:
        start -= timedelta(days=1)
    return start.astimezone(timezone.utc)


def current_session(
    print_time: Any,
    now: datetime | None = None,
    *,
    session_name: str | None = None,
) -> tuple[str | None, datetime | None, datetime | None]:
    """Validate a print's session against the current trading window.

    Args:
        print_time: The provider's own market print timestamp.
        now: The response clock, defaulting to UTC now.
        session_name: The session a venue block asserts, if it has one.

    Returns:
        ``(current_name, print_instant, current_window_start)``. The name is
        non-null only when the print belongs to the same calendar occurrence of
        that window. A timestamp without a known window can never be current.
    """
    stamp = parse_market_timestamp(print_time)
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    active = market_session(moment)
    if session_name is not None and active != session_name:
        return None, stamp, None
    if stamp is None:
        return None, None, None
    stamp = stamp.astimezone(timezone.utc)
    # Both windows are contiguous in Eastern time except for overnight, which
    # crosses midnight. Comparing only hours would confuse an old evening print
    # with this morning's overnight session, so preserve both calendar dates.
    if active is None:
        return None, stamp, None
    start = session_window_start(moment, active)
    if start is None:
        return None, stamp, None
    if stamp < start or stamp > moment:
        return None, stamp, start
    return active, stamp, start


def _number(value: Any) -> float | None:
    """A finite float, or ``None``. Strings and bools are not prices."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _baseline(price: Any, change_percent: Any) -> float | None:
    """The close a print's own percent change was computed against.

    Recovered as ``price / (1 + change/100)``, which is exact rather than
    approximate: it is the number the provider itself divided by, so no extra
    request is needed to learn the baseline a print is measured against.

    Args:
        price: The print.
        change_percent: That print's own change, in percent.

    Returns:
        The implied reference close, or ``None`` when either input is missing or
        the change is exactly -100 (a total loss has no recoverable base).
    """
    number = _number(price)
    change = _number(change_percent)
    if number is None or change is None or change == -100:
        return None
    return number / (1 + change / 100)


def live_print(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The live price one provider's shaped quote carries, with its session.

    Each provider publishes the current print under a different name and
    leaves the plain ``price``/``close`` field holding the regular session's
    value. TradingView is the clearest case: its scanner ``close`` is the
    primary feed's last trade, which stops moving the moment pre-market
    trading starts on another venue, while its own ``premarket_close`` keeps
    streaming. Reading ``close`` as the price is what let a quote sit hours
    behind the market while the response still claimed to be current.

    Args:
        provider: The provider label, as :mod:`tapebasis.providers_state` uses
            it (``TRADINGVIEW``, ``FINVIZ``, ``YAHOO``, ``SA``, ``BLOOMBERG``).
        payload: That provider's shaped quote.

    Returns:
        ``{"price", "timestamp", "session", "field"}``. ``price`` is ``None``
        when the provider sent no usable number. ``session`` comes from the
        provider's own label when it publishes one, otherwise from
        :func:`market_session` applied to the print time. ``field`` names the
        provider field the number was read from, so the provenance is auditable
        rather than implied.
    """
    if provider == "TRADINGVIEW":
        return _tradingview(payload)
    if provider == "FINVIZ":
        return _finviz(payload)
    if provider == "YAHOO":
        return _yahoo(payload)
    if provider == "SA":
        return _stockanalysis(payload)
    if provider == "BLOOMBERG":
        return _bloomberg(payload)
    return _plain(payload)


def _pack(
    price: Any,
    timestamp: Any,
    session: str | None,
    field: str,
    *,
    reference_close: Any = None,
    change_percent: Any = None,
) -> dict[str, Any]:
    """Assemble the result, deriving the session from the time when unlabelled.

    ``reference_close`` is the close this print should be measured against, as
    the provider itself states it. Carrying it is what keeps a row's price and
    its day change on one reference session; taking the price from one provider
    and the baseline from another produced rows that implied two different day
    changes at once.
    """
    moment = parse_market_timestamp(timestamp)
    number = _number(price)
    if number is None:
        return {
            "price": None, "timestamp": None, "session": None, "field": field,
            "reference_close": None, "change_percent": None,
        }
    return {
        "price": number,
        "timestamp": moment,
        "session": session or market_session(moment),
        "field": field,
        "reference_close": _number(reference_close),
        "change_percent": _number(change_percent),
    }


#: TradingView's ``current_session`` value to our session name. The scanner
#: spells the regular session ``market``; the quote socket spells the overnight
#: window ``out_of_session``. Exported because the tool layer maps the same
#: labels when it has already normalised a provider's row itself.
SESSION_NAMES: dict[str, str] = {
    "premarket": PRE_MARKET,
    "pre": PRE_MARKET,
    "pre_market": PRE_MARKET,
    "market": REGULAR,
    "regular": REGULAR,
    "postmarket": POST_MARKET,
    "post": POST_MARKET,
    "post_market": POST_MARKET,
    "out_of_session": OVERNIGHT,
    "overnight": OVERNIGHT,
}

_TV_SESSIONS = SESSION_NAMES


def _tradingview(payload: dict[str, Any]) -> dict[str, Any]:
    """TradingView: the session the scanner names, and that session's print.

    The scanner states which session it is in (``current_session``) and carries
    one field per extended session. When it says ``pre_market``, ``close`` is
    not the pre-market print, so ``premarket_close`` is the number that answers
    "what is the price". The scanner sends no print time for those extended
    fields, so that value is returned untimestamped rather than being stamped
    with ``update_time``: ``update_time`` is when the row was refreshed, and
    using it as a print time is exactly the mistake that made a stale price
    look like the newest one.

    The reference close is the close each print's own change was computed
    against, recovered from that print's arithmetic: ``price / (1 + change/100)``.
    It is **not** interchangeable between branches. The regular ``close`` is a
    regular-session print and its ``change`` is measured against the prior
    session's close, while ``premarket_close``/``postmarket_close`` are extended
    prints and their changes are measured against the last regular close. Those
    are different reference sessions by construction, so a branch derives from
    its own change and never reuses another branch's baseline. Measured on a live
    pre-market session, the extended branch's arithmetic reproduced the official
    previous close exactly, while reusing the regular branch's baseline was off
    by the whole of the regular move.
    """
    session = _TV_SESSIONS.get(str(payload.get("current_session") or "").lower())
    regular_close = _number(payload.get("close"))
    change = _number(payload.get("change"))
    stamp = payload.get("update_time")
    if session == PRE_MARKET and _number(payload.get("premarket_close")) is not None:
        live_change = _number(payload.get("premarket_change"))
        return _pack(
            payload.get("premarket_close"), stamp, PRE_MARKET, "premarket_close",
            reference_close=_baseline(payload.get("premarket_close"), live_change),
            change_percent=live_change,
        )
    if session == POST_MARKET and _number(payload.get("postmarket_close")) is not None:
        live_change = _number(payload.get("postmarket_change"))
        return _pack(
            payload.get("postmarket_close"), stamp, POST_MARKET, "postmarket_close",
            reference_close=_baseline(payload.get("postmarket_close"), live_change),
            change_percent=live_change,
        )
    # ``close`` is the regular feed's last trade, so it is a regular-session
    # print whenever it is served. Labelling it with the scanner's current
    # session would call a regular print pre-market just because the symbol has
    # no extended print yet, which is the same conflation one step over.
    return _pack(
        regular_close, stamp, REGULAR, "close",
        reference_close=_baseline(regular_close, change),
        change_percent=change,
    )


def _finviz(payload: dict[str, Any]) -> dict[str, Any]:
    """Finviz: the quote page's "Last Close" header, which is the live print.

    Despite the label this is the most recent print, extended hours included;
    the page renders its own timestamp beside it ("Nov 12 • 8:01 AM ET"), which
    is the only print time Finviz publishes and the reason its readings can be
    ordered against another provider's at all. Its change is measured against
    the snapshot's ``Prev Close``, so that is the reference it is published with.
    """
    header = payload.get("last_close") or {}
    snapshot = payload.get("snapshot_numeric") or {}
    return _pack(
        header.get("price"), header.get("date"), None, "last_close.price",
        reference_close=snapshot.get("Prev Close"),
        change_percent=header.get("change_percent"),
    )


def _yahoo(payload: dict[str, Any]) -> dict[str, Any]:
    """Yahoo: the freshest print it publishes, session blocks or ``fullday``.

    ``regularMarketPrice`` freezes the moment the regular session ends, so Yahoo
    publishes the session-inclusive value beside it as ``fulldayPrice``. Which of
    the two is current depends on the time of day, so the later one wins; during
    the regular session they are the same number anyway. ``yh_access`` also
    shapes per-session blocks (``pre_market``/``regular``/``post_market``) with
    their own print times, and those are preferred when present because they
    name the session instead of leaving it to the clock.
    """
    best: dict[str, Any] | None = None
    for key, name in (
        ("pre_market", PRE_MARKET),
        ("post_market", POST_MARKET),
        ("regular", REGULAR),
    ):
        block = payload.get(key) or {}
        candidate = _pack(
            block.get("price"),
            block.get("as_of_utc") or block.get("price_timestamp"),
            name,
            f"{key}.price",
            reference_close=block.get("reference_close"),
            change_percent=block.get("change_vs_previous_close_pct")
            if block.get("change_vs_previous_close_pct") is not None
            else block.get("change_pct"),
        )
        if candidate["price"] is None:
            continue
        if best is None or _is_newer(candidate["timestamp"], best["timestamp"]):
            best = candidate
    if best is not None:
        return best
    # No session blocks: ``fulldayPrice`` is Yahoo's own session-inclusive print
    # and is measured against the regular session's price. Yahoo publishes no
    # print time for it, so it is returned undated rather than stamped with
    # ``regularMarketTime``, which belongs to the regular close and would claim
    # the extended print happened at the regular session's last tick.
    regular = _number(payload.get("price"))
    fullday = _number(payload.get("fullday_price"))
    if fullday is not None and regular is not None and fullday != regular:
        return {
            "price": fullday,
            "timestamp": None,
            "session": market_session(
                parse_market_timestamp(payload.get("market_time"))
            ),
            "field": "fullday_price",
            "reference_close": regular,
            "change_percent": _number(payload.get("fullday_change_percent")),
        }
    return _pack(
        payload.get("price"), payload.get("market_time"), None, "price",
        reference_close=payload.get("previous_close"),
        change_percent=payload.get("change_pct"),
    )


def _stockanalysis(payload: dict[str, Any]) -> dict[str, Any]:
    """StockAnalysis: its extended-hours block when the regular quote is older.

    The quote API keeps the regular session in ``price`` and publishes the
    current extended print, with its own timestamp, in ``extended_hours``. That
    block measures its change against the regular session's price, which is the
    baseline it is returned with.
    """
    block = payload.get("extended_hours") or {}
    if payload.get("has_extended_hours") and _number(block.get("price")) is not None:
        labelled = str(block.get("session") or "").lower()
        name = (
            POST_MARKET if "post" in labelled
            else PRE_MARKET if "pre" in labelled
            else None
        )
        return _pack(
            block.get("price"), block.get("price_timestamp"), name,
            "extended_hours.price",
            reference_close=block.get("previous_close"),
            change_percent=block.get("change_percent"),
        )
    return _pack(
        payload.get("price"), payload.get("price_timestamp"), None, "price",
        reference_close=payload.get("previous_close"),
        change_percent=payload.get("change_percent"),
    )


def _bloomberg(payload: dict[str, Any]) -> dict[str, Any]:
    """Bloomberg: its quote price, whose ``print_time`` dates the same print."""
    return _pack(
        payload.get("price"), payload.get("print_time"), None, "price",
        reference_close=payload.get("previous_close"),
        change_percent=payload.get("change_percent"),
    )


def _plain(payload: dict[str, Any]) -> dict[str, Any]:
    """A provider with no session-specific fields: its own price and time."""
    return _pack(
        payload.get("price"), payload.get("price_timestamp"), None, "price",
        reference_close=payload.get("previous_close"),
        change_percent=payload.get("change_percent"),
    )


def _is_newer(left: datetime | None, right: datetime | None) -> bool:
    """Whether *left* is strictly later than *right*; an undated value never is.

    A value with no print time cannot claim to be current, so it never displaces
    a dated one. That asymmetry is deliberate: it is what stops an undated
    reading from winning the freshness race by default.
    """
    if left is None:
        return False
    if right is None:
        return True
    return left > right


__all__ = [
    "OVERNIGHT",
    "POST_MARKET",
    "PRE_MARKET",
    "REGULAR",
    "live_print",
    "market_session",
]
