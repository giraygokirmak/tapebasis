"""TradingView's quote websocket: the feed the web chart itself streams from.

The scanner is a snapshot service. It answers with the regular feed's last trade
for a symbol and, separately, that row's extended-session columns; it has no row
for the overnight venues at all (``BOATS:AAPL`` is rejected with
``symbol_not_exists`` on every scanner market, measured). The quote websocket is
a different upstream inside TradingView: it resolves symbols the scanner does
not index, streams their live price, and states the session each print belongs
to. That is what makes the 24-hour session reachable at all, and it is the same
socket the public web chart uses, so it is TradingView's own data rather than a
proxy for anyone else's.

One socket carries many symbols. The protocol is a sequence of JSON frames
wrapped in ``~m~<len>~m~<payload>``; each ``qsd`` message is a delta merged
into that symbol's earlier snapshot. Missing keys retain their previous value;
a received null remains an explicit null. Heartbeat frames must be echoed back
or the connection is dropped. This module speaks just
enough of that protocol to subscribe, collect, and close.

Rate limits are real and IP-scoped, exactly as they are for the chart socket:
asking too often gets the symbol refused as ``invalid symbol`` even though it
exists. Every call therefore goes through :mod:`tapebasis.ratelimit`.
"""
from __future__ import annotations

import json
import random
import string
import time
from typing import Any

from ...blocking_pool import run as run_blocking
from ...ratelimit import RateLimited, call, limiter
from ...utils import BROWSER_UA

PROVIDER = "TRADINGVIEW"

WS_URL = "wss://data.tradingview.com/socket.io/websocket?from=chart%2F&type=chart"

#: Fields asked of the quote socket. ``current_session`` is the whole point of
#: using this feed: it is the only place TradingView states, per print, whether
#: the number belongs to the regular session, an extended one, or the overnight
#: venue's out-of-session window. ``update_mode`` says whether it is streaming
#: or delayed, which the scanner also reports but per row rather than per print.
QUOTE_FIELDS: tuple[str, ...] = (
    "lp",
    "lp_time",
    "volume",
    "current_session",
    "update_mode",
    "ch",
    "chp",
    "short_name",
    "description",
    "exchange",
    "type",
    "original_name",
    "is_tradable",
    "pricescale",
)

#: How long to keep reading after the last new symbol arrives. Prints keep
#: streaming after the first response, so a short quiet window is what turns
#: "one print per symbol" into "the latest print per symbol".
_SETTLE_SECONDS = 1.5


class QuoteSocketError(Exception):
    """The quote socket refused the whole request."""


def _token(prefix: str = "qs") -> str:
    """A fresh session or request id, the shape the protocol expects."""
    return prefix + "_" + "".join(random.choice(string.ascii_uppercase) for _ in range(12))


def _frame(method: str, params: list[Any]) -> str:
    """One protocol frame: ``~m~<len>~m~<json>``."""
    payload = json.dumps({"m": method, "p": params}, separators=(",", ":"))
    return f"~m~{len(payload)}~m~{payload}"


def _messages(raw: str) -> list[dict[str, Any]]:
    """Every JSON message in one websocket frame, heartbeats discarded."""
    out: list[dict[str, Any]] = []
    for chunk in raw.split("~m~"):
        if not chunk or chunk.isdigit():
            continue
        try:
            message = json.loads(chunk)
        except ValueError:
            continue
        if isinstance(message, dict):
            out.append(message)
    return out


def _quote_blocking(tickers: list[str], timeout: float) -> dict[str, dict[str, Any]]:
    """Open one quote socket, subscribe to *tickers*, collect, close. Blocking.

    A plain function on purpose: it is handed to
    :func:`tapebasis.blocking_pool.run`, which calls it in a worker thread.

    Args:
        tickers: TradingView symbols. Both the scanner's spelling
            (``NASDAQ:AAPL``) and the overnight venue's (``BOATS:AAPL``) resolve
            here.
        timeout: Overall socket timeout in seconds.

    Returns:
        Each ticker that the socket resolved, mapped to its raw value dict. A
        ticker the upstream refuses is simply absent; the caller decides whether
        that is "no data" or a rate limit.

    Raises:
        QuoteSocketError: The socket failed before returning a print. A quiet
            connection returns the observations collected so far.
    """
    import websocket  # local import: optional dependency, only needed for sockets

    session = _token()
    connection = websocket.create_connection(
        WS_URL,
        timeout=timeout,
        header=["Origin: https://www.tradingview.com", f"User-Agent: {BROWSER_UA}"],
    )
    try:
        deadline = time.monotonic() + max(timeout, 0.0)
        connection.send(_frame("set_auth_token", ["unauthorized_user_token"]))
        connection.send(_frame("quote_create_session", [session]))
        connection.send(_frame("quote_set_fields", [session, *QUOTE_FIELDS]))
        for ticker in tickers:
            connection.send(_frame("quote_add_symbols", [session, ticker]))

        wanted = set(tickers)
        collected: dict[str, dict[str, Any]] = {}
        refused: list[str] = []
        while True:
            wait = min(_SETTLE_SECONDS if collected else timeout, deadline - time.monotonic())
            if wait <= 0:
                break
            connection.settimeout(wait)
            try:
                raw = connection.recv()
            except Exception as exc:  # noqa: BLE001
                timeout_error = getattr(websocket, "WebSocketTimeoutException", None)
                if isinstance(exc, TimeoutError) or (
                    timeout_error is not None and isinstance(exc, timeout_error)
                ):
                    # Ordinary receive silence ends this read. It is different
                    # from a transport failure masquerading as no observation.
                    break
                raise QuoteSocketError(f"quote receive failed: {exc}") from exc
            if not raw:
                if collected:
                    break
                raise QuoteSocketError("quote socket closed before sending a price")
            if raw.startswith("~h~"):
                # Heartbeats must be echoed or the server closes the socket.
                connection.send(raw)
                continue
            for message in _messages(raw):
                method = message.get("m")
                if method == "qsd":
                    body = (message.get("p") or [None, {}])[1]
                    name = body.get("n")
                    if name in wanted and body.get("s") == "ok":
                        collected.setdefault(name, {}).update(body.get("v") or {})
                elif method in {"symbol_error", "quote_error"}:
                    detail = message.get("p") or []
                    refused.append(str(detail[-1]) if detail else "")
                elif method == "critical_error":
                    raise QuoteSocketError(f"quote socket error: {message.get('p')}")
        if not collected and refused and all("invalid symbol" in r.lower() for r in refused):
            # The documented throttle signal: the symbols exist, this IP is
            # being refused. Reported as a rate limit, not as a missing symbol.
            raise RateLimited(PROVIDER, "quote socket refused every symbol")
        return collected
    finally:
        try:
            connection.close()
        except Exception:  # noqa: BLE001 - closing must never raise
            pass


async def quotes(tickers: list[str], *, timeout: float = 20.0) -> dict[str, dict[str, Any]]:
    """Live prints for several symbols from TradingView's quote socket.

    Args:
        tickers: TradingView symbols, deduplicated and upper-cased here.
        timeout: Overall socket timeout in seconds.

    Returns:
        Each resolved ticker mapped to its value dict, whose keys are
        :data:`QUOTE_FIELDS`. Symbols the upstream refused are absent.

    Raises:
        RateLimited: When TradingView refuses every symbol, which is its
            IP-scoped throttle.
    """
    wanted = sorted({t.strip().upper() for t in tickers if t and t.strip()})
    if not wanted:
        return {}

    paced = limiter(PROVIDER)
    key = "wsquote|" + ",".join(wanted)
    cached = paced.cache_get(key, ttl=5.0)
    if cached is not None:
        return cached

    async def _once() -> dict[str, dict[str, Any]]:
        # The outer ``call`` owns pacing and retry coordination. Waiting here
        # as well would impose the provider's minimum interval twice per call.
        try:
            rows = await run_blocking(_quote_blocking, wanted, timeout)
        except RateLimited:
            raise
        except QuoteSocketError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise QuoteSocketError(f"{type(exc).__name__}: {exc}") from exc
        if any(row.get("lp") is not None for row in rows.values()):
            # Only a real print is reusable. An entirely empty or price-less
            # socket response gets another subscription on the next call.
            paced.cache_set(key, rows)
        return rows

    return await call(PROVIDER, _once)


__all__ = ["QUOTE_FIELDS", "QuoteSocketError", "quotes"]
