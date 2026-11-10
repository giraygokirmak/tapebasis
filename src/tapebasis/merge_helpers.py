"""Payload shapers: raw provider dicts -> comparable/normalised field dicts.

Each ``tv_*`` / ``fv_*`` function is a pure mapper. The reconciler uses them to
extract values for comparison and to fill in fields only one provider offers.
Keeping them here (not in the tool modules) makes the mapping auditable and
unit-testable without any network access.
"""
from __future__ import annotations

from typing import Any, Iterable

from .symbols import canonical_index
from .utils import lead_float, to_float

# ── Quote ────────────────────────────────────────────────────────────────────


def _fv_quote_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("snapshot_numeric") or {}


def fv_quote_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Finviz ``get_quote`` payload."""
    snapshot = _fv_quote_snapshot(payload)
    header = payload.get("last_close") or {}
    after = payload.get("after_hours") or {}
    return {
        "company": payload.get("company"),
        "sector": payload.get("sector"),
        "industry": payload.get("industry"),
        "country": payload.get("country"),
        "market_cap": snapshot.get("Market Cap"),
        "pe_ratio": snapshot.get("P/E"),
        "forward_pe": snapshot.get("Forward P/E"),
        "peg": snapshot.get("PEG"),
        "ps_ratio": snapshot.get("P/S"),
        "pb_ratio": snapshot.get("P/B"),
        "eps_ttm": snapshot.get("EPS (ttm)"),
        "dividend_yield": snapshot.get("Dividend TTM"),
        "beta": snapshot.get("Beta"),
        "rsi_14": snapshot.get("RSI (14)"),
        "atr_14": lead_float(snapshot.get("ATR (14)")),
        "volume": lead_float(snapshot.get("Volume")),
        "avg_volume": lead_float(snapshot.get("Avg Volume")),
        "relative_volume": lead_float(snapshot.get("Rel Volume")),
        "shares_float": snapshot.get("Shs Float"),
        "short_float": snapshot.get("Short Float"),
        "sma20": snapshot.get("SMA20"),
        "sma50": snapshot.get("SMA50"),
        "sma200": snapshot.get("SMA200"),
        # Without the leading numeric coercion these stay annotated strings
        # ("351.73 -5.64%") and can never be compared with the other provider.
        "week_52_high": lead_float(snapshot.get("52W High")),
        "week_52_low": lead_float(snapshot.get("52W Low")),
        # Finviz's page does not publish a day open/high/low row in its
        # snapshot table, so these stay absent rather than being invented: a
        # spec whose getter returns None is a provider that has nothing to say,
        # which is different from a provider that said nothing.
        "after_hours_price": after.get("price"),
        "after_hours_change_percent": after.get("change_percent"),
        # Identity fields the quote payload already carried and the shaper
        # dropped: the company website and logo were parsed into the payload
        # and then never reached an agent.
        "website": payload.get("website"),
        "logo_url": payload.get("logo_url"),
        "market_cap_class": payload.get("market_cap_class"),
        "etf_type": payload.get("etf_type"),
        # The revenue/expense breakdown and the product/region/segment revenue
        # split. Finviz ships this as a JSON island on the same page the quote
        # already fetched, so it costs no extra request; it was previously
        # dropped before it reached any tool.
        "income_breakdown": payload.get("income_breakdown"),
        "snapshot": payload.get("snapshot") or {},
        "snapshot_numeric": snapshot,
        "profile": payload.get("profile"),
        "peers": payload.get("peers") or [],
        "last_close": header,
        "after_hours": after,
        "finviz_ticker": payload.get("ticker"),
        "ticker_warning": payload.get("ticker_warning"),
    }


def tv_quote_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalise a TradingView scanner row (one leg of a multi-source quote)."""
    return {
        "price": payload.get("close"),
        "change_percent": payload.get("change"),
        "volume": payload.get("volume"),
        "market_cap": payload.get("market_cap_basic"),
        "pe_ratio": payload.get("price_earnings_ttm"),
        "eps_ttm": payload.get("earnings_per_share_basic_ttm"),
        "dividend_yield": payload.get("dividends_yield_current"),
        "sector": payload.get("sector"),
        "industry": payload.get("industry"),
        "beta": payload.get("beta_1_year"),
        "rsi_14": payload.get("RSI"),
        "atr_14": payload.get("ATR"),
        "week_52_high": payload.get("price_52_week_high"),
        "week_52_low": payload.get("price_52_week_low"),
        "relative_volume": payload.get("relative_volume_10d_calc"),
        "tradingview_symbol": payload.get("ticker"),
        "description": payload.get("description"),
    }


def fv_quote_spec_values(payload: dict[str, Any]) -> dict[str, Any]:
    """The subset of Finviz quote fields that participate in comparison."""
    fields = fv_quote_fields(payload)
    header = payload.get("last_close") or {}
    fields["price"] = header.get("price")
    fields["change_percent"] = header.get("change_percent")
    fields["previous_close"] = (payload.get("snapshot_numeric") or {}).get("Prev Close")
    return fields


# ── Bulk prices ──────────────────────────────────────────────────────────────


def fv_screener_row_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise one Finviz screener row."""
    return {
        "symbol": row.get("ticker"),
        "company": row.get("company"),
        "price": row.get("price"),
        "change_percent": row.get("change"),
        "previous_close": row.get("prevClose"),
        "volume": row.get("volume"),
        "market_cap_millions": row.get("marketCap"),
        "pe_ratio": row.get("PE"),
        "sector": row.get("sector"),
        "industry": row.get("industry"),
        "country": row.get("country"),
    }


def tv_screener_row_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise one TradingView screener row."""
    return {
        "symbol": row.get("symbol") or row.get("name"),
        "company": row.get("description"),
        "price": row.get("price") or row.get("close"),
        "change_percent": row.get("change_percent") or row.get("change"),
        "volume": row.get("volume"),
        "market_cap": row.get("market_cap_basic"),
        "pe_ratio": row.get("price_earnings_ttm"),
        "ticker": row.get("ticker"),
    }


# ── Indices ──────────────────────────────────────────────────────────────────


def fv_indices_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Map Finviz indices -> ``{canonical: {...}}``."""
    out: dict[str, Any] = {}
    for row in payload.get("indices") or []:
        name = str(row.get("ticker") or "").upper()
        canonical = canonical_index(name) or name
        out[canonical] = {
            "level": row.get("last"),
            "previous_close": row.get("prev_close"),
            "change": row.get("change"),
            "change_percent": row.get("change_percent"),
            "day_open": row.get("day_open"),
            "day_high": row.get("day_high"),
            "day_low": row.get("day_low"),
            "name": row.get("name"),
            "source_ticker": name,
            # ``lastDate`` is a bare ``YYYYMMDD``; the freshness parser reads it
            # so a provider that has rolled into the next session is ordered
            # correctly instead of being treated as a conflicting level.
            "price_timestamp": row.get("last_update"),
        }
    return {"indices": out}


#: Finviz index tickers are folded onto canonical names through
#: :func:`canonical_index` inside the field mappers, so no separate
#: index-symbol table is needed here: the spellings live in exactly one home
#: (:data:`tapebasis.symbols.INSTRUMENTS`) and the snapshot list in
#: :data:`tapebasis.symbols.INDEX_SNAPSHOT`.


def tv_indices_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Map the TradingView/Yahoo market snapshot -> ``{canonical: {...}}``."""
    out: dict[str, Any] = {}
    for row in payload.get("indices") or []:
        symbol = str(row.get("symbol") or "").upper()
        canonical = canonical_index(symbol) or symbol.lstrip("^")
        out[canonical] = {
            "level": row.get("price"),
            "change_percent": row.get("change_pct"),
            "currency": row.get("currency"),
            "name": row.get("name"),
            "source_ticker": symbol,
            "price_timestamp": row.get("price_timestamp"),
        }
    return {"indices": out}


# ── News ─────────────────────────────────────────────────────────────────────


def _norm_title(title: Any) -> str:
    return " ".join(str(title or "").lower().split())


def fv_news_fields(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("news") or payload.get("items") or []
    normalised = []
    for item in items:
        title = item.get("headline") or item.get("title")
        normalised.append(
            {
                "title": title,
                "source": item.get("source"),
                "published": item.get("datetime") or item.get("date"),
                "url": item.get("url") or item.get("link"),
                "reaction_day_percent": item.get("reaction_day_percent"),
                "reaction_next_day_percent": item.get("reaction_next_day_percent"),
                "titles_key": _norm_title(title),
            }
        )
    return {"items": normalised, "count": len(normalised), "ticker": payload.get("ticker")}


def tv_news_fields(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items") or []
    normalised = []
    for item in items:
        normalised.append(
            {
                "title": item.get("title"),
                "source": item.get("source"),
                "published": item.get("published"),
                "url": item.get("url"),
                "summary": item.get("summary"),
                "titles_key": _norm_title(item.get("title")),
            }
        )
    return {"items": normalised, "count": len(normalised), "ticker": payload.get("symbol")}


def yahoo_news_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Yahoo news-search payload (same shape as the TV shaper)."""
    return tv_news_fields(payload)


def yahoo_quote_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Yahoo chart quote into the comparable field dict."""
    return {
        "price": payload.get("price"),
        "change_percent": payload.get("change_pct"),
        "previous_close": payload.get("previous_close"),
        "week_52_high": payload.get("52w_high"),
        "week_52_low": payload.get("52w_low"),
        "currency": payload.get("currency"),
        "exchange": payload.get("exchange"),
        "market_state": payload.get("market_state"),
        "price_timestamp": payload.get("market_time"),
    }


def news_overlap(tv_items: Iterable[dict[str, Any]], fv_items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Share of TradingView headline titles also present in the Finviz list."""
    tv_keys = {item["titles_key"] for item in tv_items if item.get("titles_key")}
    fv_keys = {item["titles_key"] for item in fv_items if item.get("titles_key")}
    if not tv_keys or not fv_keys:
        return {"overlap_pct": None, "shared": 0, "tv_count": len(tv_keys), "fv_count": len(fv_keys)}
    shared = tv_keys & fv_keys
    return {
        "overlap_pct": round(len(shared) / max(1, len(tv_keys)) * 100, 1),
        "shared": len(shared),
        "tv_count": len(tv_keys),
        "fv_count": len(fv_keys),
    }


# ── Options ──────────────────────────────────────────────────────────────────


def _option_rows(contracts: Iterable[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    """Normalise option contracts from either provider.

    Finviz uses ``lastVolume``/``openInterest``/``bidPrice``/``askPrice``/
    ``lastClose``; Yahoo uses ``volume``/``openInterest``/``bid``/``ask``/
    ``lastPrice``.
    """
    out = []
    for contract in contracts:
        out.append(
            {
                "side": side,
                "strike": to_float(contract.get("strike")),
                "expiry": contract.get("expiry") or contract.get("expiration"),
                "volume": to_float(
                    contract.get("lastVolume") or contract.get("volume")
                ),
                "open_interest": to_float(
                    contract.get("openInterest") or contract.get("open_interest")
                ),
                "iv": to_float(
                    contract.get("iv") or contract.get("implied_volatility")
                    or contract.get("impliedVolatility")
                ),
                "last": to_float(
                    contract.get("lastClose") or contract.get("last_price")
                    or contract.get("lastPrice") or contract.get("last")
                ),
                "bid": to_float(contract.get("bidPrice") or contract.get("bid")),
                "ask": to_float(contract.get("askPrice") or contract.get("ask")),
            }
        )
    return out


def fv_options_fields(payload: dict[str, Any]) -> dict[str, Any]:
    contracts = payload.get("contracts") or []
    # Finviz tags each row with ``type`` = "call" | "put".
    calls = _option_rows(
        [c for c in contracts if str(c.get("type", "")).lower() == "call"], "call"
    )
    puts = _option_rows(
        [c for c in contracts if str(c.get("type", "")).lower() == "put"], "put"
    )
    return {
        "expiries": payload.get("expiries") or [],
        "expiry": payload.get("expiry"),
        "underlying_price": payload.get("last_close"),
        "calls": calls,
        "puts": puts,
        "contract_count": payload.get("count"),
        "raw_contracts": contracts,
    }


def tv_options_fields(payload: dict[str, Any]) -> dict[str, Any]:
    calls = payload.get("calls") or []
    puts = payload.get("puts") or []
    return {
        "expiries": payload.get("available_expiries") or [],
        "expiry": payload.get("requested_expiry"),
        "underlying_price": payload.get("underlying_price"),
        "underlying_change_percent": payload.get("underlying_change_pct"),
        "calls": _option_rows(calls, "call"),
        "puts": _option_rows(puts, "put"),
        "contract_count": payload.get("call_count", 0) + payload.get("put_count", 0),
        "raw_calls": calls,
        "raw_puts": puts,
    }


def option_overlap(
    tv_rows: Iterable[dict[str, Any]], fv_rows: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Match contracts by strike and compare volume / open interest.

    Volume is the primary agreement signal. Open interest is compared only when
    *both* sides report a positive value: Yahoo zeroes OI on contracts expiring
    the same day, so a ``0 vs N`` pair is a known provider convention, not a
    contradiction, and is counted separately instead of as a mismatch.
    """
    fv_list = list(fv_rows)
    tv_index = {round(float(r["strike"]), 4): r for r in tv_rows if r.get("strike") is not None}
    rows = []
    volume_agree = volume_compared = 0
    oi_agree = oi_compared = oi_unavailable = 0
    for contract in fv_list:
        if contract.get("strike") is None:
            continue
        key = round(float(contract["strike"]), 4)
        counterpart = tv_index.get(key)
        if counterpart is None:
            continue
        volume_match = _close(counterpart.get("volume"), contract.get("volume"))
        tv_oi = to_float(counterpart.get("open_interest"))
        fv_oi = to_float(contract.get("open_interest"))
        if tv_oi is None or fv_oi is None or tv_oi <= 0 or fv_oi <= 0:
            oi_match = None
            oi_unavailable += 1
        else:
            oi_match = _close(tv_oi, fv_oi, 1.0)
            oi_compared += 1
            if oi_match:
                oi_agree += 1
        if volume_match is not None:
            volume_compared += 1
            if volume_match:
                volume_agree += 1
        rows.append(
            {
                "strike": key,
                "side": contract["side"],
                "volume": {
                    "tv": counterpart.get("volume"),
                    "fv": contract.get("volume"),
                    "match": volume_match,
                },
                "open_interest": {
                    "tv": counterpart.get("open_interest"),
                    "fv": contract.get("open_interest"),
                    "match": oi_match,
                },
            }
        )
    return {
        "matched_contracts": len(rows),
        "matched_pct_of_finviz": round(len(rows) / max(1, len(fv_list)) * 100, 1),
        "volume_compared": volume_compared,
        "volume_agreeing": volume_agree,
        "volume_agree_pct": round(volume_agree / volume_compared * 100, 1) if volume_compared else None,
        "open_interest_compared": oi_compared,
        "open_interest_agreeing": oi_agree,
        "open_interest_unavailable": oi_unavailable,
        "samples": rows[:12],
    }


def _close(left: Any, right: Any, tolerance_pct: float = 5.0) -> bool | None:
    lhs, rhs = to_float(left), to_float(right)
    if lhs is None or rhs is None:
        return None
    denominator = max(abs(lhs), abs(rhs), 1e-9)
    return abs(lhs - rhs) / denominator * 100 <= tolerance_pct


# ── Earnings ─────────────────────────────────────────────────────────────────


def fv_earnings_fields(payload: dict[str, Any]) -> dict[str, Any]:
    quarterly = payload.get("quarterly") or []
    latest = quarterly[-1] if quarterly else {}
    return {
        "earnings_date": payload.get("earnings_date"),
        "latest_quarter": latest,
        "latest_eps_actual": latest.get("epsActual"),
        "latest_eps_estimate": latest.get("epsEstimate"),
        "quarterly": quarterly,
        "annual": payload.get("annual") or [],
        "revisions": payload.get("revisions") or [],
        "price_reactions": payload.get("price_reactions") or [],
        "counts": payload.get("counts") or {},
    }
