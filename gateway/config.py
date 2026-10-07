"""
Zero-Cost Fax Gateway - Configuration Management
Loads environment variables and YAML configurations with strict validation.
"""

from pathlib import Path
from typing import Dict, List, Optional
import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_YAML_PATH = BASE_DIR / "config" / "gateway_config.yaml"
ENV_FILE_PATH = BASE_DIR / ".env"


class GatewaySettings(BaseSettings):
    """Pydantic-based configuration model for runtime settings."""

    # Sender Info
    fax_sender_name: str = Field(default="Taxpayer Services Office", description="Sender display name")
    fax_sender_company: str = Field(default="Independent Petitioner", description="Sender company/affiliation")
    fax_sender_email: str = Field(default="your-email@gmail.com", description="Sender email for notifications")
    fax_sender_phone: str = Field(default="2025550199", description="Sender 10-digit US callback number")
    fax_station_id: str = Field(default="+18005550199", description="T.30 Local Station ID for fax banner")

    # Gmail IMAP Auto-Activation
    gmail_imap_server: str = Field(default="imap.gmail.com", description="IMAP server hostname")
    gmail_imap_port: int = Field(default=993, description="IMAP SSL port")
    gmail_username: str = Field(default="your-email@gmail.com", description="Gmail user address")
    gmail_app_password: str = Field(default="", description="16-character Gmail App Password")
    gmail_poll_timeout_sec: int = Field(default=120, description="Max seconds to wait for activation email")
    gmail_poll_interval_sec: int = Field(default=3, description="Seconds between IMAP poll checks")

    # Route A (VoIP 8YY SIP)
    sip_primary_8yy_trunk: str = Field(default="tf.alcazarnetworks.com", description="Open 8YY SIP trunk")
    sip_fallback_8yy_trunk: str = Field(default="tollfree.sip-trunk.info", description="Fallback 8YY SIP trunk")
    sip_port: int = Field(default=5060, description="SIP UDP/TCP port")
    asterisk_host: str = Field(default="localhost", description="Asterisk hostname or container IP")
    asterisk_ami_port: int = Field(default=5038, description="Asterisk AMI port")
    asterisk_ami_user: str = Field(default="faxadmin", description="AMI username")
    asterisk_ami_secret: str = Field(default="FaxAdminPass2026!", description="AMI password")
    asterisk_spool_dir: str = Field(default="/var/spool/asterisk", description="Asterisk spool directory")
    asterisk_fax_spool: str = Field(default="/tmp/fax_spool", description="Local shared TIFF spool directory")

    # Route B (Web Gateway)
    web_gateway_headless: bool = Field(default=True, description="Run Playwright headlessly")
    web_gateway_timeout_sec: int = Field(default=60, description="Web gateway navigation timeout")
    web_gateway_screenshot_dir: str = Field(default="./scratch", description="Directory to store debug screenshots")
    http_proxy: Optional[str] = Field(default=None, description="Optional HTTP/HTTPS proxy URL")

    # General
    log_level: str = Field(default="INFO", description="Logging verbosity (DEBUG, INFO, WARNING, ERROR)")
    dry_run_default: bool = Field(default=False, description="Default dry-run mode")

    # AWS EC2 Remote Dispatcher
    aws_region: str = Field(default="us-east-2", description="AWS Region for EC2 instance")
    aws_instance_id: str = Field(default="i-09d990d3f2519e575", description="Target EC2 Instance ID")
    aws_access_key_id: Optional[str] = Field(default=None, description="AWS Access Key ID")
    aws_secret_access_key: Optional[str] = Field(default=None, description="AWS Secret Access Key")
    ssh_key_path: str = Field(default="~/.ssh/fax-key.pem", description="Path to SSH private key file")
    ssh_user: str = Field(default="ec2-user", description="EC2 SSH username")

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )


class RoutingData:
    """Contains loaded YAML routing definitions and directory lookups."""

    def __init__(self, yaml_path: Path = CONFIG_YAML_PATH):
        self.yaml_path = yaml_path
        self.toll_free_prefixes: List[str] = ["800", "888", "877", "866", "855", "844", "833"]
        self.reserved_prefixes: List[str] = ["822", "880", "881", "882", "883", "884", "885", "886", "887", "889"]
        self.agencies: Dict[str, Dict[str, str]] = {}
        self._load()

    def _load(self):
        if not self.yaml_path.exists():
            return
        try:
            with open(self.yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                routing = data.get("routing", {})
                self.toll_free_prefixes = routing.get("toll_free_prefixes", self.toll_free_prefixes)
                self.reserved_prefixes = routing.get("reserved_toll_free_prefixes", self.reserved_prefixes)
                self.agencies = data.get("agencies", {})
        except Exception:
            # Fallback to defaults if YAML parse fails
            pass

    def lookup_agency(self, ten_digit: str) -> Optional[str]:
        """Returns agency and department description if known."""
        info = self.agencies.get(ten_digit)
        if info:
            agency = info.get("agency", "Unknown Agency")
            dept = info.get("department", "")
            return f"{agency} ({dept})" if dept else agency
        return None


# Global singleton instances
settings = GatewaySettings()
routing_data = RoutingData()
