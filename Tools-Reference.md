# Tools Reference

35 tools. `providers` is the tool's **possible** provider set, not a promise about any single call:
an individual response can degrade to fewer providers if some fail. The per-call truth is always that
response's `data_provider` plus its `providers_answered`.

Ask the server for this list at runtime: `tapebasis_tool_map()` returns it without any upstream
call.

## Multi-source (13)

Every provider that can serve the field is asked, in parallel and natively; overlapping fields are
compared. These can return `ALL`.

### `stock_quote`

Quote plus fundamentals snapshot for any instrument class, equity, index, FX, commodity or crypto.

| | |
| --- | --- |
| Providers | TradingView scanner · Finviz quote page · Yahoo chart API · StockAnalysis quote API · Bloomberg quote page |
| Compared | price, change %, previous close, volume, session open/high/low, 52-week high/low, P/E, RSI(14) |
| Tolerances | price/prev-close/52-week/session range 0.5 % · change % 2 % · P/E 2 % · RSI 5 % · volume 1 % |
| Observation guards | price, change %, previous close, volume, session high/low/open: `max_skew_seconds = 900` and same US/Eastern session date; change %, volume and the session range also carry an 8 h age ceiling |
| Declared delay | Bloomberg's 15-minute equity/index delay is itself a comparability boundary: a pair that far apart is `not_comparable`, with the delay named |
| Never compared | change % on FX, where no shared previous close exists (reported from every provider) |

Each compared field resolves to one value, the newest print, while every reading stays in
`comparisons`. Finviz-only material rides along, labelled per field in `fields` (each descriptor's
`source` is FINVIZ): the 84-field
fundamentals snapshot, company profile, peers, the after-hours print, the classification chips
(`sector`, `industry`, `country`, `market_cap_class`, `exchange`, `etf_type`) and the
`income_breakdown` island. `resolutions` records the ticker each provider was asked for.

`day_open` comes from TradingView, Yahoo and StockAnalysis: Finviz has no Open row and Bloomberg's
page carries one only sometimes, so the field is compared where both sides publish it rather than
against a provider that never had it. `feed_mode` (`streaming`, `delayed_streaming_900`) states the
scanner's own delay, the same fact Bloomberg's `exchange_delay` reports for its leg. `pe_ratio` has no
StockAnalysis getter: its quote API carries price, range, volume and the 52-week range, and P/E lives
on a separate stock page this tool does not fetch.

Symbol resolution only decides who can be asked. Once a symbol resolves, an empty provider response
remains a visible `NO_DATA` error; it is not reclassified as `NOT_ATTEMPTED` merely because the
symbol is absent from that provider's payload.

`data.session` (also at the envelope level) names the window `data.price` is a print from:
`pre_market`, `regular`, `post_market` or `overnight`, and `data.price_field` names the provider field it
was read from. Each provider's live print is resolved before comparison, because the obvious price field
goes stale the moment the regular session ends:
TradingView's `close` is the regular feed's last trade while its `premarket_close` keeps streaming,
Yahoo's `regularMarketPrice` freezes while `fulldayPrice` does not, and StockAnalysis keeps the regular
close in `price` and the current extended print in `extended_hours`. Reading the obvious field is what
let a quote sit hours behind the market and still be labelled current. The day change and the previous
close move with the price, so a row's three numbers describe one session rather than mixing a live
price with a baseline from two sessions back.

The session is taken from the winning provider's own print, never from another leg's label. A delayed
feed states the session it is in, and while it lags that statement describes a print the row is not
serving: measured at 09:42 ET, the scanner still said `pre_market` because its feed is 15 minutes
delayed, while the winning print was a regular-session one. Labelling from the scanner made
`stock_quote` and `stock_prices` name different sessions for the same symbol at the same moment.

#### `income_breakdown` (a field of `stock_quote`)

The Finviz "Revenue & Expenses Breakdown" table and the product / region / segment revenue split ship
as a JSON island on the quote page `stock_quote` already fetched, so reading it costs no extra
request. It is not a separate tool: it is served inside `stock_quote`'s payload as
`income_breakdown`, labelled `FINVIZ` per field.

`statement` holds up to two fiscal years of revenue, gross profit, operating income, net income and
the expense lines between them. Its amounts are published in millions and are scaled to absolute
currency units here; `statement.scale_applied` states the factor, and `statement.currency` the unit.
Bank filers swap the row set (interest income, loan loss provision, non-interest expense) and have no
`Total Revenue` row, which is served as it arrives.

`revenue.axes` holds up to three annual series: `products_and_services`, `regions` and `segment`. Which
exist varies by company, and their meaning is company-specific (Apple's `segment` is geographic,
NVIDIA's is operating segments), so the keys stay as Finviz sends them. Each axis carries `unit` and
`converted`; `converted: true` means Finviz FX-converted the amounts into the filing currency. An ETF
has no island at all, so the field is `null` and the quote is unaffected.

Because symbols are resolved per provider, `XAUUSD` reaches `OANDA:XAUUSD` on TradingView and
`XAUUSD:CUR` on Bloomberg, is correctly reported as not carried by Yahoo, Finviz and StockAnalysis,
and the response is `ALL` over the two that answered rather than `NONE`. Indices and commodities
(gold, silver, WTI, Brent, copper, natural gas, spot and front-month futures) are addressed through
the instrument registry in `symbols.py`, so `WTI` reaches TradingView as `FX:USOIL`, never as
`NYSE:WTI` (an equity whose ticker happens to match), and `CL1!` reaches Yahoo as `CL=F` and
Bloomberg as `CL1:COM`.

Bloomberg and StockAnalysis are asked in parallel like the others, so `providers_answered` can hold
every label and `comparisons[].values` every reading. Bloomberg's delayed print is bounded two ways:
it is last in the freshness tie-break, and a pair a delay length apart is reported as
`not_comparable` instead of as a disagreement. `exchange_delay` / `print_time` ride along in `data`,
so the delay is visible without reading the comparison detail. StockAnalysis covers US equities and
ETFs only, so it is `NOT_ATTEMPTED` for indices, FX, crypto, commodities and foreign listings; its
price surface is the same consolidated tape Yahoo serves, so that pair is weak corroboration. Its
extended-hours block rides along as `stockanalysis_extended_hours`.

### `stock_prices`

Bulk quotes for a ticker list.

Each row carries its own `data_provider`, `providers_answered` and an `agrees` verdict, one ticker can
be `ALL` while another is single-source or `NONE` in the same response. `agrees` is `true` only when
at least one compared field agreed and none disagreed, `false` on a real conflict, and `null` when
both price and change percent reached no verdict. Multi-source rows also carry `price_source` (whose
print the single `price` came from), a `fields` map and their own `comparisons` and `freshness`
blocks.

Every row exposes `misses` and `errors` for its failed or uncarried providers, not just rows where
every provider came up empty. Error entries include `provider`, `symbol`, the original `code` and the
`message`; an omitted batch row is `NO_DATA`. A provider-wide empty response is also `NO_DATA`, never
`NOT_ATTEMPTED`. A returned payload without a usable price is also `NO_DATA`, never coverage.
The envelope aggregates the symbol-tagged failures, and its coverage and comparison notice are
derived from the actual provider-symbol outcomes. A complete `ALL` row does not mask an attempted
miss for another ticker: the envelope is `PARTIAL` while every provider supplying a row still
appears in `providers_answered`. The FX day change is reported but never compared, exactly as in
`stock_quote`.

Each row also names its `session`, the window its `price` is a print from, and the `price_field` it was
read from. The price itself is the live print rather than the obvious field: TradingView's scanner
`close` stops moving when the regular feed's last trade falls behind the market while `premarket_close`
keeps streaming, Yahoo's `regularMarketPrice` freezes while `fulldayPrice` does not, and StockAnalysis
keeps the current extended print in its own block. The row's `change_percent` and `previous_close` are
measured against the same session's baseline, so the row's own three numbers are consistent. Before
this, a pre-market price could be paired with a close two sessions old, implying a day change that
neither the `change_percent` beside it nor any provider reported.

`fields` states provenance per value, because `data_provider` describes the row rather than each
number in it:

```jsonc
{
  "price": { "source": "YAHOO", "compared": ["TRADINGVIEW", "FINVIZ", "YAHOO"], "agreement": true },
  "change_percent": { "source": "YAHOO", "compared": ["TRADINGVIEW", "FINVIZ", "YAHOO"], "agreement": true },
  "previous_close": { "source": "YAHOO", "compared": ["YAHOO"], "agreement": null },
  "volume": { "source": "TRADINGVIEW", "compared": ["TRADINGVIEW"], "agreement": null }
}
```

A row can read `ALL` while `previous_close` was shaped by one provider. Only `price` and
`change_percent` are compared, so only those carry an agreement verdict and a `compared` list of every
provider that supplied a reading. The rest name the one provider whose value was used, chosen
freshest-print-first: an uncontested field comes from whichever provider has it and can date its
print, with the documented order breaking a tie on the same instant. A provider with no usable print
time cannot outrank one that has it. `price_source` remains as the row-level shorthand for the
provider the compared values were taken from.

Bloomberg is asked about at most four tickers per call (`TAPEBASIS_BLOOMBERG_BATCH_MAX`), because its
page path is paced at 10 s per request. The rest are listed in `warnings` and are not counted as
Bloomberg-answered for those rows: coverage stays truthful per row. StockAnalysis is asked about every
ticker: its pacing absorbs a short list, so it needs no cap, and a symbol it does not carry is
recorded as `NOT_ATTEMPTED` for that row.

### `stock_screener`

US equity screener, cross-checked on the same instruments.

TradingView ranks the whole market server-side (`sort_by` ∈ `market_cap`, `dividend_yield`, `change`,
`price`). Finviz is then asked about **exactly the tickers TradingView returned**, and the price is
compared at 0.5 %. The optional `finviz_filters` expression is forwarded to Finviz to narrow this
selected universe; its usual filter validation applies. The option never replaces the TradingView
ranking with an independent Finviz universe.

Asking Finviz for its own independent ranking would compare two unrelated universes: a market-cap
ranking against a day-%-change ranking shared zero rows on every call, so the "multi-source" screen
was silently single-source. `cross_checked_rows`, `agreeing_rows` and `not_comparable_rows` summarise
the result.

Finviz screener rows carry no print time, so a per-row match cannot be *proven* to describe the same
session. Those rows are reported as `not_comparable` (not as agreement), and the envelope warns that
no row could be confirmed. Yahoo has no screener endpoint, so it is not asked.

### `market_indices`

S&P 500, Dow, Nasdaq Composite, Russell 2000, IWM and VIX levels, keyed by canonical name (`SPX`,
`DJI`, `COMP`, `RUT`, `IWM`, `VIX`).

| | |
| --- | --- |
| Providers | TradingView `SP:SPX`/`DJ:DJI`/`NASDAQ:IXIC`/`TVC:RUT`/`TVC:VIX` · Finviz indices feed · Yahoo `^GSPC`/`^DJI`/`^IXIC`/`^RUT`/`^VIX` |
| Compared | index level, 0.5 % (VIX 3 %, because a volatility gauge moves percent-level within a minute) |
| Not compared | day-change %, reported from every provider, derived from different reference closes |

Each level resolves by the same newest-print rule as a quote, and levels are only compared between
providers whose prints share a session. A provider that has rolled into the next session is *newer*
not wrong; its level is the one shown, and the session-date guard keeps yesterday's close from being
reported as a data conflict.

Finviz quotes indices only through its indices feed, not a per-ticker page, `/stock?t=SPX` is a 404
and `COMP` there is Compass Inc, a real equity. So `resolutions` reports Finviz as not carrying an
index ticker, while `market_indices` still uses Finviz's indices feed for the level.

`RUT` (index) and `IWM` (its tracking ETF) are different instruments at different price levels and
are never cross-compared.

The list is fixed (`INDEX_SNAPSHOT`), and the registry being broader does not extend it: `NDX` is a
registry row addressable through single-instrument tools (`stock_quote NDX`), but it is not part of
the snapshot.

Each index carries its own `fields` map and `data_provider`. The day-quote block (level, previous
close, change, change percent) is filled from providers whose print belongs to the winner's session
date, so a row is always one observation: a provider from another session never lends a number. When
the winning provider's session has no previous close to report, the field is `null` rather than
borrowed from the other session, which is the behaviour that stopped a level and its previous close
contradicting each other on the page.

### `stock_news`

Ticker headlines, matched by title across the feeds.

Finviz supplies price reactions around each item; Yahoo supplies its own search feed. The TradingView
leg is the provider's licensed Marketaux feed and needs `MARKETAUX_API_TOKEN`; without it that leg is
`NOT_ATTEMPTED` and the response is labelled with the feeds that did answer.

Sentiment does **not** need the token, see [`market_sentiment`](#market_sentiment).

### `stock_options_chain`

Options chain for one expiry, from Finviz and Yahoo, with the underlying price confirmed by
TradingView's scanner (TradingView publishes no chain).

Contracts are matched by side, expiry and strike; volume is compared at 5 %, open interest at 1 %
when both report it. Finviz carries full greeks. A missing side, expiry or strike cannot establish a
match and never counts as agreement. A contract-level expiry takes precedence over its chain-level
expiry, which supplies the date only when the contract does not carry one.

With no explicit expiry, each provider chooses its nearest expiry independently. If those dates differ,
`data.expiry` is `null` and `data.overlap` carries `not_comparable: true` with both dates in its reason;
the contracts are not compared. When both chains establish the same date, including an explicitly
requested shared expiry, comparison proceeds normally. `data.expiries` names the providers separately
when their available-expiry lists differ.

Missing activity fields stay `null` and a reported zero stays zero in normalisation and comparison;
neither falls through to another field or becomes a synthetic zero.

Yahoo reports zero open interest for contracts expiring the same day, so a `0 vs N` pair is counted
under `open_interest_unavailable`, not as a mismatch.

### `stock_earnings`

Earnings dates, reported-quarter history, estimate revisions and post-earnings price reactions.

Finviz owns the detailed tables; its `earnings_date` is the **last reported** timestamp, which is why
it is returned as `finviz_earnings_date`, separate from `next_earnings_date` (the upcoming release
from TradingView or Yahoo). Finviz never serves as a fallback for the next date: when both calendars
have no upcoming timestamp, were not attempted, or failed, `next_earnings_date` is `null`. A
historical report cannot be reported as a future event.

### `stock_extended_hours`

Pre-/post-market price from every independent source that publishes one: TradingView's
`premarket_*`/`postmarket_*` scanner columns, Finviz's after-hours print, Yahoo's 1-minute
extended-hours candles, and StockAnalysis's extended-hours block. The after-hours price is compared
at 0.5 %. Each provider's `after_hours_readings` entry carries `price`, `session`, `timestamp`, a
normalized UTC `as_of_utc` when parseable, `reference_close`, `change`, `change_percent` and
`change_reference`. A missing baseline or print time
stays null. Only like pre-market or post-market windows can be judged. Differing named sessions are
`not_comparable`, and agreement on a shared window requires a usable `as_of_utc` or `price_timestamp`
from both providers in that pair. An undated TradingView print therefore cannot veto a dated
Yahoo/StockAnalysis pair; it remains visible with `match: null` only in its own pairs. StockAnalysis's
pre/post label is retained even if it supplies no timestamp. Yahoo's `as_of_utc` is seconds-preserving,
timezone-aware ISO from the candle, not a string the freshness parser has to guess.

Each session block carries the session's `volume` when the feed reports one, so a pre-market print
can be told apart from a single lot. Yahoo's pre-market reference comes from `reference_close`, its
post-market print from the regular block alongside it. StockAnalysis reads its extended
`previous_close`, Finviz its snapshot's `Prev Close` before falling back to its own extended
change arithmetic, and TradingView recovers the close from its extended print and reported change.
A missing Finviz session or print clock stays null without suppressing that available baseline;
its pairs remain unjudged. These are provider-owned baselines, not an overnight Yahoo baseline
borrowed for a pre/post print. StockAnalysis's block is also served whole as
`stockanalysis_extended_hours`, next to `stockanalysis_regular_close`.

`stock_quote` does not itself return the independent BOATS `overnight` block. Request
`stock_extended_hours` when that session is needed; adding those separate upstream calls to every
quote remains a distinct contract expansion, not part of this metadata repair.

`data.session` names the window the instrument is in right now (`pre_market`, `regular`,
`post_market`, `overnight`), so a caller asking "pre or post" does not have to infer it from which block
happens to be populated. It comes from TradingView's own `current_session` statement, with the newest
Yahoo block as the fallback.

The `overnight` block is the 20:00-04:00 ET window that Blue Ocean ATS trades. It is read natively
through TradingView's `BOATS:` quote websocket and Yahoo's `/v7/finance/quote` request with
`overnightPrice=true`. TradingView's scanner has no BOATS row, and Yahoo's 1-minute chart stops at
after-hours, so neither is substituted for the venue's print. Yahoo uses its `overnightMarketPrice`,
`overnightMarketChange`, `overnightMarketChangePercent` and `overnightMarketTime` quote fields, with
`regularMarketPrice` as the overnight change reference. Yahoo publishes no overnight volume on that
header, so its volume is null rather than inferred from regular trading.

`overnight_source` names the provider whose newest eligible print is in `overnight`. Each provider block
stays in `overnight_readings`, including `print_time`, seconds-preserving ISO `as_of_utc`, the 20:00 ET
window start in `session_window_start_utc`, `is_current`, and venue identity when reported. On prints
sharing that evidenced occurrence, every block's `change` and `change_percent` are calculated from
Yahoo's `reference_close`; `change_reference` states `YAHOO.reference_close`. TradingView's original
BOATS `ch` and `chp` readings remain separate as `reported_change` and `reported_change_percent`, since
they use a different venue baseline. If Yahoo is absent, the reference is invalid, or the occurrences
cannot be shown to match, the normalized change and reference fields are null rather than borrowed from
another close. The reported TradingView fields are still retained.

`overnight_comparison` compares only prints from that same overnight occurrence with usable,
sufficiently close timestamps. These are two readers of one BOATS venue, not independent market venues.
`overnight_errors` reports a failed secondary
endpoint; those errors are appended to the envelope's `errors`, so a `null` overnight block is not
silently indistinguishable from venue no-data. The primary pre/post comparisons remain independent.

Every overnight block carries `is_current` and the aggregate has `overnight_is_current`. After 04:00 ET
the last BOATS print remains available as the last overnight observation with `is_current: false`,
but is not called the live print and cannot displace a pre-market price. TradingView's `out_of_session`
and `streaming` labels alone do not assert that the venue is still trading.

TradingView quote `qsd` frames are deltas. They are merged into the preceding symbol snapshot rather
than replacing it, so a later frame carrying only `lp_time`, volume or another field cannot delete a
price already received. A quiet empty socket is not cached, and receive or rate-limit failures keep
a typed provider error instead of silently becoming `overnight: null`.

Yahoo's candles are requested over two days, not one: `range=1d` stopped returning a `timestamp`
array, so every call reported `NO_DATA` with "unexpected response shape: 'timestamp'" and the session
timeline silently disappeared. Each candle is classified against the session windows of the day it
falls in, which keeps yesterday's regular prints out of today's pre-market block.

### `technical_analysis`

Full indicator stack from TradingView (RSI, MACD, EMAs, Bollinger, ATR, ADX, structure, trade setup).
The request uses the resolved TradingView symbol and venue, including an `EXCHANGE:TICKER`
resolution; the caller's default exchange cannot route a resolved ticker to the wrong venue. If a
resolved symbol has no venue and no exchange prefix, the `exchange` argument remains the fallback.
Finviz's snapshot and Yahoo's chart API independently confirm four headline readings in `cross_check`:
price (0.5 %), RSI(14) (12 %), ATR(14) (10 %), volume (2 %).

The three price-and-price-derived readings are guarded by print time: TradingView's scanner
`update_time`, Finviz's rendered print time and Yahoo's `market_time` are compared, so two prints from
different sessions are reported as `not_comparable` rather than as a conflict. RSI and ATR are
lookback statistics and are judged without a timestamp guard.

Volume is reported from every provider but never compared: Finviz's snapshot counts the current
partial session while the consolidated feeds report the last completed one, so the two numbers answer
different questions. That is stated in `cross_check.volume.pairs[].not_comparable` rather than
presented as a disagreement.

### `stock_backtest`

A single strategy, run **twice**, once on TradingView's chart-websocket OHLCV, once on Yahoo's chart
OHLCV, then compared. Finviz is not asked: it has no history endpoint.

Compared: total return (1 %), win rate (2 %), trade count (exact), max drawdown (2 %), Sharpe (5 %),
buy-and-hold return (1 %). Identical candles produce identical metrics; a divergence means the two
feeds disagree about the instrument's history, which is worth knowing before trusting either.

For RSI, Bollinger, MACD, EMA cross, Supertrend, RSI pullback, Keltner breakout and triple EMA, a
signal is evaluated only after its bar closes and the entry or exit fills at the following bar's open.
A signal on the final close cannot open a new position. A final bar with no following execution bar
still force-closes an open position at its close and flags that exit in the raw trade list. The
optional per-trade log carries the same execution prices; per-bar equity marking includes the entry
bar's close and applies net costs at exit.

Donchian retains its separate assumption: an intrabar high/low breakout fills at that bar's close.
This is not a close-confirmed signal model, but final-bar entries are suppressed there too. The
`execution_model` block names the mode, signal-to-fill rule, final-bar rule and forced-exit treatment
instead of requiring callers to infer them. It is present on single backtests, comparisons and
walk-forward results.

### `stock_backtest_compare`

The full strategy leaderboard, also computed on both feeds. Adds `winner_comparison`, the winning
strategy on TradingView, the winner on Yahoo, and whether the two feeds pick the same one.

### `market_snapshot`

Global FX, crypto, index and ETF snapshot from TradingView's scanner and Yahoo's chart API, group by
group. Finviz has no equivalent breadth, so it is not asked.

Rows join by the *requested* ticker, not by the symbol the upstream reports back: Yahoo answers both
`JPY=X` and `USDJPY=X` with `meta.symbol: "JPY=X"`, which used to split one instrument into two rows.
Each row carries both providers' prints and an `agree` flag. `all_groups_agree` summarises the whole
snapshot.

For a cross-checked *index* read, use `market_indices`.

### `combined_analysis`

TradingView technical read + sentiment + news, with the underlying price cross-checked against
Finviz's snapshot and Yahoo's chart API. One request, not one per leg.

The price leg is genuinely multi-source; the analysis and sentiment legs remain single-source and are
labelled per field in `fields` (their `source` is TRADINGVIEW). `sentiment_source` states whether
the sentiment came from Marketaux or
local scoring.

---

## Finviz-only (7)

Served, labelled `FINVIZ`, explicitly single-source. No other provider has a comparable dataset, so
those legs are marked `NOT_ATTEMPTED`, which is **not** an error and is excluded from `errors`.

| Tool | Capability | Notes |
| --- | --- | --- |
| `stock_filings` | SEC filing history | Finviz's SEC feed |
| `stock_ownership` | Insider + institutional ownership, short interest | Several datasets; a failing one is reported without losing the others |
| `stock_peers` | Peer-group companies | No provider has a curated peer list |
| `stock_why_moving` | Narrative explainer for a price move | Finviz editorial feed |
| `stock_chart` | Rendered PNG candlestick chart | TradingView produces text analysis, not images |
| `stock_dilution` | Dilution risk model (share count, float, cash runway) | Finviz only models dilution-prone companies; others return `NONE` with that reason |
| `stock_screener_filters` | Finviz screener filter catalogue | Finviz's proprietary filter vocabulary |

### `stock_chart`

The normal MCP JSON envelope contains `data.image_base64`, `data.mime_type: "image/png"`,
`data.bytes` and chart dimensions. Decode `image_base64` to obtain the PNG. A remote client does not
need filesystem access. `data.path` and the convenience field `image_path` carry the same
server-local path when a local copy can be written; that path is not a URL and is secondary to the
inline image. A write failure returns the inline image, a `null` path and a warning.

`fv_access.chart` calls `chart_service.get_chart_base64`, which makes one Finviz request and writes
the resulting bytes to local storage when possible. It does not call `download_chart` for a second
copy. At most 32 service-generated PNGs are retained, ordered by modification time. Unknown files in
the chart directory are never deleted. The existing `download_chart` path-only service remains
available for callers that explicitly do not want base64 in the response.

### `market_sentiment`

Two backends, selected at runtime, same payload shape:

| Condition | Backend | Label |
| --- | --- | --- |
| `MARKETAUX_API_TOKEN` set and usable | Marketaux entity sentiment (licensed) | `TRADINGVIEW` |
| no token, or Marketaux rejected/quota/outage | Finviz headlines scored locally (VADER) | `FINVIZ` |
| neither available | labelled empty payload, `sentiment_score: null` | `NONE` |

Both paths are single-source by nature: there is nothing to cross-check a sentiment score against,
so the label names whichever feed supplied the headlines.

The local path is labelled `FINVIZ` because the **headlines are Finviz's**, only the scoring is
ours. Labelling it `TRADINGVIEW` would claim a provenance the data does not have.

`sentiment_score: null` (not `0.0`) means "nothing could be scored". `0.0` means "the tone is
balanced". Conflating them would dress a data gap up as a finding. Full detail:
[Sentiment](Sentiment).

---

## TradingView-only (10)

Served, labelled `TRADINGVIEW`, explicitly single-source, no other provider has the dataset.

| Tool | Capability | Why nobody else can confirm it |
| --- | --- | --- |
| `crypto_top_movers` | Crypto gainers/losers | Finviz does not cover crypto; Yahoo has no movers endpoint |
| `crypto_bollinger_scan` | Bollinger squeeze scan | Same |
| `crypto_volume_breakout` | Volume + price breakout scan | Same |
| `crypto_multi_timeframe` | Multi-timeframe crypto analysis | Same |
| `crypto_multi_agent` | Multi-agent bull/bear debate | Same |
| `futures_market_overview` | Futures overview by category | Neither other provider has futures |
| `futures_top_movers` | Futures gainers/losers | Same |
| `futures_watchlist` | Curated futures watchlist with levels | Same |
| `bitcoin_market_pulse` | Bitcoin trend and volatility pulse | Composite of the crypto scans above |
| `egx_market_overview` | Egyptian Exchange overview | No EGX coverage elsewhere |

Note that crypto and futures *quotes* are multi-source, `stock_quote("BTCUSD")` asks TradingView and
Yahoo. It is the scan/analysis endpoints that are TradingView-only.

---

## Bloomberg-only (2)

These tools ask Bloomberg and nobody else, so their responses are single-source by construction:
`data_provider: BLOOMBERG`, `cross_checked: false`, `reconciliation_leg: false`. The provider itself
is a full leg of `stock_quote` / `stock_prices`, where it is asked in parallel and its readings
appear in `comparisons`. What these two tools add is Bloomberg's own quote page and its market board.

| Tool | Capability | Notes |
| --- | --- | --- |
| `bloomberg_quote` | Bloomberg's own quote page for one instrument | `print_time` from the last intraday point, never `lastUpdate`; `exchange_delay` states the delay |
| `bloomberg_markets` | Index levels, government benchmark yields, commodities, FX | The only source here of a government yield curve; the board has no per-instrument print time, so nothing is aged or ordered |

### `bloomberg_quote`

For a corroborated price use `stock_quote`, which asks Bloomberg too and compares it. Use this when
the caller wants Bloomberg's reading specifically, or a figure only Bloomberg publishes.

| | |
| --- | --- |
| Providers | `bloomberg.com/quote/<id>` HTML, `__NEXT_DATA__` payload |
| Compared | nothing: this tool asks one provider |
| Delay | `exchangeDelay` (15 Minutes on equities), echoed as `exchange_delay` / `is_exchange_delayed` |
| Print time | `priceMovements1Day[-1].dateTime`, and only when that point's value matches the quoted price |
| Never used | `lastUpdate`, a session sentinel (`...T01:00:00Z`) that is later than the real print |

`print_time: null` with `print_time_missing_reason` is the honest answer when the intraday series
ends somewhere other than the quoted price: a timestamp describing a different number is not a print
time. Symbols resolve through the instrument registry plus a curated alias table (`SPX` to `SPX:IND`,
`EURUSD` to `EURUSD:CUR`, `BRK.B` to `BRK/B:US`), because Bloomberg answers a bad id with a 403 bot
page rather than a 404.

An instrument the registry states Bloomberg does not carry is refused with that reason instead of
being guessed. `WTI` is a spot series with no Bloomberg quote page, and the mechanical fallback
`WTI:US` is W&T Offshore Inc, a different company; `USOIL` resolved to `USOIL:US`, which answers a
robot page. The response is `NONE` with a `NO_DATA` error naming the boundary, and no request is
made. The same identity function decides what the cross-checked tools report, so the id in
`resolutions` is always the id that was fetched.

### `bloomberg_markets`

The board carries 20 rows on one page: index levels, ten government benchmark yields, crude, gold and
FX. The yield curve is the capability no other provider here publishes. There is no per-instrument
print time on the board, so the response says so and no reading is aged or ordered. Treat every level
as a snapshot, not a live tape.

---

## Ops (2)

| Tool | Purpose |
| --- | --- |
| `tapebasis_health` | Read the cached drift/outage verdict and per-provider rate-limit state, `refresh=True` to probe now, or `accept_baseline=True` to accept the shape being served |
| `tapebasis_tool_map` | Return this catalogue with no upstream call |

---

## Choosing a tool

| You want | Use | Multi-source? |
| --- | --- | --- |
| One stock's price and fundamentals | `stock_quote` | Yes, on the quote fields |
| A crypto or FX quote | `stock_quote` | Yes where both carry it (FX day change excepted) |
| Many stocks' prices | `stock_prices` | Per row |
| A market scan | `stock_screener` | On price, per row |
| Index levels | `market_indices` | Yes |
| Headlines | `stock_news` | Overlap only |
| How the market feels | `market_sentiment` | No (single-source by nature) |
| Options positioning | `stock_options_chain` | On volume/OI |
| Filings, ownership, peers | `stock_filings`, `stock_ownership`, `stock_peers` | No |
| Government bond yields | `bloomberg_markets` | No, Bloomberg-only |
| Bloomberg's own quote reading | `bloomberg_quote` | No: one provider asked, delay-labelled |
| Crypto / futures scans | `crypto_*`, `futures_*` | No |
| Strategy validation | `stock_backtest`, `stock_backtest_compare` | Yes, two OHLCV feeds |
| Everything about one stock | `combined_analysis` | Price leg only |

## Related

- [Response Contract](Response-Contract): how to read any of these
- [Design Decisions](Design-Decisions): why some tools are single-source by nature
