"""
Zero-Cost ($0) Dual-Route Virtual Fax Gateway - Central Dispatcher & Failover Engine
Coordinates transmission dispatch across Route A (VoIP 8YY) and Route B (Web Relay),
with automatic failover to Route B if Route A experiences upstream carrier rejections.
Supports multi-document merging, auto-chunking (3-page slices), and dynamic Gmail alias rotation.
"""

from pathlib import Path
import time
from typing import List, Optional, Sequence, Tuple, Union
import uuid

from pypdf import PdfReader, PdfWriter

from gateway.config import settings
from gateway.converter import PdfConverter
from gateway.router import ParsedNumber, RouteType
from gateway.routes.base import FaxResult
from gateway.routes.voip_route import VoipFaxRoute
from gateway.routes.web_route import WebFaxRoute
from gateway.web.faxzero import FaxZeroGateway
from gateway.utils.logger import console, get_logger

logger = get_logger()


class FaxDispatcher:
    """
    Central dispatcher coordinating Route A and Route B with automatic failover,
    multi-document consolidation, 3-page chunking, and dynamic alias rotation.
    """

    @classmethod
    def merge_pdfs(
        cls,
        pdf_paths: Sequence[Path],
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Merges multiple PDF documents into a single consolidated PDF file using pypdf.
        """
        if not pdf_paths:
            raise ValueError("No PDF documents provided for merging.")

        # If a single file is provided and no specific output path is requested, return it directly
        if len(pdf_paths) == 1 and output_path is None:
            resolved = Path(pdf_paths[0]).resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"PDF document not found: {resolved}")
            return resolved

        if output_path is None:
            scratch_dir = Path("scratch")
            scratch_dir.mkdir(parents=True, exist_ok=True)
            output_path = scratch_dir / f"merged_fax_{int(time.time())}_{uuid.uuid4().hex[:6]}.pdf"
        else:
            output_path = Path(output_path).resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)

        writer = PdfWriter()
        for p in pdf_paths:
            path_obj = Path(p).resolve()
            if not path_obj.exists():
                raise FileNotFoundError(f"PDF document not found: {path_obj}")
            reader = PdfReader(str(path_obj))
            for page in reader.pages:
                writer.add_page(page)

        with open(output_path, "wb") as f:
            writer.write(f)

        logger.info(
            f"Merged {len(pdf_paths)} documents into consolidated PDF: "
            f"{output_path.name} ({len(writer.pages)} pages)"
        )
        return output_path

    @classmethod
    def calculate_chunks(
        cls,
        total_pages: int,
        chunk_size: int = 3,
    ) -> List[Tuple[int, int]]:
        """
        Calculates consecutive 1-indexed page boundaries for chunking.
        E.g., 7 pages with chunk_size 3 -> [(1, 3), (4, 6), (7, 7)]
        """
        if total_pages <= 0 or chunk_size <= 0:
            return []

        chunks: List[Tuple[int, int]] = []
        start = 1
        while start <= total_pages:
            end = min(start + chunk_size - 1, total_pages)
            chunks.append((start, end))
            start += chunk_size

        return chunks

    @classmethod
    def slice_pdf(
        cls,
        pdf_path: Path,
        output_dir: Optional[Path] = None,
        chunk_size: int = 3,
    ) -> List[Path]:
        """
        Slices a PDF document into consecutive chunks of chunk_size pages (default 3 pages)
        using pypdf. Returns a list of paths to the generated chunk PDF files.
        """
        pdf_path = Path(pdf_path).resolve()
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        reader = PdfReader(str(pdf_path))
        total_pages = len(reader.pages)

        if total_pages <= chunk_size:
            return [pdf_path]

        if output_dir is None:
            output_dir = Path("scratch/chunks")
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        chunk_ranges = cls.calculate_chunks(total_pages, chunk_size)
        total_chunks = len(chunk_ranges)
        chunk_files: List[Path] = []

        for idx, (start_pg, end_pg) in enumerate(chunk_ranges, 1):
            writer = PdfWriter()
            # pypdf pages are 0-indexed: start_pg - 1 up to end_pg
            for pg_num in range(start_pg - 1, end_pg):
                writer.add_page(reader.pages[pg_num])

            chunk_file = output_dir / f"{pdf_path.stem}_part_{idx}_of_{total_chunks}.pdf"
            with open(chunk_file, "wb") as f:
                writer.write(f)

            logger.debug(
                f"Generated chunk {idx}/{total_chunks}: {chunk_file.name} "
                f"(pages {start_pg}-{end_pg}, {len(writer.pages)} pages)"
            )
            chunk_files.append(chunk_file)

        return chunk_files

    @classmethod
    def generate_email_alias(
        cls,
        base_email: str,
        identifier: Optional[Union[str, int]] = None,
    ) -> str:
        """
        Extracts base username and domain from base_email and generates a unique alias:
        {base}+fax{hash_or_counter}@{domain}
        """
        return FaxZeroGateway.generate_email_alias(base_email, identifier)

    @classmethod
    def dispatch_web(
        cls,
        parsed_number: ParsedNumber,
        pdf_path: Path,
        recipient_name: str = "Authorized Agency Official",
        cover_note: str = "",
        dry_run: bool = False,
        web_engine: Optional[WebFaxRoute] = None,
    ) -> FaxResult:
        """
        Dispatches fax via Route B (Web Relay) with automatic 3-page chunking,
        sequential transmission, cover notes indicating [Part X of Y], and dynamic
        email alias rotation ({base}+fax{counter}@{domain}) for high-volume sending.
        """
        engine = web_engine or WebFaxRoute()
        pdf_meta = PdfConverter.inspect_pdf(pdf_path)
        if not pdf_meta.is_valid:
            return FaxResult(
                success=False,
                route_type=RouteType.WEB_GEOGRAPHIC,
                destination_number=parsed_number.formatted_display,
                recipient_name=recipient_name,
                pages_sent=0,
                transaction_id="",
                details="Invalid PDF file",
                error=pdf_meta.error,
            )

        total_pages = pdf_meta.page_count

        # If total document pages <= 3: single transmission with dynamic alias rotation
        if total_pages <= 3:
            alias = cls.generate_email_alias(settings.fax_sender_email)
            logger.info(f"Route B: Transmitting document ({total_pages} pages) via {alias}")
            return engine.send(
                parsed_number=parsed_number,
                pdf_path=pdf_path,
                recipient_name=recipient_name,
                cover_note=cover_note,
                dry_run=dry_run,
                sender_email=alias,
            )

        # If total document pages > 3: Slice into 3-page chunks and transmit sequentially
        chunk_files = cls.slice_pdf(pdf_path, chunk_size=3)
        total_chunks = len(chunk_files)

        console.print(
            f"\n[bold cyan]📑 Auto-Chunking Route B Document:[/bold cyan] "
            f"Total {total_pages} pages sliced into {total_chunks} parts (3 pages max per chunk)."
        )
        logger.info(
            f"Route B Auto-Chunking: {pdf_path.name} ({total_pages} pages) split into "
            f"{total_chunks} sequential chunks."
        )

        total_pages_sent = 0
        tx_ids: List[str] = []
        start_time = time.time()

        for idx, chunk_path in enumerate(chunk_files, 1):
            chunk_meta = PdfConverter.inspect_pdf(chunk_path)
            # a. Format cover note with [Part X of Y]
            part_header = f"[Part {idx} of {total_chunks}]"
            chunk_cover_note = f"{part_header} {cover_note}".strip() if cover_note else part_header

            # b. Dynamic email alias for this chunk
            chunk_alias = cls.generate_email_alias(settings.fax_sender_email, identifier=idx)

            console.print(
                f"[bold cyan]📤 Transmitting {part_header}[/bold cyan] ({chunk_meta.page_count} pages) "
                f"using sender alias [bold yellow]{chunk_alias}[/bold yellow]..."
            )
            logger.info(
                f"Transmitting chunk {idx}/{total_chunks} ({chunk_path.name}) to "
                f"{parsed_number.formatted_display} with alias {chunk_alias}"
            )

            chunk_res = engine.send(
                parsed_number=parsed_number,
                pdf_path=chunk_path,
                recipient_name=recipient_name,
                cover_note=chunk_cover_note,
                dry_run=dry_run,
                sender_email=chunk_alias,
            )

            if not chunk_res.success:
                err_msg = f"Transmission failed on {part_header}: {chunk_res.error}"
                logger.error(err_msg)
                return FaxResult(
                    success=False,
                    route_type=RouteType.WEB_GEOGRAPHIC,
                    destination_number=parsed_number.formatted_display,
                    recipient_name=recipient_name,
                    pages_sent=total_pages_sent,
                    transaction_id=",".join(tx_ids),
                    details=f"Sequential chunk transmission halted: {chunk_res.details}",
                    cost_usd=0.00,
                    duration_sec=round(time.time() - start_time, 2),
                    error=err_msg,
                )

            total_pages_sent += chunk_res.pages_sent
            if chunk_res.transaction_id:
                tx_ids.append(chunk_res.transaction_id)
            logger.info(f"Chunk {idx}/{total_chunks} succeeded (TX: {chunk_res.transaction_id})")

        duration = round(time.time() - start_time, 2)
        combined_tx = ",".join(tx_ids) if tx_ids else f"WEB-MULTI-{uuid.uuid4().hex[:8].upper()}"

        return FaxResult(
            success=True,
            route_type=RouteType.WEB_GEOGRAPHIC,
            destination_number=parsed_number.formatted_display,
            recipient_name=recipient_name,
            pages_sent=total_pages_sent,
            transaction_id=combined_tx,
            details=(
                f"All {total_chunks} parts successfully transmitted sequentially "
                f"({total_pages_sent} pages total) via dynamic Gmail alias rotation."
            ),
            cost_usd=0.00,
            duration_sec=duration,
        )

    @classmethod
    def dispatch(
        cls,
        parsed_number: ParsedNumber,
        selected_route: RouteType,
        pdf_path: Path,
        recipient_name: str = "Authorized Agency Official",
        cover_note: str = "",
        dry_run: bool = False,
    ) -> FaxResult:
        """
        Dispatches fax to destination, executing Route A with auto-failover to Route B
        if upstream carrier issues or SIP rejections occur.
        """
        if selected_route == RouteType.VOIP_TOLLFREE:
            logger.info(
                f"Dispatching via primary route: Route A (VoIP/8YY) for {parsed_number.formatted_display}"
            )
            voip_engine = VoipFaxRoute()
            result = voip_engine.send(
                parsed_number=parsed_number,
                pdf_path=pdf_path,
                recipient_name=recipient_name,
                cover_note=cover_note,
                dry_run=dry_run,
            )

            # If Route A succeeds, return result immediately
            if result.success:
                return result

            # Route A failed (SIP 503, carrier auth rejection, or trunk unavailability)
            warn_msg = (
                f"Route A (VoIP/Asterisk) rejected for {parsed_number.formatted_display}: "
                f"[{result.error}]. Engaging AUTOMATIC FAILOVER to Route B (Web Relay + ddddocr)..."
            )
            logger.warning(warn_msg)
            console.print(f"\n[bold yellow]⚠ FAILOVER TRIGGERED:[/bold yellow] {warn_msg}\n")

            # Execute automatic failover via Route B (Web Relay) with chunking & alias rotation
            fallback_result = cls.dispatch_web(
                parsed_number=parsed_number,
                pdf_path=pdf_path,
                recipient_name=recipient_name,
                cover_note=cover_note,
                dry_run=dry_run,
            )

            if fallback_result.success:
                fallback_result.details = (
                    f"Automated Failover: Route A VoIP rejected ({result.error}); "
                    f"successfully dispatched via Route B Web Relay. {fallback_result.details}"
                )
                logger.info(
                    f"Failover successful: Fax delivered to {parsed_number.formatted_display} via Route B."
                )
                return fallback_result
            else:
                logger.error(
                    f"Both Route A and Route B failover failed for {parsed_number.formatted_display}."
                )
                fallback_result.details = (
                    f"Primary Route A failed ({result.error}) AND Failover Route B failed ({fallback_result.error})."
                )
                return fallback_result

        else:
            # Route B: Geographic / Web Relay
            logger.info(
                f"Dispatching via Route B (Web Relay) for {parsed_number.formatted_display}"
            )
            return cls.dispatch_web(
                parsed_number=parsed_number,
                pdf_path=pdf_path,
                recipient_name=recipient_name,
                cover_note=cover_note,
                dry_run=dry_run,
            )
