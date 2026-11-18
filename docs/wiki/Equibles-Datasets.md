# Equibles frozen REST dataset reference

Exact dataset names and documented filters for every grouped family tool. The full surface has 55 tools. Every dataset performs one JSON GET. No free-form URL, automatic pagination or provider fallback is accepted.


## `institutions`

Use this family as `equibles_institutions`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `flows` | `/v1/13f/flows` | dimension [query, string]: How to split the filers: type (default), style, turnover, horizon, aum (13F book size), client (client base), pf (private funds) or country (filer location).<br>reportDate [query, string]: A computed quarter end (yyyy-MM-dd, defaults to the newest). Any other date returns 400 listing the computed quarters.<br>groupBy [query, string]: none (default) or sector.<br>bucket [query, string]: One bucket token of the dimension (e.g. adv or idx) to return only that bucket. |
| `market_activity` | `/v1/13f/market-activity` | bucket [query, string, required]: Required: top-buys, top-sells, new-positions or sold-out-positions.<br>reportDate [query, string]: 13F report date (yyyy-MM-dd, defaults to the latest available).<br>limit [query, integer]: Maximum stocks to return (default 20, max 500). |
| `most_held` | `/v1/13f/most-held` | reportDate [query, string]: 13F report date (yyyy-MM-dd, defaults to the latest available).<br>sort [query, string]: filers (default), filersDelta, value, conviction or crowding.<br>limit [query, integer]: Maximum stocks to return (default 25, max 500). |

## `macro`

Use this family as `equibles_macro`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `cftc_contracts` | `/v1/cftc/contracts` | query [query, string]: Market code, verified futures alias, or search words (e.g. 088691, GC, gold futures, crude oil). Omit to list every tracked contract.<br>limit [query, integer]: Maximum results (default 50, max 500). |
| `cftc_positions` | `/v1/cftc/contracts/{marketCode}/positions` | marketCode [path, string, required]: CFTC contract market code (e.g. 067651 for Crude Oil, 088691 for Gold).<br>startDate [query, string]: Start report date (yyyy-MM-dd, defaults to 1 year ago).<br>endDate [query, string]: End report date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `cftc_positions_latest` | `/v1/cftc/positions/latest` | category [query, string]: Category filter: Agriculture, Energy, Metals, EquityIndices, InterestRates, Currencies (defaults to all). |

## `public_policy`

Use this family as `equibles_public_policy`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `congress_market_activity` | `/v1/congress/market-activity` | days [query, integer]: Trailing disclosure window in days (default 30, max 365; values outside the range are clamped ; the response echoes the applied window).<br>direction [query, string]: Ranking direction: buys (most net congressional buying first, default) or sells (most net selling first).<br>chamber [query, string]: Filter by chamber: senate or house (defaults to both).<br>limit [query, integer]: Maximum stocks to return (default 25, max 500). |
| `congress_members` | `/v1/congress/members` | query [query, string]: Search query ; name words or verified alias (e.g. Pelosi, Cruz, Dan Crenshaw).<br>limit [query, integer]: Maximum results (default 20, max 500; zero or negative values are rejected, values above the maximum are clamped).<br>position [query, string]: Optional position filter: Senator or Representative. Senate and House are accepted aliases. |
| `congress_net_worth` | `/v1/congress/members/{id}/net-worth` | id [path, string, required]: Congress member id (from /v1/congress/members).<br>limit [query, integer]: Maximum years to return (default 20, max 500). |
| `congress_trades` | `/v1/congress/trades` | ticker [query, string]: Listed security ticker (e.g. AAPL or VOO).<br>memberId [query, string]: Congress member id (from /v1/congress/members).<br>transactionType [query, string]: Filter by transaction type: Purchase or Sale (defaults to all).<br>startDate [query, string]: Start transaction date (yyyy-MM-dd, defaults to 1 year ago).<br>endDate [query, string]: End transaction date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `institutions`

Use this family as `equibles_institutions`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `consensus_holdings` | `/v1/consensus-holdings` | institutions [query, string]: Comma- or semicolon-separated institution names or CIKs. Exact names, exact CIKs and verified aliases resolve; a unique partial name resolves, while an ambiguous partial returns 400 with candidate CIKs and latest-quarter context. 2-25 distinct institutions.<br>reportDate [query, string]: 13F report date (yyyy-MM-dd, defaults to the latest common quarter). Must be a report date all resolved funds share ; any other date returns 400 listing the shared dates.<br>minFunds [query, integer]: Minimum number of funds a stock must be held by to appear (default 1 ; note that 1 also includes stocks held by a single fund; set 2 or more for true consensus).<br>limit [query, integer]: Maximum stocks to return (default 30, max 500). |

## `crypto`

Use this family as `equibles_crypto`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `crypto_directory` | `/v1/crypto` | query [query, string]: Keep the coins whose symbol starts with this (e.g. BT); letters and digits only.<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `crypto_quotes` | `/v1/crypto/quotes` | symbols [query, string]: Comma-separated coin symbols (e.g. BTC,ETH,SOL), max 25; BTC/USD and BTC-USD also work. |
| `crypto_bars` | `/v1/crypto/{symbol}/bars` | symbol [path, string, required]: Coin symbol (e.g. BTC) or its pair with a dash (BTC-USD); GET /v1/crypto lists them.<br>interval [query, string]: Candle size: a whole number of minutes from 1min (default) to 240min, such as 5min or 15min, or of hours from 1hour to 4hour.<br>startDate [query, string]: First UTC day, YYYY-MM-DD (default: 7 days before the end, 30 for hourly intervals).<br>endDate [query, string]: Last UTC day, YYYY-MM-DD (default: now).<br>endTime [query, string]: Return only candles that start before this RFC 3339 time; replaces endDate. Pass the oldest candle's time to continue a truncated read, and keep startDate: without it the window slides.<br>limit [query, integer]: Maximum candles to return, newest first (default: 250, max: 500). |
| `crypto_price_history` | `/v1/crypto/{symbol}/prices` | symbol [path, string, required]: Coin symbol (e.g. BTC) or its pair with a dash (BTC-USD); GET /v1/crypto lists them.<br>startDate [query, string]: First UTC day, YYYY-MM-DD (default: the coin's first trade).<br>endDate [query, string]: Last UTC day, YYYY-MM-DD (default: today). To continue a truncated answer, pass the day before its oldest candle.<br>limit [query, integer]: Maximum days to return, newest first (default: 250, max: 500). |
| `crypto_quote` | `/v1/crypto/{symbol}/quote` | symbol [path, string, required]: Coin symbol (e.g. BTC) or its pair with a dash (BTC-USD); GET /v1/crypto lists them. A coin's symbol is not a stock ticker: /v1/crypto/BTC/quote is Bitcoin. |

## `funds`

Use this family as `equibles_funds`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `etf_directory` | `/v1/etfs` | query [query, string, required]: Ticker, fund name, sponsor or ISIN to search for (for example SPY, S&P 500, iShares, SXR8 or IE00B5BMR087); required.<br>exchange [query, string]: Market identifier code of one exchange outside the US to search alone (for example XETR); GET /v1/markets lists the codes.<br>limit [query, integer]: Maximum results to return (default 20, max 500). |
| `etf_profile` | `/v1/etfs/{ticker}` | ticker [path, string, required]: Exact exchange-traded ticker (for example SPY, VOO, or IVV), or MIC:TICKER for a fund listed on another exchange (for example XETR:SXR8), whose figures are in its trading currency. |
| `etf_holdings` | `/v1/etfs/{ticker}/holdings` | ticker [path, string, required]: Exact exchange-traded ticker (for example SPY).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `market_context`

Use this family as `equibles_market_context`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `fda_catalysts` | `/v1/fda/catalysts` | startDate [query, string]: Start date (yyyy-MM-dd, defaults to today).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to 90 days after the start; floored at the start date).<br>limit [query, integer]: Maximum meetings to return (default 60, max 500). |

## `filings`

Use this family as `equibles_filings`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `filings` | `/v1/filings` | ticker [query, string]: Optional stock ticker symbol (e.g. AAPL), or MIC:TICKER for a listing outside the US (e.g. XPAR:AIR); omit for a market-wide feed.<br>documentType [query, string]: Document type filter, by value (e.g. TenK) or form label (e.g. 10-K). Also accepts EarningsCallTranscript for call transcripts, IrNews for investor-relations news and EsefAnnualReport for a European annual report and EsefReport for another European ESEF report; an unknown value returns a 400 listing every valid value.<br>startDate [query, string]: Earliest filing date (yyyy-MM-dd).<br>endDate [query, string]: Latest filing date (yyyy-MM-dd).<br>itemNumber [query, string]: Exact SEC current-report item number (e.g. 2.02 or 5.02).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `filing_search` | `/v1/filings/search` | query [query, string, required]: Search query ; plain keywords or a short natural-language phrase (required). Concise, filing-phrased terms (e.g. 'Data Center revenue') still rank best.<br>documentType [query, string]: Document type filter ; one value or a comma-separated list (e.g. TenK,TenQ), by value or form label (e.g. 10-K).<br>startDate [query, string]: Earliest filing date (yyyy-MM-dd).<br>endDate [query, string]: Latest filing date (yyyy-MM-dd).<br>limit [query, integer]: Maximum excerpts to return (default 5, max 500).<br>excludeTickers [query, string]: Tickers whose filings are excluded from the results ; one value or a comma-separated list (e.g. AAPL,MSFT). Use when a company's own filings would dominate the results for a query about its market.<br>maxResultsPerCompany [query, integer]: Maximum excerpts from any single company (default 0 = unlimited). Set a small value to spread results across more companies for discovery-style queries.<br>match [query, string]: How the query matches: ranked (default) for relevance-ranked retrieval that broadens to any of the words when results are sparse, or phrase for only the excerpts containing the query's words consecutively and in order (case and punctuation ignored). |
| `filing_keyword_search` | `/v1/filings/{documentId}/keyword-search` | documentId [path, string, required]: Document id from the filings list.<br>keyword [query, string]: Keyword or phrase to search for (required).<br>limit [query, integer]: Maximum matches to return (default 20, max 500). |
| `filing_lines` | `/v1/filings/{documentId}/lines` | documentId [path, string, required]: Document id from the filings list.<br>startLine [query, integer]: First line to read (1-based, inclusive; required).<br>endLine [query, integer]: Last line to read (1-based, inclusive; required, capped at the document's last line; a window wider than 500 lines returns its first 500 with hasMore). |
| `filing_search_document` | `/v1/filings/{documentId}/search` | documentId [path, string, required]: Document id from the filings list or a search result.<br>query [query, string, required]: Search query ; plain keywords or a short natural-language phrase (required).<br>limit [query, integer]: Maximum excerpts to return (default 5, max 500). |

## `macro`

Use this family as `equibles_macro`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `economic_calendar` | `/v1/fred/calendar` | startDate [query, string]: Start date (yyyy-MM-dd, defaults to today).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to 30 days after the start date).<br>minImportance [query, string]: Minimum importance tier to include: low, medium, or high (defaults to low = everything).<br>limit [query, integer]: Maximum release dates to return (default 100, max 500).<br>country [query, string]: Market country code, US or CA (defaults to every market). |
| `fred_latest` | `/v1/fred/latest` | category [query, string]: Category filter: InterestRates, YieldSpreads, CorporateBondSpreads, Inflation, Employment, GdpAndOutput, MoneySupply, Sentiment, Housing, ExchangeRates, Market (defaults to all).<br>country [query, string]: Country as an ISO code: US (default) or CA. One response never mixes two countries' series. |
| `fred_series` | `/v1/fred/series` | query [query, string, required]: Series id, standard alias, or search words (e.g. FEDFUNDS, fed funds rate, jobless claims, inflation). Required.<br>limit [query, integer]: Maximum results (default 20, max 500). |
| `fred_observations` | `/v1/fred/series/{seriesId}/observations` | seriesId [path, string, required]: FRED series id (e.g. FEDFUNDS, CPIAUCSL, UNRATE, GDP, T10Y2Y, VIXCLS).<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 1 year ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `funds`

Use this family as `equibles_funds`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `fund_directory` | `/v1/funds` | query [query, string, required]: Fund name, ticker, profileId, series id, registrant, or verified share-class alias to search for (e.g. 'Russell 2000', 'iShares', 'IWM', 'VFIAX'); required.<br>limit [query, integer]: Maximum funds to return (default 20, max 500; zero or negative values are rejected, values above the maximum are clamped). |
| `fund_holdings` | `/v1/funds/{ticker}/holdings` | ticker [path, string, required]: Fund ticker, profileId, SEC series id, or verified share-class alias (e.g. SPY, 'vanguard-500-index-fund-s000002839', S000002839, or VOO).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `fund_operations` | `/v1/funds/{ticker}/operations` | ticker [path, string, required]: Fund ticker, profileId, SEC series id, or verified share-class alias (e.g. MXF, IVV, S000004310, or VOO).<br>limit [query, integer]: Maximum annual reports to return (default 10, max 500; zero or negative values are rejected, values above the maximum are clamped). |

## `public_policy`

Use this family as `equibles_public_policy`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `government_contracts` | `/v1/government-contracts/top` | startDate [query, string]: Start action date (yyyy-MM-dd, defaults to 1 year ago).<br>endDate [query, string]: End action date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum companies to return (default 25, max 500).<br>country [query, string]: Awarding government: US (default) or CA. |

## `market_context`

Use this family as `equibles_market_context`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `index_directory` | `/v1/indexes` |  |
| `index_profile` | `/v1/indexes/{index}` | index [path, string, required]: Index slug or name: "sp-500", "S&P 500", "nasdaq-100", "Russell 2000".<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `index_changes` | `/v1/indexes/{index}/changes` | index [path, string, required]: Index slug or name: "sp-500", "S&P 500", "nasdaq-100", "Russell 2000".<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `index_forecast` | `/v1/indexes/{index}/forecast` | index [path, string, required]: Index slug or name. The Dow publishes no quantitative entry rule and returns 404. |
| `index_fund_flows` | `/v1/indexes/{index}/fund-flows` | index [path, string, required]: Index slug or name: "sp-500", "S&P 500", "Russell 2000". An index with no tracking fund whose daily holdings file is read returns 404. |
| `insider_sentiment_scores` | `/v1/insider-sentiment-scores` | clusterBuysOnly [query, boolean]: Return only cluster buys (three or more distinct insiders buying in the window).<br>minMarketCap [query, number]: Minimum market capitalization in USD (default 0 = no floor; stocks with unknown market cap are excluded when set).<br>minSharePrice [query, number]: Minimum share price in USD (default 0 = no floor; unknown price excluded when set).<br>minDollarVolume [query, number]: Minimum trailing 3-month average daily dollar volume in USD (default 0 = no floor; unknown volume excluded when set).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>bottom [query, boolean]: Walk the ranking from the other end ; heaviest net insider distribution (selling) first. Ranks stay the full-universe positions.<br>ticker [query, string]: Optional stock ticker (e.g. NVDA): returns that one stock's score and universe rank instead of the leaderboard; 404 when the stock is not in the scored universe. |
| `insider_directory` | `/v1/insiders` | query [query, string]: Search query for insider name (required). Punctuation and word order are ignored. Verified aliases bridge public names to SEC legal names, so "Jensen Huang" resolves "HUANG JEN HSUN" without allowing a short substring such as "ann" to match "JOANNA".<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `institutions`

Use this family as `equibles_institutions`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `institutions` | `/v1/institutions` | query [query, string]: Institution name, partial name, or CIK (required).<br>limit [query, integer]: Maximum results to return (default 10, max 500).<br>holderTypes [query, string]: Comma-separated holder type tokens to keep: adv, era, ia, bank, ins, bd, fund, plan, nonus, hc, unk (unk also matches a filer not yet classified). |
| `institution_activity` | `/v1/institutions/{cik}/activity` | cik [path, string, required]: SEC CIK of the institution (see GET v1/institutions).<br>reportDate [query, string]: 13F report date (yyyy-MM-dd, defaults to the institution's latest). Must be one the institution reported ; any other date returns 400 listing the available dates.<br>bucket [query, string]: Optional filter: initiated, increased, reduced or exited.<br>limit [query, integer]: Maximum stocks to return per bucket (default 20, max 500). |
| `institution_beneficial_ownership` | `/v1/institutions/{cik}/beneficial-ownership` | cik [path, string, required]: SEC CIK of the institution (see GET v1/institutions).<br>view [query, string]: default (current and unconfirmed stakes) or all (every stake, including those reported below 5%, exited, or on a security that no longer trades).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `institution_portfolio` | `/v1/institutions/{cik}/portfolio` | cik [path, string, required]: SEC CIK of the institution (see GET v1/institutions).<br>reportDate [query, string]: 13F report date (yyyy-MM-dd, defaults to the institution's latest). Must be one the institution reported ; any other date returns 400 listing the available dates.<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `institution_profile` | `/v1/institutions/{cik}/profile` | cik [path, string, required]: SEC CIK of the institution (see GET v1/institutions). |
| `institution_sector_allocation` | `/v1/institutions/{cik}/sector-allocation` | cik [path, string, required]: SEC CIK of the institution (see GET v1/institutions).<br>reportDate [query, string]: 13F report date (yyyy-MM-dd, defaults to the institution's latest). Must be one the institution reported ; any other date returns 400 listing the available dates.<br>groupBy [query, string]: Grouping level: industry (default) or sector. |
| `institution_style_history` | `/v1/institutions/{cik}/style-history` | cik [path, string, required]: SEC CIK of the institution (see GET v1/institutions).<br>limit [query, integer]: Measured quarters to return, newest first (default 8, max 40). |
| `institution_summary` | `/v1/institutions/{cik}/summary` | cik [path, string, required]: SEC CIK of the institution (see GET v1/institutions).<br>reportDate [query, string]: 13F report date (yyyy-MM-dd, defaults to the institution's latest). Must be one the institution reported ; any other date returns 400 listing the available dates. |

## `market_context`

Use this family as `equibles_market_context`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `investment_adviser_directory` | `/v1/investment-advisers` | query [query, string, required]: Part of the firm's legal or business name (e.g. "Vanguard", "Renaissance"); required.<br>limit [query, integer]: Maximum advisers to return (default 20, max 500; zero or negative values are rejected, values above the maximum are clamped). |
| `investment_adviser_profile` | `/v1/investment-advisers/{crd}` | crd [path, integer, required]: The adviser's Organization CRD number (e.g. 231). |

## `investor_events`

Use this family as `equibles_investor_events`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `investor_events_recent` | `/v1/investor-events/recent` | since [query, string]: First call date to include, yyyy-MM-dd (default 7 days before until).<br>until [query, string]: Day after the last call date to include, yyyy-MM-dd (default tomorrow, so today's calls count). The window may span at most 31 days.<br>eventType [query, string]: Optional event type: EarningsCall, CapitalMarketsDay, InvestorUpdate, AGM, Conference, FiresideChat, or MAndA.<br>market [query, string]: Listing markets as comma-separated ISO country codes (for example GB,FR), or all for every market. Omitted means US.<br>minMarketCap [query, number]: Minimum market capitalization in US dollars. Accepted only with the US market, because other markets carry local-currency figures.<br>tickers [query, string]: Comma-separated tickers (max 25) to follow instead of a market: a US ticker, or MIC:TICKER for a listing outside the US (for example XLON:VOD). Only these companies' events are returned, whatever their market. Cannot be combined with market or minMarketCap; an unknown ticker returns 404.<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `event_live_transcript` | `/v1/investor-events/{eventId}/live-transcript` | eventId [path, string, required]: Investor event id from the investor-events list.<br>after [query, integer]: The highest line seq already received (default -1, the whole text so far); only later lines are returned.<br>run [query, string]: The run value of the previous response; a different run means the recording restarted and the full text is returned with reset=true. |
| `event_questions` | `/v1/investor-events/{eventId}/questions` | eventId [path, string, required]: Investor event id from the investor-events list. |
| `event_slides` | `/v1/investor-events/{eventId}/slides` | eventId [path, string, required]: Investor event id from the investor-events list. |
| `event_speakers` | `/v1/investor-events/{eventId}/speakers` | eventId [path, string, required]: Investor event id from the investor-events list.<br>limit [query, integer]: Maximum speaker turns to return (default 50, max 200; zero or negative values are rejected, values above the maximum are clamped).<br>offset [query, integer]: Speaker turns to skip before the first returned one (default 0) ; pages past the per-request cap. |
| `ipos` | `/v1/ipos` | status [query, string]: Optional lifecycle filter: Filed, Priced, Listed, or Withdrawn.<br>filerType [query, string]: Optional company-type filter: Operating (non-SPAC) or Spac (a blank-check company: SIC 6770, as SEC classifies the filer or, until it does, as its registration statement states).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `ipo_detail` | `/v1/ipos/{cik}` | cik [path, string, required]: The filer's SEC CIK, with or without leading zeros. |

## `market_context`

Use this family as `equibles_market_context`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `listings` | `/v1/listings` | query [query, string]: Company name or ticker to search for (e.g. siemens, ASML or XETR:SIE).<br>isin [query, string]: ISIN to look up (e.g. IE00B5BMR087); cannot be combined with query.<br>exchange [query, string]: Market identifier code to keep (e.g. XETR, XAMS, XLIS); with neither query nor isin it lists that exchange. GET /v1/markets lists the codes.<br>market [query, string]: ISO country code whose listings to list (e.g. US, DE, PT); cannot be combined with query, isin or exchange.<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `market_calendar` | `/v1/market/calendar` | year [query, integer]: Calendar year, e.g. 2026 (defaults to the current year). |
| `market_put_call_ratios` | `/v1/market/put-call-ratios` | type [query, string]: Ratio type: Total, Equity, Index, Vix, Etp (default Equity).<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 3 months ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `market_status` | `/v1/market/status` |  |
| `market_vix` | `/v1/market/vix` | startDate [query, string]: Start date (yyyy-MM-dd, defaults to 3 months ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `markets` | `/v1/markets` |  |
| `prices_latest` | `/v1/prices/latest` | tickers [query, string]: Comma-separated exact listed tickers (e.g. GOOG,GOOGL,BRK-A,BRK-B), or MIC:TICKER for a listing on another exchange (e.g. AAPL,XETR:SIE,XAMS:ASML), max 25. A missing listing is never replaced by its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B. |
| `quotes` | `/v1/quotes` | tickers [query, string]: Comma-separated exact listed tickers (e.g. GOOG,GOOGL,BRK-A,BRK-B) or Canadian, Euronext and NSE MIC:TICKER symbols (e.g. XTSE:RY, XPAR:AIR, XNSE:RELIANCE), max 25. |
| `screener_stocks` | `/v1/screener/stocks` | minMarketCap [query, number]: Minimum market capitalization in USD.<br>maxMarketCap [query, number]: Maximum market capitalization in USD.<br>minPrice [query, number]: Minimum share price in USD.<br>maxPrice [query, number]: Maximum share price in USD.<br>minFilerCount [query, integer]: Minimum number of 13F institutional filers.<br>maxFilerCount [query, integer]: Maximum number of 13F institutional filers.<br>minFilerDelta [query, integer]: Minimum quarter-over-quarter change in filer count.<br>maxFilerDelta [query, integer]: Maximum quarter-over-quarter change in filer count.<br>minShortInterestPercent [query, number]: Minimum short interest as a percent of shares outstanding (0-100).<br>maxShortInterestPercent [query, number]: Maximum short interest as a percent of shares outstanding (0-100).<br>minDaysToCover [query, number]: Minimum days to cover.<br>maxDaysToCover [query, number]: Maximum days to cover.<br>minSqueezeScore [query, number]: Minimum composite short-squeeze score (0-100).<br>maxSqueezeScore [query, number]: Maximum composite short-squeeze score (0-100).<br>minInsiderSentiment [query, number]: Minimum composite insider-sentiment score (0-100).<br>maxInsiderSentiment [query, number]: Maximum composite insider-sentiment score (0-100).<br>minNetInsiderBuy [query, number]: Minimum net open-market insider buying by officers and directors in USD over the trailing 90 days.<br>maxNetInsiderBuy [query, number]: Maximum net open-market insider buying by officers and directors in USD over the trailing 90 days.<br>hasGoingConcernDoubt [query, boolean]: True keeps only companies with unalleviated going-concern doubt; false keeps only companies without it.<br>sector [query, string]: Exact sector name (e.g. Technology, Healthcare). An unknown name is a 400 listing the accepted sectors.<br>industry [query, string]: Exact industry name (e.g. Semiconductors). Prefer sector for broad groups; an unknown name is a 400.<br>index [query, string]: Restrict to members of a covered index, by slug or name (e.g. sp-500, "S&P 500", SPX). A name matching no covered index is a 400 listing the covered ones.<br>market [query, string]: Listing markets to screen, as comma-separated ISO country codes (for example `GB,FR`), or `all` for every market. Omitted means `US`. A non-US row's ticker is the qualified `MIC:TICKER` symbol (for example `XPAR:AIR`) and its price and market cap are converted to USD at the official rate; `localPrice` and `currency` carry the traded close. An unknown code is a 400 listing the covered markets.<br>minPe [query, number]: Minimum trailing-twelve-month price-to-earnings ratio.<br>maxPe [query, number]: Maximum trailing-twelve-month price-to-earnings ratio (e.g. 15 for value screens).<br>minDividendYield [query, number]: Minimum trailing dividend yield in percent (e.g. 3 = 3%).<br>maxDividendYield [query, number]: Maximum trailing dividend yield in percent.<br>minRevenueGrowth [query, number]: Minimum revenue growth in percent, latest quarter vs the same quarter a year earlier.<br>maxRevenueGrowth [query, number]: Maximum revenue growth in percent, latest quarter vs the same quarter a year earlier.<br>minGrossMargin [query, number]: Minimum gross margin in percent (0-100).<br>maxGrossMargin [query, number]: Maximum gross margin in percent (0-100).<br>minDollarVolume [query, number]: Minimum trailing-3-month average daily dollar volume in USD (e.g. 5000000 = $5M/day).<br>maxDollarVolume [query, number]: Maximum trailing-3-month average daily dollar volume in USD.<br>minNetIncome [query, number]: Minimum trailing-twelve-month net income in USD (0 keeps profitable companies only).<br>maxNetIncome [query, number]: Maximum trailing-twelve-month net income in USD.<br>minInstitutionalOwnership [query, number]: Minimum institutional ownership: 13F shares over shares outstanding, in percent.<br>maxInstitutionalOwnership [query, number]: Maximum institutional ownership in percent.<br>minConvictionShare [query, number]: Minimum percent of the stock's 13F filers holding it among their ten largest positions.<br>maxConvictionShare [query, number]: Maximum conviction share in percent.<br>minCrowding [query, number]: Minimum crowding: shares held by high-turnover 13F filers and private-fund advisers, in percent of shares outstanding.<br>maxCrowding [query, number]: Maximum crowding in percent of shares outstanding.<br>minPrivateFundOwnership [query, number]: Minimum ownership by 13F filers that advise private funds (Form ADV), in percent of shares outstanding.<br>maxPrivateFundOwnership [query, number]: Maximum private-fund adviser ownership in percent of shares outstanding.<br>minActiveHolderChange [query, number]: Minimum like-for-like share change of actively managed 13F holders over the quarter, in percent.<br>maxActiveHolderChange [query, number]: Maximum like-for-like share change of actively managed 13F holders, in percent.<br>minHolderTenure [query, number]: Minimum value-weighted holder tenure in quarters.<br>maxHolderTenure [query, number]: Maximum value-weighted holder tenure in quarters.<br>minEstimatedCostGap [query, number]: Minimum quarter-end price versus the holders' estimated average cost, in percent (negative means an estimated loss).<br>maxEstimatedCostGap [query, number]: Maximum quarter-end price versus the holders' estimated average cost, in percent.<br>sortBy [query, string]: Sort key: marketcap, ticker, name, price, filers, filerdelta, sipct, dtc, squeeze, sentiment, insiderbuy, pe, divyield, revgrowth, grossmargin, dollarvol, netincome, instown, conv, crowd, pfown, actlfl, tenure, or costgap (default marketcap). An unknown key is a 400, never silently ignored.<br>sortAscending [query, boolean]: Sort ascending instead of descending.<br>limit [query, integer]: Maximum rows to return (default 50, max 200; zero or negative values are rejected, values above the maximum are clamped).<br>page [query, integer]: Result page, 1-based (default 1) ; combine with limit to walk past the first page. A page past the end returns the last real page (see the response's page field).<br>tickers [query, string]: Comma-separated list of up to 200 tickers to restrict the screen to, so a caller can score stocks they already hold instead of searching the market. Every other bound still applies. Class-share dots (BRK.B) resolve to the listed form and a secondary listing resolves to its issuer and is named in answeredAs; symbols outside the universe come back in the response's notFound array, and covered symbols the market or a bound left out in leftOut, each with its reason. A listing outside the US is its MIC:TICKER symbol (XTSE:SHOP, XPAR:AIR) or its exchange-suffixed symbol (0700.HK, SAP.DE), never the bare ticker; naming one screens every market unless market is set.<br>format [query, string]: Response format: omit or `json` for the JSON envelope, `csv` for a flat CSV file. CSV headers are the stable cols keys rather than display labels, and the envelope's paging metadata rides on the X-Screener-Total-Count, X-Screener-Page, X-Screener-Total-Pages, X-Screener-Not-Found and X-Screener-Not-Found-Count response headers. Any other value is a 400.<br>cols [query, string]: Comma-separated CSV column keys (for example `pe,de,roic,volatility`), applying only with `format=csv`; passing it without CSV is a 400 rather than a silently ignored parameter. An unknown or empty key list is a 400. Omitted means the default column set, and `none` means the pinned columns only. Every file starts with four pinned fields, `ticker`, `name`, `price` and `marketcap`, then one column per key passed; there is no `ticker` key of its own because the pinned `company` column emits ticker and name together. |

## `market_data`

Use this family as `equibles_market_data`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `security_bars` | `/v1/securities/{ticker}/bars` | ticker [path, string, required]: Exact listed US ticker (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or `MIC:TICKER` for a Euronext, Canadian or NSE listing (e.g. XPAR:AIR, XTSE:RY or XNSE:RELIANCE). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>interval [query, string]: Bar size: a whole number of minutes from 1min (default) to 240min, such as 5min or 7min, or of hours from 1hour to 4hour. The answer echoes whole hours in hours (60min as 1hour).<br>startDate [query, string]: First trading date on the exchange's own clock (New York for a US listing), YYYY-MM-DD (default: 7 days before the end, 30 for hourly intervals).<br>endDate [query, string]: Last trading date on the exchange's own clock, YYYY-MM-DD (default: today).<br>endTime [query, string]: Return only bars that start before this RFC 3339 time; replaces endDate. Pass the oldest bar's time to continue a truncated read, and keep startDate: without it the window is counted back again from this time.<br>session [query, string]: regular (default) or extended.<br>adjustment [query, string]: split (default) or raw.<br>limit [query, integer]: Maximum bars to return, newest first (default: 250, max: 500; with format=csv default and max 50,000, at one call for each 500 bars returned).<br>format [query, string]: Omit or json for the JSON envelope, csv for a flat file with one row a bar under the JSON field names. A file costs one call for each 500 bars it returns, stated on X-Bars-Calls; one that needs more calls than the day has left answers 429 and names the limit that fits. The envelope's fields ride on the X-Bars-Returned, X-Bars-Truncated, X-Bars-Delayed, X-Bars-Covered-From and X-Bars-Adjusted-From response headers, plus X-Bars-Currency and X-Bars-Stored-Through for a listing outside the US, X-Bars-Incomplete-Sessions and X-Bars-Unstored-Dates for a Euronext listing and X-Bars-Notice for a Canadian one. |

## `ownership`

Use this family as `equibles_ownership`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `security_beneficial_ownership` | `/v1/securities/{ticker}/beneficial-ownership` | ticker [path, string, required]: Listed security ticker (e.g. NVDA or BRK-B).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `positioning`

Use this family as `equibles_positioning`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `security_fails_to_deliver` | `/v1/securities/{ticker}/fails-to-deliver` | ticker [path, string, required]: Exact stock or ETF ticker symbol (e.g. AAPL or SPY).<br>startDate [query, string]: Start settlement date (yyyy-MM-dd, defaults to 3 months ago).<br>endDate [query, string]: End settlement date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `ownership`

Use this family as `equibles_ownership`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `security_fund_owners` | `/v1/securities/{ticker}/fund-owners` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO), or MIC:TICKER for a listing on another exchange (e.g. XAMS:ASML).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>registrantOrSeries [query, string]: Optional case-insensitive substring filter on registrant or fund-series name. |
| `security_holder_mix` | `/v1/securities/{ticker}/holder-mix` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO).<br>dimension [query, string]: How to split the holders: type (default), style, turnover, horizon, aum (13F book size), client (client base), pf (private funds), country (filer location) or fundtype (registered funds by N-CEN fund type).<br>periods [query, integer]: Quarters to return, newest last (default 4, max 12); each is compared with the quarter before. |
| `security_holder_targets` | `/v1/securities/{ticker}/holder-targets` | ticker [path, string, required]: Listed security ticker (e.g. NVDA).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>sort [query, string]: peerValue (default) or peerWeight. |
| `security_holders` | `/v1/securities/{ticker}/holders` | ticker [path, string, required]: Listed security ticker (e.g. NVDA or VOO).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>source [query, string]: Rows to list: all (default), 13f, 13dg (13D and 13G), 13d, 13g, insider, fund or nonus. A single source lists its rows flat, stale ones flagged.<br>view [query, string]: default (one row per holder, others nested), all (every row flat, stale included) or ultimate (summed holders grouped by ultimate parent; takes no source or holderTypes filter).<br>holderTypes [query, string]: Comma-separated holder type tokens to keep: adv, era, ia, bank, ins, bd, fund, plan, nonus, hc, unk (insiders and holders without a deciding record read unk). |
| `security_institutional_activity` | `/v1/securities/{ticker}/institutional-activity` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO).<br>reportDate [query, string]: 13F report date (yyyy-MM-dd, defaults to the latest available). Must be one of the stock's 13F report dates ; any other date returns 400 listing the available dates.<br>limit [query, integer]: Maximum buyers and sellers to return per side (default 10, max 500). |
| `security_institutional_holders` | `/v1/securities/{ticker}/institutional-holders` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO).<br>reportDate [query, string]: 13F report date (yyyy-MM-dd, defaults to the latest available). Must be one of the stock's 13F report dates ; any other date returns 400 listing the available dates.<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>holderTypes [query, string]: Comma-separated holder type tokens to keep: adv, era, ia, bank, ins, bd, fund, plan, nonus, hc, unk (unk also matches a holder not yet classified). Totals and percentages stay over every institution.<br>styles [query, string]: Comma-separated style band tokens to keep: idx (index-like), sys (systematic-like), conc (concentrated), divact (diversified active), unk (book too small or unvalued to band). Bands come from the newest measured quarter on or before the report date; a holder not measured that quarter matches no style. Totals and percentages stay over every institution. |
| `security_institutional_ownership` | `/v1/securities/{ticker}/institutional-ownership` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO).<br>periods [query, integer]: Maximum number of quarterly periods to return (default 8, max 500). |

## `positioning`

Use this family as `equibles_positioning`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `security_off_exchange_volume` | `/v1/securities/{ticker}/off-exchange-volume` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO). Class shares use a dash (BRK-B); the dot form (BRK.B) is also accepted.<br>startDate [query, string]: Start week (yyyy-MM-dd, defaults to 6 months ago).<br>endDate [query, string]: End week (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `options`

Use this family as `equibles_options`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `security_chain` | `/v1/securities/{ticker}/options/chain` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or MIC:TICKER for a TSX or TSXV listing (e.g. XTSE:RY). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>expiration [query, string]: Expiration date in YYYY-MM-DD format (default: nearest upcoming).<br>minStrike [query, number]: Only include strikes at or above this price.<br>maxStrike [query, number]: Only include strikes at or below this price.<br>type [query, string]: Contract type filter: call or put (default: both).<br>limit [query, integer]: Maximum contracts to return, taken nearest the money (default: 250, max: 500). |
| `security_contract` | `/v1/securities/{ticker}/options/contract` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or MIC:TICKER for a TSX or TSXV listing (e.g. XTSE:RY). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>symbol [query, string]: OCC option symbol (e.g. O:AAPL260724C00110000). |
| `security_contract_bars` | `/v1/securities/{ticker}/options/contract/bars` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or XNSE:SYMBOL for an NSE share or index (e.g. XNSE:RELIANCE, XNSE:NIFTY). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>symbol [query, string]: OCC option symbol (e.g. O:AAPL270617C00350000). An NSE contract is O:, NSE's symbol, the expiry as yyMMdd, C or P, then the strike times 1000 in at least eight digits (e.g. O:NIFTY261117P25100000); percent-encode an ampersand in it (M&M is M%26M).<br>timeframe [query, string]: Bar size: day, hour or minute (default: day).<br>startDate [query, string]: First date, YYYY-MM-DD (default depends on timeframe).<br>endDate [query, string]: Last date, YYYY-MM-DD (default: today).<br>limit [query, integer]: Maximum bars to return, newest first (default: 250, max: 500). |
| `security_contract_trades` | `/v1/securities/{ticker}/options/contract/trades` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>symbol [query, string]: OCC option symbol (e.g. O:AAPL270617C00350000).<br>startDate [query, string]: First date, YYYY-MM-DD (default: 4 days before end).<br>endDate [query, string]: Last date, YYYY-MM-DD (default: today).<br>endTime [query, string]: Last time to include, RFC 3339; replaces endDate. To continue a truncated read, pass the oldest row's time, which can come back again.<br>limit [query, integer]: Maximum trades to return, newest first (default: 250, max: 500). |
| `security_expirations` | `/v1/securities/{ticker}/options/expirations` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or MIC:TICKER for a TSX or TSXV listing (e.g. XTSE:RY). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>expired [query, boolean]: List past expirations instead of upcoming ones (US listings only).<br>startDate [query, string]: With expired=true: first expiration date, YYYY-MM-DD (default: 90 days before end).<br>endDate [query, string]: With expired=true: last expiration date, YYYY-MM-DD (default: yesterday). |
| `security_session` | `/v1/securities/{ticker}/options/session` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>date [query, string]: The session, YYYY-MM-DD.<br>expiration [query, string]: The expiration, YYYY-MM-DD.<br>minStrike [query, number]: Only include strikes at or above this price.<br>maxStrike [query, number]: Only include strikes at or below this price.<br>type [query, string]: Contract type filter: call or put (default: both).<br>limit [query, integer]: Maximum contracts to return, taken nearest the session's stock close (default: 250, max: 500). |
| `security_strategy` | `/v1/securities/{ticker}/options/strategy` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>leg [query, array]: One leg as OCC symbol, side and optional quantity (default 1, max 100), e.g. O:AAPL261120C00270000,long,1. Repeat for up to four legs. |
| `security_summary` | `/v1/securities/{ticker}/options/summary` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>expiration [query, string]: Expiration date, YYYY-MM-DD (default: nearest upcoming). |
| `security_term_structure` | `/v1/securities/{ticker}/options/term-structure` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>maxExpirations [query, integer]: Expirations to compare (default: 8, max: 12). |
| `security_volatility` | `/v1/securities/{ticker}/options/volatility` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>startDate [query, string]: First session, YYYY-MM-DD (default: a year before endDate).<br>endDate [query, string]: Last session, YYYY-MM-DD (default: today).<br>limit [query, integer]: Maximum sessions to return, newest first (default: 250, max: 500). |

## `ownership`

Use this family as `equibles_ownership`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `security_ownership_signals` | `/v1/securities/{ticker}/ownership-signals` | ticker [path, string, required]: Listed security ticker (e.g. NVDA).<br>holders [query, integer]: Highest-conviction holders to list (default 10, max 50).<br>peers [query, integer]: Holder-overlap peers to list (default 10, max 20). |
| `security_ownership_summary` | `/v1/securities/{ticker}/ownership-summary` | ticker [path, string, required]: Listed security ticker (e.g. NVDA or VOO).<br>view [query, string]: default, or ultimate to add the 15 largest ultimate parents. |

## `market_data`

Use this family as `equibles_market_data`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `security_prices` | `/v1/securities/{ticker}/prices` | ticker [path, string, required]: Exact listed ticker (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or MIC:TICKER for a listing on another exchange (e.g. XETR:SIE or XLON:BP). Each listing has an independent price series; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 1 year ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>interval [query, string]: daily (default), weekly or monthly. Weekly (ISO week) and monthly bars roll up the daily bars: first open, highest high, lowest low, last close and adjusted close, summed volume, dated by their last session, with periodStart and partial set. |
| `security_quote` | `/v1/securities/{ticker}/quote` | ticker [path, string, required]: Exact listed ticker (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or MIC:TICKER for a Canadian, Euronext or NSE listing (e.g. XTSE:RY, XPAR:AIR or XNSE:RELIANCE). A missing listing is never replaced by its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B. |

## `positioning`

Use this family as `equibles_positioning`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `security_short_interest` | `/v1/securities/{ticker}/short-interest` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO). Class shares use a dash (BRK-B); the dot form (BRK.B) is also accepted.<br>startDate [query, string]: Start settlement date (yyyy-MM-dd, defaults to 1 year ago).<br>endDate [query, string]: End settlement date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `security_short_volume` | `/v1/securities/{ticker}/short-volume` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO). Class shares use a dash (BRK-B); the dot form (BRK.B) is also accepted.<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 3 months ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `market_data`

Use this family as `equibles_market_data`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `security_technicals_atr` | `/v1/securities/{ticker}/technicals/atr` | ticker [path, string, required]: Exact listed ticker (e.g. GOOG or GOOGL), or MIC:TICKER for a listing on another exchange (e.g. XETR:SIE), computed in its trading currency in major units. Each listing uses its own bars; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 6 months ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>period [query, integer]: Lookback period (default 14, minimum 2).<br>limit [query, integer]: Most recent points to return (default 60, max 500). |
| `security_technicals_bollinger_bands` | `/v1/securities/{ticker}/technicals/bollinger-bands` | ticker [path, string, required]: Exact listed ticker (e.g. GOOG or GOOGL), or MIC:TICKER for a listing on another exchange (e.g. XETR:SIE), computed in its trading currency in major units. Each listing uses its own bars; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 6 months ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>period [query, integer]: Moving-average period (default 20, minimum 2).<br>stdDev [query, number]: Standard-deviation multiple for the bands (default 2, must be greater than 0).<br>limit [query, integer]: Most recent points to return (default 60, max 500). |
| `security_technicals_obv` | `/v1/securities/{ticker}/technicals/obv` | ticker [path, string, required]: Exact listed ticker (e.g. GOOG or GOOGL), or MIC:TICKER for a listing on another exchange (e.g. XETR:SIE), computed in its trading currency in major units. Each listing uses its own bars; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 6 months ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Most recent points to return (default 60, max 500). |
| `security_technicals_stochastic` | `/v1/securities/{ticker}/technicals/stochastic` | ticker [path, string, required]: Exact listed ticker (e.g. GOOG or GOOGL), or MIC:TICKER for a listing on another exchange (e.g. XETR:SIE), computed in its trading currency in major units. Each listing uses its own bars; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 6 months ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>kPeriod [query, integer]: %K lookback period (default 14, minimum 2).<br>dPeriod [query, integer]: %D smoothing period (default 3, minimum 1).<br>limit [query, integer]: Most recent points to return (default 60, max 500). |

## `positioning`

Use this family as `equibles_positioning`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `short_interest_snapshot` | `/v1/short-interest/snapshot` | minDaysToCover [query, number]: Minimum days to cover filter (default 0 = no filter).<br>minAverageDailyVolume [query, integer]: Minimum average daily share volume ; set a floor (e.g. 100000) to drop illiquid names whose days-to-cover is inflated by a tiny volume denominator (default 0 = no floor).<br>minAvgDailyVolume [query, integer]: Alias for minAverageDailyVolume matching the MCP tool's parameter name; minAverageDailyVolume wins when both are set.<br>sortBy [query, string]: Sort key: daysToCover (default; FINRA-capped 999.99 sentinel rows ranked last), shortPosition, or change (largest increase in short position first).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `short_squeeze_scores` | `/v1/short-squeeze-scores` | minMarketCap [query, number]: Minimum market capitalization in US dollars (default 0 = no floor). Stocks with an unknown market cap are excluded when set.<br>minDollarVolume [query, number]: Minimum average daily dollar volume in US dollars, approximated as the FINRA average daily share volume times the market-cap-implied share price (default 0 = no floor). Stocks with unknown volume or market cap are excluded when set.<br>ticker [query, string]: Optional stock ticker (e.g. GME): returns that one stock's score row plus its rank within the scored universe instead of the board; 404 when the stock is not in the scored universe. The liquidity floors do not apply to a single-ticker lookup.<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `short_volume_largest` | `/v1/short-volume/largest` | date [query, string]: Trading day (yyyy-MM-dd, defaults to the latest available day).<br>minShortVolume [query, integer]: Minimum short volume filter (default 0 = no filter).<br>sortBy [query, string]: Sort key: shortVolume (default) or shortPercent ; with shortPercent set a minTotalVolume floor, otherwise illiquid names dominate.<br>minTotalVolume [query, integer]: Minimum total FINRA-reported volume filter, in shares (default 0 = no floor).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `international`

Use this family as `equibles_international`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `canadian_fund_holdings` | `/v1/stocks/{exchange}/{ticker}/canadian-fund-holdings` | exchange [path, string, required]<br>ticker [path, string, required]<br>limit [query, integer]<br>offset [query, integer] |
| `director_transactions` | `/v1/stocks/{exchange}/{ticker}/director-transactions` | exchange [path, string, required]<br>ticker [path, string, required]<br>limit [query, integer] |
| `european_fund_holdings` | `/v1/stocks/{exchange}/{ticker}/european-fund-holdings` | exchange [path, string, required]<br>ticker [path, string, required]<br>limit [query, integer]<br>offset [query, integer]<br>periodEnd [query, string] |
| `filings` | `/v1/stocks/{exchange}/{ticker}/filings` | exchange [path, string, required]<br>ticker [path, string, required]<br>q [query, string]<br>startDate [query, string]<br>endDate [query, string]<br>limit [query, integer]<br>offset [query, integer] |
| `financial_reports` | `/v1/stocks/{exchange}/{ticker}/financial-reports` | exchange [path, string, required]<br>ticker [path, string, required]<br>limit [query, integer] |
| `financial_reports_native` | `/v1/stocks/{exchange}/{ticker}/financial-reports/native` | exchange [path, string, required]<br>ticker [path, string, required]<br>offset [query, integer]<br>limit [query, integer] |
| `native_financial_report` | `/v1/stocks/{exchange}/{ticker}/financial-reports/native/{reportId}` | exchange [path, string, required]<br>ticker [path, string, required]<br>reportId [path, string, required]<br>offset [query, integer]<br>limit [query, integer] |
| `government_contracts` | `/v1/stocks/{exchange}/{ticker}/government-contracts` | exchange [path, string, required]: The listing's market identifier code, e.g. XTSE.<br>ticker [path, string, required]: The listing's ticker on that exchange, e.g. WJX.<br>startDate [query, string]: Start action date (yyyy-MM-dd, defaults to 1 year ago).<br>endDate [query, string]: End action date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>agency [query, string]: Optional case-insensitive substring filter on awarding agency.<br>sortBy [query, string]: Sort by amount (default) or date.<br>country [query, string]: Awarding government: US or CA; defaults to the listing's country (CA for a Canadian listing, else US). |
| `insider_transactions` | `/v1/stocks/{exchange}/{ticker}/insider-transactions` | exchange [path, string, required]<br>ticker [path, string, required]<br>limit [query, integer]<br>offset [query, integer] |
| `major_holdings` | `/v1/stocks/{exchange}/{ticker}/major-holdings` | exchange [path, string, required]<br>ticker [path, string, required]<br>limit [query, integer]<br>offset [query, integer] |
| `public_short_positions` | `/v1/stocks/{exchange}/{ticker}/public-short-positions` | exchange [path, string, required]<br>ticker [path, string, required]<br>limit [query, integer] |
| `short_disclosures` | `/v1/stocks/{exchange}/{ticker}/short-disclosures` | exchange [path, string, required]<br>ticker [path, string, required]<br>limit [query, integer]<br>source [query, string] |
| `short_positions` | `/v1/stocks/{exchange}/{ticker}/short-positions` | exchange [path, string, required]<br>ticker [path, string, required]<br>limit [query, integer]<br>offset [query, integer] |

## `company`

Use this family as `equibles_company`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `profile` | `/v1/stocks/{ticker}` | ticker [path, string, required]: Exact listed ticker (e.g. AAPL or BRK-B), or MIC:TICKER for a listing on another exchange (e.g. XETR:SIE). |
| `analyst_estimates` | `/v1/stocks/{ticker}/analyst-estimates` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XAMS:ASML).<br>metric [query, string]: Exact source metric label to keep (up to 512 characters).<br>period [query, string]: Exact source period label to keep (up to 256 characters).<br>dimensions [query, string]: Exact source dimension labels to keep (up to 1024 characters).<br>snapshotId [query, string]: A verified snapshot ID returned in snapshots.<br>asOf [query, string]: ISO-8601 cutoff; the snapshot must have been verified by that instant.<br>snapshotOffset [query, integer]: Snapshot-history offset (default 0, 0-100000); pages hold up to 10 snapshots.<br>limit [query, integer]: Observations to return (default 100, 1-100).<br>offset [query, integer]: Zero-based observation offset (default 0, 0-100000). |
| `atm_programs` | `/v1/stocks/{ticker}/atm-programs` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL). |

## `market_data`

Use this family as `equibles_market_data`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `bars` | `/v1/stocks/{ticker}/bars` | ticker [path, string, required]: Exact listed US ticker (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or `MIC:TICKER` for a Euronext, Canadian or NSE listing (e.g. XPAR:AIR, XTSE:RY or XNSE:RELIANCE). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>interval [query, string]: Bar size: a whole number of minutes from 1min (default) to 240min, such as 5min or 7min, or of hours from 1hour to 4hour. The answer echoes whole hours in hours (60min as 1hour).<br>startDate [query, string]: First trading date on the exchange's own clock (New York for a US listing), YYYY-MM-DD (default: 7 days before the end, 30 for hourly intervals).<br>endDate [query, string]: Last trading date on the exchange's own clock, YYYY-MM-DD (default: today).<br>endTime [query, string]: Return only bars that start before this RFC 3339 time; replaces endDate. Pass the oldest bar's time to continue a truncated read, and keep startDate: without it the window is counted back again from this time.<br>session [query, string]: regular (default) or extended.<br>adjustment [query, string]: split (default) or raw.<br>limit [query, integer]: Maximum bars to return, newest first (default: 250, max: 500; with format=csv default and max 50,000, at one call for each 500 bars returned).<br>format [query, string]: Omit or json for the JSON envelope, csv for a flat file with one row a bar under the JSON field names. A file costs one call for each 500 bars it returns, stated on X-Bars-Calls; one that needs more calls than the day has left answers 429 and names the limit that fits. The envelope's fields ride on the X-Bars-Returned, X-Bars-Truncated, X-Bars-Delayed, X-Bars-Covered-From and X-Bars-Adjusted-From response headers, plus X-Bars-Currency and X-Bars-Stored-Through for a listing outside the US, X-Bars-Incomplete-Sessions and X-Bars-Unstored-Dates for a Euronext listing and X-Bars-Notice for a Canadian one. |

## `ownership`

Use this family as `equibles_ownership`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `beneficial_ownership` | `/v1/stocks/{ticker}/beneficial-ownership` | ticker [path, string, required]: Listed security ticker (e.g. NVDA or BRK-B).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `company`

Use this family as `equibles_company`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `buyback_programs` | `/v1/stocks/{ticker}/buyback-programs` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XTSE:WDO). |

## `investor_events`

Use this family as `equibles_investor_events`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `call_insights` | `/v1/stocks/{ticker}/call-insights` | ticker [path, string, required]: Company ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XLIS:NOS).<br>limit [query, integer]: Maximum scored calls to return (default 2, max 8; zero or negative values are rejected, values above the maximum are clamped).<br>fiscalYear [query, integer]: Optional fiscal year, in the company's own fiscal calendar, to fetch a specific period's insights (default: newest first).<br>fiscalQuarter [query, integer]: Optional fiscal quarter, 1-4, to fetch a specific period's insights (default: newest first). |
| `call_themes` | `/v1/stocks/{ticker}/call-themes/history` | ticker [path, string, required]: Company ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XLIS:NOS).<br>calls [query, integer]: Most recent scored fiscal quarters to compare (default 8, max 12; zero or negative values are rejected, values above the maximum are clamped). |

## `market_data`

Use this family as `equibles_market_data`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `correlated` | `/v1/stocks/{ticker}/correlated` | ticker [path, string, required]: Exact listed ticker (e.g. GOOG or GOOGL). The requested listing's own daily series is the correlation subject; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>scope [query, string]: Candidate universe: Industry (default), Sector, or Market (~1,500 largest listed names).<br>days [query, integer]: Trailing calendar window in days for the return series (default 180, clamped to 30-730).<br>direction [query, string]: Positive (default) for the strongest co-movers, Negative for the strongest inverse movers.<br>limit [query, integer]: Maximum number of stocks to return (default 10, max 50). |

## `company`

Use this family as `equibles_company`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `customer_concentration` | `/v1/stocks/{ticker}/customer-concentration` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL). |
| `debt_instrument` | `/v1/stocks/{ticker}/debt-instruments/{instrumentId}` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XAMS:ASML).<br>instrumentId [path, string, required]: Debt instrument identifier returned by the debt-profile endpoint.<br>historyLimit [query, integer]: Maximum filing-history rows to return (default 25, max 100).<br>historyOffset [query, integer]: Zero-based filing-history offset.<br>covenantLimit [query, integer]: Maximum covenant rows to return (default 25, max 100).<br>covenantOffset [query, integer]: Zero-based covenant offset.<br>documentLimit [query, integer]: Maximum governing-document rows to return (default 25, max 100).<br>documentOffset [query, integer]: Zero-based governing-document offset. |
| `debt_profile` | `/v1/stocks/{ticker}/debt-profile` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XAMS:ASML).<br>instrumentLimit [query, integer]: Maximum instruments to return (default 25, max 100).<br>instrumentOffset [query, integer]: Zero-based instrument offset.<br>reportedTotalLimit [query, integer]: Maximum issuer-reported totals to return (default 25, max 100).<br>reportedTotalOffset [query, integer]: Zero-based issuer-reported-total offset. |

## `market_data`

Use this family as `equibles_market_data`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `dividends` | `/v1/stocks/{ticker}/dividends` | ticker [path, string, required]: Listed stock or ETF ticker (e.g. AAPL, BRK.A, SCHD), or MIC:TICKER for a listing on another exchange (e.g. XETR:SIE).<br>startDate [query, string]: Earliest ex-dividend date (yyyy-MM-dd).<br>endDate [query, string]: Latest ex-dividend date (yyyy-MM-dd).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `investor_events`

Use this family as `equibles_investor_events`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `earnings_briefs` | `/v1/stocks/{ticker}/earnings-briefs` | ticker [path, string, required]: Company ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XLIS:NOS).<br>limit [query, integer]: Maximum quarterly briefs to return (default 2, max 8; zero or negative values are rejected, values above the maximum are clamped).<br>fiscalYear [query, integer]: Optional fiscal year, in the company's own fiscal calendar, to fetch a specific period's brief (default: newest first).<br>fiscalQuarter [query, integer]: Optional fiscal quarter, 1-4, to fetch a specific period's brief (default: newest first). |
| `earnings_call_phrase_trend` | `/v1/stocks/{ticker}/earnings-calls/phrase-trend` | ticker [path, string, required]: Company ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XLIS:NOS).<br>phrase [query, string, required]: Required. Word or phrase to count, 2-80 characters after trimming (e.g. tariffs, sovereign AI); a space matches any whitespace.<br>calls [query, integer]: Most recent earnings calls to read (default 8, max 12; zero or negative values are rejected, values above the maximum are clamped). |
| `earnings_call` | `/v1/stocks/{ticker}/earnings-calls/{fiscalYear}/{fiscalQuarter}` | ticker [path, string, required]: Company ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XLIS:NOS).<br>fiscalYear [path, integer, required]: Fiscal year the quarter belongs to (e.g. 2025).<br>fiscalQuarter [path, integer, required]: Fiscal quarter, 1-4. |
| `earnings_call_live_transcript` | `/v1/stocks/{ticker}/earnings-calls/{fiscalYear}/{fiscalQuarter}/live-transcript` | ticker [path, string, required]: Company ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XLIS:NOS).<br>fiscalYear [path, integer, required]: Fiscal year the quarter belongs to (e.g. 2025).<br>fiscalQuarter [path, integer, required]: Fiscal quarter, 1-4.<br>after [query, integer]: The highest line seq already received (default -1, the whole text so far); only later lines are returned.<br>run [query, string]: The run value of the previous response; a different run means the recording restarted and the full text is returned with reset=true. |
| `earnings_call_questions` | `/v1/stocks/{ticker}/earnings-calls/{fiscalYear}/{fiscalQuarter}/questions` | ticker [path, string, required]: Company ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XLIS:NOS).<br>fiscalYear [path, integer, required]: Fiscal year the quarter belongs to (e.g. 2025).<br>fiscalQuarter [path, integer, required]: Fiscal quarter, 1-4. |
| `earnings_call_speakers` | `/v1/stocks/{ticker}/earnings-calls/{fiscalYear}/{fiscalQuarter}/speakers` | ticker [path, string, required]: Company ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XLIS:NOS).<br>fiscalYear [path, integer, required]: Fiscal year the quarter belongs to (e.g. 2025).<br>fiscalQuarter [path, integer, required]: Fiscal quarter, 1-4.<br>limit [query, integer]: Maximum speaker turns to return (default 50, max 200; zero or negative values are rejected, values above the maximum are clamped).<br>offset [query, integer]: Speaker turns to skip before the first returned one (default 0) ; pages past the per-request cap. |

## `company`

Use this family as `equibles_company`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `executive_changes` | `/v1/stocks/{ticker}/executive-changes` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL).<br>action [query, string]: Optional action filter: Appointed, Resigned, Terminated, or Retired.<br>startDate [query, string]: Optional oldest filed date (yyyy-MM-dd).<br>endDate [query, string]: Optional newest filed date (yyyy-MM-dd).<br>limit [query, integer]: Maximum changes to return (default 25, max 100; zero or negative values are rejected, values above the maximum are clamped).<br>offset [query, integer]: Changes to skip before the first returned one (default 0) ; pages past the per-request cap. |
| `executive_compensation` | `/v1/stocks/{ticker}/executive-compensation` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL).<br>years [query, integer]: Maximum fiscal years to return, newest first (default all on file; values below 1 are a 400). |
| `exempt_offerings` | `/v1/stocks/{ticker}/exempt-offerings` | ticker [path, string, required]: Company ticker symbol (e.g. AAPL).<br>startDate [query, string]: Earliest filing date (yyyy-MM-dd).<br>endDate [query, string]: Latest filing date (yyyy-MM-dd).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `positioning`

Use this family as `equibles_positioning`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `fails_to_deliver` | `/v1/stocks/{ticker}/fails-to-deliver` | ticker [path, string, required]: Exact stock or ETF ticker symbol (e.g. AAPL or SPY).<br>startDate [query, string]: Start settlement date (yyyy-MM-dd, defaults to 3 months ago).<br>endDate [query, string]: End settlement date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `filings`

Use this family as `equibles_filings`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `company_filings` | `/v1/stocks/{ticker}/filings` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL), or MIC:TICKER for a listing outside the US (e.g. XPAR:AIR).<br>documentType [query, string]: Document type filter, by value (e.g. TenK) or form label (e.g. 10-K). Also accepts EarningsCallTranscript for call transcripts, IrNews for investor-relations news and EsefAnnualReport for a European annual report and EsefReport for another European ESEF report; an unknown value returns a 400 listing every valid value.<br>startDate [query, string]: Earliest filing date (yyyy-MM-dd).<br>endDate [query, string]: Latest filing date (yyyy-MM-dd).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>itemNumber [query, string]: Exact SEC current-report item number (e.g. 2.02 or 5.02). |
| `company_filing_search` | `/v1/stocks/{ticker}/filings/search` | ticker [path, string, required]: Company ticker symbol (e.g. AAPL).<br>query [query, string, required]: Search query ; plain keywords or a short natural-language phrase (required). Concise, filing-phrased terms (e.g. 'Data Center revenue') still rank best.<br>documentType [query, string]: Document type filter ; one value or a comma-separated list (e.g. TenK,TenQ), by value or form label (e.g. 10-K).<br>startDate [query, string]: Earliest filing date (yyyy-MM-dd).<br>endDate [query, string]: Latest filing date (yyyy-MM-dd).<br>limit [query, integer]: Maximum excerpts to return (default 5, max 500).<br>match [query, string]: How the query matches: ranked (default) for relevance-ranked retrieval that broadens to any of the words when results are sparse, or phrase for only the excerpts containing the query's words consecutively and in order (case and punctuation ignored). |

## `company`

Use this family as `equibles_company`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `financial_facts` | `/v1/stocks/{ticker}/financial-facts/{concept}` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XAMS:ASML).<br>concept [path, string, required]: A supported concept alias such as revenue, net-income, eps-diluted, total-assets, or operating-cash-flow. |
| `financial_statement` | `/v1/stocks/{ticker}/financial-statements/{statement}` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XAMS:ASML).<br>statement [path, string, required]: income, balance, or cashflow. The aliases is, pnl, bs, and cf also work.<br>year [query, integer]: Optional fiscal year. Omit with period to use the latest available period.<br>period [query, string]: Optional fiscal period: FY or Q1 through Q4. |

## `ownership`

Use this family as `equibles_ownership`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `fund_owners` | `/v1/stocks/{ticker}/fund-owners` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO), or MIC:TICKER for a listing on another exchange (e.g. XAMS:ASML).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>registrantOrSeries [query, string]: Optional case-insensitive substring filter on registrant or fund-series name. |

## `company`

Use this family as `equibles_company`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `going_concern` | `/v1/stocks/{ticker}/going-concern` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL). |

## `public_policy`

Use this family as `equibles_public_policy`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `company_government_contracts` | `/v1/stocks/{ticker}/government-contracts` | ticker [path, string, required]: Stock ticker symbol (e.g. LMT, RTX, BA). Class shares use a dash (BRK-B); the dot form (BRK.B) is also accepted.<br>startDate [query, string]: Start action date (yyyy-MM-dd, defaults to 1 year ago).<br>endDate [query, string]: End action date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>agency [query, string]: Optional case-insensitive substring filter on awarding agency.<br>sortBy [query, string]: Sort by amount (default) or date.<br>country [query, string]: Awarding government: US (default) or CA. |

## `company`

Use this family as `equibles_company`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `guidance` | `/v1/stocks/{ticker}/guidance` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XAMS:ASML).<br>maxReleases [query, integer]: Optional: only the newest N releases (1 or more; values above 200 read as 200). Omitted, every release on file is returned.<br>fiscalYear [query, integer]: Optional: only guidance for a period in that fiscal year of the company's own calendar, from every release that gave it. |

## `ownership`

Use this family as `equibles_ownership`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `holder_mix` | `/v1/stocks/{ticker}/holder-mix` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO).<br>dimension [query, string]: How to split the holders: type (default), style, turnover, horizon, aum (13F book size), client (client base), pf (private funds), country (filer location) or fundtype (registered funds by N-CEN fund type).<br>periods [query, integer]: Quarters to return, newest last (default 4, max 12); each is compared with the quarter before. |
| `holder_targets` | `/v1/stocks/{ticker}/holder-targets` | ticker [path, string, required]: Listed security ticker (e.g. NVDA).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>sort [query, string]: peerValue (default) or peerWeight. |
| `holders` | `/v1/stocks/{ticker}/holders` | ticker [path, string, required]: Listed security ticker (e.g. NVDA or VOO).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>source [query, string]: Rows to list: all (default), 13f, 13dg (13D and 13G), 13d, 13g, insider, fund or nonus. A single source lists its rows flat, stale ones flagged.<br>view [query, string]: default (one row per holder, others nested), all (every row flat, stale included) or ultimate (summed holders grouped by ultimate parent; takes no source or holderTypes filter).<br>holderTypes [query, string]: Comma-separated holder type tokens to keep: adv, era, ia, bank, ins, bd, fund, plan, nonus, hc, unk (insiders and holders without a deciding record read unk). |
| `insider_ownership` | `/v1/stocks/{ticker}/insider-ownership` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `insider_transactions` | `/v1/stocks/{ticker}/insider-transactions` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>startDate [query, string]: Only include transactions on or after this date (yyyy-MM-dd).<br>endDate [query, string]: Only include transactions on or before this date (yyyy-MM-dd).<br>transactionType [query, string]: Optional transaction type: Buy, Sell, Award, Conversion, Exercise, TaxPayment, Expiration, Gift, Inheritance, Discretionary, or Other. Purchase and Sale are accepted aliases.<br>insiderName [query, string]: Only include transactions whose SEC-filed insider name contains every supplied word, case-insensitively. |
| `institutional_activity` | `/v1/stocks/{ticker}/institutional-activity` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO).<br>reportDate [query, string]: 13F report date (yyyy-MM-dd, defaults to the latest available). Must be one of the stock's 13F report dates ; any other date returns 400 listing the available dates.<br>limit [query, integer]: Maximum buyers and sellers to return per side (default 10, max 500). |
| `institutional_holders` | `/v1/stocks/{ticker}/institutional-holders` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO).<br>reportDate [query, string]: 13F report date (yyyy-MM-dd, defaults to the latest available). Must be one of the stock's 13F report dates ; any other date returns 400 listing the available dates.<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>holderTypes [query, string]: Comma-separated holder type tokens to keep: adv, era, ia, bank, ins, bd, fund, plan, nonus, hc, unk (unk also matches a holder not yet classified). Totals and percentages stay over every institution.<br>styles [query, string]: Comma-separated style band tokens to keep: idx (index-like), sys (systematic-like), conc (concentrated), divact (diversified active), unk (book too small or unvalued to band). Bands come from the newest measured quarter on or before the report date; a holder not measured that quarter matches no style. Totals and percentages stay over every institution. |
| `institutional_ownership` | `/v1/stocks/{ticker}/institutional-ownership` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO).<br>periods [query, integer]: Maximum number of quarterly periods to return (default 8, max 500). |

## `investor_events`

Use this family as `equibles_investor_events`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `investor_events` | `/v1/stocks/{ticker}/investor-events` | ticker [path, string, required]: Company ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XLIS:NOS).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>eventType [query, string]: Optional event type: EarningsCall, CapitalMarketsDay, InvestorUpdate, AGM, Conference, FiresideChat, or MAndA.<br>includeUncaptured [query, boolean]: Also return events hidden because none of their materials could be captured and still on the company's own IR calendar (default false); such rows carry isTombstoned=true. |
| `ir_events` | `/v1/stocks/{ticker}/ir-events` | ticker [path, string, required]: Company ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XLIS:NOS).<br>limit [query, integer]: Maximum events to return (default 20, max 500; zero or negative values are rejected, values above the maximum are clamped).<br>eventType [query, string]: Optional event type: EarningsCall, Conference, Presentation, ShareholderMeeting, or Webcast. |
| `ir_news` | `/v1/stocks/{ticker}/ir-news` | ticker [path, string, required]: Company ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XLIS:NOS).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>since [query, string]: Only include releases published on or after this date (yyyy-MM-dd). |

## `company`

Use this family as `equibles_company`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `kpis` | `/v1/stocks/{ticker}/kpis` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL).<br>metric [query, string]: Optional metric name to return on its own (case-insensitive; matches the company's own labels). Omit for every metric. An ambiguous name that matches several metrics is a 400 listing the candidates; a name matching nothing is a 404 listing everything on file. |
| `non_gaap_bridge` | `/v1/stocks/{ticker}/non-gaap-bridge` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `positioning`

Use this family as `equibles_positioning`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `off_exchange_volume` | `/v1/stocks/{ticker}/off-exchange-volume` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO). Class shares use a dash (BRK-B); the dot form (BRK.B) is also accepted.<br>startDate [query, string]: Start week (yyyy-MM-dd, defaults to 6 months ago).<br>endDate [query, string]: End week (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `options`

Use this family as `equibles_options`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `chain` | `/v1/stocks/{ticker}/options/chain` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or MIC:TICKER for a TSX or TSXV listing (e.g. XTSE:RY). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>expiration [query, string]: Expiration date in YYYY-MM-DD format (default: nearest upcoming).<br>minStrike [query, number]: Only include strikes at or above this price.<br>maxStrike [query, number]: Only include strikes at or below this price.<br>type [query, string]: Contract type filter: call or put (default: both).<br>limit [query, integer]: Maximum contracts to return, taken nearest the money (default: 250, max: 500). |
| `contract` | `/v1/stocks/{ticker}/options/contract` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or MIC:TICKER for a TSX or TSXV listing (e.g. XTSE:RY). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>symbol [query, string]: OCC option symbol (e.g. O:AAPL260724C00110000). |
| `contract_bars` | `/v1/stocks/{ticker}/options/contract/bars` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or XNSE:SYMBOL for an NSE share or index (e.g. XNSE:RELIANCE, XNSE:NIFTY). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>symbol [query, string]: OCC option symbol (e.g. O:AAPL270617C00350000). An NSE contract is O:, NSE's symbol, the expiry as yyMMdd, C or P, then the strike times 1000 in at least eight digits (e.g. O:NIFTY261117P25100000); percent-encode an ampersand in it (M&M is M%26M).<br>timeframe [query, string]: Bar size: day, hour or minute (default: day).<br>startDate [query, string]: First date, YYYY-MM-DD (default depends on timeframe).<br>endDate [query, string]: Last date, YYYY-MM-DD (default: today).<br>limit [query, integer]: Maximum bars to return, newest first (default: 250, max: 500). |
| `contract_trades` | `/v1/stocks/{ticker}/options/contract/trades` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>symbol [query, string]: OCC option symbol (e.g. O:AAPL270617C00350000).<br>startDate [query, string]: First date, YYYY-MM-DD (default: 4 days before end).<br>endDate [query, string]: Last date, YYYY-MM-DD (default: today).<br>endTime [query, string]: Last time to include, RFC 3339; replaces endDate. To continue a truncated read, pass the oldest row's time, which can come back again.<br>limit [query, integer]: Maximum trades to return, newest first (default: 250, max: 500). |
| `expirations` | `/v1/stocks/{ticker}/options/expirations` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or MIC:TICKER for a TSX or TSXV listing (e.g. XTSE:RY). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>expired [query, boolean]: List past expirations instead of upcoming ones (US listings only).<br>startDate [query, string]: With expired=true: first expiration date, YYYY-MM-DD (default: 90 days before end).<br>endDate [query, string]: With expired=true: last expiration date, YYYY-MM-DD (default: yesterday). |
| `session` | `/v1/stocks/{ticker}/options/session` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>date [query, string]: The session, YYYY-MM-DD.<br>expiration [query, string]: The expiration, YYYY-MM-DD.<br>minStrike [query, number]: Only include strikes at or above this price.<br>maxStrike [query, number]: Only include strikes at or below this price.<br>type [query, string]: Contract type filter: call or put (default: both).<br>limit [query, integer]: Maximum contracts to return, taken nearest the session's stock close (default: 250, max: 500). |
| `strategy` | `/v1/stocks/{ticker}/options/strategy` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>leg [query, array]: One leg as OCC symbol, side and optional quantity (default 1, max 100), e.g. O:AAPL261120C00270000,long,1. Repeat for up to four legs. |
| `summary` | `/v1/stocks/{ticker}/options/summary` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>expiration [query, string]: Expiration date, YYYY-MM-DD (default: nearest upcoming). |
| `term_structure` | `/v1/stocks/{ticker}/options/term-structure` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>maxExpirations [query, integer]: Expirations to compare (default: 8, max: 12). |
| `volatility` | `/v1/stocks/{ticker}/options/volatility` | ticker [path, string, required]: Exact listed underlying (e.g. GOOG, GOOGL, BRK-A, or BRK-B). A listing never falls through to its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>startDate [query, string]: First session, YYYY-MM-DD (default: a year before endDate).<br>endDate [query, string]: Last session, YYYY-MM-DD (default: today).<br>limit [query, integer]: Maximum sessions to return, newest first (default: 250, max: 500). |

## `ownership`

Use this family as `equibles_ownership`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `ownership_signals` | `/v1/stocks/{ticker}/ownership-signals` | ticker [path, string, required]: Listed security ticker (e.g. NVDA).<br>holders [query, integer]: Highest-conviction holders to list (default 10, max 50).<br>peers [query, integer]: Holder-overlap peers to list (default 10, max 20). |
| `ownership_summary` | `/v1/stocks/{ticker}/ownership-summary` | ticker [path, string, required]: Listed security ticker (e.g. NVDA or VOO).<br>view [query, string]: default, or ultimate to add the 15 largest ultimate parents. |

## `market_data`

Use this family as `equibles_market_data`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `prices` | `/v1/stocks/{ticker}/prices` | ticker [path, string, required]: Exact listed ticker (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or MIC:TICKER for a listing on another exchange (e.g. XETR:SIE or XLON:BP). Each listing has an independent price series; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 1 year ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>interval [query, string]: daily (default), weekly or monthly. Weekly (ISO week) and monthly bars roll up the daily bars: first open, highest high, lowest low, last close and adjusted close, summed volume, dated by their last session, with periodStart and partial set. |

## `ownership`

Use this family as `equibles_ownership`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `proposed_sales` | `/v1/stocks/{ticker}/proposed-sales` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0).<br>startDate [query, string]: Only include notices filed on or after this date (yyyy-MM-dd).<br>endDate [query, string]: Only include notices filed on or before this date (yyyy-MM-dd). |

## `market_data`

Use this family as `equibles_market_data`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `quote` | `/v1/stocks/{ticker}/quote` | ticker [path, string, required]: Exact listed ticker (e.g. GOOG, GOOGL, BRK-A, or BRK-B), or MIC:TICKER for a Canadian, Euronext or NSE listing (e.g. XTSE:RY, XPAR:AIR or XNSE:RELIANCE). A missing listing is never replaced by its sibling; dot class-share spelling such as BRK.B is accepted as BRK-B. |

## `company`

Use this family as `equibles_company`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `revenue_breakdown` | `/v1/stocks/{ticker}/revenue-breakdown` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL), or MIC:TICKER for a company listed on another exchange (e.g. XAMS:ASML). |

## `ownership`

Use this family as `equibles_ownership`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `shareholder_votes` | `/v1/stocks/{ticker}/shareholder-votes` | ticker [path, string, required]: Company ticker symbol (e.g. PG).<br>limit [query, integer]: Maximum meetings to return (default 1, max 10; zero or negative values are rejected, values above the maximum are clamped). |

## `positioning`

Use this family as `equibles_positioning`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `short_interest` | `/v1/stocks/{ticker}/short-interest` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO). Class shares use a dash (BRK-B); the dot form (BRK.B) is also accepted.<br>startDate [query, string]: Start settlement date (yyyy-MM-dd, defaults to 1 year ago).<br>endDate [query, string]: End settlement date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |
| `short_interest_forecast` | `/v1/stocks/{ticker}/short-interest/forecast` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL). Class shares use a dash (BRK-B); the dot form (BRK.B) is also accepted. |
| `short_volume` | `/v1/stocks/{ticker}/short-volume` | ticker [path, string, required]: Listed security ticker (e.g. AAPL or VOO). Class shares use a dash (BRK-B); the dot form (BRK.B) is also accepted.<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 3 months ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `market_data`

Use this family as `equibles_market_data`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `splits` | `/v1/stocks/{ticker}/splits` | ticker [path, string, required]: Listed stock or ETF ticker (e.g. NVDA, BRK.B, SCHD), or MIC:TICKER for a listing on another exchange (e.g. XAMS:ASML).<br>startDate [query, string]: Earliest effective date (yyyy-MM-dd).<br>endDate [query, string]: Latest effective date (yyyy-MM-dd).<br>limit [query, integer]: Maximum rows to return (1–500; default varies per endpoint).<br>offset [query, integer]: Rows to skip before the first returned row (default 0). |

## `ownership`

Use this family as `equibles_ownership`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `supply_chain` | `/v1/stocks/{ticker}/supply-chain` | ticker [path, string, required]: Stock ticker (e.g. THO), or MIC:TICKER (e.g. XPAR:SU) for a listing outside the US.<br>side [query, string]: Only one side: customers, suppliers, competitors or partners (default: all four).<br>quantifiedOnly [query, boolean]: Only companies with a stated share (default false).<br>lens [query, string]: Order within each side: stated (largest stated share first, the default), dependsOn (largest share of this company's revenue first) or dependents (largest share of the other company's own revenue first).<br>limit [query, integer]: Maximum companies per side (default 50, max 500); in the stated order a company and the parts listed under it are kept together. |
| `supply_chain_overlap` | `/v1/stocks/{ticker}/supply-chain/overlap` | ticker [path, string, required]: Stock ticker (e.g. NVDA), or MIC:TICKER (e.g. XPAR:SU) for a listing outside the US.<br>vs [query, string]: One competitor's ticker, as the competitors list shows it (e.g. AMD).<br>limit [query, integer]: Maximum companies per list (default 50, max 500). |

## `market_data`

Use this family as `equibles_market_data`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `technicals_atr` | `/v1/stocks/{ticker}/technicals/atr` | ticker [path, string, required]: Exact listed ticker (e.g. GOOG or GOOGL), or MIC:TICKER for a listing on another exchange (e.g. XETR:SIE), computed in its trading currency in major units. Each listing uses its own bars; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 6 months ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>period [query, integer]: Lookback period (default 14, minimum 2).<br>limit [query, integer]: Most recent points to return (default 60, max 500). |
| `technicals_bollinger_bands` | `/v1/stocks/{ticker}/technicals/bollinger-bands` | ticker [path, string, required]: Exact listed ticker (e.g. GOOG or GOOGL), or MIC:TICKER for a listing on another exchange (e.g. XETR:SIE), computed in its trading currency in major units. Each listing uses its own bars; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 6 months ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>period [query, integer]: Moving-average period (default 20, minimum 2).<br>stdDev [query, number]: Standard-deviation multiple for the bands (default 2, must be greater than 0).<br>limit [query, integer]: Most recent points to return (default 60, max 500). |
| `technicals_obv` | `/v1/stocks/{ticker}/technicals/obv` | ticker [path, string, required]: Exact listed ticker (e.g. GOOG or GOOGL), or MIC:TICKER for a listing on another exchange (e.g. XETR:SIE), computed in its trading currency in major units. Each listing uses its own bars; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 6 months ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>limit [query, integer]: Most recent points to return (default 60, max 500). |
| `technicals_stochastic` | `/v1/stocks/{ticker}/technicals/stochastic` | ticker [path, string, required]: Exact listed ticker (e.g. GOOG or GOOGL), or MIC:TICKER for a listing on another exchange (e.g. XETR:SIE), computed in its trading currency in major units. Each listing uses its own bars; dot class-share spelling such as BRK.B is accepted as BRK-B.<br>startDate [query, string]: Start date (yyyy-MM-dd, defaults to 6 months ago).<br>endDate [query, string]: End date (yyyy-MM-dd, defaults to today).<br>kPeriod [query, integer]: %K lookback period (default 14, minimum 2).<br>dPeriod [query, integer]: %D smoothing period (default 3, minimum 1).<br>limit [query, integer]: Most recent points to return (default 60, max 500). |

## `company`

Use this family as `equibles_company`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `valuation_multiples` | `/v1/stocks/{ticker}/valuation-multiples` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL). |
| `valuation_multiples_history` | `/v1/stocks/{ticker}/valuation-multiples/history` | ticker [path, string, required]: Stock ticker symbol (e.g. AAPL). |

## `institutions`

Use this family as `equibles_institutions`.

| Dataset | Route | Filters (path filters required) |
| --- | --- | --- |
| `super_investors` | `/v1/super-investors` |  |

## Excluded capabilities

Account-owned portfolios, organizations, custom data and web-feed tracker routes are not exposed. Binary/CSV assets are not exposed. Institution-copy backtests and direct comparison of two institutions are not bridged from the upstream MCP surface.
