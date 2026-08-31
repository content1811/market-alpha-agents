"""Tests for alerting/discord_bot.py. Not configured in this environment
(no DISCORD_WEBHOOK_URL registered) -- confirmed that it reports that state
cleanly rather than crashing; these tests mock the HTTP layer to cover the
configured path without needing a real webhook URL."""
from __future__ import annotations

from alerting.discord_bot import MAX_MESSAGE_LENGTH, DiscordSettings, is_configured, send_discord_message


def test_is_configured_false_when_missing():
    assert is_configured(DiscordSettings(discord_webhook_url=None)) is False


def test_is_configured_true_when_set():
    assert is_configured(DiscordSettings(discord_webhook_url="https://discord.com/api/webhooks/123/abc")) is True


def test_send_returns_false_when_not_configured():
    assert send_discord_message("hello", DiscordSettings()) is False


def test_send_returns_true_on_success(monkeypatch):
    import alerting.discord_bot as db

    class FakeResponse:
        ok = True

    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(db.requests, "post", fake_post)
    settings = DiscordSettings(discord_webhook_url="https://discord.com/api/webhooks/123/abc")

    result = send_discord_message("test message", settings)

    assert result is True
    assert captured["url"] == "https://discord.com/api/webhooks/123/abc"
    assert captured["json"]["content"] == "test message"


def test_send_returns_false_on_failure_response(monkeypatch):
    import alerting.discord_bot as db

    class FakeResponse:
        ok = False

    monkeypatch.setattr(db.requests, "post", lambda url, json, timeout: FakeResponse())
    settings = DiscordSettings(discord_webhook_url="https://discord.com/api/webhooks/123/abc")

    assert send_discord_message("test", settings) is False


def test_send_returns_false_on_network_error(monkeypatch):
    import alerting.discord_bot as db
    import requests

    def raise_error(*a, **k):
        raise requests.ConnectionError("simulated failure")

    monkeypatch.setattr(db.requests, "post", raise_error)
    settings = DiscordSettings(discord_webhook_url="https://discord.com/api/webhooks/123/abc")

    assert send_discord_message("test", settings) is False


def test_message_truncated_at_max_length(monkeypatch):
    import alerting.discord_bot as db

    class FakeResponse:
        ok = True

    captured = {}
    monkeypatch.setattr(db.requests, "post", lambda url, json, timeout: (captured.update(json=json), FakeResponse())[1])
    settings = DiscordSettings(discord_webhook_url="https://discord.com/api/webhooks/123/abc")

    send_discord_message("x" * 5000, settings)

    assert len(captured["json"]["content"]) == MAX_MESSAGE_LENGTH
