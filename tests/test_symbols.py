"""Tests for symbol normalisation across provider spellings."""
from __future__ import annotations

import pytest

from tapebasis.symbols import (
    INDEX_ALIASES,
    INSTRUMENTS,
    _ALIASES_LOWER,
    canonical_index,
    canonical_instrument,
    instrument_row,
    is_equity,
    registry_resolution,
    strip_exchange,
    to_finviz,
    to_tradingview_candidates,
    to_yahoo,
)


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("NASDAQ:AAPL", "AAPL"),
        ("AAPL", "AAPL"),
        ("NASDAQ:BRK.B", "BRK.B"),
    ],
)
def test_strip_exchange(symbol, expected):
    assert strip_exchange(symbol) == expected


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("BRK-B", "BRK.B"),
        ("BRK.B", "BRK.B"),
        ("AAPL", "AAPL"),
        ("^GSPC", "SPX"),
        ("SPX", "SPX"),
    ],
)
def test_to_finviz(symbol, expected):
    assert to_finviz(symbol) == expected


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("BRK.B", "BRK-B"),
        ("BRK-B", "BRK-B"),
        ("AAPL", "AAPL"),
        ("SPX", "^GSPC"),
        ("COMP", "^IXIC"),
        ("DJI", "^DJI"),
    ],
)
def test_to_yahoo(symbol, expected):
    assert to_yahoo(symbol) == expected


@pytest.mark.parametrize(
    "symbol,canonical",
    [
        ("^GSPC", "SPX"),
        ("SPX", "SPX"),
        ("SP:SPX", "SPX"),
        ("^IXIC", "COMP"),
        ("COMP", "COMP"),
        ("^DJI", "DJI"),
        ("^VIX", "VIX"),
    ],
)
def test_canonical_index(symbol, canonical):
    assert canonical_index(symbol) == canonical


def test_russel_index_and_etf_are_not_aliased():
    """^RUT is the index; IWM is the tracking ETF, different price levels."""
    assert canonical_index("^RUT") == "RUT"
    assert canonical_index("IWM") == "IWM"
    assert INDEX_ALIASES["RUT"]["finviz"] is None


@pytest.mark.parametrize(
    "symbol,equity",
    [
        ("AAPL", True),
        ("BRK.B", True),
        ("BTC-USD", False),
        ("EURUSD=X", False),
        ("^GSPC", False),
        ("BTCUSDT", False),
    ],
)
def test_is_equity(symbol, equity):
    assert is_equity(symbol) is equity


def test_tradingview_candidates_cover_us_venues():
    assert to_tradingview_candidates("AAPL") == [
        "NASDAQ:AAPL",
        "NYSE:AAPL",
        "AMEX:AAPL",
    ]
    assert to_tradingview_candidates("NASDAQ:AAPL") == ["NASDAQ:AAPL"]


# ── the instrument registry ─────────────────────────────────────────────────


def test_every_registry_row_is_complete():
    """A row names the instrument, its class, and all five provider columns."""
    for canonical, row in INSTRUMENTS.items():
        assert row.get("name"), canonical
        assert row.get("asset_class") in {"index", "etf", "commodity", "futures"}, canonical
        for column in ("tradingview", "finviz", "yahoo", "sa", "bloomberg"):
            assert column in row, f"{canonical} is missing the {column} column"
            # A cell is either a non-empty string or None-with-reason.
            if row[column] is None and row.get("asset_class") not in {"index", "etf"}:
                assert row.get(f"{column}_note") or column in {"sa", "finviz"}, (
                    f"{canonical}.{column} is None without a documented boundary"
                )


def test_no_two_rows_claim_the_same_spelling():
    """Two instruments must never answer to the same provider spelling.

    A collision would make the lookup silently prefer one row and send the
    other instrument's quote to the wrong comparison. ``RUT``/``IWM`` and
    ``XAUUSD``/``GC1!`` are the historical near-misses.
    """
    seen: dict[str, str] = {}
    for canonical, row in INSTRUMENTS.items():
        for column in ("tradingview", "finviz", "yahoo", "sa", "bloomberg"):
            spelling = row.get(column)
            if not isinstance(spelling, str) or not spelling:
                continue
            key = f"{column}:{spelling.lower()}"
            assert key not in seen, (
                f"{canonical} and {seen.get(key)} both claim {key}"
            )
            seen[key] = canonical


def test_index_and_commodity_rows_are_never_aliased():
    """Decision 20, extended by the registry: one row is one instrument."""
    assert canonical_instrument("RUT") == "RUT"
    assert canonical_instrument("IWM") == "IWM"
    assert INSTRUMENTS["RUT"]["asset_class"] == "index"
    assert INSTRUMENTS["IWM"]["asset_class"] == "etf"
    # Spot gold and the front-month future are different instruments.
    assert canonical_instrument("XAUUSD") == "XAUUSD"
    assert canonical_instrument("GC1!") == "GC1!"
    assert INSTRUMENTS["XAUUSD"]["yahoo"] is None
    assert INSTRUMENTS["GC1!"]["yahoo"] == "GC=F"


@pytest.mark.parametrize(
    "query,expected",
    [
        ("SPX", "SPX"),
        ("^GSPC", "SPX"),
        ("SP:SPX", "SPX"),
        ("GSPC", "SPX"),
        ("SP500", "SPX"),
        ("WTI", "USOIL"),
        ("GOLD", "XAUUSD"),
        ("CL=F", "CL1!"),
        ("COMEX:GC1!", "GC1!"),
        ("GC1:COM", "GC1!"),
        ("BRENT", "UKOIL"),
        ("COPPER", "HG1!"),
        ("NATGAS", "NG1!"),
        ("AAPL", None),
        ("BRK.B", None),
        ("BTCUSD", None),
        ("", None),
    ],
)
def test_canonical_instrument(query, expected):
    assert canonical_instrument(query) == expected


def test_registry_resolution_returns_the_spelling_or_the_boundary():
    """The registry answers both directions for every provider."""
    oil = registry_resolution("WTI", "TRADINGVIEW")
    assert oil is not None and oil.symbol == "FX:USOIL"
    assert oil.method == "alias"
    gold = registry_resolution("GOLD", "YAHOO")
    assert gold is not None and gold.symbol is None
    assert "no spot gold pair" in gold.note
    # An unregistered query falls through to the dynamic path.
    assert registry_resolution("AAPL", "TRADINGVIEW") is None


def test_bloomberg_class_suffix_is_not_a_spelling():
    """``IWM:US`` must not teach the lookup that ``US`` means IWM."""
    assert canonical_instrument("BRK/B:US") is None
    assert canonical_instrument("AAPL:US") is None
    # A full Bloomberg id still lands on its row.
    assert canonical_instrument("SPX:IND") == "SPX"
    assert canonical_instrument("GC1:COM") == "GC1!"


def test_instrument_row_returns_a_copy():
    """A caller must not be able to mutate the registry."""
    row = instrument_row("SPX")
    assert row is not None and row["yahoo"] == "^GSPC"
    row["yahoo"] = "mutated"
    assert instrument_row("SPX")["yahoo"] == "^GSPC"


def test_alias_table_never_names_a_missing_row():
    """An alias that points nowhere would send the caller to a dead key."""
    for alias, target in _ALIASES_LOWER.items():
        assert target in INSTRUMENTS, f"alias {alias} points at missing row {target}"
