"""Dynamic symbol resolution across providers.

The upstreams name the same instrument differently, and the differences
are not mechanical:

============  ==================  ===========  ===============
Instrument    TradingView         Finviz       Yahoo Finance
============  ==================  ===========  ===============
Apple         ``NASDAQ:AAPL``     ``AAPL``     ``AAPL``
Gold spot     ``OANDA:XAUUSD``    *(none)*     ``XAUUSD=X`` or ``GC=F``
S&P 500       ``SP:SPX``          ``SPX``      ``^GSPC``
EUR/USD       ``FX:EURUSD``       *(none)*     ``EURUSD=X``
Bitcoin       ``BITSTAMP:BTCUSD`` *(none)*     ``BTC-USD``
Brent         ``NYMEX:BZ1!``      *(none)*     ``BZ=F``
============  ==================  ===========  ===============

StockAnalysis addresses only US equities and ETFs (``aapl``, ``brk.b``) and has
no search endpoint, so it is a mechanical rule plus a stated "not carried" for
everything else.

A hardcoded table cannot keep up: it needs a row per instrument, per provider,
and it silently produces a wrong-but-plausible ticker when a row is missing, which is exactly how ``XAUUSD`` became ``NASDAQ:XAUUSD`` and every provider
returned "no data".

This module resolves dynamically instead:

1. **Explicit wins.** ``OANDA:XAUUSD`` is taken at face value for TradingView;
   the bare part is then mapped for the others.
2. **Native search.** Each provider is asked with its own symbol-search
   endpoint. TradingView has a documented symbol search, Yahoo has
   ``/v1/finance/search``, Finviz only accepts slugs so it gets a read-probe.
   StockAnalysis has no quote search at all, so it gets a mechanical rule plus
   an explicit "not carried" for every instrument class it does not serve.
3. **Ranked match.** Candidates are scored on exact-symbol match, asset class
   and venue preference. A result must clear a confidence floor, otherwise it
   is not used: guessing is worse than reporting "not found".
4. **Cached.** Resolution is memoised per (provider, query) for the life of the
   process plus a TTL, because a symbol's identity does not change minute to
   minute and the search endpoints are rate-limited.

Nothing here raises on a miss. :func:`resolve` returns a :class:`Resolution`
whose ``symbol`` is ``None`` when the provider genuinely has nothing, so the
tool layer can label that provider ``NO_DATA`` instead of inventing a ticker.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from .http_pool import shared_client
from .providers_state import NoDataError
from .ratelimit import RateLimited, call

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)

#: Venues that carry the canonical, most-liquid listing for an instrument, in
#: preference order. When several exchanges quote the same ticker, the first
#: match here wins, so ``XAUUSD`` resolves to ``OANDA:XAUUSD`` rather than a
#: broker's duplicate.
VENUE_PREFERENCE: tuple[str, ...] = (
    "NASDAQ", "NYSE", "AMEX", "ARCA", "BATS", "OTC",
    "SP", "DJ", "NASDAQ", "TVC", "NYMEX", "COMEX", "CME", "CBOT", "ICEUS",
    "FX", "OANDA", "FOREXCOM", "FXCM", "BITSTAMP", "COINBASE", "BINANCE",
    "KUCOIN", "BYBIT", "BIST", "EGX", "LSE", "XETR", "TSE",
)

#: Asset classes we consider "the same kind" when ranking search hits.
_CLASS_HINTS: dict[str, tuple[str, ...]] = {
    "stock": ("stock", "dr", "fund", "etf"),
    "fund": ("fund", "etf", "stock"),
    "etf": ("etf", "fund", "stock"),
    "index": ("index",),
    "commodity": ("commodity", "cfd", "futures"),
    "futures": ("futures", "commodity"),
    "forex": ("forex", "cfd", "commodity"),
    "crypto": ("crypto", "coin"),
}

#: Sentinels used in the response so a caller can tell "we did not find it"
#: apart from "we did not look".
_CACHE: dict[tuple[str, str], tuple[float, "Resolution"]] = {}
_CACHE_TTL = 3600.0


@dataclass
class Candidate:
    """One search hit, provider-specific but shaped the same."""

    symbol: str          # provider-native ticker
    venue: str = ""      # exchange / market the provider put it on
    description: str = ""
    asset_class: str = ""
    score: float = 0.0


@dataclass
class Resolution:
    """The outcome of resolving one user symbol for one provider."""

    query: str
    provider: str
    symbol: str | None = None
    venue: str = ""
    description: str = ""
    asset_class: str = ""
    # explicit | search | alias | normalise | mechanical | none
    method: str = "none"
    confidence: float = 0.0
    candidates: list[Candidate] = field(default_factory=list)
    note: str = ""

    @property
    def found(self) -> bool:
        return self.symbol is not None

    def require(self) -> str:
        """Return the symbol or raise ``NoDataError`` (the tool-layer contract)."""
        if self.symbol is None:
            raise NoDataError(self.provider, self.note or f"no match for {self.query!r}")
        return self.symbol

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "provider": self.provider,
            "symbol": self.symbol,
            "venue": self.venue,
            "description": self.description,
            "asset_class": self.asset_class,
            "method": self.method,
            "confidence": round(self.confidence, 2),
            "note": self.note,
        }


# ── Scoring ──────────────────────────────────────────────────────────────────


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _venue_rank(venue: str) -> int:
    upper = (venue or "").upper()
    try:
        return VENUE_PREFERENCE.index(upper)
    except ValueError:
        return len(VENUE_PREFERENCE)


def score_candidate(query: str, candidate: Candidate, wanted_class: str = "") -> float:
    """Rank a search hit against what the caller asked for.

    Exact ticker match dominates; asset class and venue preference break ties.
    A fuzzy-match hit can score at most 0.6, which is below the acceptance
    floor, so "something vaguely similar" is never silently used.
    """
    wanted = _normalise(query.split(":")[-1])
    got = _normalise(candidate.symbol.split(":")[-1])
    score = 0.0
    if got == wanted:
        score += 0.6
    elif got.startswith(wanted) or wanted.startswith(got):
        score += 0.25
    else:
        score += 0.0

    if wanted_class:
        allowed = _CLASS_HINTS.get(wanted_class, (wanted_class,))
        if candidate.asset_class in allowed:
            score += 0.25

    score += max(0.0, 0.15 - _venue_rank(candidate.venue) * 0.005)
    return min(score, 1.0)


CONFIDENCE_FLOOR = 0.55


def _pick(query: str, candidates: Iterable[Candidate], wanted_class: str = "") -> tuple[Candidate | None, float]:
    scored = []
    for candidate in candidates:
        candidate.score = score_candidate(query, candidate, wanted_class)
        scored.append(candidate)
    if not scored:
        return None, 0.0
    scored.sort(key=lambda c: (c.score, -_venue_rank(c.venue)), reverse=True)
    best = scored[0]
    return (best, best.score) if best.score >= CONFIDENCE_FLOOR else (None, best.score)


# ── TradingView ──────────────────────────────────────────────────────────────


async def _tradingview_search(query: str) -> list[Candidate]:
    url = "https://symbol-search.tradingview.com/symbol_search/v3/"
    params = {
        "text": query,
        "hl": "1",
        "exchange": "",
        "lang": "en",
        "search_type": "",
        "domain": "production",
        "sort_by_country": "US",
    }

    async def _once() -> list[Candidate]:
        # ``call`` below waits its turn; a second wait here would spend an extra
        # pacing interval on every search.
        client = shared_client("tradingview")
        response = await client.get(
            url,
            params=params,
            headers={"User-Agent": UA, "Origin": "https://www.tradingview.com"},
            timeout=15.0,
        )
        if response.status_code == 429:
            raise RateLimited("TRADINGVIEW", "symbol search HTTP 429")
        response.raise_for_status()
        payload = response.json()
        out: list[Candidate] = []
        for hit in payload.get("symbols") or []:
            ticker = re.sub(r"<[^>]+>", "", hit.get("symbol") or "")
            venue = hit.get("exchange") or ""
            if not ticker:
                continue
            out.append(
                Candidate(
                    symbol=ticker,
                    venue=venue,
                    description=re.sub(r"<[^>]+>", "", hit.get("description") or ""),
                    asset_class=(hit.get("type") or "").lower(),
                )
            )
        return out

    return await call("TRADINGVIEW", _once)


async def _tradingview_quotes(tickers: list[str]) -> set[str]:
    """Which of these tickers the scanner will actually return a row for.

    TradingView's symbol *search* and its *scanner* disagree: search offers
    ``OANDA:BTCUSD`` and ``OANDA:ETHUSD``, but the scanner has no row for either
    (verified live). Resolution that stops at search hands the quote path a
    ticker that cannot be quoted, and the tool reports "no data" for an
    instrument TradingView does carry, under a different venue, ``BITSTAMP``.
    """
    from .providers.tradingview import native

    try:
        rows = await native.scan(tickers, columns=("name",))
    except Exception:  # noqa: BLE001 - verification is best-effort
        return set(tickers)
    return {str(row.get("ticker") or "").upper() for row in rows}


async def resolve_tradingview(query: str, *, asset_class: str = "") -> Resolution:
    """Resolve to an ``EXCHANGE:SYMBOL`` pair TradingView actually quotes."""
    query = query.strip()
    registered = registry_resolution(query, "TRADINGVIEW")
    if registered is not None:
        # The registry's spellings were verified against the scanner, and a
        # registered query often names an instrument whose bare root also names
        # a US equity (``WTI`` -> W&T Offshore, ``GOLD`` -> Gold.com). Search
        # would return the equity as a "match", the table prevents exactly that.
        return registered
    explicit = ":" in query
    bare = query.split(":", 1)[1].upper() if explicit else query.upper()

    if explicit:
        # Trust the caller's venue; the quote path surfaces a real miss as
        # NO_DATA. Verifying here would cost a request on every explicit call.
        resolution = Resolution(
            query=query,
            provider="TRADINGVIEW",
            symbol=query.upper(),
            venue=query.split(":", 1)[0].upper(),
            method="explicit",
            confidence=1.0,
        )
        return resolution

    try:
        candidates = await _tradingview_search(bare)
    except RateLimited as exc:
        return Resolution(
            query=query,
            provider="TRADINGVIEW",
            note=f"{exc.provider} is rate limited; symbol not resolved",
        )
    except Exception as exc:  # noqa: BLE001 - search failure is not fatal
        return Resolution(
            query=query,
            provider="TRADINGVIEW",
            note=f"symbol search failed: {type(exc).__name__}",
            candidates=[],
        )

    # Rank every plausible candidate, then confirm with the scanner. Search
    # rankings alone are not evidence that a ticker is quotable.
    for candidate in candidates:
        candidate.score = score_candidate(bare, candidate, asset_class)
    scored = sorted(
        candidates,
        key=lambda c: (c.score, -_venue_rank(c.venue)),
        reverse=True,
    )
    shortlist = [c for c in scored if c.score >= CONFIDENCE_FLOOR][:5]
    if not shortlist:
        best = scored[0] if scored else None
        return Resolution(
            query=query,
            provider="TRADINGVIEW",
            note=f"no TradingView symbol matched {query!r}",
            confidence=best.score if best else 0.0,
            candidates=scored[:5],
        )

    tickers = [
        f"{c.venue}:{c.symbol}".upper() if c.venue else c.symbol.upper()
        for c in shortlist
    ]
    quotable = await _tradingview_quotes(tickers)
    chosen = next(
        (c for c, t in zip(shortlist, tickers) if t in quotable),
        None,
    )
    if chosen is None:
        return Resolution(
            query=query,
            provider="TRADINGVIEW",
            note=(
                "search matched but the scanner quotes none of: "
                + ", ".join(tickers)
            ),
            confidence=shortlist[0].score,
            candidates=shortlist,
        )

    ticker = f"{chosen.venue}:{chosen.symbol}".upper() if chosen.venue else chosen.symbol.upper()
    return Resolution(
        query=query,
        provider="TRADINGVIEW",
        symbol=ticker,
        venue=chosen.venue,
        description=chosen.description,
        asset_class=chosen.asset_class,
        method="search",
        confidence=chosen.score,
        candidates=shortlist,
    )


# ── Yahoo Finance ────────────────────────────────────────────────────────────


async def _yahoo_search(query: str) -> list[Candidate]:
    url = "https://query2.finance.yahoo.com/v1/finance/search"

    async def _once() -> list[Candidate]:
        # ``call`` below waits its turn; a second wait here would spend an extra
        # pacing interval on every search.
        client = shared_client("yahoo")
        response = await client.get(
            url,
            params={"q": query, "quotesCount": 10, "newsCount": 0},
            headers={"User-Agent": UA, "Accept": "application/json"},
            timeout=15.0,
        )
        if response.status_code == 429:
            raise RateLimited("YAHOO", "search HTTP 429")
        response.raise_for_status()
        payload = response.json()
        out: list[Candidate] = []
        for hit in payload.get("quotes") or []:
            symbol = hit.get("symbol")
            if not symbol:
                continue
            out.append(
                Candidate(
                    symbol=symbol,
                    venue=hit.get("exchange") or "",
                    description=hit.get("shortname") or hit.get("longname") or "",
                    asset_class=(hit.get("quoteType") or "").lower(),
                )
            )
        return out

    return await call("YAHOO", _once)


#: ISO-4217 codes Yahoo quotes as FX pairs. Restricting the suffix rule to real
#: currencies stops an arbitrary six-letter equity ticker from being rewritten
#: into a pair that cannot exist.
_CURRENCY_CODES: frozenset[str] = frozenset(
    """
    USD EUR GBP JPY CHF CAD AUD NZD SEK NOK DKK PLN HUF CZK TRY RUB ZAR
    MXN BRL ARS CLP COP PEN INR IDR THB SGD HKD KRW CNY TWD ILS AED SAR
    """.split()
)

#: ``XXXYYY`` where both halves are currencies -> ``XXXYYY=X``.
_FX_PAIR = re.compile(r"^([A-Z]{3})([A-Z]{3})$")

#: Crypto tickers Yahoo quotes with a dash instead of a suffix.
_CRYPTO_PAIR = re.compile(
    r"^(BTC|ETH|SOL|XRP|DOGE|ADA|BNB|LTC|AVAX|DOT|LINK|BCH|XLM|ATOM|ETC)(USD|EUR|GBP)$"
)

#: Instruments Yahoo simply does not carry, with the reason. Spot metals are the
#: important case: ``XAUUSD=X`` was a *fabricated* ticker, it returns HTTP 404.
#: Yahoo's nearest print is COMEX futures (``GC=F``), which is a different
#: instrument trading at a different price, so substituting it would be a proxy
#: claim rather than a quote. Reporting "not carried" is the honest answer.
#: The registered rows (``XAUUSD``, ``XAGUSD``) answer through
#: :data:`INSTRUMENTS` first; this table now only serves the unregistered
#: platinum and palladium pairs.
_YAHOO_UNAVAILABLE: dict[str, str] = {
    "XPTUSD": "Yahoo Finance has no spot platinum pair.",
    "XPDUSD": "Yahoo Finance has no spot palladium pair.",
}


def _yahoo_suffix(query: str) -> str | None:
    """Apply Yahoo's documented mechanical suffix conventions.

    Only rules that have been confirmed against the chart endpoint are here.
    A rule that *looks* plausible but fabricates a ticker is worse than no rule:
    the caller gets a 404 six layers later with no idea why.
    """
    pair = _FX_PAIR.match(query)
    if pair and pair.group(1) in _CURRENCY_CODES and pair.group(2) in _CURRENCY_CODES:
        return f"{query}=X"
    if _CRYPTO_PAIR.match(query):
        base, quote = query[:-3], query[-3:]
        return f"{base}-{quote}"
    return None


_YAHOO_INDEX_ALIASES: dict[str, str] = {
    "SPX": "^GSPC", "GSPC": "^GSPC", "COMP": "^IXIC", "IXIC": "^IXIC",
    "DJI": "^DJI", "DJX": "^DJI", "RUT": "^RUT", "VIX": "^VIX", "NDX": "^NDX",
    "RUT2000": "^RUT",
}
#: Kept for spellings the registry does not cover: ``NDX`` (``^NDX``) has no
#: registry row, and it must still resolve rather than fall to search.


async def resolve_yahoo(query: str, *, asset_class: str = "") -> Resolution:
    """Resolve to a Yahoo chart-API symbol."""
    query = query.strip().upper()
    registered = registry_resolution(query, "YAHOO")
    if registered is not None:
        # Carries both directions: the spelling (``GC1!`` -> ``GC=F``) and the
        # documented boundary (``XAUUSD`` -> none, no spot pair).
        return registered
    bare = query.split(":", 1)[-1]
    if query.startswith("^"):
        bare = query

    if bare in _YAHOO_INDEX_ALIASES:
        return Resolution(
            query=query,
            provider="YAHOO",
            symbol=_YAHOO_INDEX_ALIASES[bare],
            method="alias",
            asset_class="index",
            confidence=0.95,
        )

    if bare in _YAHOO_UNAVAILABLE:
        return Resolution(
            query=query,
            provider="YAHOO",
            note=_YAHOO_UNAVAILABLE[bare],
            asset_class=asset_class,
        )

    derived = _yahoo_suffix(bare)
    if derived:
        return Resolution(
            query=query,
            provider="YAHOO",
            symbol=derived,
            method="alias",
            confidence=0.9,
            note="derived from Yahoo's documented suffix convention",
        )

    explicit = ":" in query
    search_for = bare if explicit else query

    try:
        candidates = await _yahoo_search(search_for)
    except RateLimited as exc:
        return Resolution(
            query=query,
            provider="YAHOO",
            note=f"{exc.provider} is rate limited; symbol not resolved",
        )
    except Exception as exc:  # noqa: BLE001
        return Resolution(
            query=query,
            provider="YAHOO",
            note=f"symbol search failed: {type(exc).__name__}",
        )

    if explicit:
        wanted_venue = query.split(":", 1)[0]
        for candidate in candidates:
            if candidate.venue.upper() == wanted_venue:
                candidate.score = 1.0
                return Resolution(
                    query=query,
                    provider="YAHOO",
                    symbol=candidate.symbol,
                    venue=candidate.venue,
                    description=candidate.description,
                    asset_class=candidate.asset_class,
                    method="search",
                    confidence=1.0,
                    candidates=candidates[:5],
                )

    best, confidence = _pick(bare, candidates, asset_class)
    if best is None:
        return Resolution(
            query=query,
            provider="YAHOO",
            note=f"no Yahoo Finance symbol matched {query!r}",
            confidence=confidence,
            candidates=sorted(candidates, key=lambda c: c.score, reverse=True)[:5],
        )
    return Resolution(
        query=query,
        provider="YAHOO",
        symbol=best.symbol,
        venue=best.venue,
        description=best.description,
        asset_class=best.asset_class,
        method="search",
        confidence=confidence,
        candidates=sorted(candidates, key=lambda c: c.score, reverse=True)[:5],
    )


# ── Finviz ───────────────────────────────────────────────────────────────────


def resolve_finviz(query: str, *, asset_class: str = "") -> Resolution:
    """Finviz only carries US-listed equities and ETFs, and has no search API.

    So resolution is a normalisation plus an honesty check: a US ticker passes
    through, a share-class dot is converted (``BRK.B`` is already Finviz's own
    spelling), and anything that is not a US slug is reported as not served
    rather than being sent to a page that will 404.
    """
    registered = registry_resolution(query, "FINVIZ")
    if registered is not None:
        # Registered instruments carry their Finviz boundary in the registry
        # (``finviz`` cell or ``finviz_note``), stated once, with the index
        # feed exception below honoured the same way as before.
        return registered
    bare = query.strip().upper().split(":", 1)[-1]
    if asset_class and asset_class.lower() not in {"stock", "etf", "fund", "equity"}:
        return Resolution(
            query=query,
            provider="FINVIZ",
            note=f"Finviz does not carry {asset_class} instruments",
            asset_class=asset_class,
        )

    # Indices are not quote pages on Finviz. ``/stock?t=SPX`` and
    # ``/stock?t=DJI`` both return HTTP 404, and ``COMP`` is not the Nasdaq
    # Composite there, it is Compass Inc, a real equity. Claiming those tickers
    # used to make ``market_indices`` report a Finviz level that never existed.
    # Finviz's index data lives only in the ``/api/indices_data`` island, which
    # ``fv_access.indices`` reads directly.
    canonical = canonical_index(bare)
    if canonical or bare.startswith("^"):
        return Resolution(
            query=query,
            provider="FINVIZ",
            note=(
                "Finviz quotes indices only through its indices feed, not a "
                "per-ticker page"
            ),
            asset_class="index",
        )

    # Foreign listings and provider-specific venues are out of scope for Finviz.
    if "." in bare and not re.fullmatch(r"[A-Z]{1,5}\.[A-Z]{1,2}", bare):
        return Resolution(
            query=query,
            provider="FINVIZ",
            note="Finviz has no page for foreign-listed tickers",
        )
    if re.search(r"(-USD|=X|\^)", bare) or re.fullmatch(r"[A-Z]{6}", bare):
        return Resolution(
            query=query,
            provider="FINVIZ",
            note="Finviz carries US equities/ETFs only",
        )
    if not re.fullmatch(r"[A-Z][A-Z0-9\-]{0,6}", bare):
        return Resolution(
            query=query,
            provider="FINVIZ",
            note=f"{bare!r} is not a US ticker",
        )
    # BRK-B is Yahoo's spelling of Finviz's BRK.B.
    if "-" in bare and len(bare) <= 7:
        head, _, tail = bare.partition("-")
        if head.isalpha() and tail.isalpha() and len(tail) <= 2:
            bare = f"{head}.{tail}"
    return Resolution(
        query=query,
        provider="FINVIZ",
        symbol=bare,
        method="normalise",
        confidence=1.0,
        asset_class=asset_class or "stock",
    )


# ── StockAnalysis ────────────────────────────────────────────────────────────


#: Instrument classes the StockAnalysis quote API has no route for. Its HTML
#: pages do cover some of these, but the quote API answers 404/400, so the leg
#: reports "not carried" instead of spending a request to learn it.
_SA_NOT_CARRIED_CLASSES = {
    "index": "StockAnalysis quotes indices on HTML pages only; its quote API is "
             "US equities and ETFs",
    "forex": "StockAnalysis has no FX quote endpoint",
    "currency": "StockAnalysis has no FX quote endpoint",
    "crypto": "StockAnalysis has no crypto quote endpoint",
    "commodity": "StockAnalysis has no commodity quote endpoint",
    "futures": "StockAnalysis has no futures quote endpoint",
}

#: A foreign listing carries a venue suffix (``VOD.L``, ``SHOP.TO``). The quote
#: API is US-only, so these are rejected here rather than 404ing later.
_SA_FOREIGN_SUFFIX = re.compile(
    r"^[A-Z0-9]{1,6}\."
    r"(L|TO|V|AX|HK|T|DE|PA|AS|MI|MC|ST|SI|CO|OL|HE|BR|LS|IR|NZ|SA|MX|JO|KL|BK|"
    r"TA|TW|SS|SZ|KS|KQ|IS|VI|WA|PR|AT|BD|CL|CR|DU|F|HA|JK|KA|NS|BO|NZ|SG|SW)$"
)

#: Spot metals are quoted as ``XAUUSD`` and end in ``USD`` exactly like a crypto
#: pair does. They need their own answer, or a caller asking for spot gold is
#: told the leg has no crypto, which is the wrong reason.
_SA_METALS = frozenset({"XAU", "XAG", "XPT", "XPD"})

#: Crypto bases that reach this module as ``BTCUSD`` / ``BTCUSDT``. Checked
#: explicitly rather than by shape, so a metal is not misread as a coin.
_SA_CRYPTO_BASES = frozenset(
    {"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LTC", "LINK",
     "BNB", "MATIC", "TRX", "SHIB", "UNI", "ATOM", "XLM", "ETC", "FIL", "APT"}
)


def _sa_pair_reason(bare: str) -> str | None:
    """The not-carried note for a base/quote pair, or ``None`` if it is no pair.

    ``XAUUSD``, ``BTC-USD`` and ``EURUSD`` all look similar and all have
    different reasons, so the base is classified rather than guessed from the
    suffix alone.
    """
    candidate = bare.replace("-", "").replace("/", "")
    if candidate.endswith("USDT"):
        candidate = candidate[:-4]
    elif candidate.endswith("USD"):
        candidate = candidate[:-3]
    else:
        return None
    if not candidate or not candidate.isalpha():
        return None
    if candidate in _SA_METALS:
        return _SA_NOT_CARRIED_CLASSES["commodity"]
    if candidate in _SA_CRYPTO_BASES:
        return _SA_NOT_CARRIED_CLASSES["crypto"]
    if "=" in bare or "-USD" in bare:
        return "StockAnalysis's quote API carries US equities and ETFs only"
    return _SA_NOT_CARRIED_CLASSES["forex"]


def resolve_sa(query: str, *, asset_class: str = "") -> Resolution:
    """StockAnalysis's ticker for *query*, resolved without a request.

    The quote API has no search endpoint and accepts exactly one spelling: the
    US ticker, lowercased, with a share class as a dot. So resolution is a
    mechanical rule plus an honesty check: anything that is not a US equity or
    ETF is reported as not carried rather than being sent to a route that will
    answer 404.
    """
    registered = registry_resolution(query, "SA")
    if registered is not None:
        return registered
    raw = query.strip()
    bare = raw.upper().split(":", 1)[-1].replace(" ", "")

    if asset_class and asset_class.lower() in _SA_NOT_CARRIED_CLASSES:
        return Resolution(
            query=query,
            provider="SA",
            note=_SA_NOT_CARRIED_CLASSES[asset_class.lower()],
            asset_class=asset_class,
        )

    # Index spellings: SPX / ^GSPC / SP:SPX. The quote API has no route for any
    # of them (all three answer 404 live), and ``COMP`` would be Compass Inc.
    if bare.startswith("^") or canonical_index(bare):
        return Resolution(
            query=query,
            provider="SA",
            note=_SA_NOT_CARRIED_CLASSES["index"],
            asset_class="index",
        )

    # ``XAUUSD`` is spot gold, not a coin: the reason has to name the right
    # boundary, so the base is classified instead of trusting the ``USD`` tail.
    pair_reason = _sa_pair_reason(bare)
    if pair_reason is not None:
        return Resolution(query=query, provider="SA", note=pair_reason)
    # Six all-alpha letters is an FX pair in every other provider's vocabulary
    # (``USDJPY``, ``GBPEUR``); no US ticker is spelled that way, and the API
    # would answer 404 for each of them.
    if re.fullmatch(r"[A-Z]{6}", bare):
        return Resolution(
            query=query,
            provider="SA",
            note=_SA_NOT_CARRIED_CLASSES["forex"],
        )
    if _SA_FOREIGN_SUFFIX.match(bare):
        return Resolution(
            query=query,
            provider="SA",
            note="StockAnalysis's quote API carries US listings only",
        )
    if not bare or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", bare):
        return Resolution(
            query=query,
            provider="SA",
            note=f"{bare!r} is not a US ticker",
        )

    # ``BRK-B`` is Yahoo's spelling of the site's ``BRK.B``.
    if "-" in bare:
        head, _, tail = bare.partition("-")
        if head.isalpha() and tail.isalpha() and len(tail) <= 2:
            bare = f"{head}.{tail}"
    return Resolution(
        query=query,
        provider="SA",
        symbol=bare.lower(),
        method="mechanical",
        confidence=0.9,
        asset_class=asset_class or "stock",
        note="StockAnalysis has no quote search API; the US ticker is lowercased",
    )


# ── Facade ───────────────────────────────────────────────────────────────────


async def resolve(
    query: str,
    provider: str,
    *,
    asset_class: str = "",
    refresh: bool = False,
) -> Resolution:
    """Resolve one user-supplied symbol for one provider (cached)."""
    provider = provider.upper()
    cache_key = (provider, f"{query.strip().upper()}|{asset_class}")
    if not refresh:
        hit = _CACHE.get(cache_key)
        if hit and time.monotonic() - hit[0] < _CACHE_TTL:
            return hit[1]

    if provider == "TRADINGVIEW":
        result = await resolve_tradingview(query, asset_class=asset_class)
    elif provider == "YAHOO":
        result = await resolve_yahoo(query, asset_class=asset_class)
    elif provider == "FINVIZ":
        result = resolve_finviz(query, asset_class=asset_class)
    elif provider == "SA":
        result = resolve_sa(query, asset_class=asset_class)
    else:
        raise ValueError(f"unknown provider {provider!r}")

    _CACHE[cache_key] = (time.monotonic(), result)
    return result


async def resolve_all(query: str, *, asset_class: str = "") -> dict[str, Resolution]:
    """Resolve the same query for every provider concurrently."""
    results = await asyncio.gather(
        resolve(query, "TRADINGVIEW", asset_class=asset_class),
        resolve(query, "FINVIZ", asset_class=asset_class),
        resolve(query, "YAHOO", asset_class=asset_class),
        resolve(query, "SA", asset_class=asset_class),
    )
    return {r.provider: r for r in results}


def clear_cache() -> None:
    _CACHE.clear()


#: One instrument per row, keyed by its canonical name, one column per
#: provider. This is the *addressing* layer only: it says which ticker to ask
#: each provider for, never which providers to ask. Every provider with a
#: non-``None`` cell is still asked in parallel by the tool layer, exactly as
#: before; a ``None`` cell records a boundary the provider declares ("no spot
#: pair", "US equities and ETFs only") so the leg reports ``NOT_ATTEMPTED``
#: with the reason instead of being sent a ticker that will 404.
#:
#: Two rules keep the table honest:
#:
#: * a row is one instrument identity. ``RUT`` (the index) and ``IWM`` (its
#:   tracking ETF), ``XAUUSD`` (spot gold) and ``GC1!`` (its front-month
#:   future) are different instruments at different price levels and live in
#:   different rows; they must never be compared.
#: * a ``None`` cell carries its reason. The table is the single home for the
#:   "not carried" knowledge that used to live in ``_YAHOO_UNAVAILABLE`` and
#:   per-provider if-chains.
#:
#: Every spelling below was verified against the live upstreams (the scanner
#: and the chart API), not copied from another provider's vocabulary: TradingView
#: search offers ``TVC:USOIL`` but its scanner has no row for it, so the quoted
#: spot series is ``FX:USOIL``. Bare roots that also name US equities
#: (``NYSE:WTI`` is W&T Offshore, ``NYSE:GOLD`` is Gold.com, ``NYSE:CL`` is
#: Colgate-Palmolive) must resolve through this table, not through search,
#: or the dynamic path returns the equity as a "quote" for the commodity.
INSTRUMENTS: dict[str, dict[str, Any]] = {
    # ── Equity indices ──────────────────────────────────────────────────
    "SPX": {
        "name": "S&P 500", "asset_class": "index",
        "tradingview": "SP:SPX", "finviz": None,
        "finviz_note": "Finviz quotes indices only through its indices feed",
        "yahoo": "^GSPC",
        "sa": None, "bloomberg": "SPX:IND",
    },
    "COMP": {
        "name": "NASDAQ Composite", "asset_class": "index",
        "tradingview": "NASDAQ:IXIC", "finviz": None,
        "finviz_note": "Finviz quotes indices only through its indices feed",
        "yahoo": "^IXIC",
        "sa": None, "bloomberg": "CCMP:IND",
    },
    "DJI": {
        "name": "Dow Jones Industrial Average", "asset_class": "index",
        "tradingview": "DJ:DJI", "finviz": None,
        "finviz_note": "Finviz quotes indices only through its indices feed",
        "yahoo": "^DJI",
        "sa": None, "bloomberg": "INDU:IND",
    },
    "RUT": {
        "name": "Russell 2000", "asset_class": "index",
        "tradingview": "TVC:RUT", "finviz": None,
        "finviz_note": "Finviz quotes indices only through its indices feed",
        "yahoo": "^RUT", "sa": None, "bloomberg": "RTY:IND",
    },
    "IWM": {
        "name": "iShares Russell 2000 ETF", "asset_class": "etf",
        "tradingview": "AMEX:IWM", "finviz": "IWM", "yahoo": "IWM",
        "sa": "iwm", "bloomberg": "IWM:US",
    },
    "VIX": {
        "name": "CBOE Volatility Index", "asset_class": "index",
        "tradingview": "TVC:VIX", "finviz": None,
        "finviz_note": "Finviz quotes indices only through its indices feed",
        "yahoo": "^VIX", "sa": None, "bloomberg": "VIX:IND",
    },
    "NDX": {
        "name": "NASDAQ-100", "asset_class": "index",
        "tradingview": "NASDAQ:NDX", "finviz": None,
        "finviz_note": "Finviz quotes indices only through its indices feed",
        "yahoo": "^NDX", "sa": None, "bloomberg": "NDX:IND",
    },
    # ── Spot commodities ────────────────────────────────────────────────
    "XAUUSD": {
        "name": "Gold spot", "asset_class": "commodity",
        "tradingview": "OANDA:XAUUSD", "finviz": None,
        "finviz_note": "Finviz carries US equities and ETFs only",
        "yahoo": None,
        "yahoo_note": "Yahoo Finance has no spot gold pair; its nearest series "
                      "is COMEX gold futures (GC=F), a different instrument, "
                      "not substituted.",
        "sa": None, "bloomberg": "XAUUSD:CUR",
    },
    "XAGUSD": {
        "name": "Silver spot", "asset_class": "commodity",
        "tradingview": "TVC:SILVER", "finviz": None,
        "finviz_note": "Finviz carries US equities and ETFs only",
        "yahoo": None,
        "yahoo_note": "Yahoo Finance has no spot silver pair (its series is "
                      "SI=F futures).",
        "sa": None, "bloomberg": "XAGUSD:CUR",
    },
    "USOIL": {
        "name": "WTI crude oil spot", "asset_class": "commodity",
        "tradingview": "FX:USOIL", "finviz": None,
        "finviz_note": "Finviz carries US equities and ETFs only",
        "yahoo": None,
        "yahoo_note": "Yahoo Finance has no WTI spot series (its series is "
                      "CL=F futures).",
        "sa": None,
        # Bloomberg's quote page has no WTI spot series; its generic first
        # future is the id it publishes on its own commodities board. The
        # registry states it rather than sending a leg to an id that 403s.
        "bloomberg": None,
        "bloomberg_note": "Bloomberg's quote page carries no WTI spot series; "
                          "its WTI generic future is CL1:COM, a different "
                          "instrument, not substituted.",
    },
    "UKOIL": {
        "name": "Brent crude oil spot", "asset_class": "commodity",
        "tradingview": "FX:UKOIL", "finviz": None,
        "finviz_note": "Finviz carries US equities and ETFs only",
        "yahoo": None,
        "yahoo_note": "Yahoo Finance has no Brent spot series (its series is "
                      "BZ=F futures).",
        "sa": None,
        "bloomberg": None,
        "bloomberg_note": "Bloomberg's quote page carries no Brent spot "
                          "series; its Brent generic future is BZ1:COM, a "
                          "different instrument, not substituted.",
    },
    # ── Front-month futures (continuous contracts) ──────────────────────
    "GC1!": {
        "name": "COMEX gold front-month future", "asset_class": "futures",
        "tradingview": "COMEX:GC1!", "finviz": None,
        "finviz_note": "Finviz carries US equities and ETFs only",
        "yahoo": "GC=F", "sa": None, "bloomberg": "GC1:COM",
    },
    "SI1!": {
        "name": "COMEX silver front-month future", "asset_class": "futures",
        "tradingview": "COMEX:SI1!", "finviz": None,
        "finviz_note": "Finviz carries US equities and ETFs only",
        "yahoo": "SI=F", "sa": None, "bloomberg": "SI1:COM",
    },
    "CL1!": {
        "name": "NYMEX WTI crude front-month future", "asset_class": "futures",
        "tradingview": "NYMEX:CL1!", "finviz": None,
        "finviz_note": "Finviz carries US equities and ETFs only",
        "yahoo": "CL=F", "sa": None, "bloomberg": "CL1:COM",
    },
    "BZ1!": {
        "name": "NYMEX Brent front-month future", "asset_class": "futures",
        "tradingview": "NYMEX:BZ1!", "finviz": None,
        "finviz_note": "Finviz carries US equities and ETFs only",
        "yahoo": "BZ=F", "sa": None, "bloomberg": "BZ1:COM",
    },    "NG1!": {
        "name": "NYMEX Henry Hub natural gas front-month future",
        "asset_class": "futures",
        "tradingview": "NYMEX:NG1!", "finviz": None,
        "finviz_note": "Finviz carries US equities and ETFs only",
        "yahoo": "NG=F", "sa": None, "bloomberg": "NG1:COM",
    },
    "HG1!": {
        "name": "COMEX copper front-month future", "asset_class": "futures",
        "tradingview": "COMEX:HG1!", "finviz": None,
        "finviz_note": "Finviz carries US equities and ETFs only",
        "yahoo": "HG=F", "sa": None, "bloomberg": "HG1:COM",
    },
}

#: Canonical instruments the index-snapshot tools report, in display order. The
#: registry is broader (it also addresses NDX for single-instrument quotes), but
#: a market snapshot is a fixed, documented list, so it is named once here and
#: the provider-side snapshot tables are derived from it.
INDEX_SNAPSHOT: tuple[str, ...] = ("SPX", "COMP", "DJI", "RUT", "IWM", "VIX")

#: Provider column -> the reason template for a ``None`` cell. Providers that
#: mechanically accept any plausible ticker (Finviz, StockAnalysis) get their
#: boundary stated once here instead of in an if-chain at every call site.
_DEFAULT_NOT_CARRIED = {
    "sa": "StockAnalysis's quote API carries US equities and ETFs only",
    "finviz": "Finviz carries US equities and ETFs only",
    "yahoo": "Yahoo Finance does not carry this instrument",
}

#: The reason for a ``None`` cell, by asset class, for providers whose boundary
#: is stated as a class rather than a missing instrument. Finviz and
#: StockAnalysis quote US equities and ETFs; their "not carried" answer for an
#: index or a commodity must name that class, so ``resolutions`` explains why
#: the leg was not asked.
_CLASS_NOT_CARRIED = {
    "index": {
        "sa": "StockAnalysis quotes indices on HTML pages only; its quote "
              "API is US equities and ETFs",
        "finviz": "Finviz quotes indices only through its indices feed, not "
                  "a per-ticker page",
    },
    "commodity": {
        "sa": "StockAnalysis has no commodity quote endpoint",
        "finviz": "Finviz carries US equities and ETFs only",
    },
    "futures": {
        "sa": "StockAnalysis has no futures quote endpoint",
        "finviz": "Finviz carries US equities and ETFs only",
    },
    "etf": {
        "sa": "StockAnalysis's quote API carries US equities and ETFs only",
        "finviz": "Finviz carries US equities and ETFs only",
    },
}

#: Every spelling, from every provider's column, folded onto the canonical
#: name. A caller can therefore ask with any provider's own vocabulary
#: (``^GSPC``, ``COMEX:GC1!``, ``CL1:COM``) and still land on the right row.
#: A Bloomberg class suffix (``IWM:US``, ``XAUUSD:CUR``, ``CL1:COM``) is *not*
#: a spelling of its own: the class token alone (``US``, ``CUR``, ``COM``,
#: ``IND``) matches every row, so only the full id is folded, never its tail.
_INSTRUMENT_LOOKUP: dict[str, str] = {}
for _canonical, _row in INSTRUMENTS.items():
    _INSTRUMENT_LOOKUP[_canonical.lower()] = _canonical
    for _provider in ("tradingview", "finviz", "yahoo", "sa", "bloomberg"):
        _spelling = _row.get(_provider)
        if isinstance(_spelling, str) and _spelling:
            _bare = _spelling.split(":", 1)[-1].lower().lstrip("^").rstrip("!")
            # Only fold the bare tail when it is longer than a class suffix,
            # so ``IWM:US`` does not teach the lookup that ``us`` means IWM.
            if len(_bare) > 3 or _provider == "tradingview":
                _INSTRUMENT_LOOKUP.setdefault(_bare, _canonical)
            _INSTRUMENT_LOOKUP.setdefault(_spelling.lower(), _canonical)

#: Spelling aliases a caller plausibly types but no provider column carries.
#: The value must be a canonical row name.
_INSTRUMENT_ALIASES: dict[str, str] = {
    "GSPC": "SPX",
    "SP500": "SPX",
    "IXIC": "COMP",
    "DJIA": "DJI",
    "INDU": "DJI",
    "RUSSELL2000": "RUT",
    "WTI": "USOIL",
    "BRENT": "UKOIL",
    "CRUDE": "USOIL",
    "COPPER": "HG1!",
    "NATGAS": "NG1!",
    "NATURALGAS": "NG1!",
    "GOLD": "XAUUSD",
    "SILVER": "XAGUSD",
    "GCF": "GC1!",
    "SIF": "SI1!",
    "CLF": "CL1!",
    "BZF": "BZ1!",
    "NGF": "NG1!",
    "HGF": "HG1!",
    # ``WTI=F`` is Yahoo's futures convention applied to the commodity's
    # name: a caller typing it means the front-month future, and Yahoo's own
    # ticker for that is ``CL=F``. Left to search it lands on ``XETR:WTIF``,
    # the WisdomTree Japan ETF, a different instrument at a tenth of the
    # price.
    "WTI=F": "CL1!",
    "WTIF": "CL1!",
    "USOIL=F": "CL1!",
    "UKOIL=F": "BZ1!",
    "BRENT=F": "BZ1!",
}

#: The same aliases, lowercased, so :func:`canonical_instrument` can fold any
#: caller spelling onto a canonical row with one dictionary lookup.
_ALIASES_LOWER: dict[str, str | None] = {
    k.lower(): v for k, v in _INSTRUMENT_ALIASES.items() if v is not None
}


def canonical_instrument(symbol: str) -> str | None:
    """Map any provider's spelling of a registered instrument to its row key.

    Understands venue prefixes (``COMEX:GC1!``), Yahoo carets (``^GSPC``),
    Yahoo futures equals (``GC=F``) and Bloomberg class suffixes
    (``GC1:COM``), because every provider column of every registered row was
    folded into the lookup. Returns ``None`` for anything unregistered; the
    dynamic search path then takes over.
    """
    key = symbol.strip().lower().replace(" ", "")
    if not key:
        return None
    if key in _INSTRUMENT_LOOKUP:
        return _INSTRUMENT_LOOKUP[key]
    if key in _ALIASES_LOWER:
        return _ALIASES_LOWER[key]
    if ":" in key:
        tail = key.split(":", 1)[1]
        if tail in _INSTRUMENT_LOOKUP:
            return _INSTRUMENT_LOOKUP[tail]
        if tail in _ALIASES_LOWER:
            return _ALIASES_LOWER[tail]
    return None


def instrument_row(symbol: str) -> dict[str, Any] | None:
    """The registry row for *symbol*, or ``None`` when it is not registered.

    Callers get the row as a plain dict copy, so a caller cannot mutate the
    registry through it.
    """
    canonical = canonical_instrument(symbol)
    if canonical is None:
        return None
    return dict(INSTRUMENTS[canonical])


def registry_resolution(query: str, provider: str) -> Resolution | None:
    """Resolve *query* for *provider* from the instrument registry alone.

    Returns a :class:`Resolution` when the query names a registered
    instrument, with ``method="alias"`` and the provider's spelling (or the
    documented reason it is not carried), and ``None`` when the query is not
    registered, so the caller falls through to the dynamic search path.

    The registry is the addressing layer, not the scope layer: it never
    decides who is *asked*, only what ticker each leg is asked for. A
    ``symbol=None`` result states a boundary the provider itself declares.
    """
    canonical = canonical_instrument(query)
    if canonical is None:
        return None
    row = INSTRUMENTS[canonical]
    provider = provider.upper()
    column = {
        "TRADINGVIEW": "tradingview",
        "FINVIZ": "finviz",
        "YAHOO": "yahoo",
        "SA": "sa",
        "BLOOMBERG": "bloomberg",
    }.get(provider)
    if column is None:
        return None

    spelling = row.get(column)
    note = row.get(f"{column}_note")
    if spelling is None:
        reason = (
            note
            or _CLASS_NOT_CARRIED.get(str(row.get("asset_class") or ""), {}).get(column)
            or _DEFAULT_NOT_CARRIED.get(
                column, "not carried by this provider"
            )
        )
        return Resolution(
            query=query,
            provider=provider,
            note=reason,
            asset_class=str(row.get("asset_class") or ""),
        )
    return Resolution(
        query=query,
        provider=provider,
        symbol=str(spelling),
        method="alias",
        confidence=0.95,
        asset_class=str(row.get("asset_class") or ""),
        description=str(row.get("name") or ""),
        note="registry alias",
    )


# ── Synchronous helpers ──────────────────────────────────────────────────────
#
# Resolution above answers "which ticker does provider X use". The helpers below
# answer the cheaper, purely mechanical questions the shapers ask afterwards:
# "strip the venue from this label", "which canonical index is this level".
# They never touch the network, so they are safe to call in a formatting loop.
#
# Registered instruments need a table: ``SPX`` / ``SP:SPX`` / ``^GSPC`` are
# three names for one instrument and no search API will tell you they are the
# same series. The table is the list of instruments this server reports, not a
# guess about arbitrary tickers.

#: Kept for compatibility with existing callers and tests: the index subset of
#: :data:`INSTRUMENTS`, same row shape as before. Derived, never hand-edited;
#: new index rows belong in :data:`INSTRUMENTS`.
INDEX_ALIASES: dict[str, dict[str, Any]] = {
    canonical: {
        "yahoo": row["yahoo"],
        "finviz": row["finviz"],
        "tradingview": row["tradingview"],
        "name": row["name"],
    }
    for canonical, row in INSTRUMENTS.items()
    if row["asset_class"] == "index" or canonical == "IWM"
}


def canonical_index(symbol: str) -> str | None:
    """Map any index spelling (``^GSPC``, ``SPX``, ``SP:SPX``) to its short name.

    Thin compatibility wrapper over :func:`canonical_instrument`: an index
    row of the registry answers directly, and an equity/ETF row (``IWM``)
    returns its own canonical name, preserving the index/ETF separation.
    """
    canonical = canonical_instrument(symbol)
    if canonical is None:
        return None
    if INSTRUMENTS[canonical].get("asset_class") in {"index", "etf"}:
        return canonical
    return None


def strip_exchange(symbol: str) -> str:
    """``NASDAQ:AAPL`` -> ``AAPL``; leaves plain symbols untouched."""
    return symbol.split(":", 1)[1] if ":" in symbol else symbol


#: Yahoo-style crypto/FX tickers that Finviz has no equivalent for.
_NON_EQUITY = re.compile(r"(-USD|=X|^[A-Z]{3,5}USDT$|^\^)", re.IGNORECASE)


def to_finviz(symbol: str) -> str:
    """Finviz's spelling for a symbol (``BRK-B`` -> ``BRK.B``, ``^GSPC`` -> ``SPX``).

    Registered instruments answer from the registry's ``finviz`` cell; the
    cell folds every provider's spelling onto Finviz's own (``^GSPC`` ->
    ``SPX``). For index rows whose cell is ``None`` (Finviz serves indices
    through its indices feed only, and ``/stock?t=SPX`` is a 404), the
    canonical name is returned: the value is only a comparison key there,
    never a page URL.
    """
    raw = strip_exchange(symbol).strip().upper()
    canonical = canonical_instrument(raw)
    if canonical is not None:
        spelling = INSTRUMENTS[canonical].get("finviz")
        if spelling:
            return str(spelling)
        if INSTRUMENTS[canonical].get("asset_class") == "index":
            return canonical
        return raw
    if raw and "-" in raw and len(raw) <= 7 and not raw.endswith("-USD"):
        head, _, tail = raw.partition("-")
        if head.isalpha() and tail.isalpha() and len(tail) <= 2:
            return f"{head}.{tail}"
    return raw


def to_yahoo(symbol: str) -> str:
    """Yahoo's spelling for a symbol (``BRK.B`` -> ``BRK-B``, ``SPX`` -> ``^GSPC``).

    Registered instruments answer from the registry's ``yahoo`` cell, so the
    index spellings have one home. A registered row whose Yahoo cell is
    ``None`` (Yahoo has no spot pair for it) keeps the bare spelling: the
    resolution layer already reports that boundary, this helper must not
    invent a ticker.
    """
    raw = strip_exchange(symbol).strip().upper()
    canonical = canonical_instrument(raw)
    if canonical is not None:
        spelling = INSTRUMENTS[canonical].get("yahoo")
        return str(spelling) if spelling else raw
    if raw and "." in raw and len(raw) <= 7:
        head, _, tail = raw.partition(".")
        if head.isalpha() and tail.isalpha() and len(tail) <= 2:
            return f"{head}-{tail}"
    return raw


def is_equity(symbol: str) -> bool:
    """True when Finviz could plausibly have this instrument (US-listed equity/ETF)."""
    raw = strip_exchange(symbol).strip().upper()
    if not raw or _NON_EQUITY.search(raw):
        return False
    if "." in raw and not raw.replace(".", "").isalnum():
        return False
    return bool(re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", raw))


def to_tradingview_candidates(symbol: str) -> list[str]:
    """Legacy venue candidates for a bare US ticker.

    Kept for the paths that have not moved to :func:`resolve` yet. New code
    should call :func:`resolve_tradingview`, which asks TradingView where the
    symbol actually lives instead of assuming a US venue.
    """
    raw = strip_exchange(symbol).strip().upper()
    if ":" in symbol:
        return [symbol.strip().upper()]
    return [f"{venue}:{raw}" for venue in ("NASDAQ", "NYSE", "AMEX")]
