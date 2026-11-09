# Configuration

Every setting is optional. Defaults are chosen so a bare `pip install` works.

## Server

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Bind address for streamable-http (`--host` overrides) |
| `PORT` | `8000` | Bind port (`--port` overrides) |
| `DEBUG_MCP` | - | Any non-empty value enables debug logging |

## Health monitor

| Variable | Default | Purpose |
| --- | --- | --- |
| `TAPEBASIS_HEALTH_ENABLED` | `true` | Turn the drift monitor on/off |
| `TAPEBASIS_HEALTH_INTERVAL` | `300` | Seconds between background probe rounds |
| `TAPEBASIS_HEALTH_TTL` | `60` | Seconds a cached verdict is reused |
| `TAPEBASIS_HEALTH_STATE` | `~/.tapebasis/health_state.json` | Baseline + verdict file |
| `TAPEBASIS_HEALTH_TIMEOUT` | `12` | Per-probe HTTP timeout (s) |

See [Health Monitor](Health-Monitor).

## Rate limiting (every provider)

Every upstream is undocumented and rate-limited by its owner, so **every** request (TradingView
scanner, TradingView chart websocket, Finviz HTML/JSON, Yahoo chart API, StockAnalysis quote API,
Bloomberg quote pages) passes through a per-provider limiter ([`ratelimit.py`](https://github.com/giraygokirmak/tapebasis/blob/main/src/tapebasis/ratelimit.py)).

| Variable | Default | Purpose |
| --- | --- | --- |
| `TAPEBASIS_TV_MIN_INTERVAL` | `0.5` | Minimum seconds between TradingView request starts |
| `TAPEBASIS_TV_MAX_INFLIGHT` | `2` | Max concurrent TradingView requests |
| `TAPEBASIS_TV_MAX_RETRIES` | `2` | Retries per TradingView request |
| `TAPEBASIS_FINVIZ_MIN_INTERVAL` | `0.35` | Minimum seconds between Finviz request starts |
| `TAPEBASIS_FINVIZ_MAX_INFLIGHT` | `2` | Max concurrent Finviz requests |
| `TAPEBASIS_FINVIZ_MAX_RETRIES` | `2` | Retries per Finviz request |
| `TAPEBASIS_YAHOO_MIN_INTERVAL` | `1.0` | Minimum seconds between Yahoo request starts |
| `TAPEBASIS_YAHOO_MAX_INFLIGHT` | `1` | Max concurrent Yahoo requests |
| `TAPEBASIS_YAHOO_MAX_RETRIES` | `2` | Retries per Yahoo request |
| `TAPEBASIS_SA_MIN_INTERVAL` | `0.5` | Minimum seconds between StockAnalysis request starts |
| `TAPEBASIS_SA_MAX_INFLIGHT` | `2` | Max concurrent StockAnalysis requests |
| `TAPEBASIS_SA_MAX_RETRIES` | `2` | Retries per StockAnalysis request |
| `TAPEBASIS_SA_TIMEOUT` | `20` | stockanalysis.com HTTP timeout (s) |
| `TAPEBASIS_SA_CACHE_TTL` | `20` | Quote cache lifetime (s); the upstream advertises a 3 s shared cache |
| `TAPEBASIS_BLOOMBERG_MIN_INTERVAL` | `10.0` | Minimum seconds between Bloomberg request starts |
| `TAPEBASIS_BLOOMBERG_MAX_INFLIGHT` | `1` | Max concurrent Bloomberg requests |
| `TAPEBASIS_BLOOMBERG_MAX_RETRIES` | `1` | Retries per Bloomberg request |
| `TAPEBASIS_BLOOMBERG_IMPERSONATE` | `chrome124` | Browser fingerprint `curl_cffi` presents; `chrome` and `chrome131` are refused |
| `TAPEBASIS_BLOOMBERG_TIMEOUT` | `30` | bloomberg.com HTTP timeout (s) |
| `TAPEBASIS_BLOOMBERG_CACHE_TTL` | `60` | Bloomberg page cache lifetime (s) |
| `TAPEBASIS_BLOOMBERG_QUOTE_DEADLINE` | `12.0` | Longest `stock_quote` waits for its Bloomberg leg before recording a `TIMEOUT` |
| `TAPEBASIS_BLOOMBERG_BATCH_MAX` | `4` | Tickers per `stock_prices` call asked of Bloomberg |

Some behaviours are not configurable, because they are safety properties rather than tuning knobs:

- **A shared, exponential cooldown.** After a `429` (or a websocket `invalid symbol` / `resolve
  error`), the provider is paused for the whole process: 5 s, doubling to a 120 s ceiling, with
  jitter, decaying on success. One blocked request protects every later caller instead of each one
  rediscovering the block.
- **A short TTL cache**, so a quote asked twice in one agent turn does not reach the network twice.
- **A per-process gate.** Limiter state is process-local; running several containers multiplies the
  effective request rate.

Yahoo is paced slowly (`1.0 s`, one at a time) because it starts answering `429` after a short burst
and stays angry for a while. Bloomberg is paced slowest of all (`10 s`, one at a time): its HTML path
tolerated five requests 10 s apart, while its separate API bucket burned after about ten rapid calls
and stayed 403 for minutes. Raising concurrency or lowering an interval increases throughput at the
cost of a block that outlasts the burst.

Because that pace is slow, the quote tools bound the cost instead of hiding it:
`TAPEBASIS_BLOOMBERG_QUOTE_DEADLINE` turns a queued or blocked leg into a stated `TIMEOUT` while the
other readings still go out, and `TAPEBASIS_BLOOMBERG_BATCH_MAX` caps how many tickers one
`stock_prices` call asks Bloomberg about, naming the rest in `warnings`.

StockAnalysis sits in the middle (`0.5 s`, two at a time): it fronts its API with Cloudflare and
advertises a 3 s shared cache, so a normal pace is fine, while a burst from one IP is still punished.
Its quote leg needs no batch cap for that reason, and `TAPEBASIS_SA_CACHE_TTL` absorbs the duplicate
questions of one agent turn without ever serving a price a live feed would disagree with.

Current limiter state (`min_interval_s`, `max_inflight`, `cooling_down_s`, `block_streak`,
`cached_entries`) is reported by `tapebasis_health` and `GET /health` under `rate_limits`.

## Finviz (provider layer)

| Variable | Default | Purpose |
| --- | --- | --- |
| `FINVIZ_CACHE_TTL` | `30` | Scraped-page cache lifetime (s) |
| `FINVIZ_TIMEOUT` | `25` | finviz.com HTTP timeout (s) |
| `FINVIZ_MAX_RETRIES` | `2` | Retries per failed request inside the provider layer |
| `FINVIZ_CHART_DIR` | `~/.tapebasis/charts` | Chart PNG output directory |
| `FINVIZ_NEWS_TTL` | `60` | News cache lifetime (s) |
| `FINVIZ_USER_AGENT` | browser UA | Override the User-Agent sent to finviz.com |

Finviz's quote data is scraped from rendered HTML, so a short cache keeps prices fresh at the cost of
more upstream requests. `FINVIZ_CACHE_TTL=30` is a deliberate middle ground.

`FINVIZ_TIMEOUT=25` is a fail-fast ceiling: the fan-out waits for the slowest leg, so a hanging Finviz
sets the latency of a response that the other providers could have answered in a second.

## TradingView provider layer

The legacy `TRADINGVIEW_MCP_*` variables tune the technical-analysis/backtest services inside the
provider package. The scanner, the chart websocket and every tool-level fan-out use the
`TAPEBASIS_TV_*` limiters above; setting these does not change how often tools hit upstreams.

| Variable | Default | Purpose |
| --- | --- | --- |
| `TRADINGVIEW_MCP_MIN_INTERVAL_S` | `0.5` | Minimum seconds between analysis-call starts |
| `TRADINGVIEW_MCP_MAX_INFLIGHT` | `2` | Max concurrent analysis calls |
| `TRADINGVIEW_MCP_RETRY_DELAYS` | `1.0,4.0` | Retry backoff schedule (seconds, comma-separated) |
| `TRADINGVIEW_MCP_RETRY_JITTER` | `0.2` | ±20 % jitter so parallel callers do not retry in lockstep |
| `TRADINGVIEW_MCP_SOCKET_TIMEOUT` | `20` | Socket timeout (s) |
| `TRADINGVIEW_MCP_CACHE_TTL` | `60` | Successful-result cache lifetime (s) |
| `TRADINGVIEW_MCP_STALE_TTL` | `21600` | How long a cached result may still be served (6 h) |
| `TRADINGVIEW_MCP_FAILURE_COOLDOWN_S` | `15` | Pause after a failure before retrying |
| `TRADINGVIEW_MCP_BATCH_BUDGET_S` | provider default | Wall-clock budget for one batch of analysis calls |
| `TRADINGVIEW_MCP_BATCH_MAX_CONSECUTIVE_FAILS` | provider default | Abort a batch after this many consecutive failures |

## News and sentiment

| Variable | Default | Purpose |
| --- | --- | --- |
| `MARKETAUX_API_TOKEN` | - | **Optional.** Licensed Marketaux news + entity sentiment |
| `MARKETAUX_DAILY_BUDGET` | `90` | Marketaux request cap per day |

Neither is required. Without a token, sentiment is scored locally from Finviz headlines and
`stock_news` uses the Finviz and Yahoo feeds. See [Sentiment](Sentiment).

## No proxy configuration

There is deliberately **no proxy support**. Every provider reaches its upstream directly. If
you need egress control, do it at the network or container level.

## Example `.env`

```bash
# Health monitor
TAPEBASIS_HEALTH_ENABLED=true
TAPEBASIS_HEALTH_INTERVAL=300
TAPEBASIS_HEALTH_TTL=60

# Finviz
FINVIZ_CACHE_TTL=30
FINVIZ_TIMEOUT=25

# Per-provider pacing
TAPEBASIS_TV_MIN_INTERVAL=0.5
TAPEBASIS_TV_MAX_INFLIGHT=2
TAPEBASIS_FINVIZ_MIN_INTERVAL=0.35
TAPEBASIS_FINVIZ_MAX_INFLIGHT=2
TAPEBASIS_YAHOO_MIN_INTERVAL=1.0
TAPEBASIS_YAHOO_MAX_INFLIGHT=1
TAPEBASIS_SA_MIN_INTERVAL=0.5
TAPEBASIS_SA_MAX_INFLIGHT=2
TAPEBASIS_SA_CACHE_TTL=20
TAPEBASIS_BLOOMBERG_MIN_INTERVAL=10.0
TAPEBASIS_BLOOMBERG_MAX_INFLIGHT=1
TAPEBASIS_BLOOMBERG_QUOTE_DEADLINE=12.0
TAPEBASIS_BLOOMBERG_BATCH_MAX=4

# Optional: licensed news + sentiment
# MARKETAUX_API_TOKEN=
MARKETAUX_DAILY_BUDGET=90
```

Docker reads `.env` automatically. For stdio clients, pass variables in the client's `env` block or
export them in the parent process.

## Data written to disk

| Path | Contents | Safe to delete? |
| --- | --- | --- |
| `~/.tapebasis/health_state.json` | Probe baselines + last verdicts | Yes, re-baselines on next round |
| `~/.tapebasis/charts/` | Generated chart PNGs | Yes |

Both live under `~/.tapebasis` by default; in Docker that is the `tapebasis-state` volume.

## Symbol resolution cache

Symbol resolution is cached per `(provider, query)` for **1 hour**, in memory. It is not persisted and
has no environment variable: a restart simply re-resolves. This is separate from the rate-limit TTL
cache, which is measured in seconds.

## Related

- [Health Monitor](Health-Monitor): what the health variables control
- [Docker](Docker): volume layout and `.env` handling
- [Troubleshooting](Troubleshooting): symptoms traced to settings
