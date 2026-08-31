# Agent Design & Technical Analysis Specification

## 0. Design Principles and Shared Conventions

Before defining each agent, three conventions apply system-wide so that the `PortfolioSupervisorAgent` can mechanically reconcile heterogeneous outputs rather than re-interpreting free text each time.

**Signal score convention.** Every analysis agent (except `RiskManagerAgent` and `MarketRegimeAgent`, §11, both of which are gates/modifiers, not directional voters) outputs a single float `signal_score ∈ [-1.0, +1.0]`: `-1.0` = maximum-conviction sell/short, `0.0` = neutral/no-edge, `+1.0` = maximum-conviction buy. This mirrors the score-mapping formulas already worked out in the underlying TA and crypto-factor research (e.g. `score = -(2×%B - 1)`, `score = clip(z/2, -1, 1)`), so each agent is really just a thin LLM/prompt wrapper around a deterministic numeric computation — the LLM's job is to interpret the computed sub-scores in context and write the rationale, not to eyeball a chart and guess a number.

**Confidence is separate from score.** `confidence ∈ [0.0, 1.0]` reflects how *reliable* the current reading is (sample size, data freshness, regime fit, agreement between sub-indicators) — not how extreme the score is. A `-0.9` score with `confidence 0.2` (e.g., RSI-2 deeply oversold but on a thin, gapping small-cap with stale data) must be treated very differently from a `-0.9` score with `confidence 0.8`.

**Every agent must declare its regime/gating logic.** Per the TA research, ADX (and equivalents) function as a *regime switch*, not a standalone signal — mean-reversion agents must gate themselves off in strong trends and vice versa. This is specified per-agent below and is mandatory, not optional, since the research explicitly warns that fading a real breakout (or trend-following into a range-bound chop) is the most common way this class of system loses money.

**Shared output schema (JSON).** All directional (non-gate/modifier) agents emit this envelope; only the fields inside `sub_scores` and the specific enumerations differ. `RiskManagerAgent` (§9) and `MarketRegimeAgent` (§11) are gates/modifiers rather than directional voters and each define their own differently-shaped output schema instead:

```json
{
  "agent_name": "string",
  "asset_class": "us_equity | jp_equity | crypto",
  "ticker": "string",
  "as_of_timestamp": "ISO8601 UTC",
  "signal_score": -1.0,
  "confidence": 0.0,
  "suggested_holding_period": {"min_days": 0, "max_days": 0, "unit": "trading_days|calendar_days|hours"},
  "stop_loss": {"method": "percent|atr_multiple|structure|vwap_sigma", "value": 0.0, "price_level": null},
  "profit_target": {"method": "percent|atr_multiple|r_multiple|structure", "value": 0.0, "price_level": null},
  "rationale": "<=280 char plain-English string citing the specific numbers that drove the score",
  "sub_scores": { "...": 0.0 },
  "regime_gate_applied": "string or null (e.g. 'ADX=31>25, trend regime, mean-reversion suppressed')",
  "data_quality_flag": "ok | stale | partial | unavailable"
}
```
The canonical propagation rule for `data_quality_flag` — exactly when a value becomes `stale` vs. `unavailable`, and what that forces each agent (and `RiskManagerAgent`) to do — is defined once in the data & alerting section (§2.4); every agent below consumes that rule rather than redefining it (see, e.g., `RiskManagerAgent`'s Confidence note in §9 for a worked example).

**Asset-class applicability matrix.** Not every agent fires for every asset class — this must be enforced in code (the supervisor should never receive, e.g., a `CryptoOnChainAgent` verdict for a TSE ticker):

| Agent | US Equity | JP Equity | Crypto |
|---|---|---|---|
| MeanReversionAgent | ✅ | ✅ | ✅ |
| TrendMomentumAgent | ✅ | ✅ | ✅ |
| SeasonalityAgent | ✅ | ✅ | ✅ (different sub-model) |
| ShortSqueezeAgent | ✅ (full) | ⚠️ (degraded — see below) | ❌ (use CryptoDerivativesAgent funding/OI instead) |
| VolatilityVolumeAgent | ✅ | ✅ | ✅ |
| CryptoOnChainAgent | ❌ | ❌ | ✅ |
| CryptoDerivativesAgent | ❌ | ❌ | ✅ |
| NewsSentimentAgent | ✅ | ✅ (thinner free feed) | ✅ |
| RiskManagerAgent | ✅ | ✅ | ✅ |
| MarketRegimeAgent (§11, system-wide, not per-ticker) | ✅ | ✅ | ✅ |
| PortfolioSupervisorAgent | ✅ | ✅ | ✅ |

---

## 1. MeanReversionAgent

**What it examines.** Whether the instrument is statistically "stretched" away from a short-term equilibrium (price vs. its own moving average / VWAP / band) *and* whether the current regime is actually reversion-prone rather than trending, since fading a real trend is the single most-flagged failure mode in the source research.

**Inputs / data needed.**
- OHLCV daily bars (20–252 day lookback) — yfinance primary, Twelve Data/Tiingo fallback (US); yfinance unofficial `.T` chart endpoint or J-Quants Free (JP, accept ~12-week lag for backtesting only, not live signal); yfinance/exchange REST (crypto).
- Intraday bars (1–5 min) for the VWAP-reversion sub-strategy, session-scoped, day-trading use only.
- 14-period ADX/+DI/−DI (computed locally from OHLC, no extra API needed).

**Concrete indicators and thresholds.**
1. **Bollinger %B / Bandwidth**: SMA(20), σ(20), K=2. `%B = (price-lower)/(upper-lower)`. Fire long-fade when `%B ≤ 0`, exit target `%B ≥ 0.5` (mid-band). Squeeze pre-filter: `Bandwidth < 6-month median Bandwidth` before trusting a fade.
2. **RSI-2 (Connors)**: 2-period RSI + 200-day SMA trend filter. Long trigger: `RSI(2) < 5` AND `price > SMA(200)`. Exit: `RSI(2) > 70` or close > prior day's high.
3. **VWAP reversion** (intraday/day-trade variant only): session VWAP ± σ bands; fire fade at `|z| ≥ 2` where `z=(price-VWAP)/intraday_stdev`; disabled in first/last 15 minutes of session.
4. **Z-score vs 20–50 day MA**: `z=(price-MA)/σ`. Fire at `|z|≥2`. Before trusting, require an ADF/half-life sanity check (or at minimum the ADX gate below) — do not fire on a series behaving like a trend, not a range.
5. **Regime gate (mandatory)**: compute ADX(14). If `ADX > 25`, multiply all mean-reversion sub-scores by `(1 - trend_confidence)` where `trend_confidence = clip((ADX-15)/10, 0, 1)` — i.e. auto-suppress fades in strongly trending tape. Corrected values: `trend_confidence(ADX=20)=0.5`, `trend_confidence(ADX=25)=1.0`, `trend_confidence(ADX=30)=1.0`, `trend_confidence(ADX=40)=1.0` — this reaches full suppression by ADX=25, matching `TrendMomentumAgent`'s ">25 = trending, full weight" threshold (see §2) rather than the earlier `(ADX-20)/30` formula, which only reached 0.17 at ADX=25.

**Signal score computation.**
```
bb_score   = clip(-(2*%B - 1), -1, 1)
rsi2_score = clip((50-RSI2)/50, -1, 1)  if price>SMA200 else 0
vwap_score = clip(-z_vwap/2, -1, 1)     (intraday only)
z_score    = clip(-z_ma/2, -1, 1)
raw_score  = weighted_avg(bb_score:0.3, rsi2_score:0.3, z_score:0.3, vwap_score:0.1 if intraday else redistribute)
signal_score = raw_score * (1 - trend_confidence)
```
**Confidence** = `1 - trend_confidence`, further reduced by 0.3 if `n<30` days of history available, reduced to ≤0.3 if the ADF/half-life check (where computed) indicates non-mean-reverting behavior.

**Output specifics.**
- `suggested_holding_period`: 1–5 trading days (swing variant), or intraday close-out (VWAP variant, must flatten by session end).
- `stop_loss`: `structure` method — beyond the band/level being faded (e.g. lower Bollinger band minus 0.5×ATR for a long fade), cross-checked against `atr_multiple` 1.5×ATR(14) as a sanity floor.
- `profit_target`: `structure` — the mid-band/VWAP/moving average being reverted to; expressed also as an R-multiple (typically 1–1.5R given mean reversion's naturally tighter payoffs).

**Persona and prompt behavior.** Persona: **a disciplined short-term quant/prop trader who distrusts narrative and only trusts statistics that have passed a regime check.** The system prompt should instruct the agent to: (1) always state the ADX reading and whether the mean-reversion gate is active or suppressed *before* stating the score; (2) explicitly flag when it is fading a level with no trend-filter confirmation ("this is a lower-confidence fade — trend filter unavailable/failed"); (3) never use language implying certainty ("will bounce") — require probabilistic framing ("elevated probability of reversion toward X given historical band behavior, not a guarantee"); (4) refuse to raise its own score above what the deterministic sub-score formulas produce, even if the rationale "feels" more convincing — the LLM's role is explanation and gating-sanity-check, not score inflation.

---

## 2. TrendMomentumAgent

**What it examines.** Whether the instrument is in a genuine, strengthening directional trend worth riding, using lagging-but-robust trend/momentum tools, cross-sectionally ranked against a peer universe where relevant.

**Inputs / data needed.**
- Daily OHLCV, 252+ day history (same sources as above).
- For cross-sectional momentum: trailing 252-day total return of the ticker's relevant broad-market proxy — SPY for US equities, a TOPIX-tracking ETF (`1306.T`) for JP equities (**correction, verified live Aug 2026**: `^TOPX` is not a valid Yahoo Finance symbol and returns a 404; `1306.T` is a real, liquid TOPIX ETF that works), BTC (or a cap-weighted top-20 crypto index) for altcoins — computable locally from the same cached OHLCV already pulled for the proxy ticker, no extra API. (Superseded design note: an earlier draft percentile-ranked against a small hand-picked watchlist of 20–50 tickers; that inflated conviction because a ticker could rank highly against a self-selected small list while being mediocre against the actual market — see indicator #4 below.)
- ATR(14) for normalization (shared utility, computed once per ticker per day and cached for reuse by other agents).

**Concrete indicators and thresholds.**
1. **MA crossover**: 50/200-day SMA (position-trade horizon) and 9/21-day EMA (swing horizon). Long bias when fast > slow.
2. **ADX/DMI(14)**: `ADX<20` = no trend (suppress this agent, hand off to MeanReversionAgent); `20–25` = ambiguous, halve confidence; `>25` = trending, full weight; `>40` = strong trend, `>50` = exceptional (cap score magnitude — very high ADX often precedes exhaustion, don't let the score chase to +1.0 without a countervailing check). Per the corrected `trend_confidence` formula below, this "full weight" language is literal, not approximate: `trend_confidence(25)=1.0`, `trend_confidence(30)=1.0`, `trend_confidence(40)=1.0`.
3. **Donchian breakout**: 20-day high/low channel (55-day for JP/crypto position-trade variant), exit channel N/2.
4. **Cross-sectional momentum**: trailing 252-day return of the ticker minus the trailing 252-day return of its asset-class broad-market proxy (SPY for US, TOPIX for JP, BTC/cap-weighted crypto index for altcoins) — i.e. excess return vs. the actual broad market, not a percentile rank within a small hand-picked watchlist (which would silently inflate conviction by benchmarking against a self-selected list rather than the market) — optionally with a 10–20% pullback-from-high filter to avoid buying extended names.
5. **MACD(12,26,9)**: histogram sign and zero-line side as a lagging confirmation layer, not a primary trigger.

**Signal score computation.**
```
ma_score      = clip((fastMA - slowMA) / ATR14, -1, 1)
donchian_score= clip((price - prior_N_high) / ATR14, -1, 1)   # 0 if inside channel
excess_return_252d = ticker_252d_return - proxy_252d_return   # proxy = SPY (US) / TOPIX (JP) / BTC or a cap-weighted crypto index (alts)
xsect_score   = clip(excess_return_252d / 0.5, -1, 1)          # ±50pts excess return vs. the broad-market proxy maps to full score
macd_score    = clip(histogram / ATR14, -1, 1) + (0.1 if MACD>0 else -0.1)
trend_confidence = clip((ADX-15)/10, 0, 1)   # trend_confidence(20)=0.5, (25)=1.0, (30)=1.0, (40)=1.0 — see §1 for the identical corrected formula
signal_score = trend_confidence * weighted_avg(ma_score:0.3, donchian_score:0.25, xsect_score:0.3, macd_score:0.15)
```
**Confidence** = `trend_confidence`, reduced by 0.2 if the pullback filter is violated (buying a name already extended >20% above its recent breakout with no pullback), reduced if the broad-market proxy is a poor structural fit for the ticker (e.g., benchmarking a small-cap value name against a growth-heavy broad index) — flag this as a known limitation in the rationale rather than treating proxy-relative momentum as a perfect peer-relative measure.

**Output specifics.**
- `suggested_holding_period`: 3–10 trading days for the 9/21 EMA / Donchian-20 swing variant; several weeks to months for the 50/200 SMA / cross-sectional variant — the agent must declare which sub-model dominated the score and set the holding period accordingly, not use one blanket default.
- `stop_loss`: `atr_multiple`, 2–3×ATR(14) trailing stop (Turtle-style), tightened to 1.5×ATR for the faster EMA variant.
- `profit_target`: for breakout/Donchian trades, no fixed target — trail the stop and let winners run (consistent with the research's note that Donchian systems are ~35% win-rate/2:1+ payoff, asymmetric by design); for the MA-crossover swing variant, express as 2–3R.

**Persona and prompt behavior.** Persona: **a systematic trend-follower in the CTA/Turtle tradition — comfortable with a low win rate if the payoff structure is right, allergic to prediction, focused on "what is the trend doing right now," not "what will it do."** Prompt instructions: (1) must explicitly state current ADX and whether the trend gate is open; (2) must never claim to predict trend continuation — only characterize current strength/direction; (3) must flag "chasing" risk explicitly whenever price is >15–20% above the relevant breakout level with no pullback; (4) rationale string must cite the specific MA spread or Donchian level and current ADX value, not vague language like "strong momentum."

---

## 3. SeasonalityAgent

**What it examines.** Historically-documented, statistically-tested calendar/event-based return patterns (day-of-week, turn-of-month, PEAD, sector intramonth cycles for equities; halving-cycle phase, monthly seasonality, options-expiry windows for crypto) — treated explicitly as a *thin, contrarian-caution-worthy tilt*, never a standalone trigger, per the research's own skepticism.

**Inputs / data needed.**
- Locally-computed historical daily-return database per ticker/index (built from the same cached OHLCV as other agents), minimum 8–10 years for equities, 6–8 years for crypto (per the crypto-factors research's explicit caution against going further back given market-structure change).
- Calendar metadata: trading-day-of-month, day-of-week, current position relative to quarter/month end.
- Earnings-date calendar (yfinance per-ticker `get_earnings_dates()` primary; Alpha Vantage `EARNINGS_CALENDAR` as a sparing 25/day-budget cross-check) for PEAD.
- Consensus EPS estimate vs. actual (for SUE) where obtainable free — else fall back to price-based earnings-day abnormal-return proxy.
- Deribit/CoinGlass public expiry calendar for crypto options-expiry flags.

**Concrete indicators and thresholds.**
1. **Turn-of-month**: flag last trading day of month through 3rd trading day of next month as a historically positive-return window for equity indices; compute `score = clip((bucket_mean/bucket_stdev)*confidence_weight, -1, 1)`, `confidence_weight→0` if `n<30` samples or `|t|<2`.
2. **PEAD**: compute SUE at each earnings release; percentile-rank; `score = clip(SUE_pct*2-1,-1,1) * time_decay(days_since_earnings)`, decay tapering to ~0 by day 90; hold window 60–90 calendar days with a re-weighting bump in the 3-day window around the *next* earnings date.
3. **Sector intramonth cycle** (equities, if a sector-ETF universe is tracked): apply Quantpedia's 3-leg monthly cycle sign to the sector's 252-day-return percentile rank; treat as a very low-weight input given the published Sharpe (~0.55) even before real-world costs on a $650 account.
4. **Crypto monthly seasonality**: 6–8 year historical mean return by calendar month, z-scored, capped at ±5 points contribution; explicit rolling out-of-sample check — auto-downweight if realized returns diverge from the historical pattern over the trailing 12 months.
5. **Halving-cycle phase tag** (BTC only): label-only (`early-post-halving/mid-cycle/late-cycle`), capped at ±0.05 contribution to `signal_score`, always flagged low-confidence.
6. **Expiry/turn-of-quarter volatility flag**: does not set a directional score — instead sets a `volatility_caution` flag consumed by `RiskManagerAgent` to widen stops / reduce size.

**Signal score computation.** All sub-scores are small by design (bounded individually well inside ±0.3) and averaged; the agent should almost never emit `|signal_score| > 0.3` on seasonality alone — a system-enforced cap.

**Confidence** = function of sample size and t-stat/significance per bucket; hard-capped at 0.5 maximum (seasonality is explicitly a tilt, never a high-confidence agent in this design) — enforce this cap in code, not just via prompting.

**Output specifics.**
- `suggested_holding_period`: matches the specific effect being flagged — 3–4 calendar days (turn-of-month), 60–90 calendar days (PEAD), 1–4 trading days (sector monthly-cycle leg).
- `stop_loss` / `profit_target`: seasonality alone does not set levels — it supplies the score/holding-period tilt while stop/target defaults to a `percent` placeholder (e.g., 5%) that the supervisor overrides using whichever co-firing directional agent (Trend/MeanReversion) provides structure. Document this explicitly in rationale.

**Persona and prompt behavior.** Persona: **a statistically rigorous quant researcher who is deliberately skeptical of pattern-matching and actively looks for reasons to distrust the pattern (small n, contested EMH literature, arbitraged-away effects).** Prompt must require the agent to state sample size and significance test result inline in the rationale (e.g., "n=13 Septembers, no formal significance test — low-confidence pattern") and to explicitly say when a pattern is "consistent with recent academic critique that this effect may be shrinking/arbitraged" per the source material. The agent should never phrase seasonality output as "X historically happens" without the caveat that market participants have already priced in well-known calendar effects.

---

## 4. ShortSqueezeAgent

**What it examines.** Whether an equity (or, in a much more degraded/limited form, a crypto perp via CryptoDerivativesAgent instead) exhibits the structural preconditions for a short/gamma squeeze — a one-sided **risk/opportunity flag**, not a standard directional score, per the source research's explicit framing.

**Inputs / data needed.**
- FINRA biweekly Equity Short Interest (free, ~2-week-lagged by design) — primary US source.
- ChartExchange free SI%/borrow-fee screeners (spot-check/manual cross-reference; not a stable bulk API).
- Free daily short-*volume* files (Nasdaq Trader/NYSE Reg SHO) as a noisier, higher-frequency proxy between FINRA settlement dates.
- Options chain via yfinance (`Ticker.option_chain()`) for volume/open-interest ratio as the unusual-options/gamma overlay (no free bulk unusual-activity API exists — must be self-computed).
- Average daily volume (from OHLCV) for days-to-cover.
- **JP equities**: only via J-Quants **Standard tier ($22/mo, not free)** for structured margin/short-selling-ratio data, or free-but-scrape-only JPX daily short-selling-value-by-industry and weekly outstanding-margin-by-issue pages (aggregate/industry-level, not always per-ticker) — this agent must run in a visibly **degraded mode** for JP tickers and say so in its rationale, since no free per-ticker JP short-interest feed exists.

**Concrete indicators and thresholds** (from the research's composite):
- `si_score = clip(SI%_of_float/40, 0, 1)`; working thresholds: SI% >15–20% elevated, >30–40% high-risk.
- `dtc_score = clip(days_to_cover/10, 0, 1)`; >5 days elevated, >10 days high.
- `fee_score = clip(borrow_fee_rate/50, 0, 1)`, weighting the **5–10 day rate of change** at least as heavily as the level; >5–10% elevated, >50% extreme.
- `util_score = clip((utilization-80)/20, 0, 1)`; >90–95% = pool nearly exhausted.
- `options_score = 1 if any strike shows volume/OI ≥ 1.25 (Barchart methodology) with bullish call skew (trades at/above ask) and min liquidity (vol>500, OI>100), else 0`.
- RVOL cross-check from VolatilityVolumeAgent (RVOL ≥5× materially raises confidence that a squeeze setup is actively triggering, not just latent).

**Signal score computation.**
```
squeeze_score = weighted_avg(si_score:0.3, dtc_score:0.2, fee_score:0.25, util_score:0.15, options_score:0.10)
signal_score  = squeeze_score            # one-sided, rescaled to [0, +1] — never negative
```
This agent **never outputs a negative score** — it is a bullish-tail-risk/opportunity flag layered on top of directional agents, exactly as specified in the research; the supervisor must not treat a low squeeze_score as bearish, only as "no squeeze risk/opportunity present."

**Confidence** = high when built from fresh borrow-fee/utilization data (rare on free tier), degraded to ≤0.4 when relying solely on lagged FINRA SI% (the realistic free-tier default), and explicitly floored near 0.2 for JP tickers given the data gap above.

**Output specifics.**
- `suggested_holding_period`: hours to a few days — squeezes are violent and hard to time; the agent should default to a short window (1–3 trading days) and explicitly warn against holding through a squeeze unwind.
- `stop_loss`: tight, `percent`-based (e.g., 8–12%) given the binary/violent nature — do not use a wide ATR multiple here, since squeezes can have abnormally elevated ATR that would justify an unreasonably wide stop.
- `profit_target`: staged/partial (e.g., trim 50% at +30%, trail remainder) rather than a single level, noted in rationale.

**Persona and prompt behavior.** Persona: **a risk-aware special-situations trader who treats squeezes as high-variance lottery-like setups worth flagging but not sizing heavily** — explicitly not a hype-driven "meme stock" persona. Prompt must instruct the agent to: (1) always state data freshness (e.g., "SI% as of FINRA settlement date 2026-08-15, 11 days stale") since this is structurally lagged; (2) never phrase this as a standalone buy signal — rationale must include the phrase-pattern "structural squeeze risk present; combine with a directional catalyst before acting"; (3) explicitly warn when the JP-degraded mode is active; (4) cap enthusiasm — the system prompt should include a hard instruction like "even at squeeze_score=1.0, do not imply certainty of a squeeze occurring or its timing."

---

## 5. VolatilityVolumeAgent

**What it examines.** Whether current volatility and volume are expanding relative to their own baseline — used primarily as a **confidence multiplier / confirmation layer** on other agents' directional calls, and secondarily to set ATR-based stop/target distances used across the whole system.

**Inputs / data needed.**
- Daily/intraday OHLCV for True Range and ATR(14) computation (shared utility cached for reuse by every other agent — this agent should be the canonical ATR provider system-wide to avoid redundant computation).
- 60-day ATR history for the ATR/ATR-average expansion ratio.
- Volume history (20–30 day trailing average, time-of-day-adjusted for intraday RVOL).
- Volume-by-price data (constructed locally from intraday bars where available) for Point-of-Control estimation.

**Concrete indicators and thresholds.**
1. **ATR expansion**: `vol_expansion_score = clip((ATR14/ATR14_avg_60d)-1, -1, 1)`; practitioner rule-of-thumb trigger: current ATR > 1.5× its own 20-day average = meaningful expansion.
2. **RVOL**: `rvol_score = clip((RVOL-1)/4, 0, 1)`; RVOL≥2× = elevated, ≥5× = "something is happening" tier.
3. **Point of Control / volume profile**: `distance_score = clip((price-POC)/ATR14, -1, 1)` as a reversion-to-POC or breakout-confirmation input (stronger breakout confirmation when price decisively clears a low-volume node vs. a high-volume node).
4. **Bollinger Bandwidth** (shared with MeanReversionAgent) for squeeze detection ahead of an expansion.

**Signal score computation.** This agent is unusual: its own `signal_score` is **direction-agnostic magnitude, signed by same-bar price-return direction** — its primary system role is the multiplier it exports for other agents:
```
vol_conf_multiplier = 0.5 + 0.5 * avg(vol_expansion_score, rvol_score)   # ∈ [0.5, 1.0] typically, can exceed on strong readings
signal_score = sign(recent_price_return) * clip(avg(|vol_expansion_score|, rvol_score), 0, 1)
```
The supervisor is expected to consume `vol_conf_multiplier` directly (exported in `sub_scores`) to scale TrendMomentumAgent/MeanReversionAgent/ShortSqueezeAgent scores, per the research's composite gating design: `final_score = directional_score × vol_conf_multiplier`.

**Confidence** = high when RVOL and ATR-expansion agree in direction/magnitude; reduced when volume is confirming but ATR is flat (or vice versa), since disagreement between the two volume/volatility proxies suggests a less clean signal.

**Output specifics.**
- `suggested_holding_period`: not this agent's primary output — pass-through/advisory only; if forced to state one, breakout-confirmation implies a few days to several weeks depending on which other agent it's confirming.
- `stop_loss`/`profit_target`: this agent is the **canonical source** of `atr_multiple` values consumed by every other agent (`stop = entry ± 1.5–3×ATR14` per §1 of the risk research) — it should export the raw ATR14 value in `sub_scores` for reuse, not just a normalized score.

**Persona and prompt behavior.** Persona: **a market-microstructure/volume specialist, deliberately "boring" and mechanical — this agent should almost never editorialize about direction**, only about participation/conviction. Prompt instructions: (1) explicitly state that volume/volatility alone never implies direction — always phrase output as "confirms" or "does not confirm" another signal, never as an independent buy/sell case; (2) always export the raw ATR14 number so downstream agents/humans can sanity-check stop distances; (3) flag illiquid/thin-volume conditions plainly (e.g., "average volume below X — wide slippage risk on a $650 account") since this is exactly the friction the risk research flags as disproportionately damaging to a small account.

---

## 6. CryptoOnChainAgent

**What it examines.** On-chain holder behavior and network fundamentals for BTC/ETH and major alts — crypto-only, no equity equivalent.

**Inputs / data needed.**
- **Correction (Aug 2026): Glassnode's free API tier has been discontinued** — its pricing page now shows only paid "Advanced"/"Professional" plans, so it is no longer a usable $0 source for MVRV/SOPR/whale-cohort data (see `data & alerting` §1). **CryptoQuant's free dashboard** is the primary fallback for MVRV/SOPR/exchange-flow *viewing* (documented as freemium, though its API/scrape terms need re-verification before automating — it 403'd automated crawling during this research pass). Where no free, automatable source for a pre-computed metric exists, the agent must either (a) read the value manually off CryptoQuant's dashboard on a reduced cadence and accept that as a `data_quality_flag=partial` input, or (b) approximate it via custom SQL over **Dune Analytics'** free query API (computing realized-cap-derived metrics from raw on-chain data) — a real engineering lift, not an out-of-the-box metric, and lower-fidelity than Glassnode's discontinued feed. Do not assume any free, ready-made MVRV/SOPR API exists; this agent runs on structurally weaker data access than the others and should say so in its rationale.
- Tokenomist.ai free dashboard / DefiLlama `/unlocks` for vesting-cliff schedules (altcoins only; N/A for BTC/ETH).
- StakingRewards.com for nominal staking APY (PoS assets only).
- CoinGecko free API (100 calls/min, 10k credits/mo) for circulating/max supply, inflation rate.

**Concrete indicators and thresholds.**
1. **MVRV**: percentile-rank of `ln(MVRV)` against trailing 4-year distribution. Bands: `<1` = capitulation (bullish-contrarian, +90–100 composite equivalent); `1–2` accumulation (+60–80); `2–3.5` neutral (40–60); `>3.5–7` overheated (10–30, caution).
2. **SOPR**: 7/14-day MA relative to 1.0. In uptrend: bouncing off 1.0 from above = bullish continuation (+15–20); breaking decisively below 1.0 = trend-change warning (−20). In downtrend: rejecting 1.0 from below = bearish confirmation; holding above 1.0 = reversal signal (+).
3. **Exchange net flows**: z-score of daily net flow vs trailing 90-day distribution; `z>+1.5` outflow spike = +10 to +20; `z>+1.5` inflow spike = −10 to −20. Explicitly discount for known confounders (OTC/exchange-to-exchange transfers, entity relabeling).
4. **Whale cohort balance** (≥1,000 BTC or top-1% non-exchange addresses): % change over 7/30 days; rising whale + falling retail balance = accumulation divergence (+10–15); reverse = distribution (−10–15). Weighted lower than SOPR/flows due to classification risk.
5. **Active addresses**: divergence-only filter (price new highs + addresses declining = −5 to −10 flag; both rising = +5 confirmation). Low base weight — noisy.
6. **Unlock schedule** (altcoins only): forward 30-day unlock size as % of circulating supply and multiple of 30-day ADV. `<1% supply & <5× ADV` = negligible; `2–5% or >20× ADV` = −10 to −20; `>5% single cliff` = −20 to −30 (avoid new longs into date).
7. **Real staking yield** (PoS only): `nominal_APY − inflation_rate`; positive & rising staking ratio = +5; negative = −5 to −10 structural headwind.

**Signal score computation.**
```
onchain_raw = weighted_avg(mvrv_pctile_score:0.30, sopr_score:0.20, flow_score:0.20,
                            whale_score:0.15, addr_divergence:0.05, unlock_penalty:0.10)
signal_score = clip(onchain_raw / 100, -1, 1)   # rescale composite 0-100-style sub-score to -1..+1
```

**Confidence** = reduced when relying on free-tier data with known gaps (entity relabeling, thin exchange-flow history), explicitly capped ≤0.6 given the research's own note that on-chain signals are widely followed/arbitraged.

**Output specifics.**
- `suggested_holding_period`: weeks to months (on-chain metrics are slow-moving structural signals, not day-trade triggers) — 14–60 days typical.
- `stop_loss`: `percent`, wider than equities (e.g., 15–25%) reflecting crypto's baseline volatility; tightened around a known unlock-cliff date.
- `profit_target`: `percent`/structure — e.g., prior MVRV-band transition point (target exit near MVRV entering the "overheated" 3.5–7 band if entry was in the "accumulation" 1–2 band).

**Persona and prompt behavior.** Persona: **an on-chain analyst who treats every metric as noisy and crowd-followed — explicitly skeptical, always naming the confounders** (entity mislabeling, OTC flow, small-sample whale cohorts). Prompt requirement: state data-source freshness/tier explicitly (e.g., "CryptoQuant dashboard read, MVRV as of...", or "Dune-approximated, lower fidelity than a dedicated on-chain vendor") and always caveat that "on-chain signals are widely dashboarded and may already be priced in by faster participants" per the source research's explicit framing — this framing should appear near-verbatim in the persona's system prompt as a standing instruction, not left to chance per-response.

---

## 7. CryptoDerivativesAgent

**What it examines.** Positioning/leverage stress in the crypto derivatives market (funding, open interest, liquidation clusters, options skew) — the crypto analog of `ShortSqueezeAgent`, but bidirectional (can flag crowded-long or crowded-short).

**Inputs / data needed.**
- Exchange public REST endpoints (Binance/Bybit/OKX funding-rate endpoints — free, keyless) as the primary programmatic source.
- CoinGlass free dashboard (manual/scrape view only — its programmatic API is paid-only from $29/mo) for aggregated funding, OI, liquidation heatmap, Altcoin Season Index.
- Laevitas free tier (≤1 week history, 8 charts/page) or Deribit public options chain for 25-delta skew/DVOL (verify current Deribit URL each cycle — prior 404s observed).

**Concrete indicators and thresholds.**
1. **Funding rate**: annualize (`rate × periods/day × 365`), z-score vs trailing 90-day history. Sustained `>+30–50%` annualized = crowded-long warning (contrarian bearish/squeeze-risk flag, −10 to −20); deeply negative sustained = crowded-short (contrarian bullish, +10 to +20); near 0 = neutral. Always paired with OI (below) — high funding + falling OI = crowd already unwinding (decaying signal), high funding + rising OI = stronger warning.
2. **Open interest 2×2** vs price direction: (price↑,OI↑)=trend confirmation (+10); (price↑,OI↓)=weak short-covering rally (0 to +5); (price↓,OI↑)=fresh-short buildup/capitulation setup (flag, no fixed sign — watch for squeeze); (price↓,OI↓)=deleveraging, often marks local bottoms once flattening (+5 contrarian once stabilized).
3. **Liquidation heatmap proximity**: identify nearest large cluster above/below current price; **risk-overlay only** (feeds `RiskManagerAgent`'s stop-tightening logic) — not a standalone directional score, per the research's explicit caution that retail can't out-speed a cascade.
4. **25-delta options skew**: z-score vs 60-day trailing distribution. `z>+1.5` (put-heavy/fear) = contrarian-bullish tilt (+10); `z<-1.5` (call-heavy/greed) = contrarian caution (−10). Treated as low-weight/slow-calibrating on free-tier data given the short history window.

**Signal score computation.**
```
funding_score = -clip(annualized_funding_z/2, -1, 1)     # contrarian sign
oi_score      = f(price_dir, OI_dir)  # per 2x2 table above, mapped to [-1,1]
skew_score    = -clip(skew_z/1.5, -1, 1)                 # contrarian sign
signal_score  = weighted_avg(funding_score:0.4, oi_score:0.35, skew_score:0.25)
```
Liquidation-cluster proximity does **not** enter `signal_score`; it is exported in `sub_scores.liquidation_caution` for the RiskManagerAgent to consume directly.

**Confidence** = high for funding/OI (mechanically grounded, per the research's own confidence table), low initially for skew (thin free history), reduced overall when CoinGlass data had to be manually/scrape-viewed rather than pulled programmatically (data-freshness flag).

**Output specifics.**
- `suggested_holding_period`: days (derivatives positioning mean-reverts faster than on-chain fundamentals) — 2–10 days typical.
- `stop_loss`: tightened automatically (via `RiskManagerAgent`) when price is within ~2–3% of a major liquidation cluster, per the research's explicit recommendation.
- `profit_target`: `percent`, informed by typical funding-rate mean-reversion time (a few days to ~2 weeks based on historical decay).

**Persona and prompt behavior.** Persona: **a derivatives/positioning specialist, contrarian by default (fades crowding), highly mechanical about leverage risk.** Prompt must instruct: (1) always report both funding *level* and its *rate of change*, since the research stresses the crowd can already be unwinding by the time a level looks extreme; (2) explicitly flag liquidation-cluster proximity as a risk-sizing note for the RiskManagerAgent, not a trade trigger; (3) never suggest trying to "trade the cascade" directly — the system prompt should include an explicit prohibition matching the research's own caution that this requires speed a manual trader on free-tier data does not have.

---

## 8. NewsSentimentAgent

**What it examines.** Same-day/recent news, filings, and headline sentiment that could explain or foreshadow price action — a "why is this moving" and "is something about to move it" layer, explicitly framed as noisy/low-precision.

**Inputs / data needed.**
- SEC EDGAR real-time Atom feed (`getcurrent` filings, 8-K focus) + `companyfacts`/`submissions` JSON — free, keyless, real-time, 10 req/sec cap, requires descriptive `User-Agent`. Primary structured US trigger source.
- TDnet (JP disclosure portal) — free but HTML-scrape-only, no RSS; must be polled and parsed, flagged as added engineering cost.
- Finnhub free-tier `general_news`/`company_news` (verify current rate cap per API key at build time).
- RSS: CoinDesk, CoinTelegraph (crypto); MarketWatch, CNBC, Yahoo Finance, Seeking Alpha, Investing.com (US); Japan Times, NHK business, Yahoo Japan News business (JP, general-interest only — no TSE-filing-specific free feed exists).
- Alpha Vantage `NEWS_SENTIMENT` as an occasional (25/day-budget) cross-check with pre-computed sentiment scores.
- Local FinBERT (`ProsusAI/finbert`, CPU-friendly) as first-pass bulk headline triage; local small LLM via Ollama (Gemma3/Qwen/Phi-4-mini) for second-pass, context-aware scoring of the subset that clears a relevance/magnitude threshold.
- **Explicitly excluded**: X/Twitter (no free tier at all in 2026 — pure pay-per-credit).

**Concrete indicators and thresholds.**
1. **Filing-trigger flag**: any new 8-K (US) / TDnet disclosure (JP) / major protocol governance or exchange-listing announcement (crypto) within the last 24–48 hours sets `event_flag=true` and forces a `volatility_caution` sub-flag regardless of sentiment polarity.
2. **Headline sentiment score**: FinBERT softmax → `(positive - negative)` per headline, averaged across all headlines in the last 24–72 hours mentioning the ticker, weighted by outlet-relevance (structured news > general blog RSS).
3. **Sentiment magnitude vs. volume of coverage**: a single strongly negative headline from a low-relevance source should not move the score as much as a moderate negative sentiment across 5+ independent structured sources — require a minimum coverage count (e.g., ≥3 independent sources) before allowing `|signal_score|>0.4` on sentiment alone.
4. **Recency decay**: `time_decay = exp(-hours_since/24)` applied to each headline's contribution — news from 3 days ago should barely move today's score.

**Signal score computation.**
```
headline_score = Σ(sentiment_i * relevance_i * time_decay_i) / Σ(relevance_i * time_decay_i)
signal_score = clip(headline_score, -1, 1)
# event_flag forces confidence down and routes a caution note to RiskManagerAgent regardless of sign
```

**Confidence** = function of coverage count and source diversity (low with 1 source, higher with 3+ independent structured sources), explicitly capped ≤0.5 for JP tickers given the free-feed gap, and reduced whenever the underlying signal is FinBERT-only (no LLM second pass) since FinBERT is a fast triage tool, not a nuanced reader.

**Output specifics.**
- `suggested_holding_period`: hours to a few days for headline-driven moves; N/A (defer to other agents) for pure background sentiment with no active event.
- `stop_loss`/`profit_target`: this agent typically defers structural levels to Trend/MeanReversion agents, but widens the *recommended* stop distance (`volatility_caution` flag) around confirmed material 8-K/TDnet events or known large derivatives-expiry windows.

**Persona and prompt behavior.** Persona: **a skeptical news desk analyst, not a headline-chasing retail trader** — explicitly trained to distinguish "market-moving primary-source event" (filing, protocol change, exchange action) from "noise/opinion piece/recycled headline." Prompt instructions: (1) always cite the specific source and timestamp for any headline driving the score; (2) explicitly flag low-source-diversity situations as low-confidence ("single source, unconfirmed — treat with caution"); (3) never let sentiment alone justify a large score — enforce the coverage-count gate above in the prompt as a hard rule, not a suggestion; (4) explicitly note when X/Twitter-style social buzz is *not* available to this agent (design gap, stated plainly rather than silently omitted) so the human operator knows the blind spot.

---

## 9. RiskManagerAgent

**What it examines.** Not a new directional opinion — a **hedge-fund-style risk gate** over the other agents' collective recommendation: position sizing, account-level exposure, correlation, structural constraints (TSE lot sizes, PDT/margin rules), and a veto power over the final call. This is the agent most directly shaped by the risk-validation research's sober conclusions about small-account trading.

**Inputs / data needed.**
- Current account equity, currency, and asset-class breakdown (local state, not an external API).
- ATR14 (from `VolatilityVolumeAgent`) for volatility-adjusted sizing.
- Liquidation-cluster proximity (from `CryptoDerivativesAgent`, crypto only).
- Broker/exchange structural constraints: TSE 100-share (`tangen kabu`) unit size and mini-kabu/odd-lot availability (JP); US FINRA Rule 4210 intraday-margin (IML) framework post-PDT-rule-elimination (June 4, 2026) and ~$2,000 margin-equity floor, T+1 cash-account settlement constraints if trading a non-margin account; no analogous account minimum for crypto.
- Correlation/exposure across currently open positions (local portfolio state) to avoid stacking correlated risk (e.g., multiple long-BTC-correlated alts simultaneously).
- Upcoming known volatility events (earnings dates, options-expiry calendars, unlock cliffs) surfaced by SeasonalityAgent/CryptoOnChainAgent/NewsSentimentAgent.
- **JP tickers only**: previous close and the TSE published price-limit-tier table, used to compute today's daily price-limit band (see rule 9 below).
- `MarketRegimeAgent`'s `position_size_ceiling_multiplier` (system-wide, per asset class — see §11) as an additional input to rules 3 and 6 below.

**Concrete rules and thresholds.**
1. **Per-trade risk cap**: fixed-fractional, **0.5–1% of current equity** per trade as the default ceiling for this account size (per the research's explicit recommendation to push toward the low end for a small, concentrated account) — at ¥100,000/$650, that is roughly $3.25–$6.50 risked per trade; the agent must compute and display this dollar figure, not just a percentage.
2. **Kelly overlay**: if a per-strategy historical edge estimate exists (from validated backtests, not raw agent confidence), compute fractional Kelly (≤¼-Kelly) as an *upper bound check* on position size, but never let it override the fixed-fractional ceiling above — full or high-fraction Kelly on noisy retail edge estimates is explicitly flagged in the research as a blow-up risk.
3. **Volatility-adjusted sizing**: `position_size = (equity × risk_pct) / (entry - stop)`, where `(entry-stop)` is set via ATR (1.5–3×ATR14 depending on holding-period agent) — ensures a volatile crypto asset and a calm large-cap contribute comparable portfolio risk. This per-ticker result must then be multiplied by `MarketRegimeAgent`'s asset-class `position_size_ceiling_multiplier` (§11) as an additional, stacking input — the ambient market-wide regime check applies on top of, not instead of, this per-ticker ATR-based logic.
4. **Structural feasibility check** (hard gate, not a score): for JP tickers, verify a full 100-share unit is affordable within the risk-adjusted position size; if not, either require a mini-kabu/odd-lot broker feature or **veto the trade as structurally infeasible** for this account size — do not silently downsize past what the broker actually offers.
5. **Regulatory/account-type check**: confirm current account type (cash vs. margin) and, for US equities, whether the ~$2,000 margin floor and IML framework (post-June 2026) are satisfied if day-trading; default to cash-account/T+1-settlement assumptions unless explicitly configured otherwise.
6. **Correlation cap**: reduce aggregate suggested size if ≥2 concurrently open/proposed positions are highly correlated (e.g., two large-cap alts both dominated by BTC-beta) — cap combined correlated exposure at a multiple (e.g., 1.5×) of the single-trade risk cap. As with rule 3, apply `MarketRegimeAgent`'s `position_size_ceiling_multiplier` (§11) on top of this correlated-exposure cap, not instead of it — e.g., if the ambient crypto regime breaker is active, the combined correlated-crypto-exposure cap itself is also halved, not just each individual position.
7. **Drawdown circuit breaker**: if trailing realized account drawdown exceeds a configured threshold (e.g., −15% from peak), automatically halve the per-trade risk cap and require higher aggregate confidence before approving new entries — operationalizing the research's point that a human will abandon a system after a large drawdown regardless of long-run Sharpe, so the system should itself de-risk before that happens.
8. **Veto rule**: if this agent's own `conviction` on "avoid/reduce" exceeds **0.7**, it overrides the numeric weighted average from the other agents and forces the final recommendation to HOLD/no-new-exposure regardless of how bullish other agents are — mirroring TradingAgents' "Portfolio Manager approves or rejects" gate rather than a naive average.
9. **JP daily price-limit band check** (JP tickers only): compute today's TSE price-limit band (previous close ± the limit-move amount for that price's published TSE price-tier table) before finalizing any stop/target for a JP ticker — a stock that hits its limit can freeze into 特別気配 (special quotation) with stop/limit orders unable to fill at or beyond the band. (a) If a proposed `stop_loss.price_level` (from any specialist agent) falls outside today's computed band, set `stop_loss_override` to widen it back inside the band and flag it `may_not_be_executable: true` in the rationale — a stop placed beyond the band cannot realistically fill until the band resets the next session. (b) If the current price is within a configurable percent of either band edge (default e.g. 3%), set `jp_limit_band_flag = "limit_lock_risk"`, reduce `conviction`/approved size (e.g., halve the proposed position size), and note the limit-lock risk explicitly in the JP-ticker alert template — a locked-limit day is a realistic, JP-specific tail risk for a concentrated ¥100,000 account.

**Signal score computation.** `RiskManagerAgent` does not vote directionally; instead it outputs:
```json
{
  "risk_signal": "approve | reduce_size | veto",
  "conviction": 0.0,
  "max_position_size_pct_equity": 0.0,
  "max_position_size_currency": 0.0,
  "stop_loss_override": {...},   // may tighten but never loosen another agent's stop
  "structural_feasibility": "ok | infeasible_lot_size | infeasible_margin_floor",
  "jp_limit_band_flag": "none | approaching_limit | limit_lock_risk | stop_outside_band",  // JP tickers only, per rule 9; null for non-JP asset classes
  "veto_reason": "string or null"
}
```

**Confidence** here represents confidence in the *risk assessment itself* (data completeness on account state/constraints), not in a market call. Per the canonical propagation rule in §2.4: if any input agent's data for this ticker is `unavailable` (primary+fallback both circuit-broken), that agent abstains (`signal_score=0, confidence=0`) and `RiskManagerAgent` must itself force `risk_signal="veto"`/HOLD for that ticker rather than proceeding on a partial picture; if an input agent's data is merely `stale` (age > 2×TTL), that agent's own confidence is already capped ≤0.3 upstream, which should organically pull down the blended confidence the supervisor computes without `RiskManagerAgent` needing separate stale-data logic of its own.

**Persona and prompt behavior.** Persona: **a conservative hedge-fund-style Chief Risk Officer — capital preservation first, explicitly the "adult in the room" whose job is to say no.** The system prompt should be markedly different in tone from every other agent: (1) instructed to actively look for reasons to reduce size or veto, not to find reasons to approve; (2) required to state the exact dollar risk amount and structural constraints in plain numbers every time (e.g., "risking $5.20 of $650, 0.8% of equity — within policy"); (3) explicitly forbidden from being swayed by high conviction/confidence scores from directional agents — required to state "I evaluate risk independent of how confident the other agents are"; (4) required to reference the account's small size and the research's own sober framing explicitly when relevant (e.g., "this account cannot absorb more than N consecutive losses at current sizing without material drawdown — treat that as a hard constraint, not a suggestion").

---

## 10. PortfolioSupervisorAgent

**What it examines.** The final reconciliation step: takes every applicable specialist agent's structured output for a given ticker and produces one auditable buy/sell/hold call with a confidence score, following the aggregation approach validated in the orchestration research (weighted scoring + disagreement penalty + risk-manager veto, computed deterministically in code rather than via an opaque LLM "vote").

**Inputs.** The full set of structured JSON outputs from whichever agents are applicable to the ticker's asset class (per the matrix in §0), plus the ticker's current price/ATR for level translation.

### 10.1 Weighting scheme

Base weights are asset-class-specific and **normalized to sum to 1.0 across only the agents active for that asset class** (i.e., crypto tickers redistribute the weight that would have gone to `ShortSqueezeAgent` into `CryptoDerivativesAgent`/`CryptoOnChainAgent`, and vice versa for equities):

| Agent | US Equity weight | JP Equity weight | Crypto weight |
|---|---|---|---|
| TrendMomentumAgent | 0.28 | 0.28 | 0.22 |
| MeanReversionAgent | 0.18 | 0.18 | 0.15 |
| ShortSqueezeAgent | 0.14 | 0.08 (degraded data) | — |
| SeasonalityAgent | 0.08 | 0.08 | 0.05 |
| NewsSentimentAgent | 0.22 | 0.18 (thinner JP feed) | 0.15 |
| CryptoOnChainAgent | — | — | 0.20 |
| CryptoDerivativesAgent | — | — | 0.23 |
| *VolatilityVolumeAgent* | multiplier (0.10 of blend weight, see below) | same | same |
| *RiskManagerAgent* | veto/gate, not a weighted vote | same | same |

`VolatilityVolumeAgent` contributes **10% as a direct weighted vote** (its own signed `signal_score`) *and* separately supplies the `vol_conf_multiplier` applied to the whole blend — it is deliberately double-counted in a bounded way because the source research treats it as both a minor directional input and the primary confidence amplifier for everyone else.

### 10.2 Aggregation algorithm (deterministic, not another LLM call)

```
# Step 1 — confidence-weighted directional blend
weighted_sum = Σ_i (base_weight_i * signal_score_i * confidence_i)
weight_norm  = Σ_i (base_weight_i * confidence_i)
blended_score = weighted_sum / weight_norm         # ∈ [-1, 1]

# Step 2 — volatility/volume confirmation gate
blended_score *= vol_conf_multiplier               # ∈ [0.5, ~1.2] typically

# Step 3 — dispersion / disagreement penalty
scores = [signal_score_i for i where confidence_i > 0.3]
dispersion = stdev(scores)
disagreement_penalty = clip(dispersion / 0.7, 0, 0.6)   # up to a 60% confidence haircut

overall_confidence = weight_norm_avg_confidence * (1 - disagreement_penalty) * data_quality_multiplier

# Step 4 — special-case flags (additive, not blended)
if ShortSqueezeAgent.signal_score > 0.6:
    tag "elevated squeeze risk" — do not let it flip a bearish blended_score bullish;
    only used to widen upside-tail awareness / tighten stops
if any agent has event_flag/volatility_caution:
    widen recommended stop distance by +25-50%, note in rationale

# Step 5 — RiskManagerAgent veto (hard override)
if RiskManagerAgent.risk_signal == "veto":
    final_call = "HOLD"
    final_confidence = RiskManagerAgent.conviction
    override_reason = RiskManagerAgent.veto_reason
elif RiskManagerAgent.risk_signal == "reduce_size":
    final_call = decision_from_blended_score(blended_score, overall_confidence)
    apply RiskManagerAgent.max_position_size_* as a hard cap regardless of blended_score strength
else:
    final_call = decision_from_blended_score(blended_score, overall_confidence)
```

### 10.3 Decision bands

```
if final_call != "HOLD" (veto path):  use veto outcome
elif blended_score >= +0.35 and overall_confidence >= 0.50:  BUY
elif blended_score <= -0.35 and overall_confidence >= 0.50:  SELL / AVOID-or-EXIT
elif |blended_score| >= 0.20 and overall_confidence >= 0.50: WATCH (sub-threshold directional lean, no action — surfaced to human as a lower-urgency alert)
else: HOLD / NO ACTION
```
Thresholds (0.35, 0.50, 0.20) are deliberately conservative and should be tunable config, not hardcoded — the risk-validation research's own finding that a sophisticated 2026 statistical-robustness score showed **no significant forward relationship with future performance** in a real out-of-sample test is a strong argument for keeping decision bands conservative and adjustable rather than over-trusting any single blended number.

### 10.4 Reconciling specific conflicts (concrete examples)

- **TrendMomentumAgent bullish + MeanReversionAgent bearish** (a genuinely common conflict, since one agent is designed to fire when the other is suppressed): check `regime_gate_applied` on both — if MeanReversionAgent's gate shows it was already suppressed by high ADX (i.e., its score is near-zero *because* of the trend gate, not a competing live signal), this is not a real conflict and should not trigger the dispersion penalty; if both are firing at meaningful magnitude with opposite signs (rare, but possible at a regime inflection), the dispersion penalty above naturally drags confidence down, which is the correct behavior — the supervisor should not attempt to adjudicate which technical view is "right," only reflect the genuine uncertainty.
- **CryptoOnChainAgent bullish (accumulation) + CryptoDerivativesAgent bearish (crowded long/high funding)**: this is a textbook "strong hands accumulating while weak-handed leveraged longs get flushed" pattern — do not simply average; the supervisor's rationale-generation step should surface both explicitly ("on-chain accumulation supportive medium-term, but derivatives positioning suggests near-term downside/squeeze-of-longs risk") and this specific pattern should widen the suggested holding period (favor the on-chain agent's longer horizon) while adopting the derivatives agent's tighter stop-loss recommendation — i.e., reconcile time horizons explicitly rather than just blending scores.
- **NewsSentimentAgent strongly negative (single low-diversity source) + everything else neutral/positive**: the coverage-count confidence gate in §8 already caps this agent's own confidence low in that scenario, which correctly limits its blend impact — the supervisor should still surface the headline in the rationale ("unconfirmed negative report — monitor, not yet acted on") without letting a single low-confidence source override multiple higher-confidence structural signals.
- **ShortSqueezeAgent high + TrendMomentumAgent bearish**: per §4, squeeze score never goes negative and never overrides a bearish trend call on its own — it is surfaced as a tail-risk *warning to short-sellers/against shorting*, not a buy override; the final call in this case can legitimately still be SELL/AVOID (or HOLD if shorting isn't in scope) with an explicit caveat in rationale: "trend bearish, but elevated squeeze-risk metrics present — avoid initiating/adding to a short here even though the directional score is negative."

### 10.5 Output schema addition (Supervisor-specific)

```json
{
  "agent_name": "PortfolioSupervisorAgent",
  "asset_class": "...",
  "ticker": "...",
  "final_call": "BUY | SELL | HOLD | WATCH",
  "blended_score": 0.0,
  "overall_confidence": 0.0,
  "component_breakdown": [
    {"agent": "TrendMomentumAgent", "score": 0.0, "confidence": 0.0, "weight": 0.0, "contribution": 0.0}
    /* ... one row per contributing agent, for full auditability */
  ],
  "disagreement_penalty_applied": 0.0,
  "risk_manager_override": "none | reduce_size | veto",
  "suggested_holding_period": {...},
  "stop_loss": {...},
  "profit_target": {...},
  "max_position_size_currency": 0.0,
  "rationale": "string synthesizing agreements/conflicts across agents, <=500 chars",
  "human_action_required": true
}
```
`human_action_required` is always `true` and no downstream tool ever consumes this to place an order — consistent with the project's non-negotiable "never auto-execute" requirement, this output is architecturally a terminal artifact (written to a log/dashboard and optionally pushed via a Telegram/Discord alert), not an input to any execution capability that doesn't exist in this system's toolset.

**Persona and prompt behavior.** Persona: **a portfolio manager/CIO synthesizing specialist analyst reports for a single decision-maker (the human operator) who must be able to trust and audit the "why."** Prompt instructions: (1) never present the blended score as more certain than its `overall_confidence` warrants — explicitly translate low-confidence bands into hedged language ("weak, low-confidence lean, not a strong call"); (2) always name which agents agreed and which conflicted, and why, using the reconciliation logic in §10.4 rather than glossing over disagreement; (3) always restate the RiskManagerAgent's position sizing/veto explicitly and prominently — this is the one piece of output the persona must never soften or bury; (4) close every output with an explicit reminder that this is analysis for manual decision-making, not an instruction, and that the project's own research indicates most systematic small-account retail trading underperforms after costs — the persona should carry forward the system-wide realistic-skepticism framing rather than resetting to hype-neutral or, worse, promotional language at the final and most human-visible step of the pipeline.

---

## 11. MarketRegimeAgent

**What it examines.** Ambient, market-*wide* volatility/stress regime — a lightweight, non-directional gate/modifier (like `RiskManagerAgent`, never a directional voter) that reduces position-size ceilings system-wide *before* losses accrue, distinct from `RiskManagerAgent` rule 7's drawdown circuit breaker (§9), which only de-risks *after* this specific account has already drawn down ≥15%. This closes the gap the risk research flags: a VIX-equivalent spike, a broad crypto-wide deleveraging event, or a JP market-wide stress day should cut sizing ahead of realized losses, not just after them.

**Inputs / data needed.**
- **US equities**: a free VIX-equivalent level (CBOE VIX, typically obtainable free alongside other index quotes) or, if unavailable, a locally-computed realized-volatility proxy (trailing 20-day annualized realized vol of SPY) — either way, benchmarked against its own trailing 1-year daily history for percentile computation.
- **JP equities**: a Nikkei-linked volatility index if freely obtainable, else a locally-computed trailing 20-day annualized realized-volatility proxy on TOPIX/Nikkei 225 daily returns, benchmarked against its own trailing 1-year distribution.
- **Crypto**: trailing 20-day annualized realized volatility of BTC (or a cap-weighted basket), benchmarked against its own trailing 1-year distribution — computed locally from OHLCV already cached by other agents, no extra API needed.
- Config-driven percentile threshold (default e.g. the 85th percentile of the trailing-1-year distribution) and the resulting de-risking multiplier (default e.g. 0.5), both tunable, not hardcoded.

**Concrete rule.**
```
vol_percentile = percentile_rank(current_trailing_20d_realized_vol, trailing_1yr_distribution)   # per asset class, using the proxy above
if vol_percentile >= config.regime_breaker_percentile (default 85):
    position_size_ceiling_multiplier = config.regime_breaker_multiplier (default 0.5)
else:
    position_size_ceiling_multiplier = 1.0
```
This multiplier is computed and emitted **per asset class**, not globally — a US-equity vol spike does not automatically halve crypto sizing, and vice versa, since these regimes are sometimes but not always correlated.

**Output.**
```json
{
  "agent_name": "MarketRegimeAgent",
  "asset_class": "us_equity | jp_equity | crypto",
  "as_of_timestamp": "ISO8601 UTC",
  "vol_percentile": 0.0,
  "regime_breaker_active": false,
  "position_size_ceiling_multiplier": 1.0,
  "data_quality_flag": "ok | stale | partial | unavailable"
}
```
This is intentionally not the shared per-ticker envelope in §0 — there is no `ticker`, `signal_score`, `confidence`, `stop_loss`, or `profit_target`, because this agent runs once per asset class per cycle, not once per ticker.

**Mandatory consumption by RiskManagerAgent.** Per §9 rules 3 and 6, `RiskManagerAgent`'s volatility-adjusted sizing (rule 3) and correlation cap (rule 6) must each multiply their existing per-ticker outputs by this agent's `position_size_ceiling_multiplier` for the relevant asset class — as an *additional* input stacked on top of, not a replacement for, their existing per-ticker ATR-based and correlation-based logic.

**Confidence / data quality.** Since this agent never scores a ticker, its "confidence" is really confidence in the vol-percentile computation itself. Per the canonical propagation rule in §2.4 (data & alerting), cap it ≤0.3 if the realized-vol history feeding the percentile is `stale`; if the underlying data is `unavailable`, fail safe by defaulting `position_size_ceiling_multiplier` to the breaker-active value (e.g. 0.5) rather than 1.0 — i.e. default toward de-risking, not toward business-as-usual, when this agent's own inputs are degraded.

**Persona and prompt behavior.** This is a mechanical percentile computation, not an opinion — no LLM reasoning is strictly required to produce the multiplier itself. If an LLM wrapper is used to phrase the rationale, its persona should mirror `RiskManagerAgent`'s tone: **terse, mechanical, and explicitly indifferent to any directional agent's optimism.** Its only job is to state the current percentile, whether the breaker is active, and the resulting multiplier, e.g.: "US-equity realized vol at the 91st percentile of its trailing 1-year range — regime breaker ACTIVE, position-size ceilings halved system-wide regardless of per-ticker conviction."