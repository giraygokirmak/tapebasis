"""Regression: an index row is one session, not a per-field provider pick.

The measured bug: SPX reported a level 0.74 % above its previous close beside a
day change of -0.38 %. The level and the previous close came from the provider
that had rolled into the next session while the change percent came from a row
still holding the previous session, so four numbers describing one observation
contradicted each other on the page.

The test drives the tool with two providers on different session dates and
asserts the row reports only one session's numbers, and that the numbers are
internally consistent (implied percent matches reported percent).
"""
from __future__ import annotations

import pytest

from tapebasis import tools_market


def _resolved(provider: str, symbol: str) -> object:
    from tapebasis.symbols import Resolution

    return Resolution(
        query="SPX",
        provider=provider,
        symbol=symbol,
        method="explicit",
        confidence=1.0,
        note="",
    )


@pytest.fixture
def split_session(monkeypatch):
    """Providers disagree on session date for SPX, which is the hazard."""
    from tapebasis import fv_access, tv_access, yh_access

    async def tv_snapshot():
        # TradingView has rolled into today: level 6900.0 against a previous
        # close of 6850.0, so its own implied change is +0.73 %.
        return {
            "indices": [
                {
                    "symbol": "SP:SPX",
                    "price": 6900.0,
                    "change_pct": 0.73,
                    "name": "S&P 500",
                    "price_timestamp": "2026-11-11T14:35:00+00:00",
                }
            ]
        }

    async def fv_indices():
        # Finviz is still on yesterday's session and carries the whole block:
        # level 6874.0, previous close 6900.0, change -26.0, change -0.38 %.
        return {
            "indices": [
                {
                    "ticker": "SPX",
                    "name": "S&P 500",
                    "last": 6874.0,
                    "prev_close": 6900.0,
                    "change": -26.0,
                    "change_percent": -0.38,
                    "last_update": "20261110",
                }
            ]
        }

    async def yh_snapshot():
        return {"indices": []}

    monkeypatch.setattr(tv_access, "index_snapshot", tv_snapshot)
    monkeypatch.setattr(fv_access, "indices", fv_indices)
    monkeypatch.setattr(yh_access, "index_snapshot", yh_snapshot)


@pytest.mark.asyncio
async def test_index_row_never_mixes_two_sessions(split_session):
    """The day-quote block comes from one session, so its numbers agree."""
    result = await tools_market.market_indices()
    row = result["data"]["indices"]["SPX"]

    # TradingView printed more recently, so its level is the one shown.
    assert row["level"] == pytest.approx(6900.0)
    assert row["level_source"] == "TRADINGVIEW"

    # Its own day change is served, and it belongs to TradingView's session.
    assert row["change_percent"] == pytest.approx(0.73)
    # Finviz's previous close belongs to the *other* session, so it is not
    # borrowed. Pairing it with today's level is exactly the contradiction that
    # was measured: a level 0.74 % above its previous close beside -0.38 %.
    assert row["previous_close"] is None
    assert row["change"] is None
    # Nothing on the row came from the other session.
    for name in ("previous_close", "change", "change_percent"):
        source = (row["fields"].get(name) or {}).get("source")
        assert source in (None, "TRADINGVIEW")


@pytest.mark.asyncio
async def test_index_row_is_internally_consistent(monkeypatch):
    """When one provider supplies the whole block, the arithmetic must close."""
    from tapebasis import fv_access, tv_access, yh_access

    async def tv_snapshot():
        return {"indices": []}

    async def fv_indices():
        return {
            "indices": [
                {
                    "ticker": "SPX",
                    "name": "S&P 500",
                    "last": 6874.0,
                    "prev_close": 6900.0,
                    "change": -26.0,
                    "change_percent": -0.38,
                    "last_update": "20261111",
                }
            ]
        }

    async def yh_snapshot():
        return {"indices": []}

    monkeypatch.setattr(tv_access, "index_snapshot", tv_snapshot)
    monkeypatch.setattr(fv_access, "indices", fv_indices)
    monkeypatch.setattr(yh_access, "index_snapshot", yh_snapshot)

    result = await tools_market.market_indices()
    row = result["data"]["indices"]["SPX"]

    implied = (row["level"] - row["previous_close"]) / row["previous_close"] * 100
    assert implied == pytest.approx(row["change_percent"], abs=0.01)
    assert row["level"] - row["previous_close"] == pytest.approx(row["change"])

