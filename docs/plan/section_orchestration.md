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
- **Deterministic, auditable aggregation function** (plain Python, not an LLM) computes a weighted signal + confidence score, with (a) a **risk-manager veto** (a strong-conviction SELL/avoid from the risk manager overrides the numeric average) and (b) a **disagreement penalty** (confidence drops when specialists disagree, even if the naive weighted average is positive).
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
│   │   ├── crypto_onchain_glassnode.py  # MVRV/SOPR (free Community tier)
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
│   ├── schemas.py                   # SpecialistVerdict Pydantic model (shared contract)
│   ├── financial_analyst.py         # fundamentals/news-driven specialist
│   ├── quant_technical.py           # TA/quant specialist (see §5.2 example)
│   ├── risk_manager.py              # position sizing, stop/target, veto logic
│   ├── bull_researcher.py           # debate role
│   ├── bear_researcher.py           # debate role
│   └── llm_client.py                # thin wrapper: Ollama local / cheap API, swappable
├── orchestration/
│   ├── state.py                     # LangGraph State TypedDict/Pydantic definition
│   ├── graph.py                     # build_graph(): nodes, edges, interrupt points (§5.1)
│   ├── aggregate.py                 # deterministic weighted-score + veto + disagreement fn
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
│   ├── recommendations.db           # SQLite: append-only log of every scored recommendation
│   └── outcomes.db                  # human-recorded actual entries/exits, for fine-tuning
├── scheduler/
│   ├── jobs.py                      # APScheduler 3.x job definitions
│   └── com.marketalpha.dailyrun.plist  # macOS launchd supervisor plist
├── ui/
│   └── review_cli.py                # human-review console: approve/reject/annotate
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
- **`agents/`** — LLM-backed specialists that consume `signals/` outputs plus fundamentals/news context and produce the shared `SpecialistVerdict` structured object.
- **`orchestration/`** — the LangGraph graph definition, state schema, deterministic aggregation math, and the two persistence layers (checkpointer for run durability, store for cross-day memory).
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
**Build:** `signals/` math implementations first (pure functions, no LLM) — mean-reversion, trend/momentum, seasonality, squeeze composite, volatility/volume gating, crypto composite; then wrap each specialist agent (`financial_analyst.py`, `quant_technical.py`) around these signals plus an LLM call constrained to the `SpecialistVerdict` schema; `agents/llm_client.py` abstracts local Ollama (e.g., Qwen2.5/Phi-4-mini for cheap iteration) vs. a paid API, swappable via config.
**Test:** unit tests on `signals/` with hand-computed fixture data (known RSI-2/ADX/MACD values from a fixed price series); agent-level tests asserting the LLM call *always* returns schema-valid JSON (retry-with-repair on validation failure) and that conviction/signal correlate sanely with the underlying signal scores on a handful of manually reviewed tickers.

### Phase 3 — Supervisor / Aggregation Layer
**Build:** `orchestration/graph.py` wiring financial-analyst → quant-technical → bull/bear debate → risk-manager → `aggregate.py`; deterministic weighted-score function with veto + disagreement-penalty rules; `orchestration/state.py` finalized; cross-day `memory_store.py` so the risk manager can see yesterday's verdict for the same ticker.
**Test:** run the full graph on a frozen historical date for 5–10 known tickers and manually sanity-check that the aggregation math matches hand-computed expectations; adversarial test — feed intentionally conflicting specialist verdicts and confirm confidence drops and the risk-manager veto fires correctly; confirm checkpoint/resume works after a simulated crash mid-run.

### Phase 4 — Backtesting & Validation
**Build:** `backtesting/run_backtest.py` (vectorbt for fast signal-level testing + bt/zipline-reloaded for portfolio-level realism with slippage/commissions) for equities; `run_backtest_crypto.py` on freqtrade for the crypto leg; `walk_forward.py` implementing rolling walk-forward splits; `robustness.py` computing Deflated Sharpe Ratio, PBO estimate, and Minimum Track Record Length before any strategy variant is allowed to "graduate" into the live agent set.
**Test:** every signal in `signals/` gets a walk-forward backtest with out-of-sample-only reporting; require DSR/PBO checks to run against every parameter set actually trialed (not just the winner) to guard against the exact overfitting failure mode documented in the risk-validation research; explicitly test on point-in-time historical constituents (not "today's S&P 500 applied to 2019") to avoid survivorship bias.

### Phase 5 — News/Alerting Integration
**Build:** `alerting/news_watch/edgar_feed.py` (real-time, free, keyless Atom polling), `tdnet_scraper.py` (HTML scrape, no feed exists for TSE), `rss_aggregator.py` (CoinDesk/CoinTelegraph/MarketWatch/CNBC/Japan Times/NHK), `sentiment_finbert.py` (local FinBERT first pass, local LLM second pass on the subset crossing a relevance threshold); `telegram_bot.py` and `desktop_notify.py` as delivery channels; explicit exclusion of X/Twitter (no free tier exists in 2026) and NewsAPI.org production use (ToS forbids it).
**Test:** confirm EDGAR poller correctly de-dupes and respects the 10 req/sec + User-Agent policy; confirm TDnet scraper survives a schema change gracefully (log-and-skip, don't crash the whole run); end-to-end test that a synthetic "high-severity" filing/news event triggers a Telegram message within the expected latency budget.

### Phase 6 — Paper-Trading Dry Run
**Build:** `scripts/run_daily_scan.py` as the production entrypoint, scheduled via `scheduler/jobs.py` + launchd; full graph runs against live (delayed/free-tier) data daily, writes every recommendation + component breakdown to `storage/recommendations.db`, but the human manually "papers" the trade in a spreadsheet/`ui/review_cli.py` rather than real capital.
**Test:** run for a minimum of several weeks to a few months (per the risk-validation research's recommended forward-test runway) before any real capital is committed; compare paper-trade outcomes against backtest expectations to catch free-tier-data-specific gaps (delayed J-Quants free tier, Yahoo 429s, EDGAR-vs-TDnet asymmetry) that a backtest can't fully capture; track realized vs. backtested slippage.

### Phase 7 — Human Review Workflow & Fine-Tuning Loop
**Build:** `ui/review_cli.py` surfaces each pending recommendation at the `interrupt()` checkpoint with full rationale/score breakdown, accepts approve/reject/annotate; `storage/outcomes.db` captures what the human actually did and the eventual real outcome; a periodic (e.g., monthly) `backtesting/robustness.py` re-run against the accumulating real-world outcome log to check whether specialist weights/veto thresholds in `aggregate.py` need retuning, and whether any `config/strategies/*.yaml` parameter has decayed (per the seasonality-effect-shrinking and PEAD-decay caveats in the research).
**Test:** confirm no recommendation is ever written to `alerting/` without passing through the `interrupt()`/human-approval node (this is the single most important regression test in the whole system — assert programmatically, not just by convention, that the graph has no path from `aggregate.py` to any alert node that bypasses the interrupt); confirm the fine-tuning loop only adjusts documented, logged config values (never silently changes agent code) so every behavior change is auditable.

---

## 4. Core Orchestration Loop (Illustrative Pseudo-code)

```python
# orchestration/state.py
from typing import TypedDict, Literal
from agents.schemas import SpecialistVerdict

class ScanState(TypedDict):
    ticker: str
    asset_class: Literal["us_equity", "jp_equity", "crypto"]
    as_of_date: str
    market_data: dict
    analyst_verdict: SpecialistVerdict | None
    quant_verdict: SpecialistVerdict | None
    bull_case: str | None
    bear_case: str | None
    risk_verdict: SpecialistVerdict | None
    aggregated: dict | None
    human_decision: Literal["approved", "rejected", "pending"]
```

```python
# orchestration/graph.py
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command

from orchestration.state import ScanState
from orchestration.aggregate import aggregate_verdicts
from agents.financial_analyst import run_financial_analyst
from agents.quant_technical import run_quant_technical
from agents.bull_researcher import run_bull_case
from agents.bear_researcher import run_bear_case
from agents.risk_manager import run_risk_manager
from alerting.telegram_bot import send_alert

def analyst_node(state: ScanState) -> dict:
    return {"analyst_verdict": run_financial_analyst(state)}

def quant_node(state: ScanState) -> dict:
    return {"quant_verdict": run_quant_technical(state)}

def debate_node(state: ScanState) -> dict:
    bull = run_bull_case(state)
    bear = run_bear_case(state)
    return {"bull_case": bull, "bear_case": bear}

def risk_node(state: ScanState) -> dict:
    return {"risk_verdict": run_risk_manager(state)}

def aggregate_node(state: ScanState) -> dict:
    # Deterministic Python math, NOT another LLM call.
    result = aggregate_verdicts(
        analyst=state["analyst_verdict"],
        quant=state["quant_verdict"],
        risk=state["risk_verdict"],
    )
    return {"aggregated": result}

def human_gate_node(state: ScanState) -> dict:
    # Pauses the graph; state is persisted via the checkpointer and
    # survives a process restart until a human calls Command(resume=...).
    decision = interrupt({
        "ticker": state["ticker"],
        "recommendation": state["aggregated"],
        "rationale": {
            "analyst": state["analyst_verdict"],
            "quant": state["quant_verdict"],
            "risk": state["risk_verdict"],
        },
    })
    return {"human_decision": decision}

def alert_node(state: ScanState) -> dict:
    # Only reachable if human_decision == "approved".
    # NOTE: no trade-execution tool exists anywhere in this codebase.
    send_alert(state["ticker"], state["aggregated"])
    return {}

def route_after_gate(state: ScanState) -> str:
    return "alert" if state["human_decision"] == "approved" else END

def build_graph():
    g = StateGraph(ScanState)
    g.add_node("analyst", analyst_node)
    g.add_node("quant", quant_node)
    g.add_node("debate", debate_node)
    g.add_node("risk", risk_node)
    g.add_node("aggregate", aggregate_node)
    g.add_node("human_gate", human_gate_node)
    g.add_node("alert", alert_node)

    g.set_entry_point("analyst")
    g.add_edge("analyst", "quant")
    g.add_edge("quant", "debate")
    g.add_edge("debate", "risk")
    g.add_edge("risk", "aggregate")
    g.add_edge("aggregate", "human_gate")
    g.add_conditional_edges("human_gate", route_after_gate, {"alert": "alert", END: END})
    g.add_edge("alert", END)

    checkpointer = SqliteSaver.from_conn_string("orchestration/checkpoints.db")
    return g.compile(checkpointer=checkpointer)

# scripts/run_daily_scan.py (entrypoint invoked by launchd)
def run_for_ticker(graph, ticker: str, asset_class: str, as_of_date: str):
    thread_id = f"{ticker}-{as_of_date}"  # new thread per day = fresh short-term state
    config = {"configurable": {"thread_id": thread_id}}
    graph.invoke(
        {"ticker": ticker, "asset_class": asset_class, "as_of_date": as_of_date},
        config=config,
    )
    # Later, e.g. from ui/review_cli.py, once the human decides:
    # graph.invoke(Command(resume="approved"), config=config)
```

### Example Specialist Agent: Quant/Technical Agent

```python
# agents/schemas.py
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
# agents/quant_technical.py
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

### Deterministic Aggregation

```python
# orchestration/aggregate.py
from agents.schemas import SpecialistVerdict

SIGNAL_SIGN = {"BUY": 1, "HOLD": 0, "SELL": -1}
WEIGHTS = {"analyst": 0.3, "quant": 0.4, "risk": 0.3}
RISK_VETO_CONVICTION_THRESHOLD = 0.7

def aggregate_verdicts(analyst: SpecialistVerdict, quant: SpecialistVerdict,
                        risk: SpecialistVerdict) -> dict:
    scores = {
        "analyst": SIGNAL_SIGN[analyst.signal] * analyst.conviction,
        "quant": SIGNAL_SIGN[quant.signal] * quant.conviction,
        "risk": SIGNAL_SIGN[risk.signal] * risk.conviction,
    }
    weighted_avg = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)

    # Risk-manager veto (TradingAgents-style gate), not a naive average.
    veto = risk.signal == "SELL" and risk.conviction >= RISK_VETO_CONVICTION_THRESHOLD
    final_signal = "SELL" if veto else (
        "BUY" if weighted_avg > 0.15 else "SELL" if weighted_avg < -0.15 else "HOLD"
    )

    # Disagreement penalty: dispersion across specialists lowers confidence
    # even if the naive weighted average looks decisive.
    dispersion = max(scores.values()) - min(scores.values())
    confidence = max(0.0, weighted_avg_abs_scaled(weighted_avg) * (1 - dispersion / 2))

    return {
        "final_signal": final_signal,
        "confidence": round(confidence, 3),
        "weighted_avg": round(weighted_avg, 3),
        "risk_veto_applied": veto,
        "component_scores": scores,
        "suggested_stop_loss": risk.stop_loss,
        "suggested_target": risk.target_price,
        "suggested_holding_period_days": risk.suggested_holding_period_days,
    }

def weighted_avg_abs_scaled(x: float) -> float:
    return min(1.0, abs(x))
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