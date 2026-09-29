"""Provider-independent email delivery."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from app.core.config import settings


class EmailDeliveryError(RuntimeError):
    """Raised when an authentication email cannot be delivered."""


class EmailSender(Protocol):
    """Email operations required by the authentication service."""

    def send_verification(
        self,
        *,
        recipient: str,
        token: str,
        expires_hours: int,
    ) -> None:
        """Deliver an email-verification token."""


class UnconfiguredEmailSender:
    """Fail closed when no SMTP provider has been configured."""

    def send_verification(
        self,
        *,
        recipient: str,
        token: str,
        expires_hours: int,
    ) -> None:
        raise EmailDeliveryError("Email delivery is not configured")


class SMTPEmailSender:
    """SMTP implementation independent of any particular provider."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_email: str,
        username: str | None = None,
        password: str | None = None,
        starttls: bool = True,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.from_email = from_email
        self.username = username
        self.password = password
        self.starttls = starttls
        self.timeout_seconds = timeout_seconds

    def send_verification(
        self,
        *,
        recipient: str,
        token: str,
        expires_hours: int,
    ) -> None:
        message = EmailMessage()
        message["Subject"] = "Verify your email"
        message["From"] = self.from_email
        message["To"] = recipient
        message.set_content(
            "Secure Auth email verification\n\n"
            "Use this one-time verification token:\n\n"
            f"{token}\n\n"
            f"This token expires in {expires_hours} hours.\n\n"
            "If you did not create this account, ignore this message."
        )

        try:
            with smtplib.SMTP(
                self.host,
                self.port,
                timeout=self.timeout_seconds,
            ) as smtp:
                smtp.ehlo()

                if self.starttls:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()

                if self.username is not None:
                    if self.password is None:
                        raise EmailDeliveryError(
                            "SMTP password is required when username is configured"
                        )

                    smtp.login(
                        self.username,
                        self.password,
                    )

                smtp.send_message(message)

        except EmailDeliveryError:
            raise
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError("Email delivery failed") from exc


def build_email_sender() -> EmailSender:
    """Build the configured delivery backend without exposing credentials."""
    if settings.SMTP_HOST is None or settings.SMTP_FROM_EMAIL is None:
        return UnconfiguredEmailSender()

    password = (
        settings.SMTP_PASSWORD.get_secret_value()
        if settings.SMTP_PASSWORD is not None
        else None
    )

    return SMTPEmailSender(
        host=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        from_email=str(settings.SMTP_FROM_EMAIL),
        username=settings.SMTP_USERNAME,
        password=password,
        starttls=settings.SMTP_STARTTLS,
        timeout_seconds=settings.SMTP_TIMEOUT_SECONDS,
    )
