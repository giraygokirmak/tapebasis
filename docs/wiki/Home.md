# Tapebasis

<img src="https://raw.githubusercontent.com/giraygokirmak/tapebasis/main/docs/logo.svg" alt="Tapebasis" width="300">

**Multiple tapes, one basis.** An MCP server that serves **TradingView**, **Finviz**, **Yahoo Finance**,
**StockAnalysis** and **Bloomberg** market data together, cross-checks every overlapping figure, and
labels each response with the provider that actually produced it.

*Basis* is the finance term for the price difference between two markets quoting the same asset.
*Tape* is the ticker tape. Tapebasis is the spread between multiple feeds, measured on every call.

The point is redundancy you can *see*. Every provider that could answer a field is asked, natively
and in parallel. When several answer, the data is cross-checked. When only one answers, you get the
data, clearly marked as single-source. When none answers, you get `NONE` instead of a
plausible-looking number. And because every provider scrapes or calls an undocumented upstream, a
background monitor probes every endpoint and reports API/schema drift inside ordinary tool responses.

Each leg is fetched natively: TradingView's own scanner and chart websocket, Finviz's HTML and JSON
islands, Yahoo's chart API, StockAnalysis's quote API, Bloomberg's quote pages. A provider that
quietly proxies another is worthless as a cross-check, so none does. Bloomberg and StockAnalysis are
the other two legs, asked in parallel with the rest. Bloomberg's equity prints are exchange-delayed,
so a pair that far apart is reported as not comparable with the delay named instead of being counted
as disagreement. StockAnalysis covers US equities and ETFs only and serves the same consolidated tape
Yahoo does, so that pair is weak corroboration. See
[Bloomberg](#bloomberg-the-leg-that-states-its-delay) and
[StockAnalysis](#stockanalysis-the-leg-that-covers-us-equities-and-etfs).

**No tool requires an API key.** Every capability works out of the box; `MARKETAUX_API_TOKEN` only
upgrades news and sentiment to a licensed feed.

---

## Why this exists

One market-data source gives an agent a single number and no way to judge it. Asking several
independent providers the same question and comparing the answers inverts the problem: the server
asks them all, compares, and tells the agent what it is holding.

| Situation | What this server reports | What a single-source feed cannot |
| --- | --- | --- |
| Every asked provider answers, values agree | `ALL`, `comparisons[].match: true` | confirm the number against independent readings |
| They answer but diverge | `ALL` + every value in `comparisons` + a warning | show that a disagreement exists |
| One provider is down | `TRADINGVIEW`/`FINVIZ`/`YAHOO`/`SA` + "not corroborated" | say the figure is single-source |
| Only Bloomberg has it | `BLOOMBERG` + `cross_checked: false` | say what is uncorroborated and how stale |
| All down | `NONE`, no value presented | avoid a stale or invented number |
| Upstream markup changed | `degraded: true` + a named warning | avoid a silently empty or wrong response |

---

## Documentation map

| Page | What it covers |
| --- | --- |
| [Getting Started](Getting-Started) | Install, run over stdio or HTTP, first calls |
| [Response Contract](Response-Contract) | The envelope, every field, how to read it correctly |
| [Tools Reference](Tools-Reference) | All 35 tools, providers, and what is compared |
| [Architecture](Architecture) | Module layout, data flow, why the pieces sit where they do |
| [Health Monitor](Health-Monitor) | Probes, fingerprints, drift detection, baselines |
| [Sentiment](Sentiment) | Token-free local scoring vs. licensed Marketaux |
| [Configuration](Configuration) | Every environment variable |
| [Docker](Docker) | Standalone image, compose, volumes, healthcheck |
| [Development](Development) | Tests, layout, adding a tool |
| [Troubleshooting](Troubleshooting) | Symptom → cause → fix |
| [Design Decisions](Design-Decisions) | Non-obvious choices and the reasons behind them |

---

## The `data_provider` contract

Every tool result carries exactly one of seven values. It states **coverage**, never agreement:

| Value | Meaning |
| --- | --- |
| `ALL` | Every provider that was asked answered. |
| `TRADINGVIEW` | Only TradingView answered. Served, but **not** corroborated. |
| `FINVIZ` | Only Finviz answered. Served, but **not** corroborated. |
| `YAHOO` | Only Yahoo Finance answered. Served, but **not** corroborated. |
| `SA` | Only StockAnalysis answered. Served, but **not** corroborated; US equities and ETFs only. |
| `BLOOMBERG` | Only Bloomberg answered. Served, but **not** corroborated; its quote can be delayed. |
| `NONE` | No provider could supply it. No value is presented. |

```jsonc
{
  "data_provider": "ALL",
  "verification": "MULTI_SOURCE",          // MULTI_SOURCE | SINGLE_SOURCE | UNAVAILABLE
  "providers_answered": ["TRADINGVIEW", "FINVIZ", "YAHOO", "SA", "BLOOMBERG"],   // only those that answered
  "notice": "Every provider asked answered ...",   // sentence to relay to the user
  "data": { ... },                         // the reconciled payload, one value per field
  "fields": { "price": "ALL", "peers": "FINVIZ" }, // per-field provenance
  "freshness": {                           // why `data` holds the value it does
    "tradingview": "2026-11-04T00:59:53+00:00",
    "finviz": "2026-11-04T10:42:00+00:00",
    "yahoo": "2026-11-03T21:00:01+00:00",
    "sa": "2026-11-03T21:00:01+00:00",         // same consolidated tape as Yahoo
    "bloomberg": "2026-11-04T10:27:00+00:00",  // 15 min behind, so it cannot win
    "chosen": "FINVIZ",
    "decision": "newest",                  // newest | tie | no_timestamp
    "newest_print": "2026-11-04T10:42:00+00:00"
  },
  "comparisons": [                         // the actual side-by-side numbers
    { "field": "price",
      "values": { "TRADINGVIEW": 331.9, "FINVIZ": 332.33, "YAHOO": 331.9, "SA": 331.9, "BLOOMBERG": 332.1 },
      "match": true, "diff_pct": 0.1294, "tolerance_pct": 0.5 }
  ],
  "resolutions": { "TRADINGVIEW": { "symbol": "NASDAQ:AAPL" }, ... },
  "sources": { "TRADINGVIEW": "scanner.tradingview.com", "FINVIZ": "...", "YAHOO": "...", "SA": "...", "BLOOMBERG": "..." },
  "errors": [ { "provider": "FINVIZ", "code": "...", "message": "..." } ],
  "warnings": [ "..." ],
  "degraded": false,                       // true when the health monitor saw drift/downtime
  "generated_at": "2026-11-04T10:43:02+00:00"
}
```

**One value per compared field, and it is the newest print.** `data` holds a single price: the
reading whose market print is newest. Ties are broken by the documented default order (`FINVIZ`,
`TRADINGVIEW`, `YAHOO`, `SA`, `BLOOMBERG`); Bloomberg is last because its print can be structurally
older, and StockAnalysis sits just before it because its coverage is the narrowest of the live feeds.
Every original reading stays in `comparisons.values`, and `freshness.decision` states which rule
applied.

**`ALL` does not mean "the values agree".** It means every provider asked answered. Agreement is a
separate axis, reported per field in `comparisons[].match` and summarised in `notice`/`warnings`. A
subset of providers answering is still `ALL`; `providers_answered` names which ones.

**Disagreements are never silently resolved.** If the providers report different prices, all values
stay in `comparisons`, the field is named in `notice` and `warnings`, and `data_provider` stays `ALL`.
An agent reading it can see exactly how far apart they are.

**A non-comparison is not a disagreement.** A field the providers measure against different baselines
is reported as `not_comparable`, with the reason in `pairs[].not_comparable`, instead of being called
a conflict. That covers a day change or volume whose prints belong to different sessions, a print
past the staleness ceiling, a provider that exposes no print time at all, a declared feed delay
(Bloomberg states 15 minutes on equities, so its pairs stop being comparable at that distance), and a
field with no shared definition: spot FX has no single official previous close, so an FX day change is
always reported from every provider and never judged.

Full detail: [Response Contract](Response-Contract).

---

## StockAnalysis: the leg that covers US equities and ETFs

StockAnalysis is in `PROVIDER_ORDER`, is asked in parallel by `stock_quote`, `stock_prices` and
`stock_extended_hours`, and contributes to `ALL` / `providers_answered`. Three properties keep that
honest instead of inflated:

- it is a US feed: the quote API serves US-listed equities and ETFs and answers `404` for indices,
  FX, crypto and foreign listings, so anything else resolves to *not carried* and is recorded as
  `NOT_ATTEMPTED`, never as an error;
- its price, previous close, session range and 52-week range are the same consolidated tape Yahoo
  serves, so agreement between those two is one tape read twice, not two witnesses;
- `ts` is epoch milliseconds, converted to ISO in the access layer so a print is never dated to a
  century no market trades in.

What it adds is the session open/high/low Finviz does not publish and the extended-hours block from
the same request (`stockanalysis_extended_hours`). It is paced at `0.5 s`, so a `stock_prices` batch
needs no cap for it.

## Bloomberg: the leg that states its delay

Bloomberg is in `PROVIDER_ORDER`, is asked in parallel by `stock_quote` and `stock_prices`, and
contributes to `ALL` / `providers_answered`. Its reading sits in `comparisons[].values` with the rest.
Three properties keep that honest instead of inflated:

- its equity and index prints are delayed (`exchangeDelay` reads `15 Minutes`), so a pair a delay
  length apart is reported as `not_comparable` with the delay named, not as a disagreement;
- it is last in the tie-break order, so a delayed page can never outrank a live print that shares
  the same instant;
- its static fields are penny-identical to Yahoo's, so agreement between those two is one
  consolidated close read twice. Its ratios (`pe_ratio`, `eps`) are computed independently.

`lastUpdate` is a session sentinel, not a print time (`2026-11-05T01:00:00.000Z` on a page whose real
print was `2026-11-04T20:58:00Z`), so `print_time` is taken from the last intraday point and
`print_time_missing_reason` explains a mismatch. `stock_quote` bounds the leg with a deadline, so a
blocked page becomes a stated `TIMEOUT` / `UPSTREAM_BLOCKED` error while the other readings
still go out.

`bloomberg_quote` and `bloomberg_markets` are the single-source case: those tools ask Bloomberg and
nobody else, so they return `cross_checked: false` and `reconciliation_leg: false`. The board is also
the only source here of the government benchmark yield curve, and it carries no per-instrument print
time, which the response says.

Access needs `curl_cffi`: bloomberg.com gates plain HTTP clients on the TLS fingerprint, so `httpx`
gets a 403 robot page. That is also why the health monitor does not probe this provider; the tool
response is the availability signal. Details: [Design Decisions](Design-Decisions).

---

## Symbols are resolved per provider

`XAUUSD` is `OANDA:XAUUSD` on TradingView, `^GSPC`-style aliasing for indices, a suffix for Yahoo FX,
`XAUUSD:CUR` on Bloomberg and simply not carried by Yahoo, Finviz or StockAnalysis. [`symbols.py`](https://github.com/giraygokirmak/tapebasis/blob/main/src/tapebasis/symbols.py)
resolves each query per provider, caches the result for an hour, and records the derivation in
`resolutions`. A ticker is only returned if the provider can actually quote it, and a missing
instrument becomes `NOT_ATTEMPTED`: a structural fact, not an error.

---

## Quick start

```bash
git clone https://github.com/giraygokirmak/tapebasis.git
cd tapebasis
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

```jsonc
// Claude Desktop / any stdio MCP client
{
  "mcpServers": {
    "tapebasis": {
      "command": "/path/to/.venv/bin/tapebasis"
    }
  }
}
```

```bash
# HTTP
tapebasis streamable-http --host 0.0.0.0 --port 8000
curl -s localhost:8000/health
```

```bash
# Docker (prebuilt image from GHCR)
docker run -d --name tapebasis -p 6013:8000 \
  -v tapebasis-state:/home/mcpuser/.tapebasis \
  ghcr.io/giraygokirmak/tapebasis:latest
curl -s localhost:6013/health
```

Or build from the checkout with `docker compose up -d --build`.

Details: [Getting Started](Getting-Started) · [Docker](Docker).

---

## Note on labelling

Every provider is asked for its own data: TradingView from `scanner.tradingview.com` and its chart
websocket, Finviz from `finviz.com` HTML and JSON islands, Yahoo from `query1.finance.yahoo.com`,
StockAnalysis from `stockanalysis.com/api/quotes`, Bloomberg from `bloomberg.com` quote pages and its
market board. Nothing is proxied through another provider, and `sources` records the upstream each
leg used.

Where a capability exists on only some providers, that is stated, not simulated: options chains come
from Finviz and Yahoo (TradingView contributes only the underlying price), backtests run twice on
TradingView and Yahoo OHLCV, and Finviz and StockAnalysis are never asked for crypto, FX or commodity
quotes because neither carries them.

---

## Disclaimer

Market data is provided as-is for research and automation. It is not investment advice, and scraped
data can be delayed, incomplete or wrong. Cross-verification reduces the chance of a bad number
reaching you; it does not eliminate it. Sentiment scores are a deterministic summary of headline
tone, not a prediction, and not a trading signal.

## License

MIT. See [LICENSE](https://github.com/giraygokirmak/tapebasis/blob/main/LICENSE).
