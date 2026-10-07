"""
Zero-Cost Fax Gateway - Asynchronous Gmail IMAP Auto-Activation Listener
Monitors Gmail inbox for incoming activation links from free fax web gateways
and triggers instant confirmation within seconds.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
import email
from email.header import decode_header
import imaplib
import re
import time
from typing import Optional, Tuple
import httpx
from gateway.config import settings
from gateway.utils.logger import get_logger

logger = get_logger()

# Regex pattern for FaxZero activation links
FAXZERO_CONFIRM_REGEX = re.compile(
    r"https?://(?:www\.)?faxzero\.com/confirm/[a-zA-Z0-9_\-\.\?&=/]+",
    re.IGNORECASE,
)

GENERIC_CONFIRM_REGEX = re.compile(
    r"https?://[^\s\"'<>]+(?:confirm|activate|verify)[^\s\"'<>]*",
    re.IGNORECASE,
)


@dataclass
class ImapActivationResult:
    """Outcome of the IMAP activation link detection and execution."""
    success: bool
    confirmation_url: Optional[str] = None
    email_subject: Optional[str] = None
    message_id: Optional[str] = None
    elapsed_seconds: float = 0.0
    error: Optional[str] = None


class ImapConfirmationListener:
    """Asynchronous/polling IMAP listener for Gmail auto-activation."""

    def __init__(
        self,
        server: str = settings.gmail_imap_server,
        port: int = settings.gmail_imap_port,
        username: str = settings.gmail_username,
        app_password: str = settings.gmail_app_password,
        poll_timeout_sec: int = settings.gmail_poll_timeout_sec,
        poll_interval_sec: int = settings.gmail_poll_interval_sec,
    ):
        self.server = server
        self.port = port
        self.username = username
        self.password = app_password
        self.timeout = poll_timeout_sec
        self.interval = poll_interval_sec

    def _extract_body_text(self, msg: email.message.Message) -> str:
        """Extracts plain text and HTML content from a MIME message."""
        body_parts = []
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if "attachment" not in content_disposition:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        try:
                            body_parts.append(payload.decode(charset, errors="ignore"))
                        except Exception:
                            body_parts.append(payload.decode("utf-8", errors="ignore"))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                try:
                    body_parts.append(payload.decode(charset, errors="ignore"))
                except Exception:
                    body_parts.append(payload.decode("utf-8", errors="ignore"))

        return "\n".join(body_parts)

    def extract_link_from_text(self, text: str) -> Optional[str]:
        """Scans message text for the gateway activation link."""
        match = FAXZERO_CONFIRM_REGEX.search(text)
        if match:
            return match.group(0).strip(".,;\"'")

        fallback = GENERIC_CONFIRM_REGEX.search(text)
        if fallback:
            return fallback.group(0).strip(".,;\"'")

        return None

    def execute_activation(self, url: str) -> Tuple[bool, str]:
        """
        Visits the confirmation URL to activate the pending fax.
        """
        logger.info(f"Triggering auto-activation HTTP GET on: {url}")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    text_lower = resp.text.lower()
                    if any(term in text_lower for term in [
                        "verified",
                        "will be delivered",
                        "has been sent",
                        "thank you",
                        "delivered",
                        "almost done",
                    ]):
                        logger.info("Activation successfully verified by web gateway!")
                        return True, "Confirmation accepted and fax is queued for transmission."
                    return True, "Activation URL visited with HTTP 200."
                return False, f"Activation URL returned HTTP status {resp.status_code}"
        except Exception as e:
            logger.error(f"Failed to visit activation link: {e}")
            return False, f"HTTP activation error: {e}"

    def poll_for_confirmation(
        self,
        since_time: Optional[datetime] = None,
        dry_run: bool = False,
    ) -> ImapActivationResult:
        """
        Polls IMAP inbox until the confirmation email is found and activated.
        """
        start_time = time.time()
        logger.info(f"Starting IMAP listener for account: {self.username} (Timeout: {self.timeout}s)...")

        if dry_run:
            logger.info("[yellow][DRY RUN][/yellow] Simulated IMAP listener: Returning mock confirmation link.")
            mock_url = "https://faxzero.com/confirm/mock-activation-token-dry-run-0001"
            return ImapActivationResult(
                success=True,
                confirmation_url=mock_url,
                email_subject="FaxZero.com Fax Confirmation (Simulated)",
                message_id="<mock-msg-id-1234@faxzero.com>",
                elapsed_seconds=1.5,
            )

        if not self.password or "xxxx" in self.password:
            err = (
                "GMAIL_APP_PASSWORD is not configured in .env.\n"
                "To enable Route B auto-activation, generate a 16-character App Password at:\n"
                "https://myaccount.google.com/apppasswords"
            )
            logger.error(err)
            return ImapActivationResult(
                success=False,
                error=err,
            )

        deadline = start_time + self.timeout

        while time.time() < deadline:
            elapsed = time.time() - start_time
            logger.info(f"Checking IMAP inbox ({elapsed:.0f}s elapsed)...")

            try:
                mail = imaplib.IMAP4_SSL(self.server, self.port)
                mail.login(self.username, self.password)
                mail.select("INBOX")

                # Search for recent messages from FaxZero or matching keywords
                status, messages = mail.search(None, '(OR FROM "faxzero" SUBJECT "FaxZero")')
                if status == "OK" and messages[0]:
                    msg_ids = messages[0].split()
                    # Check recent messages in reverse order
                    for msg_id in reversed(msg_ids[-5:]):
                        _, msg_data = mail.fetch(msg_id, "(RFC822)")
                        raw_email = msg_data[0][1]
                        email_message = email.message_from_bytes(raw_email)

                        subject = email_message.get("Subject", "")
                        body = self._extract_body_text(email_message)

                        link = self.extract_link_from_text(body)
                        if link:
                            logger.info(f"Discovered activation link in email: '{subject}' -> {link}")
                            mail.logout()

                            # Immediately execute the activation request
                            act_ok, act_msg = self.execute_activation(link)

                            return ImapActivationResult(
                                success=act_ok,
                                confirmation_url=link,
                                email_subject=subject,
                                message_id=str(msg_id),
                                elapsed_seconds=round(time.time() - start_time, 2),
                                error=None if act_ok else act_msg,
                            )

                mail.logout()

            except Exception as e:
                logger.warning(f"IMAP polling cycle encountered transient issue: {e}")

            time.sleep(self.interval)

        return ImapActivationResult(
            success=False,
            elapsed_seconds=round(time.time() - start_time, 2),
            error=f"Timed out waiting for confirmation email after {self.timeout}s.",
        )
