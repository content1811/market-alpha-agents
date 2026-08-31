"""Tests for alerting/email_smtp.py. Not configured in this environment (no
SMTP_HOST/SMTP_USER/SMTP_PASSWORD registered) -- these tests mock the
smtplib.SMTP layer to cover the configured path without needing a real
mailbox."""
from __future__ import annotations

import smtplib

from alerting.email_smtp import EmailSettings, is_configured, send_email


def test_is_configured_false_when_missing():
    assert (
        is_configured(
            EmailSettings(smtp_host=None, smtp_user=None, smtp_password=None, smtp_to_address=None)
        )
        is False
    )


def test_is_configured_true_when_all_set():
    assert (
        is_configured(
            EmailSettings(
                smtp_host="smtp.gmail.com",
                smtp_user="me@example.com",
                smtp_password="app-password",
                smtp_to_address="me@example.com",
            )
        )
        is True
    )


def test_send_returns_false_when_not_configured():
    assert send_email("subject", "body", EmailSettings()) is False


def test_send_returns_true_on_success(monkeypatch):
    import alerting.email_smtp as es

    calls = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls["host"] = host
            calls["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def starttls(self):
            calls["starttls"] = True

        def login(self, user, password):
            calls["login"] = (user, password)

        def send_message(self, message):
            calls["message"] = message

    monkeypatch.setattr(es.smtplib, "SMTP", FakeSMTP)
    settings = EmailSettings(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_user="me@example.com",
        smtp_password="app-password",
        smtp_to_address="dest@example.com",
    )

    result = send_email("Test subject", "Test body", settings)

    assert result is True
    assert calls["host"] == "smtp.gmail.com"
    assert calls["port"] == 587
    assert calls["starttls"] is True
    assert calls["login"] == ("me@example.com", "app-password")
    assert calls["message"]["Subject"] == "Test subject"
    assert calls["message"]["To"] == "dest@example.com"


def test_send_returns_false_on_smtp_exception(monkeypatch):
    import alerting.email_smtp as es

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            raise smtplib.SMTPConnectError(421, "simulated failure")

        def __exit__(self, *exc_info):
            return False

    monkeypatch.setattr(es.smtplib, "SMTP", FakeSMTP)
    settings = EmailSettings(
        smtp_host="smtp.gmail.com",
        smtp_user="me@example.com",
        smtp_password="app-password",
        smtp_to_address="dest@example.com",
    )

    assert send_email("subject", "body", settings) is False


def test_send_returns_false_on_os_error(monkeypatch):
    import alerting.email_smtp as es

    def raise_error(*a, **k):
        raise OSError("simulated network failure")

    monkeypatch.setattr(es.smtplib, "SMTP", raise_error)
    settings = EmailSettings(
        smtp_host="smtp.gmail.com",
        smtp_user="me@example.com",
        smtp_password="app-password",
        smtp_to_address="dest@example.com",
    )

    assert send_email("subject", "body", settings) is False
