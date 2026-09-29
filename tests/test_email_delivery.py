"""Tests for provider-independent SMTP verification delivery."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.email_delivery import (
    EmailDeliveryError,
    SMTPEmailSender,
    UnconfiguredEmailSender,
)


def test_unconfigured_sender_fails_closed() -> None:
    sender = UnconfiguredEmailSender()

    with pytest.raises(
        EmailDeliveryError,
        match="not configured",
    ):
        sender.send_verification(
            recipient="user@example.com",
            token="secret-token",
            expires_hours=24,
        )


def test_smtp_sender_delivers_verification_message() -> None:
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp

    sender = SMTPEmailSender(
        host="smtp.example.com",
        port=587,
        from_email="security@example.com",
        username="mailer",
        password="smtp-secret",
        starttls=True,
    )

    with patch(
        "app.core.email_delivery.smtplib.SMTP",
        return_value=smtp,
    ):
        sender.send_verification(
            recipient="user@example.com",
            token="verification-secret",
            expires_hours=24,
        )

    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with(
        "mailer",
        "smtp-secret",
    )
    smtp.send_message.assert_called_once()

    message = smtp.send_message.call_args.args[0]

    assert message["To"] == "user@example.com"
    assert message["From"] == "security@example.com"
    assert "verification-secret" in message.get_content()


def test_smtp_sender_requires_password_with_username() -> None:
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp

    sender = SMTPEmailSender(
        host="smtp.example.com",
        port=587,
        from_email="security@example.com",
        username="mailer",
        password=None,
        starttls=False,
    )

    with (
        patch(
            "app.core.email_delivery.smtplib.SMTP",
            return_value=smtp,
        ),
        pytest.raises(
            EmailDeliveryError,
            match="password is required",
        ),
    ):
        sender.send_verification(
            recipient="user@example.com",
            token="verification-secret",
            expires_hours=24,
        )

    smtp.send_message.assert_not_called()
