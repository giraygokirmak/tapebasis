"""The session rule, and which print a provider's quote is measured against.

Two things are easy to get wrong here and both were: reading a stale price field
as "the price", and recovering a baseline from the wrong branch so a row reports
a day change against a close that belongs to a different session.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tapebasis import sessions
from tapebasis.sessions import (
    OVERNIGHT,
    POST_MARKET,
    PRE_MARKET,
    REGULAR,
    live_print,
    market_session,
)
from tapebasis.freshness import parse_market_timestamp

EASTERN = "America/New_York"


def _et(hour: int, minute: int = 0, day: int = 12) -> datetime:
    """An instant on 2026-11-12 at a US/Eastern wall-clock time, in UTC."""
    from zoneinfo import ZoneInfo

    return datetime(2026, 11, day, hour, minute, tzinfo=ZoneInfo(EASTERN))


# ── market_session ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "moment, expected",
    [
        (_et(4, 0), PRE_MARKET),
        (_et(9, 29), PRE_MARKET),
        (_et(9, 30), REGULAR),
        (_et(12, 0), REGULAR),
        (_et(15, 59), REGULAR),
        (_et(16, 0), POST_MARKET),
        (_et(19, 59), POST_MARKET),
        (_et(20, 0), OVERNIGHT),
        (_et(23, 59), OVERNIGHT),
        (_et(0, 0), OVERNIGHT),
        (_et(3, 59), OVERNIGHT),
        (_et(4, 0), PRE_MARKET),
    ],
)
def test_session_boundaries_are_half_open(moment, expected):
    """Each boundary belongs to the session that starts there, not the one ending."""
    assert market_session(moment) == expected


def test_no_instant_means_no_session():
    """An unknown time is not guessed into a session."""
    assert market_session(None) is None


def test_current_overnight_belongs_to_one_calendar_occurrence():
    """A past evening print is not current on the following evening."""
    from tapebasis.sessions import current_session

    evening = datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc)
    next_night = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    assert current_session(evening, next_night, session_name=OVERNIGHT)[0] is None
    this_morning = datetime(2026, 11, 13, 8, 0, tzinfo=timezone.utc)
    active, _, start = current_session(evening, this_morning, session_name=OVERNIGHT)
    assert active == OVERNIGHT
    assert start == datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc)


def test_overnight_window_uses_the_prints_own_instant_at_the_close():
    """03:59:59 ET remains in the occurrence that began at 20:00 ET."""
    from zoneinfo import ZoneInfo

    print_instant = datetime(2026, 11, 13, 3, 59, 59, tzinfo=ZoneInfo(EASTERN))
    start = sessions.session_window_start(print_instant, OVERNIGHT)
    assert start == datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc)
    next_instant = print_instant.replace(second=0, minute=0, hour=4)
    assert sessions.session_window_start(next_instant, OVERNIGHT) is None


def test_a_naive_instant_is_read_as_utc():
    """The boundary rule does not silently assume local wall time."""
    naive = datetime(2026, 11, 12, 14, 30)  # 09:30 ET
    assert market_session(naive) == REGULAR


# ── live_print: the regular branch ───────────────────────────────────────────


def test_regular_price_is_labelled_regular_and_keeps_its_own_change():
    """``close`` is a regular-session print, whatever the clock now says."""
    live = live_print(
        "TRADINGVIEW",
        {
            "close": 355.36,
            "change": -0.0759,
            "premarket_close": 357.9,
            "premarket_change": 0.638,
            "current_session": "market",
            "update_time": 1794493485,
        },
    )
    assert live["price"] == pytest.approx(355.36)
    assert live["session"] == REGULAR
    assert live["field"] == "close"
    assert live["change_percent"] == pytest.approx(-0.0759)


# ── live_print: the extended branch ──────────────────────────────────────────


def test_premarket_print_replaces_the_stale_regular_close():
    """When the scanner says pre-market, that session's print is the price."""
    live = live_print(
        "TRADINGVIEW",
        {
            "close": 355.36,
            "change": -0.0759,
            "premarket_close": 357.9,
            "premarket_change": 0.638,
            "current_session": "pre_market",
            "update_time": 1794493485,
        },
    )
    assert live["price"] == pytest.approx(357.9)
    assert live["session"] == PRE_MARKET
    assert live["field"] == "premarket_close"
    # The scanner's own stated change, not one recomputed from the stale close.
    assert live["change_percent"] == pytest.approx(0.638)


def test_postmarket_print_is_used_when_the_scanner_names_it():
    live = live_print(
        "TRADINGVIEW",
        {
            "close": 355.36,
            "change": -0.0759,
            "postmarket_close": 354.1,
            "postmarket_change": -0.354,
            "current_session": "post_market",
        },
    )
    assert live["price"] == pytest.approx(354.1)
    assert live["session"] == POST_MARKET
    assert live["field"] == "postmarket_close"


def test_a_named_session_without_that_session_print_keeps_the_regular_value():
    """The scanner saying "pre_market" is not permission to invent a print."""
    live = live_print(
        "TRADINGVIEW",
        {"close": 355.36, "change": -0.0759, "current_session": "pre_market"},
    )
    assert live["price"] == pytest.approx(355.36)
    assert live["session"] == REGULAR
    assert live["field"] == "close"


# ── the baseline each branch is measured against ─────────────────────────────


def test_each_branch_recovers_the_baseline_its_own_change_was_computed_against():
    """The regular and extended prints reference different sessions.

    This is the rule that is easy to collapse: a regular print is measured
    against the prior session's close, an extended print against the last regular
    close. Reusing one branch's baseline for the other reports a day change
    against a close that belongs to a different session, which is what pairing a
    pre-market price with a two-sessions-old close looked like.
    """
    payload = {
        "close": 521.12,
        "change": -2.257,
        "premarket_close": 523.45,
        "premarket_change": 0.446,
        "current_session": "pre_market",
    }
    live = live_print("TRADINGVIEW", payload)
    # The extended print's baseline: the last regular close.
    assert live["reference_close"] == pytest.approx(
        523.45 / (1 + 0.446 / 100), rel=1e-9
    )
    # And it is *not* the regular branch's baseline, which reaches back one
    # session further.
    regular = live_print("TRADINGVIEW", {**payload, "current_session": "market"})
    assert regular["reference_close"] == pytest.approx(
        521.12 / (1 - 2.257 / 100), rel=1e-9
    )
    assert live["reference_close"] != pytest.approx(regular["reference_close"])


def test_the_recovered_baseline_reproduces_the_providers_change():
    """The row is self-consistent: price and baseline imply the stated change."""
    live = live_print(
        "TRADINGVIEW",
        {
            "close": 355.36,
            "change": -0.0759,
            "premarket_close": 357.9,
            "premarket_change": 0.638,
            "current_session": "pre_market",
        },
    )
    implied = (live["price"] - live["reference_close"]) / live["reference_close"] * 100
    assert implied == pytest.approx(live["change_percent"], abs=1e-9)


def test_a_total_loss_has_no_recoverable_baseline():
    """A -100 % change cannot be divided back into a price."""
    live = live_print(
        "TRADINGVIEW",
        {"close": 10.0, "change": -100.0, "current_session": "market"},
    )
    assert live["reference_close"] is None


# ── the other providers ──────────────────────────────────────────────────────


def test_finviz_last_close_is_already_the_live_print():
    """Finviz needs no swap, and its baseline is the snapshot's Prev Close."""
    live = live_print(
        "FINVIZ",
        {
            "last_close": {
                "price": 158.9,
                "date": "Nov 12 • 8:01 AM ET",
                "change_percent": -8.54,
            },
            "snapshot_numeric": {"Prev Close": 173.73},
        },
    )
    assert live["price"] == pytest.approx(158.9)
    assert live["field"] == "last_close.price"
    assert live["reference_close"] == pytest.approx(173.73)
    # The rendered time is understood, and it lands in the pre-market window.
    assert live["session"] == PRE_MARKET


def test_yahoo_fullday_print_is_used_but_stays_undated():
    """``fulldayPrice`` has no print time, so it is never stamped with one."""
    live = live_print(
        "YAHOO",
        {
            "price": 355.63,
            "change_pct": 2.043,
            "previous_close": 348.51,
            "market_time": 1794430801,
            "fullday_price": 356.853,
            "fullday_change_percent": 0.42,
        },
    )
    assert live["price"] == pytest.approx(356.853)
    assert live["field"] == "fullday_price"
    assert live["timestamp"] is None
    assert live["reference_close"] == pytest.approx(355.63)
    assert live["change_percent"] == pytest.approx(0.42)


def test_yahoo_regular_quote_is_used_when_there_is_no_fullday_print():
    live = live_print(
        "YAHOO",
        {
            "price": 355.63,
            "change_pct": 2.043,
            "previous_close": 348.51,
            "market_time": 1794430801,
        },
    )
    assert live["price"] == pytest.approx(355.63)
    assert live["field"] == "price"
    assert live["timestamp"] == parse_market_timestamp(1794430801)


def test_stockanalysis_extended_block_is_the_live_print():
    live = live_print(
        "SA",
        {
            "price": 331.9,
            "change_percent": -1.9,
            "previous_close": 338.32,
            "price_timestamp": "2026-11-04T20:00:00+00:00",
            "has_extended_hours": True,
            "extended_hours": {
                "price": 329.8,
                "session": "Post-market",
                "previous_close": 331.9,
                "change_percent": -0.63,
                "price_timestamp": "2026-11-04T21:30:00+00:00",
            },
        },
    )
    assert live["price"] == pytest.approx(329.8)
    assert live["session"] == POST_MARKET
    assert live["field"] == "extended_hours.price"
    assert live["reference_close"] == pytest.approx(331.9)


def test_bloomberg_price_keeps_its_own_print_time():
    live = live_print(
        "BLOOMBERG",
        {
            "price": 332.1,
            "change_percent": -1.8,
            "previous_close": 338.32,
            # 15:27 UTC is 10:27 ET, inside the regular session.
            "print_time": "2026-11-04T15:27:00+00:00",
        },
    )
    assert live["price"] == pytest.approx(332.1)
    assert live["field"] == "price"
    assert live["session"] == REGULAR
    assert live["timestamp"] == parse_market_timestamp("2026-11-04T15:27:00+00:00")


def test_a_missing_price_is_reported_as_missing_not_zero():
    """No usable number means no price, never a fabricated zero."""
    live = live_print("BLOOMBERG", {"price": None, "previous_close": 338.32})
    assert live["price"] is None
    assert live["timestamp"] is None
    assert live["session"] is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_not_prices(value):
    assert sessions._number(value) is None
    live = live_print("BLOOMBERG", {"price": value, "previous_close": 338.32})
    assert live["price"] is None


def test_session_names_map_every_provider_spelling():
    """The exported vocabulary covers the labels the feeds actually send."""
    for raw, expected in (
        ("premarket", PRE_MARKET),
        ("pre", PRE_MARKET),
        ("pre_market", PRE_MARKET),
        ("market", REGULAR),
        ("regular", REGULAR),
        ("postmarket", POST_MARKET),
        ("post", POST_MARKET),
        ("post_market", POST_MARKET),
        ("out_of_session", OVERNIGHT),
        ("overnight", OVERNIGHT),
    ):
        assert sessions.SESSION_NAMES[raw] == expected
