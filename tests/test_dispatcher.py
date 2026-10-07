"""
Unit & Integration Tests - Fax Dispatcher, Multi-Document Merging,
3-Page Chunking, and Dynamic Gmail Alias Rotation.
"""

from pathlib import Path
import re
from unittest.mock import MagicMock, patch
import pytest
from pypdf import PdfReader, PdfWriter

from gateway.core.dispatcher import FaxDispatcher
from gateway.router import NumberRouter, RouteType
from gateway.routes.base import FaxResult
from gateway.routes.web_route import WebFaxRoute
from gateway.web.faxzero import FaxZeroGateway


@pytest.fixture
def create_pdf(tmp_path: Path):
    """Factory fixture for generating test PDFs with arbitrary page counts."""
    def _create(filename: str, page_count: int = 1) -> Path:
        p = tmp_path / filename
        writer = PdfWriter()
        for _ in range(page_count):
            writer.add_blank_page(width=612, height=792)
        with open(p, "wb") as f:
            writer.write(f)
        return p
    return _create


# ==============================================================================
# 1. Multi-Document Merging Tests
# ==============================================================================

def test_merge_two_pdfs(create_pdf, tmp_path: Path):
    doc1 = create_pdf("doc1.pdf", page_count=2)
    doc2 = create_pdf("doc2.pdf", page_count=3)

    out_file = tmp_path / "merged_out.pdf"
    merged = FaxDispatcher.merge_pdfs([doc1, doc2], output_path=out_file)

    assert merged == out_file
    assert merged.exists()

    reader = PdfReader(str(merged))
    assert len(reader.pages) == 5


def test_merge_three_pdfs_scratch(create_pdf):
    doc1 = create_pdf("docA.pdf", page_count=1)
    doc2 = create_pdf("docB.pdf", page_count=2)
    doc3 = create_pdf("docC.pdf", page_count=4)

    merged = FaxDispatcher.merge_pdfs([doc1, doc2, doc3])
    assert merged.exists()

    reader = PdfReader(str(merged))
    assert len(reader.pages) == 7


def test_merge_single_pdf_returns_original(create_pdf):
    doc = create_pdf("single.pdf", page_count=3)
    res = FaxDispatcher.merge_pdfs([doc])
    assert res == doc.resolve()


def test_merge_empty_list_raises_error():
    with pytest.raises(ValueError, match="No PDF documents"):
        FaxDispatcher.merge_pdfs([])


def test_merge_missing_file_raises_error(tmp_path: Path):
    missing = tmp_path / "does_not_exist.pdf"
    with pytest.raises(FileNotFoundError):
        FaxDispatcher.merge_pdfs([missing])


# ==============================================================================
# 2. 3-Page Chunking Calculation Tests
# ==============================================================================

def test_calculate_chunks_standard():
    # 7 pages with default chunk_size=3 -> 1-3, 4-6, 7-7
    chunks = FaxDispatcher.calculate_chunks(7, chunk_size=3)
    assert chunks == [(1, 3), (4, 6), (7, 7)]


def test_calculate_chunks_boundary_cases():
    assert FaxDispatcher.calculate_chunks(0) == []
    assert FaxDispatcher.calculate_chunks(-5) == []
    assert FaxDispatcher.calculate_chunks(1) == [(1, 1)]
    assert FaxDispatcher.calculate_chunks(2) == [(1, 2)]
    assert FaxDispatcher.calculate_chunks(3) == [(1, 3)]
    assert FaxDispatcher.calculate_chunks(4) == [(1, 3), (4, 4)]
    assert FaxDispatcher.calculate_chunks(6) == [(1, 3), (4, 6)]
    assert FaxDispatcher.calculate_chunks(8) == [(1, 3), (4, 6), (7, 8)]
    assert FaxDispatcher.calculate_chunks(9) == [(1, 3), (4, 6), (7, 9)]
    assert FaxDispatcher.calculate_chunks(10) == [(1, 3), (4, 6), (7, 9), (10, 10)]


def test_calculate_chunks_custom_size():
    # 5 pages with chunk_size=2 -> (1,2), (3,4), (5,5)
    chunks = FaxDispatcher.calculate_chunks(5, chunk_size=2)
    assert chunks == [(1, 2), (3, 4), (5, 5)]


def test_slice_pdf_into_chunks(create_pdf, tmp_path: Path):
    doc = create_pdf("multi_doc.pdf", page_count=7)
    chunks_dir = tmp_path / "chunks"

    chunk_files = FaxDispatcher.slice_pdf(doc, output_dir=chunks_dir, chunk_size=3)
    assert len(chunk_files) == 3

    # Verify pages per chunk
    c1 = PdfReader(str(chunk_files[0]))
    c2 = PdfReader(str(chunk_files[1]))
    c3 = PdfReader(str(chunk_files[2]))

    assert len(c1.pages) == 3
    assert len(c2.pages) == 3
    assert len(c3.pages) == 1

    # Verify naming convention
    assert "part_1_of_3" in chunk_files[0].name
    assert "part_2_of_3" in chunk_files[1].name
    assert "part_3_of_3" in chunk_files[2].name


def test_slice_pdf_small_doc_not_sliced(create_pdf, tmp_path: Path):
    doc = create_pdf("small_doc.pdf", page_count=3)
    chunks = FaxDispatcher.slice_pdf(doc, output_dir=tmp_path / "chunks", chunk_size=3)
    assert len(chunks) == 1
    assert chunks[0] == doc.resolve()


# ==============================================================================
# 3. Dynamic Gmail Alias Generation Tests
# ==============================================================================

def test_generate_email_alias_counter():
    alias1 = FaxDispatcher.generate_email_alias("user.test@gmail.com", 1)
    assert alias1 == "user.test+fax1@gmail.com"

    alias2 = FaxDispatcher.generate_email_alias("user.test@gmail.com", 2)
    assert alias2 == "user.test+fax2@gmail.com"


def test_generate_email_alias_strips_existing_tags():
    alias = FaxDispatcher.generate_email_alias("user.test+legacy@gmail.com", "part1")
    assert alias == "user.test+faxpart1@gmail.com"


def test_generate_email_alias_custom_domain():
    alias = FaxDispatcher.generate_email_alias("officer@uspto.gov", 42)
    assert alias == "officer+fax42@uspto.gov"


def test_generate_email_alias_random_hash():
    alias = FaxDispatcher.generate_email_alias("user.test@gmail.com")
    pattern = r"^user\.test\+fax[a-f0-9]{6}@gmail\.com$"
    assert re.match(pattern, alias) is not None


def test_generate_email_alias_via_faxzero_gateway():
    alias = FaxZeroGateway.generate_email_alias("user.test@gmail.com", 5)
    assert alias == "user.test+fax5@gmail.com"


def test_generate_email_alias_invalid():
    with pytest.raises(ValueError, match="Invalid email address"):
        FaxDispatcher.generate_email_alias("invalid_no_at_sign")


# ==============================================================================
# 4. Sequential Chunk Transmission on Route B Tests
# ==============================================================================

def test_dispatch_web_auto_chunking_success(create_pdf):
    doc = create_pdf("seven_pages.pdf", page_count=7)
    parsed_num = NumberRouter.parse_nanp("510-444-1234")

    mock_engine = MagicMock(spec=WebFaxRoute)
    # Simulate successful transmission for each chunk
    mock_engine.send.side_effect = [
        FaxResult(success=True, route_type=RouteType.WEB_GEOGRAPHIC, destination_number="5104441234", recipient_name="Alameda County Office", pages_sent=3, transaction_id="TX-PART1", details="Part 1 delivered"),
        FaxResult(success=True, route_type=RouteType.WEB_GEOGRAPHIC, destination_number="5104441234", recipient_name="Alameda County Office", pages_sent=3, transaction_id="TX-PART2", details="Part 2 delivered"),
        FaxResult(success=True, route_type=RouteType.WEB_GEOGRAPHIC, destination_number="5104441234", recipient_name="Alameda County Office", pages_sent=1, transaction_id="TX-PART3", details="Part 3 delivered"),
    ]

    with patch("gateway.config.settings.fax_sender_email", "user.test@gmail.com"):
        res = FaxDispatcher.dispatch_web(
            parsed_number=parsed_num,
            pdf_path=doc,
            recipient_name="Alameda County Office",
            cover_note="Urgent Legal Packet",
            dry_run=True,
            web_engine=mock_engine,
        )

    assert res.success is True
    assert res.pages_sent == 7
    assert mock_engine.send.call_count == 3
    assert "TX-PART1,TX-PART2,TX-PART3" in res.transaction_id

    # Verify each call received sequential cover note and aliased email
    calls = mock_engine.send.call_args_list

    # Chunk 1
    assert "[Part 1 of 3]" in calls[0].kwargs["cover_note"]
    assert "Urgent Legal Packet" in calls[0].kwargs["cover_note"]
    assert calls[0].kwargs["sender_email"] == "user.test+fax1@gmail.com"

    # Chunk 2
    assert "[Part 2 of 3]" in calls[1].kwargs["cover_note"]
    assert calls[1].kwargs["sender_email"] == "user.test+fax2@gmail.com"

    # Chunk 3
    assert "[Part 3 of 3]" in calls[2].kwargs["cover_note"]
    assert calls[2].kwargs["sender_email"] == "user.test+fax3@gmail.com"


def test_dispatch_web_chunk_failure_aborts_cleanly(create_pdf):
    doc = create_pdf("four_pages.pdf", page_count=4)
    parsed_num = NumberRouter.parse_nanp("510-444-1234")

    mock_engine = MagicMock(spec=WebFaxRoute)
    # Part 1 succeeds, Part 2 fails
    mock_engine.send.side_effect = [
        FaxResult(success=True, route_type=RouteType.WEB_GEOGRAPHIC, destination_number="5104441234", recipient_name="Alameda County Office", pages_sent=3, transaction_id="TX-OK", details="Part 1 delivered"),
        FaxResult(success=False, route_type=RouteType.WEB_GEOGRAPHIC, destination_number="5104441234", recipient_name="Alameda County Office", pages_sent=0, transaction_id="", details="Failed", error="FaxZero network error"),
    ]

    with patch("gateway.config.settings.fax_sender_email", "user.test@gmail.com"):
        res = FaxDispatcher.dispatch_web(
            parsed_number=parsed_num,
            pdf_path=doc,
            web_engine=mock_engine,
        )

    assert res.success is False
    assert "[Part 2 of 2]" in res.error
    assert res.pages_sent == 3
    assert mock_engine.send.call_count == 2


def test_dispatch_voip_no_chunking_unlimited_pages(create_pdf):
    """Route A (8YY VoIP) transmits multi-page documents without chunking."""
    doc = create_pdf("ten_pages.pdf", page_count=10)
    parsed_num = NumberRouter.parse_nanp("800-829-1040")

    with patch("gateway.core.dispatcher.VoipFaxRoute") as mock_voip_cls:
        mock_voip = MagicMock()
        mock_voip.send.return_value = FaxResult(
            success=True,
            route_type=RouteType.VOIP_TOLLFREE,
            destination_number="+1 (800) 829-1040",
            recipient_name="IRS Toll Free",
            pages_sent=10,
            transaction_id="VOIP-TX-10PAGES",
            details="Transmitted 10 pages in single call session via 8YY",
        )
        mock_voip_cls.return_value = mock_voip

        res = FaxDispatcher.dispatch(
            parsed_number=parsed_num,
            selected_route=RouteType.VOIP_TOLLFREE,
            pdf_path=doc,
            recipient_name="IRS Toll Free",
        )

        assert res.success is True
        assert res.pages_sent == 10
        # VoipFaxRoute called exactly once with the unchunked 10-page PDF
        mock_voip.send.assert_called_once()
        assert mock_voip.send.call_args.kwargs["pdf_path"] == doc


def test_dispatch_failover_to_web_with_chunking(create_pdf):
    """When Route A fails, failover to Route B executes auto-chunking."""
    doc = create_pdf("five_pages.pdf", page_count=5)
    parsed_num = NumberRouter.parse_nanp("800-829-1040")

    with patch("gateway.core.dispatcher.VoipFaxRoute") as mock_voip_cls, \
         patch.object(FaxDispatcher, "dispatch_web") as mock_web_dispatch:

        mock_voip = MagicMock()
        mock_voip.send.return_value = FaxResult(
            success=False,
            route_type=RouteType.VOIP_TOLLFREE,
            destination_number="+1 (800) 829-1040",
            recipient_name="IRS",
            pages_sent=0,
            transaction_id="",
            details="SIP 503 Service Unavailable",
            error="Trunk Rejected",
        )
        mock_voip_cls.return_value = mock_voip

        mock_web_dispatch.return_value = FaxResult(
            success=True,
            route_type=RouteType.WEB_GEOGRAPHIC,
            destination_number="+1 (800) 829-1040",
            recipient_name="IRS",
            pages_sent=5,
            transaction_id="WEB-FAILOVER-TX",
            details="Delivered via Web failover in 2 chunks",
        )

        res = FaxDispatcher.dispatch(
            parsed_number=parsed_num,
            selected_route=RouteType.VOIP_TOLLFREE,
            pdf_path=doc,
            recipient_name="IRS",
        )

        assert res.success is True
        assert res.pages_sent == 5
        mock_voip.send.assert_called_once()
        mock_web_dispatch.assert_called_once()
        assert "Automated Failover" in res.details
