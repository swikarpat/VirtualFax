"""
Unit Tests - IMAP Confirmation Link Extraction & MIME Parsing
"""

from email.message import EmailMessage
from gateway.web.imap_listener import ImapConfirmationListener


def test_extract_faxzero_link_plain():
    listener = ImapConfirmationListener()
    body = (
        "Dear User,\n\n"
        "Thank you for using FaxZero.com. To confirm and send your free fax, please click on the link below:\n\n"
        "https://faxzero.com/confirm/89123847/3847129384719238\n\n"
        "If you did not request this fax, please ignore this email.\n"
    )
    link = listener.extract_link_from_text(body)
    assert link == "https://faxzero.com/confirm/89123847/3847129384719238"


def test_extract_faxzero_link_html():
    listener = ImapConfirmationListener()
    html_body = (
        "<html><body>"
        "<p>Please click <a href='https://faxzero.com/confirm/abc123token_valid'>here</a> to confirm your fax.</p>"
        "</body></html>"
    )
    link = listener.extract_link_from_text(html_body)
    assert link == "https://faxzero.com/confirm/abc123token_valid"


def test_extract_body_text_multipart():
    listener = ImapConfirmationListener()

    msg = EmailMessage()
    msg["Subject"] = "FaxZero.com Fax Confirmation"
    msg["From"] = "support@faxzero.com"
    msg["To"] = "user@gmail.com"
    msg.set_content("Plain text body: https://faxzero.com/confirm/token_plain")
    msg.add_alternative(
        "<html><body>HTML body: <a href='https://faxzero.com/confirm/token_plain'>link</a></body></html>",
        subtype="html",
    )

    extracted_body = listener._extract_body_text(msg)
    assert "token_plain" in extracted_body

    link = listener.extract_link_from_text(extracted_body)
    assert link == "https://faxzero.com/confirm/token_plain"


def test_no_link_present():
    listener = ImapConfirmationListener()
    body = "Just a regular email notification without any activation link."
    link = listener.extract_link_from_text(body)
    assert link is None
