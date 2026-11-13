# Response Contract

Every tool returns the same envelope. Learn it once and every tool is readable.

## The eight provider states

| `data_provider` | `verification` | Meaning | What an agent should do |
| --- | --- | --- | --- |
| `ALL` | `MULTI_SOURCE` | Every provider that was asked answered | Quote the numbers; `fields` names which provider each value came from, `providers_answered` the legs that answered |
| `PARTIAL` | `MULTI_SOURCE` | More than one answered, but at least one provider that was asked produced nothing | Quote the numbers, say a provider was asked and did not answer, and read `errors` for why. Coverage is not complete |
| `TRADINGVIEW` | `SINGLE_SOURCE` | Only TradingView answered | Quote, but say it is single-source and not corroborated |
| `FINVIZ` | `SINGLE_SOURCE` | Only Finviz answered | Same, from the Finviz side |
| `YAHOO` | `SINGLE_SOURCE` | Only Yahoo Finance answered | Same, from the Yahoo side |
| `SA` | `SINGLE_SOURCE` | Only StockAnalysis answered | Same; note it covers US equities and ETFs only |
| `BLOOMBERG` | `SINGLE_SOURCE` | Only Bloomberg answered | Same, but state `exchange_delay` / `print_time` before calling a price live |
| `NONE` | `UNAVAILABLE` | No provider answered | Say no data is available. Do not invent one. |

`verification` is derived, never independent: `ALL` and `PARTIAL` → `MULTI_SOURCE`, a single provider
`→ SINGLE_SOURCE`, `NONE → UNAVAILABLE`.

**`ALL` means every provider that was asked answered, and `PARTIAL` is the honest label when one did
not.** A provider that was asked and failed is still part of the ask set, so a response carrying its
error cannot claim `ALL`: that would state complete coverage while the same payload lists the
failure. `PARTIAL` says the values are served but a leg was asked and produced nothing, and
`errors` names it. A provider that was never asked (no endpoint for this request) is recorded as
`NOT_ATTEMPTED` and does not affect the label at all.

**`ALL` does not mean "the values agree".** It means every provider *asked* answered. Agreement is a
separate axis, reported per field in `comparisons[].match` and summarised in `notice`/`warnings`.
Providers answering but diverging is still `ALL`, with the conflict named.

**`ALL` never applies to a single value.** `data_provider` describes the call's coverage; each value
in `data` came from exactly one provider, and `fields.<field>.source` says which. Four providers
answering means the price was cross-checked four ways, not that `data.price` is a number four
providers produced together.

**`ALL` does not mean every provider in the catalogue.** A tool asks only the providers that could
serve the field. If TradingView and Yahoo answer and Finviz has no page for the instrument, that
response is `ALL`: every provider *asked* answered. `providers_answered` lists exactly which ones
contributed, so coverage can be read precisely.

**`ALL` can include Bloomberg and StockAnalysis.** Both are entries in `PROVIDER_ORDER`, so
`stock_quote` and `stock_prices` ask them in parallel and they are counted in `ALL` /
`providers_answered`.

What Bloomberg never does is win a comparison it cannot make: its equity and index
prints are exchange-delayed, so a pair of prints a delay length apart is reported as
`not_comparable` with the delay named, and it is last in the freshness tie-break so a delayed page
cannot outrank a live print. Agreement with Yahoo on statics is weak corroboration, not two
witnesses, which `notice` does not claim otherwise.

StockAnalysis covers US equities and ETFs only, and its quote surface is the same consolidated tape
Yahoo serves, so that pair is weak corroboration for the same reason. Anything it does not carry
(indices, FX, crypto, commodities, foreign listings) resolves to *not carried* and is recorded as
`NOT_ATTEMPTED`, never as an error.

The `bloomberg_*` tools are the single-source case: they ask that one provider, so they return
`BLOOMBERG` / `SINGLE_SOURCE` plus `cross_checked: false` and `reconciliation_leg: false`.

## Fields

### `data_provider`
`"ALL" | "PARTIAL" | "TRADINGVIEW" | "FINVIZ" | "YAHOO" | "SA" | "BLOOMBERG" | "NONE"`. The single
most important field in the response.

### `verification`
`"MULTI_SOURCE" | "SINGLE_SOURCE" | "UNAVAILABLE"`. Convenience mirror of the table above.

### `providers_answered`
The provider labels that actually produced data for this response, in display order. Use this, not
`data_provider` alone, to state coverage precisely ("all sources agreed" vs "only some answered").

### `notice`
One sentence, written to be relayed verbatim to a user. It always names the provider state. When
providers disagree it names the disagreeing fields and says every reading is in `comparisons`. When a
field could not be compared it says why. When the health monitor has seen drift, a `WARNING` is
appended.

### `data`
The reconciled payload. Its shape is tool-specific (a dict for `stock_quote`, a list for
`stock_prices`, a nested object for `market_indices`). This is the only place a value should be read
from.

**One value per compared field.** `data` holds exactly one price, the reading whose market print is
newest. Every original stays in `comparisons`, and `freshness` records which one won and why. An
agent never has to reconcile several numbers to answer "what is the price", but it can always audit
the choice.

**The price is the live print, and it names its session.** The field that looks like "the price" is
the regular session's value, and it stops moving when that session ends. Before comparison, each
provider's reading is moved to the print that provider would call current: TradingView's
`premarket_close`/`postmarket_close` when it says so in `current_session`, Yahoo's `fulldayPrice`
when it differs from `regularMarketPrice`, StockAnalysis's `extended_hours` block when it names a
session. `stock_quote` publishes the result as `data.session` (mirrored at the envelope level), and
`stock_prices` per row. `pre_market`, `regular`, `post_market` and `overnight` are the values; a print
whose session cannot be determined carries `session: null` rather than a guess.

The same session owns the baseline. `change_percent` and `previous_close` describe the print beside
them, not an older session's close, so the three numbers in a row are internally consistent: computing
`(price - previous_close) / previous_close` reproduces `change_percent`. A row that paired a live
pre-market price with a baseline two sessions old would report a day change no provider published.

The baseline is recovered from the print's own change, as `price / (1 + change/100)`. That is the number
the provider itself divided by, so it is exact rather than approximate, and it keeps the reference
session right: a regular print is measured against the prior session's close and an extended print
against the last regular close. Those are different numbers, so one branch's baseline is never reused
for another's.

The session names the print that was served, not a leg that was merely asked. A delayed feed states the
window it is in, and while it lags, that statement describes a print the row is not serving. The label
therefore follows the winner's own print, so two tools asked about the same symbol at the same instant
cannot disagree about its session. `data.price_field` names the provider field that print was read from,
so the move away from a stale regular value is visible on the payload rather than only in the docs.

### `fields`
Per-field provenance, one descriptor per key in `data`:

```jsonc
{
  "price":  { "source": "FINVIZ",
              "supplied": ["TRADINGVIEW", "FINVIZ", "YAHOO", "SA"],
              "compared": ["TRADINGVIEW", "FINVIZ", "SA"],
              "agreement": true },
  "peers":  { "source": "FINVIZ", "supplied": ["FINVIZ"], "compared": [], "agreement": null }
}
```

`data` holds exactly one value per field, so a field has exactly one `source`: the provider whose
reading was placed there. **A field is never labelled with more than one provider**, because a value
sourced from four providers does not exist: the four readings were compared, one was chosen, and
`source` names the one that was. The earlier `{"price": "ALL"}` spelling collapsed that distinction
and read as if the number were a joint product of every provider; the descriptor separates the facts
that used to be fused:

| Key | Meaning |
| --- | --- |
| `source` | The one provider whose reading is in `data`. Never `ALL` |
| `supplied` | Every provider that returned a reading for this field, in display order. This answers "who answered" |
| `compared` | Every provider whose reading was actually judged against another one. Never wider than `supplied` |
| `agreement` | `true` every compared pair agreed, `false` a real disagreement, `null` nothing was judged |

**`supplied` and `compared` are different questions, and the difference is not cosmetic.** A field
can have four suppliers while only three of its six pairs were comparable: two prints from different
sessions are two observations, so nothing was concluded from that pair. Reading `agreement: true` as
"every provider agreed" was the mistake the split exists to stop. `supplied` says who answered;
`compared` says whose reading actually corroborated the number in `data`; `agreement` describes
exactly that second set. A field a tool serves but does not cross-check (`previous_close` on
`stock_prices`, a peer list) has an empty `compared` and a `null` `agreement`, even when several
providers supplied it.

`providers_answered` names who answered for the response as a whole, which is a third scope again.
The three differ on any tool with uneven coverage: a quote gets its price from four providers but its
peer list from Finviz alone.

To go one step further: `comparisons[].values` holds every provider's raw reading keyed by label, and
`sources[fields.<field>.source]` names the upstream that produced the chosen one.

### `comparisons`
One row per compared field:

```jsonc
{
  "field": "price",
  "values": { "TRADINGVIEW": 331.9, "FINVIZ": 332.33, "YAHOO": 331.9, "SA": 331.9 },  // verbatim
  "match": true,          // null when no pair could be compared
  "diff": 0.43,           // largest absolute gap among comparable pairs
  "diff_pct": 0.1294,     // largest relative gap, %
  "tolerance_pct": 0.5,   // threshold this field was judged against
  "chosen": "FINVIZ",     // which reading went into `data`
  "pairs": [              // every pairwise comparison, so no pair is hidden
    { "between": ["TRADINGVIEW", "FINVIZ"], "tv": 331.9, "fv": 332.33,
      "match": true, "diff": 0.43, "diff_pct": 0.1294, "tolerance_pct": 0.5 },
    { "between": ["TRADINGVIEW", "YAHOO"], "tv": 331.9, "fv": 331.9,
      "match": true, "diff": 0.0, "diff_pct": 0.0, "tolerance_pct": 0.5 }
  ]
}
```

`match` is the aggregate: `true` when every comparable pair agrees, `false` when any pair disagrees,
and `null` when no pair could reach a verdict, whether because fewer than two providers supplied a
reading or because every pair was unusable. `notice` says `Compared fields agree within tolerance`
only when at least one comparison reached agreement. When comparisons exist but none reached a
verdict, it instead says `No compared fields reached an agreement verdict.`

The `tv`/`fv` keys inside a pair are historical names for "first reading" and "second reading"; the
`between` list names the providers unambiguously and is the field to read.

### `comparisons[].not_comparable`
Set on a field whose readings cannot be legitimately compared, with the reason:

```jsonc
{
  "field": "change_percent",
  "values": { "TRADINGVIEW": -1.8976, "FINVIZ": 0.13, "YAHOO": -1.8976, "SA": -1.8976 },
  "match": null,
  "not_comparable": true,
  "pairs": [
    { "between": ["TRADINGVIEW", "FINVIZ"], "match": null,
      "not_comparable": "prints belong to different sessions (2026-11-03 and 2026-11-04); this field is measured against a session-relative baseline, so the readings are not comparable" }
  ]
}
```

A day-change percentage or a session volume is measured against the previous close of the session the
print belongs to. Two providers looking at different sessions legitimately differ, so calling that a
"conflict" would be a false alarm. The pair is excluded from the agreement decision, every reading
stays visible, and the field is listed in `warnings` as not cross-checked. The reason in
`pairs[].not_comparable` says which guard fired: different session dates, a print past the age
ceiling, or no print time to prove the observation.

`not_comparable` is also used for a field that has **no shared definition**, where no timestamp check
can help. Spot FX has no single official previous close, so `change_percent` on an FX instrument is
always reported from every provider and never compared, with that reason stated. Every guard is
one-way: it can lose a comparison, never invent a conflict.

For a multi-value pair, non-numeric values and blank symbols also stay in `pairs`, with `match:
null` and a `not_comparable` explanation. An unusable pair is therefore never an invisible omission
or a source of agreement. `match: null` **without** `not_comparable` means fewer than two providers
supplied a reading. `match: false` is a real disagreement.

`stock_extended_hours` compares only the active or evidenced pre-market/post-market window, not a
post print from yesterday against a pre print from today. Differing named windows and undated reads
in a shared window are both `not_comparable`. StockAnalysis's own pre/post label is retained when its
timestamp is absent, but agreement still requires a dated print from every side of the pair.

### `freshness`
Present when a comparison actually happened **and** at least one provider reported a usable print
time. Tools that compare non-price fields (index levels, row counts) omit it entirely rather than
announce that no timestamp existed:

```jsonc
{
  "tradingview": "2026-11-04T00:59:53+00:00",   // market print time, UTC
  "finviz": "2026-11-04T10:42:00+00:00",
  "yahoo": "2026-11-03T21:00:01+00:00",
  "sa": "2026-11-03T21:00:01+00:00",
  "bloomberg": "2026-11-04T10:27:00+00:00",
  "chosen": "FINVIZ",
  "decision": "newest",
  "newest_print": "2026-11-04T10:42:00+00:00",
  "reason": "FINVIZ printed most recently (2026-11-04T10:42:00+00:00)"
}
```

These are **print** times, not fetch times. `decision` is the machine-readable outcome; read it
instead of parsing `reason`:

| `decision` | Meaning | Extra keys |
| --- | --- | --- |
| `newest` | One provider printed strictly later; its values were used | `newest_print` |
| `tie` | Several printed at the same newest instant | `newest_print`, `tied` |
| `no_timestamp` | No provider exposed a parseable print time | - |

Only providers that share the newest instant are tie-break candidates, so a stale provider can never
win a tie against fresher ones. Ties are broken by the documented order (`FINVIZ`, `TRADINGVIEW`,
`YAHOO`, `SA`, `BLOOMBERG`); with no usable timestamp at all, the value comes from the first provider
in that order that answered. The order is fixed and stated in `reason`, never implicit.

### `resolutions`
How each provider's ticker was derived for this call:

```jsonc
{
  "TRADINGVIEW": { "query": "AAPL", "provider": "TRADINGVIEW",
                   "symbol": "NASDAQ:AAPL", "venue": "NASDAQ",
                   "method": "search", "confidence": 0.75, "note": "" },
  "FINVIZ":      { "symbol": "AAPL", "method": "normalise", ... },
  "YAHOO":       { "symbol": "AAPL", "method": "alias", ... },
  "SA":          { "symbol": "aapl", "method": "mechanical", ... },
  "BLOOMBERG":   { "symbol": "AAPL:US", "method": "mechanical", ... }
}
```

`method` is one of `explicit` (the caller gave `EXCHANGE:SYMBOL`), `alias` (the instrument registry:
indices and commodities carry one row per instrument with one column per provider), `search` (the
provider's own symbol search, verified against its quote endpoint), `normalise`/`mechanical` (a
documented spelling rule, used by providers with no search endpoint), or `none` (not carried). A
`none` resolution carries a `note` explaining why, and becomes `NOT_ATTEMPTED` rather than an error.

This is the field to read when a symbol behaved unexpectedly. `XAUUSD` shows `OANDA:XAUUSD` for
TradingView, `XAUUSD:CUR` for Bloomberg (from the registry row, `method: alias`), no Yahoo ticker
(Yahoo has no spot-gold pair, `XAUUSD=X` is a 404) and notes from Finviz and StockAnalysis saying
they carry US equities and ETFs only. `WTI` shows `FX:USOIL` for TradingView, never `NYSE:WTI`
(W&T Offshore, an equity whose ticker happens to match), and `CL1!` shows `GC=F`-style futures
spellings (`CL=F` for Yahoo, `CL1:COM` for Bloomberg). `WTI=F` folds onto the same front-month
future (`CL1!`) instead of falling into search, where TradingView resolves it to `XETR:WTIF`, the
WisdomTree Japan ETF. `NDX` and `^NDX` both resolve through the registry row (`NASDAQ:NDX`,
`^NDX`, `NDX:IND`) with Finviz and StockAnalysis reported as not carried.

### `cross_checked` / `reconciliation_leg`
Present on the `bloomberg_*` tools, both `false`: that call asked a single provider, so its payload
was not reconciled. They describe the call, not the provider: the same provider is a full leg inside
`stock_quote` / `stock_prices`. They are absent from every reconciled response, because there the
answer is implied by `data_provider` and `comparisons`.

### `sources`
Where each provider's data actually came from: upstream URL or dataset name.

```jsonc
{ "TRADINGVIEW": "scanner.tradingview.com",
  "FINVIZ": "https://finviz.com/stock?t=AAPL",
  "YAHOO": "query1.finance.yahoo.com chart API",
  "SA": "https://stockanalysis.com/api/quotes/s/aapl",
  "BLOOMBERG": "https://www.bloomberg.com/quote/AAPL:US" }
```

This is the honesty field. Each label names the upstream that was actually called, no leg proxies
another.

### `errors`
Real failures only:

```jsonc
{ "provider": "FINVIZ", "code": "UPSTREAM_TIMEOUT", "message": "..." }
```

`NOT_ATTEMPTED` is **excluded**. It means "this provider has no such capability" (Finviz has no spot
gold quote, TradingView publishes no options chain), which is a structural fact, not an error. Once
`stock_quote` has resolved a provider's symbol, an empty answer is `NO_DATA`, not `NOT_ATTEMPTED`.

`stock_prices` repeats attempted failures in each affected row's `errors` and explains them in its
`misses` map. Every error carries both `provider` and `symbol`; provider exception codes are retained.
The envelope aggregates those symbol-tagged row failures without also repeating each provider-wide
summary. An attempted provider that returns no rows is `NO_DATA`, including when the entire batch is
empty. A returned payload without a usable price is likewise `NO_DATA`, not an answered reading.
Coverage applies to each provider-symbol request: a complete `ALL` row does not mask another
symbol's attempted miss, which makes a multi-provider batch envelope `PARTIAL`.

`stock_extended_hours` also reports its secondary overnight failures in `data.overnight_errors` and
appends those same records to the envelope's `errors`. The records carry
`detail.capability: "overnight"`; they neither replace primary quote-fetch errors nor change the
primary legs' `ALL`/`PARTIAL` coverage classification. `overnight`, `overnight_source`,
`overnight_readings`, `overnight_comparison` and `overnight_errors` stay together so a null selected
print cannot silently conceal an attempted endpoint's failure.

Common codes: `UPSTREAM_TIMEOUT`, `UPSTREAM_RATE_LIMIT`, `UPSTREAM_BLOCKED`, `UPSTREAM_ERROR`,
`NO_DATA`, `PARSE_ERROR`, `INVALID_TICKER`, `NOT_CONFIGURED`, `SCHEMA_DRIFT`, `PROVIDER_ERROR`.

Two codes are deliberately distinct rather than merged:

- `TIMEOUT` is **this server's own deadline** expiring on a paced leg (Bloomberg's page path is paced
  at 10 s per request), so the request may well have succeeded a moment later. Retrying is sensible.
- `UPSTREAM_TIMEOUT` is the **upstream itself** timing out.

Collapsing them would tell a caller to retry a leg that is not slow. `SCHEMA_DRIFT` is this server
reporting that a provider's payload no longer parses, as distinct from a reconciliation disagreement,
which is not an error at all and lives in `comparisons`.

### `warnings`
Human-readable cautions. A disagreement adds `"Providers disagree on: price"`. A field that could not
be compared adds `"Not cross-checked (no shared basis for comparison): change_percent, volume"`. Health drift adds a warning naming the affected upstream.

### Missing, zero and non-finite values

A provider's reported `0` remains zero, including option volume, open interest, IV, last, bid and ask.
An absent or null value stays `null`; neither case falls through to an alias that can substitute an
unrelated reading. A zero open-interest pair has the provider-specific treatment described under
`stock_options_chain`, not a blanket conversion of zeroes to missing data.

Session prices must be finite numbers. `NaN`, positive infinity and negative infinity are unavailable
readings, not usable prices or baselines. Booleans and numeric strings are not accepted as prices either.

`stock_options_chain` uses a contract's side, expiry and strike for comparison. If chains with no
explicit shared expiry return different evidenced dates, `data.expiry` is `null` and
`data.overlap.not_comparable` is true, with the reason and each provider's selected date. An explicit
shared expiry retains normal volume and open-interest comparisons. Backtest results add
`execution_model`; it declares next-open versus Donchian same-close execution, final-bar entry
suppression and forced exit at the final close.

### `degraded`
`true` when the health monitor reports drift or an outage **for a provider this call actually used**.
Health problems on an unused provider do not mark the response degraded.

### `generated_at`
UTC ISO-8601 timestamp of response construction.

## Tolerance

Comparisons are relative (`diff_pct <= tolerance_pct`), with an optional absolute floor so tiny
readings are not flagged over rounding noise.

| Field | Tolerance | Why |
| --- | --- | --- |
| price | 0.5 % | Same instrument, different print times |
| change % | 2 % (floor 0.05) | Derived from different reference closes; not judged at all on FX |
| previous close | 0.5 % | Should be identical; a gap is meaningful |
| session open/high/low | 0.5 % | Same session, different print moments; open is compared only where both sides publish it |
| P/E | 2 % | Rounding in the Finviz snapshot |
| RSI(14) | 5 % (floor 0.5) | Different lookback windows |
| volume | 1 % | Intraday accumulation timing |
| index level | 0.5 % | Same index, different print times |
| VIX level | 3 % | A volatility gauge that moves percent-level within a minute |
| options volume | 5 % ; open interest 1 % | Different snapshot moments |
| backtest metric | 0–5 % per metric | Two independent OHLCV feeds |

Tolerances are per-field in `tools_market._quote_specs()` and at the comparison sites, and are echoed
back in each `comparisons` row.

Fields marked session-relative (`change_percent`, `previous_close`, `volume`, `day_high`, `day_low`,
`day_open`) are governed by three
guards, applied per field, because a day change is measured against the previous close *of the
session the print belongs to*:

| Guard | Value | What it catches | What it cannot see |
| --- | --- | --- | --- |
| `max_skew_seconds` | 900 s | two prints far enough apart to be different observations | a session roll between two nearby prints; every provider frozen together |
| `KNOWN_REPORTING_LAG` | the delay the feed declares (Bloomberg: 900 s on equities and indices) | a pair that is far apart *by design*, so the delay is named rather than called a conflict | nothing about other providers, which declare no lag |
| `session_boundary` | US/Eastern date | prints on either side of a session roll, even 30 s apart | a feed that stopped updating inside one session |
| `max_age_seconds` | 8 h, within one session date | a print that stopped advancing while the clock kept moving | anything across a session boundary, where a quote legitimately ages overnight |

The age ceiling is set on `change_percent`, `volume` and the session range, the fields re-derived from
the print. `previous_close` does not get it: an old quote does not falsify a previous close, so only
the skew and session-date guards apply there.

Readings that fail a guard are reported as *not comparable* rather than as a disagreement: both
readings stay in `comparisons`, the field is named in `warnings`, and it is never counted as a
conflict. The guards are one-way by design, they can lose a comparison but never invent one.

One field has no shared definition at all, so no timestamp check can rescue it. **Spot FX has no
single official previous close**: each provider derives its own daily roll, so a day change of 0.09 %
and one of 0.31 % are answers to different questions, one second apart. On an FX resolution the
`change_percent` field is therefore always `not_comparable`, with that reason in the pair, while the
readings stay visible. This is instrument-level, not provider-level: it applies whenever any provider
resolved the symbol to `forex` or `currency`.

The 900 s ceiling is measured, not arbitrary: two *live* endpoints were observed 604 s apart on a
thin contract (gold futures, TradingView 09:13:15Z vs Yahoo 09:03:11Z), so a tighter value would
discard valid comparisons in order to look strict. `price` gets the same three timestamp guards: a
price points at an instant, so two prints 20 minutes apart are two observations and their difference
is the market moving, not a provider conflict.

## A worked multi-provider response

```jsonc
{
  "data_provider": "ALL",
  "verification": "MULTI_SOURCE",
  "providers_answered": ["TRADINGVIEW", "FINVIZ", "YAHOO", "SA", "BLOOMBERG"],
  "notice": "Every provider asked answered (TradingView, Finviz, Yahoo Finance, StockAnalysis and Bloomberg). Coverage is ALL; agreement is a separate axis. Compared fields agree within tolerance. The value shown is FINVIZ's because it printed more recently than the other providers'. Not cross-checked, because the providers' readings have no shared basis for comparison: change_percent, previous_close, volume.",
  "data": { "price": 332.33, "change_percent": 0.13, ... },   // one value per field
  "fields": { "price": { "source": "FINVIZ",
                          "supplied": ["TRADINGVIEW", "FINVIZ", "YAHOO", "SA", "BLOOMBERG"],
                          "compared": ["TRADINGVIEW", "FINVIZ", "YAHOO", "SA", "BLOOMBERG"],
                          "agreement": true },
              "peers": { "source": "FINVIZ", "supplied": ["FINVIZ"], "compared": [], "agreement": null } },
  "freshness": { "chosen": "FINVIZ", "decision": "newest",
                 "reason": "FINVIZ printed most recently (2026-11-04T10:42:00+00:00)" },
  "comparisons": [
    { "field": "price", "match": true,
      "values": { "TRADINGVIEW": 331.9, "FINVIZ": 332.33, "YAHOO": 331.9, "SA": 331.9, "BLOOMBERG": 332.1 },
      "diff_pct": 0.1294, "chosen": "FINVIZ" },
    { "field": "change_percent", "match": null, "not_comparable": true,
      "values": { "TRADINGVIEW": -1.8976, "FINVIZ": 0.13, "YAHOO": -1.8976, "SA": -1.8976 } }
  ],
  "warnings": ["Not cross-checked (no shared basis for comparison): change_percent, previous_close, volume"],
  "degraded": false
}
```

Read it as: *every provider asked answered. Their prices agree within 0.13 %, so the price shown is a
corroborated reading. Finviz is mid-session while the others are at the prior close, so the
day-change figures were not compared, and the response says so rather than pretending they conflicted
or that they agreed.*

## A worked disagreement

```jsonc
{
  "data_provider": "ALL",
  "verification": "MULTI_SOURCE",
  "notice": "Every provider asked answered ... NOTE: the providers disagree on price; every reading appears in `comparisons` and the response holds a single value. The value shown is TRADINGVIEW's because it printed more recently. The conflict is reported, not silently resolved.",
  "data": { "price": 331.9, ... },          // one value: the newest print
  "fields": { "price": { "source": "TRADINGVIEW",
                          "supplied": ["TRADINGVIEW", "FINVIZ"],
                          "compared": ["TRADINGVIEW", "FINVIZ"],
                          "agreement": false } },
  "freshness": { "chosen": "TRADINGVIEW", "decision": "newest",
                 "reason": "TRADINGVIEW printed most recently (2026-11-03T21:00:01+00:00)" },
  "comparisons": [
    { "field": "price",
      "values": { "TRADINGVIEW": 331.9, "FINVIZ": 300.0 },
      "match": false, "diff_pct": 9.6, "chosen": "TRADINGVIEW" }
  ],
  "warnings": ["Providers disagree on: price"],
  "degraded": false
}
```

Read it as: *every provider answered, two contradict each other by 9.6 %, and nothing was hidden.*
`data.price` holds **one** value, the newest print. The losing value is one field away in
`comparisons`, and the notice says exactly that.

## Why not just return one number?

It does return one number, but the envelope keeps the other readings visible next to it. Silently
discarding a contradicting reading is how a wrong number becomes authoritative: if an agent cannot
see that another independent source disagreed, it cannot warn its user. One value in `data`, all
values in `comparisons`, and the reason for the choice in `freshness`.

## Related

- [Tools Reference](Tools-Reference): which fields each tool compares
- [Health Monitor](Health-Monitor): how `degraded` is decided
- [Design Decisions](Design-Decisions): why the contract looks like this
