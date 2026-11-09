# Response Contract

Every tool returns the same envelope. Learn it once and every tool is readable.

## The seven provider states

| `data_provider` | `verification` | Meaning | What an agent should do |
| --- | --- | --- | --- |
| `ALL` | `MULTI_SOURCE` | Every provider that was asked answered | Quote the numbers; use `providers_answered` to name the providers that covered them |
| `TRADINGVIEW` | `SINGLE_SOURCE` | Only TradingView answered | Quote, but say it is single-source and not corroborated |
| `FINVIZ` | `SINGLE_SOURCE` | Only Finviz answered | Same, from the Finviz side |
| `YAHOO` | `SINGLE_SOURCE` | Only Yahoo Finance answered | Same, from the Yahoo side |
| `SA` | `SINGLE_SOURCE` | Only StockAnalysis answered | Same; note it covers US equities and ETFs only |
| `BLOOMBERG` | `SINGLE_SOURCE` | Only Bloomberg answered | Same, but state `exchange_delay` / `print_time` before calling a price live |
| `NONE` | `UNAVAILABLE` | No provider answered | Say no data is available. Do not invent one. |

`verification` is derived, never independent: `ALL → MULTI_SOURCE`, a single provider
`→ SINGLE_SOURCE`, `NONE → UNAVAILABLE`.

**`ALL` does not mean "the values agree".** It means every provider *asked* answered. Agreement is a
separate axis, reported per field in `comparisons[].match` and summarised in `notice`/`warnings`.
Providers answering but diverging is still `ALL`, with the conflict named.

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
`"ALL" | "TRADINGVIEW" | "FINVIZ" | "YAHOO" | "SA" | "BLOOMBERG" | "NONE"`. The single most important field
in the response.

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

### `fields`
Per-field provenance: `{"price": "ALL", "peers": "FINVIZ", "after_hours_price": "FINVIZ"}`.

Needed because most responses legitimately mix sources. `stock_quote` gets price from every provider
that quotes it but the fundamentals snapshot, company profile and peer list from Finviz alone, a
blanket `ALL` on the whole response would overclaim.

A field is labelled `ALL` when two or more providers supplied it, and with the provider's name when
only one did.

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
`null` when fewer than two providers reported a usable value.

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

`match: null` **without** `not_comparable` means the comparison was impossible (a non-numeric or
missing value). `match: false` is a real disagreement.

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

`method` is one of `explicit` (the caller gave `EXCHANGE:SYMBOL`), `alias` (a documented mechanical
rule or index table), `search` (the provider's own symbol search, verified against its quote
endpoint), `mechanical` (StockAnalysis has no search endpoint, so its US slug is derived by rule), or
`none` (not carried). A `none` resolution carries a `note` explaining why, and becomes
`NOT_ATTEMPTED` rather than an error.

This is the field to read when a symbol behaved unexpectedly. `XAUUSD` shows `OANDA:XAUUSD` for
TradingView, `XAUUSD:CUR` for Bloomberg (derived mechanically, `method: mechanical`), no Yahoo ticker
(Yahoo has no spot-gold pair, `XAUUSD=X` is a 404) and notes from Finviz and StockAnalysis saying
they carry US equities and ETFs only.

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
gold quote, TradingView publishes no options chain), which is a structural fact, not an error.

Common codes: `UPSTREAM_TIMEOUT`, `UPSTREAM_RATE_LIMIT`, `UPSTREAM_BLOCKED`, `UPSTREAM_ERROR`,
`NO_DATA`, `PARSE_ERROR`, `INVALID_TICKER`, `NOT_CONFIGURED`, `PROVIDER_ERROR`.

### `warnings`
Human-readable cautions. A disagreement adds `"Providers disagree on: price"`. A field that could not
be compared adds `"Not cross-checked (no shared basis for comparison): change_percent, volume"`. Health drift adds a warning naming the affected upstream.

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
  "fields": { "price": "ALL", "peers": "FINVIZ", ... },
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
  "fields": { "price": "ALL", ... },
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
