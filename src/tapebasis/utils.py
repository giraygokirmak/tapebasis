"""Tiny value-coercion helpers shared by providers and the orchestration layer."""
from __future__ import annotations

from typing import Any

_SUFFIXES = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}

#: The one browser identity this server presents to every upstream.
#:
#: It lives here rather than beside any single provider because every leg sends
#: the same string: TradingView's scanner and symbol search, Finviz's HTML and
#: JSON routes, Yahoo's chart API, StockAnalysis's quote API and the health
#: probes. Seven copies of the literal had already drifted apart (six on one
#: Chrome version, one on an older one), so refreshing the version was a
#: seven-file edit that could silently leave one leg fingerprintable. A single
#: constant makes that one edit, and makes the health probe present the identity
#: the real request presents.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)


def to_float(value: Any) -> float | None:
    """Best-effort numeric coercion, or ``None`` when the value is not numeric.

    Understands ``"1.2B"``, ``"$331.90"``, ``"-1.9%"`` and plain numbers; keeps
    the sign of parenthesised negatives like ``(1.25)``.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
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
        if text and text[-1].upper() in _SUFFIXES:
            multiplier = _SUFFIXES[text[-1].upper()]
            text = text[:-1]
        try:
            number = float(text) * multiplier
        except ValueError:
            return None
        return -number if negative else number
    return None


def lead_float(value: Any) -> float | None:
    """First numeric token in a string, or the value itself when already numeric.

    Finviz annotates some snapshot cells as ``"351.73 -5.64%"`` (level followed
    by the distance from it). The level is the first token.
    """
    direct = to_float(value)
    if direct is not None:
        return direct
    if isinstance(value, str):
        first = value.strip().split(" ", 1)[0]
        return to_float(first)
    return None


def to_int(value: Any) -> int | None:
    number = to_float(value)
    return None if number is None else int(number)


def as_dict(value: Any) -> dict[str, Any]:
    """Return *value* if it is a dict, else an empty dict."""
    return value if isinstance(value, dict) else {}


def first_key(payload: dict[str, Any], *names: str) -> Any:
    """First non-``None`` value among *names*."""
    for name in names:
        if name in payload and payload[name] is not None:
            return payload[name]
    return None
