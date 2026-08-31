# Crypto-Specific Analytical Factors for Manual Trading — Research Report
**As of: August 26, 2026**

This report covers factors beyond generic TA (moving averages, RSI, chart patterns) that professional/semi-professional crypto traders use, with concrete data inputs and a method to turn each into a numeric sub-score (recommend combining into a single 0–100 composite "Crypto Signal Score" per asset, same pattern as the equity factor scores in the rest of the system). All sources below were live-fetched and verified on 2026-08-26; several show real current readings (e.g., BTC dominance, Fear & Greed) that confirm the pages are current, not stale training-data knowledge.

**Important framing note (skepticism):** every factor below is a *probabilistic, noisy* input, not a predictive rule. Crypto on-chain/derivatives signals are widely followed, which means they are also widely arbitraged — by the time a retail dashboard shows "extreme greed" or "overheated funding," much of the edge has already been priced in by faster players. For a ~$650 starting account, transaction costs, spread, and the operator's own execution lag will likely matter more than marginal improvements to any single factor below. Treat every score as a *tilt*, not a signal to size up aggressively, and don't expect any documented "cycle pattern" (e.g., halving seasonality) to repeat with the same magnitude or timing as 2013/2017/2021.

---

## 1. On-Chain Metrics

### 1.1 MVRV Ratio (Market Value to Realized Value)
- **What it is:** Market Cap ÷ Realized Cap (realized cap values each coin at the price it last moved on-chain, not current price). Measures aggregate unrealized profit/loss of holders.
- **Data inputs:** Market cap (price × circulating supply) and realized cap (sum of UTXO value at last-move price).
- **Sources / free tier:** Glassnode's metric catalog documents MVRV, MVRV Z-Score, NUPL, realized P/L, active addresses, exchange flows, whale/entity-adjusted metrics, and miner balances across BTC/ETH/SOL/etc. — Glassnode's own free "Community" tier covers a limited metric set and Studio/paid tiers unlock the rest. (https://docs.glassnode.com/introduction/metric-catalog.md, https://docs.glassnode.com/) CryptoQuant offers an overlapping free dashboard tier for MVRV/SOPR/exchange flows (site fetch returned 403 to the crawler but is publicly documented as freemium; verify current tier limits at cryptoquant.com before relying on it).
- **Numeric score conversion:** Normalize historical MVRV into a percentile rank (e.g., 0–100 based on trailing 4-year distribution). Classic heuristic bands: MVRV < 1 = capitulation/statistically cheap (score 90–100 bullish-contrarian); 1–2 = accumulation zone (60–80); 2–3.5 = neutral/bull-market normal (40–60); >3.5–7 = historically overheated (score 10–30, caution); extreme historical peaks near 7 have coincided with cycle tops. Convert via a sigmoid or z-score of ln(MVRV) rather than raw linear thresholds, since MVRV is heavy-tailed.

### 1.2 SOPR (Spent Output Profit Ratio)
- **What it is:** Price sold ÷ price paid, averaged across all coins moved on-chain that day. SOPR > 1 means the average moved coin is being sold at a profit; = 1 is a psychologically significant breakeven line.
- **Data inputs:** On-chain spent-output value at time of sale vs. value at time of acquisition (Glassnode/CryptoQuant provide pre-computed daily SOPR and "Adjusted SOPR" which excludes short-term/dust noise).
- **Numeric score:** Track SOPR relative to 1.0 with a 7-day / 14-day moving average. In an uptrend, SOPR repeatedly bouncing off 1.0 from above = healthy bull-market "reset" (bullish continuation, score +15–20 to composite); SOPR breaking decisively below 1.0 in an uptrend = trend-change warning (score −20). In a downtrend, SOPR rejecting 1.0 from below = bear-market resistance confirmation (bearish, negative score); SOPR pushing and holding above 1.0 = potential trend reversal (positive score).

### 1.3 Exchange Net Flows
- **What it is:** Net BTC/ETH/etc. moving onto vs. off exchange wallets. Sustained net outflows are read as accumulation/reduced sell-pressure (coins moving to cold storage/staking); net inflows often precede selling.
- **Data inputs:** Exchange wallet balance deltas (Glassnode, CryptoQuant both track this; CryptoQuant's free tier historically included basic exchange netflow charts for BTC/ETH — reconfirm current free-tier scope directly since tiers change).
- **Numeric score:** Compute 7-day and 30-day net flow as % of exchange reserve. Z-score the daily net flow against its own trailing 90-day distribution. Large net outflow spike (z > +1.5) → positive score contribution (+10 to +20); large inflow spike (z > +1.5 inflow) → negative (−10 to −20). Beware confounders: OTC desk activity, exchange-to-exchange arbitrage transfers, and known wallet reclassification (Glassnode/CryptoQuant periodically relabel entities) can create false signals — this is a real limitation, not a minor caveat.

### 1.4 Whale Wallet Accumulation/Distribution
- **What it is:** Behavior of large holders (commonly defined as addresses holding ≥1,000 BTC, or top 1% of non-exchange addresses), tracked via Glassnode's entity-adjusted / cohort-balance metrics (https://docs.glassnode.com/introduction/metric-catalog.md lists "whale position monitoring (addresses with 1k+ units)").
- **Numeric score:** Track % change in aggregate whale-cohort balance over 7/30 days. Rising whale balance concurrent with flat/falling retail (small-address) balance = accumulation divergence (bullish, +10–15); the reverse = distribution (−10–15). Weight this lower than exchange flow/SOPR because whale-cohort definitions can include exchange cold wallets and get misclassified.

### 1.5 Active Addresses / Network Growth
- **What it is:** Count of unique addresses active per day; a coarse usage/adoption proxy, weak on its own but useful as a divergence check against price.
- **Numeric score:** 30-day moving average of active addresses, converted to % change trailing 90 days. Use mainly as a *divergence* filter: price making new highs while active addresses trend down = bearish divergence flag (subtract 5–10 from composite); price and active addresses both rising = confirmation (add small positive weight, +5). Keep the weight low — this metric is noisy and easily distorted by bot/spam activity on some chains.

---

## 2. Derivatives Signals

### 2.1 Funding Rates (Perpetual Futures)
- **What it is:** Periodic payment (typically every 1h or 8h depending on exchange) between longs and shorts on perpetual futures, designed to anchor perp price to spot. Persistently high positive funding = market is paying a premium to be long (crowded long positioning, mean-reversion/squeeze risk); deeply negative funding = crowded short.
- **Data inputs:** Per-exchange funding rate (Binance, Bybit, OKX, etc.) and open-interest-weighted aggregate funding. CoinGlass aggregates this across exchanges; note that CoinGlass's programmatic **API is paid-only starting at $29/mo (Hobbyist tier, 80+ endpoints/30 req-min)** as of the pricing page fetched today — https://www.coinglass.com/pricing — but the **website dashboard itself displays funding rate, open interest, liquidation, and "Altcoin Season Index" data for free viewing** (https://www.coinglass.com/). For a free-tier, no-paid-API build, plan to scrape/view the dashboard manually or use individual exchange public REST endpoints (Binance/Bybit funding-rate endpoints are free and don't require a key for public market data).
- **Numeric score:** Normalize the annualized funding rate (funding × periods/day × 365) into a z-score vs. trailing 90-day history. Score bands: annualized funding > +30–50% sustained for multiple days = crowded-long warning (contrarian bearish tilt, −10 to −20 to composite, or a "squeeze risk" flag rather than a directional trade); funding deeply negative for days = crowded-short, contrarian bullish tilt (+10 to +20). Funding near 0 = neutral, no adjustment. Always pair with open interest (see 2.2) — high funding + falling OI can mean the crowd is already unwinding (signal decaying), while high funding + rising OI is a stronger warning.

### 2.2 Open Interest (OI)
- **What it is:** Total notional value of outstanding derivative contracts. Rising OI + rising price = trend supported by new money (healthy); rising OI + flat/falling price = potential over-leverage buildup; falling OI = position unwinding/deleveraging.
- **Numeric score:** Track OI rate-of-change (7-day) alongside price rate-of-change; classify into a 2x2: (price↑, OI↑)=trend confirmation (+10), (price↑, OI↓)=short-covering rally, weaker trend (0 to +5), (price↓, OI↑)=fresh shorts building / potential capitulation setup (flag, no fixed direction — watch for squeeze), (price↓, OI↓)=long liquidation/deleveraging, often marks local bottoms once it stabilizes (+5 contrarian once OI decline flattens).

### 2.3 Liquidation Cluster Heatmaps
- **What it is:** Visualization of where large clusters of leveraged long/short liquidation prices sit, built from estimated leverage/entry data across exchanges. Price often gets "magnetized" toward large liquidation clusters (cascading stop-outs).
- **Data inputs:** CoinGlass Liquidation Heatmap (https://www.coinglass.com/LiquidationData) shows real-time and historical (1h/4h/12h/24h) long vs. short liquidation volumes by exchange and price level; a Pro-tier unlocks deeper historical liquidation-event data, but headline heatmap/dashboard viewing is free.
- **Numeric score:** This is best used as a *risk-management overlay* rather than a standalone directional score: identify the nearest large liquidation cluster above and below current price; treat proximity to a large downside cluster as added stop-loss/position-size caution (reduce suggested position size or tighten stop by a fixed % when price is within ~2–3% of a major cluster), rather than trying to trade the cascade directly (that requires speed a manual trader on free-tier data won't have).

### 2.4 Options Skew / Implied Volatility Term Structure
- **What it is:** The difference in implied volatility between OTM puts and OTM calls (25-delta skew is standard). Skew tilted toward puts (put IV > call IV) = market paying up for downside protection (fear); skew tilted toward calls = greed/upside chasing. Deribit dominates BTC/ETH options volume and IV benchmarking (its DVOL index is the crypto equivalent of VIX).
- **Data inputs:** Deribit's public options chain and DVOL (Deribit's insights/statistics pages exist but a couple of specific URLs I probed returned 404s today — verify current path at deribit.com/statistics before building an automated pull). Laevitas provides packaged options analytics (25-delta skew, term structure, Greeks) with a **free tier limited to ~1 week of historical data and basic charting (8 charts/page)**, and a $50/mo Premium tier for 1 year of history and unlimited charts (https://www.laevitas.ch/).
- **Numeric score:** Compute 25-delta skew (put IV − call IV) as a raw number; z-score against its own 60-day trailing distribution. Skew z > +1.5 (unusually put-heavy) = elevated fear, often historically a contrarian-bullish tilt for swing entries (+10); skew z < −1.5 (unusually call-heavy) = complacency/greed, contrarian caution (−10). Given the free-tier data window is short (1 week on Laevitas free), this factor's history-dependent normalization will be weak initially — treat it as a low-weight, slowly-calibrating input in a free-tier build.

---

## 3. Tokenomics Factors

### 3.1 Unlock Schedules / Vesting Cliffs
- **What it is:** Scheduled release of previously locked team/investor/foundation tokens into circulating supply — a known source of sell pressure, especially for large single-cliff unlocks.
- **Data inputs:** The tracker formerly at "Token Unlocks" has rebranded — **token.unlocks.app now redirects (301) to tokenomist.ai** (verified live today: https://tokenomist.ai/). Tokenomist tracks unlock events, vesting schedules, allocation breakdown, emissions, and buyback/burn data across 500+ tokens, with a free dashboard tier, a paid "Tokenomist Pro" tier, and an API with a free trial (per-endpoint free-tier limits not disclosed on the homepage — check /pricing directly). DefiLlama's unlocks page (defillama.com/unlocks) is another free, no-signup source worth cross-checking.
- **Numeric score:** Compute upcoming-unlock size as % of current circulating supply and % of 30-day average daily volume, for a rolling 30-day forward window. Score inversely: unlock value < 1% of circulating supply and < 5x daily volume = negligible (no adjustment); unlock 2–5% of supply or >20x daily volume = meaningful overhang (−10 to −20 to composite, i.e., bearish tilt / reduce position size ahead of the date); >5% of supply in a single cliff = high-risk event (−20 to −30, consider avoiding new long entries into the unlock date). This factor is most relevant to altcoins, not BTC/ETH which have no vesting unlocks.

### 3.2 Supply Inflation / Emission Rate
- **What it is:** Annualized rate of new supply issuance (mining rewards, staking emissions, liquidity-mining incentives) diluting holders.
- **Data inputs:** Tokenomist's emission tracking (staking yields, mining rewards) and Messari/CoinGecko token supply pages (circulating vs. max supply, inflation %).
- **Numeric score:** Annualized inflation rate as a direct negative multiplier on any yield-farming/staking numeric score: net real yield = staking APY − inflation rate (see 3.3). Where inflation > 15–20%/year with no offsetting burn/buyback, apply a standing −5 to −10 penalty to the token's composite score as a structural headwind, independent of price action.

### 3.3 Staking Yields (Real vs. Nominal)
- **What it is:** APY paid for staking/securing PoS networks; the professional distinction is *nominal yield* (headline APY) vs. *real yield* (nominal minus token inflation, i.e., whether staking actually grows your share of the network or merely offsets dilution).
- **Data inputs:** StakingRewards.com tracks 120+ assets and explicitly frames its ratings around "risk-adjusted returns... downside risk, not headline yield" (https://www.stakingrewards.com/, verified live today); it offers an API ("data-api" link) though free-tier limits weren't disclosed on the homepage — confirm at their API docs page.
- **Numeric score:** real_yield = nominal_staking_APY − annual_inflation_rate. Positive real yield with staking ratio (% of supply staked) rising = mild structural bullish tilt (+5); negative real yield (common in many high-emission L1s/L2s) = structural headwind regardless of price momentum (−5 to −10). This factor matters far more for medium/long-term holding-period decisions than for day/swing trades.

---

## 4. Crypto-Specific Seasonality

### 4.1 Halving-Cycle Patterns (BTC)
- **What it is:** The ~4-year BTC block-reward halving (most recent: April 2024) has historically been followed by multi-month rallies peaking roughly 12–18 months post-halving, then a drawdown, in the 2012, 2016, and 2020 cycles. This is the single most-hyped "pattern" in crypto and deserves the strongest skepticism in this report.
- **Caveats (important):** (a) n=3 historical cycles is a very small sample to extrapolate a "law" from; (b) each cycle had a different market-structure backdrop (2024's cycle uniquely includes spot BTC ETFs and much larger institutional flows than prior cycles, which changes the supply/demand mechanics the pattern was based on); (c) proponents themselves increasingly discuss a "diminishing returns" theory — each cycle's percentage gain has been smaller than the last — meaning even people who believe in the pattern don't expect 2017/2021-style multiples to repeat. I attempted to pull a live 2026-dated halving-cycle analysis (Fidelity Digital Assets URL returned 404 today) — recommend the operator search current 2026 cycle-position commentary directly (e.g., via Glassnode/CoinMetrics/Bitcoin Magazine Pro "cycle" pages) before encoding any halving-based seasonality rule, rather than relying on older (2021-era) cycle-pattern writeups.
- **Numeric score (if used at all):** Treat as a very low-weight, slow-moving macro backdrop tag, not a timing signal — e.g., a single "cycle phase" label (early-post-halving / mid-cycle / late-cycle/distribution-risk) contributing at most ±5 to the composite score, clearly flagged to the human operator as low-confidence pattern-matching rather than a data-driven signal.

### 4.2 Monthly / Day-of-Week Seasonality
- **What it is:** Documented (though weak and regime-dependent) historical tendencies, e.g., "September has historically been BTC's weakest month" and "Q4/Q1 turn-of-year effects," discussed across various exchange research blogs and Coinglass's historical monthly-returns tables.
- **Numeric score:** Compute historical mean and win-rate of BTC/ETH returns by calendar month over the past 6–8 years (not further back — market structure has changed too much). Convert the current month's historical average return into a small z-score-based tilt (e.g., ±3–5 points to composite). Explicitly downweight this factor's contribution over time if realized returns stop matching the historical seasonal pattern (a rolling out-of-sample check), since seasonality effects in a market this young are prone to overfitting on a short history.

### 4.3 Quarter-End / Month-End Effects
- **What it is:** Futures/options expiries (notably large monthly and quarterly BTC/ETH options expiries on Deribit) and stablecoin-issuer rebalancing can create elevated volatility around month/quarter-end.
- **Numeric score:** Flag the 24–48 hours around known large options-expiry dates (Deribit publishes expiry calendars) as a "volatility caution" tag — widen suggested stop-loss distance and/or reduce suggested position size by a fixed % rather than assigning a directional score, since the effect is on volatility, not direction.

---

## 5. Sentiment / Social Signals

### 5.1 Crypto Fear & Greed Index
- **What it is:** A composite 0–100 sentiment score. Verified current methodology (fetched live today from https://alternative.me/crypto/fear-and-greed-index/): **Volatility 25%, Market Momentum/Volume 25%, Social Media 15%, Surveys 15% (currently paused), Dominance 10%, Google Trends 10%.** Note the Survey component being paused is a real, current methodology gap worth knowing — the published weights don't currently sum to an active 100% of *live* inputs.
- **Live data point verified today:** A Binance Square page fetched live on 2026-08-26 showed the Fear & Greed reading at **81 ("Extreme Greed")**, consistent with BTC dominance also reading high (59.7%, see §6) — i.e., broad risk-on sentiment as of this report's date.
- **Numeric score:** Use the index value directly, but invert at extremes for contrarian positioning: 0–20 (Extreme Fear) → mild contrarian-bullish tilt (+10 to composite); 20–45 → neutral-to-slightly-bullish; 45–55 → neutral; 55–75 → neutral-to-cautious; 75–100 (Extreme Greed) → contrarian-bearish/caution tilt (−10 to −15), i.e., don't chase strength, tighten profit-targets/trail stops. Do not use this as a standalone entry trigger — it lags and is best as a position-sizing/risk overlay.

### 5.2 Social Volume Spikes
- **What it is:** Sudden spikes in mention volume/engagement (X/Twitter, Reddit, YouTube, TikTok) for a specific asset, often preceding or coinciding with sharp price moves (both genuine narrative shifts and pump-and-dump-style hype).
- **Data inputs:** LunarCrush (Galaxy Score, AltRank, social volume/dominance across 40+ categories per its live homepage today, https://lunarcrush.com/ — free-tier API scope not confirmed on the homepage, verify at their docs) and Santiment (on-chain + social + dev-activity indicators via Sanbase/SanAPI, https://academy.santiment.net/ — free-tier scope also needs direct verification at their pricing page).
- **Numeric score:** Z-score daily social volume against its own trailing 30-day mean/stdev. Spike > 2–3 standard deviations with *positive* sentiment skew and price still near recent lows/consolidation = early-momentum flag (+10 to +15, watch-list trigger for a swing entry). The same spike after a large price move already occurred = late/FOMO flag (−10, caution against chasing). Social-volume spikes are among the noisiest inputs here — recommend low base weight (5–10% of composite) with a cap on how much it alone can move the score, since low-cap tokens are especially prone to coordinated/bot-driven social spikes.

### 5.3 Google Trends
- **What it is:** Relative search interest for terms like "Bitcoin," "buy crypto," or a specific coin name; historically a decent *retail* FOMO/capitulation proxy, already folded into the Fear & Greed Index's 10% Trends component (see 5.1).
- **Data inputs:** Google Trends is free and has no official public API (the unofficial `pytrends` Python library scrapes the public web UI — note this is fragile/ToS-gray-area and can break without notice; today's live fetch attempt to trends.google.com returned HTTP 429, illustrating exactly this fragility).
- **Numeric score:** If used independently of the Fear & Greed composite, compute % change in weekly search interest for the asset name vs. its trailing 12-month average; treat a >2x spike as a lagging confirmation/exhaustion signal (search interest peaks tend to coincide with or slightly lag price peaks, so this factor is best used as a *late-stage euphoria warning*, not an entry trigger) — apply a −5 to −10 adjustment when both price and search interest are simultaneously at multi-month highs.

---

## 6. BTC Dominance / Altcoin-Rotation Dynamics

### 6.1 BTC Dominance
- **What it is:** BTC's share of total crypto market cap. Rising dominance = capital concentrating in BTC (often "flight to relative safety" within crypto); falling dominance = capital rotating into altcoins ("risk-on within crypto").
- **Live data point verified today (2026-08-26):** CoinMarketCap's dominance chart showed **BTC dominance at 59.7%, ETH dominance at 11.3%** (https://coinmarketcap.com/charts/bitcoin-dominance/). This is a genuinely current data point, not a stale figure from training data.
- **Numeric score:** Track 30-day rate-of-change of BTC dominance. Dominance rising + total market cap flat/down = risk-off, alt-selling into BTC (reduce suggested altcoin exposure/tighten alt stops, −10 to alt composite scores specifically). Dominance falling + total market cap rising = classic "altcoin season" setup (positive tilt to alt composite scores, +10 to +15).

### 6.2 Altcoin Season Index
- **What it is:** A cleaner, purpose-built rotation metric than raw dominance. Verified live methodology today (https://www.blockchaincenter.net/en/altcoin-season-index/): if **≥75% of the top 50 coins (excluding stablecoins and wrapped/staked-asset tokens like WBTC/stETH) outperformed BTC over the trailing 90 days**, it's classified as "Altcoin Season"; otherwise "Bitcoin Season." CoinGlass also republishes an Altcoin Season Index on its free dashboard (https://www.coinglass.com/).
- **Numeric score:** Use the index's own breadth % (e.g., "62% of top 50 beat BTC") directly as a rotation-strength continuous score rather than just the binary label: <25% = strong BTC-season tilt (favor BTC over alts, +15 BTC / −15 alts to relative composite); 25–75% = neutral/transition (no strong tilt, rely on asset-specific factors instead); >75% = strong alt-season tilt (+15 alts / −10 BTC relative). Given the system's small account size and free-tier constraints, this is one of the more directly usable, low-cost, well-defined signals in this whole report — recommend giving it real weight in any altcoin buy/sell sizing decision.

---

## Summary Table

| Factor category | Best free-tier source(s) verified today | Score range contribution (suggested) | Confidence |
|---|---|---|---|
| MVRV / SOPR | Glassnode Community tier, CryptoQuant (verify current free scope) | ±20 | Medium — widely followed, some crowding of edge |
| Exchange net flows | Glassnode / CryptoQuant | ±20 | Medium — entity-mislabeling risk |
| Whale accumulation | Glassnode entity-adjusted cohorts | ±15 | Low-medium — classification risk |
| Active addresses | Glassnode | ±10 (divergence only) | Low — noisy |
| Funding rate | Exchange public APIs (free) / CoinGlass dashboard (free view) | ±20 | Medium-high — mechanically grounded |
| Open interest | CoinGlass dashboard | ±10 | Medium |
| Liquidation heatmap | CoinGlass (free dashboard) | Risk overlay only | Medium (for risk mgmt, not direction) |
| Options skew | Laevitas free tier (1wk history) / Deribit | ±10 | Low initially (thin free history) |
| Unlock schedules | Tokenomist (free dashboard) | −30 to 0 | High for known events, mechanical |
| Supply inflation / real yield | StakingRewards, Tokenomist | ±10 | Medium |
| Halving-cycle "pattern" | N/A — treat as narrative, not data | ±5 max | Very low — n=3, structurally changed by ETFs |
| Monthly seasonality | Self-computed from historical price data | ±5 | Low — overfitting risk on short history |
| Fear & Greed Index | alternative.me (free) | ±15 (contrarian at extremes) | Medium |
| Social volume | LunarCrush / Santiment (verify free scope) | ±15 | Low-medium — bot/manipulation risk |
| Google Trends | Free but no official API (fragile scraping) | ±10 | Low |
| BTC dominance | CoinMarketCap (free) | ±15 (relative alt scoring) | Medium |
| Altcoin Season Index | Blockchaincenter.net / CoinGlass (free) | ±15 | Medium-high — clean, well-defined |

## Sources Cited (live-verified 2026-08-26)
- Glassnode docs/metric catalog: https://docs.glassnode.com/ , https://docs.glassnode.com/introduction/metric-catalog.md
- Alternative.me Fear & Greed methodology: https://alternative.me/crypto/fear-and-greed-index/
- Binance Square live Fear & Greed reading (81, Extreme Greed): https://www.binance.com/en/square/post/halving-cycle-2024-price-pattern (page redirected/served homepage content with live index)
- CoinGlass dashboard and pricing: https://www.coinglass.com/ , https://www.coinglass.com/pricing , https://www.coinglass.com/LiquidationData
- Blockchain Center Altcoin Season Index: https://www.blockchaincenter.net/en/altcoin-season-index/
- Tokenomist (rebrand of Token Unlocks): https://tokenomist.ai/ (redirect confirmed from https://token.unlocks.app/)
- StakingRewards: https://www.stakingrewards.com/
- Laevitas options analytics and pricing: https://www.laevitas.ch/
- CoinMarketCap BTC dominance chart (59.7% BTC / 11.3% ETH as of today): https://coinmarketcap.com/charts/bitcoin-dominance/
- CoinGecko API pricing/free tier (100 calls/min, 10k credits/mo): https://www.coingecko.com/en/api/pricing
- Santiment / Sanbase overview: https://academy.santiment.net/
- LunarCrush overview: https://lunarcrush.com/

**Not independently verified live today (recommend re-checking before building automation):** exact CryptoQuant free-tier scope (403 to crawler), Deribit DVOL/options page exact URL (404s hit), Fidelity Digital Assets halving-cycle piece (404), Google Trends live access (429 rate-limited during this research session).