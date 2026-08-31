"""SMTP channel for the EOD/monthly digest emails, per
section_data_pipeline.md section 4.2/4.3: alerting/templates.py's
format_eod_summary/format_monthly_performance_digest already build the
message bodies -- this module only needs to send them. Needs
SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/SMTP_TO_ADDRESS (e.g. Gmail:
smtp.gmail.com:587 with an App Password) -- see .env.example. Not registered/
tested live in this pass since that requires real mailbox credentials the
operator has to provision themselves; the smtplib/STARTTLS call shape below
matches Python's documented stdlib usage exactly.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from pydantic_settings import BaseSettings, SettingsConfigDict


class EmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_to_address: str | None = None


def is_configured(settings: EmailSettings | None = None) -> bool:
    s = settings or EmailSettings()
    return bool(s.smtp_host and s.smtp_user and s.smtp_password and s.smtp_to_address)


def send_email(subject: str, body: str, settings: EmailSettings | None = None, timeout: float = 10.0) -> bool:
    """Returns True on a confirmed send, False on any failure (not
    configured, connection error, auth error, send error) -- never raises,
    since a failed alert must not crash the scheduled run that triggered it."""
    s = settings or EmailSettings()
    if not is_configured(s):
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = s.smtp_user
    message["To"] = s.smtp_to_address
    message.set_content(body)

    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=timeout) as server:
            server.starttls()
            server.login(s.smtp_user, s.smtp_password)
            server.send_message(message)
        return True
    except (smtplib.SMTPException, OSError):
        return False


if __name__ == "__main__":
    settings = EmailSettings()
    if not is_configured(settings):
        print("Email not configured (SMTP_HOST/SMTP_USER/SMTP_PASSWORD/SMTP_TO_ADDRESS missing from .env) -- skipping live send.")
    else:
        ok = send_email("market-alpha-agents: Phase 5 smoke test.", "This is a smoke test.", settings)
        print(f"Sent: {ok}")
