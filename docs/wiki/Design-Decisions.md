# Design Decisions

Non-obvious choices, and the reasoning that produced them. Each entry is a rule that is easy to
violate by accident.

---

## 1. Six provider states, not two

**Decision:** `ALL` / `TRADINGVIEW` / `FINVIZ` / `YAHOO` / `SA` / `BLOOMBERG` / `NONE`, never a
boolean like `verified: true`.

**Why:** "verified" collapses two different facts: *how many providers answered* and *whether they
agreed*. A boolean loses the case that matters most: several answered and disagreed. With an explicit
state per provider plus `comparisons`, that case is visible instead of hidden. Bloomberg and
StockAnalysis were added later as further legs with their own properties, see decisions 30 and 35.

**Consequence:** `ALL` means "every provider that was asked answered", not "they agree". Agreement
lives in `comparisons[].match`. This is documented in several places because it is the single easiest
thing to misread.

---

## 2. `ALL` is coverage, not agreement

**Decision:** `ALL` is set whenever every provider that was asked produced data, including a
partial response, and `providers_answered` names exactly which providers contributed.

**Why:** the alternative is either a lie or a combinatoric explosion of labels. If `ALL` required
every provider in the catalogue to answer, a tool that legitimately asks only some of them (options
chains: Finviz + Yahoo) could never report complete coverage, and an instrument only some providers
carry would look degraded on every call. Naming the answering set separately keeps both facts exact:
`data_provider` says "you got everything asked for", `providers_answered` says what that was.

**Consequence:** an agent that wants to say "several sources agreed" must read `providers_answered`,
not infer it from `ALL`.

---

## 3. Disagreement is never resolved by fiat

**Decision:** when providers disagree, keep every value in `comparisons`, name the field in `notice`
and `warnings`, and leave `data_provider` as `ALL`.

**Why:** silently picking one turns an arbitrary choice into an authoritative-looking number. An
agent that cannot see the conflict cannot warn its user. The cost is a slightly noisier response; the
benefit is that a wrong number never becomes invisible.

---

## 4. A single value per field, chosen by print time

**Decision:** resolve each compared field to a single value in `data`, the reading whose market
print is **newest**, while `comparisons` keeps every raw reading verbatim.

**Why:** an agent should not have to reconcile several numbers to answer "what is the price". But
it must be able to *audit* that choice, which requires the losers to remain one field away.

**Why freshness, not a fixed provider:** preferring one provider unconditionally is arbitrary. During
a session one provider is routinely a minute behind another (Yahoo stamps the close `21:00:01Z`
Finviz renders `3:59 PM ET` = `20:59Z`), so a fixed winner periodically serves the staler price. The
freshest print is the defensible choice, and `freshness.reason` plus the notice state it plainly.
`freshness.decision` makes the rule machine-readable (`newest`, `tie`, `no_timestamp`) so no caller has
to parse the sentence.

Ties, and cases where no provider reports a usable timestamp, fall back to a fixed documented order
(`FINVIZ`, `TRADINGVIEW`, `YAHOO`), not to whichever label happened to be first. Only providers that
share the newest instant are tie-break candidates, so a stale provider can never win against fresher
ones.

---

## 5. A session-relative field is not compared across observations

**Decision:** `change_percent`, `previous_close` and `volume` carry `max_skew_seconds = 900` and
`session_boundary = True`; the two re-derived fields (`change_percent`, `volume`) also carry
`max_age_seconds = 8h` when a reference clock is supplied. `previous_close` omits the age ceiling
because an old quote does not falsify a previous close.
A pair that fails any guard is reported as `not_comparable` with the reason, and the field is listed
in `warnings` as not cross-checked.

**Why:** those fields are measured against the previous close of the session the print belongs to.
A pre-market Finviz quote and a prior-close Yahoo quote legitimately disagree about the day change:
that is two different questions, not two answers to one. Reporting it as a provider conflict produces
a warning on nearly every call, which trains readers to ignore warnings; widening the tolerance would
report a false agreement. Neither is true, so the pair is excluded from the agreement decision and the
reason is stated. The three guards exist because each sees a hazard the others cannot; the reasoning
and the measured floor for the 900 s value are in decision 28.

**Consequence:** the price itself is still compared across minutes. A price stays comparable across
print times; a session baseline does not. `require_all_times=True` is the same principle for
providers that expose no observation time at all: agreement cannot be *proven*, so `match` stays
`null` rather than being asserted.

---

## 6. Single-source data is served, not withheld

**Decision:** if one provider answers, serve it, labelled and with an explicit "not corroborated"
notice.

**Why:** withholding one provider's valid data would be worse than serving it with a caveat. The
failure mode we care about is a *number presented as verified when it is not*, not the existence of
uncorroborated numbers. The label, not the omission, is the safeguard.

---

## 7. `NOT_ATTEMPTED` is not an error

**Decision:** a capability a provider simply does not have (Finviz has no futures feed, Finviz and
Yahoo carry no spot gold) produces `NOT_ATTEMPTED`, excluded from `errors`.

**Why:** conflating "this provider cannot answer" with "this provider failed" makes structural facts
look like outages. A reader would see errors on every crypto or metals call and learn to ignore
errors, destroying the signal for real failures.

---

## 8. Symbols are resolved per provider, and verified

**Decision:** resolve each query independently per provider, then verify a candidate ticker against
the provider's own quote endpoint before returning it.

**Why:** a hardcoded table cannot keep up and, worse, fails as a *wrong-but-plausible* ticker that
breaks six layers later. But trusting provider search is not enough either: TradingView's symbol
search offers `OANDA:BTCUSD`, while its scanner has no row for it. Resolution that stops at search
hands the quote path an unquotable ticker and a real instrument is reported as unavailable. So
candidates are verified against the scanner, and `BTCUSD` resolves to `BITSTAMP:BTCUSD`.

The same rule explains what is *not* returned: Yahoo has no spot-gold pair (`XAUUSD=X` is HTTP 404)
and its nearest series is COMEX gold futures (`GC=F`), a different instrument at a different price.
Substituting it would be a fabricated quote, so the resolution is `none` with a note.

Results are cached per `(provider, query)` for an hour.

---

## 9. Every provider is rate-limited, and the cooldown is shared

**Decision:** every request to every provider passes a `ProviderLimiter` with a minimum interval, a
concurrency cap, a process-wide exponential cooldown after a `429`, and a short TTL cache.

**Why:** retrying harder is the wrong reaction to a rate limit; it deepens the block. Pacing and a
shared pause are what actually recover. A process-wide cooldown means one blocked request protects
every later caller instead of each discovering the block separately, and the TTL cache absorbs the
duplicate questions an agent naturally asks in one turn.

**Consequence:** Yahoo is paced slowest (one at a time, 1 s apart) because it starts answering `429`
after a short burst. TradingView's chart websocket signals a block as `invalid symbol` or
`resolve error` rather than `429`; those are treated as rate limiting too, because they are
IP-scoped, not ticker-scoped. Reporting a valid symbol as nonexistent because of a block would be a
wrong answer, not a bad ticker.

---

## 10. Multiple independent legs, no proxying

**Decision:** TradingView, Finviz and Yahoo each hit genuinely different upstreams through their own
access module. Every provider added later (Bloomberg, StockAnalysis) follows the same rule.

**Why:** cross-verification is only meaningful if the sources are independent. An earlier version of
this server took TradingView's price from Yahoo's chart API: two legs, one upstream wearing two
labels, a comparison that could only ever agree. That is worse than no comparison, because it looks
like confirmation.

**Consequence:** `sources` names the upstream each leg actually called, so a reader can check the
independence claim rather than trust it.

---

## 11. Health probes bypass the provider code

**Decision:** `health.py` probes upstreams directly, not through `tv_access`/`fv_access`/`yh_access`.

**Why:** a provider that catches its own exceptions looks healthy from outside. Probing through it
would inherit the same blindness. Independent probes can fail while every tool call succeeds, and
that divergence is the signal.

**Consequence:** a probe must exercise a ticker the provider actually serves. The Yahoo FX and crypto
probes exist because those resolution paths are separate assumptions; a probe using only `AAPL` would
stay green while `EURUSD=X` started 404-ing.

---

## 12. Fingerprints, not just status codes

**Decision:** store a SHA-256 fingerprint of the payload's key paths as a baseline; compare later.

**Why:** a drifted endpoint returns HTTP 200 with a renamed field. Status-only monitoring reports a
broken parser as healthy while it returns `None`. The baseline also prevents the first observation of
an already-drifted shape from being adopted as the new normal.

---

## 13. Health state is persisted to disk

**Decision:** baselines live in `~/.tapebasis/health_state.json`, volume-mounted in Docker.

**Why:** in-memory baselines reset on every restart, so a slow-moving schema change would be adopted
silently at each restart. Persistence is what makes drift detection cumulative.

---

## 14. The monitor starts lazily, not via lifespan

**Decision:** `MONITOR.ensure_started()` is called from tool entry points.

**Why:** FastMCP's streamable-HTTP app builds its own lifespan and ignores `lifespan=`. A
lifespan-only start would work over stdio and silently never run over HTTP: a bug that only appears
in the deployment most people use. Lazy start works on both transports.

---

## 15. Per-field provenance, not a blanket claim

**Decision:** `fields` maps each output field to its provider.

**Why:** most responses legitimately mix sources. `stock_quote` gets price from every provider that
quotes it but the fundamentals snapshot, profile and peers from Finviz alone. A response-level `ALL`
would overclaim for every Finviz-only field riding along.

---

## 16. Sentiment is labelled by data origin, not by code location

**Decision:** local sentiment over Finviz headlines returns `data_provider: FINVIZ`, even though the
tool lives in `tools_tradingview.py`.

**Why:** the numbers are Finviz's; only the scoring is ours. Labelling it `TRADINGVIEW` would assert
a provenance the data does not have: precisely the mislabelling this server exists to prevent. Code
location is an implementation detail; the label must describe the data.

---

## 17. `0.0` and `null` are not interchangeable

**Decision:** `sentiment_score: null` means "nothing could be scored"; `0.0` means "the tone is
balanced". The unavailable path never returns `0.0`.

**Why:** a failed fetch reported as `0.0`/`Neutral` reads as a finding, "the news is balanced",
when the truth is "we could not look". Silent fallbacks to a neutral-looking default are a classic
way for a data gap to become an asserted fact. The same reasoning rejected a fabricated sentiment
score when Marketaux returns an empty article list.

---

## 18. A rejected token falls back rather than failing

**Decision:** an invalid/expired token falls back to local scoring, recording the cause in
`licensed_path_unavailable`.

**Why:** the tool's job is to produce sentiment, not to enforce a billing relationship. A hard
failure would make an expired token look like a broken server. But the fallback must be visible: a
silent switch from licensed to locally-computed numbers would misrepresent the output's quality.

---

## 19. News sources were evaluated for independence, not just availability

**Decision:** keep Finviz as the news spine; use Yahoo as the second free leg and Marketaux as the
optional licensed one; score sentiment locally.

**Why:** candidate feeds were tested live and rejected on concrete grounds:

| Candidate | Rejected because |
| --- | --- |
| Nasdaq RSS (`rssoutbound?symbol=`) | Does not actually filter by symbol, `THYAO.IS` and `BTC-USD` returned identical items |
| Yahoo `/v1/finance/search` as a *primary* news spine | `Disallow: /` in robots.txt and a brittle feed; kept only as a secondary leg behind Finviz |
| Yahoo RSS feeds | User-Agent sensitive, browser UA got `429`, Windows UA got `200`; too brittle to depend on |
| Google News RSS | 100 items and genuinely independent, but article links are unresolvable Google redirects and `/rss/` is not in its robots allow-list |
| Reddit / StockTwits | Blocked (`403`) from this network |
| Finnhub / Polygon / Tiingo / AlphaVantage | All require a token, the opposite of the goal |

Yahoo's *chart* API is used for prices and its `/v1/finance/search` feed for headlines. Both are
separate upstreams from Finviz and from TradingView's scanner, so Yahoo counts as an independent
leg. The result: no tool needs a key, and no third party's terms are strained to achieve it.

---

## 20. Index and ETF are never aliased

**Decision:** `RUT` (Russell 2000 index) and `IWM` (its tracking ETF) are separate canonical
instruments.

**Why:** they are different instruments at different price levels. Aliasing them would produce a
comparison that always "disagrees" and a canonical key that silently mixes two things.

---

## 21. `finviz_earnings_date` and `next_earnings_date` are separate fields

**Decision:** never merge them into one `earnings_date`.

**Why:** Finviz's is the **last reported** quarter's timestamp (the anchor for its results tables);
TradingView's is the **upcoming** release. They answer different questions. Merging them would
produce a date that is right for neither.

---

## 22. Options open interest: `0 vs N` is not a mismatch

**Decision:** count `0 vs N` under `open_interest_unavailable`, not as a conflict.

**Why:** Yahoo reports zero OI for contracts expiring the same day. Treating a provider convention as
a data conflict would generate false mismatches on exactly the contracts people look at most.

---

## 23. The screener compares the same instruments, not two rankings

**Decision:** TradingView ranks the market; Finviz is then asked about **exactly those tickers** and
the price is compared per row.

**Why:** the obvious design, ask both providers for their own top-N and compare, compares two
unrelated universes. A market-cap ranking and a day-%-change ranking share no rows, so the "multi-
source" screen was silently single-source. It looked cross-checked while nothing was checked.

**Consequence:** Finviz screener rows carry no print time, so a per-row match cannot be *proven* to
describe the same session. Those rows are reported as `not_comparable` (with `require_all_times=True`)
rather than as agreement, and the envelope says no row could be confirmed.

---

## 24. Day-change % is reported from every provider but not compared (indices)

**Decision:** compare index levels tightly (0.5 %, VIX 3 %), but not day-change percentages.

**Why:** each provider derives the change from its own reference close. A small gap is a formula
difference, not a data conflict. Comparing it would warn on every response and train readers to
ignore warnings: the same failure mode as a too-loose tolerance, from the other direction.

---

## 25. No proxy support

**Decision:** there is no proxy layer; no proxy variables exist.

**Why:** an explicit requirement, and it simplifies the failure surface. Egress control belongs at
the network or container layer, where it can be applied consistently and audited.

---

## 26. Docker fixes CA trust before installing anything

**Decision:** both build stages upgrade `pip` and `certifi` as the first action.

**Why:** base images built before the eMudhra/emSign CA incident (Oct 2026) trust a compromised
chain. An install through that trust store either fails or, worse, succeeds against the wrong host.
Pinning the fix into the build makes the image reproducible regardless of when it is built.

---

## 27. Tolerances are per-field and documented

**Decision:** no global tolerance constant.

**Why:** fields differ in how a legitimate discrepancy arises. Price on a closed market should match
to the cent (0.5 %); RSI computed over different lookbacks can differ by percent (5 %); ATR across
providers can differ more (10 %); VIX moves percent-level within a minute (3 %). A single number
would be simultaneously too tight for one field and too loose for another.

---

## 28. Comparability takes more than one time threshold

**Decision:** a field is compared only when the guards that apply to it pass: a 900 s print-time
ceiling, equality of the US/Eastern session date, a declared feed delay as a boundary of its own
(Bloomberg states 15 minutes, see decision 30), and, for the fields re-derived from the print
(`change_percent`, `volume`, and the session high/low/open), an 8 h absolute age ceiling when a
reference clock is available.
`previous_close` takes the first three only, because an old quote does not falsify a previous close.
`price` takes the first three as well: two prices minutes apart are two observations, and calling
their difference a provider conflict blames the feed for the market moving.

**Why:** each guard sees something the others cannot.

- The seconds ceiling alone is blind to a session roll: two prints 30 s apart across midnight ET
  are a whole session apart in meaning and pass any threshold. Comparing them reports a false
  conflict, which is the one outcome a verification tool cannot afford.
- The measured floor for the ceiling is not zero. Two *live* endpoints were observed 604 s apart on
  a thin contract (gold futures: TradingView 09:13:15Z, Yahoo 09:03:11Z). A tighter ceiling buys
  apparent rigor by discarding valid comparisons.
- Skew compares providers to *each other*, so a feed that froze together with its peers has zero
  skew and passes. Only a comparison against the clock sees that. The ceiling is therefore absolute,
  but applied only within one session date: a quote legitimately ages overnight and across a long
  weekend, so a plain wall-clock test would fire on correct data.
- Every guard is one-way. Failing one produces `not comparable`, never a disagreement, so the guards
  can lose a comparison but can never invent a conflict.

**Consequence:** tests and replays stay deterministic, because the age ceiling is inert unless the
caller passes `now`. Fixtures dated in the past are therefore not silently aged out.

---

## 29. An FX day change is never called a conflict

**Decision:** when any provider resolves the instrument to FX (`forex` on TradingView, `currency` on
Yahoo), `change_percent` is reported from every provider but marked `not_comparable` with an explicit
reason. `stock_quote` and `stock_prices` both apply the rule.

**Why:** the guards in decision 28 all assume the field has one definition and the providers merely
observe it at different moments. FX breaks that assumption. Spot FX has no single official previous
close, so each provider picks its own daily roll; measured live on EURUSD, TradingView reported a
day change of 0.0935 % and Yahoo 0.3101 % on prints one second apart, from baselines of 1.12289 and
1.12072. Both are correct against their own baseline, which means a tolerance cannot separate a real
conflict from a difference in definition. Widening the tolerance to hide it would also hide genuine
conflicts in the same field for every other instrument.

**Consequence:** every FX `stock_quote` call would otherwise carry `Providers disagree on:
change_percent` and name the field in `warnings`, which is exactly the alarm fatigue the whole
comparison design exists to avoid. Reporting it as not comparable keeps the readings visible and the
warning meaningful.

---

## 30. Bloomberg is a reconciliation leg, with its delay as a comparability boundary

**Decision:** Bloomberg is a full provider: it is in `PROVIDER_ORDER`, `stock_quote` and
`stock_prices` pass it to `reconcile.ask` in parallel with the others, its readings appear in
`comparisons[].values`, and it contributes to `ALL` / `providers_answered`. Its declared feed delay
is modelled as a boundary of its own rather than as a tolerance, and it sits last in the documented
tie-break order.

**Why it is a leg.** Redundancy is the product. An overlapping figure asked of another provider is
one more chance to catch a broken feed, and refusing to ask a provider because its numbers often
match is a decision made from memory of one afternoon's measurements, not from the data flow. The
"it is delayed" objection turned out to be solvable: the page's real print time is derivable
(`priceMovements1Day[-1].dateTime`, verified against the quoted price), so the leg can be ordered
against the others instead of being excluded.

**Why the delay is a boundary, not a tolerance.** Equity and index pages report
`exchangeDelay: "15 Minutes"` and `isExchangeDelayed: true`. A 15-minute-old print does not describe
the same observation as a live one, and the difference measured between them is the market moving,
not the providers disagreeing. Widening the tolerance to absorb it would either hide real conflicts
or report a false one on every live quote. So a pair that includes Bloomberg stops being comparable
at one declared delay length, and the reason string names the delay. Below that boundary (a closed
market, where every feed shows the same closing print) the pair is compared normally and the
cross-check is genuine.

**What is still weak, and said out loud.** Closing statics come back penny-identical to Yahoo's (same
previous close, same 52-week range), so those two agreeing is one consolidated close read twice.
`pe_ratio` and `eps` are computed independently and do carry a small cross-check value. The docs say
this rather than letting the `ALL` label imply more than it can.

**The sentinel stays guarded.** Equity pages carry `lastUpdate: 2026-11-05T01:00:00.000Z` while the
real print was `2026-11-04T20:58:00Z`. `bb_access` therefore derives `print_time` from the last
intraday point and refuses it when that point's value does not match the quoted price, and the leg is
last in `DEFAULT_ORDER` so a delayed page can never win a tie against a live print.

**Cost control.** Its page path is paced at 10 s per request, so `stock_quote` bounds the leg with
`TAPEBASIS_BLOOMBERG_QUOTE_DEADLINE` (a stated `TIMEOUT` instead of a held response, with the other
readings still going out) and `stock_prices` asks it about at most
`TAPEBASIS_BLOOMBERG_BATCH_MAX` tickers per call, naming the rest in `warnings`.

**Access constraint:** bloomberg.com gates plain HTTP clients on the TLS fingerprint. `httpx` gets a
403 robot page with any headers; `curl_cffi` with a specific impersonation version gets 200. Only the
HTML path is used: the `/bazaar/api/` path burned after about ten rapid requests and stayed 403 for
minutes while the HTML page kept answering from the same session. This is also why the health monitor
has no Bloomberg probe: an `httpx` probe would report a false outage, so the tool response itself is
the availability signal.

**Consequence:** `ALL` can now include Bloomberg, and `comparisons` can carry it, with the delay
visible in `exchange_delay`, `print_time` and any `not_comparable` reason. The `bloomberg_*` tools
remain single-source calls (`cross_checked: false`, `reconciliation_leg: false`), and the board still
reports `print_time: null` because it has none.

---

## 31. Data that arrives with the response is shaped, never dropped

**Decision:** if a provider returns a field on a request the server already makes, that field is
mapped and served, and if it describes the same measurement as another provider's field it joins the
comparison. A field is only absent because the provider does not publish it, never because nobody
wrote the mapping.

**Why:** the cheapest data in the system is the data already in the payload. The audit that produced
this rule found the same failure everywhere: the request was made, the value arrived, the mapping
stopped short.

| Where | What arrived and was dropped |
| --- | --- |
| TradingView scanner | `open`, `high`, `low` (the session range), `premarket_volume`, `postmarket_volume`, `update_mode` (the feed's own delay), `subtype` |
| Yahoo chart `meta` | `regularMarketDayHigh`, `regularMarketDayLow`, `regularMarketOpen`, `regularMarketVolume`, `shortName` |
| Finviz quote page | the whole `income-breakdown` JSON island, plus `website`, `logo_url`, `market_cap_class` |
| Bloomberg quote page | `dayRange` (as a pair, never split into high/low), `earningsPerShare` |

The volume case is the one that shows why this matters beyond tidiness: `volume` was being compared
across some providers while another had been asked and had answered. A comparison that leaves out an
answering provider claims more precision than it has. The same applies to the day range, which two
providers published and no tool exposed.

**Consequence:** `stock_quote` compares `day_open` / `day_high` / `day_low` and Yahoo's `volume` joins
the same cross-check as every other provider. `feed_mode` states the scanner's own delay
(`delayed_streaming_900` vs `streaming`), the same distinction Bloomberg's `exchange_delay` already
made for its leg. The
TradingView identity fields (`instrument_type`, `instrument_subtype`) ride along labelled
`TRADINGVIEW` because only that provider publishes them.

**The corollary:** a provider field that is *not* comparable is still served. `beta`, `eps_ttm` and
`dividend_yield` stay out of `comparisons` on purpose: measured live they diverge by construction
(beta 0.67 vs 1.08, dividend yield 0.30% vs 1.06% for the same ticker), so comparing them would
report a conflict where the providers simply define the metric differently. They are served,
labelled per provider, and not counted as a cross-check.

---

## 32. The Finviz breakdown island is served at one scale

**Decision:** the `income-breakdown-init-data-0` island is parsed into `income_breakdown` on
`stock_quote` and on the Finviz snapshot payload every composite tool already fetches, its statement
amounts are multiplied to absolute currency units, and `statement.scale_applied` states the factor.

**Why:** the island holds two blocks that do not share a unit. `statement` publishes millions
(`"478,834.00"` for Apple's $478.834bn); `revenue` publishes absolute units (`198083000000` for the
Americas segment). Serving the strings verbatim would hand an agent two figures for the same company
six orders of magnitude apart with nothing to say which is which. Verified against the page's own
`Sales` field across large caps, banks, foreign filers and sub-million-revenue companies: statement x
1e6 matches every time, and the axis totals match the statement.

Two shapes are preserved rather than normalised into one:

- **Bank filers** swap the row set (interest income, loan loss provision, non-interest expense) and
  have no `Total Revenue` row. The rows are served as they arrive.
- **Axes vary by company** (three for Apple, two for ASML and JPM, none for TD), and their meaning is
  company-specific: Apple's `segment` is geographic, NVIDIA's is operating segments. The keys stay as
  Finviz sends them instead of being relabelled into something wrong for half the market.

`converted: true` means Finviz FX-converted the axis amounts into the filing currency; `unit`,
`currency` and `converted` are reported next to the numbers so nothing has to be assumed.

**Consequence:** `income_breakdown` costs no extra request, since the island is in the HTML the quote
already fetched. An ETF has no island, so the field is `null` and the quote is unaffected.

**Consequence for `stock_dilution`:** that tool used to return this breakdown as a fallback, which
meant a tool named for dilution answered with revenue data for 29 of 30 large caps. It now returns
`NONE` with the reason ("Finviz only builds this model for dilution-prone companies") and the
breakdown is served where it belongs.

---

## 33. A page-markup move is a data outage, not a cosmetic change

**Decision:** parsers accept the markup shapes that mean the same thing, and the health probe pins the
marker the parser needs.

**Why:** Finviz moved its classification chips from `screener?v=111&f=sec_technology` to
`/screener/stocks?v=111&f=sec_technology`. The old regex still matched nothing without erroring, so
`sector`, `industry`, `country`, `market_cap_class` and `exchange` became `null` on every quote and the
`fields` map simply labelled them as absent. Nothing failed; the data just quietly stopped existing.

**Consequence:** the chip parser accepts both spellings and matches the filter key rather than the
path. ETFs are recognised as their own classification (`etf_sectype_*` maps to `etf_type`, not to
`sector`), because calling an ETF's fund type a sector is a wrong answer rather than a missing one.

---

## 34. Uncontested fields are filled freshest-first, same as compared ones

**Decision:** after the compared fields are resolved, any field a provider shaped but the spec list did
not cover is taken from the provider order that starts with the freshest print.

**Why:** `setdefault` means the first writer wins, and the loop iterated the *reverse* of the
freshness order while a comment claimed the opposite. Every uncontested field therefore came from the
stalest provider. On a live quote that served a four-day-old TradingView sector over a fresh Finviz
one, and it would have quietly overridden Finviz's EPS with Bloomberg's delayed page once Bloomberg's
`eps` joined the shaped payload.

The compared fields were never affected: they have their own selection. This only decides the fields
where there is nothing to compare, which is exactly where nobody looks.

**Consequence:** a field only one provider shapes (a company website, an AI summary) is still labelled
with that provider, and a field several shape but none compare is labelled with the freshest one. Both
behaviours are pinned by tests.

---

## 35. StockAnalysis is the fifth leg, and its coverage boundary is stated

**Decision:** stockanalysis.com is asked in parallel with the other providers on `stock_quote`,
`stock_prices` and `stock_extended_hours`. Its readings enter `comparisons[].values` and it counts
toward `ALL` / `providers_answered`. It sits immediately before Bloomberg in both `PROVIDER_ORDER`
and `DEFAULT_ORDER`.

**Why it is a leg.** The rule this server applies is that every provider which can answer a field is
asked, in parallel. StockAnalysis can answer price, change, previous close, the session open/high/low,
the 52-week range and volume for any US equity or ETF, so treating it as a side channel would have
been the exact asymmetry the rule forbids: a provider with the same data point, fetched anyway,
left out of the comparison for no reason but that it was added later.

**Why it sits before Bloomberg.** Both orders matter only for display and for the documented
tie-break. It is a live feed, so it should outrank a leg whose prints can be structurally 15 minutes
old. But its coverage is the narrowest of the live feeds (US equities and ETFs, no indices, FX,
crypto or foreign listings), so on an exact print-time tie it should never take precedence over a
provider that carries the same instrument more broadly. Last-but-one is where both statements hold,
and it keeps Bloomberg last for the reason decision 30 gives.

**Why a not-carried instrument is not an error.** The quote API has no search endpoint and answers
`404` for
every instrument class it does not serve. Sending a guess and treating the `404` as a provider failure
would blame the leg for a boundary it declares, so `symbols.resolve_sa` reports it up front and the
attempt is recorded as `NOT_ATTEMPTED`. A `400`/`404` is `NoDataError`; only `401`/`403` or a `5xx`
is a provider error.

**What is weak, and said out loud.** Its quote surface is the same consolidated tape Yahoo serves:
measured penny-identical on price, previous close, day range, volume and the 52-week range across
8 of 8 instruments. Agreement between those two is one tape read twice, not two independent
witnesses. This follows the Bloomberg precedent and is stated in `providers_state.py`, the server
instructions, the catalogue and these docs rather than being presented as extra corroboration.

**Deliberate getter gap.** `pe_ratio` has no `sa_get` in `_quote_specs`. The quote API carries no
fundamentals; P/E lives on the stock page, a second endpoint this tool does not fetch. A getter that
reads a field nobody asked for would make the comparison look broader than it is, which is worse than
the gap. `day_open` is the other deliberate gap, for Finviz and Bloomberg.

**Two mechanical facts that would otherwise corrupt a comparison.** `ts` and `ets` are epoch
**milliseconds**; they are converted in `sa_access`, because passing one through would date a print to
the year 56828 and let it win every freshness arbitration. And `cl` is the previous close while `pd`
merely repeats the current price, so reading `pd` as the previous close would make every change
percentage wrong by the day's move. This is the same shape of bug as Bloomberg's `lastUpdate`
sentinel in decision 30.

**Consequence:** `stock_quote` can now return every provider label in `providers_answered`, and
`comparisons[].values` every reading. A symbol StockAnalysis does not carry is `NOT_ATTEMPTED` for
that leg, never an error and never a silent absence.

---

## Related

- [Architecture](Architecture): how these decisions are implemented
- [Response Contract](Response-Contract): the observable result
- [Development](Development): house rules derived from these decisions
