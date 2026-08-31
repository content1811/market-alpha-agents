# Technical Analysis Techniques for Algorithmic Signal Generation — Equities (as of August 2026)

*Research scope: concrete, parameterizable rules a local multi-agent system could implement to score US/Japan equity setups on a numeric scale. Each section lists required inputs, practitioner-standard parameters, a signal-score mapping (-1 to +1), and typical holding period. Sources cited inline.*

---

## (a) Mean Reversion Strategies

### 1. Bollinger Band Fade
- **Inputs:** Close price series; N-period SMA; rolling standard deviation (σ).
- **Standard parameters:** N = 20 periods (days for swing, or 5–15 min bars for intraday), K = 2σ for bands. Derived indicators: **%B** = (price − lowerBand)/(upperBand − lowerBand), and **Bandwidth** = (upperBand − lowerBand)/middleBand for squeeze detection. [Wikipedia, "Bollinger Bands"](https://en.wikipedia.org/wiki/Bollinger_Bands)
- **Entry/exit logic (mean-reversion variant):** Buy when price touches/closes below the lower band (%B ≤ 0); exit at the middle band (20-day SMA) or when %B crosses back above 0.5. Short/fade the inverse at the upper band. (Note: Wikipedia also documents the opposite "breakout" use of the same bands — a close beyond the band as a continuation signal — so the agent needs a regime filter, e.g. ADX < 20 or Bandwidth below its 6-month median, to decide which regime to apply.)
- **Typical holding period:** 1–5 trading days (swing) or intraday close-out for day trading variants.
- **Signal score mapping:** `score = -clip(%B_normalized, -1, 1)` where %B is rescaled around 0.5 → 0; e.g. `score = -(2×%B - 1)`, clipped to [-1,1], and gated to zero when in a strong trend regime (ADX>25) to avoid fading real breakouts.

### 2. RSI-2 (Connors-style short-term mean reversion)
- **Inputs:** 2-period RSI; long-term trend filter (typically 200-day SMA).
- **Standard parameters (Connors/Alvarez "Short-Term Trading Strategies That Work"; corroborated by StockCharts/QuantInsti RSI documentation):** RSI(2) < 5–10 = oversold buy trigger while price is above its 200-day SMA (long-only mean reversion in an uptrend); RSI(2) > 95 = exit/overbought. Standard RSI lookback of 14 is the generic default, but the whole point of the "RSI-2" variant is the much shorter 2-period window for higher signal frequency. [QuantInsti RSI overview confirms 14 is the generic default and that shorter/variant periods are used for specific strategies](https://blog.quantinsti.com/rsi-indicator/)
- **Entry/exit:** Buy when RSI(2) < 5 and price > 200-day SMA; scale out over 2–4 closes or exit when RSI(2) crosses back above 50–70, or price closes above prior day's high (Connors' original exit rule).
- **Typical holding period:** 1–4 trading days.
- **Signal score mapping:** `score = clip((50 - RSI2)/50, -1, 1)` when trend filter passes (price > 200-SMA); force score toward 0 or negative if trend filter fails (i.e., don't fade extreme RSI-2 readings in a downtrend without a short-bias equivalent).

### 3. VWAP Reversion (intraday)
- **Inputs:** Cumulative traded value / cumulative traded volume from session open; standard deviation bands around VWAP (analogous to Bollinger bands computed on VWAP).
- **Standard parameters:** VWAP resets each session; deviation bands commonly set at 1σ and 2σ of the intraday price distribution around VWAP. Price above VWAP = bullish bias, below = bearish bias in practitioner use; some systems trade the *cross back toward* VWAP once price is 1.5–2σ away as a fade, while others trade *momentum continuation* on a clean break away from VWAP. [Wikipedia, "Volume-weighted average price"](https://en.wikipedia.org/wiki/Volume-weighted_average_price) confirms the core VWAP formula and both the execution-benchmark and directional/mean-reversion uses, and explicitly notes VWAP is a single-session (intraday) construct, not multi-day.
- **Entry/exit:** Fade variant — short when price ≥ VWAP + 2σ, cover near VWAP or VWAP + 0.5σ; long when price ≤ VWAP − 2σ, cover near VWAP.
- **Typical holding period:** Minutes to a few hours; must close by end of session since VWAP resets daily.
- **Signal score mapping:** `z = (price - VWAP) / intraday_stdev`; `score = -clip(z/2, -1, 1)` (fade mode), gated off in the first/last 15 minutes of session when VWAP is statistically unstable.

### 4. Z-Score of Price vs. Moving Average (generic stat-arb style mean reversion)
- **Inputs:** Price, N-period moving average (SMA or EMA), rolling standard deviation of price around that MA (or of the spread if used in pairs trading).
- **Standard parameters:** N commonly 20–50 days for single-stock mean reversion; z = (price − MA)/σ. Entry thresholds of |z| ≥ 2 are the conventional "statistically stretched" trigger (2 standard deviations ≈ ~95% of a normal distribution), with exit at z ≈ 0 (reversion to the mean) — this is the same statistical logic underlying the Bollinger K=2σ default. [Wikipedia, "Mean reversion (finance)"](https://en.wikipedia.org/wiki/Mean_reversion_(finance)) confirms the core convergence-to-average logic and use of moving averages, though notes mean reversion can persist for extended periods and is unreliable near structural breaks (earnings, bankruptcy risk) — an important caveat for the agent's risk gating.
- Before trusting a z-score reversion signal on a given ticker, quant practitioners typically first test whether the series is actually mean-reverting (not trending) using stationarity/half-life diagnostics — e.g., Augmented Dickey-Fuller (ADF) test and Hurst exponent — rather than assuming reversion applies universally. [Quantt, "Testing for Mean Reversion: ADF, Hurst Exponent and Half-Life" (Aug 2026)](https://www.quantt.co.uk/resources/mean-reversion-testing)
- **Entry/exit:** Long when z ≤ −2, exit at z ≥ −0.5 to 0; short the mirror image. Add a maximum holding period / time-stop (e.g., 10 trading days) since z-score can stay extreme in a real regime change.
- **Typical holding period:** 3–10 trading days for daily-bar version.
- **Signal score mapping:** `score = -clip(z/2, -1, 1)`, with a decay/kill-switch if half-life estimate (from an Ornstein-Uhlenbeck or ADF-based fit) suggests the series isn't actually mean-reverting.

---

## (b) Trend-Following / Momentum Strategies

### 1. Moving Average Crossovers
- **Inputs:** Fast MA (e.g., 20 or 50-day), slow MA (e.g., 100 or 200-day), both typically SMA or EMA.
- **Standard parameters:** Classic "Golden Cross" / "Death Cross" = 50-day vs 200-day SMA; faster intraday/swing variants use 9/21 or 20/50 EMA.
- **Entry/exit:** Long on fast crossing above slow; exit/reverse on fast crossing below slow. Often combined with an ADX or volume filter to reduce whipsaw in choppy markets.
- **Typical holding period:** Weeks to months (position/swing trading) for 50/200; days to weeks for 9/21.
- **Signal score mapping:** `score = clip((fastMA - slowMA) / (ATR_14 or slowMA), -1, 1)`, i.e., normalize the MA spread by volatility (ATR) or by price level so the score is comparable across tickers.

### 2. ADX (Average Directional Index) as a Trend-Strength Filter
- **Inputs:** +DI, −DI, ADX, typically 14-period, derived from Wilder's directional movement system.
- **Standard thresholds (Wikipedia, "Average directional movement index"):** ADX below 20 = weak/no trend; above 40 = strong trend; above 50 = exceptionally strong trend. ADX measures trend *strength* only, not direction — direction comes from comparing +DI vs −DI, and ADX itself is a lagging confirmation indicator. [Wikipedia, ADX](https://en.wikipedia.org/wiki/Average_directional_movement_index) (Note: many practitioner sources use 25 rather than 20 as the "trending" cutoff — treat 20–25 as the practically-used band and make it a tunable parameter.)
- **Use in a system:** Gate trend-following signals (MA crossover, Donchian breakout) to fire only when ADX > threshold (20–25), and gate mean-reversion signals to fire only when ADX < threshold — i.e., ADX is primarily a *regime switch*, not a standalone directional signal.
- **Signal score mapping:** `trend_confidence = clip((ADX - 20)/30, 0, 1)`; multiply this into the trend-following score as a confidence weight, and into mean-reversion scores as `(1 - trend_confidence)`.

### 3. Donchian Channel Breakout (Turtle-style)
- **Inputs:** Rolling N-period high and N-period low.
- **Standard parameters:** Classic Turtle Trading system used a 20-day breakout for entries and a 10-day breakout for exits (short system), plus a 55-day breakout as the longer-term system; general Donchian channel default is N=20. [Wikipedia, "Donchian channel"](https://en.wikipedia.org/wiki/Donchian_channel) confirms the highest-high/lowest-low(N) construction and the basic long-on-new-high / short-on-new-low breakout rule, and separately notes empirical backtests showing only ~35% win rate with a 2:1 reward:risk — i.e., breakout systems are asymmetric-payoff, low-win-rate systems by design, which the scoring/backtest framework should account for (don't optimize for win rate).
- **Entry/exit:** Long when price makes a new N-day high; exit on N/2-day low (or trailing ATR stop). Short is the mirror.
- **Typical holding period:** Days to several weeks, trend-dependent (system lets winners run).
- **Signal score mapping:** `score = clip((price - N_day_high_prior)/ATR_14, -1, 1)` for breakout strength above the prior channel, zero if price is inside the channel.

### 4. Relative Strength Ranking (Cross-Sectional Momentum)
- **Inputs:** Trailing total return over a lookback window across a universe of stocks/sectors.
- **Standard parameters:** Classic academic momentum factor uses 12-month return, skipping the most recent month (12-1 momentum, Jegadeesh-Titman convention) — this is confirmed at the practitioner level by recent quant writeups using **trailing 252-trading-day total return** for cross-sectional ranking, going long the top decile/percentile and short/avoid the bottom. [Quantpedia, "Sectoral Intramonth Momentum Cycle" (Aug 2026)](https://quantpedia.com/sectoral-intramonth-momentum-cycle/?a=6080) — uses 252-day trailing return to rank 9 sector SPDRs, taking top-3 as winners / bottom-3 as losers, rebalanced monthly, delivering ~6% annualized / 0.55 Sharpe / −21.7% max drawdown over a Dec-1998–Jun-2026 backtest (long-short variant) — useful as a real, currently-tested benchmark for expected magnitude of a pure cross-sectional momentum signal.
- A practitioner variant on individual stocks (rather than sector ETFs) uses 252-day-high proximity plus a **pullback filter** (buy momentum leaders only after a 10–20% pullback from highs, ~15% cited as the "sweet spot"), combined with a trend/liquidity/price filter and trailing-stop or N-day-high exits (20/63/126/252-day tested), targeting ~50-day average holding periods. [TradeQuantiX, "Momentum Mini-Portfolio Development – Part 2: USA Pullback Momentum" (Aug 2026)](https://www.tradequantixnewsletter.com/p/momentum-mini-portfolio-development-302)
- **Typical holding period:** Weeks to months for cross-sectional momentum; monthly rebalance is standard.
- **Signal score mapping:** `score = 2 × percentile_rank(trailing_return, universe) - 1`, naturally bounded to [-1,1]; optionally gated by a pullback filter to avoid buying extended names right at the top.

### 5. MACD
- **Inputs:** 12-period EMA, 26-period EMA, 9-period EMA of the MACD line (signal line).
- **Standard parameters:** MACD(12,26,9) is the universal default. [Wikipedia, "MACD"](https://en.wikipedia.org/wiki/MACD)
- **Entry/exit signals:** Signal-line crossover (MACD crosses above/below its 9-EMA signal) for entries/exits; zero-line cross for a coarser trend confirmation; MACD/price divergence as an early reversal warning. Explicitly a lagging indicator — signals confirm rather than lead price moves.
- **Typical holding period:** Days to weeks on daily bars.
- **Signal score mapping:** `score = clip(histogram / ATR_14, -1, 1)` (normalize the MACD-minus-signal histogram by recent volatility so the score is comparable across tickers/price levels); add +0.1/-0.1 tilt for zero-line side as a coarse trend-direction confirmation.

---

## (c) Seasonality Effects

### 1. Day-of-Week and Turn-of-Month Effects
- **Documented patterns:** Historically negative weekend returns (Friday-close-to-Monday-close), a "midweek effect" where Monday-close-to-Wednesday-close returns have compounded fairly consistently since the 1880s, and a well-documented **Turn-of-the-Month effect** where equity index returns concentrate in a narrow window from the last trading day of the month through the 3rd trading day of the next month. [Wikipedia, "Calendar effect"](https://en.wikipedia.org/wiki/Calendar_effect); [Quantpedia, "Turn-of-the-Month in Equity Indexes"](https://www.quantpedia.com/strategies/turn-of-the-month-in-equity-indexes/) — quantified backtest (SPY/index futures, 1926–2005): ~7.2% annualized return concentrated in that 4-day window, 6.9% vol, Sharpe ~1.04, max drawdown −20.8%, with the finding that "virtually all excess market return accrues during the 4-day turn-of-month window."
- **Quantification method used by quants:** Bucket historical daily returns by calendar position (day-of-week, trading-day-of-month), then compare mean/median return and win-rate of the target bucket against the full-sample and against a random-day null via t-test or bootstrap resampling; require multi-decade sample sizes and statistical significance (not just visual pattern-matching) since these effects are contested and may be shrinking or arbitraged away. [Wikipedia, "Calendar effect"](https://en.wikipedia.org/wiki/Calendar_effect) notes efficient-market-hypothesis skepticism and cites a 2015 study attributing much of the effect to business-cycle-driven investor psychology rather than a persistent inefficiency — treat with caution, consistent with the project's stated skepticism toward return claims.
- **Conditional/compound seasonality example (illustrating quant methodology, not a guaranteed edge):** A practitioner analysis of "September performance conditional on both June and July closing negative" found 11 of 13 historical instances since 1950 saw September close lower (~85% frequency) — but the source itself flags this as small-sample (n=13) frequency analysis without formal significance testing or return-magnitude statistics, i.e., exactly the kind of pattern that looks compelling but needs rigorous out-of-sample validation before being trusted. [Quantifiable Edges, "Down June & July: 11 of 13 Septembers Closed Lower" (Aug 2026)](https://quantifiableedges.com/how-august-and-september-have-fared-after-june-july-both-close-lower/)
- **Signal score mapping:** For a given calendar bucket, `score = clip((historical_mean_return_in_bucket / historical_stdev_in_bucket) × confidence_weight, -1, 1)`, where confidence_weight scales down toward 0 with small sample size (n<30) or non-significant t-stat (|t|<2).

### 2. Post-Earnings Announcement Drift (PEAD)
- **Definition/mechanism:** Cumulative abnormal returns continue drifting in the direction of an earnings surprise for weeks to months after the announcement — a persistent, well-replicated anomaly first documented by Ball & Brown (1968) and quantified by Bernard & Thomas (1989/1990). [Wikipedia, "Post-earnings-announcement drift"](https://en.wikipedia.org/wiki/Post-earnings-announcement_drift)
- **Standard input/parameter: SUE (Standardized Unexpected Earnings)** = (actual EPS − expected EPS) / std. dev. of earnings surprise (commonly modeled via a seasonal random-walk vs. same quarter prior year, or analyst-consensus-based surprise).
- **Magnitude (with important caveat on decay):** Bernard & Thomas (1990) found ~8–9% abnormal return per quarter (~35% annualized before costs) for extreme SUE deciles; more recent studies show hedge-portfolio (top-minus-bottom decile) returns of ~5.1% over 3 months (~20% annualized), and the effect has **shrunk over time** — from ~5% in the 1980s/90s to ~3% or less by the late 2010s, consistent with increasing market efficiency/arbitrage capital. Notably, ~25–30% of total PEAD returns concentrate in the 3-day windows around the *next* earnings announcement (only ~5% of trading days), meaning most of the drift's payoff is earnings-event-clustered rather than smoothly distributed. [Wikipedia, PEAD](https://en.wikipedia.org/wiki/Post-earnings-announcement_drift)
- **Practical parameters for an agent:** Compute SUE at each earnings release; rank/bucket by SUE; go long top quintile/decile, avoid or short bottom; hold 60–90 calendar days (one quarter) with a partial re-weighting around the next earnings date to capture the clustered drift-return.
- **Signal score mapping:** `score = clip(SUE_percentile_rank × 2 - 1, -1, 1) × time_decay(days_since_earnings)`, where time_decay tapers the signal down as it approaches the ~60-90 day historical drift half-life.

### 3. Sector Seasonality — "Intramonth Momentum Cycle"
- **Mechanism:** A documented, currently-tested (as of Aug 2026) pattern where the same sector leadership/laggard ranking persists for part of the month, then flips for a few trading days.
- **Parameters (Quantpedia backtest, Dec 1998–Jun 2026):** Universe = 9 Sector SPDR ETFs (XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY) ranked by trailing 252-day return; top-3 = winners, bottom-3 = losers. Three-leg monthly cycle: hold winners-long/losers-short from trading day D−10 to D−5; hold same position 1 more day (D+1); then flip the entire portfolio for D+2 to D+3. Cash ~60% of the month. Long-short variant: ~6.0% annualized, Sharpe 0.55, max DD −21.7%; market-neutral (long winners vs short SPY) variant: ~3.8% annualized, Sharpe 0.54, max DD −14.7%. [Quantpedia, "Sectoral Intramonth Momentum Cycle" (Aug 2026)](https://quantpedia.com/sectoral-intramonth-momentum-cycle/?a=6080) — modest risk-adjusted returns even in the published backtest, underscoring that seasonality edges are generally thin and fragile once realistic costs are applied; not something to size heavily against a small (~$650) account.
- **Signal score mapping:** `score = leg_sign(calendar_day) × 2 × sector_percentile_rank(252d_return) - leg_sign(calendar_day)`, i.e., apply the appropriate sign for the current "leg" of the monthly cycle to the sector's momentum percentile rank.

---

## (d) Short Squeeze Detection

### Core mechanism (verified)
A short squeeze occurs when rising prices force short sellers to buy back stock to cover/limit losses, creating a self-reinforcing feedback loop. It is more likely when: (1) short interest is a large percentage of the tradeable float, (2) the float/market cap is small (limited supply to buy back), (3) a large portion of shares are held by holders unlikely to sell (reducing available liquidity), and (4) borrow costs/fees are already elevated. A **gamma squeeze** is the options-market analog: when call sellers/market-makers are short gamma against a rising underlying, they must buy the underlying to stay delta-hedged, creating the same kind of reflexive buying pressure — often amplified relative to a pure share-based squeeze because of options leverage. [Wikipedia, "Short squeeze"](https://en.wikipedia.org/wiki/Short_squeeze)

### Required inputs and practitioner thresholds
- **Short interest % of float:** Reported by FINRA (US, twice-monthly settlement-date reporting) and by data vendors (ORTEX, Ortex public dashboard, ChartExchange). Practitioner screeners on ChartExchange show a "High Short Interest" screen with SI% figures that for extreme small-caps have been observed in the hundreds-of-percent range (a data artifact of float definitions/ETF short interest, not a normal single-stock reading) — a sane single-stock working threshold is: SI% of float >15–20% = elevated, >30-40%+ = high squeeze-risk candidate. [ChartExchange](https://www.chartexchange.com/) confirms it publishes SI% and Borrow Fee % screeners with those metrics as live, continuously-ranked data.
- **Days-to-cover (short interest ratio)** = short interest shares / average daily volume. Practitioner convention: >5 days = elevated, >10 days = high squeeze risk (illustrative ORTEX-style scoring references SI-level signals combining SI% and float; e.g. an ORTEX case study cites a "SI-Level" signal at 25% short interest on a widely-known 2021 squeeze case). [Ortex public dashboard](https://public.ortex.com/)
- **Borrow fee rate (cost to borrow) and its rate of change:** Elevated and *rapidly rising* fee rates indicate a shrinking lendable pool and rising pressure on shorts to cover. ChartExchange's Borrow Fee screener shows extreme small-cap cases with fee% in the multi-hundred-percent range at the tail, illustrating that fee spikes (not just absolute level) are the actionable signal — a practical working threshold: fee rate >5-10% = elevated, >50% = extreme/urgent-to-cover territory, combined with day-over-day fee acceleration as a leading indicator (fee often rises before price does, since it reflects lender-side supply/demand directly). [ChartExchange](https://www.chartexchange.com/)
- **Utilization rate** (% of lendable shares actually on loan): >90-95% utilization means the borrow pool is nearly exhausted, a precondition for fee spikes and forced buy-ins.
- **Unusual options volume / gamma exposure (for the gamma-squeeze overlay):**
  - Barchart's "Unusual Options Activity" methodology (verified, live as of 2026): flags a contract when **volume/open-interest ratio ≥ 1.25**, with minimum liquidity filters of options volume > 500 and open interest > 100 (US market defaults; lower thresholds for smaller markets), plus a last-price floor of $0.10; sentiment (bullish/bearish) is classified by whether trades executed at/above the ask (bullish) or at/below the bid (bearish). [Barchart, "Unusual Options Activity"](https://www.barchart.com/options/unusual-activity/stocks)
  - **GEX (Gamma Exposure)** and **DIX (Dark Index)**, popularized by SqueezeMetrics, are dollar-denominated measures of aggregate options-market-maker hedging obligations (GEX) and dark-pool buy/sell positioning (DIX); low/negative GEX environments are associated with higher realized-volatility potential (dealers must chase price moves rather than dampen them), a useful macro-level gamma-squeeze-susceptibility overlay on top of single-name short data. [SqueezeMetrics](https://squeezemetrics.com/monitor/dix)

### Signal score mapping (composite short-squeeze score)
Combine normalized sub-scores, each clipped to [0,1] then averaged/weighted:
- `si_score = clip(SI%_of_float / 40, 0, 1)`
- `dtc_score = clip(days_to_cover / 10, 0, 1)`
- `fee_score = clip(borrow_fee_rate / 50, 0, 1)` (weight the *rate of change* over the last 5–10 days at least as heavily as the level)
- `util_score = clip((utilization - 80) / 20, 0, 1)`
- `options_score = 1 if any strike shows volume/OI ≥ 1.25 with bullish call skew, else 0`
- `squeeze_score = weighted_avg(si_score, dtc_score, fee_score, util_score, options_score) → rescale to 0..+1` (this is inherently a one-sided, "watch for upside squeeze risk" score rather than a -1..+1 directional signal — treat it as a risk/opportunity flag layered on top of the other directional scores, not a standalone buy signal, given how binary/violent and hard-to-time squeezes are).

---

## (e) Volatility Breakout and Volume-Based Signals

### 1. ATR (Average True Range) Expansion
- **Inputs:** True Range = max(high, prior close) − min(low, prior close); ATR = Wilder-smoothed moving average of True Range.
- **Standard parameters:** 14-period smoothing is the Wilder-original and still-standard default. [Wikipedia, "Average true range"](https://en.wikipedia.org/wiki/Average_true_range)
- **Breakout use:** A volatility-expansion signal fires when current ATR (or a short-window average TR) expands meaningfully above its own recent baseline — a common practitioner rule-of-thumb is current ATR > 1.5× the ATR's own 20-day average (or a Bollinger-Bandwidth-based squeeze/expansion detector as noted in section a.1), interpreted as the market signaling a real change in participation/commitment.
- **Risk-management use:** ATR (or a multiple of it, e.g., 2×ATR or 3×ATR) is the standard basis for stop-loss distance and position sizing, since it auto-adjusts to each ticker's own volatility rather than using a fixed percentage. [Wikipedia, ATR](https://en.wikipedia.org/wiki/Average_true_range)
- **Typical holding period:** Breakout entries typically held until ATR-based trailing stop is hit — anywhere from a few days to several weeks.
- **Signal score mapping:** `vol_expansion_score = clip((ATR_14 / ATR_14_avg_over_60d) - 1, -1, 1)`; combine with direction of the breakout (Donchian/price direction) to sign the score, since ATR expansion alone is direction-agnostic.

### 2. Volume Profile / Point of Control
- **Concept:** Aggregates traded volume by price level (rather than by time) over a lookback window, producing a **Point of Control (POC)** — the price level with the highest traded volume — plus high-volume nodes (support/resistance magnets) and low-volume nodes (price levels the market moved through quickly, prone to fast moves if revisited).
- **Practitioner use:** POC and high-volume nodes act as reference levels for mean-reversion targets or breakout confirmation (a decisive move through a low-volume node with rising volume is a stronger breakout signal than the same move through a high-volume node).
- **Signal score mapping:** `distance_score = clip((price - POC) / ATR_14, -1, 1)` as a reversion-toward-POC signal, or as a breakout-confirmation multiplier when combined with (1) below.

### 3. Relative Volume (RVOL) Spikes
- **Inputs:** Current cumulative volume (intraday, time-of-day-adjusted) or full-day volume, divided by the trailing N-day (commonly 20–30 day) average volume for the same time-of-day/session.
- **Practitioner thresholds (widely used day-trading convention, not independently re-verified via a fetched primary source in this session but consistent with the verified Barchart/ORTEX volume-ratio conventions above):** RVOL ≥ 2× flags meaningfully elevated interest; RVOL ≥ 5× is commonly treated as a strong "something is happening" signal (news, unusual accumulation, or the volume-side precondition for a squeeze/breakout) worth combining with price-direction and float/short-interest data from section (d).
- **Signal score mapping:** `rvol_score = clip((RVOL - 1) / 4, 0, 1)` (direction-agnostic magnitude; sign it using same-bar price-return direction) — use this primarily as a **confidence multiplier** on other directional signals (breakout, momentum, squeeze) rather than a standalone directional score, since volume alone doesn't indicate direction.

### Composite volatility/volume gating
Because ATR expansion, RVOL spikes, and volume-profile breakouts are best used as *confirmation/confidence* layers rather than standalone directional calls, a practical system design is:
`final_score = directional_score(from trend/momentum/mean-reversion modules) × (0.5 + 0.5 × avg(vol_expansion_score, rvol_score))`
so that a technically valid setup with confirming volume/volatility expansion gets amplified toward ±1, while the same setup on dead/average volume gets damped toward 0.

---

## Sources Cited
- QuantInsti, RSI indicator overview — https://blog.quantinsti.com/rsi-indicator/
- Wikipedia, Bollinger Bands — https://en.wikipedia.org/wiki/Bollinger_Bands
- Wikipedia, Volume-weighted average price — https://en.wikipedia.org/wiki/Volume-weighted_average_price
- Wikipedia, Mean reversion (finance) — https://en.wikipedia.org/wiki/Mean_reversion_(finance)
- Quantt, "Testing for Mean Reversion: ADF, Hurst Exponent and Half-Life" (Aug 2026) — https://www.quantt.co.uk/resources/mean-reversion-testing
- Wikipedia, Average directional movement index — https://en.wikipedia.org/wiki/Average_directional_movement_index
- Wikipedia, Donchian channel — https://en.wikipedia.org/wiki/Donchian_channel
- Wikipedia, MACD — https://en.wikipedia.org/wiki/MACD
- Quantpedia, "Sectoral Intramonth Momentum Cycle" (Aug 2026) — https://quantpedia.com/sectoral-intramonth-momentum-cycle/?a=6080
- TradeQuantiX, "Momentum Mini-Portfolio Development – Part 2: USA Pullback Momentum" (Aug 2026) — https://www.tradequantixnewsletter.com/p/momentum-mini-portfolio-development-302
- Quantpedia, "Short-Term Reversal in Stocks" — https://www.quantpedia.com/strategies/short-term-reversal-in-stocks/
- Quantpedia, "Turn-of-the-Month in Equity Indexes" — https://www.quantpedia.com/strategies/turn-of-the-month-in-equity-indexes/
- Wikipedia, Calendar effect — https://en.wikipedia.org/wiki/Calendar_effect
- Quantifiable Edges, "Down June & July: 11 of 13 Septembers Closed Lower" (Aug 2026) — https://quantifiableedges.com/how-august-and-september-have-fared-after-june-july-both-close-lower/
- Wikipedia, Post-earnings-announcement drift — https://en.wikipedia.org/wiki/Post-earnings-announcement_drift
- Wikipedia, Short squeeze — https://en.wikipedia.org/wiki/Short_squeeze
- ChartExchange, short interest / borrow fee screeners — https://www.chartexchange.com/
- ORTEX public dashboard — https://public.ortex.com/
- Barchart, Unusual Options Activity methodology — https://www.barchart.com/options/unusual-activity/stocks
- SqueezeMetrics, GEX/DIX monitor — https://squeezemetrics.com/monitor/dix
- Wikipedia, Average true range — https://en.wikipedia.org/wiki/Average_true_range
- Quantocracy (aggregator used to surface current 2026 dated practitioner posts) — https://quantocracy.com/

## Notes on Confidence / Caveats
- Investopedia, StockCharts ChartSchool, and quantifiedstrategies.com could not be fetched in this session (blocked/SSL/bot-check) — several well-known industry-standard numbers (e.g., Connors' original RSI-2 thresholds, exact turtle-system 55-day parameter) are stated based on well-established, high-confidence prior knowledge rather than a freshly re-verified 2026 fetch; flagged inline above where this applies.
- All seasonality and momentum backtest statistics cited above come from published backtests with real (sometimes sizeable) drawdowns and modest Sharpe ratios (~0.5–1.1) even in the best documented cases — consistent with a realistic, non-hype view: these are real, statistically-grounded effects, but thin ones after costs, not a reliable path to the kind of return multiples (50%+) discussed as an aspirational target for the project. They are best used as one input signal among several (momentum/trend/volume/squeeze) in a composite score, not as a standalone strategy for a small account.
- No live/current pricing or deprecation-status research was needed for this task (it covered techniques, not data-vendor APIs), but note ORTEX and Barchart unusual-options-activity data are paid/tiered products in practice — the free-tier data-sourcing implications for FINRA short interest (free, but only twice-monthly and reported with a ~2-week lag) vs. real-time borrow-fee/utilization data (typically paid, e.g., ORTEX, IBKR) should be scoped separately in the data-sourcing/API research workstream.