"""Local FinBERT first-pass sentiment triage, per docs/plan/section_orchestration.md
Phase 5 ("local FinBERT first pass, local LLM second pass on the subset crossing a
relevance threshold") and section_data_pipeline.md section 3.2 step 3: every tagged
headline gets a cheap positive/negative/neutral softmax score from ProsusAI/finbert
(CPU, ~440MB of PyTorch weights, runs fully locally -- no API key, and no network
dependency once huggingface_hub has cached the weights on first use) so the expensive
per-headline LLM call in agents/news_sentiment_agent.py only has to run on the subset
that actually looks like it says something.

Model load (~1-2s once weights are cached locally in ~/.cache/huggingface, ~30-40s on
the very first call on a machine that has to download them) is deferred to first use
and memoized at module level -- never at import time -- so importing this module (or
anything that imports it, e.g. news_sentiment_agent) costs nothing until
score_headlines_bulk()/is_available() is actually called.

Graceful degradation, matching every other channel/connector in this codebase (see
alerting/telegram_bot.py's send_telegram_message, which never raises and returns
False on any failure instead): score_headlines_bulk() returns None -- not an empty
list, since an empty list is a valid "scored zero headlines" answer -- if
transformers/torch aren't installed, the model fails to download/load, or inference
itself raises. Callers must treat None as "score everything downstream instead"
rather than crashing the scheduled run that triggered the call.
"""
from __future__ import annotations

MODEL_NAME = "ProsusAI/finbert"
NEUTRAL_LABEL = "neutral"
#: Default cutoff for is_relevant(): a "neutral" call is only treated as
#: irrelevant noise once FinBERT is quite confident about it (see module-level
#: tests for the calibration headlines this was picked against).
DEFAULT_NEUTRAL_CONFIDENCE_THRESHOLD = 0.85

_pipeline = None
_load_failed = False


def _get_pipeline():
    """Lazily load + memoize the FinBERT pipeline. Returns None (and remembers
    the failure for the rest of the process, so repeated calls don't keep
    retrying a slow/broken load) on any import/download/load error -- never
    raises, per this module's graceful-degradation contract."""
    global _pipeline, _load_failed
    if _pipeline is not None:
        return _pipeline
    if _load_failed:
        return None
    try:
        from transformers import pipeline  # local import: torch/transformers are
        # heavy optional deps -- this module must stay importable even if they're
        # missing, so the import itself is deferred to first actual use.

        _pipeline = pipeline("sentiment-analysis", model=MODEL_NAME)
        return _pipeline
    except Exception:
        _load_failed = True
        return None


def is_available() -> bool:
    """True if the FinBERT pipeline is loaded (or successfully loads right now)."""
    return _get_pipeline() is not None


def score_headlines_bulk(headlines: list[str]) -> list[dict] | None:
    """Score every headline's text with FinBERT in one batched forward pass
    (batching is what keeps this cheap enough to run on the full firehose, per
    section_data_pipeline.md section 3.2 step 3). Returns one
    {"label": "positive"|"negative"|"neutral", "score": float} dict per
    headline, in input order, or None if FinBERT is unavailable for any
    reason (never raises)."""
    if not headlines:
        return []
    pipe = _get_pipeline()
    if pipe is None:
        return None
    try:
        results = pipe(headlines, truncation=True)
        return [{"label": r["label"].lower(), "score": float(r["score"])} for r in results]
    except Exception:
        return None


def is_relevant(result: dict, neutral_confidence_threshold: float = DEFAULT_NEUTRAL_CONFIDENCE_THRESHOLD) -> bool:
    """Relevance-proxy gate used to pre-filter headlines before the expensive
    local-LLM pass (section_orchestration.md Phase 5): a non-neutral call
    (positive or negative) is always kept -- FinBERT already found a
    sentiment signal in it. A "neutral" call is only dropped once FinBERT is
    *confident* it's neutral (score >= threshold); a low-confidence "neutral"
    really means "the model couldn't tell", which is exactly the ambiguous
    case worth spending an LLM call on rather than silently discarding."""
    if result["label"] != NEUTRAL_LABEL:
        return True
    return result["score"] < neutral_confidence_threshold


if __name__ == "__main__":
    import time

    sample = [
        "Company posts record profit, stock soars to all-time high",
        "Company shares plummet after massive fraud scandal revealed",
        "Company to release quarterly earnings report next Tuesday",
    ]

    t0 = time.time()
    scores = score_headlines_bulk(sample)
    load_and_score_elapsed = time.time() - t0

    if scores is None:
        print("FinBERT unavailable (see is_available()/module docstring) -- would degrade to scoring everything.")
    else:
        for headline, s in zip(sample, scores):
            print(f"[{s['label']:>8} {s['score']:.3f}] relevant={is_relevant(s)}  {headline}")

        # timing for a single already-warm headline, isolated from model-load cost
        t1 = time.time()
        score_headlines_bulk([sample[0]])
        single_headline_elapsed = time.time() - t1

        print(f"\nfirst call (load + score {len(sample)} headlines): {load_and_score_elapsed:.2f}s")
        print(f"warm single-headline inference: {single_headline_elapsed:.3f}s")
