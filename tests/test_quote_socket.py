"""TradingView quote frames are deltas, not replacement snapshots."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from tapebasis.providers.tradingview import quote_socket


class _Socket:
    """Return prepared frames and record connection timeouts."""

    def __init__(self, frames):
        self.frames = iter(frames)
        self.timeouts = []

    def send(self, _frame):
        """Accept subscription frames and heartbeat echoes."""

    def settimeout(self, timeout):
        """Record a receive timeout without opening a real socket."""
        self.timeouts.append(timeout)

    def recv(self):
        """Supply the next frame, then simulate a quiet connection."""
        try:
            return next(self.frames)
        except StopIteration:
            raise TimeoutError("quiet")

    def close(self):
        """Release this fake connection."""


def _frame(method: str, name: str, values: dict) -> str:
    """Create a raw TradingView frame, optionally missing snapshot keys."""
    payload = {"m": method, "p": ["session", {"n": name, "s": "ok", "v": values}]}
    encoded = json.dumps(payload)
    return f"~m~{len(encoded)}~m~{encoded}"


def test_qsd_deltas_retain_previous_values_on_both_receive_paths(monkeypatch):
    """A partial update cannot delete a price already received for the symbol."""
    full = {
        "lp": 166.58, "lp_time": 1794560399, "volume": 1200,
        "current_session": "out_of_session", "update_mode": "streaming",
    }
    socket = _Socket([
        _frame("qsd", "BOATS:NVDA", full),
        _frame("qsd", "BOATS:NVDA", {"lp_time": 1794560400}),
        _frame("qsd", "BOATS:NVDA", {"currency": "USD"}),
    ])
    monkeypatch.setitem(sys.modules, "websocket", SimpleNamespace(
        create_connection=lambda *args, **kwargs: socket,
    ))

    rows = quote_socket._quote_blocking(["BOATS:NVDA"], timeout=20)

    assert rows["BOATS:NVDA"]["lp"] == pytest.approx(166.58)
    assert rows["BOATS:NVDA"]["lp_time"] == 1794560400
    assert rows["BOATS:NVDA"]["volume"] == 1200
    assert rows["BOATS:NVDA"]["current_session"] == "out_of_session"
    assert rows["BOATS:NVDA"]["update_mode"] == "streaming"
    assert rows["BOATS:NVDA"]["currency"] == "USD"


def test_qsd_settle_update_preserves_the_initial_snapshot(monkeypatch):
    """The settle window after all symbols answered follows the same merge rule."""
    socket = _Socket([
        _frame("qsd", "BOATS:NVDA", {"lp": 166.58, "volume": 1200}),
        _frame("qsd", "BOATS:NVDA", {"lp": 166.59}),
        _frame("qsd", "BOATS:BRK.B", {"lp": 5.0}),
    ])
    monkeypatch.setitem(sys.modules, "websocket", SimpleNamespace(
        create_connection=lambda *args, **kwargs: socket,
    ))

    rows = quote_socket._quote_blocking(["BOATS:NVDA"], timeout=20)

    assert rows["BOATS:NVDA"] == {"lp": 166.59, "volume": 1200}


@pytest.mark.asyncio
async def test_empty_quote_result_is_not_cached(monkeypatch):
    """A quiet socket retries on a later call instead of caching no data."""
    paced = quote_socket.limiter(quote_socket.PROVIDER)
    paced.cache_clear()
    monkeypatch.setattr(paced, "_cooldown_until", 0)
    key = "wsquote|BOATS:NVDA"
    calls = 0

    async def empty(*args):
        nonlocal calls
        calls += 1
        return {}

    async def no_wait():
        return None
    monkeypatch.setattr(quote_socket, "run_blocking", empty)
    monkeypatch.setattr(paced, "wait_turn", no_wait)
    assert await quote_socket.quotes(["BOATS:NVDA"]) == {}
    assert paced.cache_get(key, ttl=5.0) is None
    assert calls == 1


@pytest.mark.asyncio
async def test_limiter_exhaustion_becomes_visible_rate_limit(
    monkeypatch, _isolate_extended_session_upstreams
):
    """The overnight collector sees a typed failure, not an escaping exception."""
    from tapebasis import tv_access
    from tapebasis.ratelimit import RateLimitError
    from tapebasis.providers_state import ProviderError

    async def limited(*_args, **_kwargs):
        raise RateLimitError("TRADINGVIEW", 5)

    monkeypatch.setattr(quote_socket, "quotes", limited)
    monkeypatch.setattr(
        tv_access,
        "live_session_quotes",
        _isolate_extended_session_upstreams[1],
    )
    with pytest.raises(ProviderError) as exc:
        await tv_access.live_session_quotes(["BOATS:NVDA"])
    assert exc.value.code == "UPSTREAM_RATE_LIMIT"


def test_websocket_timeout_is_a_quiet_read_not_a_transport_failure(monkeypatch):
    """The websocket client's own timeout type retains the first print."""
    class WebSocketTimeoutException(Exception):
        pass

    class TimeoutSocket(_Socket):
        def recv(self):
            try:
                return super().recv()
            except TimeoutError as exc:
                raise WebSocketTimeoutException("quiet") from exc

    socket = TimeoutSocket([_frame("qsd", "BOATS:NVDA", {"lp": 166.58})])
    monkeypatch.setitem(sys.modules, "websocket", SimpleNamespace(
        create_connection=lambda *args, **kwargs: socket,
        WebSocketTimeoutException=WebSocketTimeoutException,
    ))

    assert quote_socket._quote_blocking(["BOATS:NVDA"], timeout=20)["BOATS:NVDA"]["lp"] == 166.58


def test_os_error_is_not_silently_rewritten_as_no_data(monkeypatch):
    """A failed receive stays distinguishable from a quiet timeout."""
    class FailingSocket(_Socket):
        def recv(self):
            raise OSError("connection reset")

    socket = FailingSocket([])
    monkeypatch.setitem(sys.modules, "websocket", SimpleNamespace(
        create_connection=lambda *args, **kwargs: socket,
    ))
    with pytest.raises(quote_socket.QuoteSocketError, match="connection reset"):
        quote_socket._quote_blocking(["BOATS:NVDA"], timeout=20)


def test_receive_timeout_is_bounded_by_the_overall_deadline(monkeypatch):
    """The first receive uses the remaining budget, not unlimited retries."""
    clock = iter([0.0, 0.0, 10.0])
    monkeypatch.setattr(quote_socket.time, "monotonic", lambda: next(clock))
    socket = _Socket([])
    monkeypatch.setitem(sys.modules, "websocket", SimpleNamespace(
        create_connection=lambda *args, **kwargs: socket,
    ))
    assert quote_socket._quote_blocking(["BOATS:NVDA"], timeout=10) == {}
    assert socket.timeouts == [10.0]


def test_closed_socket_before_a_print_is_a_visible_error(monkeypatch):
    """An empty receive is EOF, not a legitimate no-print observation."""
    socket = _Socket([""])
    monkeypatch.setitem(sys.modules, "websocket", SimpleNamespace(
        create_connection=lambda *args, **kwargs: socket,
    ))
    with pytest.raises(quote_socket.QuoteSocketError, match="closed before"):
        quote_socket._quote_blocking(["BOATS:NVDA"], timeout=20)
