# Troubleshooting

Symptom → cause → fix.

---

## `data_provider` is `TRADINGVIEW`, `FINVIZ`, `YAHOO`, `SA` or `BLOOMBERG`, not `ALL`

**Cause:** at least one provider failed or timed out for this call, so coverage is incomplete.

**Diagnose:** read `errors` in the response. It names the failing provider and a code.

| Code | Meaning | Fix |
| --- | --- | --- |
| `UPSTREAM_TIMEOUT` | Provider too slow | Retry; raise `FINVIZ_TIMEOUT` if persistent |
| `UPSTREAM_RATE_LIMIT` | Too many requests | Raise `TAPEBASIS_<PROVIDER>_MIN_INTERVAL`; check `rate_limits` |
| `UPSTREAM_BLOCKED` | WAF rejected the request | Usually transient; check `tapebasis_health` |
| `NO_DATA` | Provider answered, had nothing for this symbol | Check `resolutions`, then the ticker spelling |
| `PARSE_ERROR` | Markup/JSON shape changed | See [health drift](#tapebasis_health-reports-drift) |
| `NOT_CONFIGURED` | Feature needs a token | Add `MARKETAUX_API_TOKEN`, or ignore: the data is still served |

A single-source response is **not** a failure. The data is served and labelled; the notice says it is
not corroborated. `BLOOMBERG` here means only Bloomberg answered (the `bloomberg_*` tools ask that one
provider), not that Bloomberg is excluded from `ALL`: in `stock_quote` / `stock_prices` it is a full
leg, and its failures appear as ordinary `errors` entries. A `TIMEOUT` from that leg is the 15-minute
delay plus 10 s pacing hitting `TAPEBASIS_BLOOMBERG_QUOTE_DEADLINE`; the other readings are still
valid; the Bloomberg sections below cover the rest. `SA` behaves the same way: it is a leg, so its
failure is an ordinary error, while an instrument it does not carry is `NOT_ATTEMPTED`, not a failure.

**Also check `providers_answered`.** `ALL` means every provider that was asked answered, which can be
only some of them. If a provider is missing from that list and there is no matching `errors` entry,
look for `NOT_ATTEMPTED`: the provider does not carry the instrument at all, and `resolutions` says
why.

---

## `data_provider` is `NONE`

**Cause:** no provider answered.

1. Check `errors`: usually several entries.
2. Run `tapebasis_health(refresh=True)`.
3. Most common root cause is a lost network path or DNS, not the code.
4. For an unknown symbol: `NO_DATA` from every provider is correct behaviour, not an outage.

Never present a value when `data_provider` is `NONE`.

---

## `tapebasis_health` reports `DRIFT`

**Cause:** an upstream changed shape: a renamed JSON field, a moved route, a missing HTML marker.
The endpoint still answers 200, which is exactly why this is detected separately.

1. Read the probe's `message`: it names the field or marker that vanished.
2. Fetch the endpoint yourself and compare against what the parser expects.
3. If upstream genuinely changed: update the parser or shaper, then reset the baseline.
4. If the change looks temporary/interstitial: wait one interval, re-check with `refresh=True`.

**Do not reset the baseline before fixing the parser.** That converts a detectable break into a
silent wrong answer.

```bash
rm ~/.tapebasis/health_state.json     # only after fixing the parser
```

---

## Prices differ between providers

**Cause:** normally the print times differ, or a field is derived differently.

1. Read `freshness.decision` first. `newest` means one provider printed later and its value is the
   one shown; that is not a conflict.
2. Read `comparisons[].diff_pct`: how far apart, in percent.
3. Compare against `tolerance_pct` for that field.
4. Within tolerance → `match: true`, no warning. Normal.
5. Beyond tolerance → `match: false`, named in `notice` and `warnings`.
6. `match: null` with `not_comparable: true` → the readings were not judged at all. The reason in
   `pairs[].not_comparable` says which: different session dates, a print past the age ceiling, no
   print time to prove the observation, a declared feed delay (Bloomberg's 15 minutes), or a field
   with no shared definition (FX day change).

**Check `sources` before assuming a bug.** Each label names the upstream that leg actually called:
TradingView's scanner, finviz.com, query1.finance.yahoo.com, stockanalysis.com and bloomberg.com. A
closed market should agree to the cent; an intraday read legitimately will not.

If a mismatch is systematic on one field, the tolerance may be wrong. See
[Development § Choosing a tolerance](Development#choosing-a-tolerance).

---

## `change_percent`, `previous_close` or `volume` is `not_comparable`

**Expected**, and not a defect. Those fields are measured against the previous close of the session
the print belongs to. Finviz mid-session and Yahoo at the prior close answer two different questions,
so the pair is excluded from the agreement decision with the reason recorded in
`pairs[].not_comparable`.

The price is compared when the prints are close enough to be the same observation; past that window
it is reported as `not_comparable` too, with the gap in minutes. A price points at an instant, so two
prints 20 minutes apart are two observations and their difference is the market moving. If you need a
like-for-like day change, compare providers whose `freshness` timestamps share a session date and are
within 15 minutes of each other.

On FX this is permanent, not a timing accident: spot FX has no single official previous close, so
`change_percent` is never compared there. The reading from every provider is still reported.

---

## `bloomberg_quote` returns a price that differs from `stock_quote`

**Expected.** Bloomberg's equity pages are delayed (`exchangeDelay` is `15 Minutes`), so its print is
older by design. `stock_quote` already asks Bloomberg and compares it: when its print is a delay length
away from the others, the pair is reported as `not_comparable` with that reason instead of being
counted as agreement or as a conflict. The single `price` comes from the newest print, and Bloomberg is
last in the tie-break order, so it never wins one.

Read `exchange_delay` and `print_time` in the `bloomberg_quote` payload before quoting it. If
`print_time` is null, the intraday series did not end at the quoted price and the response says so in
`print_time_missing_reason`; that is deliberate, because a timestamp describing a different number is
not a print time.

---

## `bloomberg_*` returns `NONE` or `UPSTREAM_BLOCKED`

**Cause:** bloomberg.com answered 403.

| Symptom | Cause | Fix |
| --- | --- | --- |
| `UPSTREAM_BLOCKED` | The anti-bot wall, usually after a burst | Wait; the provider pauses itself (`rate_limits.BLOOMBERG.cooling_down_s`) |
| `NOT_CONFIGURED` | `curl_cffi` is not installed | `pip install curl_cffi`; the site rejects plain HTTP clients on the TLS fingerprint |
| `SCHEMA_DRIFT` | The page no longer carries `__NEXT_DATA__` | Treat like any other upstream drift |
| `NO_DATA` | Bloomberg has no quote for that id | Check the id spelling (`AAPL:US`, `SPX:IND`, `EURUSD:CUR`) |

Bloomberg is deliberately not probed by the health monitor: an `httpx` probe gets a 403 robot page
from a healthy provider, so it would report a false outage. The tool response itself is the
availability signal, and `rate_limits.BLOOMBERG` shows whether it is cooling down.

---

## `stock_quote` returns `peers` with `compared: ["FINVIZ"]` inside an `ALL` response

**Expected.** `stock_quote` mixes sources: price and core metrics are compared across providers, but
the fundamentals snapshot, company profile, peers and after-hours print exist only on Finviz.

`fields` exists precisely for this. `data_provider: ALL` means every provider that was asked answered
for this call, not that every field was covered by every provider. Per-field truth is in `fields`:
`source` names the one provider whose value is in `data`, `compared` the providers that supplied a
reading for that field, `agreement` the cross-check result.

---

## `fields.price.source` is one provider even though four answered

**Expected, and deliberate.** `data.price` holds one value: the reading chosen as the freshest
print. Four providers supplied a price, they were compared, one won. A field descriptor that said
"ALL" there would read as if the number were a joint product of the four providers when it is one
provider's print. `compared` names the four; `comparisons[].values` holds every reading if you need
the others.

---

## `market_sentiment` returns `provider: local-vader` and `data_provider: FINVIZ`

**Expected** when `MARKETAUX_API_TOKEN` is unset or rejected. The headlines are Finviz's; only the
scoring is local, so the label is `FINVIZ`.

If you expected the licensed path:

1. Check `data.licensed_path_unavailable`: it carries the reason.
2. Most common: no token, expired token, or the daily budget is spent.
3. `MARKETAUX_DAILY_BUDGET` defaults to 90 under a 100/day plan.

To use the licensed path, set `MARKETAUX_API_TOKEN`. To accept local scoring, do nothing.

---

## `market_sentiment` returns `sentiment_score: null`

**Cause:** there was nothing to score: Marketaux unavailable **and** Finviz headlines unavailable.

Read `note` for both reasons. This is deliberate: `null` means "we could not look", `0.0` would mean
"the news is balanced". They are never conflated, because a data gap must not read as a finding.

---

## Sentiment disagrees with my own reading of the news

**Expected sometimes.** Scoring is a lexicon over headline text, not comprehension. It cannot parse
negation or long-range context, so some headlines will land wrong.

Practical notes:

- It is deterministic and cheap, not accurate in an absolute sense: a triage signal.
- `top_posts` shows the highest-conviction headlines, so you can audit what drove the average.
- `posts_analyzed` tells you the sample size; a score over 3 headlines is weak evidence.
- It is not a trading signal, and the payload says so.

If a specific domain word is scored wrong, adding it to the overlay in `sentiment.py` with an
explicit valence is the fix. Use a **float**: VADER adds valences arithmetically and a string raises
`TypeError`.

---

## `combined_analysis` has an empty `news` leg

**Expected** without `MARKETAUX_API_TOKEN`: that leg is Marketaux-only. The sentiment leg still works
(local scoring), and `data.news` says why it is empty. The price cross-check is unaffected.

---

## A tool hangs for ~25 s then returns single-source

**Cause:** one provider hit its HTTP timeout and the others' data still went out. The fan-out waits
for every leg, so latency is the slowest one.

Tuning: lower `FINVIZ_TIMEOUT` (default 25 s) or `TAPEBASIS_SA_TIMEOUT` (default 20 s) to fail faster,
at the cost of losing slow-but-valid answers. Bloomberg's leg is already bounded by
`TAPEBASIS_BLOOMBERG_QUOTE_DEADLINE` (12 s), so it becomes a stated `TIMEOUT` instead of holding the
whole response.

---

## Responses suddenly degrade to one provider

**Cause:** usually a rate-limit cooldown, not an outage.

1. Call `tapebasis_health()` and read `rate_limits`. A positive `cooling_down_s` means that provider is
   in its post-`429` pause right now, and a rising `block_streak` means it has been blocked repeatedly.
2. Let it decay (5 s doubling to 120 s, with jitter). A fan-out over many tickers can trip it.
3. If it recurs, raise `TAPEBASIS_YAHOO_MIN_INTERVAL` first: Yahoo is the most sensitive provider.
4. TradingView's websocket reports a block as `invalid symbol` / `resolve error`. Those are treated as
   rate limiting, so a burst does not permanently poison the symbol-resolution cache.

---

## `/health` says healthy but tool calls fail

`/health` reads the **cached** verdict and makes no upstream call, by design, so a Finviz outage does
not mark the container unhealthy. A stale cache can therefore look green while upstreams are broken.

```bash
tapebasis_health(refresh=True)
```

---

## Container is unhealthy

```bash
docker compose ps
docker compose logs --tail=100 tapebasis
```

1. `start_period` is 15 s; a slow first probe can trip an early check. Wait, then re-check.
2. Confirm `HOST=0.0.0.0` inside the container: loopback makes the port mapping useless.
3. Confirm the health path is `/health`, not `/mcp`.

---

## Container accumulates `<defunct>` processes

**Cause:** the server is PID 1 and Python does not reap children. Docker starts the `HEALTHCHECK`
and every `docker exec` inside the container's PID namespace with a parent outside it, so those
processes are reparented to PID 1 and stay as zombies when nothing calls `wait()`.

**Diagnose:**

```bash
docker top tapebasis -o pid,stat,cmd | head
docker exec tapebasis ps -eo pid,stat,comm | awk '$2 ~ /Z/'
```

**Fix:** run under an init. The image already does (its entrypoint is `tini --`), and
`docker-compose.yml` sets `init: true`. If you built your own image without `tini`, add
`--init` to `docker run`, or `init: true` to the compose service.

Zombies are not why the container restarts, but a PID 1 that ignores `SIGTERM` turns every stop
into the 10 s kill timeout and then a hard `SIGKILL`; `tini` forwards the signal so shutdown stays
graceful.

---

## `ModuleNotFoundError: tapebasis`

The package is not installed in the interpreter the MCP client uses.

```bash
pip install -e .
# or point the client at the venv's absolute path:
#   "command": "/absolute/path/.venv/bin/tapebasis"
```

MCP clients do not inherit your shell `PATH`; absolute paths avoid the whole class of problem.

---

## Symbol returns `NO_DATA` but I know it trades

Read `resolutions` first. It shows exactly which ticker each provider was asked for and how it was
derived (`explicit`, `alias`, `search`, `none`).

| Case | Handling |
| --- | --- |
| `BRK.B` ↔ `BRK-B` | Normalised automatically |
| `^GSPC` ↔ `SPX` ↔ `SP:SPX` | Aliased to `SPX` |
| `RUT` vs `IWM` | Index vs its ETF: **different instruments**, never aliased |
| `XAUUSD` (spot gold) | TradingView `OANDA:XAUUSD` and Bloomberg `XAUUSD:CUR`. Yahoo has no spot pair (`XAUUSD=X` is a 404), and Finviz and StockAnalysis do not carry it |
| `WTI` / `BRENT` / `GOLD` / `SILVER` | Registry aliases: `WTI` -> `FX:USOIL` on TradingView (never `NYSE:WTI`, an equity), `GOLD` -> `XAUUSD`, `SILVER` -> `XAGUSD` (`TVC:SILVER` on TradingView) |
| `CL1!` / `GC=F` (front futures) | Same instrument, both spellings: TradingView `NYMEX:CL1!`, Yahoo `CL=F`, Bloomberg `CL1:COM`. Spot (`USOIL`) and futures (`CL1!`) are separate rows and never compared with each other |
| `BTCUSD` | TradingView `BITSTAMP:BTCUSD`, Yahoo `BTC-USD`, Bloomberg `XBTUSD:CUR`; Finviz and StockAnalysis have no crypto |
| `EURUSD` | TradingView `FX:EURUSD`, Yahoo `EURUSD=X`, Bloomberg `EURUSD:CUR`; Finviz and StockAnalysis have no FX |
| `SPX` / `DJI` | Finviz has no per-ticker index page (`/stock?t=SPX` is a 404, and `COMP` there is Compass Inc), and StockAnalysis's quote API has no index route. Use `market_indices` |
| Non-US (`.IS`, `.CA`) | TradingView only, unless Yahoo or Finviz happens to list it; StockAnalysis's quote API is US-only |
| `BRK-B` | StockAnalysis spells it `brk.b`; the dash is converted mechanically |

A resolution of `none` is not an outage: it means the provider genuinely has no such instrument, and
its `note` says so. That is why a `NONE` resolution never appears in `errors`.

If Finviz silently resolves a delisted/renamed ticker, the response carries `ticker_warning` with
both the requested and resolved symbol. Never assume they are the same.

---

## Related

- [Health Monitor](Health-Monitor): drift detection in depth
- [Response Contract](Response-Contract): reading `errors`/`warnings`
- [Configuration](Configuration): every tunable
