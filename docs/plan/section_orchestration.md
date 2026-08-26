# Orchestration & Repository Architecture

## 1. Chosen Orchestration Approach

### 1.1 Framework: LangGraph, as a hierarchical supervisor graph

**Decision: build the orchestration backbone on LangGraph (`pip install langgraph`), structured as a hierarchical supervisor with an optional bull/bear debate step, deterministic Python aggregation, and `interrupt()`-based human checkpoints.**

Rationale, weighed against the alternatives surveyed:

| Option | Why not chosen as primary |
|---|---|
| **CrewAI** | Good fast-prototyping fit and a genuinely nice built-in `Memory` class (LanceDB-backed, semantic+recency+importance), but coarser control over graph-level branching/retries than we want for a system that must gate every path through a human-approval node before any alert fires. Kept as a documented fallback if LangGraph's lower-level graph API proves too slow to iterate on in Phase 2. |
| **AutoGen (Microsoft)** | Explicitly in "Maintenance Mode" per its own README as of 2026 — not started on for new builds. |
| **Microsoft Agent Framework (MAF)** | Credible, provider-agnostic (including local Ollama), but younger, less battle-tested for this use case, and its tooling still skews Azure/enterprise. |
| **OpenAI Agents SDK** | Clean "agents-as-tools" pattern is exactly the manager-owns-final-answer shape we want, but it's structurally oriented around OpenAI's API even with LiteLLM adapters — a poor fit for a "free-tier-first, mix local/cheap models" budget philosophy. |
| **Anthropic Claude Agent SDK** | Optimized for coding-agent workloads (file/shell/tool use), not a bespoke financial multi-agent debate/aggregation pipeline. Reasonable as an LLM-calling layer *underneath* LangGraph (e.g., Claude as one of the specialist agents' model backend), not as the top-level orchestrator. |

LangGraph wins on four concrete, checkable grounds:
1. **Zero mandatory paid dependency** — the core library is fully open-source and local; LangSmith/"LangGraph Platform" are optional add-ons we simply never install.
2. **Native primitives for the three hardest problems in this system**: multi-agent supervision (supervisor/hierarchical/network topologies "all using one framework"), human-in-the-loop (`interrupt()` + `Command(resume=...)`, state persisted via checkpointer so a pause can survive a process restart), and short/long-term memory separation (`checkpointer` for a single day's run, `Store` for cross-day history).
3. **A real, current (July 2026, v0.3.1) open-source reference implementation, [TradingAgents](https://github.com/TauricResearch/TradingAgents), already built on LangGraph**, implementing almost exactly the analyst → bull/bear debate → trader → risk-manager pipeline this project needs. We study/adapt its graph and state code rather than designing from scratch, while re-tuning it for a free-tier/small-account budget (it's built assuming heavier paid-LLM usage than we want).
4. **Model-agnostic** — works with local Ollama models or any cheap API, not locked to one vendor, matching the "free-tier first" budget constraint.

### 1.2 Core design decisions baked into the graph

- **Structured, typed outputs only.** Every specialist agent returns a Pydantic-validated JSON object (`signal`, `conviction`, `rationale`, `key_risks`, `suggested_holding_period`, `target_price`, `stop_loss`), never free text, so aggregation is deterministic code, not another LLM call.
- **Agents-as-tools, not full handoff.** The supervisor node invokes each specialist as a bounded tool call and always retains control; no specialist is ever handed the turn.
- **One adversarial debate round** (bull vs. bear pass over the same evidence, TradingAgents-style) feeds into the risk-manager node, cheaply reducing one-sided overconfidence.
- **Deterministic, auditable aggregation function** (plain Python, not an LLM) — `orchestration/aggregate.py` implements the `PortfolioSupervisorAgent` weighting/blend algorithm defined verbatim in `section_agents.md` §10.1–§10.2 (the single source of truth for this math, not restated loosely here): a confidence-weighted directional blend across whichever specialist agents are active for the ticker's asset class, a `vol_conf_multiplier` volatility/volume confirmation gate, a stdev-based dispersion/disagreement penalty on `overall_confidence`, and a **`RiskManagerAgent` veto/reduce-size gate** (not a weighted vote) that can force `HOLD` or hard-cap position size regardless of the blended score. See §4 below for the actual node/aggregation code. *(Once the planned `MarketRegimeAgent` — a system-wide position-size multiplier gate/modifier — is specified in `section_agents.md`, `aggregate.py` should apply that multiplier alongside the `RiskManagerAgent` cap; its interface isn't defined yet, so this is a forward note, not a wired dependency.)*
- **`interrupt()` gates every alert/log-write action.** The graph pauses after the risk-manager/aggregator step, shows the human the recommendation + confidence + full component breakdown, and requires an explicit resume before anything is written to the alert channel or persisted as "actioned."
- **No trade-execution tool exists anywhere in the codebase.** This is a stronger safety property than a permission check that could be misconfigured — the capability is architecturally absent, not merely gated.
- **Persistence split**: `SqliteSaver` checkpointer for single-run durability/crash-recovery, plus a separate SQLite-backed `Store` for cross-day memory (yesterday's recommendation, score, and outcome per ticker), so agents can answer "did we already flag this, did the thesis play out."

---

## 2. Repository Folder Structure

```
market-alpha-agents/
├── config/
│   ├── config.yaml                  # master config (see §6)
│   ├── watchlists/
│   │   ├── us_equities.yaml
│   │   ├── jp_equities.yaml
│   │   └── crypto.yaml
│   ├── strategies/
│   │   ├── mean_reversion.yaml      # per-strategy params (RSI-2, BB, VWAP, z-score)
│   │   ├── trend_momentum.yaml      # MA cross, ADX, Donchian, MACD, rel-strength
│   │   ├── seasonality.yaml
│   │   ├── squeeze.yaml
│   │   └── crypto_factors.yaml      # MVRV, funding, altseason, F&G, etc.
│   └── .env.example                 # API key placeholders, never committed with real keys
├── data/
│   ├── connectors/
│   │   ├── base.py                  # DataSource ABC: get_ohlcv(), get_fundamentals()...
│   │   ├── us_equities_yfinance.py
│   │   ├── us_equities_twelvedata.py    # fallback/cross-check
│   │   ├── us_equities_tiingo.py        # fallback/cross-check
│   │   ├── us_fundamentals_edgar.py     # SEC EDGAR XBRL companyfacts
│   │   ├── us_short_interest_finra.py
│   │   ├── jp_equities_jquants.py       # Free tier: 12wk-lagged
│   │   ├── jp_equities_yahoo_unofficial.py
│   │   ├── jp_margin_short_jpx_scrape.py
│   │   ├── jp_filings_edinet.py
│   │   ├── crypto_ccxt.py               # exchange OHLCV/funding via public REST
│   │   ├── crypto_onchain_dune.py       # MVRV/SOPR approximation via Dune SQL + CryptoQuant dashboard reads (Glassnode free tier discontinued)
│   │   ├── crypto_altseason_blockchaincenter.py
│   │   └── crypto_feargreed_alternativeme.py
│   ├── cache/                       # local parquet/sqlite cache, gitignored
│   └── schema.py                    # canonical OHLCV/fundamentals/on-chain Pydantic models
├── signals/
│   ├── ta/
│   │   ├── mean_reversion.py        # BB fade, RSI-2, VWAP reversion, z-score
│   │   ├── trend_momentum.py        # MA cross, ADX, Donchian, rel-strength rank, MACD
│   │   └── seasonality.py           # day-of-week, turn-of-month, PEAD, sector cycle
│   ├── squeeze.py                   # composite short-squeeze score
│   ├── volatility_volume.py         # ATR expansion, volume profile, RVOL
│   └── crypto_composite.py          # on-chain + derivatives + sentiment composite
├── agents/
│   ├── schemas.py                   # shared JSON envelope (signal_score/confidence/...) per
│   │                                 #   section_agents.md §0; AgentVerdict + SupervisorVerdict models
│   ├── mean_reversion_agent.py      # MeanReversionAgent (agents §1)
│   ├── trend_momentum_agent.py      # TrendMomentumAgent (agents §2)
│   ├── seasonality_agent.py         # SeasonalityAgent (agents §3)
│   ├── short_squeeze_agent.py       # ShortSqueezeAgent (agents §4; full on US, degraded on JP, absent on crypto)
│   ├── volatility_volume_agent.py   # VolatilityVolumeAgent (agents §5): direct vote + vol_conf_multiplier
│   ├── crypto_onchain_agent.py      # CryptoOnChainAgent (agents §6, crypto-only)
│   ├── crypto_derivatives_agent.py  # CryptoDerivativesAgent (agents §7, crypto-only)
│   ├── news_sentiment_agent.py      # NewsSentimentAgent (agents §8)
│   ├── risk_manager_agent.py        # RiskManagerAgent (agents §9): veto/reduce_size gate, not a weighted vote
│   ├── portfolio_supervisor_agent.py # PortfolioSupervisorAgent (agents §10): LLM rationale-synthesis
│   │                                 #   persona ONLY -- the numeric blend/veto math it describes lives
│   │                                 #   in orchestration/aggregate.py, deterministically, not here
│   ├── bull_researcher.py           # debate role
│   ├── bear_researcher.py           # debate role
│   └── llm_client.py                # thin wrapper: Ollama local / cheap API, swappable
├── orchestration/
│   ├── state.py                     # LangGraph State TypedDict/Pydantic definition
│   ├── graph.py                     # build_graph(): nodes, edges, interrupt points (§5.1)
│   ├── aggregate.py                 # implements agents §10.1-§10.2 verbatim: confidence-weighted
│   │                                 #   blend + vol_conf_multiplier gate + dispersion penalty + veto
│   ├── memory_store.py              # cross-day Store: symbol/date -> past verdicts
│   └── checkpoints.db               # SqliteSaver file, gitignored
├── backtesting/
│   ├── run_backtest.py              # vectorbt/bt/zipline-reloaded driver (equities)
│   ├── run_backtest_crypto.py       # freqtrade driver
│   ├── walk_forward.py              # rolling/anchored WFO harness
│   ├── robustness.py                # Deflated Sharpe, PBO, MinTRL checks
│   └── reports/                     # quantstats tear sheets, gitignored
├── alerting/
│   ├── telegram_bot.py
│   ├── desktop_notify.py            # macOS osascript / terminal-notifier
│   ├── news_watch/
│   │   ├── edgar_feed.py            # real-time 8-K/10-Q Atom feed poller
│   │   ├── tdnet_scraper.py         # TSE disclosure, HTML-scrape (no feed available)
│   │   ├── rss_aggregator.py        # CoinDesk, MarketWatch, CNBC, Japan Times, etc.
│   │   └── sentiment_finbert.py     # local FinBERT first-pass + local LLM second-pass
│   └── templates/                   # alert message formats
├── storage/
│   ├── recommendations.db           # SQLite: append-only log of every scored recommendation,
│   │                                 #   keyed by recommendation_id (== LangGraph thread_id)
│   └── outcomes.db                  # human-recorded actual entries/exits, for fine-tuning;
│                                     #   joined back to recommendations.db by recommendation_id
│                                     #   (see ui/review_cli.py log-outcome, Phase 7)
├── scheduler/
│   ├── jobs.py                      # APScheduler 3.x job definitions
│   └── com.marketalpha.dailyrun.plist  # macOS launchd supervisor plist
├── ui/
│   └── review_cli.py                # two explicit flows (§Phase 7): `approve|reject` (pre-alert
│                                     #   gate) and `log-outcome`/`pending-outcomes` (post-trade backfill)
├── scripts/
│   ├── run_daily_scan.py            # entrypoint invoked by launchd/cron
│   ├── backfill_history.py
│   └── validate_config.py
├── tests/
│   ├── test_signals/
│   ├── test_agents/
│   ├── test_orchestration/
│   └── test_data_connectors/
├── notebooks/                       # exploratory research, not production code
├── logs/                            # gitignored
├── requirements.txt / pyproject.toml
└── README.md
```

### Module responsibilities

- **`config/`** — all tunables (watchlists, thresholds, schedules, API key *references*) live here, never hardcoded in `agents/` or `signals/`. See §6.
- **`data/connectors/`** — one adapter per data source, each implementing the same `DataSource` interface (`get_ohlcv`, `get_fundamentals`, `get_short_interest`, …) so a broken/rate-limited free source (yfinance 429s, Stooq's JS challenge, J-Quants' 5 calls/min) can be swapped for its documented fallback without touching signal or agent code.
- **`signals/`** — pure, stateless, deterministic functions implementing the TA/crypto/seasonality math from the research (RSI-2, Bollinger %B, ADX regime gate, Donchian breakout, squeeze composite, MVRV/SOPR/funding-rate scores, etc.). No LLM calls here — this layer is unit-testable and cheap to run continuously.
- **`agents/`** — the LLM-backed specialists defined in `section_agents.md` §1–§9 (MeanReversion, TrendMomentum, Seasonality, ShortSqueeze, VolatilityVolume, CryptoOnChain, CryptoDerivatives, NewsSentiment, RiskManager), each consuming `signals/` outputs plus fundamentals/news context and producing the shared `signal_score`/`confidence` JSON envelope from §0 of that doc — plus `portfolio_supervisor_agent.py`, which is *only* the rationale-synthesis persona from §10; the numeric blend it describes is computed deterministically, not by this agent.
- **`orchestration/`** — the LangGraph graph definition, state schema, and the two persistence layers (checkpointer for run durability, store for cross-day memory); `aggregate.py` here — not any agent — is the single authoritative implementation of the `PortfolioSupervisorAgent` blend/veto math (`section_agents.md` §10.1–§10.2).
- **`backtesting/`** — offline validation only; never imported by the live daily-scan path.
- **`alerting/`** — the only layer allowed to reach a human (Telegram/desktop/log); explicitly the last node after the `interrupt()` approval gate.
- **`storage/`** — the append-only audit trail: every recommendation, its full component score breakdown, and (once the human manually trades) the actual outcome, feeding Phase 7's fine-tuning loop.
- **`scheduler/`** — cron-equivalent triggering (APScheduler 3.x, since 4.0 is still alpha as of Aug 2026, supervised by a `launchd` plist so it survives sleep/reboot).

---

## 3. Phased Implementation Roadmap

### Phase 0 — Environment Setup
**Build:** repo skeleton above; `pyproject.toml`/`requirements.txt` pinning `langgraph`, `pydantic`, `yfinance`, `apscheduler==3.*`, `vectorbt`, `freqtrade` (separate venv, it's opinionated about its own env), `quantstats`; `.env.example` + `python-dotenv`; SQLite files initialized with schema migrations; `launchd` plist installed and confirmed to survive a reboot.
**Test:** `scripts/validate_config.py` loads `config.yaml` + all watchlists and fails loudly on missing/malformed fields; a "hello world" LangGraph graph with one no-op node runs and checkpoints to `orchestration/checkpoints.db`; confirm macOS notification permission granted (`osascript -e 'display notification'` succeeds).

### Phase 1 — Data Layer
**Build:** all connectors in `data/connectors/`; per-source rate-limit/backoff wrappers (yfinance UA-spoofing, SEC EDGAR 10 req/sec + descriptive User-Agent, J-Quants 5 calls/min free tier, FINRA biweekly short-interest puller); local parquet/SQLite cache with TTL per source type (daily OHLCV cached until next session close; fundamentals cached ~quarterly); `data/schema.py` canonical models so downstream code never touches vendor-specific field names.
**Test:** integration tests hitting each free API with a real key/no key as applicable, asserting schema conformance and graceful fallback (e.g., force yfinance to fail, confirm Twelve Data/Tiingo fallback fires); a manual daily job pulls the full watchlist and reports per-source latency/error rates for one week before moving on.

### Phase 2 — Individual Specialist Agents
**Build:** `signals/` math implementations first (pure functions, no LLM) — mean-reversion, trend/momentum, seasonality, squeeze composite, volatility/volume gating, crypto composite; then wrap each of the eight specialist agents (`mean_reversion_agent.py`, `trend_momentum_agent.py`, `seasonality_agent.py`, `short_squeeze_agent.py`, `volatility_volume_agent.py`, `crypto_onchain_agent.py`, `crypto_derivatives_agent.py`, `news_sentiment_agent.py` — the full set specified in `section_agents.md` §1–§8) around these signals plus an LLM call constrained to the shared `signal_score`/`confidence` JSON envelope (§0 of that doc); `agents/llm_client.py` abstracts local Ollama (e.g., Qwen2.5/Phi-4-mini for cheap iteration) vs. a paid API, swappable via config.
**Test:** unit tests on `signals/` with hand-computed fixture data (known RSI-2/ADX/MACD values from a fixed price series); agent-level tests asserting the LLM call *always* returns schema-valid JSON (retry-with-repair on validation failure) and that `confidence` and `signal_score` are populated as genuinely independent fields (not the same number restated) and correlate sanely with the underlying signal scores on a handful of manually reviewed tickers.

### Phase 3 — Supervisor / Aggregation Layer
**Build:** `orchestration/graph.py` wiring all eight specialist-agent nodes (each a no-op for asset classes where it doesn't apply, per the §0 applicability matrix) → bull/bear debate → risk-manager → `aggregate.py`; `aggregate.py` implements the §10.1–§10.2 weighting table/blend/`vol_conf_multiplier`-gate/dispersion-penalty/veto algorithm verbatim (see §4 below), not a simplified stand-in; `orchestration/state.py` finalized to hold a `specialist_verdicts` dict keyed by agent name plus a stable `recommendation_id`; cross-day `memory_store.py` so the risk manager can see yesterday's verdict for the same ticker.
**Test:** run the full graph on a frozen historical date for 5–10 known tickers (spanning all three asset classes, so US/JP/crypto each exercise their own weight row) and manually sanity-check that the aggregation math matches hand-computed expectations from §10.2; adversarial test — feed intentionally conflicting specialist verdicts and confirm `overall_confidence` drops via the dispersion penalty (not via score magnitude) and the risk-manager veto/reduce_size gate fires correctly; confirm checkpoint/resume works after a simulated crash mid-run.

### Phase 4 — Backtesting & Validation
**Build:** `backtesting/run_backtest.py` (vectorbt for fast signal-level testing + bt/zipline-reloaded for portfolio-level realism with slippage/commissions) for equities; `run_backtest_crypto.py` on freqtrade for the crypto leg; `walk_forward.py` implementing rolling walk-forward splits; `robustness.py` computing Deflated Sharpe Ratio, PBO estimate, and Minimum Track Record Length before any strategy variant is allowed to "graduate" into the live agent set.
**Test:** every signal in `signals/` gets a walk-forward backtest with out-of-sample-only reporting; require DSR/PBO checks to run against every parameter set actually trialed (not just the winner) to guard against the exact overfitting failure mode documented in the risk-validation research; explicitly test on point-in-time historical constituents (not "today's S&P 500 applied to 2019") to avoid survivorship bias.

### Phase 5 — News/Alerting Integration
**Build:** `alerting/news_watch/edgar_feed.py` (real-time, free, keyless Atom polling), `tdnet_scraper.py` (HTML scrape, no feed exists for TSE), `rss_aggregator.py` (CoinDesk/CoinTelegraph/MarketWatch/CNBC/Japan Times/NHK), `sentiment_finbert.py` (local FinBERT first pass, local LLM second pass on the subset crossing a relevance threshold); `telegram_bot.py` and `desktop_notify.py` as delivery channels; explicit exclusion of X/Twitter (no free tier exists in 2026) and NewsAPI.org production use (ToS forbids it).
**Test:** confirm EDGAR poller correctly de-dupes and respects the 10 req/sec + User-Agent policy; confirm TDnet scraper survives a schema change gracefully (log-and-skip, don't crash the whole run); end-to-end test that a synthetic "high-severity" filing/news event triggers a Telegram message within the expected latency budget.

### Phase 6 — Paper-Trading Dry Run
**Build:** `scripts/run_daily_scan.py` as the production entrypoint, scheduled via `scheduler/jobs.py` + launchd; full graph runs against live (delayed/free-tier) data daily, writes every recommendation + component breakdown to `storage/recommendations.db`, but the human manually "papers" the trade in a spreadsheet/`ui/review_cli.py` rather than real capital.
**Test:** Phase 6 is not complete until §5's gate is met: a minimum of 8–12 weeks of continuous forward-testing, or a minimum of ~30 completed simulated trades per strategy, whichever is longer, with a logged paper-vs-backtest Sharpe/profit-factor comparison below the divergence threshold defined in §5 (`section_risk_validation.md` §5 is the single source of truth for this gate — restating a looser version here, or calling Phase 6 done sooner, is not acceptable). Before any real capital is committed, also compare paper-trade outcomes against backtest expectations to catch free-tier-data-specific gaps (delayed J-Quants free tier, Yahoo 429s, EDGAR-vs-TDnet asymmetry) that a backtest can't fully capture; track realized vs. backtested slippage.

### Phase 7 — Human Review Workflow & Fine-Tuning Loop
**Build:** `ui/review_cli.py` implements two explicit, separately-invoked flows rather than one conflated command, because they answer different questions at different times:
  - **(a) `review_cli.py approve|reject <recommendation_id>`** — the pre-alert, same-day gate deciding whether a recommendation is even sent/acted on. Surfaces the pending recommendation waiting at the `interrupt()` checkpoint (full rationale/component breakdown from `state["specialist_verdicts"]` + `state["aggregated"]`) and resumes the graph via `Command(resume="approved"|"rejected")` against that same run's LangGraph `thread_id`. This is the *only* flow that can ever cause `alerting/` to fire.
  - **(b) `review_cli.py log-outcome <ticker> <date>`** — a separate flow, invoked any time later (days or weeks after the fact) once the human has actually traded (or decided not to). It has no interaction with `interrupt()`/`Command(resume=...)` at all. Outcomes are matched back to the original recommendation by `recommendation_id`: every row written to `storage/recommendations.db` is keyed by `recommendation_id = f"{ticker}-{as_of_date}"`, the same string used as the graph's `thread_id` (see §4's `run_for_ticker`), so `log-outcome <ticker> <date>` deterministically reconstructs that id, looks up the matching recommendation row, and appends `actual_entry_price/actual_exit_price/human_action: followed|modified|ignored/realized_pnl` to `storage/outcomes.db` under that same `recommendation_id`.
  - **(c) `review_cli.py pending-outcomes --older-than 90d`** — a reporting-only command: joins `recommendations.db` (rows with `human_decision == "approved"`) against `outcomes.db` on `recommendation_id`, and lists every approved recommendation older than 90 days with no matching outcomes row yet, so trades the human never got around to logging are visible in Phase 7's fine-tuning loop rather than silently absent from the scorecards.
  A periodic (e.g., monthly) `backtesting/robustness.py` re-run against the accumulating `outcomes.db` log checks whether the weighting table / veto thresholds implemented in `orchestration/aggregate.py` (per `section_agents.md` §10.1–§10.2) need retuning, and whether any `config/strategies/*.yaml` parameter has decayed (per the seasonality-effect-shrinking and PEAD-decay caveats in the research).
**Test:** confirm no recommendation is ever written to `alerting/` without passing through the `interrupt()`/human-approval node (this is the single most important regression test in the whole system — assert programmatically, not just by convention, that the graph has no path from `aggregate.py` to any alert node that bypasses the interrupt); confirm `review_cli.py log-outcome` correctly joins a known `recommendation_id` weeks after the original run and rejects/flags an unknown one; confirm `pending-outcomes --older-than 90d` correctly flags a synthetic approved-but-unlogged recommendation while excluding rejected and already-logged ones; confirm the fine-tuning loop only adjusts documented, logged config values (never silently changes agent code) so every behavior change is auditable.

---

## 4. Core Orchestration Loop (Illustrative Pseudo-code)

> **Note:** the `aggregate.py`/`graph.py` sketch below implements the `PortfolioSupervisorAgent` weighting/blend/veto algorithm from `section_agents.md` §10.1–§10.2 **verbatim**. An earlier draft of this file had a simplified, incompatible 3-role sketch here (fixed `analyst`/`quant`/`risk` weights of `0.3`/`0.4`/`0.3`, and a `confidence = f(weighted_avg)` formula that conflated confidence with score magnitude — exactly the anti-pattern `section_agents.md` §0 forbids). That sketch has been fully replaced; `section_agents.md` §10 remains the single source of truth for this math, and this code should be read as one concrete implementation of it, not a competing design.

```python
# orchestration/state.py
from typing import TypedDict, Literal
from agents.schemas import AgentVerdict

class ScanState(TypedDict):
    ticker: str
    asset_class: Literal["us_equity", "jp_equity", "crypto"]
    as_of_date: str
    recommendation_id: str        # == LangGraph thread_id; persisted to
                                   # storage/recommendations.db and used by
                                   # `ui/review_cli.py log-outcome` (§Phase 7)
                                   # to match a later human-entered outcome
                                   # back to this exact run
    market_data: dict
    # Keyed by agent_name (e.g. "TrendMomentumAgent"). Only the agents active
    # for this asset_class per section_agents.md §0's applicability matrix are
    # ever populated here -- a missing key means "not applicable to this
    # asset class", not "neutral 0.0", and aggregate.py treats it that way.
    specialist_verdicts: dict[str, AgentVerdict]
    bull_case: str | None
    bear_case: str | None
    risk_verdict: AgentVerdict | None   # RiskManagerAgent: veto / reduce_size / none (§9, §10.1)
    aggregated: dict | None             # orchestration/aggregate.py output, per agents §10.5 schema
    human_decision: Literal["approved", "rejected", "pending"]
```

```python
# agents/schemas.py
#
# Shared JSON envelope per section_agents.md §0. All eight directional
# specialists (mean_reversion, trend_momentum, seasonality, short_squeeze,
# volatility_volume, crypto_onchain, crypto_derivatives, news_sentiment)
# return an AgentVerdict. RiskManagerAgent reuses the same envelope but is a
# gate/modifier, not a directional voter (§0) -- its risk_signal/veto_reason/
# max_position_size_currency fields are what aggregate.py actually consumes.
from pydantic import BaseModel, Field
from typing import Literal

class AgentVerdict(BaseModel):
    agent_name: str
    asset_class: Literal["us_equity", "jp_equity", "crypto"]
    ticker: str
    as_of_timestamp: str
    signal_score: float = Field(ge=-1.0, le=1.0)   # NOT the same thing as confidence (§0)
    confidence: float = Field(ge=0.0, le=1.0)       # reliability of the reading, not its extremity
    suggested_holding_period: dict
    stop_loss: dict
    profit_target: dict
    rationale: str
    sub_scores: dict[str, float] = {}
    regime_gate_applied: str | None = None
    data_quality_flag: Literal["ok", "stale", "partial", "unavailable"] = "ok"
    event_flag: bool = False
    # RiskManagerAgent-only fields (§9); left at default for the other 8 agents:
    risk_signal: Literal["none", "reduce_size", "veto"] = "none"
    veto_reason: str | None = None
    max_position_size_currency: float | None = None
```

```python
# orchestration/graph.py
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command

from orchestration.state import ScanState
from orchestration.aggregate import aggregate_verdicts
from agents.mean_reversion_agent import run_mean_reversion
from agents.trend_momentum_agent import run_trend_momentum
from agents.seasonality_agent import run_seasonality
from agents.short_squeeze_agent import run_short_squeeze
from agents.volatility_volume_agent import run_volatility_volume
from agents.crypto_onchain_agent import run_crypto_onchain
from agents.crypto_derivatives_agent import run_crypto_derivatives
from agents.news_sentiment_agent import run_news_sentiment
from agents.bull_researcher import run_bull_case
from agents.bear_researcher import run_bear_case
from agents.risk_manager_agent import run_risk_manager
from agents.portfolio_supervisor_agent import synthesize_rationale
from alerting.telegram_bot import send_alert

# One node per specialist in section_agents.md §1-§8. Every node runs for
# every asset class -- applicability is enforced INSIDE each node (per the §0
# matrix), not by varying the graph's topology: a crypto ticker's
# short_squeeze_node simply writes nothing, a US-equity ticker's
# crypto_onchain_node simply writes nothing. This keeps one static graph
# instead of three near-duplicate ones, and matches ASSET_CLASS_WEIGHTS in
# aggregate.py, which only expects a verdict for agents actually applicable.
def _specialist_node(agent_name: str, runner, applicable_classes: frozenset[str]):
    def _node(state: ScanState) -> dict:
        if state["asset_class"] not in applicable_classes:
            return {}
        verdict = runner(state)
        return {"specialist_verdicts": {**state.get("specialist_verdicts", {}), agent_name: verdict}}
    return _node

EQUITY_AND_CRYPTO = frozenset({"us_equity", "jp_equity", "crypto"})

mean_reversion_node = _specialist_node("MeanReversionAgent", run_mean_reversion, EQUITY_AND_CRYPTO)
trend_momentum_node = _specialist_node("TrendMomentumAgent", run_trend_momentum, EQUITY_AND_CRYPTO)
seasonality_node = _specialist_node("SeasonalityAgent", run_seasonality, EQUITY_AND_CRYPTO)
short_squeeze_node = _specialist_node("ShortSqueezeAgent", run_short_squeeze, frozenset({"us_equity", "jp_equity"}))
volatility_volume_node = _specialist_node("VolatilityVolumeAgent", run_volatility_volume, EQUITY_AND_CRYPTO)
crypto_onchain_node = _specialist_node("CryptoOnChainAgent", run_crypto_onchain, frozenset({"crypto"}))
crypto_derivatives_node = _specialist_node("CryptoDerivativesAgent", run_crypto_derivatives, frozenset({"crypto"}))
news_sentiment_node = _specialist_node("NewsSentimentAgent", run_news_sentiment, EQUITY_AND_CRYPTO)

def debate_node(state: ScanState) -> dict:
    bull = run_bull_case(state)
    bear = run_bear_case(state)
    return {"bull_case": bull, "bear_case": bear}

def risk_node(state: ScanState) -> dict:
    # RiskManagerAgent: veto / reduce_size / none -- a gate/modifier, not a
    # weighted vote (agents §9, §10.1).
    return {"risk_verdict": run_risk_manager(state)}

def aggregate_node(state: ScanState) -> dict:
    # Deterministic Python (agents §10.2), NOT another LLM call. Implements:
    # confidence-weighted blend -> vol_conf_multiplier gate -> dispersion
    # penalty -> squeeze/event-flag special cases -> RiskManagerAgent
    # veto/reduce_size. See orchestration/aggregate.py below for the math.
    result = aggregate_verdicts(
        asset_class=state["asset_class"],
        specialist_verdicts=state["specialist_verdicts"],
        risk_verdict=state["risk_verdict"],
    )
    # The ONE LLM step in this node: PortfolioSupervisorAgent's rationale
    # persona (agents §10, "Persona and prompt behavior") writes the
    # human-facing narrative only -- it never touches blended_score /
    # overall_confidence / final_call, which are already fixed above.
    result["rationale"] = synthesize_rationale(state, result)
    return {"aggregated": result}

def human_gate_node(state: ScanState) -> dict:
    # Pauses the graph; state is persisted via the checkpointer and survives
    # a process restart until a human calls Command(resume=...). This is the
    # pre-alert, same-day gate ONLY -- see `ui/review_cli.py approve|reject`
    # (§Phase 7). Post-trade outcome logging is a separate, later flow
    # (`review_cli.py log-outcome`) keyed off state["recommendation_id"],
    # with no interaction with this interrupt at all.
    decision = interrupt({
        "recommendation_id": state["recommendation_id"],
        "ticker": state["ticker"],
        "recommendation": state["aggregated"],
        "rationale": {
            "specialist_verdicts": state["specialist_verdicts"],
            "risk_verdict": state["risk_verdict"],
        },
    })
    return {"human_decision": decision}

def alert_node(state: ScanState) -> dict:
    # Only reachable if human_decision == "approved".
    # NOTE: no trade-execution tool exists anywhere in this codebase.
    send_alert(state["ticker"], state["recommendation_id"], state["aggregated"])
    return {}

def route_after_gate(state: ScanState) -> str:
    return "alert" if state["human_decision"] == "approved" else END

def build_graph():
    g = StateGraph(ScanState)
    for name, node in [
        ("mean_reversion", mean_reversion_node),
        ("trend_momentum", trend_momentum_node),
        ("seasonality", seasonality_node),
        ("short_squeeze", short_squeeze_node),
        ("volatility_volume", volatility_volume_node),
        ("crypto_onchain", crypto_onchain_node),
        ("crypto_derivatives", crypto_derivatives_node),
        ("news_sentiment", news_sentiment_node),
        ("debate", debate_node),
        ("risk", risk_node),
        ("aggregate", aggregate_node),
        ("human_gate", human_gate_node),
        ("alert", alert_node),
    ]:
        g.add_node(name, node)

    # The eight specialist nodes have no data dependency on each other, so a
    # production graph would fan them out concurrently (e.g. LangGraph
    # `Send()`/map-reduce); chained sequentially below purely to keep this
    # pseudocode readable.
    g.set_entry_point("mean_reversion")
    g.add_edge("mean_reversion", "trend_momentum")
    g.add_edge("trend_momentum", "seasonality")
    g.add_edge("seasonality", "short_squeeze")
    g.add_edge("short_squeeze", "volatility_volume")
    g.add_edge("volatility_volume", "crypto_onchain")
    g.add_edge("crypto_onchain", "crypto_derivatives")
    g.add_edge("crypto_derivatives", "news_sentiment")
    g.add_edge("news_sentiment", "debate")
    g.add_edge("debate", "risk")
    g.add_edge("risk", "aggregate")
    g.add_edge("aggregate", "human_gate")
    g.add_conditional_edges("human_gate", route_after_gate, {"alert": "alert", END: END})
    g.add_edge("alert", END)

    checkpointer = SqliteSaver.from_conn_string("orchestration/checkpoints.db")
    return g.compile(checkpointer=checkpointer)

# scripts/run_daily_scan.py (entrypoint invoked by launchd)
def run_for_ticker(graph, ticker: str, asset_class: str, as_of_date: str):
    thread_id = f"{ticker}-{as_of_date}"     # new thread per day = fresh short-term state
    recommendation_id = thread_id            # same id is written to storage/recommendations.db;
                                              # `ui/review_cli.py log-outcome <ticker> <date>`
                                              # (§Phase 7) reconstructs this exact string from
                                              # (ticker, date) to match a later-logged real-world
                                              # outcome back to this specific run
    config = {"configurable": {"thread_id": thread_id}}
    graph.invoke(
        {
            "ticker": ticker, "asset_class": asset_class, "as_of_date": as_of_date,
            "recommendation_id": recommendation_id, "specialist_verdicts": {},
        },
        config=config,
    )
    # Later, same day, from `ui/review_cli.py approve|reject <recommendation_id>`:
    # graph.invoke(Command(resume="approved"), config=config)
    # Separately, days/weeks later, from `ui/review_cli.py log-outcome <ticker> <date>`:
    # this does NOT call graph.invoke/Command at all -- it writes directly to
    # storage/outcomes.db keyed by recommendation_id (§Phase 7 above).
```

### Superseded illustrative example (predates the 10-agent split — kept only to show the "signals in Python, LLM writes the rationale" pattern)

The snippet below is an **earlier, now-superseded** sketch: it names a single monolithic `quant_technical.py` agent and an old `SpecialistVerdict(signal, conviction, ...)` schema, both predating `section_agents.md`'s split into `TrendMomentumAgent`/`MeanReversionAgent`/etc. and its `signal_score`/`confidence` envelope (§0) defined above. It is **not** wired into the current `graph.py`/`aggregate.py` above and should not be implemented as written — it is retained only because the underlying pattern (pre-compute deterministic signal scores, hand them to an LLM constrained to a structured schema for interpretation/rationale, don't let the LLM invent numbers) is still exactly how each of the eight real specialist agents in `section_agents.md` §1–§8 is meant to be built.

```python
# SUPERSEDED — do not use agents/schemas.py::SpecialistVerdict or agents/quant_technical.py
# as written below; see agents/schemas.py::AgentVerdict above for the current schema, and
# section_agents.md §2 (TrendMomentumAgent) / §1 (MeanReversionAgent) for the current split
# of what this single "quant_technical" agent used to do.
from pydantic import BaseModel, Field
from typing import Literal

class SpecialistVerdict(BaseModel):
    signal: Literal["BUY", "SELL", "HOLD"]
    conviction: float = Field(ge=0, le=1)
    rationale: str
    key_risks: list[str]
    suggested_holding_period_days: int
    target_price: float | None = None
    stop_loss: float | None = None
```

```python
# SUPERSEDED — see note above.
from signals.ta.trend_momentum import adx, macd_score, ma_cross_score
from signals.ta.mean_reversion import rsi2_score, bollinger_pctb_score
from signals.volatility_volume import atr_expansion_score, rvol_score
from agents.schemas import SpecialistVerdict
from agents.llm_client import call_llm_structured

QUANT_SYSTEM_PROMPT = """You are the quant/technical specialist in a manual
trading research system. You are given pre-computed, already-normalized
technical signal scores (each roughly in [-1, 1]) for one ticker. Combine
them into a single structured verdict. Do NOT invent additional technical
claims beyond what the provided scores support. Weight regime gating
(ADX-based trend/mean-reversion switch) as instructed. Output must conform
exactly to the SpecialistVerdict schema."""

def run_quant_technical(state: dict) -> SpecialistVerdict:
    md = state["market_data"]
    adx_val = adx(md["high"], md["low"], md["close"])
    trend_confidence = max(0.0, min(1.0, (adx_val - 20) / 30))

    trend_score = macd_score(md) * trend_confidence + ma_cross_score(md) * trend_confidence
    reversion_score = (
        rsi2_score(md) + bollinger_pctb_score(md)
    ) * (1 - trend_confidence)

    vol_confirm = (atr_expansion_score(md) + rvol_score(md)) / 2
    directional_score = trend_score + reversion_score
    final_score = directional_score * (0.5 + 0.5 * vol_confirm)

    payload = {
        "ticker": state["ticker"],
        "adx": adx_val,
        "trend_confidence": trend_confidence,
        "final_score": round(final_score, 3),
        "component_scores": {
            "trend_score": round(trend_score, 3),
            "reversion_score": round(reversion_score, 3),
            "vol_confirm": round(vol_confirm, 3),
        },
    }

    return call_llm_structured(
        system_prompt=QUANT_SYSTEM_PROMPT,
        user_payload=payload,
        response_model=SpecialistVerdict,
    )
```

### Deterministic Aggregation (`section_agents.md` §10.1–§10.2, implemented verbatim)

```python
# orchestration/aggregate.py
#
# Single authoritative implementation of the PortfolioSupervisorAgent's
# weighting/blend/veto algorithm -- section_agents.md §10.1-§10.2, verbatim.
# This REPLACES the older 3-role (analyst/quant/risk, fixed 0.3/0.4/0.3)
# sketch that used to live here, which conflated confidence with score
# magnitude and never modeled the 8 asset-class-specific specialists -- both
# exactly the anti-patterns agents §0/§10 rule out. There is now one
# aggregation implementation, not two incompatible ones.
import statistics
from agents.schemas import AgentVerdict

# section_agents.md §10.1 weighting table. Values are relative, not required
# to sum to 1.0 per column as written in that table (US equity sums to 1.00,
# JP to 0.90, crypto to 1.10 below) -- Step 1's division by weight_norm
# self-normalizes regardless, since blended_score = weighted_sum / weight_norm.
ASSET_CLASS_WEIGHTS: dict[str, dict[str, float]] = {
    "us_equity": {
        "TrendMomentumAgent": 0.28, "MeanReversionAgent": 0.18,
        "ShortSqueezeAgent": 0.14, "SeasonalityAgent": 0.08,
        "NewsSentimentAgent": 0.22, "VolatilityVolumeAgent": 0.10,
    },
    "jp_equity": {
        "TrendMomentumAgent": 0.28, "MeanReversionAgent": 0.18,
        "ShortSqueezeAgent": 0.08,   # degraded JP short-interest data
        "SeasonalityAgent": 0.08, "NewsSentimentAgent": 0.18,  # thinner JP feed
        "VolatilityVolumeAgent": 0.10,
    },
    "crypto": {
        "TrendMomentumAgent": 0.22, "MeanReversionAgent": 0.15,
        "SeasonalityAgent": 0.05, "NewsSentimentAgent": 0.15,
        "CryptoOnChainAgent": 0.20, "CryptoDerivativesAgent": 0.23,
        "VolatilityVolumeAgent": 0.10,
    },
}
# NOTE: VolatilityVolumeAgent's 0.10 weight above is its direct weighted vote.
# Its vol_conf_multiplier (Step 2) is a SEPARATE, second use of the same
# agent's output -- deliberately double-counted per agents §10.1.
# RiskManagerAgent is intentionally absent from this table: it is a
# veto/reduce_size gate (§9, §10.1), never a weighted vote.

DISPERSION_CONFIDENCE_FLOOR = 0.3     # only agents with confidence > this count toward dispersion
DISAGREEMENT_PENALTY_DIVISOR = 0.7    # dispersion / 0.7, clipped to [0, 0.6]
DISAGREEMENT_PENALTY_CAP = 0.6
SQUEEZE_WARNING_THRESHOLD = 0.6
# §10.3 decision bands -- deliberately conservative and, per that section's
# own rationale, should be tunable config (thresholds.* in config.yaml), not
# hardcoded as below in the real implementation.
BUY_SELL_THRESHOLD = 0.35
WATCH_THRESHOLD = 0.20
MIN_CONFIDENCE_FOR_A_CALL = 0.50


def aggregate_verdicts(
    asset_class: str,
    specialist_verdicts: dict[str, AgentVerdict],
    risk_verdict: AgentVerdict,
) -> dict:
    weights = ASSET_CLASS_WEIGHTS[asset_class]

    # --- Step 1: confidence-weighted directional blend ---
    weighted_sum = 0.0
    weight_norm = 0.0
    component_breakdown = []
    for agent_name, base_weight in weights.items():
        verdict = specialist_verdicts.get(agent_name)
        if verdict is None:
            continue  # not applicable / didn't run for this ticker -- excluded, not zero
        contribution = base_weight * verdict.signal_score * verdict.confidence
        weighted_sum += contribution
        weight_norm += base_weight * verdict.confidence
        component_breakdown.append({
            "agent": agent_name, "score": verdict.signal_score,
            "confidence": verdict.confidence, "weight": base_weight,
            "contribution": contribution,
        })
    blended_score = weighted_sum / weight_norm if weight_norm > 0 else 0.0

    # --- Step 2: volatility/volume confirmation gate ---
    vol_agent = specialist_verdicts.get("VolatilityVolumeAgent")
    vol_conf_multiplier = vol_agent.sub_scores.get("vol_conf_multiplier", 1.0) if vol_agent else 1.0
    blended_score *= vol_conf_multiplier

    # --- Step 3: dispersion / disagreement penalty ---
    scores = [v.signal_score for v in specialist_verdicts.values() if v.confidence > DISPERSION_CONFIDENCE_FLOOR]
    dispersion = statistics.pstdev(scores) if len(scores) > 1 else 0.0
    disagreement_penalty = min(max(dispersion / DISAGREEMENT_PENALTY_DIVISOR, 0.0), DISAGREEMENT_PENALTY_CAP)
    # weight_norm_avg_confidence: §10.2 names this term without spelling out its
    # exact normalization; this illustrative version scales weight_norm by the
    # asset class's total nominal weight so it stays roughly in [0, 1].
    weight_norm_avg_confidence = weight_norm / sum(weights.values()) if weight_norm else 0.0
    # data_quality_multiplier: illustrative mapping (exact thresholds belong in
    # config.yaml, not hardcoded); "unavailable" agents are excluded above already.
    quality_scores = [
        1.0 if v.data_quality_flag == "ok" else 0.5 if v.data_quality_flag == "stale" else 0.2
        for v in specialist_verdicts.values()
    ]
    data_quality_multiplier = min(quality_scores) if quality_scores else 0.0
    overall_confidence = weight_norm_avg_confidence * (1 - disagreement_penalty) * data_quality_multiplier

    # --- Step 4: special-case additive flags (never blended into the score) ---
    flags = []
    squeeze = specialist_verdicts.get("ShortSqueezeAgent")
    if squeeze and squeeze.signal_score > SQUEEZE_WARNING_THRESHOLD:
        # Widens upside-tail awareness / tightens stops only -- never flips a bearish
        # blended_score bullish (agents §10.2 step 4, §10.4's ShortSqueeze reconciliation example).
        flags.append("elevated squeeze risk")
    stop_widen_pct = 0.0
    if any(v.event_flag for v in specialist_verdicts.values()):
        stop_widen_pct = 0.25  # widen recommended stop distance by +25-50%; agent's discretion picks the exact value within that band

    # --- Step 5: RiskManagerAgent veto / reduce_size (hard override, not a vote) ---
    if risk_verdict.risk_signal == "veto":
        final_call = "HOLD"
        final_confidence = risk_verdict.confidence
        override_reason = risk_verdict.veto_reason
        max_position_size = 0.0
    else:
        final_call = _decision_from_blended_score(blended_score, overall_confidence)
        final_confidence = overall_confidence
        override_reason = None
        max_position_size = (
            risk_verdict.max_position_size_currency
            if risk_verdict.risk_signal == "reduce_size" else None
        )
        # TODO(agents §9-adjacent, forthcoming MarketRegimeAgent): once that
        # gate/modifier agent is specified, apply its system-wide position-size
        # multiplier here too, alongside RiskManagerAgent's cap. Its interface
        # is not yet defined in section_agents.md -- do not invent it here.

    return {
        "asset_class": asset_class,
        "final_call": final_call,
        "blended_score": round(blended_score, 3),
        "overall_confidence": round(final_confidence, 3),
        "component_breakdown": component_breakdown,
        "disagreement_penalty_applied": round(disagreement_penalty, 3),
        "risk_manager_override": risk_verdict.risk_signal,
        "flags": flags,
        "stop_widen_pct": stop_widen_pct,
        "stop_loss": risk_verdict.stop_loss,
        "profit_target": risk_verdict.profit_target,
        "max_position_size_currency": max_position_size,
        "override_reason": override_reason,
        "human_action_required": True,   # never consumed by any execution tool -- see §1.2
    }


def _decision_from_blended_score(blended_score: float, overall_confidence: float) -> str:
    # section_agents.md §10.3 decision bands.
    if overall_confidence < MIN_CONFIDENCE_FOR_A_CALL:
        return "HOLD"
    if blended_score >= BUY_SELL_THRESHOLD:
        return "BUY"
    if blended_score <= -BUY_SELL_THRESHOLD:
        return "SELL"
    if abs(blended_score) >= WATCH_THRESHOLD:
        return "WATCH"
    return "HOLD"
```

---

## 5. Config File Design

Single master `config/config.yaml` referencing sub-files, with **no real secrets ever committed** — all API keys pulled from environment variables (`.env`, gitignored) via `${VAR_NAME}` interpolation.

```yaml
# config/config.yaml
system:
  environment: local
  timezone: Asia/Tokyo          # affects which "session close" triggers daily scan
  log_level: INFO
  storage:
    recommendations_db: storage/recommendations.db
    outcomes_db: storage/outcomes.db
    checkpoint_db: orchestration/checkpoints.db

asset_classes:
  us_equity:
    enabled: true
    watchlist_file: config/watchlists/us_equities.yaml
    strategy_files: [config/strategies/mean_reversion.yaml,
                      config/strategies/trend_momentum.yaml,
                      config/strategies/seasonality.yaml,
                      config/strategies/squeeze.yaml]
  jp_equity:
    enabled: true
    watchlist_file: config/watchlists/jp_equities.yaml
    strategy_files: [config/strategies/mean_reversion.yaml,
                      config/strategies/trend_momentum.yaml]
    notes: "J-Quants free tier is 12wk-lagged; treat as reference-only, not live signal"
  crypto:
    enabled: true
    watchlist_file: config/watchlists/crypto.yaml
    strategy_files: [config/strategies/crypto_factors.yaml]

data_sources:
  us_equity_primary: yfinance
  us_equity_fallback: [twelvedata, tiingo]
  jp_equity_primary: jquants_free
  jp_equity_fallback: [yahoo_unofficial]
  crypto_ohlcv: ccxt_binance_public
  api_keys:
    alpha_vantage: ${ALPHA_VANTAGE_API_KEY}
    twelvedata: ${TWELVEDATA_API_KEY}
    tiingo: ${TIINGO_API_KEY}
    finnhub: ${FINNHUB_API_KEY}
    jquants: ${JQUANTS_API_KEY}
    edinet: ${EDINET_SUBSCRIPTION_KEY}
  rate_limits:                  # enforced in code, not just documentation
    alpha_vantage_per_day: 25
    jquants_per_min: 5
    twelvedata_per_day: 800
    tiingo_per_day: 1000
    sec_edgar_per_sec: 10

thresholds:
  min_conviction_to_alert: 0.5
  min_confidence_to_alert: 0.4
  adx_trend_cutoff: 22
  short_squeeze_watch_score: 0.6
  risk_veto_conviction: 0.7
  disagreement_penalty_cap: 1.0

risk_management:
  account_equity_jpy: 100000
  max_risk_per_trade_pct: 1.0     # fixed-fractional; see risk-validation research
  kelly_fraction_cap: 0.25        # never exceed 1/4 Kelly even if the model suggests more
  stop_loss_method: atr_multiple
  atr_stop_multiple_swing: 2.5
  atr_stop_multiple_daytrade: 1.5
  max_position_pct_of_equity: 20.0

schedules:
  daily_scan:
    cron: "0 16 30 * * MON-FRI"    # example; actual times set per asset-class session close
    scheduler: apscheduler_3       # explicitly not 4.0 (still alpha as of Aug 2026)
  news_poll:
    interval_minutes: 5
  weekly_robustness_check:
    cron: "0 8 * * SUN"

alerting:
  channels:
    telegram:
      enabled: true
      bot_token: ${TELEGRAM_BOT_TOKEN}
      chat_id: ${TELEGRAM_CHAT_ID}
    desktop_notification:
      enabled: true
    email:
      enabled: false
  never_auto_execute: true         # documentation flag only; the real guarantee is
                                    # the absence of any execution tool in code

llm:
  provider: ollama                 # or "anthropic", "openai" via config swap
  model: qwen2.5:7b
  temperature: 0.1
  fallback_provider: null

backtesting:
  walk_forward:
    window_type: rolling
    in_sample_days: 252
    out_of_sample_days: 63
  robustness_gates:
    min_deflated_sharpe: 0.5
    max_pbo: 0.4
    min_track_record_days: 180
```

Per-watchlist files (`config/watchlists/us_equities.yaml`) hold just symbol lists plus per-symbol overrides (e.g., a tighter stop multiple for a known-volatile small-cap); per-strategy files (`config/strategies/*.yaml`) hold the tunable numeric parameters called out throughout the TA/crypto research (RSI-2 thresholds, Bollinger K, ADX cutoffs, squeeze sub-score weights, MVRV percentile bands, etc.) so a strategy can be retuned in Phase 7 without touching any Python code — every parameter change is then a diffable, auditable config commit rather than a silent code edit.