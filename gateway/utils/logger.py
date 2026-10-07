"""
Zero-Cost Fax Gateway - Logging Module
Provides beautiful terminal formatting via Rich and structured file logging.
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

console = Console()
error_console = Console(stderr=True)

LOGGER_NAME = "fax_gateway"


def setup_logger(
    level: str = "INFO",
    log_file: Optional[Path] = None,
) -> logging.Logger:
    """Configures the root logger with Rich console handler and optional file output."""
    logger = logging.getLogger(LOGGER_NAME)
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)

    # Avoid duplicate handlers on re-init
    if logger.handlers:
        logger.handlers.clear()

    # Rich console handler
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        markup=True,
    )
    rich_handler.setLevel(log_level)
    logger.addHandler(rich_handler)

    # File handler if path provided
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d) - %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG)  # Always log verbose to file
        logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    """Returns the configured gateway logger instance."""
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        return setup_logger()
    return logger


def print_banner():
    """Prints a styled CLI banner."""
    banner_text = (
        "[bold cyan]⚡ ZERO-COST ($0) DUAL-ROUTE VIRTUAL FAX GATEWAY[/bold cyan]\n"
        "[dim]India -> USA Free Transmission Engine | Government & Agency Gateway[/dim]\n"
        "[green]Route A:[/green] Toll-Free (8YY) -> Asterisk/SpanDSP -> Open 8YY SIP Trunk ($0.00)\n"
        "[yellow]Route B:[/yellow] Geographic (NANP) -> Playwright Web Relay -> Gmail IMAP Auto-Activation ($0.00)"
    )
    console.print(Panel(banner_text, border_style="cyan", expand=False))


def print_route_summary(
    number: str,
    route_type: str,
    agency_info: Optional[str] = None,
    pages: Optional[int] = None,
    dry_run: bool = False,
):
    """Prints a styled summary table before transmission."""
    table = Table(title="📋 Fax Transmission Manifest", border_style="blue")
    table.add_column("Property", style="bold white")
    table.add_column("Details", style="cyan")

    table.add_row("Destination", number)
    table.add_row("Route Selected", f"[{ 'green' if 'VOIP' in route_type else 'yellow' }]{route_type}[/]")
    if agency_info:
        table.add_row("Identified Agency", f"[magenta]{agency_info}[/magenta]")
    if pages is not None:
        table.add_row("Page Count", str(pages))
    table.add_row("Estimated Cost", "[bold green]$0.00 (Zero Out-of-Pocket)[/bold green]")
    table.add_row("Execution Mode", "[bold yellow]DRY RUN (Simulation)[/bold yellow]" if dry_run else "[bold green]LIVE DISPATCH[/bold green]")

    console.print(table)
