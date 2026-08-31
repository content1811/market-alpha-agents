"""Discord webhook channel (backup), per section_data_pipeline.md section
4.2: free, HTTPS, a simple fire-and-forget POST -- no bot/gateway needed for
a one-way alert channel. Needs DISCORD_WEBHOOK_URL (Server Settings ->
Integrations -> Webhooks -> New Webhook -> Copy Webhook URL) -- see
.env.example. Not registered/tested live in this pass since that requires
interactive setup in Discord the operator has to do themselves; the HTTP
call shape below matches Discord's documented webhook API exactly.
"""
from __future__ import annotations

import requests
from pydantic_settings import BaseSettings, SettingsConfigDict

MAX_MESSAGE_LENGTH = 2000  # Discord's documented hard limit per webhook message


class DiscordSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    discord_webhook_url: str | None = None


def is_configured(settings: DiscordSettings | None = None) -> bool:
    s = settings or DiscordSettings()
    return bool(s.discord_webhook_url)


def send_discord_message(text: str, settings: DiscordSettings | None = None, timeout: float = 10.0) -> bool:
    """Returns True on a confirmed Discord webhook success response, False on
    any failure (not configured, network error, non-2xx response) -- never
    raises, since a failed alert must not crash the scheduled run that
    triggered it (Discord is itself the documented backup channel for
    exactly this failure mode on the Telegram side, per
    section_data_pipeline.md section 4.2)."""
    s = settings or DiscordSettings()
    if not is_configured(s):
        return False

    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[: MAX_MESSAGE_LENGTH - 1] + "…"

    try:
        response = requests.post(s.discord_webhook_url, json={"content": text}, timeout=timeout)
        return response.ok
    except requests.RequestException:
        return False


if __name__ == "__main__":
    settings = DiscordSettings()
    if not is_configured(settings):
        print("Discord not configured (DISCORD_WEBHOOK_URL missing from .env) -- skipping live send.")
    else:
        ok = send_discord_message("market-alpha-agents: Phase 5 smoke test.", settings)
        print(f"Sent: {ok}")
