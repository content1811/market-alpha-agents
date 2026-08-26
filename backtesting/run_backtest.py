"""Signal-level backtest driver for the equity leg, per
docs/plan/section_orchestration.md section 3 Phase 4 ("vectorbt for fast
vectorized signal research"). vectorbt is used ONLY for position/equity-curve
simulation (entries/exits, realistic fees/slippage) -- Sharpe/profit-factor/
Calmar/DSR/PBO/MinTRL all come from backtesting/robustness.py uniformly,
not vectorbt's own stats accessors, which threw ValueError on this project's
business-day-indexed series ("Index frequency is None" / "BusinessDay is a
non-fixed frequency") -- verified live; routing every metric through one
implementation avoids that fragility entirely rather than working around it
ad hoc per call site.

Costs: TSE odd-lot spread penalty and crypto taker fees (both flagged in
section_risk_validation.md section 2) are NOT modeled in the generic
`fees`/`slippage` params below -- callers backtesting JP or crypto signals
must pass asset-class-appropriate values explicitly; the defaults here are
US-equity-realistic only.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import vectorbt as vbt

from backtesting.robustness import (
    calmar_ratio,
    deflated_sharpe_ratio,
    max_drawdown,
    minimum_track_record_length,
    profit_factor,
    sharpe_ratio,
)
from backtesting.walk_forward import rolling_walk_forward_splits


def signal_to_positions(signal_score: pd.Series, buy_threshold: float = 0.35, exit_threshold: float = 0.10) -> tuple[pd.Series, pd.Series]:
    """Entries when signal_score crosses above buy_threshold, exits when it
    falls back below exit_threshold -- mirrors the BUY/WATCH/HOLD decision
    bands' spirit (section_agents.md section 10.3) applied to a single
    signal's own score series rather than the full blended supervisor output,
    since this backtests one signal in isolation, not the aggregated system."""
    in_position = False
    entries, exits = [], []
    for score in signal_score:
        entry = (not in_position) and score >= buy_threshold
        exit_ = in_position and score < exit_threshold
        entries.append(entry)
        exits.append(exit_)
        if entry:
            in_position = True
        if exit_:
            in_position = False
    return pd.Series(entries, index=signal_score.index), pd.Series(exits, index=signal_score.index)


def simulate_returns(
    price: pd.Series,
    signal_score: pd.Series,
    buy_threshold: float = 0.35,
    exit_threshold: float = 0.10,
    fees: float = 0.001,
    slippage: float = 0.0005,
    init_cash: float = 100_000,
) -> pd.Series:
    """Runs vectorbt's Portfolio.from_signals with realistic costs and
    returns the per-period returns series."""
    entries, exits = signal_to_positions(signal_score, buy_threshold, exit_threshold)
    pf = vbt.Portfolio.from_signals(price, entries, exits, fees=fees, slippage=slippage, init_cash=init_cash)
    return pf.returns()


@dataclass
class WalkForwardBacktestResult:
    out_of_sample_returns: pd.Series
    sharpe: float
    profit_factor: float
    max_drawdown: float
    calmar: float
    deflated_sharpe: float
    min_track_record_length: float
    num_splits: int


def walk_forward_backtest(
    price: pd.Series,
    signal_score: pd.Series,
    in_sample_days: int = 252,
    out_of_sample_days: int = 63,
    buy_threshold: float = 0.35,
    exit_threshold: float = 0.10,
    fees: float = 0.001,
    slippage: float = 0.0005,
    num_trials: int = 1,
    trial_sharpe_std: float | None = None,
) -> WalkForwardBacktestResult:
    """Per section_risk_validation.md section 4: only the concatenated
    out-of-sample segments count toward any performance claim -- in-sample
    fit is used only to confirm the signal isn't degenerate over that window,
    never reported as "the strategy's performance."

    `num_trials` must reflect every parameter/indicator combination actually
    tried system-wide (not just this call), per the plan's explicit DSR
    requirement -- the default of 1 is almost certainly wrong for a real
    go/no-go decision and exists only so this function is callable in
    isolation; pass the real count when this is wired into the full
    validation pipeline."""
    splits = rolling_walk_forward_splits(len(price), in_sample_days, out_of_sample_days)
    if not splits:
        raise ValueError(f"series of length {len(price)} is too short for in_sample_days={in_sample_days}")

    oos_returns_segments = []
    for split in splits:
        # in-sample window exists to mirror a real workflow (fit/tune on
        # train, then apply unchanged to test) -- this driver takes a
        # pre-computed signal_score series, so there's no parameter fitting
        # happening here yet; the split is still honored structurally so nothing
        # downstream ever reports in-sample-only performance.
        test_price = price.iloc[split.test_slice]
        test_signal = signal_score.iloc[split.test_slice]
        returns = simulate_returns(test_price, test_signal, buy_threshold, exit_threshold, fees, slippage)
        oos_returns_segments.append(returns)

    concatenated = pd.concat(oos_returns_segments)

    return WalkForwardBacktestResult(
        out_of_sample_returns=concatenated,
        sharpe=sharpe_ratio(concatenated),
        profit_factor=profit_factor(concatenated),
        max_drawdown=max_drawdown((1 + concatenated).cumprod()),
        calmar=calmar_ratio(concatenated),
        deflated_sharpe=deflated_sharpe_ratio(concatenated, num_trials=num_trials, trial_sharpe_std=trial_sharpe_std),
        min_track_record_length=minimum_track_record_length(concatenated),
        num_splits=len(splits),
    )
