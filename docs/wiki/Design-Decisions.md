# Design Decisions

Non-obvious choices, and the reasoning that produced them. Each entry is a rule that is easy to
violate by accident.

---

## 1. Seven provider states, not two

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
(`FINVIZ`, `TRADINGVIEW`, `YAHOO`, `SA`, `BLOOMBERG`), not to whichever label happened to be first.
Only providers that share the newest instant are tie-break candidates, so a stale provider can never
win against fresher ones.

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

## 36. A field is sourced from one provider, never from all of them

**Decision.** `fields` carries one descriptor per key in `data`: `source` (the provider whose
reading was placed in `data`), `supplied` (every provider that returned a reading for the field),
`compared` (every provider whose reading was actually judged against another one) and `agreement`
(the cross-check result). A field is never labelled `ALL`.

**Why.** `data` holds exactly one value per field, chosen as the freshest print. The old
`{"price": "ALL"}` spelling described *coverage* in the slot that names *origin*, so a reader saw
four providers and one number and concluded the number was a joint product of the four. It is one
provider's print, cross-checked against the others; that is a different fact, and the contract now
says both instead of fusing them.

The fused label also lost single-source-ness silently: `agreement` is `null` only when a field was
never judged, so a cross-checked field that failed comparison (`false`) can no longer be mistaken
for one nobody compared (`null`).

**Why `supplied` and `compared` are separate, later.** Filling `compared` from the supplied set was
the same collapse one level down: five providers can have a price while only three of the ten pairs
are comparable, and then `agreement: true` read as "all five agreed" when two were never judged. See
[#44](#44-coverage-is-partial-when-a-leg-was-asked-and-produced-nothing).

**What did not change.** `data_provider` and `verification` still describe the call: `ALL` means
every provider asked answered, full stop. `comparisons[].values` still holds every provider's raw
reading. The chosen reading is still the freshest print, and `freshness.chosen` still explains why.
`tapebasis_tool_map` had been overloading `fields` to mean tool-to-provider, a different relation in
the same slot; its descriptors now name the catalogue's declared set through the same
`source`/`supplied`/`compared` shape, so one schema describes both.

**Consequence:** reading a value's origin is one lookup (`fields.<field>.source`), its upstream is
one more (`sources[fields.<field>.source]`), and no response ever presents a number as coming from
several providers at once.

---

## 37. One instrument registry, not five per-provider tables

**Decision:** indices and commodities (gold, silver, WTI, Brent, copper, natural gas; spot and
front-month futures) are addressed through one registry in `symbols.py`: one row per instrument,
one column per provider, a `None` cell stating the boundary that provider declares. The per-provider
copies (`_YAHOO_INDEX_ALIASES`, `TV_INDEX_SYMBOLS`, the index/commodity halves of Bloomberg's alias
table, `INDEX_SYMBOLS`, `INDEX_TICKERS`) are derived from it or deleted; the dead `TV_INDEX_SYMBOLS`
copy, never wired to a call site, was removed outright.

**Why:** the same knowledge lived in five tables across four files in three shapes. Adding copper
meant editing every one; a stale spelling drifted silently. Worse, the dynamic search path is
*wrong* exactly here: `WTI` resolves to `NYSE:WTI` (W&T Offshore, an equity), `GOLD` to
`NYSE:GOLD`, `CL` to `NYSE:CL` (Colgate-Palmolive), and TradingView's search offers `TVC:USOIL`,
which its own scanner cannot quote. A closed set of instruments whose names collide with real
equities needs a table, and it needs exactly one.

**The registry is addressing, never scope.** A filled cell says which ticker to ask that provider
for; every provider with a filled cell is still asked in parallel, and the fan-out is unchanged. A
`None` cell records a boundary the provider itself declares ("no spot pair", "indices feed only"),
reported as `NOT_ATTEMPTED` with the reason. One row is one instrument: `RUT`/`IWM` and
`XAUUSD`/`GC1!` stay separate rows, so a spot price is never compared with a futures price.

**A registry row is not snapshot membership.** The registry is broader than the fixed list
`market_indices` reports (`INDEX_SNAPSHOT`: SPX, COMP, DJI, RUT, IWM, VIX). `NDX` was added as a row
so a single-instrument quote folds every spelling (`NDX`, `^NDX`, `NASDAQ:NDX`, `NDX:IND`) onto
one instrument instead of steering Finviz/StockAnalysis to their stock endpoints, and so
Bloomberg's `^NDX` no longer resolves to the equity-class id `^NDX:US` but to `NDX:IND`. The
provider snapshot tables are derived from the registry *restricted to the snapshot list*, so the
row does not silently join the loop. `WTI=F`/`WTIF` are aliases of the front-month future row
(`CL1!`) for the same reason: left to search, Yahoo's futures convention applied to the commodity's
name lands on `XETR:WTIF`, the WisdomTree Japan ETF, a different instrument at a tenth of the
price.

**Consequence:** a registry row is cheap to audit (tests assert every cell is either a spelling or
a documented `None`, and that no two rows claim the same provider spelling), and every spelling in
it was verified against the live upstreams, not copied from another provider's vocabulary.

## 38. One pooled connection per upstream, and one pacing wait per request

**Decision:** each upstream gets one HTTP client per event loop (`http_pool.py`), created on first
use and closed by the lifespan. Bloomberg, whose transport is `curl_cffi`, gets one pooled session
by the same rule. Provider requests wait for their turn in the shared limiter exactly once: the
waiting lives in `call()`, and a request body does not repeat it.

**Why:** every provider built a fresh client per request, so every call paid a new TCP and TLS
handshake. Measured against the live upstreams, that handshake was the largest single term in a warm
response: a Yahoo chart request took 1324-2019 ms with a fresh client and 62-70 ms on a reused
connection, TradingView's symbol search 5555 ms versus 80-284 ms, Yahoo's symbol search 5508 ms versus
56-61 ms, and Bloomberg's page 325-725 ms versus 176 ms. The equivalent mistake on the pacing side
was a second `wait_turn` inside the request body after `call` had already taken its turn, which cost
a whole extra `min_interval` per request (measured: an extra 1000 ms on a Yahoo quote).

**Pacing is not the thing to optimise.** A slower knock rate protects an undocumented upstream, and
dropping a connection does nothing for it, so pooling changes no `min_interval`, no `max_inflight`
and no cooldown. What the change removes is the cost the server added on top of the pace.

**A slow first call is a resolver problem, not a request problem.** On a host whose
`/etc/nsswitch.conf` tries mDNS before DNS, the first `getaddrinfo` of a process costs about 5 s
while every later one costs ~20 ms. The lifespan and `/health` therefore start a background
`warm_origins()` that resolves every httpx upstream once, so that second is not on the first user
request's critical path.

**What was deliberately not done.** Yahoo's multi-symbol endpoints would answer the six index quotes
in one request, but they report different numbers: `/v7/finance/quote` gives
`regularMarketPreviousClose` equal to the current price for `^VIX` (a 0.0 % day change where the chart
path reports -2.31 %), and `/v8/finance/spark` reported 281.88 for `IWM` where the chart path reports
280.58. One request is not worth a wrong day change, so the snapshot asks the six quotes
concurrently and keeps the chart path.

**Consequence:** a warm `stock_quote` fell from 1.3-2.0 s to tens of milliseconds once caches are
warm, and the parallel provider legs from 1328 ms to 986 ms with the same providers answering.

---

## 39. An `asyncio` primitive belongs to the loop that created it

**Decision:** the semaphore and interval lock behind `min_interval` / `max_inflight` are created per
event loop on first use, in a weak table keyed by the loop, exactly as `http_pool` keys its clients
and `singleflight` keys its in-flight table.

**Why:** an `asyncio.Semaphore` or `asyncio.Lock` built at import time belongs to no loop. It binds to
the first loop that *contends* it, and the second loop to contend raises
`RuntimeError: <asyncio.locks.Lock ...> is bound to a different event loop`. That is invisible in a
single-loop server and breaks the moment anything starts a second loop: a test runner, a script, a
re-entrant start. The limiter is process-wide and shared, so it was the one place where "one per
loop" had not been applied.

**Consequence:** a limiter's pacing state (`_last_call`, cooldown, cache) stays process-wide on
purpose, because it describes the upstream's patience rather than any one loop. Only the primitives
that a loop must own are per loop.

---

## 40. Identical concurrent work is merged, and never cached by that merge

**Decision:** `singleflight.py` runs `factory()` once per equal key per loop. The first caller
performs the work, everyone else awaits the same task, and the entry disappears when it finishes.

**Why:** a cache answers "have I done this already" and cannot answer "am I doing this right now", so
two identical questions in the same instant both miss it and both go to the network. Measured before
the module existed: 8 concurrent `resolve("AAPL", "TRADINGVIEW")` calls made 8 upstream searches, and
5 concurrent identical `stock_quote` calls made 5 Yahoo requests, serialised behind
`max_inflight=1`, so cost grew linearly with the caller count. An agent asking for one quote and then
for a batch in the same turn does exactly that.

**A cancelled waiter is detached, not propagated.** Waiters use `asyncio.shield`, so one caller
giving up does not cancel a request the others are still waiting on. A task whose every waiter is
gone still finishes; it is one request the process was already making.

**Single-flight is not a cache.** Nothing is stored, so a request made a moment later is a real
request. Caching stays each provider's short TTL cache, where the staleness ceiling is stated.

---

## 41. Drift is judged on the fields the parser reads, not on the whole shape

**Decision:** every JSON probe declares `watched_keys`, the field names its parser reads, and drift
is reported only when one of those disappears. An added key is never drift. The whole-payload
fingerprint is still recorded, for diagnosis.

**Why:** a whole-shape comparison reports a removed key nobody reads as an outage. Two cosmetic
upstream removals (`COMP.premarketProxyTicker` and `data.epv`) made every response carry
`degraded: true` and three warnings for as long as the process lived, which trains a reader to ignore
the warning that matters.

**Matching is exact on the key, at any depth.** The same field sits at different depths per endpoint
(a scanner row is `data[0].d`, a StockAnalysis quote is `data.p`), so a depth-specific path per
provider would be another thing to maintain and get wrong. The question the check answers is "is the
field this parser reads still somewhere in the payload".

**Accepting a new baseline is a decision surface.** `tapebasis_health(accept_baseline=True)`
re-records the current shape and clears drift, because the alternative was a verdict that could only
be cleared by deleting the state file. It reports which probes it re-recorded and which it skipped,
and a probe that is `DOWN` keeps its old baseline because it has no shape to record. Making this an
explicit parameter rather than a side effect keeps "the upstream changed" separate from "I have
decided the change is fine".

---

## 42. Blocking provider work gets its own bounded pool

**Decision:** synchronous provider calls run in a dedicated `ThreadPoolExecutor`
(`blocking_pool.py`, `TAPEBASIS_BLOCKING_THREADS`, default 4) created per event loop, not in the
loop's default executor via `asyncio.to_thread`.

**Why:** half the provider layer is blocking: TradingView's screener posts with `requests` and sleeps
through its own backoff, its history path opens `urllib`, and the EGX, options and backtest services
do the same. The default executor is shared with everything else that pool serves, twelve workers on
an eight-core host, so a whole-market screen can occupy every one of them for seconds while a fast
path that needs one thread queues behind it. The slow work is not more urgent for being slower; it is
less urgent.

**The limiter, not this number, controls the request rate.** The ceiling only bounds how many slow
calls sit in flight at once, and it is deliberately smaller than the default executor's so a fan-out
cannot flood upstreams the limiters are pacing anyway.

---

## 43. One identity function per instrument, per provider

**Decision:** Bloomberg identity is decided in exactly one place,
`bb_access.resolve_bloomberg()`. Every path that asks Bloomberg goes through it, including the
cross-checked tools.

**Why:** `tools_market` resolved through the instrument registry, which states `WTI` has no Bloomberg
spot series, while `bb_access.to_bloomberg()` guessed `WTI:US` from the mechanical rule. The same
symbol was therefore "not carried" to one tool and "W&T Offshore Inc at 2.89" to the other. `USOIL`
became `USOIL:US`, which answers a robot page.

**A boundary the instrument declares is not a resolution failure.** A registry row with an empty
provider cell and a note is a stated limitation of the provider, so it resolves to `symbol=None` with
that note. `to_bloomberg()` refuses the same case rather than guessing, so no caller can invent an id
that belongs to something else. The id a response reports is always the id it fetched.

---

## 44. Coverage is PARTIAL when a leg was asked and produced nothing

**Decision:** `DataProvider` gains `PARTIAL`. `ALL` means every provider that was *asked* answered;
`PARTIAL` means more than one answered while at least one provider that was asked produced nothing.
`verification_for` maps both onto `MULTI_SOURCE`. The ask set is explicit: `Pair.asked` derives it
from the attempts (`error.code != "NOT_ATTEMPTED"`), and `provider_from_answered(answered, asked)`
takes it as an argument.

**Why:** a live `stock_quote` response reported `data_provider: ALL` beside `errors: [{YAHOO, ...}]`
and three answers. Coverage is a claim about the providers a call asked, so listing a failure in the
same payload and then claiming complete coverage is a false statement, not a rounding of one. The
measured case was not a one-off: any provider outage during a fan-out produced it.

**`NOT_ATTEMPTED` is not a failure.** A provider with no endpoint for the request, or one that does
not carry the instrument, was never asked; counting its silence as missing coverage would make every
`XAUUSD` or `WTI` response `PARTIAL` for a boundary that is declared in the registry. Only an
attempt that was made and produced nothing changes the label.

**Consequence:** a caller can now trust `ALL` literally. `PARTIAL` says the values are served but a
leg is missing, and `errors` names it. `providers_answered` remains the precise list either way.

---

## 45. `supplied` and `compared` are different questions about a field

**Decision:** `field_source()` returns `{source, supplied, compared, agreement}`, and
`compared_providers(comparison)` extracts the providers on a side of any pair that reached a verdict
(`match is not None`). `compared` is never wider than `supplied`.

**Why:** filling `compared` from the supplied set reintroduced the original collapse one level down.
Five providers can supply a price while only some of the pairs are comparable; the rest were excluded
for a reason (different session, declared feed delay, no print time, no shared definition). Reporting
`agreement: true` against the supplied set therefore claimed agreement for providers that were never
judged. The measured shape: a `technical_analysis` price row with five suppliers, ten pairs, three
comparable.

**A field a tool does not compare has an empty `compared`.** `stock_prices` compares `price` and
`change_percent` only; `previous_close` and `volume` are served from the freshest provider that has
them and carry `supplied` for who answered with `compared: []`. Listing suppliers there would claim a
check that never ran.

**Back-compat:** `compared` is still the third positional argument, so old call sites keep working;
`supplied=` is the keyword that makes the split explicit.

---

## 46. A provider that prints a time is a provider that can be dated

**Decision:** the TradingView leg now asks its scanner for `update_time` and exposes it on the
analysis payload (`update_time`, separate from the library's own `Analysis.time`). Finviz's compact
`YYYYMMDD` index date is pinned at US/Eastern midnight, not UTC midnight.

**Why:** `technical_analysis` had four `compare_values` calls with no print-time guards, because the
TradingView payload carried no observation time to guard against. Its only time-ish field was
`timestamp: "real-time"`, a static string. The scanner was already returning the print time; the
wrapper simply never requested the column. Without it every cross-check had to either compare across
sessions or drop the provider.

The compact-date bug was the mirror image: Finviz renders `20261111`, and parsing that as UTC
midnight lands on the previous ET date, so a current session was read as the prior one and its
numbers were mixed with genuinely-current ones. A date without a zone is a market-calendar date, and
the market is US/Eastern.

**Consequence:** `technical_analysis` reports every price pair as `not_comparable` with the correct
reason (different sessions, or 240 minutes past the window) instead of a false conflict, and
`market_indices` rows are internally consistent.

---

## 47. An index row is one session, not one provider per field

**Decision:** `market_indices` resolves the day-quote block (level, previous close, change, change
percent) from providers whose print belongs to the winner's session date. A provider from another
session is excluded, not merely ranked last. Per-index `fields` name each value's source.

**Why:** the measured row reported SPX at a level 0.74 % above its previous close beside a day change
of -0.38 %. The level and previous close came from the provider that had rolled into today, the
change percent from a row still on yesterday. Four numbers describing one observation contradicted
each other.

**A provider with no print time is still consulted last.** It cannot be shown to disagree with the
winner's session, and TradingView's index rows carry no previous close at all, so excluding undated
providers outright would blank a number another provider shaped from the same session.

**Consequence:** a row can read `previous_close: null` when the winning provider's session has no
previous close to report, which is honest: borrowing the other session's number is the bug.

---

## 48. `range=1d` is not a trading day, and a multi-day window has multi-day sessions

**Decision:** the Yahoo extended-hours request asks for `range=2d`, and the shaper classifies every
candle against its *own* day's session windows from `meta.tradingPeriods`, falling back to
`currentTradingPeriod` when only one day is present.

**Why:** Yahoo stopped returning a `timestamp` array for `range=1d&interval=1m&includePrePost=true`.
It answers with `meta` and `indicators` only, so every call degraded to `errors: [{YAHOO, NO_DATA,
"unexpected response shape: 'timestamp'"}]` and the session timeline vanished from the response
without a test noticing. `range=2d` is the narrowest window that still carries candles.

A wider window brings a second hazard: walking two days of candles against today's single
`currentTradingPeriod` block files yesterday's regular prints as today's pre-market. Each candle is
therefore classified by the windows of the day it falls in. The post window ends after midnight UTC,
so a candle at 00:30 UTC belongs to the previous session's after-hours and must not be filed as the
next day's pre-market.

**Consequence:** the extended-hours response carries real session blocks again, and the classification
is correct across the midnight roll that the wider window introduced.

---

## 49. The price is the session's live print, not the obvious field

**Decision:** `tapebasis.sessions.live_print()` resolves, per provider, which number that provider
would call the price right now, and which session it printed in. `stock_quote` and `stock_prices` serve
that number and publish its `session`. The row's `change_percent` and `previous_close` come from the
same session as the price, so the three numbers in a row describe one observation.

**Why:** the obvious price field goes stale the moment the regular session ends, and nothing in the
response said so. Measured at 08:15 ET on a live pre-market session, `stock_prices("NVDA")` returned
`price: 173.73`, `change_percent: +2.87` while the instrument was trading near 158.90, down 8.5 %.
The provider readings in the same row showed it: TradingView 173.73, Finviz 158.9, Yahoo 173.73, SA
173.73. The winner was TradingView's `close`, which is the regular feed's last trade and had stopped
moving, while TradingView's own `premarket_close` column on the same row streamed 356.7 to 357.4 for
AAPL.

Each provider states the live print somewhere, just not where the plain field is:

| Provider | Stale field | Live field | Own label |
| --- | --- | --- | --- |
| TradingView scanner | `close` | `premarket_close` / `postmarket_close` | `current_session` |
| Yahoo chart `meta` | `regularMarketPrice` | `fulldayPrice` | none, inferred from the clock |
| StockAnalysis | `price` | `extended_hours.price` | `fms` (`pre` / `post`) |
| Finviz quote page | none: `last_close` is already the live print | same | timestamp beside it |

**A provider without a session field keeps its old value.** The swap happens only when the provider
itself names a session other than `regular` and carries a number for it. A provider is never credited
with a print it did not send, so a row from a feed that publishes no extended-hours surface is unchanged
rather than invented.

**The scanner's `close` is not the previous close either.** TradingView computes `change` against the
official previous close while its `close` column holds a stale last trade: measured 355.36 against an
official 355.63 for AAPL. Using `close` as the pre-market baseline reported a move against a print that
was never the close.

**Each print's baseline is recovered from that print's own change.** The scanner publishes a change
beside every price column, and the number it divided by is exactly `price / (1 + change/100)`. The
regular column's `close / (1 + change/100)` reaches the *prior* session's close, which is what a regular
print is measured against; the extended columns' `premarket_close / (1 + premarket_change/100)` reach the
last regular close, which is what an extended print is measured against. They are different reference
sessions, so a branch must derive from its own change and never reuse another branch's baseline.
Measured on a live pre-market session, the pre-market branch reproduced the official previous close
exactly on every symbol probed, while reusing the regular branch's derivation was off by the whole of
the regular move.

**`update_time` is a refresh heartbeat, not a print time.** It was observed advancing while `close`
stayed frozen at the same value, and for NVDA it carried 20:00 ET from the previous evening. It dates
the row's refresh, so it is used as the timestamp of a scanner-sourced print only because it is the
only clock that feed offers, and it is not used to make a stale value win a freshness race.

**The session is read off the served print, not off a nominated leg.** A feed can state a session that
describes where *it* is, while lagging behind the print that wins. Measured at 09:42 ET: the scanner
said `pre_market` because its feed is 15 minutes delayed (`delayed_streaming_900`), and the winning print
was a regular-session one. Labelling from the scanner made `stock_quote` report `pre_market` while
`stock_prices` reported `regular` for the same symbol at the same moment. Both now label the print they
serve, so the two tools cannot disagree, and `price_field` names the provider field that print was read
from.

**Consequence:** `stock_prices` and `stock_quote` return the print the market is actually trading on,
label its session, and a row can no longer imply a day change that contradicts its own
`change_percent`. The measured NVDA row afterwards read price 159.04, `session: pre_market`,
change -8.46 %, previous close 173.73, and the implied change matched the reported change exactly.

---

## 50. A row's baseline belongs to the same session as its price

**Decision:** when the winning provider states the close its own print is measured against, that close
becomes the row's `previous_close`. It is not borrowed from whichever provider holds the freshest copy
of a previous close.

**Why:** the previous close and the price were resolved independently, so a row could pair today's
pre-market price with a close two sessions old. Measured before the fix: price 355.36 from TradingView
and `previous_close` 348.51 from Yahoo. Those two imply +1.97 %, while the `change_percent` beside them
read -0.076 %. The row was internally inconsistent, and the number an agent would compute from it was
reported by no provider at all.

**Why the baseline is exact:** the baseline travels with the print it belongs to, recovered from that
print's own change as `price / (1 + change/100)` rather than borrowed from another column or another
provider. That is the number the provider itself divided by, so it is exact instead of close enough,
and it keeps the reference session right too: a regular print is measured against the prior session's
close and an extended print against the last regular close, which are different numbers by construction.

**Consequence:** a row is a self-consistent observation. Reading `price`, `change_percent` and
`previous_close` from one row and computing the change gives the same answer as the field, whichever
session the row belongs to.

---

## 51. Overnight is an independently read session, not a chart inference

**Decision:** `stock_extended_hours` asks TradingView's `BOATS:` quote socket and Yahoo's
`/v7/finance/quote` endpoint with `overnightPrice=true` for separate Blue Ocean ATS observations.
`overnight` and `overnight_source` select the newest eligible print; `overnight_readings` retains every
provider block, `overnight_comparison` contains the pairwise verdict, and `overnight_errors` preserves
endpoint failures. Those failures also append to the envelope's `errors` without replacing primary
quote-fetch failures. Neither provider's regular, pre/post or primary price is an overnight fallback.

**Why:** Blue Ocean trades 20:00-04:00 ET, a real session with real prints. Yahoo's 1-minute chart does
not cover that window, but its quote header publishes `overnightMarketPrice`, `overnightMarketChange`,
`overnightMarketChangePercent` and `overnightMarketTime`. Yahoo's `regularMarketPrice` is the published
overnight change reference; regular previous close, `fulldayPrice` and post-market price are not
substitutes. The same header supplies no overnight volume, so that field stays null. TradingView's
scanner has no BOATS row, while its quote socket supplies the venue's price, print time, volume,
exchange and feed mode. Live NVDA observations on 2026-11-13 were 166.52 at 08:59:48 UTC through Yahoo
and 166.58 at 08:59:59 UTC through TradingView.

**The price and normalized day change use Yahoo's explicit reference.** TradingView's BOATS `ch` and
`chp` describe its venue baseline and can point in the opposite direction from Yahoo's
`overnightMarketChangePercent` even when the dollar prices match. Preserve them as `reported_change`
and `reported_change_percent`. On the same evidenced overnight occurrence, calculate every block's
`change` and `change_percent` from Yahoo's `reference_close`, and name that fact in `change_reference`.
Never substitute regular previous close, `fulldayPrice` or post-market price. Without a valid Yahoo
reference and matching occurrence, the normalized change and reference remain null.

**Comparison has a calendar boundary.** A common `overnight` label is insufficient because the session
crosses midnight. Each print's 20:00 ET occurrence is calculated, retained as
`session_window_start_utc`, and compared only with the other provider's same occurrence. Two unknown
window starts are not a matching occurrence. Usable print times and the ordinary price-time skew limit
are still required. Agreement between two readers of BOATS is not represented as independent
market-venue evidence. Print timestamps retain seconds in `as_of_utc`.

**Closed-venue evidence stays dated rather than becoming live.** At and after 04:00 ET, a last BOATS
print is preserved with `is_current: false`; `overnight_is_current` is false and that print cannot
replace a pre-market print. TradingView's `out_of_session` and `update_mode: "streaming"` labels alone
do not establish an open venue. A current print must lie between the current occurrence's start and the
response clock, so an old evening print cannot masquerade as the following morning's overnight print.

**Socket deltas are not replacement snapshots.** Each `qsd.v` dictionary is merged onto earlier fields,
so a later volume- or timestamp-only packet cannot erase the price. A quiet empty response and a
price-less result are not cached. Receive deadlines distinguish the websocket timeout class from a
transport failure, and limiter exhaustion remains a typed rate-limit error rather than an unexplained
`overnight: null`.

**Consequence:** consumers can identify the selected provider, read every raw observation, distinguish
no print from an attempted endpoint failure, and avoid mistaking the last overnight trade for live
premarket activity.

---

## 52. Inline images are portable output; local chart files are secondary

**Decision:** `stock_chart` uses `chart_service.get_chart_base64` to obtain bytes once, then returns
base64 and `mime_type` in the JSON envelope alongside an optional local path. It does not call
`download_chart` separately. A local write failure preserves the inline image, returns a null path and
records a warning. The existing path-only service remains available for callers that do not want an
inline payload.

**Why:** a remote client cannot follow a path inside the server's container, and a second fetch wastes
upstream capacity and can serve a different image in the two forms. Inline output is portable and the
path remains for local clients that already use it.

**Retention:** the service keeps at most 32 generated PNGs, ordered by modification time, and never
deletes unknown filenames or other contents of an operator-supplied directory. Pruning is best effort;
a live path is not an archive interface and may eventually refer to a pruned file. A local storage
failure does not turn a working PNG into an unavailable MCP result.

---

## 53. Only build inputs enter the image; the host listener starts closed to other devices

**Decision:** Docker copies only explicit distribution inputs and the installed Python package, not the
checkout. The ignore rules exclude local environments, docs, tests, caches, source-control state and
credential-shaped files, while retaining `.env.example`. Compose binds its host port to loopback by
default and only uses a different host address when `TAPEBASIS_BIND_ADDRESS` is explicitly set. The
container's listener remains `0.0.0.0` so its published port can work.

**Why:** copying the checkout carries the entire build context into an unauthenticated runtime image,
including any local `.env` and credentials. Publishing without a host address exposes the listener on
every interface on common Docker installations. The default must be safe even when an operator is
setting up the service for the first time.

**Boundary:** this is not an authentication feature and not a replacement for content-based secret
scanning. A deliberate remote deployment still requires authentication and TLS in front of the server.
DNS rebinding and host-header protections are a separate server-level change, not silently assumed to
exist here.

---

## 54. Close-confirmed backtest signals fill at the next open

**Decision:** RSI, Bollinger, MACD, EMA cross, Supertrend, RSI pullback, Keltner breakout and triple
EMA evaluate a signal at a completed close and execute its entry or exit at the next bar's open.
A final-bar signal cannot create a position. An open position is forced out at the final close.

**Why:** filling at the same close whose value established the signal used a price the strategy could
no longer trade at. It also allowed a final-bar entry and forced exit on the same bar, which is not an
implementable trade. Separating the signal bar from the execution bar makes the trade log, per-bar
equity and return calculation describe the same fills. Entry-bar equity is marked to that bar's close,
and transaction costs still apply at exit.

**Donchian exception:** its existing high/low breakout model identifies an intrabar event and fills at
the same bar's close. That assumption is preserved rather than silently changing the strategy to a
close-confirmed model; the separate assumption and final-bar entry suppression are explicit in
`execution_model`.

---

## 55. Option identity includes side and expiry, and missing is not zero

**Decision:** an option comparison key is side, expiry and strike, all required. Contract-level dates
take precedence, with the chain-level date supplying a missing contract date. Volume, open interest,
IV and quote fields use the first non-`None` provider alias, so a reported `0` is preserved. Missing
values remain `null`, never a fabricated zero. Session price parsing likewise rejects non-finite
numeric values rather than allowing `NaN` or infinity into freshness and comparison calculations.

**Why:** the same strike can describe calls, puts and multiple expiries. Strike-only matching could
report agreement between different contracts, especially when `expiry=None` lets each provider choose
its nearest expiry. Eager `or` aliases also replaced a zero with an unrelated fallback and made absent
activity indistinguishable from real zero activity.

**Consequence:** when the providers do not establish one shared expiry, `stock_options_chain` leaves
`data.expiry` null and records `data.overlap.not_comparable` with its reason. Differing nearest expiries
are not compared. An explicit expiry for which both providers return the same evidenced date retains
normal comparison behaviour.

---

## 56. A non-comparison is evidence, not agreement

**Decision:** every multi-value pair that cannot be judged remains in `pairs` with `match: null` and
a specific reason: non-numeric values, blank symbols, different sessions and
missing print times all receive reasons. `notice` claims compared fields agree only after at least
one comparison reached agreement. If every comparison is unresolved, it states that no agreement
verdict was reached.

`stock_extended_hours` selects the active or latest evidenced pre/post window rather than preferring
whichever session happens to contain a price. Different named windows and undated reads in a shared
window are not judged. An undated print affects only its own pairs. In particular, TradingView's
regular `update_time` cannot date a separate extended print, so that print stays undated while its
Yahoo and StockAnalysis `as_of_utc`/`price_timestamp` values can establish their own agreement.
StockAnalysis's own pre/post label remains useful evidence even without a timestamp, but an undated
pair cannot agree. Yahoo candle times are seconds-preserving, UTC-aware ISO so this evidence reaches
the existing timestamp parser rather than being discarded by text formatting.

Each `after_hours_readings` entry carries its own print, session, timestamp, normalized `as_of_utc`,
baseline and derived change. It uses the provider's evidenced regular close or extended-change
arithmetic. Finviz can supply its snapshot baseline without proving a session or print time, and those
facts remain null next to the reference instead of suppressing it. The overnight rule of sharing
Yahoo's reference is deliberately not applied to pre/post sessions.

**Why:** silently dropping invalid pairs made an all-empty agreement aggregate indistinguishable from
success. A generic comparison of the first populated extended field could turn yesterday's post print
and today's pre print into a provider conflict. Preserving the raw readings and reason distinguishes
uncorroborated data from both agreement and conflict.

---

## 57. A resolved miss stays visible and keeps its type

**Decision:** resolution is a capability check, not a guarantee of data. In `stock_quote`, a
`NoDataError` after resolution remains `NO_DATA`. `NOT_ATTEMPTED` is reserved for a provider that the
request never asked.

`stock_prices` records a provider's per-symbol exceptions instead of reducing them to message strings
or converting an entirely empty result to `NOT_ATTEMPTED`. Each row exposes `misses` and `errors`,
with `provider`, `symbol`, the retained exception `code` and `message`. Missing TradingView/Finviz
batch keys become `NO_DATA`, as does a returned payload with no usable price. The envelope
aggregates those same symbol-tagged errors. `agrees` is `null` when neither price nor change percent
reached a verdict, and envelope coverage, comparisons and notice are built from the row verdicts.
Coverage belongs to each provider-symbol request, not a union of provider names: a complete `ALL`
row does not overwrite an attempted miss for another symbol. A Bloomberg budget cutoff is never a
request, so that symbol is absent from its ask set and has no Bloomberg error.

`technical_analysis` passes the resolved TradingView identity to the upstream analysis rather than a
bare ticker with an assumed exchange. A resolved venue wins, then an explicit exchange prefix, then
the caller's exchange argument.

**Why:** dropping these distinctions hid provider misses, discarded actionable error codes and could
claim `ALL` while listing failed legs or claiming agreement without a judged pair. Finviz's
last-reported earnings timestamp is likewise not evidence of an upcoming event, so only TradingView
or Yahoo can populate `next_earnings_date`. `finviz_filters` remains an explicit filter over the
TradingView-selected screener universe rather than an ignored argument or an independent ranking.

---

## 58. Overnight belongs in `stock_extended_hours` until a separate quote expansion

**Decision:** the two metadata fixes above do not add an overnight capability to `stock_quote`.
Carrying overnight there requires new TradingView and Yahoo upstream requests, explicit failure and
coverage semantics, and its own contract tests. It remains separate follow-up work, not an implied
part of the timestamp or reference-baseline repair.

**Why:** silently widening `stock_quote` during this repair would increase request cost and failure
surface for every quote, including instruments with no Blue Ocean session. The current contract
therefore remains explicit: use `stock_extended_hours` for the BOATS price, its other reading,
normalized change and closed-session status.

**Consequence:** `is_current: false` after 04:00 ET remains an ordinary closed-overnight observation,
not an outage. The premarket reading and its comparison stay available independently.
---

## 59. Release publication is downstream of the tested artifact

**Decision:** main tests and package checks never publish. A version tag must match every distribution
and registry version, and the built wheel, sdist, npm tarball and image receive real install or startup
smoke checks. One `release` environment gates all publication. The approved job uses those artifacts
with checksum verification, publishing PyPI, npm and GHCR in sequence, then the MCP Registry after the
packages resolve. Main has no moving image publication and no independent tag image publisher bypasses
this gate.

**Why:** a tag string, a green unit test, or a successfully built file alone does not prove the code
being released. Independent publication workflows allow a later registry to ship after an earlier
smoke test or upload failed. Rebuilding after approval also loses the correspondence between tested
bytes and published bytes.

**Boundary:** registry uploads cannot form one transaction. If a later upload fails, an earlier upload
can remain visible. The pipeline stops instead of pretending a rollback occurred. Its fix is reviewed
deliberately, generally with a new version rather than different bytes carrying an already used one.

---

## 60. Publishing identity is short-lived; npm bootstraps once

**Decision:** PyPI, npm and the MCP Registry use GitHub OIDC in the protected `release` publish job.
No persistent PyPI, npm or MCP Registry token is configured in CI. The PyPI pending publisher can
create the first project. npm cannot be configured as a trusted publisher before its package exists,
so its first public upload is an explicit maintainer operation with interactive two-factor
authentication before the release tag. A set release-environment variable then lets the tag job verify
that exact existing version instead of uploading it twice. Registry version and SHA-512 integrity must
match the tested artifact; the marker alone never skips or replaces a package. Subsequent npm releases
use `release.yml`, the `release` environment and Node.js 24 with its bundled npm CLI, which satisfies
npm's minimum CLI requirement for trusted publishing.

**Why:** a persistent CI token is unnecessary ongoing account exposure. The pending-publisher difference
between registries matters: assuming they both support pre-creation OIDC would guarantee a failed first
npm release, or tempt a permanent token fallback merely to bypass account provisioning. The MCP Registry
namespace needs no separate registry account: its `github-oidc` login proves the workflow's repository
identity and permits the matching `io.github.giraygokirmak/tapebasis` namespace.

**Consequence:** registry availability and account provisioning are release prerequisites, not CI
successes claimed in advance. `server.json`, the npm and PyPI ownership markers and the OCI ownership
label support verified MCP Registry publication after package uploads. `uvx tapebasis` always runs the
Python server; npm supplies only its launcher, not a separate implementation.

---

## 61. Partial release recovery is main-only and MCP-only

**Decision:** a failed tag run is never retried. Recovery uses `workflow_dispatch` on `main` with
`recover_source_run` and `recover_tag` inputs, gated by a separate `release-recovery` environment.
The recovery job validates the source run's tag, commit, and artifact digest, downloads the exact
tested artifacts, and verifies PyPI, npm, and GHCR content match those artifacts. It can only publish
missing MCP Registry metadata; it cannot upload packages or modify container images. If any package
registry differs or is missing, the job stops.

**Why:** retrying a failed tag run reuses the old tag's YAML and risks duplicate uploads or overwriting
existing packages with different bytes. A main-only recovery path allows fixing workflow bugs without
moving tags or rebuilding artifacts. Restricting recovery to MCP metadata prevents accidental package
modification during incident response.

**Boundary:** recovery requires the original tag's artifacts to be intact and unexpired. If the tag
artifacts are missing or damaged, recovery cannot proceed; a new tag with a new version is required.
The `release-recovery` environment must be configured with main-only deployment restrictions and
reviewer approval to prevent unauthorized registry changes.

---

## Related

- [Architecture](Architecture): how these decisions are implemented
- [Response Contract](Response-Contract): the observable result
- [Releasing](Releasing): account setup and the release procedure
- [Development](Development): house rules derived from these decisions
