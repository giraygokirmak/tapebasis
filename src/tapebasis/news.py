"""Merge symbol news from TradingView/Marketaux, Finviz and Yahoo Finance.

StockAnalysis and Bloomberg currently expose quote and market-board adapters,
not symbol-news feeds in this server. The available feeds are asked directly and
merged into a newest-first list. Cross-provider matching indicates that they
published the same story, possibly syndicated from one newswire. It is provider
corroboration, not independent editorial verification or proof of truth.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit

from . import fv_access, symbols, tv_access, yh_access
from .freshness import parse_news_timestamp
from .merge_helpers import fv_news_fields, tv_news_fields, yahoo_news_fields
from .providers_state import NotApplicable, provider_from_answered
from .reconcile import FINVIZ, TRADINGVIEW, YAHOO, Pair, ask

#: Every news-shaped symbol response carries this many stories by default.
NEWS_LIMIT = 10
MAX_NEWS_LIMIT = 50
NEWS_PROVIDERS = (TRADINGVIEW, FINVIZ, YAHOO)

#: Display precedence selects a representative and breaks equal-time ties. It
#: never displaces a newer Yahoo or TradingView story with an older Finviz one.
_DISPLAY_ORDER = (FINVIZ, TRADINGVIEW, YAHOO)

_STOPWORDS = frozenset({
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "is",
    "its", "of", "on", "or", "s", "that", "the", "their", "this", "to", "with",
})
_WORD = re.compile(r"[a-z0-9]+")


def news_limit(value: Any = NEWS_LIMIT) -> int:
    """Return the requested story count bounded to 1 through 50, default 10."""
    return max(1, min(int(value), MAX_NEWS_LIMIT))


def _normalise_title(title: Any) -> str:
    """Return punctuation-free lowercase words for headline comparison."""
    return " ".join(_WORD.findall(str(title or "").lower()))


def _significant_tokens(title: Any) -> frozenset[str]:
    """Return non-stopword tokens used to judge headline similarity."""
    return frozenset(_normalise_title(title).split()) - _STOPWORDS


def _url_key(url: Any) -> str | None:
    """Return a tracking-insensitive article URL key, or None when unusable."""
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    return (host + parts.path.rstrip("/")).lower() or None


def _match_kind(story: dict[str, Any], item: dict[str, Any]) -> str | None:
    """Return the evidence for a story match, or None for a different story.

    Match in order: the same normalized URL, the same normalized headline, then
    a similar headline sharing at least four significant words with Jaccard
    similarity at least 0.55. Merely naming the same company is not sufficient.
    """
    story_urls = {
        key for entry in story["entries"] if (key := _url_key(entry.get("url")))
    }
    if (key := _url_key(item.get("url"))) and key in story_urls:
        return "same_url"
    story_titles = {
        _normalise_title(entry.get("title")) for entry in story["entries"]
    }
    normalized = _normalise_title(item.get("title"))
    if normalized and normalized in story_titles:
        return "same_title"
    tokens = _significant_tokens(item.get("title"))
    if len(tokens) >= 4:
        for entry in story["entries"]:
            other = _significant_tokens(entry.get("title"))
            shared = len(tokens & other)
            if shared >= 4 and shared / len(tokens | other) >= 0.55:
                return "similar_title"
    return None


def _published_at(item: dict[str, Any], now: datetime) -> datetime | None:
    """Return one item's UTC publication time with one shared relative clock."""
    return parse_news_timestamp(item.get("published"), reference=now)


def _shortfall(block: dict[str, Any]) -> str | None:
    """Return a concrete reason when fewer real stories than requested exist."""
    if block["count"] >= block["limit"]:
        return None
    failures = [
        f"{error['provider']} ({error['code']})"
        for error in block["errors"]
        if error.get("code") != "NOT_ATTEMPTED"
    ]
    reason = (
        f"available feeds supplied {block['unique_stories']} unique valid stories, "
        f"fewer than the requested limit of {block['limit']}"
    )
    if failures:
        reason += "; unavailable calls: " + ", ".join(failures)
    return reason + "; no filler stories were added"


def merge_news(
    feeds: dict[str, Iterable[dict[str, Any]]],
    *,
    limit: int = NEWS_LIMIT,
    asked: Iterable[str] = NEWS_PROVIDERS,
    errors: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Merge valid provider items into a newest-first story-consensus block.

    Returns ``items`` (at most ``limit`` unique stories), the real ``count``,
    per-item ``providers``/``provider_count``/``consensus``/``matching`` and
    alternate ``headlines``, plus audit feeds and coverage. Unknown publication
    times stay ``null`` and sort last. A repeated item from one provider is
    collapsed but never increases consensus. Fewer than the requested stories
    produces ``shortfall_reason`` rather than fabricated filler.
    """
    limit = news_limit(limit)
    stories: list[dict[str, Any]] = []
    duplicate_items = 0
    provider_counts: dict[str, int] = {}
    by_provider: dict[str, list[dict[str, Any]]] = {}
    for provider in _DISPLAY_ORDER:
        items = [
            item for item in (feeds.get(provider) or [])
            if str(item.get("title") or "").strip()
        ]
        by_provider[provider] = items
        provider_counts[provider] = len(items)
        for item in items:
            matched_story = None
            match = None
            duplicate = False
            for story in stories:
                candidate = _match_kind(story, item)
                if not candidate:
                    continue
                if provider in story["providers"]:
                    duplicate = True
                    break
                matched_story, match = story, candidate
                break
            if duplicate:
                duplicate_items += 1
            elif matched_story is None:
                stories.append({
                    "providers": [provider], "entries": [item], "matching": [],
                })
            else:
                matched_story["providers"].append(provider)
                matched_story["entries"].append(item)
                if match not in matched_story["matching"]:
                    matched_story["matching"].append(match)

    merged: list[dict[str, Any]] = []
    reference = datetime.now(timezone.utc)
    for sequence, story in enumerate(stories):
        entries = story["entries"]
        representative = entries[0]
        newest = None
        newest_iso = None
        published = [
            (stamp, item) for item in entries if (stamp := _published_at(item, reference))
        ]
        if published:
            newest, newest_item = max(published, key=lambda pair: pair[0].timestamp())
            representative = newest_item
            newest_iso = newest.isoformat()
        else:
            newest_iso = None
        providers = [p for p in NEWS_PROVIDERS if p in story["providers"]]
        consensus_providers = [p for p in providers if len(providers) >= 2]
        merged.append({
            "title": representative.get("title"),
            "source": representative.get("source"),
            "published": representative.get("published"),
            "published_at": newest_iso,
            "url": representative.get("url"),
            "summary": next(
                (entry.get("summary") for entry in entries if entry.get("summary")), None
            ),
            "reaction_day_percent": next(
                (entry.get("reaction_day_percent") for entry in entries
                 if entry.get("reaction_day_percent") is not None), None
            ),
            "reaction_next_day_percent": next(
                (entry.get("reaction_next_day_percent") for entry in entries
                 if entry.get("reaction_next_day_percent") is not None), None
            ),
            "tickers": next(
                (entry.get("tickers") for entry in entries if entry.get("tickers")), []
            ),
            "providers": providers,
            "provider_count": len(providers),
            "consensus": len(providers) >= 2,
            "consensus_providers": consensus_providers,
            "consensus_kind": "provider_corroboration" if consensus_providers else "not_corroborated",
            "matching": story["matching"],
            "headlines": [
                {"provider": provider, **entry}
                for provider, entry in zip(story["providers"], entries)
            ],
            "_sort": newest,
            "_sequence": sequence,
        })
    merged.sort(
        key=lambda item: (
            item["_sort"] is None,
            -(item["_sort"].timestamp() if item["_sort"] else 0),
            item["_sequence"],
        )
    )
    items = merged[:limit]
    for item in items:
        item.pop("_sort", None)
        item.pop("_sequence", None)

    answered = [p for p in NEWS_PROVIDERS if provider_counts.get(p, 0) > 0]
    pairwise = []
    for index, left in enumerate(NEWS_PROVIDERS):
        for right in NEWS_PROVIDERS[index + 1:]:
            if left not in answered or right not in answered:
                continue
            shared = sum(
                left in item["providers"] and right in item["providers"]
                for item in merged
            )
            left_total = sum(left in item["providers"] for item in merged)
            pairwise.append({
                "between": [left, right],
                "shared": shared,
                "left_count": left_total,
                "right_count": sum(right in item["providers"] for item in merged),
                "overlap_pct": round(shared / left_total * 100, 1) if left_total else None,
            })
    block = {
        "items": items,
        "count": len(items),
        "limit": limit,
        "has_full_limit": len(items) == limit,
        "unique_stories": len(merged),
        "consensus_count": sum(item["consensus"] for item in items),
        "single_source_count": sum(not item["consensus"] for item in items),
        "duplicates_collapsed": duplicate_items,
        "pairwise": pairwise,
        "provider_counts": provider_counts,
        "by_provider": by_provider,
        "providers_answered": answered,
        "data_provider": provider_from_answered(answered, list(asked)).value,
        "consensus_meaning": "provider_corroboration_not_independent_editorial_verification",
        "errors": list(errors),
    }
    block["shortfall_reason"] = _shortfall(block)
    return block


async def fetch_news(
    symbol: str,
    *,
    limit: int = NEWS_LIMIT,
    include_reactions: bool = True,
) -> dict[str, Any]:
    """Ask every news-capable provider and return their efforts and merged block.

    StockAnalysis and Bloomberg are deliberately omitted because this server has
    no symbol-news adapter for either. Missing instruments, absent tokens,
    upstream failures and valid empty results remain distinguishable in the
    reconciler attempts; they never become invented headlines.
    """
    limit = news_limit(limit)
    ticker = symbols.strip_exchange(symbol).upper()
    tv_res, fv_res, yh_res = await asyncio.gather(
        symbols.resolve(symbol, TRADINGVIEW),
        symbols.resolve(symbol, FINVIZ),
        symbols.resolve(symbol, YAHOO),
    )

    async def tv_call() -> dict[str, Any]:
        """Return Marketaux headlines resolved to TradingView's ticker spelling."""
        if not tv_res.found:
            raise NotApplicable(TRADINGVIEW, tv_res.note or "no TradingView symbol")
        return await tv_access.news(tv_res.symbol, limit=limit)

    async def fv_call() -> dict[str, Any]:
        """Return Finviz headlines, with optional article price reactions."""
        if not fv_res.found:
            raise NotApplicable(FINVIZ, fv_res.note or "Finviz has no page")
        return await fv_access.news(
            fv_res.symbol, limit=limit, include_reactions=include_reactions
        )

    async def yh_call() -> dict[str, Any]:
        """Return Yahoo Finance headlines from its resolved symbol search."""
        if not yh_res.found:
            raise NotApplicable(YAHOO, yh_res.note or "no Yahoo symbol")
        return await yh_access.news(yh_res.symbol, limit=limit)

    pair: Pair = await ask(tv_call, fv_call, yh_call)
    normalizers = {
        TRADINGVIEW: tv_news_fields,
        FINVIZ: fv_news_fields,
        YAHOO: yahoo_news_fields,
    }
    feeds: dict[str, list[dict[str, Any]]] = {}
    for provider in NEWS_PROVIDERS:
        attempt = pair.attempts[provider]
        feeds[provider] = normalizers[provider](attempt.payload or {}).get("items") or []
    errors = [error for error in pair.errors if error.get("provider") in NEWS_PROVIDERS]
    block = merge_news(feeds, limit=limit, asked=pair.asked, errors=errors)
    block["endpoints"] = {
        FINVIZ: f"https://finviz.com/api/news/quote/{fv_res.symbol or ticker}",
        YAHOO: "query1.finance.yahoo.com/v1/finance/search",
        TRADINGVIEW: "Marketaux news feed (via TradingView provider)",
    }
    block["provider_calls"] = {
        "asked": list(pair.asked),
        "answered": list(pair.answered),
        "did_not_answer": [
            provider for provider in pair.asked if provider not in pair.answered
        ],
        "coverage": pair.provider.value,
    }
    return {
        "ticker": ticker,
        "pair": pair,
        "block": block,
        "resolutions": {
            provider: resolution.to_dict()
            for provider, resolution in (
                (TRADINGVIEW, tv_res), (FINVIZ, fv_res), (YAHOO, yh_res)
            )
        },
    }


def attach_news(
    response: dict[str, Any], news: dict[str, Any], provider: str | None = None
) -> None:
    """Attach a news block while preserving the primary leg's provenance.

    Adds ``news`` at the top level and, when the primary payload exists, at
    ``data.news`` and ``fields.news``. Nested labels describe only news, never
    reattribute the sentiment score or Finviz editorial explainer. If that
    primary leg failed, the envelope remains ``NONE`` with ``data: null`` and
    the independently retrieved news stays in top-level ``news`` beside the
    preserved primary error. News-call errors are also added to envelope errors.
    """
    block = news["block"]
    response["news"] = block
    if isinstance(response.get("data"), dict):
        response["data"]["news"] = block
        if isinstance(response.get("fields"), dict):
            response["fields"]["news"] = {
                "source": None,
                "coverage": block["data_provider"],
                "supplied": list(block["providers_answered"]),
                "compared": [],
                "agreement": None,
                "note": (
                    "This merged object has no single provider. `coverage` describes "
                    "its separate news calls. Per-story matching is provider "
                    "corroboration, not independent editorial verification."
                ),
            }
    for label, endpoint in block.get("endpoints", {}).items():
        if provider != label:
            response.setdefault("sources", {}).setdefault(label, endpoint)
    primary = response.get("errors") or []
    response["errors"] = primary + [
        error for error in block.get("errors", []) if error not in primary
    ]
    if block.get("shortfall_reason"):
        response.setdefault("warnings", []).append(
            "News returned fewer stories than requested: " + block["shortfall_reason"] + "."
        )
    response["notice"] = (
        (response.get("notice") or "")
        + " News coverage is separate in `news` and, when available, `data.news`; "
        "per-story consensus means provider corroboration, not editorial truth."
    ).strip()


__all__ = [
    "NEWS_LIMIT", "MAX_NEWS_LIMIT", "NEWS_PROVIDERS", "attach_news", "fetch_news",
    "merge_news", "news_limit",
]
