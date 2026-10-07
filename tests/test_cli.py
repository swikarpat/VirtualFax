"""
Integration Tests - CLI Interface & Commands
"""

from pathlib import Path
from click.testing import CliRunner
import pytest
from pypdf import PdfWriter
from gateway.cli import cli, EXIT_SUCCESS, EXIT_INVALID_INPUT


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def test_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "cli_test_doc.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


def test_cli_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Zero-Cost" in result.output
    assert "send" in result.output
    assert "doctor" in result.output


def test_cli_info_toll_free(runner):
    result = runner.invoke(cli, ["info", "855-215-1627"])
    assert result.exit_code == EXIT_SUCCESS
    assert "8552151627" in result.output
    assert "VOIP_TOLLFREE" in result.output


def test_cli_info_geographic(runner):
    result = runner.invoke(cli, ["info", "(510) 444-1234"])
    assert result.exit_code == EXIT_SUCCESS
    assert "5104441234" in result.output
    assert "WEB_GEOGRAPHIC" in result.output


def test_cli_send_invalid_number(runner, test_pdf):
    result = runner.invoke(cli, ["send", "123", str(test_pdf)])
    assert result.exit_code == EXIT_INVALID_INPUT
    assert "Input Error" in result.output


def test_cli_send_missing_file(runner):
    result = runner.invoke(cli, ["send", "800-555-0199", "non_existent.pdf"])
    assert result.exit_code != EXIT_SUCCESS


def test_cli_send_voip_dry_run(runner, test_pdf):
    result = runner.invoke(cli, ["send", "800-829-1040", str(test_pdf), "--dry-run"])
    assert result.exit_code == EXIT_SUCCESS
    assert "VOIP_TOLLFREE" in result.output
    assert "TRANSMISSION COMPLETED" in result.output
    assert "$0.00" in result.output


def test_cli_convert_dry_run(runner, test_pdf):
    result = runner.invoke(cli, ["convert", str(test_pdf), "--dry-run"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Conversion successful" in result.output


def test_cli_send_multi_doc_dry_run(runner, tmp_path):
    # Create two test documents
    pdf1 = tmp_path / "partA.pdf"
    writer1 = PdfWriter()
    writer1.add_blank_page(width=612, height=792)
    with open(pdf1, "wb") as f:
        writer1.write(f)

    pdf2 = tmp_path / "partB.pdf"
    writer2 = PdfWriter()
    writer2.add_blank_page(width=612, height=792)
    writer2.add_blank_page(width=612, height=792)
    with open(pdf2, "wb") as f:
        writer2.write(f)

    result = runner.invoke(cli, ["send", "800-829-1040", str(pdf1), str(pdf2), "--dry-run"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Merging Documents" in result.output
    assert "Consolidating 2 documents" in result.output
    assert "TRANSMISSION COMPLETED" in result.output
    assert "Pages Transmitted: 3" in result.output
