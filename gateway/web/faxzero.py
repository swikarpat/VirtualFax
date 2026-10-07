"""
Zero-Cost Fax Gateway - FaxZero Headless Browser Relay (Playwright)
Automates submission on FaxZero (zero-cost US fax provider, 3 pages free)
with anti-detection settings, form parsing, and debug screenshot logging.
"""

from datetime import datetime
import os
from pathlib import Path
import time
from typing import Optional, Union
import uuid
from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError
from gateway.config import settings
from gateway.web.base_gateway import (
    BaseWebGateway,
    SenderInfo,
    ReceiverInfo,
    WebSubmissionResult,
)
from gateway.utils.logger import get_logger

logger = get_logger()

FAXZERO_URL = "https://faxzero.com"
CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class FaxZeroGateway(BaseWebGateway):
    """Playwright-based automation adapter for FaxZero.com."""

    @classmethod
    def generate_email_alias(
        cls,
        base_email: str,
        identifier: Optional[Union[str, int]] = None,
    ) -> str:
        """
        Extracts base username and domain from base_email and generates a unique sender address:
        {base}+fax{hash_or_counter}@{domain}
        This prevents hitting FaxZero's 5-fax-per-day rate limit across multiple documents/chunks,
        while routing all activation emails to the user's primary inbox.
        """
        if not base_email or "@" not in base_email:
            raise ValueError(f"Invalid email address provided for alias generation: {base_email}")

        username, domain = base_email.split("@", 1)
        # Strip any existing tag if already present
        base_username = username.split("+")[0]
        domain = domain.strip()

        if identifier is not None:
            tag = f"fax{identifier}"
        else:
            tag = f"fax{uuid.uuid4().hex[:6]}"

        return f"{base_username}+{tag}@{domain}"

    def __init__(self):
        self.headless = settings.web_gateway_headless
        self.timeout_ms = settings.web_gateway_timeout_sec * 1000
        self.screenshot_dir = Path(settings.web_gateway_screenshot_dir).resolve()
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def _take_screenshot(self, page: Page, name: str) -> Path:
        """Captures a debug screenshot."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.screenshot_dir / f"faxzero_{name}_{timestamp}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
            logger.debug(f"Captured debug screenshot: {path}")
        except Exception as e:
            logger.warning(f"Could not take screenshot: {e}")
        return path

    def _fill_sender(self, page: Page, sender: SenderInfo):
        """Populates sender fields using robust fallback selectors."""
        # Name
        if page.locator("#input-fax_s_name").is_visible():
            page.fill("#input-fax_s_name", sender.name)
        elif page.locator("#sender_name").is_visible():
            page.fill("#sender_name", sender.name)
        elif page.locator("input[name='sender_name']").is_visible():
            page.fill("input[name='sender_name']", sender.name)

        # Company
        if page.locator("#input-fax_s_company").is_visible():
            page.fill("#input-fax_s_company", sender.company)
        elif page.locator("#sender_company").is_visible():
            page.fill("#sender_company", sender.company)
        elif page.locator("input[name='sender_company']").is_visible():
            page.fill("input[name='sender_company']", sender.company)

        # Email
        if page.locator("#input-fax_s_email").is_visible():
            page.fill("#input-fax_s_email", sender.email)
        elif page.locator("#sender_email").is_visible():
            page.fill("#sender_email", sender.email)
        elif page.locator("input[name='sender_email']").is_visible():
            page.fill("input[name='sender_email']", sender.email)

        # Phone (can be 1 single field or 3 split fields)
        digits = sender.phone.replace("+", "").replace("-", "")[-10:]
        if page.locator("#input-fax_s_phone").is_visible():
            page.fill("#input-fax_s_phone", digits)
        elif page.locator("#sender_phone").is_visible():
            page.fill("#sender_phone", digits)
        elif page.locator("input[name='sender_phone']").is_visible():
            page.fill("input[name='sender_phone']", digits)
        elif page.locator("#sender_phone_1").is_visible():
            page.fill("#sender_phone_1", digits[0:3])
            page.fill("#sender_phone_2", digits[3:6])
            page.fill("#sender_phone_3", digits[6:10])

    def _fill_receiver(self, page: Page, receiver: ReceiverInfo):
        """Populates receiver fields."""
        # Name
        if page.locator("#input-fax_r_name").is_visible():
            page.fill("#input-fax_r_name", receiver.name)
        elif page.locator("#receiver_name").is_visible():
            page.fill("#receiver_name", receiver.name)
        elif page.locator("input[name='receiver_name']").is_visible():
            page.fill("input[name='receiver_name']", receiver.name)

        # Company
        if page.locator("input[name='fax_r_company']").is_visible():
            page.fill("input[name='fax_r_company']", receiver.company)
        elif page.locator("#receiver_company").is_visible():
            page.fill("#receiver_company", receiver.company)
        elif page.locator("input[name='receiver_company']").is_visible():
            page.fill("input[name='receiver_company']", receiver.company)

        # Fax Number (10 digits)
        fax_digits = receiver.fax_number.replace("+", "").replace("-", "")[-10:]
        if page.locator("#input-fax_r_fax").is_visible():
            page.fill("#input-fax_r_fax", fax_digits)
        elif page.locator("#receiver_fax").is_visible():
            page.fill("#receiver_fax", fax_digits)
        elif page.locator("input[name='receiver_fax']").is_visible():
            page.fill("input[name='receiver_fax']", fax_digits)
        elif page.locator("#fax_phone").is_visible():
            page.fill("#fax_phone", fax_digits)
        elif page.locator("#receiver_phone_1").is_visible():
            page.fill("#receiver_phone_1", fax_digits[0:3])
            page.fill("#receiver_phone_2", fax_digits[3:6])
            page.fill("#receiver_phone_3", fax_digits[6:10])

    def _attach_document(self, page: Page, document_path: Path):
        """Attaches the PDF file to the file input."""
        file_input = page.locator("input[type='file']").first
        file_input.set_input_files(str(document_path))
        logger.info(f"Attached document: {document_path.name}")

    def submit(
        self,
        sender: SenderInfo,
        receiver: ReceiverInfo,
        document_path: Path,
        cover_note: str = "",
        dry_run: bool = False,
    ) -> WebSubmissionResult:
        """
        Submits the fax form on FaxZero and confirms that an email verification link
        has been triggered.
        """
        # Ensure dynamic email alias rotation is active to prevent rate limits
        if sender.email and "+fax" not in sender.email:
            aliased_email = self.generate_email_alias(sender.email)
            logger.info(f"Applying dynamic email alias rotation: {sender.email} -> {aliased_email}")
            sender = SenderInfo(
                name=sender.name,
                company=sender.company,
                email=aliased_email,
                phone=sender.phone,
            )

        logger.info(f"Opening FaxZero web portal ({FAXZERO_URL})...")

        proxy_config = None
        if settings.http_proxy:
            proxy_config = {"server": settings.http_proxy}
            logger.info(f"Using HTTP Proxy for Route B: {settings.http_proxy}")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                proxy=proxy_config,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            context: BrowserContext = browser.new_context(
                user_agent=CHROME_UA,
                viewport={"width": 1280, "height": 850},
                locale="en-US",
                timezone_id="America/New_York",
            )

            page: Page = context.new_page()
            page.set_default_timeout(self.timeout_ms)

            try:
                # 1. Navigate to FaxZero
                logger.info("Navigating to https://faxzero.com...")
                response = page.goto(FAXZERO_URL, wait_until="domcontentloaded")
                if response and response.status >= 400:
                    screenshot = self._take_screenshot(page, "http_error")
                    return WebSubmissionResult(
                        success=False,
                        provider_name="FaxZero",
                        confirmation_pending=False,
                        status_message=f"HTTP status {response.status}",
                        screenshot_path=screenshot,
                        error=f"FaxZero returned status {response.status}",
                    )

                page.wait_for_selector("input[type='file']", timeout=15000)

                # 2. Populate Form
                logger.info(f"Filling sender ({sender.name} <{sender.email}>) and receiver ({receiver.name} - {receiver.fax_number})...")
                self._fill_sender(page, sender)
                self._fill_receiver(page, receiver)
                self._attach_document(page, document_path)

                # Optional cover note / text
                if cover_note:
                    if page.locator("textarea[name='message']").is_visible():
                        page.fill("textarea[name='message']", cover_note)
                    elif page.locator("textarea[name='text']").is_visible():
                        page.fill("textarea[name='text']", cover_note)

                # Solve Captcha if present
                captcha_input = page.locator("#input-captcha, input[name='captcha']").first
                if captcha_input.is_visible():
                    logger.info("Captcha detected. Solving with ddddocr...")
                    try:
                        captcha_img = page.locator("img[src*='captcha']").first
                        img_bytes = captcha_img.screenshot()
                        import ddddocr
                        ocr = ddddocr.DdddOcr(show_ad=False)
                        code = ocr.classification(img_bytes).strip()
                        logger.info(f"Solved captcha code: {code}")
                        captcha_input.fill(code)
                    except Exception as e:
                        logger.warning(f"Could not solve captcha automatically: {e}")

                # 3. Handle Dry-Run
                if dry_run:
                    logger.info("[yellow][DRY RUN][/yellow] Verified form inputs, file attachment, and page elements. Halting before submission click.")
                    screenshot = self._take_screenshot(page, "dry_run")
                    browser.close()
                    return WebSubmissionResult(
                        success=True,
                        provider_name="FaxZero",
                        confirmation_pending=True,
                        status_message="Form populated and verified successfully (Dry Run).",
                        screenshot_path=screenshot,
                    )

                # 4. Submit Form
                logger.info("Submitting FaxZero dispatch form...")
                submit_button = page.locator("#free_fax_submit, button#free_fax_submit, input[type='submit'], button[type='submit']").first
                submit_button.click()

                # Wait for post-submission page load (domcontentloaded to prevent ad tracker networkidle hangs)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception as e:
                    logger.debug(f"domcontentloaded wait: {e}")

                # Poll DOM text for submission confirmation acknowledgment (prevents timeouts from ad network activity)
                confirmation_detected = False
                body_text = ""
                poll_start = time.time()
                while time.time() - poll_start < 15:
                    try:
                        body_text = page.locator("body").inner_text()
                        if any(phrase in body_text.lower() for phrase in [
                            "almost there",
                            "confirmation email",
                            "confirmation message",
                            "check your email",
                            "check your e-mail",
                            "we sent a confirmation",
                            "click the link",
                            "ready to send",
                        ]):
                            confirmation_detected = True
                            break
                    except Exception:
                        pass
                    page.wait_for_timeout(1000)

                screenshot = self._take_screenshot(page, "submitted")

                if confirmation_detected:
                    logger.info("FaxZero confirmed submission! Activation email dispatched to sender.")
                    browser.close()
                    return WebSubmissionResult(
                        success=True,
                        provider_name="FaxZero",
                        confirmation_pending=True,
                        status_message="FaxZero accepted submission; waiting for Gmail IMAP confirmation link.",
                        screenshot_path=screenshot,
                    )
                else:
                    # Check for form validation error banners
                    error_msg = f"Unexpected response text on page: {body_text[:200]}..."
                    logger.warning(error_msg)
                    browser.close()
                    return WebSubmissionResult(
                        success=False,
                        provider_name="FaxZero",
                        confirmation_pending=False,
                        status_message="Submission was not acknowledged by FaxZero.",
                        screenshot_path=screenshot,
                        error=error_msg,
                    )

            except PlaywrightTimeoutError as te:
                screenshot = self._take_screenshot(page, "timeout")
                browser.close()
                return WebSubmissionResult(
                    success=False,
                    provider_name="FaxZero",
                    confirmation_pending=False,
                    status_message="Playwright navigation or element timeout.",
                    screenshot_path=screenshot,
                    error=str(te),
                )
            except Exception as e:
                screenshot = self._take_screenshot(page, "exception")
                browser.close()
                return WebSubmissionResult(
                    success=False,
                    provider_name="FaxZero",
                    confirmation_pending=False,
                    status_message="Web automation failed.",
                    screenshot_path=screenshot,
                    error=str(e),
                )
