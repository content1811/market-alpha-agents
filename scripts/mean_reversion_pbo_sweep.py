"""Real multi-variant parameter sweep for MeanReversionAgent, to get an
actual PBO (Probability of Backtest Overfitting) number to feed into
backtesting/graduation_gate.py -- per docs/plan/section_risk_validation.md
section 4 point 2 ("log every variant tested").

Sweeps mean_reversion_signal_series's `z_window` (the rolling window behind
the Bollinger-vs-moving-average z-score sub-score) across 5 real values,
walk-forward-backtests each variant on real multi-year AAPL data, and feeds
all 5 variants' out-of-sample return series into
backtesting.robustness.probability_of_backtest_overfitting (CSCV) to get one
real PBO number -- not the synthetic-variant sanity fixtures in
tests/test_backtesting/test_robustness.py. The best variant (by out-of-sample
Sharpe) is then run through backtesting.graduation_gate.evaluate_strategy for
a real pass/fail verdict.

No parameters here were tuned to make the result look better -- z_window
values are a plain even spread around the existing default (20), chosen
before any variant was run.
"""
from __future__ import annotations

import yaml

from backtesting.graduation_gate import evaluate_strategy
from backtesting.robustness import probability_of_backtest_overfitting
from backtesting.run_backtest import walk_forward_backtest
from data.connectors.us_equities_yfinance import YFinanceSource
from signals.ta.mean_reversion import mean_reversion_signal_series

SYMBOL = "AAPL"
START = "2018-01-01"
END = "2026-08-27"
Z_WINDOWS = [10, 15, 20, 25, 30]  # 5 real values bracketing the existing default (20)


def main() -> None:
    with open("config/config.yaml") as f:
        config = yaml.safe_load(f)
    wf_cfg = config["backtesting"]["walk_forward"]

    source = YFinanceSource()
    bars = source.get_ohlcv_range(SYMBOL, START, END)
    import pandas as pd

    idx = pd.DatetimeIndex([b.ts_utc for b in bars])
    high = pd.Series([b.high for b in bars], index=idx)
    low = pd.Series([b.low for b in bars], index=idx)
    close = pd.Series([b.close for b in bars], index=idx)
    print(f"Fetched {len(close)} daily bars for {SYMBOL}: {idx[0].date()} .. {idx[-1].date()}")

    results = {}
    for z_window in Z_WINDOWS:
        signal = mean_reversion_signal_series(high, low, close, z_window=z_window)
        result = walk_forward_backtest(
            close,
            signal,
            in_sample_days=wf_cfg["in_sample_days"],
            out_of_sample_days=wf_cfg["out_of_sample_days"],
            num_trials=len(Z_WINDOWS),
        )
        results[z_window] = result
        print(
            f"z_window={z_window:>3}: sharpe={result.sharpe:.3f} profit_factor={result.profit_factor:.3f} "
            f"max_drawdown={result.max_drawdown:.3f} calmar={result.calmar:.3f} "
            f"deflated_sharpe={result.deflated_sharpe:.3f} min_track_record_length={result.min_track_record_length:.1f} "
            f"num_splits={result.num_splits} oos_days={len(result.out_of_sample_returns)}"
        )

    variant_returns = [results[z].out_of_sample_returns for z in Z_WINDOWS]
    pbo_result = probability_of_backtest_overfitting(variant_returns, num_blocks=10)
    print(f"\nPBO across {len(Z_WINDOWS)} z_window variants: {pbo_result.pbo:.3f} ({pbo_result.num_combinations} IS/OOS combinations)")

    best_z = max(results, key=lambda z: results[z].sharpe)
    best_result = results[best_z]
    print(f"\nBest variant by out-of-sample Sharpe: z_window={best_z} (sharpe={best_result.sharpe:.3f})")

    graduation = evaluate_strategy(best_result, num_trials=len(Z_WINDOWS), pbo=pbo_result.pbo, config=config)
    print(f"\nGraduation gate verdict for best variant: passed={graduation.passed}")
    for reason in graduation.reasons:
        print(f"  - {reason}")
    print(f"  (eyeball only) max_drawdown={graduation.max_drawdown:.3f} calmar_ratio={graduation.calmar_ratio:.3f}")


if __name__ == "__main__":
    main()
