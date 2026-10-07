"""
Zero-Cost Fax Gateway - Route B: Web Relay & IMAP Auto-Activation Orchestrator
Dispatches PDF faxes to Geographic / Non-Toll-Free numbers (e.g., 510, 202, 415)
via automated Playwright web gateway and asynchronous Gmail IMAP email confirmation.
"""

from datetime import datetime
from pathlib import Path
import time
from typing import Optional, Tuple
import uuid
from gateway.config import settings
from gateway.converter import PdfConverter
from gateway.router import ParsedNumber, RouteType
from gateway.routes.base import BaseFaxRoute, FaxResult
from gateway.web.base_gateway import SenderInfo, ReceiverInfo
from gateway.web.faxzero import FaxZeroGateway
from gateway.web.imap_listener import ImapConfirmationListener
from gateway.utils.logger import console, get_logger

logger = get_logger()

MAX_WEB_FREE_PAGES = 3


class WebFaxRoute(BaseFaxRoute):
    """
    Route B implementation:
    Playwright Web Relay -> FaxZero Form Submission -> Gmail IMAP Link Auto-Activation.
    """

    def __init__(self):
        self.gateway = FaxZeroGateway()
        self.imap_listener = ImapConfirmationListener()

    def validate(
        self,
        parsed_number: ParsedNumber,
        pdf_path: Path,
    ) -> Tuple[bool, Optional[str]]:
        """Validates document structure and sender configuration."""
        pdf_meta = PdfConverter.inspect_pdf(pdf_path)
        if not pdf_meta.is_valid:
            return False, f"Invalid PDF file: {pdf_meta.error}"

        if not settings.fax_sender_email or "@" not in settings.fax_sender_email:
            return False, "FAX_SENDER_EMAIL is not configured with a valid email address in .env."

        return True, None

    def send(
        self,
        parsed_number: ParsedNumber,
        pdf_path: Path,
        recipient_name: str = "Authorized Agency Officer",
        cover_note: str = "",
        dry_run: bool = False,
        sender_email: Optional[str] = None,
    ) -> FaxResult:
        """Executes Route B dispatch with automated IMAP verification and chunking support."""
        start_time = time.time()
        logger.info(f"Initiating Route B (Web Gateway + IMAP) for: {parsed_number.formatted_display}")

        # 1. Validation
        is_valid, err = self.validate(parsed_number, pdf_path)
        if not is_valid:
            return FaxResult(
                success=False,
                route_type=RouteType.WEB_GEOGRAPHIC,
                destination_number=parsed_number.formatted_display,
                recipient_name=recipient_name,
                pages_sent=0,
                transaction_id="",
                details="Validation failed",
                error=err,
            )

        pdf_meta = PdfConverter.inspect_pdf(pdf_path)

        # If document exceeds 3 pages, delegate to FaxDispatcher chunking engine
        if pdf_meta.page_count > MAX_WEB_FREE_PAGES:
            from gateway.core.dispatcher import FaxDispatcher
            return FaxDispatcher.dispatch_web(
                parsed_number=parsed_number,
                pdf_path=pdf_path,
                recipient_name=recipient_name,
                cover_note=cover_note,
                dry_run=dry_run,
                web_engine=self,
            )

        # 2. Prepare Form Metadata with dynamic sender alias rotation
        resolved_email = (
            sender_email
            if sender_email
            else self.gateway.generate_email_alias(settings.fax_sender_email)
        )
        sender = SenderInfo(
            name=settings.fax_sender_name,
            company=settings.fax_sender_company,
            email=resolved_email,
            phone=settings.fax_sender_phone,
        )

        agency_name = parsed_number.agency_description or "US Government / Municipal Office"
        receiver = ReceiverInfo(
            name=recipient_name,
            company=agency_name,
            fax_number=parsed_number.normalized_10_digit,
        )

        # 3. Headless Browser Web Submission
        logger.info("Step 1/2: Submitting web gateway form via Playwright...")
        submission_res = self.gateway.submit(
            sender=sender,
            receiver=receiver,
            document_path=pdf_path,
            cover_note=cover_note,
            dry_run=dry_run,
        )

        if not submission_res.success:
            duration = round(time.time() - start_time, 2)
            return FaxResult(
                success=False,
                route_type=RouteType.WEB_GEOGRAPHIC,
                destination_number=parsed_number.formatted_display,
                recipient_name=recipient_name,
                pages_sent=0,
                transaction_id="",
                details="Web submission failed",
                cost_usd=0.00,
                duration_sec=duration,
                error=submission_res.error or submission_res.status_message,
            )

        # 4. Asynchronous IMAP Auto-Activation
        logger.info("Step 2/2: Awaiting activation email and auto-approving verification link...")
        activation_res = self.imap_listener.poll_for_confirmation(
            since_time=datetime.now(),
            dry_run=dry_run,
        )

        duration = round(time.time() - start_time, 2)

        if not activation_res.success:
            return FaxResult(
                success=False,
                route_type=RouteType.WEB_GEOGRAPHIC,
                destination_number=parsed_number.formatted_display,
                recipient_name=recipient_name,
                pages_sent=pdf_meta.page_count,
                transaction_id="",
                details="Form submitted, but email activation failed or timed out.",
                cost_usd=0.00,
                duration_sec=duration,
                error=activation_res.error,
            )

        tx_id = f"WEB-{uuid.uuid4().hex[:8].upper()}"
        return FaxResult(
            success=True,
            route_type=RouteType.WEB_GEOGRAPHIC,
            destination_number=parsed_number.formatted_display,
            recipient_name=recipient_name,
            pages_sent=pdf_meta.page_count,
            transaction_id=tx_id,
            details=(
                f"Dispatched via FaxZero relay and confirmed via Gmail IMAP in "
                f"{activation_res.elapsed_seconds:.1f}s. Link: {activation_res.confirmation_url}"
            ),
            cost_usd=0.00,
            duration_sec=duration,
        )
