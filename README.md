<div align="center">

<img src="docs/logo.svg" alt="Tapebasis" width="360">

**Multiple tapes, one basis.** An MCP server that serves **TradingView**, **Finviz**, **Yahoo Finance**
and **Bloomberg** market data together, cross-checks every overlapping figure, and labels each
response with the provider that actually produced it.

</div>

---

*Basis* is the finance term for the price difference between two markets quoting the same asset.
*Tape* is the ticker tape. Tapebasis is the spread between multiple feeds, measured on every call:
zero when they agree, reported when they don't.

The point is redundancy you can *see*. Every provider that could answer a field is asked, natively
in parallel. When several answer, the data is cross-checked. When only one answers, you get the data,
clearly marked as single-source. When none answers, you get `NONE` instead of a
plausible-looking number. And because every provider scrapes or calls an undocumented upstream, a
background monitor probes every endpoint and reports API/schema drift inside ordinary tool responses.

Each provider is fetched natively: TradingView's own scanner and chart websocket, Finviz's HTML and
JSON islands, Yahoo's chart API, Bloomberg's quote pages. No leg proxies another: a provider that
quietly forwards a competitor's numbers is worthless as a cross-check.

Bloomberg is the fourth leg and it is asked like the others, in parallel, on the same call. Two of its
properties are reported rather than hidden by a tolerance. Its equity and index prints are
exchange-delayed (`exchangeDelay` is `15 Minutes`), so a pair of prints further apart than the
print-time guard allows is reported as **not comparable** with the delay named, instead of being
called a provider disagreement; it also never wins the freshness tie-break against a live print. And
its static fields are penny-identical to Yahoo's, so agreement between those two is weak corroboration,
not two independent witnesses. What it adds is its own quote pages and the
[government benchmark yield curve](#bloomberg-only-tools-labelled-bloomberg-single-source-by-construction),
which no other provider here publishes.

[![Tests](https://github.com/giraygokirmak/tapebasis/actions/workflows/test.yml/badge.svg)](https://github.com/giraygokirmak/tapebasis/actions/workflows/test.yml)
[![Python 3.10–3.13](https://img.shields.io/badge/python-3.10%E2%80%933.13-3776ab)](https://github.com/giraygokirmak/tapebasis)
[![License: MIT](https://img.shields.io/badge/license-MIT-5eead4)](LICENSE)

---

## The `data_provider` contract

Every tool result carries exactly one of six values. It states **coverage**, never agreement:

| Value         | Meaning                                                                    |
| ------------- | -------------------------------------------------------------------------- |
| `ALL`         | Every provider that was asked answered. Coverage is complete for this call. |
| `TRADINGVIEW` | Only TradingView answered. Served, but **not** corroborated.               |
| `FINVIZ`      | Only Finviz answered. Served, but **not** corroborated.                    |
| `YAHOO`       | Only Yahoo Finance answered. Served, but **not** corroborated.             |
| `BLOOMBERG`   | Only Bloomberg answered. Served, but **not** corroborated; its quote can be delayed. |
| `NONE`        | No provider could supply it. No value is presented.                        |

`ALL` means "every provider asked answered", not "they agree". Agreement is a separate axis, and it
lives in `comparisons[].match`. A partial response is still `ALL`; `providers_answered` names
exactly which providers contributed.

The same envelope also contains:

```jsonc
{
  "data_provider": "ALL",
  "verification": "MULTI_SOURCE",        // MULTI_SOURCE | SINGLE_SOURCE | UNAVAILABLE
  "providers_answered": ["TRADINGVIEW", "FINVIZ", "YAHOO"],   // + "BLOOMBERG" when it answers
  "notice": "Every provider asked answered (TradingView, Finviz and Yahoo Finance). ...",
  "data": { ... },                       // the reconciled payload, one value per field
  "fields": { "price": "ALL", "peers": "FINVIZ" },   // per-field provenance
  "freshness": {                         // why `data` holds the value it does
    "tradingview": "2026-11-04T00:59:53+00:00",
    "finviz": "2026-11-04T10:42:00+00:00",
    "yahoo": "2026-11-03T21:00:01+00:00",
    "bloomberg": "2026-11-04T10:27:00+00:00",   // 15 min behind, so it cannot win
    "chosen": "FINVIZ",
    "decision": "newest",                // newest | tie | no_timestamp
    "newest_print": "2026-11-04T10:42:00+00:00",
    "reason": "FINVIZ printed most recently (2026-11-04T10:42:00+00:00)"
  },
  "comparisons": [                       // the actual side-by-side numbers
    { "field": "price",
      "values": { "TRADINGVIEW": 331.9, "FINVIZ": 332.33, "YAHOO": 331.9 },
      "match": true, "diff_pct": 0.1294, "tolerance_pct": 0.5,
      "pairs": [ { "between": ["TRADINGVIEW", "FINVIZ"], "match": true, "diff_pct": 0.1294 }, ... ],
      "chosen": "FINVIZ" }
  ],
  "resolutions": { "TRADINGVIEW": { "symbol": "NASDAQ:AAPL", ... }, ... },
  "sources": { "TRADINGVIEW": "scanner.tradingview.com", "FINVIZ": "...", "YAHOO": "..." },
  "errors": [ { "provider": "FINVIZ", "code": "...", "message": "..." } ],
  "warnings": [ "..." ],
  "degraded": false,                     // true when the health monitor saw drift/downtime
  "generated_at": "2026-11-04T10:43:02+00:00"
}
```

**One price, and it is the newest print.** Every provider that can supply a field is asked. `data`
holds exactly one value per compared field: the reading whose market print is newest. Providers that
share the newest instant are the only tie-break candidates, and the documented default order
(`FINVIZ`, `TRADINGVIEW`, `YAHOO`, `BLOOMBERG`) picks between them; Bloomberg is last precisely
because its print can be structurally older. `freshness.decision` is the machine-readable
outcome (`newest`, `tie`, `no_timestamp`), so a caller never has to parse the sentence in `reason`.
Every original reading stays in `comparisons.values`.

**Disagreements are never silently resolved.** If the providers report different prices, all values
stay in `comparisons`, the field is named in `notice` and `warnings`, and `data_provider` stays `ALL`
(every asked provider *did* answer; they just disagree). The single value in `data` is the newest
print, and the notice says so.

**A field measured against a session baseline is not compared across observations.** A day-change
percentage or a session volume is derived from the previous close of the session the print belongs
to. Finviz in a pre-market session and Yahoo at the prior close will legitimately differ, so such a
pair is reported as `not_comparable` (with the reason in `pairs[].not_comparable`) instead of being
called a provider conflict. Four guards decide that: a 900 s print-time ceiling, equality of the
US/Eastern session date even when the prints are seconds apart, a declared feed delay as a boundary
of its own (Bloomberg states 15 minutes on equities, so its pairs stop being comparable at that
distance), and, for the fields re-derived from the print, an 8 h age ceiling against the clock so a
feed that froze with its peers cannot pass. Both readings still appear; the field is listed in
`warnings` as not cross-checked.

**Some fields have no shared definition at all.** Spot FX has no single official previous close, so
each provider derives its own daily roll and the day-change figures answer different questions. On
FX, `change_percent` is therefore always reported from every provider but never compared, with that
reason in the pair. Instrument-level, not provider-level: no tolerance can make it a conflict.

Implementation: [`reconcile.py`](src/tapebasis/reconcile.py) (fan-out + comparison),
[`freshness.py`](src/tapebasis/freshness.py) (print-time parsing),
[`providers_state.py`](src/tapebasis/providers_state.py) (envelope + labels).

---

## Symbols are resolved per provider

The same instrument is spelled differently by each upstream, and the differences are not mechanical:

| Instrument | TradingView | Finviz | Yahoo Finance |
| --- | --- | --- | --- |
| Apple | `NASDAQ:AAPL` | `AAPL` | `AAPL` |
| Gold (spot) | `OANDA:XAUUSD` | *(not carried)* | *(not carried, `XAUUSD=X` is a 404)* |
| S&P 500 | `SP:SPX` | *(indices feed only)* | `^GSPC` |
| EUR/USD | `FX:EURUSD` | *(not carried)* | `EURUSD=X` |
| Bitcoin | `BITSTAMP:BTCUSD` | *(not carried)* | `BTC-USD` |

[`symbols.py`](src/tapebasis/symbols.py) resolves each query per provider, caches the answer for an
hour, and records how it was derived in `resolutions` (`explicit`, `alias`, `search`, `none`). Two
rules keep it honest:

- **A ticker is only returned if the provider can actually quote it.** TradingView's symbol *search*
  offers `OANDA:BTCUSD`, but its *scanner* has no row for it, resolution verifies against the
  scanner and picks `BITSTAMP:BTCUSD` instead.
- **A missing instrument is not an outage.** `NotApplicable` becomes `NOT_ATTEMPTED`, which is
  excluded from `errors`. "Finviz does not carry spot gold" is a structural fact, not a failure.

XAUUSD, for example, resolves to `OANDA:XAUUSD` for TradingView, `XAUUSD:CUR` for Bloomberg and
nothing for the other two, so the response is `ALL` over the two that answered, served and clearly
labelled, not hidden.

---

## Tools (35)

### Multi-source, every capable provider asked, answers compared

| Tool | Providers | Fields cross-checked |
| --- | --- | --- |
| `stock_quote` | all four | price, change %, previous close, volume, session open/high/low, 52-w high/low, P/E, RSI(14) |
| `stock_prices` | all | price and change % per ticker (per-row `data_provider`) |
| `stock_screener` | TradingView + Finviz | per-row price for the tickers both return |
| `market_indices` | all | S&P 500, Dow, Nasdaq Composite, Russell 2000, VIX levels |
| `stock_options_chain` | Finviz + Yahoo (+ TV underlying) | volume per contract, matched by strike; OI when both report it |
| `stock_earnings` | all | next release date; EPS history |
| `stock_extended_hours` | all | after-hours / pre-market price |
| `technical_analysis` | all | price, RSI(14), ATR(14), volume |
| `stock_news` | all | headline title overlap between the feeds |
| `stock_backtest` | TradingView + Yahoo | strategy metrics run twice on two independent OHLCV feeds |
| `stock_backtest_compare` | TradingView + Yahoo | same, plus whether both feeds pick the same winning strategy |
| `market_snapshot` | TradingView + Yahoo | indices, major crypto, FX pairs, ETFs |
| `combined_analysis` | all | underlying price |

`stock_news`'s TradingView leg is the provider's licensed Marketaux feed and needs
`MARKETAUX_API_TOKEN`; without it that leg is `NOT_ATTEMPTED` and the response reports the feeds that
did answer.

**No tool requires an API key.** `market_sentiment` prefers Marketaux when `MARKETAUX_API_TOKEN` is
set, and otherwise scores Finviz headlines locally (VADER with a financial lexicon). That path is
deterministic, offline and free. Because the headlines are Finviz's, that path is labelled `FINVIZ`; see [Sentiment](#sentiment-no-api-key-required).

### Finviz-only, served, labelled `FINVIZ`, explicitly single-source

`stock_filings` · `stock_ownership` (insider + institutional + short interest) · `stock_peers` ·
`stock_why_moving` · `stock_chart` (PNG) · `stock_dilution` · `stock_screener_filters`

No other provider has an equivalent dataset, so those legs are marked `NOT_ATTEMPTED` (not an error)
and the notice states the data is not cross-checked.

### TradingView-only, served, labelled `TRADINGVIEW`, explicitly single-source

`crypto_top_movers` · `crypto_bollinger_scan` · `crypto_volume_breakout` ·
`crypto_multi_timeframe` · `crypto_multi_agent` · `futures_market_overview` · `futures_top_movers` ·
`futures_watchlist` · `bitcoin_market_pulse` · `egx_market_overview`

`market_sentiment` is single-source too, but which source depends on the environment, see
[Sentiment](#sentiment-no-api-key-required).

### Bloomberg-only tools, labelled `BLOOMBERG`, single-source by construction

`bloomberg_quote` · `bloomberg_markets`

These two tools ask Bloomberg and nobody else, so their responses are single-source: `data_provider:
BLOOMBERG`, `cross_checked: false`, `reconciliation_leg: false`. The provider itself is a full fourth
leg of `stock_quote` and `stock_prices`, where it is asked in parallel and its readings appear in
`comparisons` (see below). The distinction is the call, not the provider.

What these tools add is the government benchmark yield curve plus index, commodity and FX levels on
one board, which no other provider here publishes. `bloomberg_markets` says plainly that the board
carries no per-instrument print time, so nothing there is aged or ordered.

`bloomberg_quote` serves one page and discloses what that page is: `exchange_delay` /
`is_exchange_delayed` state the delay, and `print_time` comes from the last intraday point, never from
`lastUpdate` (`2026-11-05T01:00:00.000Z` on a page whose print was `2026-11-04T20:58:00Z`, which would
make a stale page win a freshness comparison). When that point does not match the quoted price,
`print_time` is null and `print_time_missing_reason` says why.

### Bloomberg as the fourth leg

In `stock_quote` and `stock_prices` Bloomberg is asked in parallel with the other three, contributes
to `ALL` / `providers_answered`, and its reading sits in `comparisons[].values`. Three facts keep that
honest:

- **Delay is a comparability boundary, not a tolerance.** `exchangeDelay` reads `15 Minutes` on
  equities and indices, so a pair of prints a delay-length apart is reported as
  `not_comparable` with the delay named, never as a disagreement. Below that boundary (a closed
  market, where every feed shows the same closing print) it is compared normally, and there the
  cross-check is real.
- **It never wins a tie.** The freshness tie-break lists Bloomberg last, so a delayed page can never
  outrank a live feed that printed at the same instant.
- **Agreement with Yahoo is weak.** Its previous close, 52-week range and closing price are
  penny-identical to Yahoo's, so those two agreeing is one consolidated close read twice. Its ratios
  (`pe_ratio`, `eps`) are computed independently and do carry a little cross-check value.

`stock_prices` asks Bloomberg about at most four tickers per call (`TAPEBASIS_BLOOMBERG_BATCH_MAX`),
because its page path is paced at 10 s per request; the rest are named in `warnings` instead of
quietly missing. `stock_quote` bounds the leg with `TAPEBASIS_BLOOMBERG_QUOTE_DEADLINE`, so a slow or
blocked page becomes a stated `TIMEOUT` / `UPSTREAM_BLOCKED` error while the other three readings
still go out.

### Ops

- `tapebasis_health`, run the probes now (`refresh=True`) or read the cached verdict.
- `tapebasis_tool_map`, every tool with its providers and comparison strategy, without any
  upstream call.

---

## Rate limits are handled per provider

Every upstream is undocumented and rate-limited by its owner, so every request goes through a
per-provider limiter ([`ratelimit.py`](src/tapebasis/ratelimit.py)):

| Control | What it does |
| --- | --- |
| `min_interval` | Hard floor between two requests to one provider, so a 30-ticker fan-out is not a 30-request burst |
| `max_inflight` | Bounds concurrent requests per provider |
| shared cooldown | After a `429` (or a websocket `invalid symbol`) every caller waits an exponentially growing, jittered pause, so one blocked request protects the whole process |
| TTL cache | Absorbs the duplicate questions an agent naturally asks in one turn |

Yahoo is paced slowest (1 request at a time, 1 s apart) because it starts answering `429` after a
short burst. TradingView's websocket treats `invalid symbol` / `resolve error` as an IP-scoped block
rather than a bad ticker, for the same reason. Current limiter state is exposed by
`tapebasis_health` and `GET /health` under `rate_limits`.

Defaults are tuned per provider and overridable; see [Configuration](#configuration).

---

## Sentiment: no API key required

`market_sentiment` has two backends, chosen at runtime. Both produce the same payload shape, and
the payload always says which one ran (`provider`, `scoring`, and the top-level `data_provider`).

| Condition | Backend | `data_provider` |
| --- | --- | --- |
| `MARKETAUX_API_TOKEN` set and usable | Marketaux entity sentiment (licensed) | `TRADINGVIEW` |
| no token, or Marketaux rejected/quota/outage | Finviz headlines scored locally (VADER) | `FINVIZ` |
| neither available | labelled empty payload, `sentiment_score: null` | `NONE` |

Why the labels differ: the **numbers are Finviz headlines** in the local path; only the scoring is
ours. Labelling that `TRADINGVIEW` would claim a provenance the data does not have.

**Local scoring** ([`sentiment.py`](src/tapebasis/sentiment.py)) is VADER (MIT, ships its own
lexicon, no download) with a financial overlay. Plain VADER is tuned for social text and scores
`"Apple beats estimates, raises guidance"` as **neutral**, because *beats* and *raises* are
out-of-vocabulary. The overlay fixes that class of miss:

| Headline | Score |
| --- | --- |
| `Apple beats estimates, raises guidance, shares surge` | `+0.88` |
| `Analysts downgrade Apple on iPhone demand concerns` | `-0.57` |
| `Apple stock drops on weak margin forecast` | `-0.66` |
| `Apple: 3 Key Takeaways for Long-Term Investors` | `0.00` |

Scoring is deterministic: the same headlines always produce the same number, and it never touches
the network.

**A data gap is never dressed up as a finding.** `sentiment_score: 0.0` means "the tone is
balanced", so it is never used for "nothing could be fetched". When there is no material to score
the field is `null`, `sentiment_label` is `Unavailable`, and `note` says why. An invalid or
expired Marketaux token therefore falls back to local scoring and records the reason in
`licensed_path_unavailable`; it does not report a neutral market.

`MARKETAUX_API_TOKEN` also adds the second leg of `stock_news` (licensed article text + URLs).
Without it, `stock_news` reports the Finviz and Yahoo feeds only: complete, labelled and still
useful.

---

## Upstream change detection

Every provider depends on things that can move without notice: Finviz's HTML class names and
unversioned `/api/*` JSON islands, TradingView's scanner POST schema and chart websocket protocol,
and Yahoo's chart API shape.

The monitor in [`health.py`](src/tapebasis/health.py) probes each upstream **independently of
the provider code paths**, so a provider can't hide a break by catching its own exception:

| Probe | Provider | Asserts |
| --- | --- | --- |
| `finviz.indices_api` | FINVIZ | `DJI`, `SPX`, `COMP` keys present |
| `finviz.quote_html` | FINVIZ | the snapshot table, the classification chips and the revenue-breakdown island are still in the rendered page |
| `finviz.news_api` | FINVIZ | `html` key present |
| `tradingview.scanner_api` | TRADINGVIEW | `totalCount` and `data[0].d` present |
| `tradingview.symbol_search` | TRADINGVIEW | symbol search still returns `symbols` |
| `yahoo.chart_api` | YAHOO | `chart.result[0].meta` / `.timestamp` present |
| `yahoo.chart_fx` | YAHOO | the `EURUSD=X` resolution path still answers |
| `yahoo.chart_crypto` | YAHOO | the `BTC-USD` resolution path still answers |

Each successful probe records a SHA-256 fingerprint of the payload's key paths as a **baseline**
persisted to `~/.tapebasis/health_state.json`. Later probes compare against it, so a renamed
field is caught even if the endpoint still returns 200. Verdicts:

- `OK`: status and shape match the baseline
- `DRIFT`: answered, but the status/shape changed (renamed field, moved route, missing marker)
- `DOWN`: timeout, connection error or unexpected HTTP status
- `UNKNOWN`: not probed yet

Drift is surfaced, not swallowed: every tool response gets a `warnings` entry, `degraded: true`, and
a `WARNING` appended to `notice`, scoped to the providers this call actually used. The monitor runs
in the background (`TAPEBASIS_HEALTH_INTERVAL`, default 300 s) and tool calls only read the cached
verdict.

---

## Install

Requires Python 3.10–3.13.

```bash
git clone https://github.com/giraygokirmak/tapebasis.git
cd tapebasis
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### stdio (Claude Desktop, most MCP clients)

```json
{
  "mcpServers": {
    "tapebasis": {
      "command": "/path/to/.venv/bin/tapebasis",
      "env": { "MARKETAUX_API_TOKEN": "" }
    }
  }
}
```

### Streamable HTTP

```bash
tapebasis streamable-http --host 0.0.0.0 --port 8000
curl -s localhost:8000/health
```

## Docker

### Prebuilt image (GHCR)

Every push to `main` publishes a multi-arch image to the GitHub Container Registry:

```bash
docker pull ghcr.io/giraygokirmak/tapebasis:latest
docker run -d --name tapebasis -p 6013:8000 \
  -v tapebasis-state:/home/mcpuser/.tapebasis \
  ghcr.io/giraygokirmak/tapebasis:latest
```

Tags are `latest` and `main` for the branch head, `sha-<shortsha>` for an exact commit, and
`<major>.<minor>.<patch>` (plus `major.minor` and `major`) once a `v*` tag is pushed. The image is
built for `linux/amd64` and `linux/arm64`.

### Build locally

```bash
cp .env.example .env      # optional; every setting has a default
docker compose up -d --build
curl -s localhost:6013/health
```

Port `6013` is the published host port; change the mapping in `docker-compose.yml` if it conflicts
with something already running. The named volume `tapebasis-state` persists chart PNGs **and** the
health baselines, so drift detection survives restarts.

Standalone:

```bash
docker build -t tapebasis:latest .
docker run -d --name tapebasis -p 6013:8000 \
  -v tapebasis-state:/home/mcpuser/.tapebasis \
  tapebasis:latest
```

The image runs the server under `tini` as PID 1, so the container reaps the processes Docker starts
inside its namespace (`HEALTHCHECK`, `docker exec`) instead of accumulating zombies, and `docker stop`
is a graceful SIGTERM. Compose also sets `init: true`, which covers an image built without `tini`.

## Configuration

Everything is optional. See [`.env.example`](.env.example) for the full list.

| Variable | Default | Purpose |
| --- | --- | --- |
| `TAPEBASIS_HEALTH_ENABLED` | `true` | Turn the drift monitor on/off |
| `TAPEBASIS_HEALTH_INTERVAL` | `300` | Seconds between background probe rounds |
| `TAPEBASIS_HEALTH_TTL` | `60` | Seconds a cached verdict is reused |
| `TAPEBASIS_HEALTH_STATE` | `~/.tapebasis/health_state.json` | Baseline file |
| `FINVIZ_CACHE_TTL` | `30` | Scraped-page cache lifetime (s) |
| `FINVIZ_TIMEOUT` | `25` | finviz.com HTTP timeout (s) |
| `FINVIZ_CHART_DIR` | `~/.tapebasis/charts` | Chart PNG output |
| `TAPEBASIS_TV_MIN_INTERVAL` | `0.5` | TradingView request spacing (s) |
| `TAPEBASIS_TV_MAX_INFLIGHT` | `2` | TradingView concurrent requests |
| `TAPEBASIS_FINVIZ_MIN_INTERVAL` | `0.35` | Finviz request spacing (s) |
| `TAPEBASIS_FINVIZ_MAX_INFLIGHT` | `2` | Finviz concurrent requests |
| `TAPEBASIS_YAHOO_MIN_INTERVAL` | `1.0` | Yahoo request spacing (s) |
| `TAPEBASIS_YAHOO_MAX_INFLIGHT` | `1` | Yahoo concurrent requests |
| `TAPEBASIS_BLOOMBERG_MIN_INTERVAL` | `10.0` | Bloomberg request spacing (s); the strictest limiter here |
| `TAPEBASIS_BLOOMBERG_MAX_INFLIGHT` | `1` | Bloomberg concurrent requests |
| `TAPEBASIS_BLOOMBERG_MAX_RETRIES` | `1` | Retries per Bloomberg request |
| `TAPEBASIS_BLOOMBERG_IMPERSONATE` | `chrome124` | Browser fingerprint `curl_cffi` presents to bloomberg.com |
| `TAPEBASIS_BLOOMBERG_TIMEOUT` | `30` | bloomberg.com HTTP timeout (s) |
| `TAPEBASIS_BLOOMBERG_CACHE_TTL` | `60` | Bloomberg page cache lifetime (s) |
| `TAPEBASIS_BLOOMBERG_QUOTE_DEADLINE` | `12.0` | Longest `stock_quote` waits for the Bloomberg leg before recording a `TIMEOUT` |
| `TAPEBASIS_BLOOMBERG_BATCH_MAX` | `4` | Tickers per `stock_prices` call asked of Bloomberg (its page path is paced at 10 s) |
| `TAPEBASIS_TV_MAX_RETRIES`, `TAPEBASIS_FINVIZ_MAX_RETRIES`, `TAPEBASIS_YAHOO_MAX_RETRIES` | `2` | Retries per provider request (the shared cooldown is not tunable) |
| `MARKETAUX_API_TOKEN` | - | Optional. Enables licensed Marketaux news + entity sentiment |
| `MARKETAUX_DAILY_BUDGET` | `90` | Marketaux request cap per day (free plan is 100) |

The legacy `TRADINGVIEW_MCP_*` variables still tune the provider-layer technical-analysis services
while the scanner, websocket and every tool call go through the `TAPEBASIS_*` limiters above.

No proxy configuration exists: every provider reaches its upstream directly.

## Reading a response correctly

```
1. Check data_provider.
   ALL         -> quote the numbers; every provider asked answered.
   TRADINGVIEW -> quote them, but say the figure is single-source and not corroborated.
   FINVIZ      -> same, from the Finviz side.
   YAHOO       -> same, from the Yahoo side.
   BLOOMBERG   -> same, but find out why in comparisons: a delayed print is
                  reported as not_comparable with the delay named. Quote
                  exchange_delay / print_time before calling a price live.
   NONE        -> say no data is available. Do not invent one.

2. Check degraded / warnings.
   Non-empty -> tell the user an upstream API changed or is down, and that
                provider's figures may be stale or incomplete.

3. Check fields for per-field provenance when the response mixes sources
   (e.g. price is ALL while peers is FINVIZ).

4. Check comparisons when you need to show how far apart the providers are.
   match: true  -> they agree within tolerance.
   match: false -> a real disagreement; every reading is in `values`.
   match: null  -> not comparable: no print time, a session/age difference, a
                   declared feed delay (Bloomberg's 15 minutes), or a field
                   with no shared definition (FX day change).

5. Check resolutions when a symbol behaved unexpectedly: it shows exactly which
   ticker each provider was asked for, and why.
```

## Development

```bash
pip install -e ".[dev]"     # or, with uv: uv venv && uv pip install -e ".[dev]"
pytest                      # 275 hermetic tests, no network
pytest -m live              # opt-in: hits real upstreams
```

Tests mock at the HTTP boundary (`httpx.MockTransport`) and the provider-access boundary, so the
suite runs offline and deterministically, including the drift-detection tests that corrupt a stored
baseline and assert the warning reaches a normal tool response.

## Layout

```
src/tapebasis/
├── server.py             FastMCP instance, lifespan, /health, CLI
├── providers_state.py    DataProvider enum, errors, response envelope
├── reconcile.py          concurrent fan-out, comparison, freshness arbitration, notice text
├── freshness.py          market-print timestamps + freshest-print selection
├── ratelimit.py          per-provider pacing, shared cooldown, TTL cache
├── merge_helpers.py      pure payload shapers (raw provider dict -> fields)
├── sentiment.py          token-free headline scoring (VADER + finance lexicon)
├── symbols.py            dynamic per-provider symbol resolution + index aliases
├── health.py             upstream probes, fingerprints, drift state
├── tv_access.py          typed access to TradingView's own data
├── fv_access.py          typed access to the Finviz provider
├── yh_access.py          typed access to the Yahoo Finance provider
├── bb_access.py          typed access to bloomberg.com (fourth leg + Bloomberg-only tools)
├── catalog.py            plain-data tool catalogue (providers + comparison strategy)
├── tools_market.py       multi-source market tools
├── tools_finviz.py       Finviz-only tools
├── tools_tradingview.py  TradingView-only tools + combined_analysis
├── tools_bloomberg.py    Bloomberg-only tools (one provider asked, so single-source)
├── tools_health.py       health + tool map
└── providers/            provider implementations (TradingView, Finviz)
```

## Note on labelling

Every provider is asked for its own data. TradingView quotes come from
`scanner.tradingview.com` and its chart websocket; Finviz from `finviz.com` HTML and JSON islands;
Yahoo from `query1.finance.yahoo.com`; Bloomberg from `bloomberg.com/quote/...` and its market
board, fetched with `curl_cffi` because the site gates plain HTTP clients on the TLS fingerprint.
Nothing is proxied through another provider, and `sources` records the upstream each leg actually
used.

Where a capability exists on only some providers, that is stated rather than simulated: options
chains come from Finviz and Yahoo (TradingView contributes only the underlying price), backtests run
twice on TradingView and Yahoo OHLCV, and Finviz is never asked for crypto, FX or commodity quotes.

## Disclaimer

Market data is provided as-is for research and automation. It is not investment advice, and
scraped data can be delayed, incomplete or wrong. Cross-verification reduces the chance of a bad
number reaching you; it does not eliminate it.

## License

MIT. See [LICENSE](LICENSE).
