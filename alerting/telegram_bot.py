"""Telegram Bot API channel (primary), per section_data_pipeline.md section
4.2: free, HTTPS, a simple fire-and-forget POST -- no polling/listener needed
for a one-way alert channel. Needs TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
(register a bot via @BotFather in Telegram, then message it once and use
https://api.telegram.org/bot<token>/getUpdates to find your chat_id) --
see .env.example. Not registered/tested live in this pass since that requires
interactive setup in Telegram the operator has to do themselves; the HTTP
call shape below matches Telegram's documented Bot API exactly.
"""
from __future__ import annotations

import requests
from pydantic_settings import BaseSettings, SettingsConfigDict

TELEGRAM_API_BASE = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096  # Telegram's documented hard limit per message


class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


def is_configured(settings: TelegramSettings | None = None) -> bool:
    s = settings or TelegramSettings()
    return bool(s.telegram_bot_token and s.telegram_chat_id)


def send_telegram_message(text: str, settings: TelegramSettings | None = None, timeout: float = 10.0) -> bool:
    """Returns True on a confirmed Telegram API success response, False on
    any failure (not configured, network error, non-200/non-ok response) --
    never raises, since a failed alert must not crash the scheduled run that
    triggered it (the Discord webhook is the documented backup channel for
    exactly this failure mode, per section_data_pipeline.md section 4.2)."""
    s = settings or TelegramSettings()
    if not is_configured(s):
        return False

    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[: MAX_MESSAGE_LENGTH - 1] + "…"

    url = f"{TELEGRAM_API_BASE}/bot{s.telegram_bot_token}/sendMessage"
    try:
        response = requests.post(
            url, json={"chat_id": s.telegram_chat_id, "text": text, "parse_mode": "Markdown"}, timeout=timeout
        )
        return response.ok and response.json().get("ok", False)
    except requests.RequestException:
        return False


if __name__ == "__main__":
    settings = TelegramSettings()
    if not is_configured(settings):
        print("Telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing from .env) -- skipping live send.")
    else:
        ok = send_telegram_message("market-alpha-agents: Phase 5 smoke test.", settings)
        print(f"Sent: {ok}")
