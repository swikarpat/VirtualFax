"""
Zero-Cost Fax Gateway - PDF to TIFF Conversion Engine
Uses Ghostscript to convert PDF documents to ITU-T T.30 / T.38 compliant TIFF-F format
for Asterisk res_fax_spandsp transmission.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Optional, Tuple
from pypdf import PdfReader
from gateway.utils.logger import get_logger

logger = get_logger()

# Standard ITU-T T.4 / T.30 Fax Specifications
FINE_RES_DPI = "204x196"
STANDARD_RES_DPI = "204x98"
TIFF_LITTLE_ENDIAN = b"II*\x00"
TIFF_BIG_ENDIAN = b"MM\x00*"


@dataclass
class PdfMetadata:
    """PDF Document Analysis Report."""
    path: Path
    page_count: int
    file_size_bytes: int
    is_valid: bool
    error: Optional[str] = None


@dataclass
class ConversionResult:
    """Output report of the TIFF conversion process."""
    pdf_path: Path
    tiff_path: Path
    page_count: int
    tiff_size_bytes: int
    resolution: str
    conversion_command: str
    success: bool
    error: Optional[str] = None


class PdfConverter:
    """Handles PDF validation and Ghostscript conversion to Fax TIFF."""

    @staticmethod
    def get_ghostscript_path() -> Optional[str]:
        """Locates the Ghostscript executable (gs) on system PATH or standard locations."""
        # 1. System PATH
        which_gs = shutil.which("gs")
        if which_gs:
            return which_gs

        # 2. Common Homebrew macOS locations
        mac_paths = [
            "/opt/homebrew/bin/gs",
            "/usr/local/bin/gs",
        ]
        for p in mac_paths:
            if os.path.exists(p) and os.access(p, os.X_OK):
                return p

        # 3. Common Linux locations
        linux_paths = ["/usr/bin/gs", "/bin/gs"]
        for p in linux_paths:
            if os.path.exists(p) and os.access(p, os.X_OK):
                return p

        return None

    @classmethod
    def inspect_pdf(cls, pdf_path: Path) -> PdfMetadata:
        """Inspects and validates the input PDF file."""
        if not pdf_path.exists():
            return PdfMetadata(
                path=pdf_path,
                page_count=0,
                file_size_bytes=0,
                is_valid=False,
                error=f"PDF file not found at: {pdf_path}",
            )

        file_size = pdf_path.stat().st_size
        if file_size == 0:
            return PdfMetadata(
                path=pdf_path,
                page_count=0,
                file_size_bytes=0,
                is_valid=False,
                error="PDF file is 0 bytes (empty).",
            )

        try:
            reader = PdfReader(str(pdf_path))
            page_count = len(reader.pages)
            if page_count == 0:
                return PdfMetadata(
                    path=pdf_path,
                    page_count=0,
                    file_size_bytes=file_size,
                    is_valid=False,
                    error="PDF contains 0 pages.",
                )
            return PdfMetadata(
                path=pdf_path,
                page_count=page_count,
                file_size_bytes=file_size,
                is_valid=True,
            )
        except Exception as e:
            return PdfMetadata(
                path=pdf_path,
                page_count=0,
                file_size_bytes=file_size,
                is_valid=False,
                error=f"Failed to parse PDF document: {e}",
            )

    @classmethod
    def convert_to_tiff(
        cls,
        pdf_path: Path,
        output_tiff_path: Optional[Path] = None,
        resolution: str = "fine",
        dry_run: bool = False,
    ) -> ConversionResult:
        """
        Converts a PDF document to ITU-T Fax Class F TIFF (CCITT Group 4, US Letter).
        """
        pdf_path = Path(pdf_path).resolve()
        pdf_meta = cls.inspect_pdf(pdf_path)

        if not pdf_meta.is_valid:
            raise ValueError(f"Invalid PDF: {pdf_meta.error}")

        if output_tiff_path is None:
            output_tiff_path = pdf_path.with_suffix(".tif")
        else:
            output_tiff_path = Path(output_tiff_path).resolve()

        output_tiff_path.parent.mkdir(parents=True, exist_ok=True)

        res_flag = FINE_RES_DPI if resolution.lower() == "fine" else STANDARD_RES_DPI
        gs_binary = cls.get_ghostscript_path()

        cmd = [
            gs_binary or "gs",
            "-q",
            "-dNOPAUSE",
            "-dBATCH",
            "-sDEVICE=tiffg4",
            "-sPAPERSIZE=letter",
            f"-r{res_flag}",
            f"-sOutputFile={output_tiff_path}",
            str(pdf_path),
        ]
        cmd_str = " ".join(cmd)

        logger.debug(f"Ghostscript conversion command: {cmd_str}")

        if dry_run:
            logger.info(f"[yellow][DRY RUN][/yellow] Simulated PDF->TIFF conversion for: {pdf_path.name}")
            # In dry-run mode, if gs is not present or we don't want to write, write a mock TIFF header
            if not output_tiff_path.exists():
                with open(output_tiff_path, "wb") as f:
                    f.write(TIFF_LITTLE_ENDIAN + b"\x00" * 1024)

            return ConversionResult(
                pdf_path=pdf_path,
                tiff_path=output_tiff_path,
                page_count=pdf_meta.page_count,
                tiff_size_bytes=1028,
                resolution=res_flag,
                conversion_command=cmd_str,
                success=True,
            )

        if not gs_binary:
            # Ghostscript is missing on the host
            error_msg = (
                "Ghostscript binary ('gs') was not found on your system PATH.\n"
                "Install Ghostscript using:\n"
                "  • macOS: brew install ghostscript\n"
                "  • Ubuntu/Debian: sudo apt-get update && sudo apt-get install -y ghostscript"
            )
            logger.error(error_msg)
            return ConversionResult(
                pdf_path=pdf_path,
                tiff_path=output_tiff_path,
                page_count=pdf_meta.page_count,
                tiff_size_bytes=0,
                resolution=res_flag,
                conversion_command=cmd_str,
                success=False,
                error=error_msg,
            )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                err = f"Ghostscript exited with code {result.returncode}: {result.stderr.strip()}"
                logger.error(err)
                return ConversionResult(
                    pdf_path=pdf_path,
                    tiff_path=output_tiff_path,
                    page_count=pdf_meta.page_count,
                    tiff_size_bytes=0,
                    resolution=res_flag,
                    conversion_command=cmd_str,
                    success=False,
                    error=err,
                )

            # Validate generated TIFF file
            if not output_tiff_path.exists() or output_tiff_path.stat().st_size == 0:
                err = "Ghostscript completed but output TIFF file is empty or missing."
                logger.error(err)
                return ConversionResult(
                    pdf_path=pdf_path,
                    tiff_path=output_tiff_path,
                    page_count=pdf_meta.page_count,
                    tiff_size_bytes=0,
                    resolution=res_flag,
                    conversion_command=cmd_str,
                    success=False,
                    error=err,
                )

            # Verify TIFF magic bytes
            with open(output_tiff_path, "rb") as f:
                header = f.read(4)
                if header not in (TIFF_LITTLE_ENDIAN, TIFF_BIG_ENDIAN):
                    err = f"Output file does not have valid TIFF magic bytes. Got: {header!r}"
                    logger.error(err)
                    return ConversionResult(
                        pdf_path=pdf_path,
                        tiff_path=output_tiff_path,
                        page_count=pdf_meta.page_count,
                        tiff_size_bytes=output_tiff_path.stat().st_size,
                        resolution=res_flag,
                        conversion_command=cmd_str,
                        success=False,
                        error=err,
                    )

            tiff_size = output_tiff_path.stat().st_size
            logger.info(
                f"Successfully converted PDF ({pdf_meta.page_count} pages) to Fax TIFF: "
                f"{output_tiff_path.name} ({tiff_size / 1024:.1f} KB)"
            )

            return ConversionResult(
                pdf_path=pdf_path,
                tiff_path=output_tiff_path,
                page_count=pdf_meta.page_count,
                tiff_size_bytes=tiff_size,
                resolution=res_flag,
                conversion_command=cmd_str,
                success=True,
            )

        except Exception as e:
            logger.error(f"Failed to execute Ghostscript: {e}")
            return ConversionResult(
                pdf_path=pdf_path,
                tiff_path=output_tiff_path,
                page_count=pdf_meta.page_count,
                tiff_size_bytes=0,
                resolution=res_flag,
                conversion_command=cmd_str,
                success=False,
                error=str(e),
            )
