"""
Zero-Cost Fax Gateway - Abstract Web Gateway Interface
Defines the standard contract for headless browser fax dispatchers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SenderInfo:
    """Sender metadata for web gateway form submission."""
    name: str
    company: str
    email: str
    phone: str


@dataclass
class ReceiverInfo:
    """Recipient metadata for web gateway form submission."""
    name: str
    company: str
    fax_number: str  # 10 digits


@dataclass
class WebSubmissionResult:
    """Result of initial web form submission."""
    success: bool
    provider_name: str
    confirmation_pending: bool
    status_message: str
    screenshot_path: Optional[Path] = None
    error: Optional[str] = None


class BaseWebGateway(ABC):
    """Abstract interface for third-party zero-cost web fax gateways."""

    @abstractmethod
    def submit(
        self,
        sender: SenderInfo,
        receiver: ReceiverInfo,
        document_path: Path,
        cover_note: str = "",
        dry_run: bool = False,
    ) -> WebSubmissionResult:
        """Submits document via headless web automation."""
        pass
