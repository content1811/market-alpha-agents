"""Rolling walk-forward split generator, per
docs/plan/section_risk_validation.md section 4: "Walk-forward, rolling
window (not anchored)... 12-month in-sample fit -> 3-month out-of-sample
test -> roll forward 3 months -> repeat... Only the concatenated
out-of-sample segments count toward any performance claim."
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WalkForwardSplit:
    train_slice: slice
    test_slice: slice


def rolling_walk_forward_splits(
    length: int, in_sample_days: int = 252, out_of_sample_days: int = 63
) -> list[WalkForwardSplit]:
    """Rolling (not anchored) walk-forward splits over a series of `length`
    observations. Each split's train window slides forward by
    `out_of_sample_days` each time, so early history eventually falls out of
    the training window entirely -- the plan's explicit reason for rolling
    over anchored, given regime change."""
    if in_sample_days <= 0 or out_of_sample_days <= 0:
        raise ValueError("in_sample_days and out_of_sample_days must be positive")

    splits = []
    start = 0
    while True:
        train_end = start + in_sample_days
        test_end = train_end + out_of_sample_days
        if test_end > length:
            break
        splits.append(WalkForwardSplit(train_slice=slice(start, train_end), test_slice=slice(train_end, test_end)))
        start += out_of_sample_days
    return splits
