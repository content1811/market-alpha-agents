"""LLM client abstraction: Rakuten AI Gateway (Claude) primary, local Ollama
fallback, swappable via config per docs/plan/section_orchestration.md section 1.

The Rakuten gateway construction below mirrors the live-verified pattern in
../Server_failure/rakuten-failure-agent/src/rfa/agent/llm.py -- do not deviate
without re-verifying against a live call:
  - the gateway key does NOT go in `api_key`; it goes in a
    `default_headers={"Authorization": f"Bearer {key}"}` override, with
    `anthropic_api_key` set to an unused placeholder string.
  - claude-sonnet-5 rejects `temperature` outright (400 invalid_request_error),
    so it is never passed.
  - `max_tokens=128_000` is claude-sonnet-5's real output ceiling. A smaller
    max_tokens can starve a reply entirely if the model's server-side
    "thinking" consumes the whole budget before emitting any text (observed
    live in the sibling project) -- use the real ceiling, not "just enough".
  - `streaming=True` is required at this max_tokens size, since the SDK
    refuses non-streaming requests it estimates will run past ~10 minutes.

Every agent call in this system asks for a short, schema-constrained JSON
verdict (see agents/schemas.py), so in practice responses are small -- the
128k ceiling is headroom for the thinking-budget failure mode above, not an
expectation that replies are actually that long.
"""
from __future__ import annotations

import json
import re
from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

MAX_OUTPUT_TOKENS = 128_000
T = TypeVar("T", bound=BaseModel)


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    rakuten_api_key: str | None = None
    rakuten_base_url: str | None = None
    llm_model: str = "claude-sonnet-5"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"


class LLMCallError(Exception):
    pass


def build_primary_llm(settings: LLMSettings | None = None, model: str | None = None):
    from langchain_anthropic import ChatAnthropic

    s = settings or LLMSettings()
    if not s.rakuten_api_key or not s.rakuten_base_url:
        raise LLMCallError(
            "RAKUTEN_API_KEY/RAKUTEN_BASE_URL not set -- copy them from the "
            "gateway-using project's .env, or configure a different provider."
        )
    return ChatAnthropic(
        model=model or s.llm_model,
        max_tokens=MAX_OUTPUT_TOKENS,
        streaming=True,
        anthropic_api_url=s.rakuten_base_url,
        anthropic_api_key="unused-placeholder-gateway-ignores-this",
        default_headers={"Authorization": f"Bearer {s.rakuten_api_key}"},
        timeout=600,
        max_retries=2,
        # Do NOT pass temperature= -- claude-sonnet-5 returns 400 if present.
    )


def build_fallback_llm(settings: LLMSettings | None = None):
    from langchain_ollama import ChatOllama

    s = settings or LLMSettings()
    return ChatOllama(model=s.ollama_model, base_url=s.ollama_base_url, temperature=0.1)


def _extract_json(text: str) -> str:
    """Strip markdown code fences if the model wrapped its JSON in ```json ... ```."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    return text.strip()


def call_structured(
    system_prompt: str,
    user_prompt: str,
    schema: type[T],
    llm=None,
    max_repair_attempts: int = 1,
) -> T:
    """Call an LLM and parse+validate its reply against `schema`, retrying
    once with a repair prompt on validation failure -- per the Phase 2 test
    requirement in section_orchestration.md section 3 ("the LLM call always
    returns schema-valid JSON (retry-with-repair on validation failure)").
    """
    if llm is None:
        llm = build_primary_llm()

    schema_hint = json.dumps(schema.model_json_schema(), indent=2)
    full_system = (
        f"{system_prompt}\n\nRespond with ONLY a single JSON object matching "
        f"this JSON Schema, no prose before or after:\n{schema_hint}"
    )
    messages = [SystemMessage(content=full_system), HumanMessage(content=user_prompt)]

    last_error: Exception | None = None
    last_parsed: dict | None = None
    for attempt in range(max_repair_attempts + 1):
        response = llm.invoke(messages)
        raw_text = response.content if isinstance(response.content, str) else str(response.content)
        try:
            parsed = json.loads(_extract_json(raw_text))
            last_parsed = parsed
            return schema.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            messages.append(HumanMessage(content=raw_text))
            messages.append(HumanMessage(content=_repair_instructions(e)))

    # Last resort, specifically for the common case of an over-length string
    # field: models are unreliable at self-estimating character counts, so a
    # repair round-trip on length alone often just produces another
    # over-length string. If every remaining error is string_too_long, hard-
    # truncate those fields at a word boundary instead of failing outright.
    if last_parsed is not None and isinstance(last_error, ValidationError):
        if all(err["type"] == "string_too_long" for err in last_error.errors()):
            repaired = dict(last_parsed)
            for err in last_error.errors():
                field = err["loc"][-1]
                max_length = err["ctx"]["max_length"]
                repaired[field] = _truncate_at_word_boundary(repaired[field], max_length)
            try:
                return schema.model_validate(repaired)
            except ValidationError:
                pass

    raise LLMCallError(f"LLM did not return schema-valid JSON after {max_repair_attempts + 1} attempts: {last_error}")


def _repair_instructions(error: Exception) -> str:
    if isinstance(error, ValidationError):
        for err in error.errors():
            if err["type"] == "string_too_long":
                field = ".".join(str(p) for p in err["loc"])
                max_length = err["ctx"]["max_length"]
                actual_length = len(err["input"]) if isinstance(err.get("input"), str) else None
                return (
                    f"Field '{field}' is too long: {actual_length or '?'} characters, "
                    f"but the limit is {max_length}. Return ONLY the corrected JSON object "
                    f"with '{field}' shortened to {max_length} characters or fewer -- count carefully."
                )
    return f"That response was not valid: {error}\nReturn ONLY the corrected JSON object, matching the schema exactly."


def _truncate_at_word_boundary(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated
