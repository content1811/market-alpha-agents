# Data Sources, Pipeline & Monitoring/Alerting Design

This section specifies the concrete free-tier data sources, the local ingestion/storage pipeline, the news/sentiment scoring path into `NewsSentimentAgent`, and the alerting/scheduling design for the local multi-agent system. Everything below assumes **$0 recurring spend**, a single machine (macOS, per current setup), and no live-execution capability anywhere in the pipeline — this layer only produces data, scores, and human-readable alerts.

---

## 1. Data Sources

All entries verified against free-tier terms as of August 2026. Treat every "no key" / scraped source as fragile (undocumented, subject to breakage) and every free-tier limit as subject to change without notice — the pipeline design in §2 assumes this instability, it doesn't assume any of these numbers are permanent.

| Source | Asset Class | Data Type | Endpoint / Library | Auth | Rate Limit (free tier) | Cost |
|---|---|---|---|---|---|---|
| **yfinance** (`pip install yfinance`, v1.6.0) | US equities | OHLCV (daily/intraday), options chains, dividends/splits, earnings dates, basic fundamentals | Python lib, wraps `query1.finance.yahoo.com` | None | Undocumented/unofficial — throttles and 429s at high frequency; needs browser `User-Agent` and occasional `curl_cffi` impersonation | Free |
| **Twelve Data** | US equities/ETF, FX, crypto | OHLCV, 100+ technical indicators | REST, `api.twelvedata.com` | Free API key | 8 calls/min, 800 calls/day | Free |
| **Tiingo** | US equities | EOD OHLCV (30+ yrs history, 49k tickers) | REST, `api.tiingo.com` | Free API key | 50 req/hr, 1,000 req/day, 500 unique symbols/mo | Free |
| **Alpha Vantage** | US equities | Fundamentals (`OVERVIEW`, statements), `EARNINGS_CALENDAR`, `NEWS_SENTIMENT` | REST, `alphavantage.co/query` | Free API key | **25 requests/day** (hard cap — reserve for fundamentals/earnings, not price bars) | Free |
| **SEC EDGAR (XBRL + submissions)** | US equities | Fundamentals from filings, filing history | REST, `data.sec.gov/api/xbrl/companyfacts/`, `/submissions/CIK##########.json` | None, but requires descriptive `User-Agent` header w/ contact email | ~10 req/sec fair-access policy | Free |
| **SEC EDGAR "getcurrent" feed** | US equities | Real-time 8-K/other filing alerts | Atom feed, `sec.gov/cgi-bin/browse-edgar?action=getcurrent` | Same UA requirement | Same 10 req/sec | Free |
| **FINRA Equity Short Interest** | US equities | Short interest % of float | Web grid / `developer.finra.org` Query API | Free registration | Biweekly release (structurally delayed ~7 business days) | Free |
| **J-Quants (Free plan)** | Japan/TSE equities | Listed-issue master, daily OHLC, financial summary, earnings calendar | REST v2, `api.jquants.com/v2/...` | Free API key (email or Google signup) | 5 calls/min; history capped at 2 yrs **minus most recent 12 weeks** | Free |
| **Yahoo Finance unofficial chart API (`.T` tickers)** | Japan/TSE equities | OHLCV | `query1.finance.yahoo.com/v8/finance/chart/{ticker}.T` | None (needs Chrome UA header to avoid 429) | Undocumented, throttled | Free |
| **EDINET API v2** | Japan equities | Filings (securities/extraordinary reports), full XBRL | REST, `disclosure.edinet-fsa.go.jp/api/v2/documents.json` | Free subscription key (`Ocp-Apim-Subscription-Key`) | Not published — poll conservatively (≤1 req/5–10 sec) | Free |
| **JPX Statistics pages** | Japan equities | Aggregate short-selling value by industry, outstanding margin balances | HTML (scrape) | None | Updated daily (short-selling) / weekly (margin) | Free |
| **TDnet** | Japan equities | Company timely-disclosure filings | HTML browse only, no feed | None | N/A (scrape-only) | Free |
| **Binance public REST API** | Crypto | OHLCV, funding rate, open interest | REST, `api.binance.com/api/v3`, `/fapi/v1/fundingRate` | None for public market data | Weight-based (~1200 weight/min); public endpoints don't need a key | Free |
| **CoinGecko API** | Crypto | Spot price, market cap, BTC/ETH dominance | REST, `api.coingecko.com/api/v3` | Free "Demo" key optional | 100 calls/min soft cap, ~10k credits/mo | Free |
| **Alternative.me** | Crypto | Fear & Greed Index (0–100) | REST, `api.alternative.me/fng/` | None | No published cap, poll ≤1×/hr | Free |
| **Blockchaincenter.net** | Crypto | Altcoin Season Index (% of top-50 beating BTC over 90d) | HTML (scrape) | None | Daily update | Free |
| **CoinGlass (dashboard)** | Crypto | Funding, OI, liquidation heatmap, Altcoin Season Index | Web dashboard (view only) | None | N/A — programmatic API is $29/mo, dashboard viewing is free | Free (manual) |
| **Dune Analytics (free plan)** | Crypto | Custom-SQL on-chain analytics (EVM chains, Solana) — whale flows, exchange net-flows, and other on-chain metrics defined via query, not a fixed metric catalog | REST query-execution API, `api.dune.com` | Free account + API key | ~15 req/min (query execution), ~40 req/min (reads); 1 seat, 1 concurrent query, 30-min query timeout, queries expire after 3 months | Free |
| **Etherscan V2 (unified multichain API)** | Crypto | Address/tx/token balances, contract ABI/source, gas oracle, supply — 60+ EVM chains under one key via `chainid` param | REST, `api.etherscan.io/v2/api` | Free API key | 3 calls/sec, up to 100,000 calls/day | Free |
| **Finnhub** | US equities + crypto/forex | Real-time quotes, general/company news | REST, `finnhub.io/api/v1` | Free API key | ~60 calls/min (unverified live — confirm in dashboard) | Free |
| **RSS (CoinDesk, CoinTelegraph, MarketWatch, CNBC, Yahoo Finance, Seeking Alpha, Investing.com, Japan Times, NHK Business, Yahoo Japan Business)** | All | Headlines | Standard RSS 2.0 | None | Poll hourly, be a polite client | Free |

**Explicitly excluded from the design:** X/Twitter API (no free tier at all in 2026 — pure pay-per-credit), Ortex/Unusual Whales/Market Chameleon (paid, no usable free API), NewsAPI.org free tier (ToS explicitly forbids production/internal use), CoinGlass programmatic API ($29/mo). IEX Cloud is retired (2024) and should not appear in any code. **Glassnode** is also excluded as of this writing — its free API tier appears to have been discontinued (its pricing page now lists only paid "Advanced"/"Professional" plans, no $0 option); use Dune Analytics + Etherscan V2 above for free on-chain coverage instead, and only revisit Glassnode if the project's $0 budget assumption changes. **LunarCrush** is excluded because its free "Hobby" tier is market-data-only — the social/sentiment data it's known for requires a paid plan (~$90/mo); crypto sentiment in this design comes from Alternative.me's Fear & Greed Index plus the RSS headline firehose instead.

For direct exchange market data (OHLCV, funding rates, open interest), the **CCXT library** (`pip install ccxt`) is the recommended abstraction over hitting Binance/Bybit/Kraken/Coinbase REST endpoints directly — one unified interface across exchanges, still keyless for public market data, so `adapters/binance.py` etc. should be thin CCXT wrappers rather than hand-rolled REST clients per exchange.

**JP-equity live-data asymmetry — no real fallback exists today.** Unlike the US leg (yfinance/Twelve Data/Tiingo, three independent live vendors) and the crypto leg (Binance + CoinGecko, two independent live vendors), the JP-equity leg has exactly one live source: the Yahoo unofficial `.T` chart endpoint. J-Quants Free is *not* a usable live fallback — its free-tier history is capped at "2 years minus the most recent 12 weeks," i.e. it structurally cannot see the last ~3 months, making it reference/backtest data only, never a same-day substitute. Concretely, this means: if the Yahoo `.T` endpoint is throttled, blocked, or otherwise circuit-broken (a real risk — it is undocumented and, per §1's framing, "increasingly anti-scraping-hardened in 2026"), **the JP-equity leg has zero live fallback and goes fully dark**, whereas a US or crypto source outage merely degrades to a second live vendor. This asymmetry is a materially higher outage risk for JP than for the other two asset classes and must be surfaced to the operator, not silently absorbed as "just another stale-cache case."

**"JP data unavailable" mode (defined here; agents/orchestration reference this, not redefine it).** When the JP primary source (Yahoo `.T`) is circuit-broken and there is no live fallback to fail over to, the pipeline does **not** keep serving J-Quants-lagged or last-cached data as if it were current. Instead: (1) every JP-equity `NormalizedBar`/`NormalizedSignal` produced while the outage persists is stamped `data_quality_flag=unavailable` (per the canonical rule in §2.4 — primary AND fallback both circuit-broken); (2) per §2.4's propagation rule, every JP specialist agent consuming that ticker must abstain (`signal_score=0`, `confidence=0`) and `RiskManagerAgent` must force a HOLD/veto on that ticker — this is the "JP-degraded mode" referenced in the agents section; (3) the EOD/ops health line (§4.3) explicitly names JP as the asset class with degraded/unavailable coverage so the operator sees it, rather than the pipeline quietly going quiet. **Future improvement (not yet implemented):** evaluate a second free live JP source — e.g., Stooq's JP tickers (`http://stooq.com/q/d/l/?s=7203.jp`) — as a genuine live fallback for `jp_equity_fallback`; until that is built and verified, JP equities should be treated by the operator as running in a permanently thinner-fallback regime than US/crypto, and accepting JP degrading to a "watchlist/backtest-only" mode during an outage (recommendations paused, historical analysis still available via J-Quants/Parquet) is the honest fallback posture, not a temporary oversight.

---

## 2. Local Data Pipeline Design

### 2.1 Ingestion cadence (per source, driven by rate-limit budget)

| Data | Cadence | Rationale |
|---|---|---|
| US/JP equity OHLCV (yfinance/Twelve Data/Tiingo/Yahoo `.T`) | Every 15–30 min during market hours; 1×/day EOD otherwise | Matches intraday-check schedule (§5) without exceeding vendor throttling |
| J-Quants Free | 1×/day, batched at ≤5 calls/min | Free tier is 12-week-lagged anyway — no value in polling more often; used for reference/backtest data only |
| Alpha Vantage (fundamentals/earnings) | 1×/week per ticker, or on-demand when a ticker enters the watchlist | 25/day cap must cover the whole watchlist |
| SEC EDGAR filings feed | Poll every 2–5 min | Real-time trigger source, well within 10 req/sec |
| EDINET | Poll every 15–30 min | Conservative, undocumented limit |
| TDnet / JPX stats pages | 1×/day (after JST close) | HTML scrape, no realtime need |
| FINRA short interest | 2×/month (on release date) | Matches the source's own publication cadence |
| Crypto OHLCV/funding/OI (Binance, CoinGecko) | Every 5–15 min, 24/7 | Crypto trades round the clock; funding settles every 1h/8h depending on exchange |
| Fear & Greed, Altcoin Season Index, BTC dominance | 4×/day | These are slow-moving composites; no benefit to finer polling |
| News RSS / Finnhub news | Every 5–10 min during market hours, 15–30 min overnight | Balance freshness vs. request budget |

### 2.2 Normalization layer

All raw pulls land in a `raw/` staging area (JSON/CSV as returned by each vendor) and are immediately normalized into a common internal schema before anything else touches them:

```
NormalizedBar: {symbol, exchange, asset_class, ts_utc, open, high, low, close, volume, adjusted: bool, adjustment_factor, source, ingested_at}
NormalizedFundamental: {symbol, period_end, metric, value, unit, source, ingested_at}
NormalizedNewsItem: {item_id (hash of url+title), symbol_tags[], headline, summary, source, url, published_at_utc, ingested_at}
NormalizedSignal: {symbol, asset_class, ts_utc, signal_name, score, weight, agent, params_json}
```

**Canonical price-adjustment convention (binding for all downstream indicator math).** yfinance, Twelve Data, Tiingo, and the Yahoo unofficial `.T` endpoint do not necessarily agree on split/dividend-adjustment across a corporate-action date, and every one of the technical-analysis agents' indicators (SMA/EMA crossovers, Bollinger, RSI-2, ADX, ATR, Donchian) is silently wrong for weeks if the series it reads flips convention mid-lookback. To prevent this, `NormalizedBar` carries two explicit fields: `adjusted: bool` (true once the row has been normalized to the canonical convention below) and `adjustment_factor` (the cumulative split/dividend multiplier applied to the vendor's raw OHLC to reach the canonical value, so raw and adjusted values are both reconstructable for audit). **The one mandated canonical convention for everything downstream of the normalization layer is fully-adjusted close** (splits and dividends both applied, matching yfinance's `auto_adjust=True`/adjusted-close behavior) — every adapter must convert its vendor's native series into this convention before a bar is allowed to leave `raw/` and land in the Parquet lake or SQLite cache; no agent or backtest ever reads a mixed-convention series. **Adapter-level test requirement:** each source adapter (`adapters/yfinance.py`, `adapters/twelvedata.py`, `adapters/tiingo.py`, `adapters/jquants.py`, `adapters/yahoo_unofficial_jp.py`, …) must ship a regression test that pulls a known historical split date for a liquid symbol (e.g., a past US or JP stock split) and asserts price continuity across the split boundary once normalized — an adapter that fails this test is not permitted into the ingestion cadence in §2.1 until fixed.

A thin adapter module per vendor (`adapters/yfinance.py`, `adapters/jquants.py`, `adapters/binance.py`, …) is the *only* place vendor-specific quirks live (timezones — JST for TSE, UTC for crypto exchanges, ET for US equities; currency — JPY vs USD vs USDT; symbol conventions — `7203.T` vs `7203` vs `TM`; and the adjustment normalization above). Everything downstream operates only on the normalized schema and UTC timestamps, converting to local display timezone only at the alert/UI layer.

### 2.3 Local storage

Two-tier local storage, chosen deliberately rather than "just SQLite for everything":

- **SQLite (`state.db`)** — the *operational* store: watchlists, open "paper" positions/suggestions, rate-limit call ledgers (see §2.4), agent run logs, alert-dedup keys, and the cross-day memory store described in the orchestration design (prior recommendations keyed by `symbol/date`). SQLite is the right tool here because these are small, transactional, frequently-read/written rows and the system needs simple crash-safe persistence with zero server process.
- **Parquet files, partitioned by `asset_class/symbol/year/month`** — the *analytical* store for OHLCV bars, computed indicator series, and historical signal scores (e.g., `data/parquet/equities_us/AAPL/2026/08.parquet`). Parquet is used because backtesting and walk-forward validation (per the risk-validation research) need fast columnar scans over years of bars across many symbols — something SQLite handles poorly at scale.
- **DuckDB as the query engine over the Parquet lake** — rather than a separate database, DuckDB is used in-process (`duckdb.connect()`) purely to run SQL directly against the Parquet files for backtests, screener queries ("rank all US watchlist tickers by 252-day return"), and report generation. This avoids ETL-ing Parquet into yet another database; DuckDB queries the files where they sit.
- **News/sentiment**: raw headlines + FinBERT/local-LLM scores are written to a SQLite table (`news_items`, `sentiment_scores`) rather than Parquet, since this is high-cardinality text with lookups by symbol/date rather than large-scale numeric scans.

Rough layout:
```
data/
  raw/                  # vendor-native responses, kept ~30 days for debugging, then pruned
  parquet/
    equities_us/<symbol>/<yyyy>/<mm>.parquet
    equities_jp/<symbol>/<yyyy>/<mm>.parquet
    crypto/<symbol>/<yyyy>/<mm>.parquet
  state.db              # SQLite: watchlist, positions, agent logs, memory store, rate-limit ledger
  news.db               # SQLite: news_items, sentiment_scores
```

### 2.4 Caching and rate-limit respect

- **Token-bucket ledger in SQLite**: a `rate_limit_calls(source TEXT, ts_utc REAL)` table. Before any adapter fires a request, it queries `COUNT(*) WHERE source=? AND ts_utc > now - window` and compares against that source's documented cap (e.g., Alpha Vantage: 25/day; J-Quants: 5/min; Twelve Data: 8/min & 800/day). If the budget is exhausted, the call is deferred to the next scheduled tick or served from cache — never retried in a tight loop.
- **Read-through disk cache** (e.g., `diskcache` library or plain JSON files with a TTL column) keyed by `(source, endpoint, params_hash)`, with TTL matched to the ingestion cadence in §2.1 (e.g., a J-Quants pull is cached for 24h; a Binance funding-rate pull for 5 min). This means a crashed/retried job or an ad-hoc agent query never issues a duplicate live call within the TTL window.
- **Backoff on 429/5xx**: exponential backoff (base 2s, capped at 5 min) with jitter, specifically because yfinance, the Yahoo `.T` endpoint, and Stooq are documented to throttle unpredictably in 2026; a hard circuit-breaker (skip source for the rest of the run, log a warning) prevents one flaky vendor from stalling the whole scheduled job.
- **Batching**: wherever a vendor supports multi-symbol or wide-date-range calls in one request (Alpha Vantage's `EARNINGS_CALENDAR` CSV sweep, Twelve Data batch quotes), the pipeline always prefers one wide call over many narrow ones to conserve the daily/per-minute budget.
- **Canonical `data_quality_flag` propagation rule (this is the authoritative definition — the agents and orchestration sections reference these rules rather than restating or redefining them):**
  - `data_quality_flag=stale`: set whenever a value served from the read-through cache has age (now − `ingested_at`) exceeding **2× its configured TTL** for that source/endpoint (the TTLs are the ones defined earlier in this subsection, e.g. 24h for J-Quants, 5 min for Binance funding). Any agent consuming a `stale`-flagged input **must cap its own confidence at ≤0.3** for that signal, regardless of how strong the raw score looks.
  - `data_quality_flag=unavailable`: set whenever **both** a source's primary adapter **and** its configured fallback are circuit-broken (per the backoff/circuit-breaker behavior above) at the time a value is requested — i.e., there is no live or cached-within-2×TTL value to serve at all. Any agent consuming an `unavailable`-flagged input **must abstain**: emit `signal_score=0, confidence=0` rather than guessing, and `RiskManagerAgent` **must force a HOLD/veto** for that ticker until the flag clears. The JP-equity "JP data unavailable" mode described in §1 is the concrete worked example of this rule (JP has no live fallback, so a primary-source outage there goes straight to `unavailable`, not merely `stale`).
  - `data_quality_flag=partial`: reserved for values assembled from an incomplete batch/multi-symbol response (e.g., a batched quote call that returned data for 18 of 20 requested symbols); does not by itself force an abstain, but agents should treat it as a mild confidence penalty at their own discretion.
  - A Phase-1 regression test must assert this propagation end-to-end: feed a mock adapter that is stale-by->2×TTL and one that is fully circuit-broken (primary+fallback), and confirm the resulting agent output matches the confidence-cap / abstain-and-veto behavior above.

---

## 3. News & Sentiment Monitoring Design

### 3.1 Sources feeding the monitor

- **Real-time filing triggers**: SEC EDGAR "getcurrent" Atom feed (US, true real-time, free) for 8-K/10-Q/10-K/Form 4; EDINET API v2 poll (Japan, key required) for extraordinary/securities reports; TDnet HTML poll as a fallback/cross-check for JP disclosures (no clean feed exists, so this is a scheduled scrape, not push).
- **Headline firehose**: RSS from CoinDesk, CoinTelegraph (crypto); MarketWatch, CNBC, Yahoo Finance, Seeking Alpha, Investing.com (US); Japan Times, NHK Business, Yahoo Japan Business (JP, general-interest — there is no free Nikkei feed, a known gap for JP-specific coverage). Finnhub `company_news`/`general_news` for ticker-scoped headlines.
- **Pre-scored cross-check**: Alpha Vantage `NEWS_SENTIMENT` (25/day budget) used sparingly to spot-check the local scorer's output against a vendor-provided sentiment label, not as a primary feed.
- **Crypto-specific sentiment composites**: Alternative.me Fear & Greed Index, Blockchaincenter Altcoin Season Index, BTC dominance (CoinGecko) — these feed the crypto leg of `NewsSentimentAgent` as macro/regime overlays rather than headline-level scores.

### 3.2 Scoring pipeline

1. **Ingest & dedupe**: every RSS/API item is hashed (`sha256(url + title)`) and upserted into `news.db:news_items`; duplicates across feeds (common — e.g., the same Reuters wire story appearing on both MarketWatch and Yahoo Finance) are collapsed to one row with a `sources[]` array.
2. **Symbol tagging**: simple ticker/company-name matching against the current watchlist (plus a small alias table, e.g., "Toyota" → `7203.T`) to attach `symbol_tags[]`. Items with no watchlist match are kept for macro-sentiment aggregates (Fear & Greed style rollups) but don't trigger per-ticker alerts.
3. **First-pass filter — FinBERT** (`ProsusAI/finbert`, local, CPU): every tagged headline+summary gets a positive/negative/neutral softmax score. This is fast enough to run on the full firehose without cost.
4. **Second-pass — local LLM via Ollama** (e.g., Qwen2.5 7B or Phi-4-mini, already running locally with no API cost): only headlines that (a) are tagged to a watchlist symbol *and* (b) clear a magnitude/relevance threshold from the FinBERT pass are re-scored with a structured-JSON prompt: `{"score": -1..1, "confidence": 0..1, "rationale": "...", "event_type": "earnings|filing|macro|rumor|analyst|other"}`. This two-pass design keeps LLM latency/CPU load bounded to a small, relevant subset rather than every headline.
5. **Aggregation into a per-symbol sentiment score**: `NewsSentimentAgent` reads the last N hours (configurable, default 24h for equities, 6h for crypto given faster news cycles) of scored items for a symbol, computes a recency-weighted average (exponential decay, half-life ~4h) and an item count, and outputs a single structured verdict matching the same schema as the other specialist agents: `{signal: BUY|SELL|HOLD, conviction: 0-1, rationale, key_risks}`. Item count acts as a confidence multiplier — one strongly negative headline moves the score less than three independently-sourced negative headlines.
6. **Explicit low-precision framing**: per the research, headline sentiment (FinBERT or small local LLM) is treated as a *noisy, high-recall/low-precision* input — `NewsSentimentAgent`'s conviction is capped (e.g., max 0.6) so it can tilt the supervisor's weighted aggregation but can't unilaterally flip a BUY/SELL recommendation on sentiment alone.
7. **Filing-triggered override path**: an EDGAR/EDINET filing for a watchlist symbol bypasses the sentiment-scoring pipeline entirely and goes straight to the alerting layer (§4) as a "filing alert" — a fact, not a sentiment judgment, so it doesn't need FinBERT/LLM scoring, just a link and filing type.

---

## 4. Alerting Design

### 4.1 Alert triggers (concrete thresholds)

| Trigger | Condition | Severity |
|---|---|---|
| Composite signal score crosses threshold | Supervisor's aggregated score moves from below to at/above `\|score\| ≥ 0.7` for a watchlist symbol | High |
| Squeeze-risk flag | Composite squeeze score (§ short-squeeze factors) ≥ 0.6 | High |
| Open "suggested position" stop/target proximity | Price within 0.5×ATR of the suggested stop-loss or profit-target level | High (stop) / Medium (target) |
| RVOL + price spike | RVOL ≥ 3× with same-bar \|return\| ≥ 2% (equities) or ≥ 4% (crypto, higher baseline vol) | Medium |
| New filing on watchlist symbol | EDGAR 8-K / EDINET extraordinary or securities report / TDnet disclosure matched to a watchlist ticker | Medium (auto-escalated to High if filing type is "material event"/8-K Item 2.02, 5.02, etc.) |
| Upcoming token unlock | Unlock event within 7 days sized ≥2% of circulating supply or ≥20× daily volume | Medium |
| Earnings date approaching | Watchlist symbol has earnings within 24h | Medium (position-sizing caution, not directional) |
| Sentiment extreme + open exposure | Fear & Greed ≥ 80 or ≤ 20 while the symbol/asset-class has an open suggested position | Low (informational risk overlay) |
| Data pipeline failure | A required source has failed to refresh within 2× its expected cadence (e.g., no OHLCV update in 60 min during market hours) | Low (ops alert, separate channel) |

Every alert is deduplicated: a `(symbol, trigger_type, bucket)` key is written to SQLite with a cooldown window (e.g., 2 hours for the same trigger on the same symbol) so a stock hovering exactly at the 0.7 threshold doesn't spam the channel every 15-minute cycle.

### 4.2 Channels

- **Telegram Bot API (primary)** — free, HTTPS, simple `POST https://api.telegram.org/bot<token>/sendMessage`, ≤1 msg/sec per chat is far above this system's alert volume. Chosen as primary because it's push (arrives on phone immediately, unlike email), supports basic Markdown formatting, and needs no always-on listener on the local machine (fire-and-forget POST is enough; no need to run the bot in polling mode for a one-way alert channel).
- **Discord webhook (secondary/backup)** — free, no bot/auth needed, simple incoming webhook POST; used as a redundant channel in case Telegram delivery fails, and as the destination for the lower-priority "ops/pipeline failure" alerts to keep the Telegram channel focused on trading-relevant signals.
- **macOS local notification** — `osascript -e 'display notification ...'` (confirmed working on current macOS) for the EOD summary and pre-market scan completion, since the operator is expected to be at the machine at those times.
- **Email (SMTP, Gmail app-password)** — used only for the End-of-Day summary digest (a longer, multi-symbol report unsuited to a chat message) and the weekly seasonality refresh report.

### 4.3 Example alert message formats

**High-severity composite signal alert (Telegram, Markdown):**
```
🟢 *BUY signal — 7203.T (Toyota)*
Score: +0.78 | Conviction: 0.71 | Asset: JP Equity

Drivers:
• Momentum: 252d return percentile 88 (+0.6)
• Volume: RVOL 3.2x on breakout above 20d Donchian high (+0.5)
• News: 3 positive filings-tagged headlines, 6h decay window (+0.3)
• Risk-manager: no veto (squeeze/earnings flags clear)

Entry ref: ¥2,940 | Stop: ¥2,860 (1.8x ATR14) | Target: ¥3,140 (2R)
Suggested hold: 5–15 trading days (swing)

⚠️ Earnings in 9 days — consider trimming size or exiting before release.
Generated 2026-08-26 08:47 JST | This is analysis only — no order was placed.
```

**Filing alert (Telegram):**
```
📄 *New 8-K filed — NVDA*
Item 5.02 (officer departure) | Filed 2026-08-26 16:02 ET
https://www.sec.gov/... (EDGAR link)
No sentiment/score computed yet — headline-level scoring pending.
```

**Squeeze-risk flag:**
```
⚠️ *Squeeze-risk watch — XYZ*
Squeeze score: 0.64 (SI% of float 34%, days-to-cover 8.1, borrow fee +12% WoW)
Not a directional signal — flagging elevated volatility/whipsaw risk if you're
considering a short, or upside-risk if considering a long entry timing.
```

**EOD summary (email/local notification, one line per watchlist symbol):**
```
Daily Summary — 2026-08-26
US: AAPL HOLD (0.12) | NVDA BUY (0.61, filing caution) | TSLA SELL (-0.55)
JP: 7203.T BUY (0.78) | 6758.T HOLD (0.08)
Crypto: BTC HOLD (0.15, F&G=81 extreme greed, tighten stops) | ETH BUY (0.44)
Pipeline health: J-Quants OK, EDINET OK, Binance OK, yfinance 2 retries (recovered)
```

**Monthly performance-reality digest (email, alongside the existing weekly/monthly recalibration cadence defined in `risk & validation` §6 — this alert is the operational surfacing of that cadence, not a separate schedule):** sent once a month regardless of how the month went, specifically to counter overconfidence after a lucky streak or excessive discouragement after a losing one, by putting the realized numbers next to the aspiration every single month rather than leaving that comparison in a static document the operator stops re-reading.
```
Monthly Performance Reality Check — August 2026
Realized since inception: CAGR (annualized) 11.4% | Sharpe 0.6 | Sortino 0.8 | Max DD -9.2%
Trailing 3mo: CAGR 14.0% | Sharpe 0.7 | 24 closed trades | hit rate 46%

Aspiration on record: 50%+ account growth (~¥100,000 → ~¥150,000+).
Reality check: your realized CAGR/Sharpe above are the numbers that matter, not the
aspiration. Per `risk & validation` §7: 97% of persistent retail day traders in the
Brazilian full-population study lost money; a systematic strategy that survives years
typically runs Sharpe ~1-2 and CAGR ~15-40%/yr; 50%+ in months is a low-probability
tail outcome, not something to size or emotionally anchor on. Treat this system's
goal as capital preservation + demonstrated statistically-significant edge first.
```

### 4.4 What never triggers an alert or an action

Consistent with the "no auto-execution" requirement: alerts are informational only, no alert payload contains an executable order, no channel/bot has write-back capability into a broker/exchange account, and the human-in-the-loop checkpoint (per the orchestration design) gates even the *writing* of a recommendation to the log/alert layer — the pipeline can compute scores continuously, but nothing gets pushed to Telegram/Discord without passing that checkpoint.

---

## 5. Recommended Run Schedule

Implemented via **APScheduler 3.x** (the 4.0 line is still alpha as of Aug 2026 — do not build on it) running as a long-lived process supervised by a `launchd` plist (`~/Library/LaunchAgents/com.local.tradingagents.plist`) so it survives reboots/sleep. All times below are illustrative local-market times; the scheduler itself should be configured with explicit timezone-aware cron triggers (`America/New_York` for US, `Asia/Tokyo` for JP, `UTC` for crypto) rather than relying on the machine's local timezone.

| Job | Schedule | Purpose |
|---|---|---|
| **Pre-market scan (US)** | 08:00–09:15 ET, every 15 min | Refresh overnight news/filings, recompute scores for watchlist, surface pre-market gappers/RVOL spikes before 09:30 open |
| **Pre-market scan (JP)** | 08:00–09:00 JST, every 15 min | Same, ahead of TSE 09:00 JST open |
| **Intraday check (US equities)** | Every 15–30 min, 09:30–16:00 ET | Re-score watchlist, check stop/target proximity, RVOL spikes |
| **Intraday check (JP equities)** | Every 15–30 min, 09:00–11:30 & 12:30–15:00 JST | Same, respecting TSE's lunch break |
| **Crypto check** | Every 15 min, continuous 24/7 | No market close; funding-rate/OI/liquidation refresh plus signal re-score |
| **News/filing poll** | Every 2–5 min (EDGAR feed), every 15–30 min (EDINET, RSS) | Continuous background job, independent of market-hours jobs |
| **End-of-day summary** | 16:30 ET (US), 15:30 JST (JP), and 00:00 UTC (crypto daily rollup) | Persist the day's closing scores/positions to the SQLite memory store, send the EOD digest (§4.3) |
| **Overnight backfill/cache refresh** | 02:00 local machine time | Pull any missed bars, refresh fundamentals for tickers due for weekly refresh, prune `raw/` cache older than 30 days |
| **Weekly seasonality refresh** | Sunday 18:00 local | Recompute day-of-week/turn-of-month/sector-rotation buckets and PEAD/SUE rankings against the latest week of data; refresh the DuckDB/Parquet-derived seasonality tables used by the technical-analysis agents |
| **Monthly performance-reality digest** | 1st of month, 09:00 local | Send the §4.3 realized-CAGR/Sharpe-vs-aspiration email so the 50%+ aspiration is re-surfaced against actuals every month, not left in a static document |
| **Rate-limit ledger audit / health check** | Daily, 00:05 local | Verify no source exceeded budget in the prior 24h, alert (Discord ops channel) if any adapter has been failing beyond its retry/backoff window |

---

### Summary of key design choices and why

- **SQLite for operational state, Parquet+DuckDB for historical/analytical data** — avoids forcing one storage engine to do two very different jobs (transactional small-row state vs. columnar multi-year backtesting scans).
- **Two-pass FinBERT → local-LLM sentiment scoring** keeps compute bounded on a single local machine while still getting context-aware scoring on the subset of headlines that matter.
- **Telegram as primary alert channel**, Discord as backup, matches the free, low-latency, push-capable requirement with no server component needed.
- **All rate limits are enforced defensively** (ledger + cache + backoff) because nearly every free-tier source in this stack (yfinance, Yahoo `.T`, Stooq, J-Quants Free, Alpha Vantage) is explicitly documented above as either thin, undocumented, or increasingly anti-scraping-hardened in 2026 — the pipeline is designed to degrade gracefully (serve cached/stale data, skip a cycle) rather than crash or get IP-blocked.
- **Nothing in this design writes orders or has execution capability** — the pipeline's only outputs are scores, log entries, and alert messages for a human to act on manually.