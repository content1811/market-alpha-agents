# market-alpha-agents

A local, multi-agent research system that analyzes US equities, Japanese equities (TSE), and major crypto to produce **manual decision-support** for day/swing trading: a scored buy/sell/hold call per ticker with a suggested holding period, profit target, and stop-loss, plus the reasoning behind it. It never places or auto-executes trades — every recommendation is meant to be read by a human and acted on manually.

Status as of 2026-08-26: **planning complete; Phase 0 done; Phase 1 (data layer) partially done; Phase 2 (specialist agents) essentially done; Phase 3 (supervisor/aggregation) done for the equity path; Phase 4 (backtesting/validation) framework done, applied to one signal so far; Phase 5 (news/alerting) core pieces done.** See "Where things stand" below for exactly what's built, tested, and next.

**LLM provider note:** the plan originally specced local Ollama as primary. Per direction, this was switched to the **Rakuten AI Gateway (Claude)** instead, reusing the same live-verified client construction as `../Server_failure/rakuten-failure-agent` (gateway auth via header, not `api_key`; no `temperature` param; `max_tokens=128000`; streaming required). Ollama (`qwen2.5:7b`, already pulled locally) is now the configured fallback, not primary. See `agents/llm_client.py`.

## Read this before anything else

- **Not licensed financial advice.** This is a personal, single-operator research tool. See `docs/plan/section_risk_validation.md` §8 for Japan-specific tax/compliance notes (crypto and equities are taxed very differently; J-Quants data may not be redistributed or used to advise third parties).
- **The 50%+ return target is an aspiration, not a design goal.** `docs/plan/section_risk_validation.md` §7 lays out the honest case for why: full-population studies of retail day traders (Brazil, Taiwan) show ~97% of persistent day traders lose money; a well-validated systematic strategy that survives years typically runs Sharpe ~1-2 and CAGR ~15-40%/year, not 50%+ in months. Anything claiming better should be treated as probable overfitting until it survives the validation gauntlet in §4-§5. Success for this project should be defined as *capital preservation + demonstrated statistically-significant edge*, with 50%+ as a low-probability tail outcome, not the base case.
- **Free-tier data has real gaps.** Most notably: Glassnode's free API tier was discontinued sometime before this research (Aug 2026) — the on-chain agent runs on weaker data than originally hoped (see `docs/plan/section_data_pipeline.md` §1). Japanese equities have exactly one live data source with no real fallback. Both are called out explicitly rather than papered over.

## How this was built

The research and plan were produced by a multi-agent workflow, not written by hand:
1. **8 parallel research agents** investigated technical-analysis strategies, crypto-specific factors, multi-agent orchestration architecture, and free-tier data sources for US/Japan/crypto (`docs/research/*.md`).
2. **4 section-drafting agents** turned that research into the plan sections below (`docs/plan/section_*.md`).
3. **A critique agent** red-teamed the four drafts against each other and found 12 concrete defects — contradictory logic between two sections, a missing Japan-specific risk check, a formula bug, an uncited regulatory claim, etc. (`docs/plan/critique.md`).
4. **4 parallel fix agents** applied surgical, critique-driven corrections directly to the sections.
5. Manual follow-up caught and fixed one more issue the automated pass missed (Glassnode's free tier being gone, which the on-chain agent's spec still assumed) — a reminder that this whole pipeline needs a human checking its work, which is exactly the posture the system itself is designed around.

## The plan, section by section

| Doc | Covers |
|---|---|
| [`docs/plan/section_agents.md`](docs/plan/section_agents.md) | The 11-agent roster, what each one examines, exact inputs/indicators/thresholds, output schema, and persona/prompt design |
| [`docs/plan/section_orchestration.md`](docs/plan/section_orchestration.md) | Chosen framework (LangGraph), full repo layout, the 8-phase build roadmap, and illustrative code for the orchestration loop + aggregation math |
| [`docs/plan/section_data_pipeline.md`](docs/plan/section_data_pipeline.md) | Every free-tier data source (with rate limits/status), the local ingestion/storage pipeline, news/sentiment scoring, and the alerting design |
| [`docs/plan/section_risk_validation.md`](docs/plan/section_risk_validation.md) | Stop-loss/position-sizing formulas, backtesting & walk-forward validation, the paper-trading gate, the fine-tuning feedback loop, and the honest return-expectation assessment |
| [`docs/plan/critique.md`](docs/plan/critique.md) | The red-team pass — useful context for *why* certain design choices exist |
| `docs/research/*.md` | Raw research per topic, with citations |

## Agent roster at a glance

Every specialist outputs a `signal_score` (-1 to +1), a `confidence`, and rationale; `RiskManagerAgent` and `MarketRegimeAgent` are gates/modifiers, not directional votes; `PortfolioSupervisorAgent` deterministically blends everything into one final call (full algorithm in `section_agents.md` §10).

| Agent | Examines |
|---|---|
| MeanReversionAgent | Bollinger fade, RSI-2, VWAP reversion, z-score vs moving average |
| TrendMomentumAgent | MA crossovers, ADX, Donchian breakout, MACD, cross-sectional momentum vs. broad-market benchmark |
| SeasonalityAgent | Day-of-week/month, PEAD, sector seasonality |
| ShortSqueezeAgent | Short interest, days-to-cover, borrow-fee spikes, unusual options volume (US full, JP degraded, N/A crypto) |
| VolatilityVolumeAgent | ATR expansion, relative volume, volume profile — confirms/denies other agents, never directional alone |
| CryptoOnChainAgent | MVRV, SOPR, exchange flows, whale cohorts, unlock schedules, staking yield (crypto only) |
| CryptoDerivativesAgent | Funding rates, open interest, liquidation clusters, options skew (crypto only) |
| NewsSentimentAgent | LLM-scored headline sentiment, recency-weighted |
| RiskManagerAgent | Position sizing, structural feasibility (TSE lot size, PDT/margin rules), TSE price-limit-band risk, correlation cap, drawdown circuit breaker, veto power |
| MarketRegimeAgent | System-wide position-size-ceiling multiplier based on trailing realized-volatility percentile |
| PortfolioSupervisorAgent | Deterministic aggregation of all of the above into one auditable call |

## Tech stack (proposed)

Python, **LangGraph** as a hierarchical supervisor graph, SQLite/Parquet for local storage, **CCXT** for crypto exchange data, **yfinance/Twelve Data/Tiingo** for US equities, **J-Quants + Yahoo unofficial** for JP equities, **Dune Analytics + Etherscan V2** for on-chain (replacing Glassnode), **APScheduler + launchd** for scheduling, **Telegram bot** for alerts. Full rationale in `section_orchestration.md` §1.

## Repo layout

See `docs/plan/section_orchestration.md` §2 for the full annotated tree. Folder skeleton already created: `config/`, `data/`, `signals/`, `agents/`, `orchestration/`, `backtesting/`, `alerting/`, `storage/`, `scheduler/`, `ui/`, `scripts/`, `tests/`, `notebooks/`, `docs/`.

## Build roadmap

Phase 0 (env setup) → 1 (data layer) → 2 (specialist agents) → 3 (supervisor/aggregation) → 4 (backtesting & validation) → 5 (news/alerting) → 6 (paper-trading dry run — not "done" until ≥8-12 weeks or ≥30 simulated trades per strategy, per `section_risk_validation.md` §5) → 7 (human review workflow & fine-tuning loop). No phase touches real capital before Phase 6's gate is met. Full detail in `section_orchestration.md` §3.

## Where things stand / next steps

**Phase 0 (Environment Setup) — done and verified:**
- `pyproject.toml` + a local `.venv` with all core deps installed and importable.
- `config/config.yaml`, `.env.example`, and stub `config/watchlists/*.yaml` / `config/strategies/*.yaml` populated with real parameter defaults pulled from `section_agents.md`.
- `scripts/validate_config.py` runs clean against the real config (`python scripts/validate_config.py`).
- `orchestration/hello_world_graph.py` — a one-node LangGraph graph that checkpoints to `orchestration/checkpoints.db` via `SqliteSaver` — runs and passes.
- macOS notification permission confirmed via `osascript`.
- `scheduler/com.marketalpha.dailyrun.plist` written as a template, **deliberately not installed** — there's no `run_daily_scan.py` yet (that's Phase 6), so loading a launchd agent now would just fail on every tick.

**Phase 1 (Data Layer) — foundation done, 3 of ~13 connectors built:**
- `data/schema.py` — the canonical `NormalizedBar`/`NormalizedFundamental`/`NormalizedNewsItem`/`NormalizedSignal` models, including the mandated `adjusted`/`adjustment_factor` fields and `DataQualityFlag` enum.
- `agents/schemas.py` — the shared `AgentVerdict`/`RiskManagerVerdict`/`MarketRegimeVerdict`/`SupervisorVerdict` envelope per `section_agents.md` §0.
- `data/connectors/base.py` — the `DataSource` ABC with a real SQLite rate-limit ledger, a disk-backed read-through cache, and a circuit breaker implementing the canonical `ok`/`stale`/`unavailable` propagation rule from `section_data_pipeline.md` §2.4. Covered by 6 passing unit tests (`tests/test_data_connectors/test_base_datasource.py`) — this caught and fixed a real bug where diskcache's own eviction made the originally-designed staleness check impossible.
- Three **keyless** connectors implemented and verified against live data just now: `us_equities_yfinance.py` (AAPL), `crypto_ccxt.py` (BTC/USDT via Binance public), `jp_equities_yahoo_unofficial.py` (7203.T Toyota).
- The mandated split-adjustment regression test (`test_us_equities_yfinance.py`) passes against NVDA's real 2024-06-10 10:1 split.

**Not yet built (remaining Phase 1 work):** the ~10 connectors needing API keys/registration (Twelve Data, Tiingo, Alpha Vantage, SEC EDGAR, FINRA short interest, J-Quants, EDINET, Dune Analytics, Etherscan V2) — these need you to register for free accounts first (see `.env.example`); the Parquet/DuckDB analytical store and `state.db`/`news.db` operational store from `section_data_pipeline.md` §2.3; and the ingestion-cadence scheduler jobs.

**Phase 2 (Individual Specialist Agents) — 7 of 8 directional agents done end-to-end, live-verified:**
- `agents/llm_client.py` — Rakuten AI Gateway (Claude) client with schema-constrained JSON output and retry-with-repair. Also fixed a real robustness gap here: an over-length string field (e.g. `rationale`) that still fails validation after repair attempts is now truncated at a word boundary instead of raising — caught by NewsSentimentAgent's first live run.
- Signal math (all pure functions, all hand-fixture-tested, ~55 signal-level tests): `signals/ta/mean_reversion.py`, `signals/ta/trend_momentum.py` (Bollinger/RSI-2/VWAP-z/MA-vs-MA-z, ADX/trend_confidence, Donchian, MACD, cross-sectional momentum vs. SPY/TOPIX/BTC), `signals/volatility_volume.py` (ATR expansion, RVOL, Point-of-Control), `signals/ta/seasonality.py` (turn-of-month, day-of-week, PEAD via yfinance earnings surprise, BTC halving-cycle phase), `signals/crypto_composite.py` (funding/OI/skew for derivatives, MVRV/SOPR/flow/whale composite for on-chain), `signals/news_sentiment.py` (time-decay-weighted headline aggregation + coverage-count gate), `signals/squeeze.py` (short-squeeze composite with graceful re-normalization when inputs are missing).
- Agents done and verified against **live data**: `MeanReversionAgent`/`TrendMomentumAgent` (yfinance AAPL/SPY), `VolatilityVolumeAgent` (yfinance TSLA), `SeasonalityAgent` (yfinance AAPL + real earnings dates), `CryptoDerivativesAgent` (CCXT/Binance real funding rate + open interest), `NewsSentimentAgent` (live RSS + real LLM headline scoring), `ShortSqueezeAgent` (yfinance real options chain, running in an explicitly **degraded mode** since FINRA short-interest/borrow-fee aren't connected yet). In every case, score/confidence are 100% code-computed — the LLM's output schema has no score field at all, so it structurally cannot influence the number, only explain it.
- **Deliberately deferred: `CryptoOnChainAgent`.** Its signal math (`compute_onchain` in `signals/crypto_composite.py`) is done and tested, but every one of its inputs (MVRV, SOPR, exchange flows, whale cohorts, unlock schedules) needs the Dune Analytics/CryptoQuant connector that isn't built yet (Phase 1 remaining work). Building an agent wrapper around it now would mean passing in placeholder numbers with nothing real behind them — that's not meaningfully different from not building it, so it's left as the one open item here rather than faked.

**Not yet built:** `CryptoOnChainAgent`'s wrapper (blocked on Phase 1's Dune/CryptoQuant connector).

**Phase 3 (Supervisor / Aggregation) — done for the equity path, live-verified through the real LangGraph graph:**
- `agents/schemas.py` corrected to match `section_agents.md` §9-§11 exactly (`RiskManagerVerdict`, `MarketRegimeVerdict`, `SupervisorVerdict` — the original draft had drifted from the plan's precise field lists/enums).
- `signals/market_regime.py` + `agents/market_regime_agent.py` — **no LLM call**: the plan's own output schema for this agent has no rationale field, only numbers.
- `signals/risk.py` + `agents/risk_manager_agent.py` — **no LLM call**: implements rules 1/3/4/6/7/8/9 (position sizing, JP 100-share lot feasibility, correlation cap, drawdown circuit breaker, veto, and the JP daily price-limit-band check) fully deterministically. The TSE price-limit table is a best-effort reconstruction flagged for verification against JPX's current published table, not fetched live — same honesty standard as the FINRA citation fix earlier. Rule 2 (Kelly) and rule 5 (US margin/PDT) are implemented/config-driven but not fully wired pending Phase 4 backtest data and broker integration (neither of which exists by design).
- `orchestration/aggregate.py` — the single authoritative implementation of §10.1-§10.3's weighted-blend / `vol_conf_multiplier` gate / dispersion-penalty / veto algorithm, verbatim where the plan gives an exact formula, with two undefined terms (`weight_norm_avg_confidence`, `data_quality_multiplier`) resolved as documented judgment calls rather than guessed silently.
- `agents/portfolio_supervisor_agent.py` — assembles the final `SupervisorVerdict`; the LLM writes only the synthesized rationale (agreements/conflicts/risk restatement/skepticism reminder), never the numbers.
- `orchestration/state.py` + `orchestration/graph.py` — the actual LangGraph `StateGraph` (not just manual function composition): 6 equity specialist nodes fan out from `START`, converge into `risk_manager`, then `supervisor`. Checkpointing via `SqliteSaver` verified to survive a fresh-process resume.
- **Live-verified twice through the real graph** (not mocks) on AAPL and TSLA, each producing a coherent final call with correctly hedged, non-overconfident rationale.
- **Scope note:** crypto asset-class graph wiring isn't included yet — blocked on the same `CryptoOnChainAgent` gap above, plus `CryptoDerivativesAgent` needing a funding/OI fetch step the current `PipelineState` doesn't carry. Bull/bear debate nodes (mentioned as illustrative in the orchestration doc) also aren't built — the aggregation works directly off the 8 specialist verdicts without them.

**Not yet built:** crypto graph wiring, bull/bear debate nodes (optional refinement, not required for the aggregation to work).

**Phase 4 (Backtesting & Validation) — framework built and applied to one signal for real:**
- `backtesting/robustness.py` — Sharpe, profit factor, max drawdown, Calmar ratio (hand-fixture-tested), plus Deflated Sharpe Ratio, Probability of Backtest Overfitting (via combinatorial cross-validation), and Minimum Track Record Length, all implemented directly from Bailey & López de Prado's published formulas. **Honesty note:** no independently-sourced worked numeric example existed to hand-verify DSR/PBO/MinTRL against, so those three are tested against documented monotonicity/sanity properties (e.g. pure-noise variants → PBO≈0.5, a genuinely-best variant → low PBO) rather than exact fixtures — a real but weaker form of verification, flagged rather than presented as equivalent to the hand-computed tests elsewhere in this repo.
- `backtesting/walk_forward.py` — rolling (not anchored) walk-forward split generator, hand-fixture-tested.
- `backtesting/run_backtest.py` — vectorbt-backed position/equity-curve simulation with realistic fees/slippage. Found and fixed a real compatibility bug live: vectorbt 1.1.0 (current as of Aug 2026) crashes on import against plotly≥7 (a renamed trace name), and separately, vectorbt's own `sharpe_ratio()` accessor throws on a business-day-indexed series ("BusinessDay is a non-fixed frequency") — worked around by using vectorbt only for trade simulation and routing every statistic through `robustness.py` uniformly, not vectorbt's stats API.
- **Real result, not synthetic:** ran a full walk-forward backtest (12-month in-sample / 3-month out-of-sample, rolling) of `MeanReversionAgent`'s signal against 8 years of real AAPL data (2018-2026), reporting only the concatenated out-of-sample segments. Result: **Sharpe -0.40, profit factor 0.80, Deflated Sharpe 0.0** — this specific signal, at its current default thresholds, shows no real edge on this ticker once realistic costs are applied. That's the validation framework doing its job (rejecting a mediocre backtest), not a failure of this phase.
- Added `mean_reversion_signal_series()` (vectorized full-history version of the same formula `compute_mean_reversion` uses on the latest bar) and cross-validated it against the scalar function at multiple truncation points — they agree exactly.

**Not yet built (remaining Phase 4 work):** the other 6 live signals haven't been run through this framework yet (only MeanReversionAgent has); PBO hasn't been run on a real multi-variant parameter sweep yet (the sanity tests use synthetic variants); no MinTRL/DSR go/no-go gate is wired into anything yet — these are analysis tools proven to work, not yet a pass/fail checklist blocking Phase 6. `bt`/`zipline-reloaded` (portfolio-level realism) and `freqtrade` (crypto leg) are explicitly not installed — see `pyproject.toml`'s `backtesting` extra for why.

**Phase 5 (News/Alerting Integration) — core pieces built and live-verified:**
- `alerting/news_watch/edgar_feed.py` — real-time SEC EDGAR filings poller, live-verified against today's actual feed (96 real filings on first poll, correctly 0 on immediate re-poll — de-dup by accession number works). Auto-escalates severity for material-event 8-K items (2.02, 5.02, etc., per the plan's own examples).
- `alerting/news_watch/tdnet_scraper.py` — JP disclosure scraper, live-verified against today's real TDnet page (correctly parsed 5202.T → Nippon Sheet Glass, with the 5-digit-code → 4-digit-ticker mapping confirmed against yfinance). Every row parses inside its own try/except and the table lookup itself degrades to `[]` with a logged warning rather than raising, per the plan's "log-and-skip, don't crash the whole run" requirement — tested by feeding it a deliberately restructured page.
- `alerting/desktop_notify.py` — **found and fixed a real bug live**: AppleScript has no single-quote string form (`display notification 'x'` is a genuine syntax error, confirmed via `osascript`), so the original `repr()`-based escaping was broken; rewrote with proper double-quote escaping and re-verified live, including a message containing embedded quotes.
- `alerting/telegram_bot.py` — Bot API sender matching Telegram's documented HTTP shape exactly (message-length truncation at the real 4096-char limit, graceful `False` return on any failure). Not live-fired — that needs a bot token registered via @BotFather, which requires the operator's own interactive Telegram setup — but is fully mock-tested.
- `alerting/templates.py` — the 5 message formats from `section_data_pipeline.md` §4.3, matching the plan's exact examples (emoji, field order, "analysis only" disclaimer, monthly reality-check digest).
- `alerting/triggers.py` — composite-score-threshold, squeeze-risk, stop/target-proximity, RVOL-price-spike, and filing-match triggers, plus a SQLite `(symbol, trigger_type)` cooldown deduplicator.
- **Capstone, real end-to-end, no mocks:** ran the actual Phase 3 LangGraph pipeline on live NVDA data, took the real `SupervisorVerdict` it produced, formatted it with the real alert template, and delivered it as a live macOS desktop notification. All four layers (agents → aggregation → template → channel) run for real.
- **Side effect of this pass:** observed a real transient LLM failure (both the initial attempt and one repair attempt failed schema validation in the same live run, then succeeded cleanly on retry) — raised `llm_client`'s default repair attempts from 1 to 2 in response.

**Not yet built (remaining Phase 5 work):** `alerting/sentiment_finbert.py` (local FinBERT first-pass triage — `NewsSentimentAgent` currently sends every headline straight to the LLM, skipping the cheaper bulk-triage layer the plan describes); Discord webhook (secondary channel); email/SMTP (EOD digest, monthly digest); the unlock-calendar and Fear&Greed-extreme triggers (need data sources not yet connected); wiring triggers.py + templates.py + the channels into one scheduled dispatcher (each piece works standalone, nothing runs them together on a cadence yet — that's Phase 6 territory).
