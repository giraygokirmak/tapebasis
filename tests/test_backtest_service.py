"""Regression tests for backtest signal and execution bar separation."""
from __future__ import annotations

import pytest

from tapebasis.providers.tradingview.core.services import backtest_service


def _candles() -> list[dict]:
    """Three bars whose signal close differs materially from the next open."""
    return [
        {
            "date": f"2026-01-0{index}",
            "open": open_price,
            "high": max(open_price, close) + 1,
            "low": min(open_price, close) - 1,
            "close": close,
            "volume": 1000,
        }
        for index, (open_price, close) in enumerate(
            ((10.0, 10.0), (11.0, 11.0), (24.0, 26.0)), start=1
        )
    ]


@pytest.fixture
def close_signal_indicators(monkeypatch):
    """Create an entry on the middle close for every close-confirmed strategy."""
    monkeypatch.setattr(backtest_service, "calc_rsi", lambda closes, period: [50, 30, 30])
    monkeypatch.setattr(
        backtest_service,
        "calc_bollinger",
        lambda closes, period, std_mult: {
            "lower": [0, 12, 12],
            "middle": [0, 20, 20],
        },
    )
    monkeypatch.setattr(
        backtest_service,
        "calc_macd",
        lambda closes, fast, slow, signal: {
            "macd": [0, 1, 1],
            "signal": [1, 0, 0],
        },
    )

    def fake_ema(closes, period):
        return [0, 1, 1] if period == 20 else [1, 0, 0]

    monkeypatch.setattr(backtest_service, "calc_ema", fake_ema)
    monkeypatch.setattr(
        backtest_service,
        "calc_sma",
        lambda closes, period: [100, 100, 100]
        if period == 50
        else [10, 10, 10],
    )
    monkeypatch.setattr(backtest_service, "calc_atr", lambda highs, lows, closes, period: [1, 1, 1])
    monkeypatch.setattr(
        backtest_service,
        "calc_supertrend",
        lambda highs, lows, closes, period, multiplier: {
            "direction": [-1, 1, 1]
        },
    )


@pytest.mark.parametrize(
    "runner_name",
    [
        "_run_rsi",
        "_run_bollinger",
        "_run_macd",
        "_run_ema_cross",
        "_run_supertrend",
        "_run_rsi_pullback",
        "_run_keltner_breakout",
        "_run_triple_ema",
    ],
)
def test_close_confirmed_entry_executes_at_next_bar_open(
    close_signal_indicators, runner_name
):
    trades = getattr(backtest_service, runner_name)(_candles())
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_date"] == "2026-01-03"
    assert trade["entry_price"] == 24.0
    assert trade["exit_price"] == 26.0
    assert trade["forced_exit"] is True


@pytest.mark.parametrize("runner_name", ["_run_rsi", "_run_donchian"])
def test_last_bar_cannot_open_a_new_position(close_signal_indicators, monkeypatch, runner_name):
    candles = _candles()
    if runner_name == "_run_rsi":
        # The earlier bars carry no oversold reading, so this specifically
        # isolates a signal that becomes visible only on the final close.
        monkeypatch.setattr(backtest_service, "calc_rsi", lambda closes, period: [50, 50, 30])
    else:
        candles[0]["high"] = candles[1]["high"] = 100
        candles[2]["high"] = 120
        monkeypatch.setattr(
            backtest_service,
            "calc_donchian",
            lambda highs, lows, period: {
                "upper": [110, 110, 110],
                "lower": [0, 0, 0],
            },
        )
    assert getattr(backtest_service, runner_name)(candles) == []


def test_pending_entry_does_not_cancel_the_following_signal_bar(monkeypatch):
    """A filled entry remains pending only for its one execution bar."""
    candles = _candles()
    monkeypatch.setattr(
        backtest_service, "calc_rsi", lambda closes, period: [50, 30, 30]
    )
    [trade] = backtest_service._run_rsi(candles)
    assert trade["entry_date"] == "2026-01-03"


def test_final_bar_still_forces_exit_after_a_pending_exit_signal(monkeypatch):
    """The end of history wins over an exit order with no following bar."""
    candles = _candles()
    monkeypatch.setattr(
        backtest_service, "calc_rsi", lambda closes, period: [50, 30, 70]
    )
    [trade] = backtest_service._run_rsi(candles)
    assert trade["exit_date"] == "2026-01-03"
    assert trade["exit_price"] == 26.0
    assert trade["forced_exit"] is True


def test_close_confirmed_exit_executes_at_next_bar_open(monkeypatch):
    """An exit observed at a close cannot fill at that completed close."""
    candles = _candles()
    candles.append({**candles[-1], "date": "2026-01-04", "open": 30.0})
    monkeypatch.setattr(
        backtest_service, "calc_rsi", lambda closes, period: [50, 30, 70, 70]
    )
    [trade] = backtest_service._run_rsi(candles, overbought=60)
    assert trade["exit_date"] == "2026-01-04"
    assert trade["exit_price"] == 30.0
    assert "forced_exit" not in trade


def test_donchian_keeps_its_intrabar_signal_and_close_execution_model(monkeypatch):
    """Donchian is deliberately not converted into a next-open strategy."""
    candles = _candles()
    candles[1]["high"] = 120
    monkeypatch.setattr(
        backtest_service,
        "calc_donchian",
        lambda highs, lows, period: {
            "upper": [110, 110, 110],
            "lower": [105, 105, 105],
        },
    )
    trades = backtest_service._run_donchian(candles)
    assert trades[0]["entry_date"] == "2026-01-02"
    assert trades[0]["entry_price"] == 11.0


def test_equity_marks_the_next_open_entry_bar_to_its_close():
    candles = _candles()
    candles[1]["close"] = 20.0
    trades = [
        {
            "entry_date": "2026-01-02",
            "entry_price": 24.0,
            "exit_date": "2026-01-03",
            "exit_price": 26.0,
            "return_pct": (26.0 / 24.0 - 1) * 100,
        }
    ]
    equity = backtest_service._mark_to_market_equity(trades, 100.0, candles)
    assert equity[1] == pytest.approx(100.0 * 20.0 / 24.0)
    assert equity[2] == pytest.approx(100.0 * 26.0 / 24.0)


def test_backtest_results_declare_the_execution_model(monkeypatch):
    candles = [
        {
            "date": f"2026-01-{index:02d}",
            "open": float(index),
            "high": float(index + 1),
            "low": float(index - 1),
            "close": float(index),
            "volume": 1000,
        }
        for index in range(1, 91)
    ]
    result = backtest_service.run_backtest("TEST", "rsi", candles=candles)
    assert result["execution_model"]["mode"] == "next_bar_open"
    assert result["execution_model"]["no_entry_on_final_bar"] is True

    comparison = backtest_service.compare_strategies("TEST", candles=candles)
    assert comparison["execution_model"] == result["execution_model"]

    monkeypatch.setattr(
        backtest_service, "_fetch_ohlcv", lambda symbol, period, interval: candles
    )
    walk_forward = backtest_service.walk_forward_backtest("TEST", "rsi")
    assert walk_forward["execution_model"] == result["execution_model"]
