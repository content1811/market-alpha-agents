"""Agent-level tests for NewsSentimentAgent."""
from __future__ import annotations

import json

import pytest

from agents.news_sentiment_agent import build_verdict
from data.schema import AssetClass
from tests.test_agents.test_mean_reversion_agent import FakeLLM

SAMPLE_HEADLINES = [
    {"title": "Company X beats earnings estimates", "source": "marketwatch.com", "hours_since": 2, "item_id": "a"},
    {"title": "Company X faces regulatory probe", "source": "cnbc.com", "hours_since": 10, "item_id": "b"},
]


def test_news_sentiment_agent_end_to_end_with_fake_llm():
    response = json.dumps(
        {
            "scores": [{"sentiment": 0.6, "relevance": 0.9}, {"sentiment": -0.4, "relevance": 0.8}],
            "rationale": "Mixed: earnings beat (marketwatch) offset by regulatory probe (cnbc), 2 sources.",
        }
    )
    llm = FakeLLM(responses=[response])

    verdict = build_verdict("X", AssetClass.US_EQUITY, headlines=SAMPLE_HEADLINES, llm=llm)

    assert -1.0 <= verdict.signal_score <= 1.0
    assert verdict.sub_scores["independent_source_count"] == 2.0
    assert verdict.agent_name == "NewsSentimentAgent"


def test_news_sentiment_agent_over_length_rationale_gets_truncated_not_failed():
    over_long_rationale = "x" * 400  # exceeds the 280-char schema limit
    bad_response = json.dumps(
        {"scores": [{"sentiment": 0.1, "relevance": 0.5}, {"sentiment": 0.1, "relevance": 0.5}], "rationale": over_long_rationale}
    )
    # both repair attempts return the same over-length rationale -- the
    # llm_client's word-boundary truncation fallback must still succeed.
    llm = FakeLLM(responses=[bad_response, bad_response])

    verdict = build_verdict("X", AssetClass.US_EQUITY, headlines=SAMPLE_HEADLINES, llm=llm)
    assert len(verdict.rationale) <= 280


def test_news_sentiment_agent_no_headlines_returns_neutral_without_llm_call():
    llm = FakeLLM(responses=[])  # must not be called at all
    verdict = build_verdict("X", AssetClass.US_EQUITY, headlines=[], llm=llm)
    assert verdict.signal_score == 0.0
    assert verdict.confidence == 0.0
    assert llm.call_count == 0
