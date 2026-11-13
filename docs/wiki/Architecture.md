# Architecture

## Data flow

```
  MCP client
      │  tool call
      ▼
  tools_*.py ──────────────┐
      │                    │  health warnings for the providers used
      │                    ▼
      │              health.MONITOR
      │                    │  cached verdict (no upstream call per request)
      │                    ▼
      │              health_state.json  (baselines + last verdicts)
      │
      ▼
  symbols.resolve()  ──►  one ticker per provider, cached 1 h
      │
      ▼
  reconcile.ask(tv_fn, fv_fn, yh_fn, sa_fn=sa_fn, bb_fn=bb_fn)  ──►  asyncio.gather, never raises
      │
      ├──► tv_access ──► providers/tradingview/native ──► scanner.tradingview.com
      │                                              └──► data.tradingview.com (ws)
      ├──► fv_access ──► providers/finviz ─────────────► finviz.com (HTML + /api/*)
      ├──► yh_access ──► Yahoo chart API ──────────────► query1.finance.yahoo.com
      ├──► sa_access ──► StockAnalysis quote API ─────► stockanalysis.com/api/quotes/s/<t>
      └──► bb_access ──► curl_cffi (TLS impersonation) ► bloomberg.com/quote/<id>

  tools_bloomberg ──► bb_access (same adapter, one provider asked, so single-source)
      │
      │  every request above goes through ratelimit.limiter(PROVIDER)
      ▼
  Pair(tv=Attempt, fv=Attempt, yh=Attempt, sa=Attempt, bb=Attempt)
      │
      ▼
  reconcile.finalize() ──► merge_many() ──► comparisons + per-field fields
                              │  freshness decides which reading resolves
      │
      ▼
  providers_state.envelope()
      │
      ▼
  {data_provider, verification, providers_answered, notice, data, fields,
   comparisons, freshness, resolutions, sources, errors, warnings,
   degraded, generated_at}
```

## Modules

```
src/tapebasis/
├── server.py             FastMCP instance, lifespan, /health, CLI, MCP instructions
├── providers_state.py    DataProvider / Verification enums, error types, envelope()
├── reconcile.py          concurrent fan-out, field comparison, freshness arbitration, notice text
├── freshness.py          market-print timestamps + freshest-print selection
├── sessions.py           which session a print belongs to, and which print is the live one
├── ratelimit.py          per-provider pacing, shared cooldown, TTL cache
├── http_pool.py          one pooled HTTP client and resolver warm-up per upstream
├── singleflight.py       merge identical concurrent work (not a cache)
├── blocking_pool.py      bounded thread pool for blocking provider calls
├── merge_helpers.py      pure payload shapers (raw provider dict → normalised fields)
├── sentiment.py          token-free headline scoring (VADER + finance lexicon)
├── symbols.py            dynamic per-provider symbol resolution, the instrument registry
├── health.py             upstream probes, fingerprints, drift state, background loop
├── tv_access.py          typed access to TradingView's own data
├── fv_access.py          typed access to the Finviz provider
├── yh_access.py          typed access to the Yahoo Finance provider
├── bb_access.py          typed access to bloomberg.com (reconciliation leg, curl_cffi)
├── sa_access.py          typed access to stockanalysis.com (US equities and ETFs)
├── catalog.py            plain-data tool catalogue (providers + comparison strategy)
├── tools_market.py       the 9 multi-source market tools
├── tools_finviz.py       the 7 Finviz-only tools
├── tools_tradingview.py  TradingView-only tools + combined_analysis
├── tools_bloomberg.py    the 2 Bloomberg-only tools (one provider asked)
├── tools_health.py       tapebasis_health + tapebasis_tool_map
└── providers/
    ├── tradingview/      provider layer (scanner, chart ws, TA, backtest, …)
    │   └── native.py     TradingView-only scanner + websocket client
    └── finviz/           provider layer (quote HTML, screener, ownership, …)
```

## Why the layering looks like this

### Multiple independent legs, no proxying

Cross-verification is only meaningful if the sources are independent. So each provider has its own
access module and its own upstream:

| Leg | Access module | Upstream |
| --- | --- | --- |
| TradingView | `tv_access.py` → `providers/tradingview/native.py` | `scanner.tradingview.com` (quotes, screener), `data.tradingview.com` (chart websocket for OHLCV) |
| TradingView (overnight) | `tv_access.py` → `providers/tradingview/quote_socket.py` | `data.tradingview.com` quote websocket; `qsd` deltas merge into the preceding symbol snapshot |
| Yahoo (overnight) | `yh_access.py` | `/v7/finance/quote?overnightPrice=true` with a cookie-bound guest crumb; separate from the chart API |
| Finviz | `fv_access.py` | `finviz.com` HTML pages and `/api/*` JSON islands |
| Yahoo Finance | `yh_access.py` | `query1.finance.yahoo.com/v8/finance/chart` |
| StockAnalysis | `sa_access.py` | `stockanalysis.com/api/quotes/s/<ticker>` |
| Bloomberg | `bb_access.py` | `bloomberg.com/quote/<id>` and `/markets/rates-bonds`, through `curl_cffi` |

An earlier version of this server had TradingView's price come from Yahoo's chart API. That made the
two legs the same upstream wearing different labels: a comparison that could only ever agree. The
legs are now genuinely distinct, and `sources` names the upstream each one actually called.

`native.py` exists because TradingView's scanner and its chart websocket are the only two
TradingView-native interfaces available without a key. Quotes, fundamentals, whole-market screens and
index snapshots come from one scanner POST; OHLCV history, which the scanner does not expose, comes
from the websocket.

### `providers/` is kept as an isolated layer

Provider implementations live under `providers/` with their upstream handling, HTML parsers, retry
logic and rate limiting intact, and their import paths rewritten. Keeping them self-contained means tested
behaviour stays stable and upstream fixes can be carried over independently. The orchestration layer
is the only code that defines the tool contract; it never reaches into provider internals.

Provider code does not import anything from the orchestration layer. That one-way dependency is what
keeps the boundary real rather than decorative. It is why the token-free sentiment fallback lives in
`tools_tradingview.py` and not inside `marketaux_service.py`.

### Bloomberg is an adapter with one difference: a declared delay

`bb_access.py` is a reconciliation adapter. It is passed to `reconcile.ask` like the others,
its label is in `PROVIDER_ORDER`, and its readings appear in `comparisons`. Two things needed handling
rather than exclusion:

- **A declared delay is a comparability boundary.** Its equity and index prints are 15 minutes old by
  design, so a pair that far apart is reported as `not_comparable` with the delay named, and the
  adapter is last in `DEFAULT_ORDER` so a delayed page can never win a freshness tie. Its
  `lastUpdate` is a session sentinel, so `print_time` is derived from the last intraday point and
  refused when that point does not match the quoted price.
- **Its own transport.** It is the only adapter that needs `curl_cffi`: the site gates plain HTTP
  clients on the TLS fingerprint, so it cannot share the `httpx` path the others use. That is also
  why the health monitor has no probe for it.

`tools_bloomberg.py` reuses the same adapter for the case where only Bloomberg is asked, and marks
those responses `cross_checked: false` / `reconciliation_leg: false`. See
[Design Decisions](Design-Decisions) 30.

### StockAnalysis is a plain adapter, with a coverage boundary

`sa_access.py` needs none of Bloomberg's transport work: `stockanalysis.com` answers plain `httpx`
and advertises a 3 s shared cache, which the per-provider limiter absorbs with a short TTL. What it
does need is an honest boundary. The quote API serves US equities and ETFs only and has no search
endpoint, so `symbols.resolve_sa` is a mechanical rule (lowercase the US ticker, a share class as a
dot) plus a stated *not carried* for every instrument class the route would 404 on. A 404/400 from the
route is treated as `NoDataError`, not an outage; only a 401/403 or a 5xx is a provider failure.

Its quote surface is the same consolidated tape Yahoo serves, so the pair is weak corroboration
rather than two independent witnesses. That is documented instead of being presented as extra
coverage, following the Bloomberg precedent.

### `tv_access.py` / `fv_access.py` / `yh_access.py` / `sa_access.py` are adapters, not wrappers

The providers return different shapes for the same concept: Finviz uses
`lastVolume`/`openInterest`/`bidPrice`, Yahoo uses `volume`/`openInterest`/`bid`, TradingView's
scanner uses `close`/`update_time`. The adapters normalise shapes *and* convert provider exceptions
into `ProviderError`. That single conversion point is why `reconcile.py` can promise never to raise:
by the time an exception reaches it, it is already an envelope-ready dict.

They are also where a blocking call is pushed off the event loop. `stock_screener_service.screen_stocks`
is synchronous (pandas + requests); it runs in the dedicated provider thread pool
(`blocking_pool.run`), not the loop's default executor, so a slow screener cannot starve a fast path
that needs a worker. Awaiting it directly raises
`TypeError: object dict can't be used in 'await' expression`, which the reconciler would then record
as a provider outage: a silent demotion to single-source.

### `symbols.py` resolves per provider, and verifies

A hardcoded ticker table cannot keep up, and when a row is missing it produces a *wrong-but-plausible*
ticker that fails six layers later. The resolver instead:

1. Checks the instrument registry first: indices and commodities with provider-specific spellings
   (and names that collide with real equities) carry one row per instrument, one column per
   provider, so `NDX`, `^NDX`, `NASDAQ:NDX` and `NDX:IND` all fold onto one instrument and no leg is
   ever steered to another provider's stock endpoint.
2. Takes an explicit `EXCHANGE:SYMBOL` at face value for that provider.
3. Applies only mechanical conventions that have been confirmed against the live endpoint
   (`XXXYYY` → `XXXYYY=X` when both halves are real currency codes, `BTCUSD` → `BTC-USD`).
4. Falls back to each provider's own symbol search, ranking hits by exact-ticker match, asset class
   and venue preference, with a confidence floor so "something vaguely similar" is never used.
5. **Verifies against the quote endpoint.** TradingView's search offers `OANDA:BTCUSD`; its scanner
   has no row for it. Resolution that stops at search hands the quote path a ticker it cannot quote
   and a real instrument is reported as unavailable.
6. Returns `none` with a reason for instruments a provider genuinely does not carry, never a
   fabricated ticker. Yahoo has no spot-gold pair; `XAUUSD=X` returns HTTP 404.

Results are cached per `(provider, query)` for an hour.

### `reconcile.py` owns the rules

One module decides what "agree" means, what happens on partial failure, what the notice says, and
which reading a field resolves to. If comparison semantics lived in each tool, `stock_quote` and
`market_indices` would drift apart.

It also owns the distinction between a *disagreement* and a *non-comparison*. `compare_values`
accepts observation times plus guards (`max_skew_seconds`, `session_boundary`, `max_age_seconds`);
a session-relative field whose readings cannot be shown to describe the same observation is reported
as `not_comparable` with the reason, rather than as a conflict. `require_all_times` extends the same
principle: if a provider reports no print time at all, the match cannot be *proven*, so it is not
asserted. `not_comparable_reason` covers the remaining case where no timestamp check helps: a field
with no shared definition, such as an FX day change, which is reported from every provider and never
judged.

### `freshness.py` decides *which* number

Resolving to a single value needs a tie-break that is defensible, not arbitrary. `freshness.py`
parses each provider's **print** timestamp, TradingView's `update_time` epoch, Yahoo's
`regularMarketTime` epoch, Finviz's rendered `"Nov 03 • 3:59 PM ET"` and StockAnalysis's `ts` epoch
milliseconds, into UTC and hands the newest one to `reconcile.py`.

Print time, not fetch time: a quote fetched a second ago can still carry yesterday's close, so
ordering by fetch time would select whichever provider answered last, which says nothing about which
price is current. Parsing is deliberately forgiving and returns `None` rather than raising, because a
provider changing its date rendering must degrade to "no freshness arbitration", never to a crash
or a wrong ordering.

### `sessions.py` decides *which print*

Freshness orders the readings a provider sent. It cannot tell that the number a provider sent first
is not the one the market is trading on. `sessions.py` answers that: `market_session()` classifies an
instant into the US equity trading day (04:00 pre-market open, 09:30 regular open, 16:00 close, 20:00
end of after-hours, with 20:00-04:00 as the overnight window), and `live_print()` returns the number
each provider would call current, with the session and the field it was read from.

Each provider publishes the live print under a different name while the obvious field holds the
regular session's value, so the resolution is per provider rather than one rule over a shared field
name. TradingView states its session in `current_session` and its extended print in
`premarket_close`/`postmarket_close`; Yahoo publishes `fulldayPrice` beside a frozen
`regularMarketPrice`; StockAnalysis puts the current extended print in `extended_hours`. The module is
pure, makes no request, and returns a provider's value unchanged when that provider names no session,
so a feed is never credited with a print it did not send.

`current_session()` adds the calendar check needed for a venue block to be called current: its print
must lie in the response clock's current session, including the prior evening's start after midnight.
For overnight comparison, `session_window_start()` derives the print's own 20:00 ET occurrence start,
including the final second before 04:00 ET. `stock_extended_hours` records that start so two prints on
different nights are not treated as the same observation merely because both are named `overnight`.
A closed venue's final print remains readable but has `is_current: false`.

### `ratelimit.py` is one gate per upstream

Every upstream is undocumented and rate-limited by its owner. Each gets a `ProviderLimiter`
with a minimum interval, a concurrency cap, a shared exponential cooldown and a short TTL cache.
Raising retry counts would deepen a block; pacing and a process-wide cooldown are what actually
recover.

The details matter in two places:

- **Yahoo** starts answering `429` after a short burst and stays angry. It runs one request at a time
  1 s apart, with a cooldown that backs off from 5 s to 120 s and decays on success.
- **TradingView's websocket** signals a block as `invalid symbol` or `resolve error`, not `429`. Those
  are treated as rate limiting (they are IP-scoped, not ticker-scoped), so a busy process does not
  report a valid symbol as nonexistent.

The pace is applied once per request. A request body that waits for its turn again after the
limiter already did would spend a whole extra `min_interval` on every call, so the waiting lives in
`call()` only.

### `http_pool.py` is one connection pool per upstream

Pacing bounds how often the process knocks, so there is no reason to throw the connection away in
between. Each upstream gets one `httpx.AsyncClient` (one `curl_cffi` session for Bloomberg) per
event loop, created on first use and closed by the lifespan. Pools are keyed weakly by loop, so a
closed loop's connections go with it and the hermetic suite never inherits one test's socket.

Measured against the live upstreams, the handshake a fresh client paid per request was the largest
single term in a warm response: Yahoo chart 1324-2019 ms versus 62-70 ms reused, TradingView symbol
search 5555 ms versus 80-284 ms, Yahoo symbol search 5508 ms versus 56-61 ms, Bloomberg's page
325-725 ms versus 176 ms. Pooling changed no upstream contract and no pacing value.

The module also warms the resolver at startup (`warm_origins`). On a host whose `/etc/nsswitch.conf`
tries mDNS before DNS, the first `getaddrinfo` of a process costs about 5 s while every later one
costs ~20 ms; paying that on the first tool call makes the first user request 5 s slower than the
second.

### `merge_helpers.py` is pure

Every shaper is a pure `dict → dict` function: no I/O, no clock, no randomness. That makes field
mapping unit-testable without network, and auditable: you can read exactly which raw key becomes
which output field.

### `catalog.py` is plain data

No imports, no side effects. `tapebasis_tool_map` costs nothing to serve, so an agent can inspect
capabilities before spending upstream requests.

## The fan-out contract

```python
async def ask(tv_fn, fv_fn, yh_fn) -> Pair
```

- The provider coroutines run concurrently via `asyncio.gather`.
- A `None` callable is not a failure: it becomes `NOT_ATTEMPTED` ("this provider has no such
  capability"), which is excluded from `errors`.
- Any exception is caught and converted. `ask` **never** raises.
- The slowest provider determines latency; a fast failure does not cancel the other legs.

Tools pass `None` where a provider genuinely cannot contribute: `market_snapshot` passes `None` for
Finviz (no breadth), `stock_screener` passes `None` for Yahoo (no screener endpoint), and the backtests
pass `None` for Finviz (no OHLCV history).

## Four ways a response is built

| Entry point | When | Result |
| --- | --- | --- |
| `finalize(pair, specs=...)` | Several providers *could* answer | Field-by-field comparison, one value per field from the newest print |
| `finalize(pair, data=... provider=...)` | Tool composes a richer payload than the field list | Same envelope, custom payload + explicit label |
| `compare_values(...)` inside a tool | Comparison is per-row or per-symbol | A comparison block embedded in the payload |
| `single(provider, value)` | Only one provider serves this capability at all | That provider's label, other legs `NOT_ATTEMPTED` |

One tool needs two sequential `ask` calls because one provider's answer defines the universe the
other is asked about: `stock_screener` (TradingView ranks, Finviz is then asked about exactly those
tickers). Every other fan-out is a single round of parallel calls.

## Health monitor lifecycle

`MONITOR.ensure_started()` is called lazily from each tool. This is deliberate: FastMCP's
streamable-HTTP app builds its own lifespan and ignores `lifespan=`, so a lifespan-only start would
silently never run under HTTP. Lazy start works on both transports.

Tool calls only **read** the cached verdict, so a health probe never adds latency to a data call.

## Concurrency and blocking I/O

The provider layer contains both sync and async code paths. Anything sync is pushed to a worker
thread in a dedicated bounded pool (`blocking_pool.run`, `TAPEBASIS_BLOCKING_THREADS`), so a blocking
pandas/requests scraper or backtest computation cannot stall the event loop for other in-flight tool
calls, and cannot occupy every thread of the loop's default executor either.

Three pieces keep a fan-out from paying for the same work twice. Each upstream gets one pooled HTTP
client per event loop (`http_pool.py`). Identical requests that arrive in the same instant are merged
by `singleflight.py`, so five identical `stock_quote` calls make one Yahoo request rather than five
serialised behind `max_inflight=1`. And the `asyncio` primitives behind pacing are created per event
loop, keyed weakly by the loop, because a semaphore built at import time binds to the first loop that
contends it.

## Related

- [Response Contract](Response-Contract): the output shape
- [Health Monitor](Health-Monitor): probes and drift detection
- [Design Decisions](Design-Decisions): the reasoning behind non-obvious choices
