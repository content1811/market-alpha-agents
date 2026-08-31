# market-alpha-agents — User Manual

This is the day-to-day operating manual: how to run the system, read its output, and
act on it safely. For engineering status (what's built, what's tested, what's still
missing) see [README.md](README.md). For the original research/design, see `docs/plan/`.

## 1. What this is, and isn't

market-alpha-agents is a **local, read-only research tool**. Every day it can:
- Pull real market data for your watchlist (US equities, JP equities, crypto).
- Run it through several specialist models (mean reversion, trend, seasonality,
  short-squeeze, volatility, on-chain, derivatives, news sentiment).
- Blend those into one scored call per ticker — `BUY` / `SELL` / `HOLD` / `WATCH` —
  with a suggested holding period, stop-loss, and profit target, plus a written
  rationale.

It does **not**, and never will, place a trade. There is no execution capability
anywhere in this codebase, by design. Every recommendation is meant to be read by a
human (you) and acted on manually — or not at all. Nothing sends you an alert without
you explicitly approving that specific recommendation first (§4 below).

**Also important:** as of today, no signal in this system has actually cleared the
statistical validation checklist (Deflated Sharpe / PBO / MinTRL / profit factor —
see §8) well enough to be "trusted." Several show no measurable edge; one that does
(`TrendMomentumAgent`) hasn't yet been run through the full graduation gate with a
real multi-variant sweep. Treat every `BUY`/`SELL` call today as a structured, well-
reasoned *opinion* from a system still being validated, not a proven strategy.

## 2. One-time setup

```
cd market-alpha-agents
source .venv/bin/activate
python scripts/validate_config.py   # confirms config.yaml + watchlists are well-formed
python scripts/check_setup.py       # shows which optional integrations are configured
```

`check_setup.py` is your dashboard for external accounts. It always exits 0 — every
integration it lists except the LLM gateway is optional, and the system runs fully
without them (yfinance/CCXT/SEC EDGAR/Alternative.me need no key at all). Where it
says `MISSING`, it gives you the exact URL to register. Nothing in this system can
register those accounts for you — J-Quants, EDINET, Telegram, Discord, and your email
provider all require your own identity/verification, so this is a manual, one-time
chore per integration you want.

Copy real values into `.env` (already gitignored — never gets committed) as you get
them; re-run `check_setup.py` any time to see your progress.

## 3. The daily workflow

This is the actual loop, every time you use the system:

```
python scripts/run_daily_scan.py
```

This scans every enabled watchlist ticker (`config/watchlists/*.yaml`) across every
enabled asset class (`config/config.yaml`'s `asset_classes` block), and for each one:

1. Fetches live data.
2. Runs the full specialist pipeline.
3. Saves the recommendation to `storage/recommendations.db`.
4. **Pauses** — it does not send anything anywhere by itself.
5. Prints a one-line summary per ticker, and a `PENDING APPROVAL [...]` line for any
   ticker that crossed a real trigger (composite score, squeeze-risk, stop/target
   proximity) — those are the ones actually worth your attention that day.

You'll see output like:

```
[us_equity] regime multiplier: 1.0
    PENDING APPROVAL [composite_score_threshold]: blended_score=0.71 -- run `python ui/review_cli.py approve|reject NVDA-2026-08-31`
  NVDA BUY (+0.71)
  AAPL HOLD (-0.14)
...
```

A ticker with no `PENDING APPROVAL` line still got a full recommendation saved — it
just didn't cross a threshold worth flagging that day. You can still review/approve
it manually if you want (see §4); most days, most tickers will just be `HOLD`.

## 4. The approval gate — how alerts actually get sent

**No alert (Telegram, Discord, or desktop) is ever sent except through this step.**
This is the single most important safety property of the whole system: a recommendation
existing in the database is not the same as it being surfaced to you as actionable.

For each `recommendation_id` printed above (format: `TICKER-YYYY-MM-DD`):

```
python ui/review_cli.py approve NVDA-2026-08-31
```

This prints the recommendation's call, score, confidence, and rationale, resumes the
underlying pipeline (which was paused waiting for exactly this decision), records your
decision, and — only on `approve` — sends the alert (Telegram + Discord if configured,
plus a desktop notification always). `reject` records the decision and sends nothing.

```
python ui/review_cli.py reject NVDA-2026-08-31
```

You can only decide a given recommendation once — trying again returns an error
rather than silently resuming a second time.

## 5. Reading a recommendation

- **`final_call`**: `BUY` / `SELL` / `HOLD` / `WATCH`. `HOLD` fires whenever
  `overall_confidence` is below the configured minimum (default 0.50) — a low-confidence
  lean is treated as no call at all, regardless of how the raw score looks.
- **`blended_score`** (-1..+1): the confidence-weighted blend of every applicable
  specialist's score for that asset class. Not all 8 specialists apply to every asset
  class (e.g. `ShortSqueezeAgent` never fires for crypto; `CryptoOnChainAgent`/
  `CryptoDerivativesAgent` only fire for crypto) — see the component breakdown for
  which ones actually voted.
- **`overall_confidence`** (0..1): confidence-weighted average confidence across
  active agents, reduced by a disagreement penalty when specialists conflict, and
  further reduced if any input data was stale/degraded that day.
- **`component_breakdown`**: per-agent score/confidence/weight/contribution — this is
  where you see *why* the blend landed where it did, and whether it was a
  broad-agreement call or a close, conflicted one.
- **`risk_manager_override`**: `none` / `reduce_size` / `veto`. A `veto` forces `HOLD`
  regardless of the blended score — e.g. a JP ticker where a full 100-share lot doesn't
  fit your configured account equity, or a drawdown circuit-breaker having tripped.
  This is never softened in the rationale, by design.
- **`stop_loss` / `profit_target` / `suggested_holding_period`**: the levels/timeframe
  from whichever specialist contributed most to the blend, tightened (never loosened)
  by any `RiskManagerAgent` override, and widened if `VolatilityVolumeAgent` flagged
  elevated volatility that day.
- **`rationale`**: LLM-written, but only ever describing already-computed numbers —
  no agent's language model output can change a score or confidence value; the JSON
  schema every agent call is constrained to has no field for it to do so.

## 6. Logging outcomes (after you've actually traded, or decided not to)

Once you've manually acted (or deliberately not acted) on an **approved**
recommendation, log what happened — this is what eventually lets the system's own
`backtesting/robustness.py` be re-run against your real results, not just backtests:

```
python ui/review_cli.py log-outcome NVDA 2026-08-31 \
  --actual-entry-price 875.20 --actual-exit-price 910.00 \
  --exit-date 2026-09-05 --exit-reason target_hit \
  --human-action followed --realized-pnl 34.80
```

`--exit-reason` must be one of `target_hit` / `stop_hit` / `time_stop` / `discretionary`.
`--human-action` must be one of `followed` / `modified` / `ignored`. You can only log an
outcome against a recommendation you actually approved — trying to log one against a
rejected or never-decided recommendation is refused.

To find approved recommendations you might have forgotten to log:

```
python ui/review_cli.py pending-outcomes --older-than 90
```

Lists every approved recommendation older than 90 days with no outcome logged yet.

## 7. Configuring your watchlist and risk parameters

- **Watchlists**: `config/watchlists/us_equities.yaml`, `jp_equities.yaml`,
  `crypto.yaml`. Each is a flat `symbols:` list; equities can carry a per-symbol
  `overrides:` block (e.g. a wider stop for a known-volatile name). Keep this small
  while you're still building confidence in the system — a bigger universe just
  multiplies API-budget pressure before anything's proven out.
- **Account equity**: `config/config.yaml`'s `risk_management.account_equity_jpy` —
  every position-sizing/lot-feasibility calculation is anchored to this number.
  Change it to match your real account size.
- **Risk parameters**: same block — `max_risk_per_trade_pct`, `kelly_fraction_cap`,
  `max_position_pct_of_equity`, `drawdown_circuit_breaker_pct`, etc.
- **Strategy tunables**: `config/strategies/*.yaml` (RSI-2 thresholds, Bollinger `k`,
  ADX cutoffs, squeeze sub-weights, ...) — retuning these is a config change, not a
  code change, specifically so it stays auditable.
- **On-chain addresses**: `config/config.yaml`'s `crypto_onchain.exchange_addresses`/
  `whale_addresses` default to empty. `CryptoOnChainAgent`'s flow/whale sub-scores stay
  excluded (not guessed) until you add real ETH addresses you've independently
  verified — this system ships none of its own.

## 8. Backtesting a signal before trusting it

Every signal's pure math lives in `signals/`. To sanity-check one against real
history before leaning on its live calls:

```python
from data.connectors.us_equities_yfinance import YFinanceSource
from signals.ta.mean_reversion import mean_reversion_signal_series
from backtesting.run_backtest import walk_forward_backtest

source = YFinanceSource()
bars = source.get_ohlcv_range("AAPL", "2018-01-01", "2026-08-27")
import pandas as pd
df = pd.DataFrame([b.model_dump() for b in bars]).set_index("ts_utc")
signal = mean_reversion_signal_series(df["high"], df["low"], df["close"])
result = walk_forward_backtest(df["close"], signal)
print(result.sharpe, result.deflated_sharpe, result.profit_factor)
```

For a real pass/fail verdict against the actual validation checklist (not just raw
numbers), feed the result into `backtesting/graduation_gate.py`'s `evaluate_strategy()`
— see `scripts/mean_reversion_pbo_sweep.py` for a full worked example including a real
multi-variant parameter sweep (required for a trustworthy PBO number, not the
single-variant shortcut above).

## 9. Scheduling it (optional, and worth thinking about before you do)

`scheduler/jobs.py` wires a real APScheduler job to `config.yaml`'s cron string
(default `0 30 16 * * MON-FRI`, i.e. 16:30 JST weekdays):

```
python scheduler/jobs.py     # foreground; Ctrl-C to stop
```

For unattended running, `scheduler/com.marketalpha.dailyrun.plist` is a ready-to-use
launchd template — copy it to `~/Library/LaunchAgents/` and `launchctl load` it.
**It is not installed by default, on purpose.** Since alerts now require an explicit
`review_cli.py approve` either way, running the scan unattended is lower-risk than it
used to be (it can never alert you to something you didn't approve) — but it does
still burn API-rate-limit budget and write real rows every run, so treat installing it
as a deliberate choice, not a default.

## 10. Troubleshooting

- **`LLM did not return schema-valid JSON after 3 attempts`**: a transient failure on
  the live Rakuten/Claude gateway — observed occasionally in real runs, not unique to
  your setup. Re-run the scan; it's not typically persistent.
- **`ShortSqueezeAgent` scores looking pinned at an extreme (e.g. always 1.00)**: this
  agent runs in a documented degraded mode (FINRA short-interest/borrow-fee aren't
  connected — register at developer.finra.org if you want this fixed) and is
  currently options-flow-only. Treat its output with extra skepticism until that's
  connected.
- **A JP ticker gets vetoed every time**: check `risk_manager_override`/`veto_reason`
  in the recommendation — a very common cause is your configured `account_equity_jpy`
  being too small to afford a full 100-share lot at that ticker's price.
- **Crypto on-chain sub-scores always excluded**: expected until you add real,
  verified ETH addresses to `config.yaml`'s `crypto_onchain` block (§7). MVRV/SOPR stay
  excluded regardless — no free, live source for those exists anywhere today.

## 11. Where to look next

- [README.md](README.md) — exactly what's built, tested, and still pending, phase by phase.
- `docs/plan/section_agents.md` — the full spec for every specialist agent's inputs,
  thresholds, and persona.
- `docs/plan/section_risk_validation.md` — the statistical validation checklist,
  the mandatory paper-trading gate, and an honest assessment of what returns are
  actually realistic (worth reading before anchoring on any specific target).
