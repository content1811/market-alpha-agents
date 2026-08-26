# market-alpha-agents

A local, multi-agent research system that analyzes US equities, Japanese equities (TSE), and major crypto to produce **manual decision-support** for day/swing trading: a scored buy/sell/hold call per ticker with a suggested holding period, profit target, and stop-loss, plus the reasoning behind it. It never places or auto-executes trades — every recommendation is meant to be read by a human and acted on manually.

Status as of 2026-08-26: **planning complete; Phase 0 (environment setup) done; Phase 1 (data layer) underway.** See "Where things stand" below for exactly what's built, tested, and next.

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

**Not yet built (remaining Phase 1 work):** the ~10 connectors needing API keys/registration (Twelve Data, Tiingo, Alpha Vantage, SEC EDGAR, FINRA short interest, J-Quants, EDINET, Dune Analytics, Etherscan V2) — these need you to register for free accounts first (see `.env.example`); the Parquet/DuckDB analytical store and `state.db`/`news.db` operational store from `section_data_pipeline.md` §2.3; and the ingestion-cadence scheduler jobs. After that: Phase 2 (specialist agents).
