"""Pure-math news-sentiment aggregation for NewsSentimentAgent, per
docs/plan/section_agents.md section 8. Per-headline sentiment/relevance
scoring is inherently a language-understanding task (the plan itself names
FinBERT + a local LLM for this, unlike the pure-technical-indicator agents) --
that scoring happens in agents/news_sentiment_agent.py via the LLM client.
What lives here is the deterministic part: time-decay weighting, the
weighted-average aggregation formula, and the coverage-count gate, none of
which the LLM is trusted to apply on its own.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ScoredHeadline:
    sentiment: float  # in [-1, 1], from the LLM/FinBERT pass
    relevance: float  # in [0, 1], outlet/structured-source weighting
    hours_since: float
    source: str


def time_decay(hours_since: float) -> float:
    return float(np.exp(-hours_since / 24))


@dataclass
class NewsSentimentSubScores:
    headline_score: float
    signal_score: float
    coverage_count: int
    independent_source_count: int
    confidence: float


def compute_news_sentiment(
    headlines: list[ScoredHeadline],
    min_independent_sources_for_large_score: int = 3,
    large_score_threshold: float = 0.4,
    is_jp: bool = False,
    finbert_only: bool = False,
) -> NewsSentimentSubScores:
    """Implements section_agents.md section 8's signal_score computation
    verbatim, plus the coverage-count gate (indicator #3) and confidence
    rules (source diversity, JP cap, FinBERT-only reduction)."""
    if not headlines:
        return NewsSentimentSubScores(0.0, 0.0, 0, 0, 0.0)

    weights = [h.relevance * time_decay(h.hours_since) for h in headlines]
    total_weight = sum(weights)
    if total_weight == 0:
        return NewsSentimentSubScores(0.0, 0.0, len(headlines), 0, 0.0)

    headline_score = sum(h.sentiment * w for h, w in zip(headlines, weights)) / total_weight
    signal_score = float(np.clip(headline_score, -1.0, 1.0))

    independent_sources = len({h.source for h in headlines})
    coverage_count = len(headlines)

    # coverage-count gate: |signal_score| > threshold requires >= min independent sources
    if independent_sources < min_independent_sources_for_large_score:
        signal_score = float(np.clip(signal_score, -large_score_threshold, large_score_threshold))

    confidence = float(np.clip(0.2 + 0.2 * independent_sources, 0.0, 1.0))
    if is_jp:
        confidence = min(confidence, 0.5)
    if finbert_only:
        confidence *= 0.7

    return NewsSentimentSubScores(
        headline_score=float(headline_score),
        signal_score=signal_score,
        coverage_count=coverage_count,
        independent_source_count=independent_sources,
        confidence=confidence,
    )
