"""Native Investing.com instrument search, verified quote pages and shaping.

Plain ``httpx`` is refused by this upstream. The accessors below therefore use
one pooled ``curl_cffi`` browser session per event loop, shared pacing and short
caches. Search results supply the only acceptable path: no code here constructs
an ``/equities/<company>`` slug or substitutes a same-symbol foreign listing.

A quote is admitted only after the page repeats the search result's instrument
id, symbol, exchange, currency and supported equity/ETF class. The displayed
``lastClose`` is deliberately not treated as the regular session's previous
close. Regular and extended prints instead retain their own timestamp and
change percentage in :func:`tapebasis.sessions.live_print`.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import weakref
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from .freshness import parse_market_timestamp
from .providers_state import NoDataError, ProviderError
from .ratelimit import RateLimited, call, limiter

PROVIDER = "INVESTING"
_BASE = "https://www.investing.com"
_SEARCH = "https://endpoints.investing.com/pd-instruments/v1/instruments/search"
_IMPERSONATE = os.environ.get("TAPEBASIS_INVESTING_IMPERSONATE", "chrome124")
_TIMEOUT = float(os.environ.get("TAPEBASIS_INVESTING_TIMEOUT", "30"))
_CACHE_TTL = float(os.environ.get("TAPEBASIS_INVESTING_CACHE_TTL", "20"))
_SEARCH_CACHE_TTL = float(os.environ.get("TAPEBASIS_INVESTING_SEARCH_CACHE_TTL", "600"))

_NEXT_DATA = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(?P<body>.*?)</script>', re.S
)
_SUPPORTED_TYPES = {"equity": ("equities", "stock"), "etf": ("etf", "etfs")}
_EXCHANGE_ALIASES = {
    "NASDAQ": "NASDAQ",
    "NASDAQGS": "NASDAQ",
    "NASDAQGM": "NASDAQ",
    "NASDAQCM": "NASDAQ",
    "NMS": "NASDAQ",
    "NYQ": "NYSE",
    "NYSE": "NYSE",
    "NYSEAMERICAN": "AMEX",
    "AMEX": "AMEX",
    "ARCA": "ARCA",
    "BATS": "BATS",
}


def _client() -> Any:
    """Return the browser-impersonating async session class or a typed error."""
    try:
        from curl_cffi.requests import AsyncSession
    except Exception as exc:  # noqa: BLE001 - package boundary
        raise ProviderError(
            PROVIDER,
            "curl_cffi is not installed; Investing.com requires its browser TLS "
            "fingerprint because plain HTTP clients are refused",
            code="NOT_CONFIGURED",
        ) from exc
    return AsyncSession


_SESSIONS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any]" = (
    weakref.WeakKeyDictionary()
)


def _session() -> Any:
    """Return the pooled browser session owned by the current event loop."""
    loop = asyncio.get_running_loop()
    session = _SESSIONS.get(loop)
    if session is None:
        session = _client()(
            impersonate=_IMPERSONATE,
            timeout=_TIMEOUT,
            headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"{_BASE}/",
            },
        )
        _SESSIONS[loop] = session
    return session


async def aclose() -> None:
    """Close the current loop's pooled session without failing shutdown."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    session = _SESSIONS.pop(loop, None)
    if session is None:
        return
    try:
        await session.close()
    except Exception:  # noqa: BLE001 - a dead socket must not block shutdown
        pass


def _transport_error(exc: Exception) -> ProviderError:
    """Return a stable provider failure for a curl_cffi transport exception."""
    name = type(exc).__name__
    timed_out = "timeout" in str(exc).lower() or "timeout" in name.lower()
    return ProviderError(
        PROVIDER,
        f"Investing.com transport failed ({name}): {exc}",
        code="UPSTREAM_TIMEOUT" if timed_out else "UPSTREAM_ERROR",
    )


async def search(query: str) -> list[dict[str, Any]]:
    """Return raw Investing search instruments for an unmodified user query.

    All cursor-linked pages are searched before identity selection, up to five
    pages, so an exact listing on a later page is neither missed nor accepted
    without noticing another primary listing. Repeated cursors, malformed
    pagination or a longer chain are schema drift rather than incomplete data.
    The combined response is cached briefly. HTTP failures keep distinct
    rate-limit, blocked, not-found and upstream error codes; malformed JSON is
    schema drift.
    """
    from urllib.parse import urlencode

    text = query.strip()
    if not text:
        raise NoDataError(PROVIDER, "empty symbol query")
    cache_key = f"search:{text.upper()}"
    paced = limiter(PROVIDER)
    cached = paced.cache_get(cache_key, _SEARCH_CACHE_TTL)
    if isinstance(cached, list):
        return cached

    async def _once() -> list[dict[str, Any]]:
        instruments: list[dict[str, Any]] = []
        cursor = ""
        visited: set[str] = set()
        for page in range(5):
            parameters = {"domain_id": 1, "query": text}
            if cursor:
                parameters["cursor"] = cursor
            try:
                response = await _session().get(
                    f"{_SEARCH}?{urlencode(parameters)}",
                    headers={"Accept": "application/json"},
                )
            except NoDataError:
                raise
            except Exception as exc:  # noqa: BLE001 - curl's native exception family
                raise _transport_error(exc) from exc
            status = response.status_code
            if status == 429:
                raise RateLimited(PROVIDER, "Investing search HTTP 429")
            if status in (401, 403):
                raise ProviderError(
                    PROVIDER,
                    f"Investing.com search refused HTTP {status}; the browser-impersonated "
                    "request was blocked rather than treated as an empty search",
                    code="UPSTREAM_BLOCKED",
                )
            if status != 200:
                raise ProviderError(
                    PROVIDER,
                    f"Investing.com search answered HTTP {status}",
                    code="UPSTREAM_ERROR",
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderError(
                    PROVIDER,
                    f"Investing search returned invalid JSON: {exc}",
                    code="SCHEMA_DRIFT",
                ) from exc
            if not isinstance(payload, dict):
                raise ProviderError(
                    PROVIDER, "Investing search returned a non-object page",
                    code="SCHEMA_DRIFT",
                )
            rows = payload.get("instruments")
            cursor = payload.get("next_page_cursor")
            if (
                not isinstance(rows, list)
                or any(not isinstance(row, dict) for row in rows)
                or cursor is not None and not isinstance(cursor, str)
            ):
                raise ProviderError(
                    PROVIDER,
                    "Investing search no longer returns instruments and a valid next-page cursor",
                    code="SCHEMA_DRIFT",
                )
            instruments.extend(rows)
            if not cursor:
                paced.cache_set(cache_key, instruments)
                return instruments
            if cursor in visited or page == 4:
                raise ProviderError(
                    PROVIDER,
                    "Investing search cursor repeated or exceeded the five-page identity bound",
                    code="SCHEMA_DRIFT",
                )
            visited.add(cursor)
        raise AssertionError("unreachable Investing search pagination boundary")

    return await call(PROVIDER, _once, attempts=1)


def _exchange(value: Any) -> str:
    """Return an upper-case exchange spelling with spaces removed."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def symbol_key(value: Any) -> str:
    """Return a share-class-insensitive symbol key for exact resolution."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def exchange_key(value: Any) -> str:
    """Return a comparable exchange alias, or the normalized unknown venue."""
    normalized = _exchange(value)
    return _EXCHANGE_ALIASES.get(normalized, normalized)


def asset_class_for(row: Mapping[str, Any]) -> str | None:
    """Return ``stock`` or ``etf`` for supported rows and ``None`` otherwise."""
    client = str(row.get("client_type") or "").strip().lower()
    kind = str(row.get("type") or "").strip().lower()
    link = str(row.get("link") or "")
    if client == "stock" and kind in ("equities", "equity"):
        return "stock"
    if client == "etf" and kind == "etf":
        return "etf"
    # Some older search responses omit the client label but retain an exact,
    # provider-native class and route. That is enough to classify, not to bypass
    # the later page identity and ``base.type`` check.
    if not client and kind in ("equities", "equity") and link.startswith("/equities/"):
        return "stock"
    if not client and kind == "etf" and link.startswith("/etfs/"):
        return "etf"
    return None


def instrument_identity(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return a supported, fully identified search identity or ``None``.

    Numeric ids, active status, symbol, exchange, currency and a native link are
    mandatory. The optional extended block is not identity and is ignored here.
    """
    if row.get("active") is False:
        return None
    asset_class = asset_class_for(row)
    if asset_class is None:
        # ``Resolution.native`` stores the already verified search identity,
        # where the type was normalized to this server's vocabulary. Accept
        # that representation too; arbitrary raw search rows still need their
        # provider-native class labels and route.
        asset_class = (
            str(row.get("asset_class") or "").strip().lower()
            if row.get("asset_class") is not None
            and not row.get("type")
            and not row.get("client_type")
            else ""
        ) or None
        if asset_class == "equity":
            asset_class = "stock"
        if asset_class not in {"stock", "etf"}:
            asset_class = None
    instrument_id = row.get("instrument_id", row.get("id"))
    link = str(row.get("link") or "")
    symbol = str(row.get("symbol") or row.get("display_symbol") or "").strip()
    exchange = str(
        row.get("exchange_short_name") or row.get("exchange") or ""
    ).strip()
    currency = str(row.get("currency_code") or row.get("currency") or "").strip()
    if (
        asset_class is None
        or isinstance(instrument_id, bool)
        or not isinstance(instrument_id, int)
        or instrument_id <= 0
        or not symbol
        or not exchange
        or not currency
        or urlsplit(link).scheme
        or urlsplit(link).netloc
        or not link.startswith("/")
        or not link.startswith("/etfs/" if asset_class == "etf" else "/equities/")
    ):
        return None
    return {
        "instrument_id": instrument_id,
        "symbol": symbol,
        "display_symbol": str(row.get("display_symbol") or symbol),
        "exchange": exchange,
        "currency": currency,
        "asset_class": asset_class,
        "name": str(row.get("long_name") or row.get("short_name") or row.get("name") or ""),
        "country": str(row.get("country") or ""),
        "link": link,
        "source": f"{_BASE}{link}",
    }


def choose_instrument(
    rows: list[dict[str, Any]],
    query: str,
    *,
    exchange: str | None = None,
    asset_class: str = "",
) -> dict[str, Any] | None:
    """Choose one exact symbol/listing or reject unresolved ambiguity.

    Bare requests accept a supported primary listing only: parent id zero or the
    row's own id. Secondary depositary receipts and cross-listings, including
    MSFT Toronto/CAD, must not displace a primary US listing merely because they
    carry the same symbol. Multiple supported primary matches remain ambiguous;
    the caller must supply an exchange rather than receive the first search row.
    The optional class hint restricts candidates without relaxing identity.
    """
    exact_symbol = symbol_key(query.split(":", 1)[-1] if ":" in query else query)
    candidates = []
    for row in rows:
        identity = instrument_identity(row)
        if identity is None or symbol_key(identity["symbol"]) != exact_symbol:
            continue
        if exchange and exchange_key(identity["exchange"]) != exchange_key(exchange):
            continue
        wanted = asset_class.strip().lower()
        if wanted == "equity":
            wanted = "stock"
        if wanted in ("stock", "etf") and identity["asset_class"] != wanted:
            continue
        if wanted and wanted not in ("stock", "equity", "etf"):
            continue
        if not exchange and row.get("parent_id") not in (0, None, identity["instrument_id"]):
            continue
        candidates.append(identity)
    if len(candidates) != 1:
        return None
    return candidates[0]


async def _fetch_html(path: str, cache_key: str) -> str:
    """Read exactly the search-provided native path under pacing and short cache."""
    parsed = urlsplit(path)
    if parsed.scheme != "https" or parsed.netloc != "www.investing.com":
        raise ProviderError(
            PROVIDER,
            f"refusing a non-native Investing quote URL: {path}",
            code="UNSAFE_PROVIDER_URL",
        )
    # Preserve a native search result's cid query. It carries identity for some
    # listings and is part of the cache key; no path is generated locally.
    url = urlunsplit(parsed)
    paced = limiter(PROVIDER)
    cached = paced.cache_get(cache_key, _CACHE_TTL)
    if isinstance(cached, str):
        return cached

    async def _once() -> str:
        try:
            response = await _session().get(url)
        except Exception as exc:  # noqa: BLE001 - curl's native exception family
            raise _transport_error(exc) from exc
        status = response.status_code
        if status == 429:
            raise RateLimited(PROVIDER, "Investing quote page HTTP 429")
        if status in (401, 403):
            raise ProviderError(
                PROVIDER,
                f"Investing.com refused the quote page with HTTP {status}; this is "
                "the anti-bot wall, not proof that the instrument has no price",
                code="UPSTREAM_BLOCKED",
            )
        if status == 404:
            raise NoDataError(PROVIDER, f"Investing.com has no quote page at {path}")
        if status != 200:
            raise ProviderError(
                PROVIDER,
                f"Investing.com quote page answered HTTP {status}",
                code="UPSTREAM_ERROR",
            )
        body = response.text
        paced.cache_set(cache_key, body)
        return body

    return await call(PROVIDER, _once, attempts=1)


def _state(html: str) -> dict[str, Any]:
    """Decode the SSR state and return a dict, or raise schema drift."""
    match = _NEXT_DATA.search(html)
    if not match:
        raise ProviderError(
            PROVIDER,
            "Investing quote page no longer contains __NEXT_DATA__",
            code="SCHEMA_DRIFT",
        )
    try:
        state = json.loads(match.group("body"))["props"]["pageProps"]["state"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ProviderError(
            PROVIDER,
            f"Investing page state is missing or invalid: {exc}",
            code="SCHEMA_DRIFT",
        ) from exc
    if not isinstance(state, dict):
        raise ProviderError(
            PROVIDER, "Investing page state is not an object", code="SCHEMA_DRIFT"
        )
    return state


def _instrument_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return the exact equity or ETF instrument object from the page state."""
    matches = []
    for key, kinds in (("equityStore", ("equity",)), ("etfStore", ("etf",))):
        store = state.get(key)
        instrument = store.get("instrument") if isinstance(store, dict) else None
        base = instrument.get("base") if isinstance(instrument, dict) else None
        if isinstance(instrument, dict) and isinstance(base, dict):
            if str(base.get("type") or "").lower() not in kinds:
                raise ProviderError(
                    PROVIDER,
                    f"{key} returned an unexpected instrument class {base.get('type')!r}",
                    code="SCHEMA_DRIFT",
                )
            matches.append((key, instrument, store.get("instrumentId")))
    if len(matches) != 1:
        raise ProviderError(
            PROVIDER,
            "Investing page must expose exactly one equity or ETF instrument",
            code="SCHEMA_DRIFT",
        )
    key, instrument, store_id = matches[0]
    return {
        "store": key,
        "instrument": instrument,
        "store_id": store_id,
    }


def _number(value: Any) -> float | None:
    """Return a finite provider number and never parse a bool as a price."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _timestamp(value: Any) -> str | None:
    """Return one provider print time in UTC ISO form.

    Investing renders epoch values in decimal milliseconds, unlike most of this
    server's epoch seconds. Numeric values above 10^11 are divided by 1000 before
    parsing. Strings that are already ISO timestamps retain their actual offset.
    Invalid epoch values return ``None`` rather than a false freshness claim.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        stamp = float(value)
        if abs(stamp) >= 100_000_000_000:
            stamp /= 1000.0
        try:
            return datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
        except (ValueError, OverflowError, OSError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        stamp = float(text)
    except ValueError:
        parsed = parse_market_timestamp(text)
        return parsed.isoformat().replace("+00:00", "Z") if parsed else None
    return _timestamp(stamp)


def _extended(period: Any, price: Mapping[str, Any], kind: str) -> dict[str, Any]:
    """Return one extended print with its own clock, price and display change."""
    block = price.get(period) if isinstance(price.get(period), Mapping) else {}
    prefix = "afterHours" if kind == "aftermarket" else "premarket"
    return {
        "session": kind,
        "price": _number(block.get("price") if block else price.get(f"{prefix}Price")),
        "change": _number(block.get("change") if block else price.get(f"{prefix}Change")),
        "change_percent": _number(
            block.get("change_percent")
            if block
            else price.get(f"{prefix}ChangePercent")
        ),
        "volume": _number(block.get("volume") if block else price.get(f"{prefix}Volume")),
        "price_timestamp": _timestamp(
            block.get("shown_date_time")
            if block
            else price.get(
                "extendedUpdateTimeUnix" if kind == "aftermarket" else "preUpdateTimeUnix"
            )
        ),
    }


def _verdict(value: Any) -> dict[str, Any] | None:
    """Return one provider-owned technical verdict without generalizing it."""
    if not isinstance(value, dict):
        return None
    verdict = value.get("verdict")
    if not isinstance(verdict, dict):
        return None
    return {
        "label": verdict.get("translated_label"),
        "score": _number(verdict.get("score")),
        "definition": verdict.get("define"),
    }


def shape_quote(
    state: dict[str, Any], expected_identity: Mapping[str, Any]
) -> dict[str, Any]:
    """Verify page identity and shape shared fields and Investing-only extras.

    Raises ``SCHEMA_DRIFT`` on any identity or structural mismatch. ``lastClose``
    is retained only in the diagnostic exclusion record. It never populates
    ``previous_close``. An ordinary stock may therefore carry a ``None`` baseline,
    while an ETF may use its separately published ``keyStatistics.prevClose``.
    """
    expected = instrument_identity(dict(expected_identity))
    if expected is None:
        raise ProviderError(
            PROVIDER, "invalid expected Investing identity", code="SCHEMA_DRIFT"
        )
    try:
        found = _instrument_from_state(state)
        instrument = found["instrument"]
        base = instrument["base"]
        page_price = instrument["price"]
        name = instrument["name"]
        exchange = instrument["exchange"]
        assert isinstance(base, dict)
        assert isinstance(page_price, dict)
        assert isinstance(name, dict)
        assert isinstance(exchange, dict)
    except (KeyError, AssertionError) as exc:
        raise ProviderError(
            PROVIDER,
            f"Investing instrument/price identity fields are missing: {exc}",
            code="SCHEMA_DRIFT",
        ) from exc
    actual_id = base.get("id")
    try:
        numeric_id = int(actual_id)
    except (TypeError, ValueError) as exc:
        raise ProviderError(
            PROVIDER, "Investing page has no numeric instrument id", code="SCHEMA_DRIFT"
        ) from exc
    errors = []
    if numeric_id != expected["instrument_id"]:
        errors.append(f"instrument id {actual_id!r} != {expected['instrument_id']}")
    if found["store_id"] is not None and str(found["store_id"]) != str(expected["instrument_id"]):
        errors.append(f"store instrument id {found['store_id']!r} disagrees with the search id")
    if symbol_key(name.get("symbol")) != symbol_key(expected["symbol"]):
        errors.append(f"symbol {name.get('symbol')!r} != {expected['symbol']!r}")
    if exchange_key(exchange.get("exchange")) != exchange_key(expected["exchange"]):
        errors.append(f"exchange {exchange.get('exchange')!r} != {expected['exchange']!r}")
    if str(page_price.get("currency") or "").upper() != expected["currency"].upper():
        errors.append(f"currency {page_price.get('currency')!r} != {expected['currency']!r}")
    expected_type = "equity" if expected["asset_class"] == "stock" else "etf"
    if str(base.get("type") or "").lower() != expected_type:
        errors.append(f"class {base.get('type')!r} != {expected_type!r}")
    actual_path = base.get("path")
    expected_path = urlsplit(expected["link"]).path
    if actual_path != expected_path:
        errors.append(f"native path {actual_path!r} != {expected_path!r}")
    if errors:
        raise ProviderError(
            PROVIDER,
            "Investing quote identity mismatch: " + "; ".join(errors),
            code="SCHEMA_DRIFT",
            expected_identity=expected,
        )
    price = _number(page_price.get("last"))
    if price is None:
        raise NoDataError(
            PROVIDER, f"Investing.com has identity {expected['instrument_id']} but no last price"
        )
    stats = instrument.get("keyStatistics") or {}
    stats = stats if isinstance(stats, dict) else {}
    extended_kind = str(page_price.get("showExtendedHours") or "").lower()
    if extended_kind not in ("aftermarket", "premarket"):
        extended_kind = ""
    forecast = state.get("forecastStore", {}).get("forecast")
    if not isinstance(forecast, dict):
        forecast = None
    if forecast is not None and str(forecast.get("instrument_id")) != str(expected["instrument_id"]):
        raise ProviderError(
            PROVIDER,
            "Investing analyst data belongs to a different instrument id",
            code="SCHEMA_DRIFT",
        )
    technical = state.get("technicalStore", {}).get("summaries", {}).get("1d")
    technical_summary = None
    if isinstance(technical, dict):
        technical_summary = {
            "as_of": technical.get("as_of"),
            "interval": technical.get("interval"),
            "summary": _verdict(technical.get("summary")),
            "moving_averages": {
                key: technical.get("moving_averages", {}).get(key)
                for key in ("buy_count", "neutral_count", "sell_count")
            },
            "moving_average_verdict": _verdict(technical.get("moving_averages")),
            "technical_indicators": {
                key: technical.get("technical_indicators", {}).get(key)
                for key in ("buy_count", "neutral_count", "sell_count")
            },
            "technical_indicator_verdict": _verdict(technical.get("technical_indicators")),
            "source_scope": "Investing.com model and daily interval only; not Tapebasis technical_analysis",
        }
    ratios = state.get("dividendsStore", {}).get("ratios", {})
    indicators = ratios.get("indicators", {}) if isinstance(ratios, dict) else {}

    def ratio(key: str) -> float | None:
        """Return a named Investing ratio with its period kept in its own key."""
        value = indicators.get(key)
        return _number(value.get("value")) if isinstance(value, dict) else None

    earnings = instrument.get("earnings") or {}
    earnings = earnings if isinstance(earnings, dict) else {}
    fundamental = instrument.get("fundamental") or {}
    fundamental = fundamental if isinstance(fundamental, dict) else {}
    # ``lastClose`` is the displayed same-session value on observed stock pages,
    # not the arithmetic baseline behind their regular percentage change.
    # Only the explicit ETF ``prevClose`` carries a verified different meaning.
    previous_close = _number(stats.get("prevClose")) if expected["asset_class"] == "etf" else None
    extended = {
        "Premarket": _extended("premarket", page_price, "premarket"),
        "Aftermarket": _extended("aftermarket", page_price, "aftermarket"),
    }
    selected = extended.get(
        str(page_price.get("showExtendedHours") or ""), {}
    ) if extended_kind else {}
    analyst = None
    if forecast:
        analyst = {
            "instrument_id": expected["instrument_id"],
            "currency": expected["currency"],
            "price_target_average": _number(forecast.get("target_price_consensus_mean")),
            "price_target_low": _number(forecast.get("target_price_consensus_low")),
            "price_target_high": _number(forecast.get("target_price_consensus_high")),
            "price_target_estimate_count": forecast.get("number_of_estimates"),
            "rating_analyst_count": sum(
                forecast.get(key, 0)
                for key in (
                    "number_of_analysts_buy",
                    "number_of_analysts_hold",
                    "number_of_analysts_sell",
                )
                if isinstance(forecast.get(key), int)
            ) or None,
            "rating_distribution": {
                "buy": forecast.get("number_of_analysts_buy"),
                "hold": forecast.get("number_of_analysts_hold"),
                "sell": forecast.get("number_of_analysts_sell"),
            },
            "rating_distribution_method": "investing_forecast_store_buckets",
            "recommendation": forecast.get("consensus_recommendation"),
            "last_rating_date": forecast.get("last_rating_date"),
            "upside_percent": _number(forecast.get("upside_percent")),
            "source_scope": "Investing.com forecast population only; never combined with another provider",
        }
    return {
        "symbol": name.get("symbol"),
        "requested": expected["symbol"],
        "instrument_id": expected["instrument_id"],
        "name": name.get("fullName") or name.get("shortName"),
        "company": name.get("fullName") or name.get("shortName"),
        "asset_class": expected["asset_class"],
        "exchange": exchange.get("exchange"),
        "currency": page_price.get("currency"),
        "price": price,
        "change": _number(page_price.get("change")),
        "change_percent": _number(page_price.get("changePcr")),
        "previous_close": previous_close,
        "day_open": _number(page_price.get("open") or stats.get("priceOpen")),
        "day_high": _number(page_price.get("high") or stats.get("high")),
        "day_low": _number(page_price.get("low") or stats.get("low")),
        "week_52_high": _number(page_price.get("fiftyTwoWeekHigh") or stats.get("fiftyTwoWeekHigh")),
        "week_52_low": _number(page_price.get("fiftyTwoWeekLow") or stats.get("fiftyTwoWeekLow")),
        "volume": _number(page_price.get("volume")),
        "pe_ratio": ratio("pe_ratio_ttm"),
        "market_cap": _number(fundamental.get("marketCapRaw") or stats.get("marketCap")),
        "price_timestamp": _timestamp(page_price.get("lastUpdateTime")),
        "price_timestamp_source": "instrument.price.lastUpdateTime (epoch ms)",
        "is_exchange_delayed": page_price.get("isDelayed"),
        "exchange_delay": "delayed" if page_price.get("isDelayed") is True else None,
        "market_status": "open" if base.get("isOpen") is True else "closed" if base.get("isOpen") is False else None,
        "show_extended_hours": page_price.get("showExtendedHours"),
        "extended_kind": extended_kind if selected else "",
        "extended_hours": {
            key: value for key, value in selected.items() if value is not None
        },
        "investing_extended_sessions": extended,
        "investing_beta": ratio("beta") if ratio("beta") is not None else _number(stats.get("beta")),
        "investing_dividend_yield_ann": ratio("dividend_yield_ann"),
        "investing_etf_dividend_yield": _number(stats.get("dividendYield")),
        "investing_basic_eps_ann": ratio("basic_eps_ann"),
        "investing_price_to_book_mrq": ratio("price_to_book_mrq"),
        "investing_gross_margin_ttm": ratio("gross_margin_ttm"),
        "investing_return_on_assets_ttm": ratio("return_on_assets_ttm"),
        "investing_return_on_equity_ttm": ratio("return_on_equity_ttm"),
        "investing_next_earnings_date": str(earnings.get("nextReport") or "").partition(" ")[0] or None,
        "investing_last_close_value": _number(page_price.get("lastClose")),
        "investing_previous_close_excluded": (
            "instrument.price.lastClose and search price.last_close_value were not "
            "mapped to previous_close because their baseline meaning is unverified"
        ),
        "investing_analyst": analyst,
        "investing_technical_1d": technical_summary,
    }


async def quote_with_identity(identity: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """Fetch and shape a quote for a fully resolved Investing identity.

    Returns the verified payload together with its native source URL. No symbol
    string can select a listing except through the search identity passed here.
    """
    expected = instrument_identity(dict(identity))
    if expected is None:
        raise NoDataError(PROVIDER, "the Investing search result has incomplete identity")
    html = await _fetch_html(
        expected["source"], f"quote:{expected['instrument_id']}"
    )
    return shape_quote(_state(html), expected), expected["source"]


async def quote_with_resolution(resolution: Any) -> tuple[dict[str, Any], str]:
    """Fetch a quote using only the identity stored in a native resolution."""
    identity = getattr(resolution, "native", None)
    if not isinstance(identity, Mapping):
        raise NoDataError(
            PROVIDER,
            getattr(resolution, "note", "") or "no verified Investing identity",
        )
    return await quote_with_identity(identity)


__all__ = [
    "PROVIDER",
    "aclose",
    "asset_class_for",
    "choose_instrument",
    "exchange_key",
    "instrument_identity",
    "quote_with_identity",
    "quote_with_resolution",
    "search",
    "shape_quote",
    "symbol_key",
]

