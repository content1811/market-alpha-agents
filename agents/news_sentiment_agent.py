"""NewsSentimentAgent per docs/plan/section_agents.md section 8.

Per-headline sentiment/relevance scoring is a language-understanding task the
plan itself assigns to FinBERT + a local LLM (not a pure formula like the TA
agents) -- so the LLM DOES set those per-headline sub-scores here. What it
does NOT set is the final signal_score/confidence: those come from
signals/news_sentiment.py's deterministic time-decay aggregation and
coverage-count gate, applied in code after the LLM scores each headline.

Scope note: SEC EDGAR/TDnet filing-trigger event_flag (indicator #1) is not
wired yet -- that's Phase 5 (News/Alerting Integration) territory per
section_orchestration.md section 3. This agent covers indicators #2-#4
(headline sentiment, coverage gate, recency decay) using keyless RSS feeds.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
from pydantic import BaseModel, Field

from agents.llm_client import call_structured
from agents.schemas import AgentVerdict, HoldingPeriod, ProfitTarget, StopLoss
from alerting.news_watch.sentiment_finbert import is_relevant, score_headlines_bulk
from data.connectors.news_finnhub import fetch_finnhub_company_news
from data.schema import AssetClass
from signals.news_sentiment import ScoredHeadline, compute_news_sentiment

RSS_FEEDS_BY_ASSET_CLASS = {
    AssetClass.US_EQUITY: [
        "https://feeds.marketwatch.com/marketwatch/topstories/",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    ],
    AssetClass.JP_EQUITY: [
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",  # general-interest only -- see module docstring
    ],
    AssetClass.CRYPTO: [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
    ],
}
STRUCTURED_SOURCES = {"marketwatch.com", "cnbc.com", "coindesk.com"}

SYSTEM_PROMPT = """You are a skeptical news desk analyst, not a headline-chasing retail \
trader -- trained to distinguish a market-moving primary-source event from noise/opinion/ \
recycled headlines. You are scoring headlines for NewsSentimentAgent in a local \
trading-research system.

For EACH headline given, output a sentiment score in [-1, 1] (-1 very negative for the \
named ticker, 0 neutral/irrelevant, +1 very positive) and a relevance score in [0, 1] \
(0 = not really about this ticker, 1 = directly and materially about it). Be conservative: \
most general market headlines are only weakly relevant to a single ticker unless it is \
named directly. Also write one rationale (<=280 chars) citing the specific headline(s) \
that drove your scoring, explicitly noting if coverage is thin/single-source.
"""


class HeadlineScore(BaseModel):
    sentiment: float = Field(ge=-1.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)


class NewsScoringOutput(BaseModel):
    scores: list[HeadlineScore]
    rationale: str = Field(max_length=280)


def fetch_headlines(asset_class: AssetClass, ticker_keywords: list[str], lookback_hours: int = 72) -> list[dict]:
    feeds = RSS_FEEDS_BY_ASSET_CLASS[asset_class]
    now = datetime.now(timezone.utc)
    headlines = []
    for url in feeds:
        parsed = feedparser.parse(url)
        source_domain = urlparse(url).netloc.replace("feeds.", "").replace("www.", "")
        for entry in parsed.entries:
            title = entry.get("title", "")
            if ticker_keywords and not any(kw.lower() in title.lower() for kw in ticker_keywords):
                continue
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if published:
                published_dt = datetime(*published[:6], tzinfo=timezone.utc)
                hours_since = max(0.0, (now - published_dt).total_seconds() / 3600)
            else:
                hours_since = 0.0
            if hours_since > lookback_hours:
                continue
            headlines.append(
                {
                    "title": title,
                    "source": source_domain,
                    "hours_since": hours_since,
                    "item_id": hashlib.sha256((entry.get("link", "") + title).encode()).hexdigest()[:16],
                }
            )

    if asset_class == AssetClass.US_EQUITY and ticker_keywords:
        seen_ids = {h["item_id"] for h in headlines}
        for h in fetch_finnhub_company_news(ticker_keywords[0], lookback_hours=lookback_hours):
            if h["item_id"] not in seen_ids:
                headlines.append(h)
                seen_ids.add(h["item_id"])

    return headlines


def _finbert_prefilter(headlines: list[dict]) -> list[dict]:
    """Local FinBERT first pass (section_orchestration.md Phase 5 / section_
    data_pipeline.md section 3.2 step 3): drop headlines FinBERT is confident
    are neutral noise before paying for the expensive per-headline LLM call
    below. Degrades to "score everything" if FinBERT is unavailable for any
    reason, matching every other graceful-degradation pattern already in this
    codebase (e.g. alerting/telegram_bot.py's send_telegram_message)."""
    scores = score_headlines_bulk([h["title"] for h in headlines])
    if scores is None:
        return headlines
    return [h for h, s in zip(headlines, scores) if is_relevant(s)]


def build_verdict(
    ticker: str,
    asset_class: AssetClass,
    ticker_keywords: list[str] | None = None,
    headlines: list[dict] | None = None,
    llm=None,
) -> AgentVerdict:
    if headlines is None:
        headlines = fetch_headlines(asset_class, ticker_keywords or [ticker])

    is_jp = asset_class == AssetClass.JP_EQUITY

    if headlines:
        headlines = _finbert_prefilter(headlines)

    if not headlines:
        return AgentVerdict(
            agent_name="NewsSentimentAgent",
            asset_class=asset_class,
            ticker=ticker,
            as_of_timestamp=datetime.now(timezone.utc),
            signal_score=0.0,
            confidence=0.0,
            suggested_holding_period=HoldingPeriod(min_days=0, max_days=0, unit="hours"),
            stop_loss=StopLoss(method="percent", value=0.0, price_level=None),
            profit_target=ProfitTarget(method="percent", value=0.0),
            rationale="No headlines found in the lookback window matching this ticker -- no active news event to score.",
            sub_scores={"coverage_count": 0.0, "independent_source_count": 0.0},
            regime_gate_applied=None,
        )

    headline_list_text = "\n".join(f"{i+1}. [{h['source']}] {h['title']}" for i, h in enumerate(headlines))
    user_prompt = (
        f"Ticker: {ticker} ({asset_class.value})\n"
        f"Score these {len(headlines)} headlines, in order, for relevance to {ticker}:\n{headline_list_text}"
    )

    scored = call_structured(SYSTEM_PROMPT, user_prompt, NewsScoringOutput, llm=llm)
    if len(scored.scores) != len(headlines):
        raise ValueError(f"LLM returned {len(scored.scores)} scores for {len(headlines)} headlines")

    scored_headlines = [
        ScoredHeadline(sentiment=s.sentiment, relevance=s.relevance, hours_since=h["hours_since"], source=h["source"])
        for s, h in zip(scored.scores, headlines)
    ]
    sub = compute_news_sentiment(scored_headlines, is_jp=is_jp)

    return AgentVerdict(
        agent_name="NewsSentimentAgent",
        asset_class=asset_class,
        ticker=ticker,
        as_of_timestamp=datetime.now(timezone.utc),
        signal_score=sub.signal_score,
        confidence=sub.confidence,
        suggested_holding_period=HoldingPeriod(min_days=0.25, max_days=3, unit="calendar_days"),
        stop_loss=StopLoss(method="percent", value=5.0, price_level=None),
        profit_target=ProfitTarget(method="percent", value=5.0),
        rationale=scored.rationale,
        sub_scores={
            "headline_score": sub.headline_score,
            "coverage_count": float(sub.coverage_count),
            "independent_source_count": float(sub.independent_source_count),
        },
        regime_gate_applied=None,
    )
