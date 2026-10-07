"""
Unit Tests - Phone Number Router & NANP Normalizer
"""

import pytest
from gateway.router import NumberRouter, RouteType, InvalidPhoneNumberError


def test_toll_free_detection():
    toll_free_numbers = [
        ("800-829-1040", "800"),
        ("+1 (888) 222-3344", "888"),
        ("1-877-477-0572", "877"),
        ("866.555.0199", "866"),
        ("8552151627", "855"),
        ("+18445550100", "844"),
        ("833-222-3333", "833"),
    ]
    for num_str, expected_area in toll_free_numbers:
        parsed = NumberRouter.parse_nanp(num_str)
        assert parsed.is_toll_free is True
        assert parsed.area_code == expected_area
        assert parsed.recommended_route == RouteType.VOIP_TOLLFREE
        assert len(parsed.normalized_10_digit) == 10
        assert parsed.sip_dial_string.startswith("1")


def test_geographic_detection():
    geographic_numbers = [
        ("510-444-1234", "510"),
        ("+1 (202) 619-0000", "202"),
        ("415.555.0123", "415"),
        ("13125550199", "312"),
    ]
    for num_str, expected_area in geographic_numbers:
        parsed = NumberRouter.parse_nanp(num_str)
        assert parsed.is_toll_free is False
        assert parsed.area_code == expected_area
        assert parsed.recommended_route == RouteType.WEB_GEOGRAPHIC


def test_agency_lookup():
    parsed = NumberRouter.parse_nanp("855-215-1627")
    assert parsed.agency_description is not None
    assert "Internal Revenue Service" in parsed.agency_description


def test_invalid_numbers():
    invalid_inputs = [
        "",
        "123",
        "555-0199",                  # 7 digits
        "+44 20 7946 0950",           # UK number
        "100-555-0199",               # Invalid area code starting with 1
        "020-555-0199",               # Invalid area code starting with 0
        "800-155-0199",               # Invalid exchange starting with 1
        "800-055-0199",               # Invalid exchange starting with 0
        "abcdefghij",
    ]
    for bad_num in invalid_inputs:
        with pytest.raises(InvalidPhoneNumberError):
            NumberRouter.parse_nanp(bad_num)


def test_route_override():
    parsed, route = NumberRouter.resolve_route("510-444-1234", force_route="voip")
    assert route == RouteType.VOIP_TOLLFREE

    parsed, route = NumberRouter.resolve_route("800-829-1040", force_route="web")
    assert route == RouteType.WEB_GEOGRAPHIC

    parsed, route = NumberRouter.resolve_route("800-829-1040", force_route="auto")
    assert route == RouteType.VOIP_TOLLFREE
