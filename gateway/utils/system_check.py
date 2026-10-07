"""
Zero-Cost Fax Gateway - System Diagnostics & Pre-flight Checker
Validates local and cloud dependencies:
  - Ghostscript installation
  - Docker daemon & container status
  - Playwright browser binaries
  - Egress IP geolocation & US VPN detection
  - Gmail IMAP credentials & connectivity
"""

import imaplib
import shutil
import subprocess
from typing import Dict, Any, Optional
import httpx
from rich.table import Table
from gateway.config import settings
from gateway.converter import PdfConverter
from gateway.utils.logger import console, get_logger

logger = get_logger()


class SystemDoctor:
    """Diagnoses environment readiness for zero-cost faxing."""

    @staticmethod
    def check_ghostscript() -> Dict[str, Any]:
        """Checks for Ghostscript (gs) binary."""
        gs_path = PdfConverter.get_ghostscript_path()
        if not gs_path:
            return {
                "ok": False,
                "version": None,
                "path": None,
                "message": "Ghostscript ('gs') not found. Install via 'brew install ghostscript' (Mac) or 'sudo apt-get install -y ghostscript' (Linux).",
            }
        try:
            res = subprocess.run([gs_path, "--version"], capture_output=True, text=True, check=False)
            version = res.stdout.strip()
            return {
                "ok": True,
                "version": version,
                "path": gs_path,
                "message": f"Ghostscript v{version} ready at {gs_path}",
            }
        except Exception as e:
            return {
                "ok": False,
                "version": None,
                "path": gs_path,
                "message": f"Error running gs: {e}",
            }

    @staticmethod
    def check_docker() -> Dict[str, Any]:
        """Checks if Docker daemon is running."""
        docker_bin = shutil.which("docker")
        if not docker_bin:
            return {
                "ok": False,
                "message": "Docker CLI not found on PATH. Docker is needed for the Asterisk 8YY container.",
            }
        try:
            res = subprocess.run(
                [docker_bin, "info"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if res.returncode == 0:
                return {
                    "ok": True,
                    "message": "Docker daemon is active and responsive.",
                }
            else:
                return {
                    "ok": False,
                    "message": "Docker CLI found, but Docker daemon is not running.",
                }
        except Exception as e:
            return {
                "ok": False,
                "message": f"Docker check timed out or failed: {e}",
            }

    @staticmethod
    def check_playwright() -> Dict[str, Any]:
        """Checks if Playwright chromium browser is installed."""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser_path = p.chromium.executable_path
                return {
                    "ok": True,
                    "path": browser_path,
                    "message": "Playwright Chromium browser installed.",
                }
        except Exception as e:
            return {
                "ok": False,
                "path": None,
                "message": f"Playwright browser check failed: {e}. Run 'playwright install chromium'.",
            }

    @staticmethod
    def check_egress_ip() -> Dict[str, Any]:
        """
        Queries IP geolocation to verify US VPN / Proxy connectivity.
        Important when sending from outside the US to prevent gateway geoblocks.
        """
        try:
            with httpx.Client(timeout=6.0) as client:
                resp = client.get("https://ipwho.is/")
                if resp.status_code == 200:
                    data = resp.json()
                    ip = data.get("ip", "Unknown")
                    country = data.get("country", "Unknown")
                    country_code = data.get("country_code", "??")
                    city = data.get("city", "")
                    org = data.get("connection", {}).get("org", "")

                    is_us = (country_code == "US")
                    msg = f"Egress IP: {ip} ({city}, {country}) [{org}]"
                    if not is_us:
                        msg += " ⚠️ Warning: Non-US IP detected. Connect to US VPN or EC2 proxy to avoid rate limits."

                    return {
                        "ok": is_us,
                        "ip": ip,
                        "country_code": country_code,
                        "is_us": is_us,
                        "message": msg,
                    }
        except Exception as e:
            return {
                "ok": False,
                "is_us": False,
                "message": f"Could not determine egress IP: {e}",
            }

    @staticmethod
    def check_imap() -> Dict[str, Any]:
        """Verifies Gmail IMAP credentials and SSL connectivity."""
        if not settings.gmail_app_password or "xxxx" in settings.gmail_app_password:
            return {
                "ok": False,
                "message": "GMAIL_APP_PASSWORD is not configured in .env (Required for Route B Auto-Activation).",
            }

        try:
            mail = imaplib.IMAP4_SSL(settings.gmail_imap_server, settings.gmail_imap_port)
            mail.login(settings.gmail_username, settings.gmail_app_password)
            mail.select("INBOX")
            mail.logout()
            return {
                "ok": True,
                "message": f"Successfully authenticated with IMAP ({settings.gmail_username}).",
            }
        except Exception as e:
            return {
                "ok": False,
                "message": f"IMAP authentication failed for {settings.gmail_username}: {e}",
            }

    @classmethod
    def run_doctor(cls) -> bool:
        """Runs all checks and displays a structured status report."""
        table = Table(title="🏥 Virtual Fax Gateway - System Doctor", border_style="cyan")
        table.add_column("Component", style="bold white")
        table.add_column("Status", justify="center")
        table.add_column("Details", style="dim white")

        # 1. Ghostscript
        gs = cls.check_ghostscript()
        table.add_row(
            "Ghostscript (PDF->TIFF)",
            "[bold green]OK[/bold green]" if gs["ok"] else "[bold red]MISSING[/bold red]",
            gs["message"],
        )

        # 2. Docker
        docker = cls.check_docker()
        table.add_row(
            "Docker Daemon (Asterisk 8YY)",
            "[bold green]OK[/bold green]" if docker["ok"] else "[bold yellow]INACTIVE[/bold yellow]",
            docker["message"],
        )

        # 3. Playwright
        pw = cls.check_playwright()
        table.add_row(
            "Playwright (Web Gateway)",
            "[bold green]OK[/bold green]" if pw["ok"] else "[bold red]MISSING[/bold red]",
            pw["message"],
        )

        # 4. Egress IP / VPN
        ip_info = cls.check_egress_ip()
        table.add_row(
            "US Egress IP / VPN",
            "[bold green]US REGION[/bold green]" if ip_info.get("is_us") else "[bold yellow]NON-US / WARN[/bold yellow]",
            ip_info["message"],
        )

        # 5. Gmail IMAP
        imap = cls.check_imap()
        table.add_row(
            "Gmail IMAP Auto-Activation",
            "[bold green]CONFIGURED[/bold green]" if imap["ok"] else "[bold yellow]UNCONFIGURED[/bold yellow]",
            imap["message"],
        )

        console.print(table)
        return all([gs["ok"], pw["ok"]])
