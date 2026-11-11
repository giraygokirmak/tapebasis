"""Market-print timestamps, normalised so two providers can be ordered.

This exists because "which provider's price is fresher?" is only answerable if
both sides report *when the print happened*, in a comparable form. The two
providers express that differently:

* Yahoo (the TradingView leg) reports ``meta.regularMarketTime`` as a Unix
  epoch second.
* Finviz reports a rendered string such as ``"Nov 03 • 3:59 PM ET"``.

Neither the fetch time nor ``generated_at`` is a substitute: a quote fetched
now can carry yesterday's close, and the whole point of picking the fresher
reading is to avoid treating a stale price as current.

Parsing is deliberately forgiving: a provider tweaking its date rendering
should degrade to "timestamp unknown" (and therefore "no freshness
arbitration"), never to an exception or a wrong ordering.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

#: Finviz renders US market times and labels them ``ET``. Resolving that to a
#: real zone matters twice a year: a fixed -05:00 would be an hour wrong
#: through daylight saving.
try:  # pragma: no cover - depends on the platform shipping tzdata
    from zoneinfo import ZoneInfo

    _EASTERN = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001 - fall back to a fixed offset below
    _EASTERN = None

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

#: ``Nov 03 • 3:59 PM ET`` / ``Nov 3, 2026 • 15:59 ET`` / ``Today • 3:59 PM ET``
_DATE_TIME = re.compile(
    r"(?P<day_part>today|yesterday|(?P<mon>[A-Za-z]{3})[a-z]*\.?\s+"
    r"(?P<day>\d{1,2})(?:,\s*(?P<year>\d{4}))?)"
    r"\s*[•·|,-]?\s*"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>AM|PM|am|pm)?",
    re.I,
)

#: ``3:59 PM ET`` with no date at all.
_TIME_ONLY = re.compile(
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>AM|PM|am|pm)\s*(?:ET|EST|EDT)",
    re.I,
)

#: ``20261103``, Finviz's indices island uses a bare date.
_COMPACT_DATE = re.compile(r"^(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})$")


def _to_eastern(moment: datetime) -> datetime:
    """Attach the US/Eastern zone to a naive wall-clock reading."""
    if _EASTERN is not None:
        return moment.replace(tzinfo=_EASTERN)
    # No tzdata: US markets are on EDT from March to November, EST after.
    # Wrong by an hour for part of the year, which is why this is a fallback.
    return moment.replace(tzinfo=timezone(timedelta(hours=-4 if 3 <= moment.month <= 10 else -5)))


def _hour_24(hour: int, ampm: str | None) -> int | None:
    if ampm:
        suffix = ampm.upper()
        if not 1 <= hour <= 12:
            return None
        if suffix == "AM":
            return 0 if hour == 12 else hour
        return 12 if hour == 12 else hour + 12
    return hour if 0 <= hour <= 23 else None


def parse_market_timestamp(
    raw: object,
    *,
    reference: datetime | None = None,
) -> datetime | None:
    """Parse a provider timestamp into an aware UTC datetime.

    Accepts epoch seconds/strings, ISO-8601, and the human strings Finviz
    renders (``"Nov 03 • 3:59 PM ET"``). Returns ``None`` (never raises) when
    the value cannot be understood, which callers read as "freshness unknown".

    Args:
        raw: The provider's timestamp in any supported form.
        reference: Clock used to supply a missing year or a ``Today``/
            ``Yesterday`` token. Defaults to now in UTC.
    """
    if raw is None or raw == "":
        return None

    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc) if raw.tzinfo else _to_eastern(raw).astimezone(timezone.utc)

    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        # A 8-digit integer like ``20261105`` is a compact date, not an epoch
        # second (which would land in 1970). Finviz's indices feed sends the
        # calendar date as a number, and reading it as an epoch silently dates
        # every index print to 1970, which is worse than "unknown".
        if isinstance(raw, int) and len(str(abs(raw))) == 8:
            text = str(raw)
        else:
            try:
                return datetime.fromtimestamp(float(raw), tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
    else:
        text = "" if raw is None or raw == "" else str(raw).strip()
    if not text:
        return None

    # Bare epoch, possibly as a string.
    if re.fullmatch(r"\d{9,11}(?:\.\d+)?", text):
        try:
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    # ISO-8601 (with or without a zone).
    if re.match(r"^\d{4}-\d{2}-\d{2}[T ]", text):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else _to_eastern(parsed).astimezone(timezone.utc)

    compact = _COMPACT_DATE.match(text)
    if compact:
        try:
            # A bare ``YYYYMMDD`` is a *calendar date in the market's own zone*,
            # not an instant. Reading it as UTC midnight puts it 04:00-05:00
            # earlier in US/Eastern, which lands on the previous date and makes
            # the session guard treat today's Finviz index print as yesterday's.
            # That made COMP report a day change from one session beside a level
            # from another. The date is therefore attached to US/Eastern
            # midnight, so the session date it yields is the date it names.
            return _to_eastern(
                datetime(
                    int(compact["year"]), int(compact["month"]), int(compact["day"]),
                )
            ).astimezone(timezone.utc)
        except ValueError:
            return None

    now = (reference or datetime.now(timezone.utc)).astimezone(timezone.utc)
    eastern_now = now.astimezone(_EASTERN) if _EASTERN is not None else now

    match = _DATE_TIME.search(text)
    if match:
        hour = _hour_24(int(match["hour"]), match["ampm"])
        if hour is None:
            return None
        minute = int(match["minute"])
        day_part = (match["day_part"] or "").lower()

        if day_part in {"today", "yesterday"}:
            target = eastern_now.date() - (
                timedelta(days=1) if day_part == "yesterday" else timedelta()
            )
            year, month, day = target.year, target.month, target.day
        else:
            month = _MONTHS.get(match["mon"].lower()[:3])
            if month is None:
                return None
            year = int(match["year"]) if match["year"] else eastern_now.year
            day = int(match["day"])

        try:
            wall = datetime(year, month, day, hour, minute)
        except ValueError:
            return None

        # No year in the source: a date far in the future must belong to the
        # previous year (e.g. a December page read in January).
        if not match["year"] and wall.replace(year=year) > eastern_now.replace(tzinfo=None) + timedelta(days=2):
            try:
                wall = wall.replace(year=year - 1)
            except ValueError:
                return None
        return _to_eastern(wall).astimezone(timezone.utc)

    time_only = _TIME_ONLY.search(text)
    if time_only:
        hour = _hour_24(int(time_only["hour"]), time_only["ampm"])
        if hour is None:
            return None
        wall = eastern_now.replace(
            hour=hour, minute=int(time_only["minute"]), second=0, microsecond=0
        )
        return wall.astimezone(timezone.utc)

    return None


def session_date(moment: datetime | None) -> date | None:
    """Calendar date of a print in US/Eastern, the session key for US markets.

    Two prints with different session dates belong to different sessions *for
    US equities*, which is what makes this a sound test for a session-relative
    field: a previous close, a day change, an accumulated volume.

    Two honest limits, both deliberate:

    * It is a date, not a session. FX rolls at 17:00 ET, not at midnight, so two
      prints 30 seconds apart across midnight ET get different dates while
      belonging to the same FX trading day. The caller therefore treats a
      mismatch as ``not comparable`` and never as a disagreement, so this can
      lose a comparison but can never invent a conflict.
    * It is single-market. A JST or CET instrument's session can straddle ET
      midnight the other way. Same conservative outcome.

    Used only to *narrow* what gets compared, never to order readings.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    eastern = moment.astimezone(_EASTERN) if _EASTERN is not None else moment
    return eastern.date()


def freshest(*readings: tuple[str, datetime | None]) -> str | None:
    """Return the label of the strictly most recent reading.

    Only a strict win counts. A tie returns ``None`` so the caller applies its
    documented default instead of silently favouring whichever label happened
    to be passed first. Readings with an unknown timestamp cannot win against a
    known one.
    """
    best_label: str | None = None
    best_time: datetime | None = None
    tied = False
    for label, moment in readings:
        if moment is None:
            continue
        if best_time is None or moment > best_time:
            best_label, best_time = label, moment
            tied = False
        elif moment == best_time:
            tied = True
    if tied:
        return None
    return best_label
