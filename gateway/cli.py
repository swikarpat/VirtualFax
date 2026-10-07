"""
Zero-Cost ($0) Dual-Route Virtual Fax Gateway - Command Line Interface (CLI)
Provides command dispatch, number inspection, Ghostscript conversion testing,
system diagnostics, and container management.
"""

from pathlib import Path
import subprocess
import sys
from typing import Optional
import click
from rich.panel import Panel
from rich.table import Table

from gateway.config import settings
from gateway.converter import PdfConverter
from gateway.core.dispatcher import FaxDispatcher
from gateway.router import NumberRouter, RouteType, InvalidPhoneNumberError
from gateway.routes.base import FaxResult
from gateway.routes.voip_route import VoipFaxRoute
from gateway.routes.web_route import WebFaxRoute
from gateway.utils.logger import (
    console,
    error_console,
    get_logger,
    print_banner,
    print_route_summary,
    setup_logger,
)
from gateway.utils.system_check import SystemDoctor

logger = get_logger()

# Standard Exit Codes
EXIT_SUCCESS = 0
EXIT_INVALID_INPUT = 1
EXIT_VOIP_FAILURE = 2
EXIT_WEB_FAILURE = 3
EXIT_IMAP_TIMEOUT = 4
EXIT_SYSTEM_ERROR = 5


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose DEBUG logging.")
def cli(verbose: bool):
    """⚡ Zero-Cost ($0) Dual-Route Virtual Fax Gateway CLI."""
    log_level = "DEBUG" if verbose else settings.log_level
    log_file = Path("./gateway.log")
    setup_logger(level=log_level, log_file=log_file)


@cli.command()
@click.argument("number", type=str)
@click.argument("pdf_paths", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--recipient-name", "-r", default="Authorized Agency Official", help="Name of recipient or office.")
@click.option("--cover-note", "-c", default="", help="Optional text note or memo.")
@click.option(
    "--route",
    type=click.Choice(["auto", "voip", "web"], case_sensitive=False),
    default="auto",
    help="Route selection: 'auto' (default: 8YY->VoIP, Geo->Web), 'voip', or 'web'.",
)
@click.option("--dry-run", "-d", is_flag=True, help="Simulate execution without sending live faxes.")
def send(
    number: str,
    pdf_paths: tuple[Path, ...],
    recipient_name: str,
    cover_note: str,
    route: str,
    dry_run: bool,
):
    """
    Send one or more PDF fax documents to a US number (Toll-Free or Geographic).
    Multiple documents are automatically consolidated into a single PDF before routing.

    Example:
      faxctl send 855-215-1627 /path/to/irs_form.pdf --recipient-name "IRS Adoption Tax Credit"
      faxctl send 855-215-1627 doc1.pdf doc2.pdf doc3.pdf
      faxctl send 510-444-1234 /path/to/county_form.pdf --dry-run
    """
    print_banner()

    is_dry_run = dry_run or settings.dry_run_default

    # 1. Parse and classify phone number
    try:
        parsed_num, selected_route = NumberRouter.resolve_route(number, force_route=route)
    except (InvalidPhoneNumberError, ValueError) as e:
        error_console.print(f"[bold red]❌ Input Error:[/bold red] {e}")
        sys.exit(EXIT_INVALID_INPUT)

    # 2. Consolidate documents if multiple provided
    if len(pdf_paths) > 1:
        console.print(f"[bold cyan]📄 Merging Documents:[/bold cyan] Consolidating {len(pdf_paths)} documents into single PDF...")
        pdf_path = FaxDispatcher.merge_pdfs(pdf_paths)
    else:
        pdf_path = pdf_paths[0]

    # 3. Inspect PDF
    pdf_meta = PdfConverter.inspect_pdf(pdf_path)
    if not pdf_meta.is_valid:
        error_console.print(f"[bold red]❌ PDF Error:[/bold red] {pdf_meta.error}")
        sys.exit(EXIT_INVALID_INPUT)

    # 4. Print pre-flight manifest
    print_route_summary(
        number=parsed_num.formatted_display,
        route_type=selected_route.value,
        agency_info=parsed_num.agency_description,
        pages=pdf_meta.page_count,
        dry_run=is_dry_run,
    )

    # 5. Dispatch via central engine with automated Route A -> Route B failover
    result: FaxResult = FaxDispatcher.dispatch(
        parsed_number=parsed_num,
        selected_route=selected_route,
        pdf_path=pdf_path,
        recipient_name=recipient_name,
        cover_note=cover_note,
        dry_run=is_dry_run,
    )

    # 5. Display Outcome & Set Exit Code
    if result.success:
        panel_content = (
            f"[bold green]✔ FAX TRANSMISSION COMPLETED[/bold green]\n\n"
            f"[bold white]Destination:[/bold white] {result.destination_number}\n"
            f"[bold white]Recipient:[/bold white] {result.recipient_name}\n"
            f"[bold white]Route Engine:[/bold white] {result.route_type.value}\n"
            f"[bold white]Pages Transmitted:[/bold white] {result.pages_sent}\n"
            f"[bold white]Transaction ID:[/bold white] {result.transaction_id}\n"
            f"[bold white]Total Cost:[/bold white] [bold green]${result.cost_usd:.2f} USD (Zero-Cost)[/bold green]\n"
            f"[bold white]Duration:[/bold white] {result.duration_sec:.1f}s\n"
            f"[dim]{result.details}[/dim]"
        )
        console.print(Panel(panel_content, border_style="green"))
        sys.exit(EXIT_SUCCESS)
    else:
        err_content = (
            f"[bold red]❌ FAX TRANSMISSION FAILED[/bold red]\n\n"
            f"[bold white]Destination:[/bold white] {result.destination_number}\n"
            f"[bold white]Route Engine:[/bold white] {result.route_type.value}\n"
            f"[bold white]Reason:[/bold white] {result.error}\n"
            f"[bold white]Details:[/bold white] {result.details}\n"
        )
        console.print(Panel(err_content, border_style="red"))

        if "timeout" in (result.error or "").lower():
            sys.exit(EXIT_IMAP_TIMEOUT)
        elif result.route_type == RouteType.VOIP_TOLLFREE:
            sys.exit(EXIT_VOIP_FAILURE)
        else:
            sys.exit(EXIT_WEB_FAILURE)


@cli.command()
@click.argument("number", type=str)
def info(number: str):
    """Inspect and classify a phone number without sending."""
    print_banner()
    try:
        parsed = NumberRouter.parse_nanp(number)
    except InvalidPhoneNumberError as e:
        error_console.print(f"[bold red]❌ Invalid Number:[/bold red] {e}")
        sys.exit(EXIT_INVALID_INPUT)

    table = Table(title="🔍 Phone Number Analysis", border_style="cyan")
    table.add_column("Property", style="bold white")
    table.add_column("Value", style="cyan")

    table.add_row("Raw Input", parsed.raw)
    table.add_row("Display Format", parsed.formatted_display)
    table.add_row("10-Digit Normalization", parsed.normalized_10_digit)
    table.add_row("E.164 Format", parsed.e164)
    table.add_row("SIP Dial String", parsed.sip_dial_string)
    table.add_row("Area Code", parsed.area_code)
    table.add_row("Is Toll-Free (8YY)", "[bold green]YES[/bold green]" if parsed.is_toll_free else "NO")
    table.add_row("Default Route", f"[bold yellow]{parsed.recommended_route.value}[/bold yellow]")
    if parsed.agency_description:
        table.add_row("Known Agency", f"[magenta]{parsed.agency_description}[/magenta]")

    console.print(table)


@cli.command()
@click.argument("pdf_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", "-o", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--resolution", "-r", type=click.Choice(["fine", "standard"]), default="fine")
@click.option("--dry-run", "-d", is_flag=True, help="Simulate conversion.")
def convert(pdf_path: Path, output: Optional[Path], resolution: str, dry_run: bool):
    """Convert a PDF file to ITU-T Fax Class F TIFF (Ghostscript test)."""
    console.print(f"Converting [bold]{pdf_path.name}[/bold] to TIFF...")
    res = PdfConverter.convert_to_tiff(
        pdf_path=pdf_path,
        output_tiff_path=output,
        resolution=resolution,
        dry_run=dry_run,
    )
    if res.success:
        console.print(
            f"[bold green]✔ Conversion successful![/bold green]\n"
            f"Output: {res.tiff_path}\n"
            f"Pages: {res.page_count}\n"
            f"Resolution: {res.resolution}\n"
            f"Size: {res.tiff_size_bytes / 1024:.1f} KB"
        )
    else:
        error_console.print(f"[bold red]❌ Conversion failed:[/bold red] {res.error}")
        sys.exit(EXIT_SYSTEM_ERROR)


@cli.command()
def doctor():
    """Run full system diagnostics and dependency checks."""
    print_banner()
    SystemDoctor.run_doctor()


@cli.command("check-ip")
def check_ip():
    """Check current public egress IP and US VPN status."""
    console.print("Testing egress IP geolocation...")
    info = SystemDoctor.check_egress_ip()
    console.print(info["message"])


@cli.command("test-imap")
def test_imap():
    """Verify Gmail IMAP SSL connection and authentication."""
    console.print("Testing Gmail IMAP connectivity...")
    res = SystemDoctor.check_imap()
    if res["ok"]:
        console.print(f"[bold green]✔ {res['message']}[/bold green]")
    else:
        error_console.print(f"[bold red]❌ {res['message']}[/bold red]")
        sys.exit(EXIT_IMAP_TIMEOUT)


@cli.command("docker-up")
def docker_up():
    """Start the Asterisk 8YY VoIP container using docker-compose."""
    console.print("Starting Asterisk SpanDSP container...")
    try:
        subprocess.run(["docker", "compose", "up", "-d"], check=True)
        console.print("[bold green]✔ Asterisk container running.[/bold green]")
    except Exception as e:
        error_console.print(f"[bold red]❌ Docker compose failed: {e}[/bold red]")
        sys.exit(EXIT_SYSTEM_ERROR)


@cli.command("docker-down")
def docker_down():
    """Stop the Asterisk VoIP container."""
    console.print("Stopping Asterisk container...")
    try:
        subprocess.run(["docker", "compose", "down"], check=True)
        console.print("[bold green]✔ Asterisk container stopped.[/bold green]")
    except Exception as e:
        error_console.print(f"[bold red]❌ Docker compose down failed: {e}[/bold red]")
        sys.exit(EXIT_SYSTEM_ERROR)


@cli.command("remote-send")
@click.argument("number", type=str)
@click.argument("pdf_paths", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--recipient-name", "-r", default="Authorized Agency Official", help="Name of recipient or office.")
@click.option("--cover-note", "-c", default="", help="Optional text note or memo.")
@click.option(
    "--route",
    type=click.Choice(["auto", "voip", "web"], case_sensitive=False),
    default="auto",
    help="Route selection: 'auto' (default: 8YY->VoIP, Geo->Web), 'voip', or 'web'.",
)
@click.option("--dry-run", "-d", is_flag=True, help="Simulate execution without sending live faxes.")
def remote_send(
    number: str,
    pdf_paths: tuple[Path, ...],
    recipient_name: str,
    cover_note: str,
    route: str,
    dry_run: bool,
):
    """
    ⚡ Zero-Touch Ephemeral EC2 Dispatch.

    Automatically boots the remote EC2 instance, retrieves its dynamic public IP,
    verifies services, consolidates multiple documents into a single PDF if provided,
    uploads the PDF, executes the fax transmission, syncs receipts back to your Mac,
    and guarantees automatic shutdown.
    """
    print_banner()
    from gateway.remote_dispatcher import (
        EphemeralEC2Dispatcher,
        MissingAWSCredentialsError,
        RemoteDispatchError,
    )

    # Consolidate multiple documents into a single consolidated PDF before routing
    if len(pdf_paths) > 1:
        console.print(f"[bold cyan]📄 Merging Documents:[/bold cyan] Consolidating {len(pdf_paths)} documents into single PDF...")
        pdf_path = FaxDispatcher.merge_pdfs(pdf_paths)
    else:
        pdf_path = pdf_paths[0]

    try:
        dispatcher = EphemeralEC2Dispatcher()
        exit_code = dispatcher.run_ephemeral_dispatch(
            number=number,
            pdf_path=pdf_path,
            recipient_name=recipient_name,
            cover_note=cover_note,
            route=route,
            dry_run=dry_run,
        )
        sys.exit(exit_code)
    except MissingAWSCredentialsError as e:
        error_console.print(str(e))
        sys.exit(EXIT_INVALID_INPUT)
    except Exception as e:
        error_console.print(f"[bold red]❌ Remote Dispatch Error:[/bold red] {e}")
        sys.exit(EXIT_SYSTEM_ERROR)


def main():
    """Main CLI entrypoint."""
    cli()


if __name__ == "__main__":
    main()

