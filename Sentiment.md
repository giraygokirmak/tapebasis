# Sentiment

`market_sentiment` and the sentiment leg of `combined_analysis` have two backends, chosen at
runtime. **Neither requires an API key.**

| Condition | Backend | `data_provider` |
| --- | --- | --- |
| `MARKETAUX_API_TOKEN` set and usable | Marketaux entity sentiment (licensed) | `TRADINGVIEW` |
| no token, or Marketaux rejected / quota exhausted / outage | Finviz headlines scored locally (VADER) | `FINVIZ` |
| neither available | labelled empty payload, `sentiment_score: null` | `NONE` |

Both produce the same payload shape, so a caller never has to branch on which ran. The payload always
says which one did: `provider`, `scoring`, and the envelope's `data_provider`.

## Why the labels differ

The local path scores **Finviz headlines**. The numbers are Finviz's; only the scoring is ours.
Labelling that response `TRADINGVIEW` would claim a provenance the data does not have: the exact
mislabelling this server exists to prevent. So the local path is `FINVIZ`, and
`sources.FINVIZ` reads `"Finviz headlines scored locally (VADER)"`.

Sentiment is single-source by nature. There is nothing to cross-check a sentiment score against, and
inventing a second opinion would not make it corroborated. The label names whichever feed supplied
the headlines, and that is the honest maximum for this capability. Bloomberg and StockAnalysis are
not candidates here: neither publishes a comparable headline sentiment feed. Their quote pages do join
the cross-check in `stock_quote` / `stock_prices`, but sentiment is a different capability with
nothing to compare against.

## Local scoring

[`sentiment.py`](https://github.com/giraygokirmak/tapebasis/blob/main/src/tapebasis/sentiment.py) is VADER (MIT; ships its own lexicon,
no download, no network) with a financial overlay.

Plain VADER is tuned for social-media text and scores financial headlines as neutral more often than
it should:

| Headline | Plain VADER | With overlay |
| --- | --- | --- |
| `Apple beats estimates, raises guidance, shares surge` | `0.00` (neutral) | `+0.88` |
| `Analysts downgrade Apple on iPhone demand concerns` | neutral | `-0.57` |
| `Apple stock drops on weak margin forecast` | `-0.44` | `-0.66` |
| `Apple announces $100B buyback, dividend raised 4%` | neutral | `+0.64` |
| `Apple: 3 Key Takeaways for Long-Term Investors` | `0.00` | `0.00` |

The overlay adds ~150 domain terms at explicit valences (`beat`, `miss`, `upgrade`, `downgrade`,
`plunge`, `buyback`, `dilution`, `recall`, `layoffs`, …). Valences are floats on VADER's -4…+4 scale:
VADER adds them arithmetically, so a string valence raises `TypeError` at scoring time.

Scoring is **deterministic**: the same headlines always produce the same number. It is a summary of
headline tone, not a prediction and not a trading signal.

### What is aggregated

```
sentiment_score      mean compound score of the scored headlines, in [-1, 1]
sentiment_label      Strongly Bullish > 0.2 > Bullish > 0.05 > Neutral
                     > -0.05 > Bearish > -0.2 > Strongly Bearish
posts_analyzed       how many headlines produced a score
bullish/bearish/neutral_count   buckets; they always sum to posts_analyzed
top_posts            up to 5 headlines ranked by |score|, not by arrival order
scoring              {method, engine, runs, note}
```

`top_posts` is ranked by conviction so the samples shown are the ones that actually moved the
average.

### Neutral is a finding; unavailable is not

| Value | Meaning |
| --- | --- |
| `sentiment_score: 0.0`, `label: "Neutral"` | The headlines were scored and the tone is balanced |
| `sentiment_score: null`, `label: "Unavailable"` | There was nothing to score |

These are never conflated. Reporting `0.0` for a failed fetch would dress a data gap up as a finding:
a reader would conclude "the news is balanced" when the truth is "we could not look".

When the Marketaux path is skipped, the reason is preserved in `licensed_path_unavailable` so the gap
is diagnosable without being an error (falling back is normal when no token is configured).

## Marketaux (optional, licensed)

Setting `MARKETAUX_API_TOKEN` upgrades both news and sentiment:

- `stock_news` gains another feed: licensed article text, publishers and real URLs.
- `market_sentiment` uses Marketaux's own entity sentiment scores instead of local scoring.

Free plan: 100 requests/day, 3 articles per request. The service enforces a hard daily budget
(`MARKETAUX_DAILY_BUDGET`, default **90**, a safety margin under 100) and a 4-hour TTL cache, and
serves stale cache before it serves nothing.

One fetch serves both tools: articles are the news, their entity sentiment is the sentiment. So
`combined_analysis` costs one request, not two.

Because the free plan returns only 3 articles per request, `stock_news(limit=20)` is effectively
capped at 3 headlines on the Marketaux leg. That is a plan limit, not a bug; local scoring over
Finviz headlines has no such cap.

Marketaux is subject to the same outgoing-request discipline as the price providers
([`ratelimit.py`](https://github.com/giraygokirmak/tapebasis/blob/main/src/tapebasis/ratelimit.py)),
plus the daily budget, because its quota is the binding constraint rather than its rate limit.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `MARKETAUX_API_TOKEN` | - | Optional. Enables licensed news + entity sentiment |
| `MARKETAUX_DAILY_BUDGET` | `90` | Request cap per day |

No variable is required for local scoring.

## Related

- [Tools Reference](Tools-Reference): `market_sentiment` in context
- [Response Contract](Response-Contract): `data_provider` semantics
