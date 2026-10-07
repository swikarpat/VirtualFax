"""
Unit Tests - PDF Inspector and Ghostscript TIFF Converter
"""

from pathlib import Path
import pytest
from pypdf import PdfWriter
from gateway.converter import PdfConverter, TIFF_LITTLE_ENDIAN, TIFF_BIG_ENDIAN


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Creates a temporary valid 3-page PDF file."""
    pdf_path = tmp_path / "valid_test.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=612, height=792)
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


def test_inspect_valid_pdf(sample_pdf: Path):
    meta = PdfConverter.inspect_pdf(sample_pdf)
    assert meta.is_valid is True
    assert meta.page_count == 3
    assert meta.file_size_bytes > 0
    assert meta.error is None


def test_inspect_missing_pdf(tmp_path: Path):
    missing_path = tmp_path / "does_not_exist.pdf"
    meta = PdfConverter.inspect_pdf(missing_path)
    assert meta.is_valid is False
    assert "not found" in meta.error.lower()


def test_inspect_empty_pdf(tmp_path: Path):
    empty_path = tmp_path / "empty.pdf"
    empty_path.touch()
    meta = PdfConverter.inspect_pdf(empty_path)
    assert meta.is_valid is False
    assert "0 bytes" in meta.error.lower()


def test_convert_dry_run(sample_pdf: Path, tmp_path: Path):
    out_tiff = tmp_path / "converted.tif"
    res = PdfConverter.convert_to_tiff(
        pdf_path=sample_pdf,
        output_tiff_path=out_tiff,
        resolution="fine",
        dry_run=True,
    )
    assert res.success is True
    assert res.page_count == 3
    assert out_tiff.exists()

    with open(out_tiff, "rb") as f:
        magic = f.read(4)
        assert magic in (TIFF_LITTLE_ENDIAN, TIFF_BIG_ENDIAN)
