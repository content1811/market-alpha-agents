"""Tests for backtesting/walk_forward.py -- hand-computed split counts and
boundaries."""
from __future__ import annotations

import pytest

from backtesting.walk_forward import rolling_walk_forward_splits


def test_split_count_hand_computed():
    # start values 0,63,...,<=685 (since start+252+63<=1000 => start<=685)
    # -> floor(685/63)+1 = 10+1 = 11 splits
    splits = rolling_walk_forward_splits(length=1000, in_sample_days=252, out_of_sample_days=63)
    assert len(splits) == 11


def test_splits_are_contiguous_and_non_overlapping_within_each_split():
    splits = rolling_walk_forward_splits(length=1000, in_sample_days=252, out_of_sample_days=63)
    for split in splits:
        assert split.train_slice.stop == split.test_slice.start
        assert split.test_slice.stop - split.test_slice.start == 63
        assert split.train_slice.stop - split.train_slice.start == 252


def test_splits_roll_forward_by_out_of_sample_days():
    splits = rolling_walk_forward_splits(length=1000, in_sample_days=252, out_of_sample_days=63)
    assert splits[0].train_slice.start == 0
    assert splits[1].train_slice.start == 63
    assert splits[2].train_slice.start == 126


def test_no_split_exceeds_series_length():
    splits = rolling_walk_forward_splits(length=1000, in_sample_days=252, out_of_sample_days=63)
    assert all(s.test_slice.stop <= 1000 for s in splits)
    # last split: start=630 (10*63), train_end=882, test_end=945 <= 1000;
    # the next start (693) would push test_end to 1008 > 1000, so it stops here.
    assert splits[-1].test_slice.stop == 945


def test_raises_on_nonpositive_windows():
    with pytest.raises(ValueError):
        rolling_walk_forward_splits(length=1000, in_sample_days=0, out_of_sample_days=63)


def test_too_short_series_returns_no_splits():
    assert rolling_walk_forward_splits(length=100, in_sample_days=252, out_of_sample_days=63) == []
