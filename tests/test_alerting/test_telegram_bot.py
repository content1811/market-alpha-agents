"""Tests for alerting/telegram_bot.py. Not configured in this environment
(no TELEGRAM_BOT_TOKEN registered) -- confirmed live that it reports that
state cleanly rather than crashing; these tests mock the HTTP layer to cover
the configured path without needing a real bot token."""
from __future__ import annotations

from alerting.telegram_bot import MAX_MESSAGE_LENGTH, TelegramSettings, is_configured, send_telegram_message


def test_is_configured_false_when_missing():
    assert is_configured(TelegramSettings(telegram_bot_token=None, telegram_chat_id=None)) is False


def test_is_configured_true_when_both_set():
    assert is_configured(TelegramSettings(telegram_bot_token="abc", telegram_chat_id="123")) is True


def test_send_returns_false_when_not_configured():
    assert send_telegram_message("hello", TelegramSettings()) is False


def test_send_returns_true_on_success(monkeypatch):
    import alerting.telegram_bot as tb

    class FakeResponse:
        ok = True

        def json(self):
            return {"ok": True}

    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(tb.requests, "post", fake_post)
    settings = TelegramSettings(telegram_bot_token="TOKEN", telegram_chat_id="CHATID")

    result = send_telegram_message("test message", settings)

    assert result is True
    assert captured["url"] == "https://api.telegram.org/botTOKEN/sendMessage"
    assert captured["json"]["chat_id"] == "CHATID"


def test_send_returns_false_on_network_error(monkeypatch):
    import alerting.telegram_bot as tb
    import requests

    def raise_error(*a, **k):
        raise requests.ConnectionError("simulated failure")

    monkeypatch.setattr(tb.requests, "post", raise_error)
    settings = TelegramSettings(telegram_bot_token="TOKEN", telegram_chat_id="CHATID")

    assert send_telegram_message("test", settings) is False


def test_message_truncated_at_max_length(monkeypatch):
    import alerting.telegram_bot as tb

    class FakeResponse:
        ok = True

        def json(self):
            return {"ok": True}

    captured = {}
    monkeypatch.setattr(tb.requests, "post", lambda url, json, timeout: (captured.update(json=json), FakeResponse())[1])
    settings = TelegramSettings(telegram_bot_token="TOKEN", telegram_chat_id="CHATID")

    send_telegram_message("x" * 5000, settings)

    assert len(captured["json"]["text"]) == MAX_MESSAGE_LENGTH
