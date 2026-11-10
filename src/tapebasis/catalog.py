"""Tool catalog metadata: which providers back each tool and how it is checked.

Consumed by ``tapebasis_tool_map`` so an agent can see, before calling
anything, which capabilities are multi-source and which are single-source by
nature, and for the multi-source ones, exactly which fields are compared.

Kept as plain data (no imports) so building the map costs nothing.

``providers`` is the *possible* provider set for the tool, not the outcome of
any particular call: an individual response can degrade to fewer providers if
some fail. The per-call truth is always in the response's ``data_provider``,
and ``providers_answered`` names exactly which providers contributed.
"""

TOOL_CATALOG: tuple[dict[str, object], ...] = (
    # ── Multi-source: every capable provider asked, answers compared ─────────
    {
        "name": "stock_quote",
        "capability": "equity / index / FX / commodity / crypto quote + fundamentals",
        "providers": "ALL",
        "comparison": (
            "price, change %, previous close, volume, session open/high/low, "
            "52-week high/low, P/E, RSI(14)"
        ),
        "notes": (
            "TradingView's scanner, Finviz's quote page, Yahoo's chart API, "
            "StockAnalysis's quote API and Bloomberg's quote page are each asked "
            "natively in parallel, no provider proxies another. Each compared field "
            "resolves to ONE value: the reading "
            "from whichever provider printed more recently (see `freshness`); every "
            "original stays in `comparisons`. Ties fall back to Finviz, then "
            "TradingView, then Yahoo, then StockAnalysis, then Bloomberg. Finviz-only "
            "fields (the 84-field "
            "snapshot, profile, peers, after-hours, and the income/segment breakdown) "
            "ride along labelled per field in `fields` (`fields.<field>.source` names the "
            "provider). The income breakdown is a JSON "
            "island on the same quote page, so it costs no extra request; its statement "
            "amounts are scaled to absolute currency units (`statement.scale_applied` "
            "states the factor) so they share one unit with the segment axes, and "
            "`statement.currency` / `axes.*.unit` plus `axes.*.converted` say whether "
            "finviz converted them. Symbols are resolved per provider, so XAUUSD becomes "
            "OANDA:XAUUSD for TradingView, EURUSD:CUR for Bloomberg, and Finviz and "
            "StockAnalysis are told "
            "they do not carry it; see `resolutions`. A price or day change is only "
            "compared when the prints are within 15 minutes and share a US/Eastern "
            "session date; otherwise the field is reported as not cross-checked. "
            "Bloomberg's equity prints are 15 minutes delayed, so it often lands in "
            "`not_comparable` rather than in the agreement count: that is the delay "
            "being stated, not a provider fault. StockAnalysis covers US equities and "
            "ETFs only and its quote surface is the same consolidated tape Yahoo serves, "
            "so agreement between those two is weak corroboration rather than two "
            "independent witnesses. On FX the day change is never "
            "compared: spot FX has no single official previous close."
        ),
    },
    {
        "name": "stock_prices",
        "capability": "bulk quotes for a symbol list",
        "providers": "ALL",
        "comparison": "price and change % per symbol, across every provider that answered",
        "notes": (
            "Each row carries its own data_provider, `providers_answered` and an `agrees` "
            "flag: a symbol can be multi-source, single-source or NONE independently of "
            "the others. Multi-source rows also carry `price_source`, whose print the "
            "single `price` came from, plus their own `comparisons` block. An FX day "
            "change is reported but never compared, for the same reason as in "
            "`stock_quote`. StockAnalysis answers US equities and ETFs only, so it is "
            "recorded as NOT_ATTEMPTED for anything else rather than as a failure. "
            "Bloomberg is asked about at most 4 tickers per batch because "
            "its page path is paced at 10 s per request; the rest are named in "
            "`warnings` and are not counted as Bloomberg-answered. StockAnalysis has no "
            "such cap: its pacing absorbs a short list."
        ),
    },
    {
        "name": "stock_screener",
        "capability": "US equity screener",
        "providers": "ALL",
        "comparison": "per-ticker price for every ticker both screeners return",
        "notes": (
            "TradingView ranks the whole market server-side; Finviz is then asked about "
            "exactly those tickers, so one universe is compared instead of two rankings. "
            "cross_checked_rows / agreeing_rows / not_comparable_rows summarise the result. "
            "Finviz screener rows carry no print time, so a row match cannot be proven and "
            "is reported as not_comparable. Yahoo has no screener, so it is not asked."
        ),
    },
    {
        "name": "market_indices",
        "capability": "S&P 500, Dow, Nasdaq Composite, Russell 2000, VIX levels",
        "providers": "ALL",
        "comparison": "index level (0.5% tolerance) across every provider",
        "notes": (
            "TradingView SP:SPX / DJ:DJI / NASDAQ:IXIC / TVC:RUT / TVC:VIX, Finviz "
            "DJI/SPX/COMP and Yahoo ^GSPC/^DJI/^IXIC/^RUT/^VIX are mapped to one canonical "
            "name before comparison. Levels are compared only between prints sharing a "
            "US/Eastern session date, so a provider that has rolled into the next "
            "session is treated as newer, not wrong. Day-change % is reported from every "
            "provider but not compared: each derives it from a different reference close, "
            "so a small gap is a formula difference rather than a data conflict."
        ),
    },
    {
        "name": "stock_news",
        "capability": "ticker headlines",
        "providers": "ALL",
        "comparison": "headline-title overlap between the feeds",
        "notes": (
            "Finviz supplies price reactions around each headline; Yahoo supplies its own "
            "search feed. The TradingView leg is the provider's licensed Marketaux feed and "
            "needs MARKETAUX_API_TOKEN; without it TradingView is NOT_ATTEMPTED and the "
            "response is labelled with the feeds that did answer."
        ),
    },
    {
        "name": "stock_options_chain",
        "capability": "options chain for one expiry",
        "providers": "ALL",
        "comparison": "per-contract volume matched by strike (open interest when both report it)",
        "notes": (
            "Finviz and Yahoo both publish chains; TradingView publishes none, but its "
            "scanner independently quotes the underlying (reported as "
            "`tradingview_underlying_price`). Yahoo zeroes open interest on same-day "
            "expiries, so a 0-vs-N pair is counted separately, not as a conflict."
        ),
    },
    {
        "name": "stock_earnings",
        "capability": "earnings dates, history and estimate revisions",
        "providers": "ALL",
        "comparison": "next release date across the TradingView, Yahoo and Finviz calendars",
        "notes": (
            "Finviz owns the reported-quarter tables; its earnings_date is the last "
            "*reported* timestamp, which is why it is returned separately from "
            "next_earnings_date."
        ),
    },
    {
        "name": "stock_extended_hours",
        "capability": "pre-/post-market price",
        "providers": "ALL",
        "comparison": "after-hours price (0.5% tolerance) across TradingView, Finviz, Yahoo, StockAnalysis",
        "notes": (
            "TradingView's scanner exposes premarket_close / postmarket_close (and their "
            "session volumes), Finviz the after-hours print on the quote page, Yahoo "
            "full session windows from 1-minute candles, and StockAnalysis an "
            "extended-hours block next to its regular quote. Every reading stays in "
            "`after_hours_readings`; each pre/post block carries its `volume` when the "
            "feed reports one. StockAnalysis's block is also served whole as "
            "`stockanalysis_extended_hours`."
        ),
    },
    {
        "name": "technical_analysis",
        "capability": "multi-indicator TA (RSI, MACD, EMA, Bollinger, ATR, ADX, structure)",
        "providers": "ALL",
        "comparison": "price, RSI(14), ATR(14), volume against Finviz and Yahoo",
        "notes": (
            "TradingView computes the full indicator stack; Finviz's snapshot and Yahoo's "
            "chart API independently confirm the headline readings in `cross_check`."
        ),
    },
    # ── Finviz-only: served, labelled FINVIZ, explicitly single-source ───────
    {
        "name": "stock_filings",
        "capability": "SEC filing history",
        "providers": "FINVIZ",
        "comparison": "single-source (Finviz SEC feed)",
        "notes": "Neither TradingView nor Yahoo has a filing feed; every response says so.",
    },
    {
        "name": "stock_ownership",
        "capability": "insider + institutional ownership, short interest",
        "providers": "FINVIZ",
        "comparison": "single-source",
        "notes": (
            "Combines several Finviz datasets; a failing dataset is reported in errors "
            "and warnings without losing the others."
        ),
    },
    {
        "name": "stock_peers",
        "capability": "peer-group companies",
        "providers": "FINVIZ",
        "comparison": "single-source",
        "notes": "TradingView's scanner has no curated peer list and Yahoo has none either.",
    },
    {
        "name": "stock_why_moving",
        "capability": "narrative explainer for a price move",
        "providers": "FINVIZ",
        "comparison": "single-source",
        "notes": "Finviz's own editorial feed; no TradingView or Yahoo equivalent.",
    },
    {
        "name": "stock_chart",
        "capability": "rendered PNG candlestick chart",
        "providers": "FINVIZ",
        "comparison": "single-source",
        "notes": "TradingView builds charts as text analysis, not images.",
    },
    {
        "name": "stock_dilution",
        "capability": "dilution risk model (share count, float, cash runway)",
        "providers": "FINVIZ",
        "comparison": "single-source",
        "notes": (
            "Finviz only builds a dilution model for companies whose share count it "
            "considers dilution-prone; a large cap legitimately returns NONE with that "
            "reason. The same tab also renders an income-statement breakdown, but that is "
            "revenue/expense data, not dilution, so it is not substituted here: it is "
            "served by `stock_quote` under `income_breakdown`."
        ),
    },
    {
        "name": "stock_screener_filters",
        "capability": "Finviz screener filter catalogue",
        "providers": "FINVIZ",
        "comparison": "single-source",
        "notes": "Finviz's proprietary filter vocabulary; TradingView uses different column names.",
    },
    # ── Bloomberg-only tools: one provider asked, so one provider labelled ───
    {
        "name": "bloomberg_quote",
        "capability": "Bloomberg's own quote page for one instrument",
        "providers": "BLOOMBERG",
        "comparison": "single-source: this tool asks only Bloomberg",
        "notes": (
            "A call to this tool queries one provider, so it cannot be cross-checked; "
            "the provider itself is a full leg of `stock_quote` / `stock_prices`. Its "
            "equity quotes are delayed (`exchangeDelay` is 15 Minutes), its static "
            "fields duplicate Yahoo's, and its `lastUpdate` is a session sentinel: "
            "`print_time` therefore comes from the last intraday point, and is null "
            "when that point does not match the quoted price. Use `stock_quote` for a "
            "corroborated price; use this when the caller wants Bloomberg's reading "
            "specifically."
        ),
    },
    {
        "name": "bloomberg_markets",
        "capability": "Bloomberg market board: index levels, government benchmark yields, commodities, FX",
        "providers": "BLOOMBERG",
        "comparison": "single-source: this tool asks only Bloomberg",
        "notes": (
            "The government benchmark yield curve is the capability no other provider "
            "here publishes; index, commodity and FX levels ride along as context. The "
            "board carries no per-instrument print time, so no reading is aged or "
            "ordered and the response says so."
        ),
    },
    # ── TradingView-only: served, labelled TRADINGVIEW, single-source ────────
    {
        "name": "stock_backtest",
        "capability": "single-strategy backtest",
        "providers": "ALL",
        "comparison": "return, win rate, trade count, drawdown and Sharpe across feeds",
        "notes": (
            "The strategy runs twice: once on TradingView's chart-websocket OHLCV and once "
            "on Yahoo's chart-API OHLCV. The metric comparison says whether the two feeds "
            "support the same conclusion; `chosen_backtest` names whose numbers are shown. "
            "Finviz has no history endpoint and is not asked."
        ),
    },
    {
        "name": "stock_backtest_compare",
        "capability": "strategy leaderboard for one symbol",
        "providers": "ALL",
        "comparison": "winning strategy on TradingView's bars vs Yahoo's bars",
        "notes": (
            "Both feeds are run through all nine strategies; `winner_comparison.agree` says "
            "whether they picked the same winner."
        ),
    },
    {
        "name": "crypto_top_movers",
        "capability": "crypto gainers/losers on an exchange",
        "providers": "TRADINGVIEW",
        "comparison": "single-source",
        "notes": "Finviz does not cover crypto; Yahoo has no ranked exchange screen.",
    },
    {
        "name": "crypto_bollinger_scan",
        "capability": "Bollinger-band squeeze scan",
        "providers": "TRADINGVIEW",
        "comparison": "single-source",
        "notes": "Finviz does not cover crypto.",
    },
    {
        "name": "crypto_volume_breakout",
        "capability": "volume + price breakout scan",
        "providers": "TRADINGVIEW",
        "comparison": "single-source",
        "notes": "Finviz does not cover crypto.",
    },
    {
        "name": "crypto_multi_timeframe",
        "capability": "multi-timeframe crypto analysis",
        "providers": "TRADINGVIEW",
        "comparison": "single-source",
        "notes": "Finviz does not cover crypto.",
    },
    {
        "name": "crypto_multi_agent",
        "capability": "multi-agent bull/bear debate",
        "providers": "TRADINGVIEW",
        "comparison": "single-source",
        "notes": "Finviz does not cover crypto.",
    },
    {
        "name": "futures_market_overview",
        "capability": "futures overview by category",
        "providers": "TRADINGVIEW",
        "comparison": "single-source",
        "notes": "Finviz does not cover futures.",
    },
    {
        "name": "futures_top_movers",
        "capability": "futures gainers/losers",
        "providers": "TRADINGVIEW",
        "comparison": "single-source",
        "notes": "Finviz does not cover futures.",
    },
    {
        "name": "futures_watchlist",
        "capability": "curated futures watchlist with levels",
        "providers": "TRADINGVIEW",
        "comparison": "single-source",
        "notes": "Finviz does not cover futures.",
    },
    {
        "name": "market_snapshot",
        "capability": "global FX / crypto / index / ETF snapshot",
        "providers": "ALL",
        "comparison": "price per instrument across TradingView's scanner and Yahoo's chart API",
        "notes": (
            "Both providers are asked independently for the same groups; each row carries "
            "`tradingview_price`, `yahoo_price` and an `agree` flag. Finviz has no "
            "equivalent breadth and is not asked. Use market_indices for the Finviz-backed "
            "index read."
        ),
    },
    {
        "name": "bitcoin_market_pulse",
        "capability": "bitcoin trend and volatility pulse",
        "providers": "TRADINGVIEW",
        "comparison": "single-source (CoinGecko supply data behind the provider)",
        "notes": "Finviz does not cover crypto.",
    },
    {
        "name": "market_sentiment",
        "capability": "news-based sentiment score",
        "providers": "FINVIZ",
        "comparison": "single-source",
        "notes": (
            "No API key required. Uses Marketaux entity sentiment when "
            "MARKETAUX_API_TOKEN is set (then labelled TRADINGVIEW); otherwise "
            "scores Finviz headlines locally with VADER + a finance lexicon and "
            "labels the response FINVIZ, because the headlines are Finviz's. "
            "Returns sentiment_score=null rather than 0.0 when nothing can be "
            "scored."
        ),
    },
    {
        "name": "egx_market_overview",
        "capability": "Egyptian Exchange overview",
        "providers": "TRADINGVIEW",
        "comparison": "single-source",
        "notes": "Finviz does not cover EGX.",
    },
    # ── Composite ───────────────────────────────────────────────────────────
    {
        "name": "combined_analysis",
        "capability": "technical analysis + sentiment + news, price cross-checked",
        "providers": "ALL",
        "comparison": "underlying price across TradingView, Finviz and Yahoo",
        "notes": (
            "The price leg is multi-source; the analysis and sentiment legs are "
            "TradingView-only and labelled per field in `fields` (their `source` is "
            "TRADINGVIEW)."
        ),
    },
    # ── Ops ─────────────────────────────────────────────────────────────────
    {
        "name": "tapebasis_health",
        "capability": "upstream schema-drift and availability monitor + rate-limit state",
        "providers": "ALL",
        "comparison": "independent probes of every upstream endpoint",
        "notes": (
            "Runs in the background; drift is reported in every tool response. "
            "`rate_limits` reports per-provider pacing and cooldown after a 429."
        ),
    },
    {
        "name": "tapebasis_tool_map",
        "capability": "this catalogue",
        "providers": "ALL",
        "comparison": "n/a (local metadata, no upstream call)",
        "notes": "Returns this table so an agent can plan calls without spending requests.",
    },
)
