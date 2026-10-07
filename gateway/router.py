"""
Zero-Cost Fax Gateway - Number Parser & Route Classifier
Normalizes North American Numbering Plan (NANP) numbers and determines optimal route:
  - Toll-Free (800, 888, 877, 866, 855, 844, 833) -> Route A (VoIP / 8YY SIP)
  - Geographic / Non-Toll-Free (e.g. 202, 510, 415) -> Route B (Web Gateway)
"""

from dataclasses import dataclass
from enum import Enum
import re
from typing import Optional
from gateway.config import routing_data


class RouteType(str, Enum):
    """Execution route classification."""
    VOIP_TOLLFREE = "VOIP_TOLLFREE"    # Route A: Open 8YY SIP Trunk
    WEB_GEOGRAPHIC = "WEB_GEOGRAPHIC"  # Route B: Web Gateway + IMAP Auto-Activation


class InvalidPhoneNumberError(ValueError):
    """Raised when an input number does not conform to NANP specifications."""
    pass


@dataclass
class ParsedNumber:
    """Represents a validated and normalized NANP telephone number."""
    raw: str
    normalized_10_digit: str        # e.g., '8008291040'
    e164: str                       # e.g., '+18008291040'
    sip_dial_string: str            # e.g., '18008291040' (Standard NANP SIP format)
    area_code: str                  # e.g., '800'
    exchange_code: str              # e.g., '829'
    subscriber_number: str          # e.g., '1040'
    is_toll_free: bool
    recommended_route: RouteType
    agency_description: Optional[str] = None

    @property
    def formatted_display(self) -> str:
        """Returns standard readable US format: +1 (NXX) NXX-XXXX."""
        return f"+1 ({self.area_code}) {self.exchange_code}-{self.subscriber_number}"


class NumberRouter:
    """Parses, validates, and routes telephone destinations."""

    @staticmethod
    def parse_nanp(number_str: str) -> ParsedNumber:
        """
        Parses any standard US/NANP phone representation.
        Accepts:
          - '+1 (800) 829-1040'
          - '1-800-829-1040'
          - '8008291040'
          - '800.829.1040'
          - '18008291040'
        """
        if not number_str or not isinstance(number_str, str):
            raise InvalidPhoneNumberError("Phone number must be a non-empty string.")

        # Strip all formatting characters
        digits = re.sub(r"[^\d]", "", number_str)

        # Handle NANP country code +1
        if len(digits) == 11:
            if not digits.startswith("1"):
                raise InvalidPhoneNumberError(
                    f"11-digit number must start with country code '1'. Got: '{digits}'"
                )
            digits = digits[1:]
        elif len(digits) != 10:
            raise InvalidPhoneNumberError(
                f"Invalid number length ({len(digits)} digits). "
                f"NANP requires 10 digits (e.g. 800-555-0199) or 11 digits with +1. Raw: '{number_str}'"
            )

        area_code = digits[0:3]
        exchange_code = digits[3:6]
        subscriber_number = digits[6:10]

        # NANP NXX rule validation: Area code and exchange code cannot start with 0 or 1
        if area_code[0] in ("0", "1"):
            raise InvalidPhoneNumberError(
                f"Invalid NANP Area Code '{area_code}'. Area codes cannot begin with 0 or 1."
            )
        if exchange_code[0] in ("0", "1"):
            raise InvalidPhoneNumberError(
                f"Invalid NANP Exchange Code '{exchange_code}'. Exchange codes cannot begin with 0 or 1."
            )

        # Toll-Free Classification
        is_toll_free = area_code in routing_data.toll_free_prefixes

        recommended_route = (
            RouteType.VOIP_TOLLFREE if is_toll_free else RouteType.WEB_GEOGRAPHIC
        )

        # Government directory lookup
        agency_desc = routing_data.lookup_agency(digits)

        return ParsedNumber(
            raw=number_str,
            normalized_10_digit=digits,
            e164=f"+1{digits}",
            sip_dial_string=f"1{digits}",
            area_code=area_code,
            exchange_code=exchange_code,
            subscriber_number=subscriber_number,
            is_toll_free=is_toll_free,
            recommended_route=recommended_route,
            agency_description=agency_desc,
        )

    @classmethod
    def resolve_route(
        cls, number_str: str, force_route: Optional[str] = None
    ) -> tuple[ParsedNumber, RouteType]:
        """
        Parses the phone number and determines the route.
        Allows overriding route via force_route ('voip', 'web', 'auto').
        """
        parsed = cls.parse_nanp(number_str)

        if force_route:
            force_lower = force_route.lower().strip()
            if force_lower in ("voip", "tollfree", "8yy"):
                return parsed, RouteType.VOIP_TOLLFREE
            elif force_lower in ("web", "geographic", "geo"):
                return parsed, RouteType.WEB_GEOGRAPHIC
            elif force_lower != "auto":
                raise ValueError(
                    f"Unknown route override: '{force_route}'. Choose 'auto', 'voip', or 'web'."
                )

        return parsed, parsed.recommended_route
