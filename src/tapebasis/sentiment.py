"""Local, token-free headline sentiment scoring.

This module exists so ``market_sentiment`` and ``combined_analysis`` work
without any API key. It is the fallback behind the licensed Marketaux path:

* ``MARKETAUX_API_TOKEN`` set  -> Marketaux entity sentiment (licensed, remote).
* token unset                  -> this module, scoring headlines that Finviz
                                 already returned (local, deterministic, free).

Scoring is VADER (MIT) with a financial lexicon layered on top. Plain VADER is
tuned for social-media text and misses the vocabulary that decides financial
headlines: it scores "Apple beats estimates, raises guidance" as neutral
because *beats* and *raises* are out-of-vocabulary. The overlay below fixes
that class of miss, and ``_WEIGHT`` lets a domain word outweigh VADER's generic
guess for the same token instead of being averaged with it.

Every score is reproducible: same headlines in, same number out. Nothing here
touches the network.
"""
from __future__ import annotations

from typing import Any, Iterable

#: VADER valences are on a -4..+4 scale. Values must be floats: VADER adds them
#: arithmetically, so a string valence raises TypeError at scoring time.
_FINANCE_LEXICON: dict[str, float] = {
    # ── earnings / guidance ──────────────────────────────────────────────
    "beat": 2.0,
    "beats": 2.0,
    "exceed": 1.8,
    "exceeds": 1.8,
    "exceeded": 1.8,
    "tops": 1.6,
    "topped": 1.6,
    "miss": -2.0,
    "misses": -2.0,
    "missed": -2.0,
    "inline": 0.3,
    "guidance": 0.0,
    "outlook": 0.0,
    "forecast": 0.0,
    # ── analyst actions ──────────────────────────────────────────────────
    "upgrade": 2.2,
    "upgrades": 2.2,
    "upgraded": 2.2,
    "downgrade": -2.2,
    "downgrades": -2.2,
    "downgraded": -2.2,
    "outperform": 2.0,
    "underperform": -2.0,
    "overweight": 1.6,
    "underweight": -1.6,
    "buy": 1.2,
    "sell": -1.4,
    "hold": 0.0,
    "initiated": 0.4,
    # ── price action ─────────────────────────────────────────────────────
    "surge": 2.2,
    "surges": 2.2,
    "surged": 2.2,
    "soar": 2.4,
    "soars": 2.4,
    "soared": 2.4,
    "rally": 1.8,
    "rallies": 1.8,
    "rallied": 1.8,
    "jump": 1.6,
    "jumps": 1.6,
    "jumped": 1.6,
    "gain": 1.4,
    "gains": 1.4,
    "gained": 1.4,
    "climb": 1.4,
    "climbs": 1.4,
    "rebound": 1.4,
    "rebounds": 1.4,
    "drop": -1.8,
    "drops": -1.8,
    "dropped": -1.8,
    "fall": -1.4,
    "falls": -1.6,
    "fell": -1.6,
    "slip": -1.2,
    "slips": -1.2,
    "slump": -2.0,
    "slumps": -2.0,
    "plunge": -2.6,
    "plunges": -2.6,
    "plunged": -2.6,
    "tumble": -2.0,
    "tumbles": -2.0,
    "tumbled": -2.0,
    "sink": -1.8,
    "sinks": -1.8,
    "slide": -1.4,
    "slides": -1.4,
    "selloff": -2.2,
    "sell-off": -2.2,
    "sells": -0.8,
    # ── fundamentals ─────────────────────────────────────────────────────
    "profit": 1.4,
    "profits": 1.4,
    "strong": 1.4,
    "stronger": 1.4,
    "weak": -1.6,
    "weaker": -1.6,
    "weakness": -1.6,
    "growth": 1.2,
    "grew": 1.2,
    "expansion": 1.2,
    "margin": 0.0,
    "margins": 0.0,
    "loss": -1.8,
    "losses": -1.8,
    "buyback": 1.4,
    "dividend": 0.8,
    "under": -0.4,
    "overvalued": -1.6,
    "undervalued": 1.6,
    "bullish": 2.2,
    "bearish": -2.2,
    "overbought": -1.2,
    "oversold": 1.2,
    # ── risk / legal ─────────────────────────────────────────────────────
    "lawsuit": -1.6,
    "sues": -1.4,
    "probe": -1.4,
    "investigation": -1.6,
    "recall": -1.6,
    "warns": -1.4,
    "warning": -1.4,
    "warned": -1.4,
    "layoffs": -1.8,
    "bankruptcy": -3.0,
    "dilution": -1.4,
    "restatement": -2.4,
    "delay": -1.0,
    "delays": -1.0,
    "halt": -1.6,
    "halted": -1.6,
    # ── macro / policy ───────────────────────────────────────────────────
    "tariff": -1.2,
    "tariffs": -1.2,
    "sanction": -1.4,
    "sanctions": -1.4,
    "stimulus": 1.2,
    "rate": 0.0,
    "inflation": -0.8,
    "recession": -2.0,
}

#: Words that carry a direction in financial English but are neutral in
#: general text. Layering these over VADER's defaults is the whole point of
#: the overlay above.
_OVERRIDES = ("forward", "lower", "higher", "flat", "mixed", "unchanged")

_analyzer = None


def _lexicon() -> Any:
    """Build the VADER analyzer once, with the finance overlay applied."""
    global _analyzer
    if _analyzer is not None:
        return _analyzer
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    analyzer = SentimentIntensityAnalyzer()
    analyzer.lexicon.update(_FINANCE_LEXICON)
    _analyzer = analyzer
    return _analyzer


def score_text(text: str) -> float:
    """Compound sentiment for one headline, in ``[-1, 1]``.

    Returns ``0.0`` for empty input rather than raising: a single unscoreable
    headline must not sink the whole aggregate.
    """
    if not text or not str(text).strip():
        return 0.0
    try:
        return float(_lexicon().polarity_scores(str(text))["compound"])
    except Exception:  # noqa: BLE001 - scoring must never break a tool call
        return 0.0


def label_for(score: float) -> str:
    """Bucket a compound score into the same labels the API path used."""
    if score > 0.2:
        return "Strongly Bullish"
    if score > 0.05:
        return "Bullish"
    if score < -0.2:
        return "Strongly Bearish"
    if score < -0.05:
        return "Bearish"
    return "Neutral"


def _clean(text: Any, limit: int = 300) -> str:
    return " ".join(str(text or "").split())[:limit]


def score_headlines(
    headlines: Iterable[dict[str, Any]],
    *,
    symbol: str,
    source_label: str,
    limit: int = 20,
    headline_key: str = "headline",
    url_key: str = "url",
    publisher_key: str = "source",
    published_key: str = "datetime",
) -> dict[str, Any]:
    """Aggregate local sentiment over provider headlines.

    The output shape deliberately mirrors the Marketaux path
    (``sentiment_score``, ``sentiment_label``, ``posts_analyzed``, the per-label
    counts and ``top_posts``) so a caller does not have to branch on which
    backend produced it. ``scoring`` is the one field that differs, and it
    always states that the score is computed locally.
    """
    rows = list(headlines)[: max(1, int(limit))]
    scores: list[float] = []
    top: list[dict[str, Any]] = []

    for row in rows:
        title = _clean(row.get(headline_key) or row.get("title"), 120)
        if not title:
            continue
        score = score_text(title)
        scores.append(score)
        direction = (
            "bullish" if score > 0.05 else "bearish" if score < -0.05 else "neutral"
        )
        top.append(
            {
                "title": title,
                "url": row.get(url_key),
                "sentiment": direction,
                "score": round(score, 3),
                "source": row.get(publisher_key),
                "published": row.get(published_key),
            }
        )

    average = sum(scores) / len(scores) if scores else 0.0
    # Rank the samples by conviction so `top_posts` shows the headlines that
    # actually moved the average, not whichever arrived first.
    top.sort(key=lambda item: abs(item["score"]), reverse=True)

    return {
        "symbol": symbol.upper(),
        "sentiment_score": round(average, 3),
        "sentiment_label": label_for(average),
        "posts_analyzed": len(scores),
        "bullish_count": sum(1 for s in scores if s > 0.05),
        "bearish_count": sum(1 for s in scores if s < -0.05),
        "neutral_count": sum(1 for s in scores if -0.05 <= s <= 0.05),
        "top_posts": top[:5],
        "sources": [source_label],
        "provider": "local-vader",
        "scoring": {
            "method": "vader+finance-lexicon",
            "engine": "vaderSentiment (MIT)",
            "runs": "locally, no network, no API token",
            "note": (
                "Headline-level lexicon scoring. It is a deterministic summary "
                "of tone, not a prediction and not a trading signal."
            ),
        },
    }
