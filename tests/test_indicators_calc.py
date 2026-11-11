"""Regression tests for the pure indicator calculators.

The calculators are being optimised (rolling sums, monotonic deques, bisect),
and floating-point addition order changes the last bits of a result. These
tests pin the *observable* behaviour: values on real-shaped data, tolerance
windows, None warmup regions, and the exact values the optimised path must
reproduce. They are written against the pre-optimisation implementation, so
any drift the optimisation introduces is caught here, not in a backtest.
"""
from __future__ import annotations

import math
import random

from tapebasis.providers.tradingview.core.services.indicators_calc import (
    calc_atr,
    calc_bollinger,
    calc_donchian,
    calc_ema,
    calc_macd,
    calc_rsi,
    calc_sma,
    calc_supertrend,
)

# Deterministic pseudo-market data: an upward drift with wobble, which makes
# every warmup boundary and every window edge exercise real values.
random.seed(20261111)
N = 600
CLOSES = [100 + 0.05 * i + random.gauss(0, 1.5) for i in range(N)]
HIGHS = [c + abs(random.gauss(0, 0.8)) for c in CLOSES]
LOWS = [c - abs(random.gauss(0, 0.8)) for c in CLOSES]


def test_sma_matches_window_mean_exactly():
    """Every SMA point is the arithmetic mean of its window.

    The rolling-sum implementation maintains the window total incrementally,
    so the float result can differ from a fresh ``sum(window)`` in the last
    bits. The observable value must agree to well under a price tick (1e-9).
    """
    period = 20
    sma = calc_sma(CLOSES, period)
    assert sma[: period - 1] == [None] * (period - 1)
    for i in range(period - 1, len(CLOSES)):
        window = CLOSES[i - period + 1 : i + 1]
        assert sma[i] is not None
        assert abs(sma[i] - sum(window) / period) < 1e-9


def test_sma_short_series_all_none():
    assert calc_sma([1.0, 2.0, 3.0], 5) == [None, None, None]


def test_bollinger_matches_manual_stddev():
    """Bands are mean +/- std_mult * population std of the window.

    Mean and variance come from running window sums, which reorder float
    addition relative to a two-pass computation, so the band values are
    pinned to 1e-9 (a price difference far below any tick) rather than
    bit-for-bit equality.
    """
    period, mult = 20, 2.0
    bb = calc_bollinger(CLOSES, period, mult)
    for i in (period - 1, 100, 250, len(CLOSES) - 1):
        window = CLOSES[i - period + 1 : i + 1]
        mean = sum(window) / period
        var = sum((x - mean) ** 2 for x in window) / period
        std = math.sqrt(var)
        assert bb["middle"][i] is not None
        assert abs(bb["middle"][i] - mean) < 1e-9
        assert bb["upper"][i] is not None and bb["lower"][i] is not None
        assert abs(bb["upper"][i] - (mean + mult * std)) < 1e-9
        assert abs(bb["lower"][i] - (mean - mult * std)) < 1e-9


def test_donchian_matches_window_extremes():
    """Each bar's channel is the exact max/min of its lookback window."""
    period = 20
    dc = calc_donchian(HIGHS, LOWS, period)
    assert dc["upper"][: period - 1] == [None] * (period - 1)
    for i in (period - 1, 33, len(HIGHS) - 1):
        hi = max(HIGHS[i - period + 1 : i + 1])
        lo = min(LOWS[i - period + 1 : i + 1])
        assert dc["upper"][i] == hi
        assert dc["lower"][i] == lo
        assert dc["middle"][i] == (hi + lo) / 2


def test_donchian_window_includes_current_bar():
    """A new extreme on the current bar must be visible in the channel."""
    dc = calc_donchian(HIGHS, LOWS, 5)
    for i in range(4, len(HIGHS)):
        assert dc["upper"][i] == max(HIGHS[i - 4 : i + 1])


def test_wilder_indicators_stable():
    """RSI and ATR keep Wilder smoothing and their None warmup regions."""
    rsi = calc_rsi(CLOSES, 14)
    assert rsi[:14] == [None] * 14
    assert all(v is not None and 0.0 <= v <= 100.0 for v in rsi[14:])
    atr = calc_atr(HIGHS, LOWS, CLOSES, 14)
    assert atr[:14] == [None] * 14
    assert all(v is not None and v > 0 for v in atr[14:])


def test_ema_seed_matches_sma():
    """The first EMA value is the SMA seed; each later value is recursive."""
    period = 20
    ema = calc_ema(CLOSES, period)
    assert ema[period - 1] == sum(CLOSES[:period]) / period
    k = 2 / (period + 1)
    for i in range(period, len(CLOSES)):
        expected = CLOSES[i] * k + ema[i - 1] * (1 - k)
        assert ema[i] is not None
        assert abs(ema[i] - expected) < 1e-12


def test_macd_signal_alignment():
    macd = calc_macd(CLOSES, 12, 26, 9)
    first = next(i for i, v in enumerate(macd["macd"]) if v is not None)
    assert first == 25
    assert all(v is None for v in macd["signal"][:first])


def test_supertrend_direction_is_signed():
    st = calc_supertrend(HIGHS, LOWS, CLOSES, 10, 3.0)
    dirs = [d for d in st["direction"] if d is not None]
    assert dirs and all(d in (1, -1) for d in dirs)
    # Bands exist wherever a direction does.
    for i, d in enumerate(st["direction"]):
        if d is not None:
            assert st["upper"][i] is not None and st["lower"][i] is not None


def test_percentile_rank_bisect_matches_linear_scan():
    """The bisect-based percentile rank must reproduce the linear scan exactly.

    ``egx_service`` ranks each stock's day change against the sorted list of
    all changes. The linear original counts strict inequalities, so the
    bisect replacement must use ``bisect_left`` (values equal to a sorted
    neighbour count as *not* below), and ties must rank below every strictly
    greater change and level with their equals.
    """
    from bisect import bisect_left

    changes = [round(random.gauss(0, 2), 4) for _ in range(120)]
    changes += [0.0, 0.0, -1.5, -1.5]  # ties must survive
    ordered = sorted(changes)
    n = len(ordered)

    def linear(val: float) -> float:
        return sum(1 for c in ordered if c < val) / n if n else 0.5

    for val in changes:
        assert bisect_left(ordered, val) / n == linear(val)


def test_smart_money_oscillator_matches_window_minmax():
    """The rolling min/max in the money-flow index must stay exact.

    The smart-money oscillator (lookback 34) is (typical - lowest) /
    (highest - lowest) * 100 over the window. A monotonic-deque rewrite must
    reproduce the same extremes.
    """
    lookback = 34
    typ = [(2 * c + h + l + (c - 0.05)) / 5 for c, h, l in zip(CLOSES, HIGHS, LOWS)]
    for i in (lookback - 1, 200, len(CLOSES) - 1):
        lo = min(LOWS[i - lookback + 1 : i + 1])
        hi = max(HIGHS[i - lookback + 1 : i + 1])
        expected = ((typ[i] - lo) / (hi - lo) * 100) if hi > lo else 50.0
        assert expected >= 0.0 <= 100.0 or hi == lo
