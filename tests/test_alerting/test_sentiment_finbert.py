"""Tests for alerting/news_watch/sentiment_finbert.py.

The is_relevant() gate is pure logic and tested directly against synthetic
{label, score} dicts (fast, no model load). score_headlines_bulk() itself is
a live model-inference test -- it actually loads ProsusAI/finbert via
transformers.pipeline and scores hand-picked headlines with an obviously
positive/negative/neutral tone, so it's marked "model" (slow: ~1-2s to load
already-cached weights, longer on a machine that has to download them first)
to distinguish it from ordinary fast unit tests, per pyproject.toml's markers.
"""
from __future__ import annotations

import pytest

from alerting.news_watch.sentiment_finbert import is_available, is_relevant, score_headlines_bulk


def test_is_relevant_keeps_non_neutral_regardless_of_score():
    assert is_relevant({"label": "positive", "score": 0.51}) is True
    assert is_relevant({"label": "negative", "score": 0.99}) is True


def test_is_relevant_drops_confidently_neutral():
    assert is_relevant({"label": "neutral", "score": 0.95}) is False


def test_is_relevant_keeps_low_confidence_neutral():
    assert is_relevant({"label": "neutral", "score": 0.5}) is True


def test_score_headlines_bulk_empty_input_returns_empty_list_not_none():
    assert score_headlines_bulk([]) == []


@pytest.mark.model
def test_finbert_model_is_available():
    assert is_available() is True


@pytest.mark.model
def test_score_headlines_bulk_sensible_labels_for_hand_picked_headlines():
    headlines = [
        "Company posts record profit, stock soars to all-time high",  # obviously positive
        "Company shares plummet after massive fraud scandal revealed",  # obviously negative
        "Company to release quarterly earnings report next Tuesday",  # routine/neutral
    ]

    results = score_headlines_bulk(headlines)

    assert results is not None
    assert len(results) == 3
    for r in results:
        assert r["label"] in {"positive", "negative", "neutral"}
        assert 0.0 <= r["score"] <= 1.0

    assert results[0]["label"] == "positive"
    assert results[1]["label"] == "negative"
    assert results[2]["label"] == "neutral"

    # the routine/neutral headline should be confident enough to get filtered
    # by the default relevance-proxy threshold; the two sentiment-bearing
    # headlines must never be dropped regardless of confidence.
    assert is_relevant(results[0]) is True
    assert is_relevant(results[1]) is True
    assert is_relevant(results[2]) is False
