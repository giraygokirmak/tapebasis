"""Upstream health and schema-drift monitor.

Every provider scrapes or calls an undocumented upstream (finviz.com's HTML
and unversioned JSON islands, TradingView's scanner and symbol search, Yahoo's
chart API, stockanalysis.com's quote API). Any of them can change a path, a
JSON key or a status code without notice. When that happens, tools start
failing or silently returning zeros.

This module probes each upstream directly, independently of the provider code
paths, and classifies the result:

``OK``        HTTP status and payload shape match the recorded baseline.
``DRIFT``     The upstream answered, but the status/shape no longer matches the
              baseline (renamed field, moved route, changed marker). Data may
              still be served, but every response warns about it.
``DOWN``      Timeout, connection error or 5xx. The provider is unavailable.
``UNKNOWN``   Not probed yet (process just started).

The monitor runs in the background at a fixed interval and caches results, so
tool calls only read memory. :func:`tapebasis_health` forces a fresh probe.

Baselines are persisted to a JSON file so drift is detected *across restarts*:
the first successful probe records the shape, later probes compare against it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

import httpx

TRADINGVIEW = "TRADINGVIEW"
FINVIZ = "FINVIZ"
YAHOO = "YAHOO"
SA = "SA"

#: Every provider the monitor probes, in display order.
PROVIDERS: tuple[str, ...] = (TRADINGVIEW, FINVIZ, YAHOO, SA)

STATUS_OK = "OK"
STATUS_DRIFT = "DRIFT"
STATUS_DOWN = "DOWN"
STATUS_UNKNOWN = "UNKNOWN"

DEFAULT_INTERVAL = float(os.environ.get("TAPEBASIS_HEALTH_INTERVAL", "300"))
DEFAULT_TTL = float(os.environ.get("TAPEBASIS_HEALTH_TTL", "60"))
PROBE_TIMEOUT = float(os.environ.get("TAPEBASIS_HEALTH_TIMEOUT", "12"))
DEFAULT_STATE_PATH = os.path.join(
    os.path.expanduser("~"), ".tapebasis", "health_state.json"
)


def state_path() -> str:
    """Resolve the baseline file each time.

    Read dynamically (not at import) so a deployment can point
    ``TAPEBASIS_HEALTH_STATE`` at a mounted volume, and so tests never touch
    the real home directory.
    """
    return os.environ.get("TAPEBASIS_HEALTH_STATE") or DEFAULT_STATE_PATH

#: Chrome UA that finviz.com serves without a challenge.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)


# ── Schema fingerprints ──────────────────────────────────────────────────────


def key_paths(payload: Any, *, limit: int = 200) -> list[str]:
    """Stable, sorted list of dotted key paths in a JSON payload."""
    found: set[str] = set()

    def walk(node: Any, prefix: str) -> None:
        if len(found) >= limit:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                found.add(path)
                walk(value, path)
        elif isinstance(node, list):
            if node:
                walk(node[0], f"{prefix}[]")

    walk(payload, "")
    return sorted(found)[:limit]


def fingerprint(paths: Iterable[str]) -> str:
    joined = "\n".join(sorted(paths))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


@dataclass
class Probe:
    """One independent check of one upstream endpoint."""

    id: str
    provider: str
    description: str
    url: str
    method: str = "GET"
    #: Markers that must appear in the response body (HTML probes).
    markers: tuple[str, ...] = ()
    #: Dotted keys that must exist in the decoded JSON (JSON probes).
    required_keys: tuple[str, ...] = ()
    json_body: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    #: Only these HTTP statuses count as healthy.
    expect_status: tuple[int, ...] = (200,)


def _has_key(payload: Any, dotted: str) -> bool:
    """True when a dotted path exists, supporting list indices (``data.0.d``).

    ``[]`` means "first element of the list" and a bare integer is a list
    index, so a probe can assert on ``data.0.d`` for a scanner response whose
    ``data`` member is an array.
    """
    current = payload
    for part in dotted.split("."):
        if isinstance(current, dict):
            if part not in current:
                return False
            current = current[part]
        elif isinstance(current, list):
            if part == "[]":
                if not current:
                    return False
                current = current[0]
            elif part.lstrip("-").isdigit():
                index = int(part)
                if not -len(current) <= index < len(current):
                    return False
                current = current[index]
            else:
                return False
        else:
            return False
    return True


def _probes() -> list[Probe]:
    """The upstream contract this server depends on.

    Each probe maps to a concrete place in the provider code:
    ``finviz.core.services.finviz_client`` / ``quote_service`` /
    ``market_service``, ``providers.tradingview.native`` (scanner + chart
    websocket), ``yh_access`` (Yahoo chart API), ``sa_access`` (StockAnalysis
    quote API) and ``bb_access`` (Bloomberg, which has no probe because it gates
    on the TLS fingerprint: an httpx probe there would report a false outage).

    A probe must exercise the endpoint the provider code actually uses, on the
    provider that uses it. Yahoo used to be probed under TRADINGVIEW because the
    TradingView leg proxied it; that hid a whole provider outage, so it is now
    its own row.
    """
    return [
        # ── Finviz ──────────────────────────────────────────────────────────
        Probe(
            id="finviz.indices_api",
            provider=FINVIZ,
            description="finviz.com /api/indices_data JSON island",
            url="https://finviz.com/api/indices_data",
            headers={"User-Agent": BROWSER_UA, "Accept": "application/json, text/plain, */*"},
            required_keys=("DJI", "SPX", "COMP"),
        ),
        Probe(
            id="finviz.quote_html",
            provider=FINVIZ,
            description="finviz.com /stock?t=AAPL rendered snapshot table",
            url="https://finviz.com/stock?t=AAPL&ta=1&p=d",
            headers={"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml"},
            # Every marker is a field the server now serves, not just page
            # scaffolding: the snapshot table, the classification chips (sector /
            # industry / country / exchange) and the revenue-breakdown island.
            markers=(
                "js-snapshot-table",
                "quote-header_category",
                "income-breakdown-init-data",
            ),
        ),
        Probe(
            id="finviz.news_api",
            provider=FINVIZ,
            description="finviz.com /api/news/quote/AAPL news island",
            url="https://finviz.com/api/news/quote/AAPL",
            headers={"User-Agent": BROWSER_UA, "Accept": "application/json, text/plain, */*"},
            required_keys=("html",),
        ),
        # ── TradingView (native) ────────────────────────────────────────────
        Probe(
            id="tradingview.scanner_api",
            provider=TRADINGVIEW,
            description="scanner.tradingview.com global scan (quotes/fundamentals)",
            url="https://scanner.tradingview.com/global/scan",
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": BROWSER_UA},
            json_body={
                "symbols": {"tickers": ["OANDA:XAUUSD", "NASDAQ:AAPL"]},
                "columns": ["name", "close", "change", "update_time"],
            },
            required_keys=("totalCount", "data.0.d"),
        ),
        Probe(
            id="tradingview.symbol_search",
            provider=TRADINGVIEW,
            description="symbol-search.tradingview.com v3 (dynamic symbol resolution)",
            url=(
                "https://symbol-search.tradingview.com/symbol_search/v3/"
                "?text=XAUUSD&hl=1&exchange=&lang=en&search_type=&domain=production&sort_by_country=US"
            ),
            headers={"User-Agent": BROWSER_UA, "Origin": "https://www.tradingview.com"},
            required_keys=("symbols",),
        ),
        # ── Yahoo Finance ───────────────────────────────────────────────────
        Probe(
            id="yahoo.chart_api",
            provider=YAHOO,
            description="query1.finance.yahoo.com chart API (quotes/OHLCV)",
            url="https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=5d",
            headers={"User-Agent": BROWSER_UA, "Accept": "application/json"},
            required_keys=("chart.result.0.meta", "chart.result.0.timestamp"),
        ),
        Probe(
            id="yahoo.chart_fx",
            provider=YAHOO,
            description="Yahoo chart API for an FX pair (the EURUSD=X resolution path)",
            url="https://query1.finance.yahoo.com/v8/finance/chart/EURUSD%3DX?interval=1d&range=5d",
            headers={"User-Agent": BROWSER_UA, "Accept": "application/json"},
            required_keys=("chart.result.0.meta", "chart.result.0.timestamp"),
        ),
        Probe(
            id="yahoo.chart_crypto",
            provider=YAHOO,
            description="Yahoo chart API for a crypto pair (the BTC-USD resolution path)",
            url="https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?interval=1d&range=5d",
            headers={"User-Agent": BROWSER_UA, "Accept": "application/json"},
            required_keys=("chart.result.0.meta", "chart.result.0.timestamp"),
        ),
        # ── StockAnalysis ───────────────────────────────────────────────────
        Probe(
            id="sa.quote_api",
            provider=SA,
            description="stockanalysis.com quote API (US equities and ETFs)",
            url="https://stockanalysis.com/api/quotes/s/aapl",
            headers={"User-Agent": BROWSER_UA, "Accept": "application/json"},
            # ``data.p`` is the price field every shaped reading is built from:
            # if the route moves or the envelope is renamed, this fires instead
            # of the leg silently reporting "no price" forever. The sibling
            # ``status`` is an HTTP-style integer, so it is not part of the path.
            required_keys=("data.p",),
        ),
    ]


# ── Result model ─────────────────────────────────────────────────────────────


@dataclass
class ProbeResult:
    id: str
    provider: str
    description: str
    url: str
    status: str = STATUS_UNKNOWN
    http_status: int | None = None
    latency_ms: float | None = None
    checked_at: float | None = None
    message: str = ""
    missing: list[str] = field(default_factory=list)
    shape_hash: str | None = None
    baseline_hash: str | None = None
    drift: bool = False
    down: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.checked_at:
            payload["checked_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.checked_at)
            )
        return payload


def _load_state() -> dict[str, Any]:
    try:
        with open(state_path(), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    path = state_path()
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        # Health bookkeeping must never take the server down.
        pass


class HealthMonitor:
    """Runs the probes, tracks drift, and exposes a cached summary."""

    def __init__(self, probes: Iterable[Probe] | None = None) -> None:
        self.probes = list(probes if probes is not None else _probes())
        self.results: dict[str, ProbeResult] = {}
        self._state = _load_state()
        self._last_run: float = 0.0
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.interval = DEFAULT_INTERVAL
        self.ttl = DEFAULT_TTL
        self.enabled = os.environ.get("TAPEBASIS_HEALTH_ENABLED", "true").lower() != "false"

    # ── baseline ────────────────────────────────────────────────────────────
    def _baseline(self, probe_id: str) -> dict[str, Any] | None:
        return self._state.get("baselines", {}).get(probe_id)

    def _record_baseline(self, probe_id: str, shape_hash: str, keys: list[str]) -> None:
        self._state.setdefault("baselines", {})[probe_id] = {
            "shape_hash": shape_hash,
            "keys": keys,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _save_state(self._state)

    # ── probing ─────────────────────────────────────────────────────────────
    async def _probe(self, probe: Probe, client: httpx.AsyncClient) -> ProbeResult:
        result = ProbeResult(
            id=probe.id,
            provider=probe.provider,
            description=probe.description,
            url=probe.url,
        )
        started = time.monotonic()
        try:
            response = await client.request(
                probe.method,
                probe.url,
                headers=probe.headers,
                json=probe.json_body,
                timeout=PROBE_TIMEOUT,
                follow_redirects=True,
            )
            result.latency_ms = round((time.monotonic() - started) * 1000, 1)
            result.http_status = response.status_code
            result.checked_at = time.time()
        except Exception as exc:  # noqa: BLE001 - probe failures are data
            result.status = STATUS_DOWN
            result.down = True
            result.message = f"{type(exc).__name__}: {exc}"
            result.checked_at = time.time()
            return result

        if response.status_code not in probe.expect_status:
            result.status = STATUS_DOWN
            result.down = True
            result.message = (
                f"HTTP {response.status_code} (expected {probe.expect_status}); "
                "the endpoint may have moved"
            )
            return result

        body = response.text

        # HTML marker probes
        if probe.markers:
            missing = [m for m in probe.markers if m not in body]
            result.missing = missing
            if missing:
                result.status = STATUS_DRIFT
                result.drift = True
                result.message = (
                    "response no longer contains "
                    + ", ".join(repr(m) for m in missing)
                    + ": finviz likely changed the page markup"
                )
            else:
                result.status = STATUS_OK
            return result

        # JSON shape probes
        try:
            payload = response.json()
        except ValueError:
            result.status = STATUS_DRIFT
            result.drift = True
            result.message = "response is no longer valid JSON; the endpoint may have moved"
            return result

        missing = [key for key in probe.required_keys if not _has_key(payload, key)]
        result.missing = missing
        keys = key_paths(payload)
        result.shape_hash = fingerprint(keys)

        baseline = self._baseline(probe.id)
        result.baseline_hash = baseline["shape_hash"] if baseline else None

        if missing:
            result.status = STATUS_DRIFT
            result.drift = True
            result.message = (
                "missing expected key(s) "
                + ", ".join(repr(k) for k in missing)
                + ": upstream API/schema changed"
            )
            return result

        if baseline is None:
            self._record_baseline(probe.id, result.shape_hash, keys)
            result.status = STATUS_OK
            result.message = "baseline recorded"
            return result

        if baseline["shape_hash"] != result.shape_hash:
            added = sorted(set(keys) - set(baseline.get("keys", [])))
            removed = sorted(set(baseline.get("keys", [])) - set(keys))
            result.status = STATUS_DRIFT
            result.drift = True
            detail = []
            if removed:
                detail.append(f"removed: {', '.join(removed[:6])}")
            if added:
                detail.append(f"added: {', '.join(added[:6])}")
            result.message = (
                "payload shape changed since baseline"
                + (f" ({'; '.join(detail)})" if detail else "")
                + ": upstream schema drifted"
            )
            return result

        result.status = STATUS_OK
        return result

    async def run_once(self, *, force: bool = False) -> dict[str, ProbeResult]:
        """Probe every endpoint once (serialised; concurrent callers share)."""
        async with self._lock:
            if not force and (time.monotonic() - self._last_run) < self.ttl:
                return dict(self.results)
            async with httpx.AsyncClient(http2=False) as client:
                results = await asyncio.gather(
                    *(self._probe(probe, client) for probe in self.probes)
                )
            self.results = {r.id: r for r in results}
            self._last_run = time.monotonic()
            self._state["last_run"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )
            _save_state(self._state)
            return dict(self.results)

    # ── background loop ─────────────────────────────────────────────────────
    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="tapebasis-health")

    def ensure_started(self) -> None:
        """Start the background loop if it is not running and a loop exists.

        FastMCP's streamable-HTTP app hardcodes its own Starlette lifespan
        (``lambda app: self.session_manager.run()``), so an ``lifespan=`` passed
        to :class:`FastMCP` is silently ignored on that transport. Without this,
        the monitor would never start in the Docker/HTTP deployment. Tool calls
        and the ``/health`` route are all inside the event loop, so they can
        start it on first use.

        Safe to call repeatedly, and a no-op outside a running loop or when the
        monitor is disabled.
        """
        if self._task is not None or not self.enabled:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._loop(), name="tapebasis-health")

    async def _loop(self) -> None:
        # First pass early so the first user request already sees a verdict.
        await asyncio.sleep(2)
        while True:
            try:
                await self.run_once(force=True)
            except Exception:  # noqa: BLE001 - keep the loop alive
                pass
            await asyncio.sleep(self.interval)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    # ── read side ───────────────────────────────────────────────────────────
    def stale(self) -> bool:
        return not self.results or (time.monotonic() - self._last_run) > self.interval

    def provider_status(self, provider: str) -> str:
        rows = [r for r in self.results.values() if r.provider == provider]
        if not rows:
            return STATUS_UNKNOWN
        if any(r.status == STATUS_DOWN for r in rows):
            return STATUS_DOWN
        if any(r.status == STATUS_DRIFT for r in rows):
            return STATUS_DRIFT
        return STATUS_OK

    def degraded(self) -> bool:
        return any(r.status in (STATUS_DRIFT, STATUS_DOWN) for r in self.results.values())

    def issues(self) -> list[dict[str, Any]]:
        """Drift/down events, newest upstream change first."""
        rows = [r for r in self.results.values() if r.status in (STATUS_DRIFT, STATUS_DOWN)]
        rows.sort(key=lambda r: (r.status != STATUS_DRIFT, r.id))
        return [
            {
                "provider": r.provider,
                "probe": r.id,
                "status": r.status,
                "url": r.url,
                "message": r.message,
                "missing": r.missing,
                "http_status": r.http_status,
            }
            for r in rows
        ]

    def warnings_for(self, providers: Iterable[str]) -> list[str]:
        self.ensure_started()
        wanted = {str(p).upper() for p in providers}
        # ``ALL`` in a scoped call means "every provider this response touched";
        # it must not silently widen to providers that were not asked.
        wildcard = not wanted or "ALL" in wanted
        return [
            f"{issue['provider']} health {issue['status']} on {issue['probe']}: {issue['message']}"
            for issue in self.issues()
            if wildcard or issue["provider"] in wanted
        ]

    def summary(self) -> dict[str, Any]:
        self.ensure_started()
        from .ratelimit import snapshot as limiter_snapshot

        try:
            limiters = limiter_snapshot()
        except Exception:  # noqa: BLE001 - health must never fail the call
            limiters = {}
        return {
            "providers": {
                provider: self.provider_status(provider) for provider in PROVIDERS
            },
            "degraded": self.degraded(),
            "issues": self.issues(),
            "probes": [r.to_dict() for r in self.results.values()],
            # Per-provider pacing/cooldown state. A provider that is OK but
            # cooling down is still serving slowly, and an agent needs to know
            # that before it retries.
            "rate_limits": limiters,
            "last_run_epoch": self._last_run or None,
            "state_path": state_path(),
            "interval_seconds": self.interval,
            "monitor_running": self._task is not None and not self._task.done(),
        }


#: Process-wide monitor. ``server.py`` starts it; tools read from it.
MONITOR = HealthMonitor()
