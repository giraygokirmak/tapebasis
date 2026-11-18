<div align="center">

<img src="docs/logo.svg" alt="Tapebasis" width="360">

**Multiple tapes, one basis.** An MCP server that serves **TradingView**, **Finviz**, **Yahoo
Finance**, **StockAnalysis** and **Bloomberg** market data together, cross-checks every overlapping
figure, and labels each response with the provider that actually produced it. Separate authenticated
**Equibles** tools add fundamentals, ownership and licensed positioning. Beyond those dedicated tools,
two opt-in adapters run in `stock_earnings` and `stock_ownership`: an EPS estimate compares only when
all reporting context matches, and short positions compare only on the same FINRA settlement date.
Without `TAPEBASIS_EQUIBLES_API_KEY`, those adapters make no request and add no scope or coverage
change. Equibles never joins general live-price arbitration or substitutes its historical prices,
different-period estimates, other filing populations or option summaries for another observation.

</div>

---

*Basis* is the finance term for the price difference between two markets quoting the same asset.
*Tape* is the ticker tape. Tapebasis is the spread between multiple feeds, measured on every call:
zero when they agree, reported when they don't.

The point is redundancy you can *see*. Every provider that could answer a field is asked, natively
in parallel. When several answer, the data is cross-checked. When only one answers, you get the data,
clearly marked as single-source. When none answers, you get `NONE` instead of a
plausible-looking number. And because every market-comparison provider scrapes or calls an
undocumented upstream, a background monitor probes every endpoint and reports API/schema drift inside
ordinary tool responses. Equibles is the documented exception: its own versioned, Bearer-authenticated
REST API, its own datasets and an explicit API access contract.

Each provider is fetched natively: TradingView's own scanner and chart websocket, Finviz's HTML and
JSON islands, Yahoo's chart API, StockAnalysis's quote API, Bloomberg's quote pages. No leg proxies
another: a provider that quietly forwards a competitor's numbers is worthless as a cross-check.

Bloomberg and StockAnalysis are the other two legs, asked like the rest, in parallel, on the same
call. The properties that make each of them different from a plain live feed are reported rather
than hidden by a tolerance. Bloomberg's equity and index prints are exchange-delayed
(`exchangeDelay` is `15 Minutes`), so a pair of prints further apart than the print-time guard allows
is reported as **not comparable** with the delay named, instead of being called a provider
disagreement; it also never wins the freshness tie-break against a live print. Its static fields are
penny-identical to Yahoo's, so agreement between those two is weak corroboration, not two independent
witnesses. What it adds is its own quote pages and the
[government benchmark yield curve](#bloomberg-only-tools-labelled-bloomberg-single-source-by-construction),
which no other provider here publishes. StockAnalysis covers US equities and ETFs only, and its
quote surface is the same consolidated tape Yahoo serves, so that pair is weak corroboration for the
same reason; indices, FX, crypto, commodities and foreign listings are reported as not carried
instead of requested.

[![Tests](https://github.com/giraygokirmak/tapebasis/actions/workflows/test.yml/badge.svg)](https://github.com/giraygokirmak/tapebasis/actions/workflows/test.yml)
[![Python 3.10–3.13](https://img.shields.io/badge/python-3.10%E2%80%933.13-3776ab)](https://github.com/giraygokirmak/tapebasis)
[![License: MIT](https://img.shields.io/badge/license-MIT-5eead4)](LICENSE)

---

## The `data_provider` contract

Every tool result carries exactly one of nine values. It states **coverage**, never agreement:

| Value          | Meaning                                                                    |
| -------------- | -------------------------------------------------------------------------- |
| `ALL`          | Every provider that was asked answered. Coverage is complete for this call. |
| `PARTIAL`      | More than one answered, but a provider that was asked produced nothing. The values are served; `errors` says why the missing leg is missing. |
| `TRADINGVIEW`  | Only TradingView answered. Served, but **not** corroborated.               |
| `FINVIZ`       | Only Finviz answered. Served, but **not** corroborated.                    |
| `YAHOO`        | Only Yahoo Finance answered. Served, but **not** corroborated.             |
| `SA`           | Only StockAnalysis answered. Served, but **not** corroborated; US equities and ETFs only. |
| `BLOOMBERG`    | Only Bloomberg answered. Served, but **not** corroborated; its quote can be delayed. |
| `EQUIBLES`     | One or more named Equibles datasets answered. Single-source, **never merged** with another provider; `attribution`, `as_of`, `reporting_delay` and `access` are mandatory. Two configured adapters may compare an exactly equivalent EPS estimate or same-date short position |
| `NONE`         | No provider could supply the primary value; a separately labelled `news` block can still be available. |

`ALL` means "every provider asked answered", not "they agree". Agreement is a separate axis, and it
lives in `comparisons[].match`. A provider that was asked and failed makes the response `PARTIAL`,
never `ALL`: the label describes coverage, and a listed error is missing coverage.
`providers_answered` names exactly which providers contributed. The positive agreement notice appears
only after a real agreeing comparison. Invalid pairs keep their readings, `match: null` and a
`not_comparable` reason; a resolved symbol that returns no data is `NO_DATA`, not `NOT_ATTEMPTED`.

An Equibles response has no `comparisons` entries. Its `data_provider` stays `EQUIBLES` even when
some requested datasets failed, because each surviving block is still Equibles-only and must not be
read as multi-source corroboration. `EQUIBLES` never joins the market fan-out or the freshness
tie-break.

The same envelope also contains:

```jsonc
{
  "data_provider": "ALL",
  "verification": "MULTI_SOURCE",        // MULTI_SOURCE | SINGLE_SOURCE | UNAVAILABLE
  "providers_answered": ["TRADINGVIEW", "FINVIZ", "YAHOO", "SA", "BLOOMBERG"],
  "notice": "Every provider asked answered (TradingView, Finviz, Yahoo Finance, StockAnalysis and Bloomberg). ...",   // names whichever answered
  "data": { ... },                       // the reconciled payload, one value per field
  "fields": {                            // per-field provenance, never a joint label
    "price": { "source": "FINVIZ",
               "supplied": ["TRADINGVIEW", "FINVIZ", "YAHOO", "SA"],
               "compared": ["TRADINGVIEW", "FINVIZ", "YAHOO", "SA"],
               "agreement": true },
    "peers": { "source": "FINVIZ", "supplied": ["FINVIZ"], "compared": [], "agreement": null } },
  "freshness": {                         // why `data` holds the value it does
    "tradingview": "2026-11-04T00:59:53+00:00",
    "finviz": "2026-11-04T10:42:00+00:00",
    "yahoo": "2026-11-03T21:00:01+00:00",
    "sa": "2026-11-03T21:00:01+00:00",      // same consolidated tape as Yahoo
    "bloomberg": "2026-11-04T10:27:00+00:00",   // 15 min behind, so it cannot win
    "chosen": "FINVIZ",
    "decision": "newest",                // newest | tie | no_timestamp
    "newest_print": "2026-11-04T10:42:00+00:00",
    "reason": "FINVIZ printed most recently (2026-11-04T10:42:00+00:00)"
  },
  "comparisons": [                       // the actual side-by-side numbers
    { "field": "price",
      "values": { "TRADINGVIEW": 331.9, "FINVIZ": 332.33, "YAHOO": 331.9, "SA": 331.9, "BLOOMBERG": 332.1 },
      "match": true, "diff_pct": 0.1294, "tolerance_pct": 0.5,
      "pairs": [ { "between": ["TRADINGVIEW", "FINVIZ"], "match": true, "diff_pct": 0.1294 }, ... ],
      "chosen": "FINVIZ" }
  ],
  "resolutions": { "TRADINGVIEW": { "symbol": "NASDAQ:AAPL", ... }, ... },
  "sources": { "TRADINGVIEW": "scanner.tradingview.com", "FINVIZ": "...", "YAHOO": "...", "SA": "...", "BLOOMBERG": "..." },
  "errors": [ { "provider": "FINVIZ", "code": "...", "message": "..." } ],
  "warnings": [ "..." ],
  "degraded": false,                     // true when the health monitor saw drift/downtime
  "generated_at": "2026-11-04T10:43:02+00:00"
}
```

**One price, and it is the newest print.** Every provider that can supply a field is asked. `data`
holds exactly one value per compared field: the reading whose market print is newest. Providers that
share the newest instant are the only tie-break candidates, and the documented default order
(`FINVIZ`, `TRADINGVIEW`, `YAHOO`, `SA`, `BLOOMBERG`) picks between them; Bloomberg is last
precisely because its print can be structurally older, and StockAnalysis sits just before it because
its coverage is the narrowest of the live feeds. `freshness.decision` is the machine-readable
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

**A price is a print, and it carries its session.** The obvious price field goes stale as soon as the
regular session ends: TradingView's scanner `close` stops moving while its `premarket_close` keeps
streaming, Yahoo's `regularMarketPrice` freezes while `fulldayPrice` does not, and StockAnalysis keeps
the current extended print in `extended_hours`. Each provider's live print is therefore resolved before
anything is compared, and `stock_quote` / `stock_prices` publish the session it belongs to
(`pre_market`, `regular`, `post_market`, `overnight`) with the day change and previous close measured
against that same session's baseline, recovered from the print's own change. The label follows the print
that was served rather than a nominated leg, so a delayed feed cannot name a session the served number
does not belong to. `stock_extended_hours` independently reads Blue Ocean overnight prints from
TradingView's `BOATS:` socket and Yahoo's quote header. `overnight_source` names the newest eligible
print, while `overnight_readings`, `overnight_comparison` and `overnight_errors` retain provenance and
failures. On the same overnight occurrence, the normalized change uses Yahoo's `reference_close`;
TradingView's venue-based change is retained separately as `reported_change` and
`reported_change_percent`. An absent or cross-occurrence reference leaves the normalized change null.
Last night's print survives after 04:00 ET with `is_current: false`, rather than being passed off as
the live pre-market price. `stock_quote` does not carry overnight itself; use `stock_extended_hours`.

Extended-hour freshness is pairwise: Yahoo's candle time is parseable UTC ISO, StockAnalysis supplies
`price_timestamp`, and TradingView's regular `update_time` is never attached to its separate extended
print. An undated print therefore leaves only its own pairs `not_comparable`; a dated Yahoo/StockAnalysis
pair can still agree. `after_hours_readings` retains each provider's price, session, timestamp, baseline
and derived change, so the number's definition is visible beside it.

Implementation: [`reconcile.py`](src/tapebasis/reconcile.py) (fan-out + comparison),
[`freshness.py`](src/tapebasis/freshness.py) (print-time parsing),
[`sessions.py`](src/tapebasis/sessions.py) (which session a print belongs to, and which print is live),
[`providers_state.py`](src/tapebasis/providers_state.py) (envelope + labels).

---

## Symbols are resolved per provider

The same instrument is spelled differently by each upstream, and the differences are not mechanical:

| Instrument | TradingView | Finviz | Yahoo Finance | StockAnalysis | Bloomberg |
| --- | --- | --- | --- | --- | --- |
| Apple | `NASDAQ:AAPL` | `AAPL` | `AAPL` | `aapl` | `AAPL:US` |
| Gold (spot) | `OANDA:XAUUSD` | *(not carried)* | *(not carried, `XAUUSD=X` is a 404)* | *(not carried)* | `XAUUSD:CUR` |
| S&P 500 | `SP:SPX` | *(indices feed only)* | `^GSPC` | *(not carried)* | `SPX:IND` |
| NASDAQ-100 | `NASDAQ:NDX` | *(indices feed only)* | `^NDX` | *(not carried)* | `NDX:IND` |
| WTI (spot) | `FX:USOIL` | *(not carried)* | *(not carried)* | *(not carried)* | *(no spot page; `CL1:COM` is a future)* |
| WTI (front future) | `NYMEX:CL1!` | *(not carried)* | `CL=F` | *(not carried)* | `CL1:COM` |
| EUR/USD | `FX:EURUSD` | *(not carried)* | `EURUSD=X` | *(not carried)* | `EURUSD:CUR` |
| Bitcoin | `BITSTAMP:BTCUSD` | *(not carried)* | `BTC-USD` | *(not carried)* | `XBTUSD:CUR` |

Indices and commodities (gold, silver, WTI, Brent, copper, natural gas, spot and front-month
futures) live in one instrument registry in
[`symbols.py`](src/tapebasis/symbols.py): one row per instrument, one column per provider, a
`None` cell stating the boundary that provider declares. Everything else resolves dynamically per
provider, is cached for an hour, and is recorded in `resolutions` (`explicit`, `alias`, `search`,
`normalise`, `mechanical`, `none`). Three rules keep it honest:

- **The registry is addressing, never scope.** A filled cell says which ticker to ask that
  provider for; every provider with a filled cell is still asked in parallel. A `None` cell is the
  provider's own declared boundary, reported as `NOT_ATTEMPTED`, not a decision to skip it.
- **A ticker is only returned if the provider can actually quote it.** TradingView's symbol *search*
  offers `OANDA:BTCUSD`, but its *scanner* has no row for it, resolution verifies against the
  scanner and picks `BITSTAMP:BTCUSD` instead. This is also why `WTI` resolves to `FX:USOIL` and
  not `NYSE:WTI` (W&T Offshore, an equity whose ticker happens to match), and why `WTI=F` is
  aliased to the front-month future instead of falling into search, where it lands on `XETR:WTIF`,
  the WisdomTree Japan ETF.
- **A missing instrument is not an outage.** `NotApplicable` becomes `NOT_ATTEMPTED`, which is
  excluded from `errors`. "Finviz does not carry spot gold" is a structural fact, not a failure. Once
  a provider's symbol has resolved, an empty quote is instead a visible `NO_DATA` error.

XAUUSD, for example, resolves to `OANDA:XAUUSD` for TradingView, `XAUUSD:CUR` for Bloomberg, and
nothing for Yahoo, Finviz and StockAnalysis, so the response is `ALL` over the two that answered,
served and clearly labelled, not hidden.

---

## Tools (55)

### Multi-source, every capable provider asked, answers compared

| Tool | Providers | Fields cross-checked |
| --- | --- | --- |
| `stock_quote` | every provider that carries the instrument | price, change %, previous close, volume, session open/high/low, 52-w high/low, P/E, RSI(14), average analyst target; each price carries its `session` |
| `stock_prices` | every provider, per ticker (Bloomberg capped by batch) | price and change % per ticker (per-row `data_provider`, `session`) |
| `stock_screener` | TradingView + Finviz | per-row price for the tickers both return |
| `market_indices` | TradingView + Finviz indices feed + Yahoo | S&P 500, Dow, Nasdaq Composite, Russell 2000, VIX levels |
| `stock_options_chain` | Finviz + Yahoo (+ TV underlying) | volume per contract, matched by strike; OI when both report it |
| `stock_earnings` | TradingView + Finviz + Yahoo | next release date; EPS history |
| `stock_extended_hours` | TradingView + Finviz + Yahoo + StockAnalysis | after-hours / pre-market price; TradingView + Yahoo overnight price |
| `technical_analysis` | TradingView + Finviz + Yahoo | price, RSI(14), ATR(14), volume |
| `stock_news` | Finviz + Yahoo (+ TradingView/Marketaux) | latest 10 unique stories, per-story consensus (same_url / same_title / similar_title); duplicates_collapsed |
| `stock_backtest` | TradingView + Yahoo | strategy metrics run twice on two independent OHLCV feeds |
| `stock_backtest_compare` | TradingView + Yahoo | same, plus whether both feeds pick the same winning strategy |
| `market_snapshot` | TradingView + Yahoo | indices, major crypto, FX pairs, ETFs |
| `combined_analysis` | TradingView + Finviz + Yahoo | underlying price; data.news merges latest 10 stories with per-story consensus |

A provider absent from a row is absent because it has no endpoint for that capability: StockAnalysis
carries no index, FX, crypto or foreign listing, and no provider but Finviz publishes a curated peer
list. Those legs are `NOT_ATTEMPTED`, not errors.

`stock_quote` also compares the shared average analyst target at 0.1 % tolerance for Finviz's rounding.
Top-level `analyst_targets` retains separate TradingView one-year forecast and three-month rating
analyst counts, scanner target bounds and five rating buckets. Finviz distinct firms among its visible
rating actions stay separate from its visible-row rating distribution, which can differ from Finviz's
displayed distinct-firm summary and leaves unfamiliar labels unclassified. Source rating rows retain
their original transition strings alongside parsed before/after labels and targets. Each row's implied upside
is a decimal ratio based on the newest target and only the same SSR's `lastClose`; missing targets stay
null, and another provider's price is never borrowed. These populations are not combined, are not
contributors to a common denominator and do not form consensus. A forecast-page failure is an auxiliary
`analyst_forecasts` error and does not change primary quote coverage or remove scanner distributions.
The direct `data` payload repeats provider-specific target, rating-analyst, Buy/Hold/Sell,
visible-firm and action-row counts; each has its own source and population, null means unreported,
and zero remains a real count. `combined_analysis.data` mirrors the TradingView counts and complete
five-bucket distribution.

`stock_prices` exposes per-symbol `misses` and typed `errors`, so one failed ticker does not sink or
silently vanish from the batch. A returned row without a usable price is `NO_DATA`, not an answer.
`agrees` is `null` when neither compared field reached a verdict. The envelope's `errors`, coverage
and notice describe those same provider-symbol outcomes: a complete `ALL` row does not overwrite an
attempted miss elsewhere in the batch.

`stock_screener` forwards optional `finviz_filters` to narrow the TradingView-selected universe.
`stock_earnings` uses only TradingView or Yahoo for `next_earnings_date`, never Finviz's last
reported quarter. `stock_extended_hours` judges only the same pre/post session and requires dated
reads for agreement. Its overnight endpoint failures are appended to the envelope's `errors` rather
than replacing primary-provider errors. `technical_analysis` uses the resolved TradingView symbol
and venue rather than applying the default exchange to a bare ticker.

`stock_news` merges every news-capable feed, deduplicates across providers and
sorts newest-first. Each story names its providers, `provider_count` and
`consensus` (true when multiple providers carry the same event). Similarity
rules: same URL, same normalized headline, or at least four shared significant
words with Jaccard ≥ 0.55. Duplicates inside one provider are counted in
`duplicates_collapsed` and never upgrade to consensus; cross-provider agreement
is provider corroboration, not independent editorial verification. When fewer
than 10 unique stories exist, `count` is the real number, `shortfall_reason`
explains why, and the list is never padded with duplicates. TradingView's leg
needs `MARKETAUX_API_TOKEN`; without it that attempted leg reports `NO_DATA`
and the other feeds still supply their real headlines. StockAnalysis and Bloomberg have no symbol-news
adapter and do not contribute. `market_sentiment`, `combined_analysis` and `stock_why_moving` embed
the same merged block under both `data.news` and top-level `news` without re-attributing the primary
leg's provenance. `fields.news.source` is `null`; its `coverage` and `supplied` describe only valid
news contributors. Unparsable times remain `published_at: null` and sort last. If the Finviz
editorial leg fails, `data` is `null` and independent news remains only in top-level `news`.

**No general market tool requires an API key.** `market_sentiment` prefers Marketaux when
`MARKETAUX_API_TOKEN` is set, and otherwise scores Finviz headlines locally (VADER with a financial
lexicon). That path is deterministic, offline and free. Because the headlines are Finviz's, that
path is labelled `FINVIZ`; see [Sentiment](#sentiment-no-api-key-required). The separately named
Equibles tools require their own Bearer key. Their plan access is decided by the actual API
response, not by a local plan assertion.

### Finviz-only, served, labelled `FINVIZ`, explicitly single-source

`stock_filings` · `stock_ownership` (insider + institutional + short interest) · `stock_peers` ·
`stock_why_moving` (with merged latest-10 news block under `data.news`, single-source
editorial headline and summary) · `stock_chart` (PNG) · `stock_dilution` · `stock_screener_filters`

`stock_chart` carries `image_base64` and `mime_type: "image/png"` in its `data` object, so a remote MCP
client can decode the image without reading the server's filesystem. The best-effort `path` and
`image_path` are local to the server. One Finviz fetch supplies both forms; the local copy is optional,
and `null` with a warning if it cannot be written.

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
BLOOMBERG`, `cross_checked: false`, `reconciliation_leg: false`. The provider itself is a full leg of
`stock_quote` and `stock_prices`, where it is asked in parallel and its readings appear in
`comparisons` (see below). The distinction is the call, not the provider.

What these tools add is the government benchmark yield curve plus index, commodity and FX levels on
one board, which no other provider here publishes. `bloomberg_markets` says plainly that the board
carries no per-instrument print time, so nothing there is aged or ordered.

`bloomberg_quote` serves one page and discloses what that page is: `exchange_delay` /
`is_exchange_delayed` state the delay, and `print_time` comes from the last intraday point, never from
`lastUpdate` (`2026-11-05T01:00:00.000Z` on a page whose print was `2026-11-04T20:58:00Z`, which would
make a stale page win a freshness comparison). When that point does not match the quoted price,
`print_time` is null and `print_time_missing_reason` says why.

### Bloomberg as a reconciliation leg

In `stock_quote` and `stock_prices` Bloomberg is asked in parallel with every other provider,
contributes to `ALL` / `providers_answered`, and its reading sits in `comparisons[].values`. Three
facts keep that honest:

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
quietly missing. The leg also has a total budget (`TAPEBASIS_BLOOMBERG_BATCH_BUDGET`): once it is
spent the remaining tickers are named in `warnings` rather than waited out, so four tickers no longer
hold a batch open for four pacing intervals. `stock_quote` bounds the leg with
`TAPEBASIS_BLOOMBERG_QUOTE_DEADLINE`, so a slow or blocked page becomes a stated `TIMEOUT` /
`UPSTREAM_BLOCKED` error while the other readings still go out.

### StockAnalysis as a reconciliation leg

StockAnalysis is asked in parallel with every other provider on `stock_quote`, `stock_prices` and
`stock_extended_hours`, contributes to `ALL` / `providers_answered`, and its reading sits in
`comparisons[].values`. Three facts keep that honest:

- **It is a US feed.** The quote API serves US-listed equities and ETFs and answers `404` for
  indices, FX, crypto, commodities and foreign listings, so anything else is resolved as *not
  carried* and recorded as `NOT_ATTEMPTED` rather than sent to a route that cannot exist. There is no
  search endpoint either, so the slug is a mechanical rule: lowercase the US ticker and spell a share
  class with a dot (`BRK-B` becomes `brk.b`).
- **Its quote surface is the tape Yahoo already serves.** Price, previous close, session range and the
  52-week range are penny-identical to Yahoo's in measurement, so those two agreeing is one
  consolidated tape read twice. Treat it as corroboration of *coverage*, not as a second witness.
- **`ts` is epoch milliseconds.** It is converted to ISO in the access layer; passing it through would
  date every print to a century no market trades in and let it win every freshness comparison.

It adds the extended-hours block on the same request (served whole as
`stockanalysis_extended_hours`) and the session open/high/low that Finviz does not publish. It is
asked about every ticker in a `stock_prices` batch: its pacing absorbs a short list, so it needs no
cap like Bloomberg's.

### Equibles-only, official authenticated REST, labelled `EQUIBLES`

These tools read the documented `https://api.equibles.com/v1` API. There is no Equibles web scraping,
proxy through another provider or general price reconciliation. Rows stay in their original units and
filing scope inside named datasets.

| Tool | Datasets | Plan access |
| --- | --- | --- |
| `stock_fundamentals` | Company/listing profile, one income, balance or cashflow statement, optional annual revenue breakdown, debt profile and guidance versus actuals | Actual API response |
| `stock_analyst_estimates` | Verified analyst observations and snapshots with exact source metric, period, dimensions, unit, basis, statistic and publication fields | Actual API response |
| `stock_ownership_flows` | 13F ownership and activity, N-PORT fund owners, Form 144 proposed sales and optional Form 4 insider transactions | Actual API response |
| `stock_short_positioning` | FINRA short interest and facility volume, optional SEC fails-to-deliver and weekly off-exchange volume | Actual API response; no local paid-plan gate |
| `stock_options_analytics` | Option summary and term structure, including open interest, put/call ratios, max pain, implied volatility and expected move | Equibles Plus or Pro, confirmed by the actual response |
| `stock_price_history` | Stored daily, weekly or monthly OHLCV with split adjustment and provider-adjusted close | Actual API response; stored history, never a live-price leg |

Fourteen additional family tools expose the selected official JSON GET routes through an exact
`dataset` name and a `filters` object. There is no free-form URL parameter. `tapebasis_tool_map`
returns the local frozen dataset map, including every documented path/query filter, its type,
required flag and stated bounds. The complete map is in [Equibles datasets](docs/wiki/Equibles-Datasets.md).
Each dataset makes exactly one GET, with no automatic pagination or
provider fallback. Free, Plus and Pro access follows the account's real response.

| Family tool | Covered REST data |
| --- | --- |
| `equibles_company` | Profiles, financial reports, estimates, debt, valuation and company disclosures |
| `equibles_filings` | Filing directories, document passages, lines and full-text search |
| `equibles_investor_events` | Earnings calls, live transcripts, IR materials, events and IPOs |
| `equibles_ownership` | Insider, institutional, beneficial-owner and supply-chain disclosures |
| `equibles_institutions` | 13F filers, reported portfolios, consensus holdings and market activity |
| `equibles_positioning` | FINRA short positions and volume, FTD, off-exchange data and provider scores |
| `equibles_options` | Raw option chains and contracts, expirations, sessions and source calculations; Plus or Pro |
| `equibles_market_data` | Quotes, stored OHLCV, intraday bars, technical indicators and corporate actions |
| `equibles_funds` | Fund and ETF directories, holdings, profiles and annual operations |
| `equibles_macro` | FRED, Canadian observations, releases and CFTC positioning |
| `equibles_market_context` | Listings, indexes, advisers, screeners, calendars and market observations |
| `equibles_public_policy` | Congressional disclosures and government contract awards |
| `equibles_international` | International filings, ownership and native-report disclosures |
| `equibles_crypto` | Crypto directory, quotes, price history and intraday bars |

For example, `equibles_options(dataset="chain", filters={"ticker": "NVDA",
"expiration": "2026-12-18"})` returns the raw option chain under `data.chain`. The expiration filter
is optional and must use ISO `YYYY-MM-DD`. Use `equibles_company(dataset="financial_statement",
filters={"ticker": "NVDA", "statement": "income"})` for one raw statement.

Configuration and access:

- `TAPEBASIS_EQUIBLES_API_KEY` is the only local Equibles credential setting. There is no local
  paid-plan or redistribution assertion variable.
- The key goes only in the `Authorization: Bearer ...` header to the official origin. It never
  appears in a URL, response, error, provenance or diagnostic. Cache identity uses a short hash
  fingerprint, never the raw key.
- Without a key, every Equibles tool returns `NOT_CONFIGURED` before transport. A real `401` returns
  `NOT_CONFIGURED` with `access.status: auth_rejected`. A real `403` returns `PLAN_REQUIRED`; it
  never becomes empty or substituted data. If some datasets in an existing multi-block tool succeed,
  `access.status` is `partially_available` and `plan_required_datasets` names the denied blocks.
- The account's documented Free, Plus or Pro plan must permit its request. Normal Bearer keys are
  not intrinsically limited to Free. An opt-in check on 2026-11-18 succeeded for a company profile,
  while the account returned `PLAN_REQUIRED` for an options chain. No successful paid options
  response or publication right is thereby established. Hermetic tests do not verify a real account;
  the operator remains responsible for permitted use and redistribution.
- Redirects, undocumented paths, unknown filters, credential query parameters and CSV/binary output
  are refused. Live transcripts bypass the cache. General live-price tools do not call Equibles.

Every response, including missing-key, plan-denied, quota and upstream errors, carries exact
`Data by Equibles` attribution, `as_of`, per-dataset `freshness`, `reporting_delay` and `access`.
Unavailable datasets retain null observation timestamps and their delay definitions, not timestamps
invented from the local response clock. Filing, settlement and fiscal dates remain distinct. An
option `expiration` is a future schedule, never `as_of`.

Provider ratings, short-squeeze scores, predictions and AI briefs remain source-labelled facts, not
Tapebasis analysis. Analyst estimates are not mixed with rating or price-target populations.
`stock_options_analytics` stays separate from the multi-provider `stock_options_chain`.

Account-owned portfolios, organizations, custom data and web-feed tracker routes are outside this
surface. Institution-copy backtests and direct comparison of two institutions' portfolios remain
MCP-only upstream and have no REST bridge here. Exported binary/CSV outputs are also excluded.

Requests use one attempt per selected dataset. A daily-quota `429` retains public `X-RateLimit-*`
and reset metadata, never retries, and blocks new Equibles requests until reset. See
[Configuration](#configuration) for pacing and timeout settings.

### Ops

- `tapebasis_health`, run the probes now (`refresh=True`) or read the cached verdict. The Equibles
  probe checks local key and the last real response's public quota headers;
  it deliberately spends no upstream quota.
- `tapebasis_tool_map`, every tool with its providers and comparison strategy, without any
  upstream call.

---

## Rate limits are handled per provider

Every market-comparison upstream is undocumented and rate-limited by its owner, so every request goes
through a per-provider limiter ([`ratelimit.py`](src/tapebasis/ratelimit.py)). The documented
Equibles API uses the same pacing mechanism but a different quota rule: no retry after its daily
allowance is exhausted.

| Control | What it does |
| --- | --- |
| `min_interval` | Hard floor between two requests to one provider, so a 30-ticker fan-out is not a 30-request burst |
| `max_inflight` | Bounds concurrent requests per provider |
| shared cooldown | After a `429` (or a websocket `invalid symbol`) every caller waits an exponentially growing, jittered pause, so one blocked request protects the whole process |
| TTL cache | Absorbs the duplicate questions an agent naturally asks in one turn |

Each provider's requests share one pooled connection per event loop
([`http_pool.py`](src/tapebasis/http_pool.py)), so a warm call does not pay a TLS handshake before
every request. Pacing, not a fresh connection, is what keeps an upstream from blocking this server.

Yahoo is paced slowly (1 request at a time, 1 s apart) because it starts answering `429` after a short
burst; Bloomberg is slowest of all (10 s apart). TradingView's websocket treats `invalid symbol` /
`resolve error` as an IP-scoped block rather than a bad ticker, for the same reason. Current limiter
state is exposed by `tapebasis_health` and `GET /health` under `rate_limits`.

Defaults are tuned per provider and overridable; see [Configuration](#configuration).

---

## Sentiment: no API key required

`market_sentiment` has two backends, chosen at runtime. Both produce the same payload shape, and
the payload always says which one ran (`provider`, `scoring`, and the top-level `data_provider`).

| Condition | Backend | `data_provider` |
| --- | --- | --- |
| `MARKETAUX_API_TOKEN` set and usable | Marketaux entity sentiment (licensed) | `TRADINGVIEW` |
| no token, or Marketaux rejected/quota/outage | Finviz headlines scored locally (VADER) | `FINVIZ` |
| neither available | labelled empty payload, `sentiment_score: null`, `sentiment_label: Unavailable` | `NONE` |

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
balanced", so it is never used for "nothing could be fetched". When Finviz's headlines are
unavailable and Marketaux is rejected, `sentiment_score` becomes `null`,
`sentiment_label` becomes `Unavailable` and `data_provider` becomes `NONE`
(the news block still carries whatever feeds did answer). An invalid or expired
Marketaux token falls back to local scoring and records the reason in
`licensed_path_unavailable`; it does not report a neutral market.

`MARKETAUX_API_TOKEN` adds licensed TradingView/Marketaux headlines into the
merged `stock_news` feed (typically 3 per request on the free plan). Without it
the feed still merges Finviz + Yahoo with the same consensus and dedup rules.
News coverage is labelled separately and missing Marketaux coverage is reported.

---

## Upstream change detection

Every provider depends on things that can move without notice: Finviz's HTML class names and
unversioned `/api/*` JSON islands, TradingView's scanner POST schema and chart websocket protocol,
Yahoo's chart API shape, and StockAnalysis's quote API envelope.

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
| `sa.quote_api` | SA | `data.p` present in `/api/quotes/s/aapl` |
| `equibles.api_key` | EQUIBLES | Local key presence and last real response's public quota counters; makes no upstream request and does not prove plan access |

Bloomberg has **no network probe**, deliberately: its site gates plain HTTP clients on the TLS
fingerprint, so an `httpx` probe would report `DOWN` on a healthy provider. Its tool response is the
availability signal, and it still shows up under `rate_limits`. Equibles has only the local
configuration probe above: an upstream probe would spend the daily allowance that the health report
is meant to preserve, so a configured key is not presented as verified access.

Each successful probe records a SHA-256 fingerprint of the payload's key paths as a **baseline**
persisted to `~/.tapebasis/health_state.json`. Later probes compare against it, so a renamed
field is caught even if the endpoint still returns 200. Drift is judged on the **fields this server
reads**: each JSON probe declares its watched keys, and only one of those disappearing counts as
drift, because an upstream dropping a key nobody looks at is still serving every number correctly.
An added key is never drift, since a superset cannot break a parser.

Probes go through their provider's limiter like every other request, so the monitor paces itself on
the same upstreams the server paces. `tapebasis_health(accept_baseline=True)` re-records the current
shape after an upstream change you have checked and adapted to; a probe that is `DOWN` keeps its old
baseline. Verdicts:

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

<!-- mcp-name: io.github.giraygokirmak/tapebasis -->

Requires Python 3.10–3.13.

Run directly without cloning the repository. `uvx` creates the Python environment
isolated from the current project. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) first; Python 3.10–3.13 is selected from the package requirements.

```bash
uvx tapebasis --help
```

Or use the anonymous npm launcher with Node.js 18 or newer:

```bash
npx tapebasis --help
```

For a checkout or development build:

```bash
git clone https://github.com/giraygokirmak/tapebasis.git
cd tapebasis
# Install the checkout in a virtual environment.
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### stdio (Claude Desktop, most MCP clients)

```json
{
  "mcpServers": {
    "tapebasis": {
      "command": "npx",
      "args": ["tapebasis"],
      "env": { "MARKETAUX_API_TOKEN": "" }
    }
  }
}
```

The npm launcher calls `uvx tapebasis`, inherits its stdio and environment, and
requires uv on `PATH`. An alternative is `"command": "uvx", "args": ["tapebasis"]`.
The `mcp-name` marker above is used by the MCP Registry for PyPI ownership verification; the corresponding `mcpName` field in `package.json` does the same for npm.

### Streamable HTTP

```bash
tapebasis streamable-http --host 0.0.0.0 --port 8000
curl -s localhost:8000/health
```

## Docker

### Prebuilt image (GHCR)

A multi-arch image is published to the GitHub Container Registry as part of an approved `v*` release:

```bash
docker pull ghcr.io/giraygokirmak/tapebasis:latest
docker run -d --name tapebasis -p 127.0.0.1:6013:8000 \
  -v tapebasis-state:/home/mcpuser/.tapebasis \
  ghcr.io/giraygokirmak/tapebasis:latest
```

Main pushes build and check the image without publishing it. An approved `v*` tag publishes `<major>.<minor>.<patch>`, `<major>.<minor>`, `<major>` and `latest` from the image that passed the release checks. The manifest covers `linux/amd64` and `linux/arm64`. Pin a version tag for reproducible deployments.

### Build locally

```bash
cp .env.example .env      # optional; every setting has a default
docker compose up -d --build
curl -s localhost:6013/health
```

Compose publishes host port `6013` on `127.0.0.1` by default. The server is unauthenticated. Remote
exposure is a deliberate operator choice: set `TAPEBASIS_BIND_ADDRESS` to a routable address and put
an authenticating TLS reverse proxy in front of it. `TAPEBASIS_BIND_ADDRESS=0.0.0.0` publishes on all
host interfaces. The container itself still listens on `0.0.0.0`, which its port mapping requires.
The named volume `tapebasis-state` persists chart PNGs **and** the health baselines, so drift
detection survives restarts.

Standalone:

```bash
docker build -t tapebasis:latest .
docker run -d --name tapebasis -p 127.0.0.1:6013:8000 \
  -v tapebasis-state:/home/mcpuser/.tapebasis \
  tapebasis:latest
```

The image runs the server under `tini` as PID 1, so the container reaps the processes Docker starts
inside its namespace (`HEALTHCHECK`, `docker exec`) instead of accumulating zombies, and `docker stop`
is a graceful SIGTERM. Compose also sets `init: true`, which covers an image built without `tini`.
The build context ignores environment files, credentials, tests and caches. The runtime image carries
the installed package and its coinlists, not a copy of the checkout.

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
| `FINVIZ_CHART_DIR` | `~/.tapebasis/charts` | Chart PNG output, 32 generated files retained; inline base64 is primary |
| `TAPEBASIS_TV_MIN_INTERVAL` | `0.5` | TradingView request spacing (s) |
| `TAPEBASIS_TV_MAX_INFLIGHT` | `2` | TradingView concurrent requests |
| `TAPEBASIS_FINVIZ_MIN_INTERVAL` | `0.35` | Finviz request spacing (s) |
| `TAPEBASIS_FINVIZ_MAX_INFLIGHT` | `2` | Finviz concurrent requests |
| `TAPEBASIS_YAHOO_MIN_INTERVAL` | `1.0` | Yahoo request spacing (s) |
| `TAPEBASIS_YAHOO_MAX_INFLIGHT` | `1` | Yahoo concurrent requests |
| `TAPEBASIS_YAHOO_CACHE_TTL` | `15` | Yahoo quote cache lifetime (s) |
| `TAPEBASIS_SA_MIN_INTERVAL` | `0.5` | StockAnalysis request spacing (s) |
| `TAPEBASIS_SA_MAX_INFLIGHT` | `2` | StockAnalysis concurrent requests |
| `TAPEBASIS_SA_MAX_RETRIES` | `2` | Retries per StockAnalysis request |
| `TAPEBASIS_SA_TIMEOUT` | `20` | stockanalysis.com HTTP timeout (s) |
| `TAPEBASIS_SA_CACHE_TTL` | `20` | Quote cache lifetime (s); the upstream advertises a 3 s shared cache |
| `TAPEBASIS_BLOOMBERG_MIN_INTERVAL` | `10.0` | Bloomberg request spacing (s); the strictest limiter here |
| `TAPEBASIS_BLOOMBERG_MAX_INFLIGHT` | `1` | Bloomberg concurrent requests |
| `TAPEBASIS_BLOOMBERG_MAX_RETRIES` | `1` | Retries per Bloomberg request |
| `TAPEBASIS_BLOOMBERG_IMPERSONATE` | `chrome124` | Browser fingerprint `curl_cffi` presents to bloomberg.com |
| `TAPEBASIS_BLOOMBERG_TIMEOUT` | `30` | bloomberg.com HTTP timeout (s) |
| `TAPEBASIS_BLOOMBERG_CACHE_TTL` | `60` | Bloomberg page cache lifetime (s) |
| `TAPEBASIS_BLOOMBERG_QUOTE_DEADLINE` | `12.0` | Longest `stock_quote` waits for the Bloomberg leg before recording a `TIMEOUT` |
| `TAPEBASIS_BLOOMBERG_BATCH_MAX` | `4` | Tickers per `stock_prices` call asked of Bloomberg (its page path is paced at 10 s) |
| `TAPEBASIS_BLOOMBERG_BATCH_BUDGET` | `12.0` | Total seconds one `stock_prices` call spends on the Bloomberg leg before naming the rest in `warnings` |
| `TAPEBASIS_BLOCKING_THREADS` | `4` | Worker ceiling for the pool that runs blocking provider calls, separate from the loop's default executor |
| `TAPEBASIS_EQUIBLES_API_KEY` | - | Bearer credential for the official Equibles REST API; sent only in `Authorization` |
| `TAPEBASIS_EQUIBLES_MIN_INTERVAL` | `1.0` | Equibles request spacing (s) |
| `TAPEBASIS_EQUIBLES_MAX_INFLIGHT` | `1` | Equibles concurrent requests; a separate per-loop gate serializes each quota check and send |
| `TAPEBASIS_EQUIBLES_MAX_RETRIES` | `1` | Shared-limiter metadata only; Equibles transport always requests zero retries |
| `TAPEBASIS_EQUIBLES_CACHE_TTL` | `900` | Equibles cache lifetime (s); keyed by query and key fingerprint, never the raw key; live transcripts bypass cache |
| `TAPEBASIS_EQUIBLES_TIMEOUT` | `30` | Equibles HTTP timeout (s) |
| `TAPEBASIS_TV_MAX_RETRIES`, `TAPEBASIS_FINVIZ_MAX_RETRIES`, `TAPEBASIS_YAHOO_MAX_RETRIES` | `2` | Retries per provider request (the shared cooldown is not tunable) |
| `MARKETAUX_API_TOKEN` | - | Optional. Enables licensed Marketaux news + entity sentiment |
| `MARKETAUX_DAILY_BUDGET` | `90` | Marketaux request cap per day (free plan is 100) |

For security, do not put the Equibles key in an MCP argument, a custom URL, application JSON or a
shared log. Set only the environment variable in the server process, use a placeholder in
`.env.example`, and rotate the key if it was ever disclosed. Cached entries are keyed by a short
SHA-256 fingerprint rather than by the raw secret, and a failed HTTP response is
replaced with a sanitized error message rather than echoed upstream text. Redirects are refused so a
Bearer header cannot follow an upstream `Location` to a different origin.

The legacy `TRADINGVIEW_MCP_*` variables still tune the provider-layer technical-analysis services
while the scanner, websocket and every tool call go through the `TAPEBASIS_*` limiters above.

No proxy configuration exists: every provider reaches its upstream directly.

## Reading a response correctly

```
1. Check data_provider.
   ALL         -> quote the numbers; every provider asked answered.
   PARTIAL     -> quote them, but say a provider that was asked did not answer,
                  and read `errors` for which one and why.
   TRADINGVIEW -> quote them, but say the figure is single-source and not corroborated.
   FINVIZ      -> same, from the Finviz side.
   YAHOO       -> same, from the Yahoo side.
   SA          -> same, from the StockAnalysis side; US equities and ETFs only.
   BLOOMBERG   -> same, but find out why in comparisons: a delayed print is
                  reported as not_comparable with the delay named. Quote
                  exchange_delay / print_time before calling a price live.
   EQUIBLES    -> quote only the returned named datasets as single-source data.
                  Preserve Data by Equibles, as_of, reporting_delay and the
                  access state. A partial failure is not corroboration and
                  a denied dataset must not be silently omitted.
   NONE        -> say the primary value is unavailable. Do not invent one;
                  independently labelled news may still be available.

2. Check degraded / warnings.
   Non-empty -> tell the user an upstream API changed or is down, and that
                provider's figures may be stale or incomplete.

3. Check fields for per-field provenance when the response mixes sources
   (e.g. price.source is FINVIZ while price.supplied names four providers, and
   peers.source is FINVIZ alone). Read `supplied` for who answered and
   `compared` for whose reading was actually cross-checked; `agreement`
   describes only that second set. Composite `news` instead has `source: null`;
   read its `coverage`, `supplied` and the news block's own provider labels.

4. Check news separately for its coverage. Short lists report their real count
   and reason; consensus is provider corroboration, not editorial verification.

5. Check comparisons when you need to show how far apart the providers are.
   match: true  -> they agree within tolerance.
   match: false -> a real disagreement; every reading is in `values`.
   match: null  -> not comparable: no print time, a session/age difference, a
                   declared feed delay (Bloomberg's 15 minutes), or a field
                   with no shared definition (FX day change).

6. Check resolutions when a symbol behaved unexpectedly: it shows exactly which
   ticker each provider was asked for, and why.
```

## Latency: what is optimised, and what is not

Three things dominate a response, and only two of them are the server's to fix:

| Cost | Where it comes from | Handled by |
| --- | --- | --- |
| One HTTP handshake per request | A fresh client per call | One pooled client per upstream (`http_pool.py`), closed by the lifespan |
| Duplicate identical asks in one turn | No cache on a leg | A short TTL cache on every provider (`TAPEBASIS_YAHOO_CACHE_TTL` and its peers) |
| The slowest provider leg | Fan-out waits for every leg | Pacing bounds, not concurrency, so a slow leg is stated (deadline / budget) rather than hidden |

Measured on a warm process after those changes: the five legs run in parallel in ~1 s, a repeated
`stock_quote` answers in tens of milliseconds, and a repeated `market_indices` is served from cache.

What is **not** optimised is the pace itself. Yahoo is asked one request at a time 1 s apart, and
Bloomberg 10 s apart, because a faster knock rate turns into a `429` or a bot wall that outlasts the
burst. Pooling changes how expensive each knock is, never how often it happens.

Two costs stay visible instead of being papered over: a provider that does not answer inside its
deadline becomes a stated `TIMEOUT`, and a Bloomberg batch names the tickers its budget cut off in
`warnings`. A slow answer is reported, never silently dropped.

## Development


```bash
pip install -e ".[dev]"     # or, with uv: uv venv && uv pip install -e ".[dev]"
pytest                      # the hermetic suite, no network
pytest -m live              # opt-in: hits real upstreams
scripts/quality-gate.sh --commit   # tests plus the documentation checks
```

Tests mock at the HTTP boundary (`httpx.MockTransport`) and the provider-access boundary, so the
suite runs offline and deterministically, including the drift-detection tests that corrupt a stored
baseline and assert the warning reaches a normal tool response.

`scripts/quality-gate.sh` also checks the documentation: an undocumented function, a stale tool
count, a broken wiki link, an em dash, or a changed public signature with no documentation in the
same batch all fail it. The OpenCode plugin in `.opencode/plugins/quality-gate/` runs the same
script before a `git commit` or `git push` and refuses the command while it is red.

## Layout

```
src/tapebasis/
├── server.py             FastMCP instance, lifespan, /health, CLI
├── providers_state.py    DataProvider enum, errors, response envelope
├── reconcile.py          concurrent fan-out, comparison, freshness arbitration, notice text
├── freshness.py          market-print timestamps + freshest-print selection
├── ratelimit.py          per-provider pacing, shared cooldown, TTL cache
├── http_pool.py          one pooled HTTP client and resolver warm-up per upstream
├── merge_helpers.py      pure payload shapers (raw provider dict -> fields)
├── news.py               symbol news merge, per-story consensus and shortfall reporting
├── sentiment.py          token-free headline scoring (VADER + finance lexicon)
├── symbols.py            dynamic per-provider symbol resolution + index aliases
├── health.py             upstream probes, fingerprints, drift state
├── tv_access.py          typed access to TradingView's own data
├── fv_access.py          typed access to the Finviz provider
├── yh_access.py          typed access to the Yahoo Finance provider
├── bb_access.py          typed access to bloomberg.com (delayed leg + Bloomberg-only tools)
├── sa_access.py          typed access to stockanalysis.com (US equities and ETFs)
├── eq_access.py          allowlisted Equibles REST, Bearer secrecy, quota and freshness
├── eq_catalog.py          frozen Equibles routes, exact dataset/filter validation
├── equibles_surface.py    shared Equibles access, attribution and freshness contract
├── tools_equibles.py      six isolated Equibles tools with API access contracts
├── tools_equibles_families.py  fourteen grouped Equibles REST family tools
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
`scanner.tradingview.com`, its forecast page and its chart websocket; Finviz from `finviz.com` HTML and JSON islands;
Yahoo from `query1.finance.yahoo.com`; StockAnalysis from `stockanalysis.com/api/quotes`; Bloomberg
from `bloomberg.com/quote/...` and its market board, fetched with `curl_cffi` because the site gates
plain HTTP clients on the TLS fingerprint. Equibles comes only from its versioned authenticated REST
API and is never a leg in the comparisons above. Nothing is proxied through another provider. `sources`
records the primary quote upstream each leg used; the auxiliary forecast URL has its own
`analyst_targets.TRADINGVIEW.forecast_source`; its analyst block's `source` names the scanner.

Where a capability exists on only some providers, that is stated rather than simulated: options
chains come from Finviz and Yahoo (TradingView contributes only the underlying price), backtests run
twice on TradingView and Yahoo OHLCV, and Finviz and StockAnalysis are never asked for crypto, FX or
commodity quotes because neither carries them.

## Disclaimer

Market data is provided as-is for research and automation. It is not investment advice, and
scraped data can be delayed, incomplete or wrong. Cross-verification reduces the chance of a bad
number reaching you; it does not eliminate it.

## License

MIT. See [LICENSE](LICENSE).
