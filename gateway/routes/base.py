"""
Zero-Cost Fax Gateway - Base Route Definition
Defines the common interface and result models for transmission routes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from gateway.router import ParsedNumber, RouteType


@dataclass
class FaxResult:
    """Standardized report returned by any fax transmission route."""
    success: bool
    route_type: RouteType
    destination_number: str
    recipient_name: str
    pages_sent: int
    transaction_id: str
    details: str
    cost_usd: float = 0.00
    duration_sec: float = 0.0
    error: Optional[str] = None


class BaseFaxRoute(ABC):
    """Abstract base class for all fax transmission routes."""

    @abstractmethod
    def validate(
        self,
        parsed_number: ParsedNumber,
        pdf_path: Path,
    ) -> Tuple[bool, Optional[str]]:
        """Validates prerequisites prior to attempting dispatch."""
        pass

    @abstractmethod
    def send(
        self,
        parsed_number: ParsedNumber,
        pdf_path: Path,
        recipient_name: str = "Authorized Recipient",
        cover_note: str = "",
        dry_run: bool = False,
    ) -> FaxResult:
        """Executes fax dispatch over the designated channel."""
        pass
