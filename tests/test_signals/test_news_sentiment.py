"""Unit tests for signals/news_sentiment.py, per the Phase 2 test mandate:
hand-computed fixtures.
"""
from __future__ import annotations

import pytest

from signals.news_sentiment import ScoredHeadline, compute_news_sentiment, time_decay


def test_time_decay_hand_computed():
    assert time_decay(0) == pytest.approx(1.0)
    assert time_decay(24) == pytest.approx(0.367879, abs=1e-5)
    assert time_decay(48) == pytest.approx(0.135335, abs=1e-5)


def test_headline_score_hand_computed():
    # numerator = 0.8*1*1 + (-0.3)*0.5*e^-1 + 0.5*0.8*e^-2 = 0.79895220
    # denominator = 1*1 + 0.5*e^-1 + 0.8*e^-2 = 1.29220795
    # headline_score = 0.618285
    headlines = [
        ScoredHeadline(0.8, 1.0, 0, "A"),
        ScoredHeadline(-0.3, 0.5, 24, "B"),
        ScoredHeadline(0.5, 0.8, 48, "C"),
    ]
    result = compute_news_sentiment(headlines)
    assert result.headline_score == pytest.approx(0.618285, abs=1e-5)
    assert result.signal_score == pytest.approx(0.618285, abs=1e-5)  # 3 independent sources -> no gate clamp
    assert result.independent_source_count == 3


def test_coverage_gate_clamps_score_below_min_sources():
    # only 2 independent sources (A appears twice) -> gate clamps |score| to 0.4
    headlines = [
        ScoredHeadline(0.9, 1.0, 0, "A"),
        ScoredHeadline(0.9, 1.0, 1, "A"),
        ScoredHeadline(0.9, 1.0, 2, "B"),
    ]
    result = compute_news_sentiment(headlines, min_independent_sources_for_large_score=3, large_score_threshold=0.4)
    assert result.independent_source_count == 2
    assert result.signal_score == pytest.approx(0.4)


def test_empty_headlines_returns_zero():
    result = compute_news_sentiment([])
    assert result.signal_score == 0.0
    assert result.confidence == 0.0


def test_jp_confidence_hard_capped_at_0_5():
    headlines = [ScoredHeadline(0.5, 1.0, 0, s) for s in ("A", "B", "C", "D", "E")]
    result = compute_news_sentiment(headlines, is_jp=True)
    assert result.confidence <= 0.5


def test_finbert_only_reduces_confidence():
    headlines = [ScoredHeadline(0.5, 1.0, 0, s) for s in ("A", "B", "C")]
    normal = compute_news_sentiment(headlines, finbert_only=False)
    finbert = compute_news_sentiment(headlines, finbert_only=True)
    assert finbert.confidence < normal.confidence
