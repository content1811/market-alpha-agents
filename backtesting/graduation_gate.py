"""Paper-trading graduation gate, per docs/plan/section_risk_validation.md
section 4's numbered checklist ("Metrics that must pass before a strategy is
'trusted' enough to move to paper trading"):

  1. Deflated Sharpe Ratio (DSR) positive/significant -> config's
     min_deflated_sharpe.
  2. Probability of Backtest Overfitting (PBO) below a threshold -> config's
     max_pbo. PBO is computed across a SET of trialed parameter variants
     (backtesting/robustness.py's probability_of_backtest_overfitting), not
     derivable from one WalkForwardBacktestResult -- callers must run that
     sweep themselves and pass the resulting float in.
  3. Minimum Track Record Length (MinTRL) satisfied -- there must be enough
     out-of-sample history for the claimed Sharpe to be statistically
     distinguishable from zero. Checked two ways: the actual OOS track
     record must be at least config's min_track_record_days floor, AND at
     least the dynamic statistical requirement
     (WalkForwardBacktestResult.min_track_record_length) computed from the
     observed Sharpe/skew/kurtosis -- if that number is inf (Sharpe <=
     benchmark), the honest answer is "not yet validated", per the doc.
  4. Profit factor > 1.5 out-of-sample. This threshold is the doc's own
     literal number, not a config key.
  5. Max drawdown / Calmar ratio are explicitly NOT a hard pass/fail gate in
     the doc -- its own word is "eyeballed" against human tolerance, not a
     numeric cutoff. They are surfaced on GraduationResult for a human to
     look at, never used to flip `passed`.

Costs/fees-modeled-explicitly (the doc's point 6) is a backtest-construction
concern (see run_backtest.py's simulate_returns defaults), not something this
gate can check post-hoc from a WalkForwardBacktestResult alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from backtesting.run_backtest import WalkForwardBacktestResult

MIN_PROFIT_FACTOR = 1.5  # section_risk_validation.md section 4 point 4, literal in the doc


@dataclass
class GraduationResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    # Point 5's eyeball metrics -- reported for a human, never gated on.
    max_drawdown: float = 0.0
    calmar_ratio: float = 0.0


def evaluate_strategy(
    result: WalkForwardBacktestResult,
    num_trials: int,
    pbo: float,
    config: dict,
) -> GraduationResult:
    """Checks a single strategy variant's walk-forward result against the
    paper-trading graduation checklist.

    `num_trials` is the same trial count that should already have been fed
    into `result.deflated_sharpe`'s computation (walk_forward_backtest's
    `num_trials` param) -- carried here only for traceable failure messages,
    since DSR itself is read straight off `result`, not recomputed.

    `pbo` must come from running backtesting/robustness.py's
    probability_of_backtest_overfitting over the full set of trialed
    parameter variants (not just this one) -- see this module's docstring.
    """
    gates = config["backtesting"]["robustness_gates"]
    min_deflated_sharpe = gates["min_deflated_sharpe"]
    max_pbo = gates["max_pbo"]
    min_track_record_days = gates["min_track_record_days"]

    reasons: list[str] = []
    actual_track_record_days = len(result.out_of_sample_returns)

    # 1. Deflated Sharpe Ratio
    if result.deflated_sharpe < min_deflated_sharpe:
        reasons.append(
            f"Deflated Sharpe Ratio {result.deflated_sharpe:.3f} (num_trials={num_trials}) "
            f"is below the minimum required {min_deflated_sharpe:.3f}"
        )

    # 2. Probability of Backtest Overfitting
    if pbo > max_pbo:
        reasons.append(f"Probability of Backtest Overfitting {pbo:.3f} exceeds the maximum allowed {max_pbo:.3f}")

    # 3. Minimum Track Record Length -- both the config floor and the
    # dynamic statistical requirement must be met by the actual OOS history.
    if actual_track_record_days < min_track_record_days:
        reasons.append(
            f"Out-of-sample track record ({actual_track_record_days} days) is shorter than "
            f"the minimum required by config ({min_track_record_days} days)"
        )
    if actual_track_record_days < result.min_track_record_length:
        reasons.append(
            f"Out-of-sample track record ({actual_track_record_days} days) is shorter than the "
            f"statistically required Minimum Track Record Length ({result.min_track_record_length:.1f} days) "
            f"for the observed Sharpe to be distinguishable from zero"
        )

    # 4. Profit factor
    if result.profit_factor <= MIN_PROFIT_FACTOR:
        reasons.append(f"Profit factor {result.profit_factor:.3f} does not exceed the required {MIN_PROFIT_FACTOR}")

    # 5. Max drawdown / Calmar -- eyeballed only, per the doc; never gated.

    return GraduationResult(
        passed=len(reasons) == 0,
        reasons=reasons,
        max_drawdown=result.max_drawdown,
        calmar_ratio=result.calmar,
    )
