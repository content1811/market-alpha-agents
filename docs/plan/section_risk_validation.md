# Risk Management, Validation & Realistic Expectations

## 1. Stop-Loss Formulas

All stops are computed from **volatility (ATR)** first, with **chart structure** and a **hard percentage backstop** as overlays. Never use a bare fixed-percentage stop as the primary method — it ignores the fact that a ¥100,000 account will hold very different instruments (a calm large-cap vs. a volatile altcoin) with very different natural noise bands.

**Primary formula — ATR-multiple stop:**
```
stop_distance = k × ATR(14)
long_stop_price  = entry_price − stop_distance
short_stop_price = entry_price + stop_distance
```
- `k = 1.5–2.0` for day/intraday trades (tight, since holding is hours).
- `k = 2.0–3.0` for swing trades held 2–10 days (wider, to avoid noise stop-outs).
- Sanity-check every ATR stop against the nearest structural level (prior swing low/high, 20/50-period MA, prior consolidation range). If the ATR-derived stop sits *inside* an obvious support/resistance level (i.e., it would be hit by normal noise before the thesis is actually invalidated), widen the stop to just beyond that structural level instead — then re-check that the resulting stop distance doesn't imply a position size below the exchange/broker minimum lot (see §2).
- **Hard backstop:** regardless of ATR/structure math, no single trade's stop distance may imply a loss greater than **2% of total account equity** (~¥2,000 on a ¥100,000 base). If the ATR/structure stop would risk more than that, either shrink position size to compensate or skip the trade — never widen the stop to "make the position size work."
- For crypto (24/7, higher vol, no PDT-style constraints): use the same ATR framework but recompute ATR on a shorter lookback (e.g., ATR(14) on 1h or 4h bars for day-trade setups) since daily-bar ATR understates intraday whipsaw in majors like BTC/ETH.
- **JP-specific caveat — stops are not always fillable on TSE names:** every formula above assumes the stop price can actually be hit and executed. TSE stocks trade within a daily price-limit band around the previous close; a stock that reaches the limit can freeze into a 特別気配 (special quotation) state where stop and limit orders beyond the band simply cannot fill, regardless of how well-placed the ATR/structure math was. Do not treat a JP ATR/structure stop as guaranteed-fillable the way a US/crypto stop usually is — see `RiskManagerAgent` rule 9 (agents §9, TSE daily price-limit-band / special-quotation check), which flags stops that fall outside the band as "may not be executable" and reduces size or flags "limit-lock risk" for JP tickers trading near their limit.

## 2. Position-Sizing Formula

**Base method — fixed-fractional risk:**
```
risk_amount   = equity × risk_pct
position_size = risk_amount / stop_distance_in_price_terms
```
- `risk_pct` default: **0.5–1.0%** of current equity per trade (¥500–¥1,000 on ¥100,000), not the 1–2% often quoted for larger accounts. At this account size, capping risk lower buys more trades' worth of survivable losses before ruin, which matters more than maximizing per-trade edge capture.
- Recompute `equity` after every closed trade (not a fixed ¥100,000 forever) so sizing compounds down during drawdowns and up during winning streaks — this is what keeps fixed-fractional sizing from blowing up the account in a losing streak.

**Kelly as an upper-bound sanity check, not a sizing formula to follow directly:**
```
f* = (p/l) − (q/g)   [Kelly fraction; p=win prob, q=1−p, g=avg win %, l=avg loss %]
recommended_fraction = min(0.25 × f*, risk_pct_ceiling)
```
Because the system's estimates of `p`, `g`, `l` come from a small, noisy sample (see §5), never size at full Kelly. Use **¼-Kelly at most**, and treat it purely as an upper bound that the fixed-fractional 0.5–1.0% rule should almost always be tighter than. If ¼-Kelly ever computes to *less* than the fixed-fractional amount, defer to the smaller (more conservative) number.

**Concrete friction check before the formula even applies (this is the part generic sizing advice skips):**
- **US equities:** FINRA adopted new intraday-margin standards that replace the legacy day-trading margin framework in full — including the day-trade-count trigger for "pattern day trader" designation and the $25,000 PDT minimum-equity requirement — via Regulatory Notice 26-10 (SR-FINRA-2025-017, SEC-approved April 14, 2026; https://www.finra.org/rules-guidance/notices/26-10), effective **June 4, 2026**, with an **18-month firm phase-in period running through October 20, 2027**. Because that phase-in window is still open, individual brokers may not yet have finished implementing the new intraday-margin monitoring and could still apply legacy PDT-style restrictions (or their own stricter house minimums) in the interim — a ¥100,000 (~$650) account should **not** be assumed automatically free of the old $25k-style day-trading block just because the rule's effective date has passed. Confirm your specific broker's current implementation status and house rules before assuming 4+ day trades/week are unrestricted. Independent of this margin-rule change, a cash (non-margin) account remains subject to T+1 settled-funds constraints, and broker minimums/fees still matter. With $650, prefer sub-$20 liquid names so a single 0.5–1% risk allocation (~$3–6.50) still buys a meaningful number of shares; fractional-share brokers help here.
- **Japan equities (TSE):** the standard trading unit is 100 shares (tangen kabu). A single unit of a ¥3,000 stock costs ¥300,000 — three times the entire account. **A ¥100,000 account cannot trade full lots in most large-cap TSE names.** The position-sizing formula must first filter the tradable universe to (a) low-priced TSE stocks where 100 shares fits the budget, or (b) broker single-share/mini-kabu (odd-lot) programs (SBI, Rakuten, Monex), which carry wider spreads/less liquidity that should be added as extra slippage buffer in the stop-distance calc. Do not let the sizing formula silently assume fractional TSE shares are available — check unit availability per ticker before computing `position_size`.
- **Crypto:** no unit-size barrier, but factor exchange minimum order size and taker fees (commonly 0.05–0.1%+ per side) directly into `risk_amount`, since round-trip fees on a ¥500 risk trade are a much larger proportional drag than on a larger account.

## 3. Holding-Period & Profit-Target Rules

Use the **R-multiple framework** (Van Tharp): define `1R = risk_amount` from §2. Every target and every logged outcome is expressed in R, not raw currency, so performance is comparable across tickers/asset classes despite the account's tiny absolute size.

```
target_price (long) = entry_price + (reward_multiple × stop_distance)
```
- Default planned reward:risk = **2:1 to 3:1** (target = 2R–3R) for mean-reversion/swing setups; trend-following/breakout setups (Donchian, MA-crossover) should use a **trailing ATR stop instead of a fixed target** once price reaches +1R, letting winners run — consistent with the research finding that breakout systems are structurally low-win-rate/high-payoff (~35% win rate at 2:1 in Turtle-style systems) and should not be optimized for win rate.
- **Hard time-stop:** exit any trade that hits neither target nor stop within a pre-declared holding-period ceiling tied to the strategy type:
  - Mean-reversion (RSI-2, Bollinger fade, VWAP fade): 1–5 trading days (or same-session for intraday VWAP).
  - Trend/momentum (MA crossover, Donchian breakout): 2–6 weeks, trailing-stop managed.
  - PEAD-style earnings drift: 60–90 calendar days with a partial re-weight around the next earnings date.
  - Crypto swing setups: 1–10 days given higher volatility compresses the same R-multiple move into less time.
- Log the *planned* target/stop/holding-period alongside the *actual* exit reason (target hit / stop hit / time-stop / discretionary override) — this triplet is what the feedback loop in §5 needs to diagnose whether targets are systematically too tight/loose.

## 4. Backtesting & Walk-Forward Validation Plan

**Tooling (local, free, actively maintained as of Aug 2026 — avoid `backtrader`, which has had no commits since Aug 2024):**
- **vectorbt** (Apache-2.0 + Commons Clause, actively released, v1.1.0 Jul 2026) for fast vectorized signal research across the equity/crypto universe.
- **bt** or **zipline-reloaded** for portfolio-level backtests with realistic commission/slippage models layered in.
- **freqtrade** for the crypto leg specifically — it ships built-in backtesting, hyperopt, and a dry-run/paper mode in one actively maintained tool.
- **quantstats** for Sharpe/Sortino/drawdown tear-sheet reporting across all of the above.

**Train/test split approach:**
- **Walk-forward, rolling window** (not anchored) given both equities and especially crypto are subject to regime change — a rolling in-sample window prevents stale early-history data from propping up parameter estimates that no longer apply.
- Concretely: e.g., 12-month in-sample fit → 3-month out-of-sample test → roll forward 3 months → repeat across the full available history. Only the concatenated out-of-sample segments count toward any performance claim; in-sample-optimized numbers are never reported as "the strategy's performance."
- Build the price universe **point-in-time** (historical index/exchange membership, not "today's constituents applied to past dates") to avoid survivorship bias — this matters more for crypto small-caps, where a large fraction of tokens from any past period have since delisted or gone to zero.
- Deliberately include at least one clearly **high-volatility regime period** (a sharp equity/crypto drawdown or vol-spike episode) inside the walk-forward out-of-sample windows — this is the only way to confirm, before going live, that the system-wide `MarketRegimeAgent` position-size-ceiling multiplier (agents section, trailing realized-vol-percentile breaker) actually engages and de-risks correctly, rather than discovering in real time that its thresholds were never once exercised in backtest.

**Metrics that must pass before a strategy is "trusted" enough to move to paper trading:**
1. **Deflated Sharpe Ratio (DSR)** positive and statistically significant after correcting for the number of parameter/indicator combinations the agent system actually tried (log every variant tested — this count is the direct input to the DSR correction).
2. **Probability of Backtest Overfitting (PBO)** below an explicit threshold (e.g., <0.5, ideally lower) via combinatorial cross-validation.
3. **Minimum Track Record Length (MinTRL)** satisfied — i.e., enough out-of-sample history exists for the claimed Sharpe to be statistically distinguishable from zero at a reasonable confidence level; if MinTRL says you need more history than you have, the honest answer is "not yet validated," not "assume it's fine."
4. **Profit factor** > 1.5 out-of-sample (treat anything >3–4 as a red flag for a leak/overfit, not a reason for excitement).
5. **Max drawdown** and **Calmar ratio** reported and eyeballed against what a human could actually tolerate without abandoning the system mid-drawdown — this is more decision-relevant than Sharpe for a manually-executed tool.
6. Costs/slippage/fees modeled explicitly at realistic (not zero) values in every backtest, including the TSE odd-lot spread penalty and crypto taker fees noted in §2.

Even after all of the above, hold the result with real skepticism: a 2026 paper on backtest-robustness scoring (arXiv:2608.23808, the "MinervaScore") found its composite DSR/PBO/SPA/MinTRL robustness grade had **no significant relationship with actual future performance** (Spearman ρ=0.013) across a population of real submitted backtests. Passing this checklist reduces — it does not eliminate — the odds of deploying a lucky-looking, not-actually-skillful strategy.

## 5. Mandatory Paper-Trading Gate

**No strategy or agent-generated signal touches real capital until it has cleared a paper-trading (forward-test, no execution capability) period, full stop.**

- Minimum duration: **8–12 weeks of continuous forward-testing**, or a minimum of ~30 completed simulated trades per strategy, whichever is longer — short of that, results are dominated by sample-size noise, not edge.
- Run paper trades against **live (or minimally-delayed free-tier) data**, not the backtest engine, so real data gaps, feed outages, and the free-tier lag/staleness issues documented for J-Quants Free (12-week lag), Alpha Vantage (25 calls/day), and yfinance (unofficial, breaks periodically) actually show up and get handled before they can silently corrupt a live signal.
- Apply the **same friction assumptions as real trading**: simulated slippage (e.g., fill at next-bar open + a spread penalty, not the signal-bar close), simulated TSE odd-lot spread widening, simulated crypto taker fees.
- Compare paper-trading out-of-sample metrics (§4) against the original backtest's out-of-sample metrics. A large gap (e.g., paper Sharpe << backtest Sharpe) is itself a signal that the backtest missed real-world friction and the strategy needs re-work before any capital gate is opened.
- Architecturally, this gate is reinforced by never building an order-execution tool into the agent system at all (see orchestration design) — the paper-trading requirement isn't just a policy switch that could be misconfigured, it's the *only* path that exists until the human operator manually decides to act on a logged recommendation.

## 6. Fine-Tuning / Feedback Loop Design

**Per-recommendation logging (every signal, every agent, every day):**
Log a structured record for every recommendation the system produces, minimally:
```
{date, symbol, asset_class, strategy_id, agent_signals: {analyst, trader, risk_manager},
 aggregated_score, confidence, entry_price, stop_price, target_price,
 planned_holding_period, position_size, risk_amount_R,
 actual_outcome: {exit_price, exit_date, exit_reason, realized_R, realized_pnl},
 human_action: {followed | modified | ignored}}
```
Store this in a local SQLite file (or the orchestration framework's persistence store, e.g. LangGraph's checkpointer/store) keyed by `symbol/date`, so it survives across daily runs and can be queried by the agents themselves before making a new call on a ticker they've flagged before.

**Per-agent performance scorecards:**
- Compute, per specialist agent (financial-analyst, quant/technical-trader, risk-manager) and per strategy module (RSI-2, MA-crossover, squeeze-score, etc.), a rolling scorecard: hit rate, average realized R, Sharpe/Sortino of that agent's/strategy's signals alone, and **calibration** (did a stated 0.8 conviction actually correspond to an ~80% success rate, or is the agent systematically over/under-confident?).
- Track **agreement vs. outcome**: when agents disagreed (e.g., analyst bullish, risk-manager cautious) did the lower-confidence aggregated outcome actually underperform high-agreement calls, validating the "disagreement lowers confidence" aggregation rule? If not, recalibrate the weighting.

**Periodic recalibration cadence:**
- **Weekly:** update rolling per-strategy hit-rate/R-multiple stats; flag any strategy whose live/paper performance has diverged sharply from its backtest (possible regime change or implementation bug).
- **Monthly:** recompute aggregation weights (per-agent weight, risk-manager veto threshold) based on the trailing 1–3 months of scorecards — treat this as a slow, deliberate adjustment, not a per-day auto-tune, to avoid recalibrating the system on noise. This same monthly cadence is the operational anchor for the monthly digest alert (`data & alerting` section, Alerting Design) that restates realized CAGR/Sharpe-to-date next to the 50%+ aspiration — see §7 below — so that caveat recurs as a live artifact every month rather than living only as a static one-time document.
- **Quarterly:** re-run the full walk-forward validation (§4) on each strategy with the latest data window; retire or down-weight any strategy whose out-of-sample DSR/PBO has degraded, rather than letting it keep running on the strength of an old validation pass.
- All recalibration changes themselves get logged (old weight → new weight, and the data that justified the change) so the human operator can audit why the system's behavior shifted over time — this auditability is the whole point of using a deterministic aggregation function rather than an opaque LLM vote for the weighting step.

## 7. Honest Assessment of the 50%+ Return Aspiration

**This should be treated as an unlikely stretch outcome, not a plan to design around.** Concrete reasons:

- **Full-population evidence on retail day trading is discouraging.** A study covering essentially all individual day traders in the Brazilian futures market found **97% of those who persisted beyond 300 days lost money**, with only ~1.1% earning more than minimum wage from trading (Chague, De-Losso & Giovannetti, SSRN 3423101). Long-running Taiwan exchange research reaches similar conclusions. These are survivorship-bias-free, full-population datasets — not cherry-picked anecdotes.
- **A well-validated systematic retail strategy that survives years typically targets Sharpe ~1–2 and CAGR in the ~15–40%/year range after realistic costs** — not 50%+ over a short window. Any backtest claiming Sharpe >3 or 50%+ in months should be presumed an overfitting/survivorship/small-sample artifact until it survives the DSR/PBO/walk-forward/paper-trading gauntlet above, and even then the base rate for it being real edge rather than luck is not high (§4's MinervaScore finding).
- **Small account size makes this harder, not easier:** fixed costs (spread, commission, TSE odd-lot penalties, crypto taker fees) consume a disproportionate share of a ¥500–¥1,000 per-trade risk budget; the number of trades achievable in any "near-term" window is small enough that realized outcomes will be dominated by variance/luck, not converged edge; and a normal losing streak (which happens even to good strategies) is a large percentage hit to ¥100,000, creating real psychological pressure toward position-size creep and revenge trading — the single most common way small accounts actually get destroyed.
- **Known failure modes specific to this system's design:** overfitting from an agent that can try many indicator/parameter combinations (countered only partially by DSR/PBO); slippage from free-tier, delayed, or gapped data feeding a manually-executed trade; regime change (a strategy fit to 2023–2026 conditions failing when volatility/correlation structure shifts, which rolling walk-forward testing probes for but cannot fully insure against); and survivorship bias in any backtest universe that isn't built point-in-time.
- **Recommended framing for the project owner:** define success as *capital preservation plus demonstrated statistically-significant edge* (passing §4's checklist, then §5's paper-trading gate, then a sustained live track record), with the 50%+ figure explicitly labeled a low-probability tail outcome. The median outcome for an unvalidated small systematic account is flat-to-negative; the left tail (losing a large fraction of the ¥100,000) is at least as plausible as the right tail the 50% target describes.

## 8. Japan Tax/Compliance Notes (Retail Trader, Non-Advice)

*This tool produces analysis and suggestions only; it is not licensed financial/investment advice and never auto-executes trades. Nothing below is tax advice — confirm current rules with the NTA or a qualified Japanese tax professional before filing.*

- **Capital gains on listed Japanese stocks and crypto are taxed differently.** Listed equity trading profits in a standard "specified account with withholding" (源泉徴収あり特定口座) are typically taxed at a flat ~20.315% (national + local + special reconstruction surtax) and can be handled with simplified/no separate filing; crypto gains, by contrast, are generally treated as **miscellaneous income (雑所得)** taxed at progressive rates (up to ~45% national plus ~10% local, so a combined marginal rate that can exceed the equities flat rate substantially at higher income levels) — do not assume crypto and equity gains are taxed the same way when the system logs/estimates "after-tax" expected outcomes.
- **US equities held/traded from Japan** raise cross-border considerations (US withholding on dividends, foreign tax credit treatment, FX gain/loss on JPY↔USD conversion counted separately from the security's own gain/loss) — flag this complexity to the operator explicitly rather than having the system silently assume a single domestic tax treatment across all three asset classes.
- **Record-keeping:** because the system logs every recommendation and outcome (§5) in R-multiples/JPY, that same log is a natural source for reconciling actual realized gains/losses for tax filing — but the log should capture actual fill prices/dates/fees, not just planned ones, since Japanese tax filing requires realized transaction records, not model estimates.
- **This is a decision-support tool only:** it must never represent its output as licensed investment advice (a regulated activity in Japan under the Financial Instruments and Exchange Act for anyone providing investment advice to third parties for compensation), must remain single-operator/personal-use only, and — per the J-Quants data-license terms specifically — any data pulled from J-Quants may not be redistributed raw, and using it to continuously provide investment-analysis output to third parties would exceed J-Quants' "personal use" allowance. Keep the system's outputs and any underlying licensed data strictly internal to the single operator unless separately re-licensed.