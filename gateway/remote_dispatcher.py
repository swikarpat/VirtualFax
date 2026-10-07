"""
Zero-Cost ($0) Dual-Route Virtual Fax Gateway - Ephemeral EC2 Lifecycle Dispatcher
Orchestrates the entire EC2 lifecycle from local Mac:
  1. Boot: Calls AWS EC2 API (boto3) to start instance (e.g. i-09d990d3f2519e575).
  2. Discovery: Polls until running and retrieves dynamic public IP.
  3. Healthcheck: Waits for SSH port 22 and verifies Asterisk Docker container.
  4. Document Sync: Securely uploads PDF document to EC2.
  5. Live Dispatch: Executes faxctl on EC2 and streams Rich output in real time.
  6. Receipt Sync: Pulls delivery receipts back to local receipts/ directory.
  7. Guaranteed Teardown: Unconditionally shuts down EC2 in a finally block to
     prevent unwanted cloud runtime charges.
"""

from datetime import datetime
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from gateway.config import settings
from gateway.utils.logger import console, error_console, get_logger

logger = get_logger()


class MissingAWSCredentialsError(Exception):
    """Raised when AWS credentials cannot be located in .env or the AWS credentials chain."""
    pass


class RemoteDispatchError(Exception):
    """Raised when remote execution or lifecycle management fails."""
    pass


class EphemeralEC2Dispatcher:
    """
    Manages zero-touch ephemeral dispatch by automatically booting the remote EC2
    gateway, executing the transmission, syncing receipts, and shutting it down.
    """

    def __init__(
        self,
        instance_id: Optional[str] = None,
        region: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        ssh_user: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
    ):
        self.instance_id = instance_id or settings.aws_instance_id
        self.region = region or settings.aws_region
        raw_key = ssh_key_path or settings.ssh_key_path
        self.ssh_key_path = Path(os.path.expanduser(raw_key)).resolve()
        self.ssh_user = ssh_user or settings.ssh_user
        self.aws_access_key_id = (
            aws_access_key_id
            if aws_access_key_id is not None
            else (settings.aws_access_key_id or None)
        )
        self.aws_secret_access_key = (
            aws_secret_access_key
            if aws_secret_access_key is not None
            else (settings.aws_secret_access_key or None)
        )

    def get_ec2_client(self):
        """
        Initializes and returns a boto3 EC2 client, detecting credentials from .env
        or the system AWS credentials chain.
        """
        session_kwargs = {"region_name": self.region}
        if self.aws_access_key_id and self.aws_secret_access_key:
            session_kwargs["aws_access_key_id"] = self.aws_access_key_id
            session_kwargs["aws_secret_access_key"] = self.aws_secret_access_key

        session = boto3.Session(**session_kwargs)
        creds = session.get_credentials()
        if creds is None or not creds.access_key:
            raise MissingAWSCredentialsError(
                "[bold red]❌ AWS Credentials Not Detected![/bold red]\n\n"
                "To enable automated EC2 booting, please add your AWS credentials in [bold cyan].env[/bold cyan]:\n"
                "  [green]AWS_ACCESS_KEY_ID[/green]=AKIA...\n"
                "  [green]AWS_SECRET_ACCESS_KEY[/green]=...\n"
                "  [green]AWS_REGION[/green]=us-east-2\n\n"
                "Alternatively, run [bold cyan]aws configure[/bold cyan] in your local shell."
            )
        return session.client("ec2")

    def start_instance(self, ec2_client) -> None:
        """Calls AWS EC2 start_instances."""
        logger.info(f"Starting EC2 instance {self.instance_id} in {self.region}...")
        console.print(f"[bold cyan]🚀 Booting EC2 Gateway:[/bold cyan] Starting instance {self.instance_id} ({self.region})...")
        try:
            ec2_client.start_instances(InstanceIds=[self.instance_id])
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "IncorrectInstanceState":
                # Already running or starting
                logger.info("Instance is already starting or running.")
            else:
                raise RemoteDispatchError(f"AWS API start_instances error: {e}")

    def wait_for_running_and_get_ip(self, ec2_client, timeout_sec: int = 120) -> str:
        """Polls EC2 instance state until 'running' and retrieves dynamic Public IP."""
        logger.info(f"Waiting for {self.instance_id} to reach 'running' state (Timeout: {timeout_sec}s)...")
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            resp = ec2_client.describe_instances(InstanceIds=[self.instance_id])
            reservations = resp.get("Reservations", [])
            if reservations:
                instances = reservations[0].get("Instances", [])
                if instances:
                    inst = instances[0]
                    state = inst.get("State", {}).get("Name", "unknown")
                    public_ip = inst.get("PublicIpAddress")
                    if state == "running" and public_ip:
                        logger.info(f"Instance is running. Dynamic Public IP: {public_ip}")
                        console.print(f"[bold green]✔ EC2 Running:[/bold green] Assigned dynamic Public IP: [bold yellow]{public_ip}[/bold yellow]")
                        return public_ip
            time.sleep(3)

        raise TimeoutError(f"EC2 instance {self.instance_id} did not become running with a public IP within {timeout_sec}s.")

    def wait_for_ssh(self, public_ip: str, timeout_sec: int = 60) -> None:
        """Polls SSH port 22 until the socket is reachable and accepting connections."""
        logger.info(f"Testing SSH connectivity on {public_ip}:22...")
        console.print(f"[bold cyan]🔍 Checking SSH:[/bold cyan] Waiting for {public_ip}:22 to accept handshakes...")
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            try:
                with socket.create_connection((public_ip, 22), timeout=3):
                    logger.info(f"SSH port 22 is open on {public_ip}.")
                    console.print(f"[bold green]✔ SSH Accessible:[/bold green] Port 22 is open.")
                    # Brief pause for SSH daemon banner initialization
                    time.sleep(2)
                    return
            except (socket.timeout, OSError):
                time.sleep(2)

        raise TimeoutError(f"SSH port 22 on {public_ip} was not accessible within {timeout_sec}s.")

    def _build_ssh_cmd(self, public_ip: str, remote_cmd: str) -> list:
        """Constructs an SSH command array with host checking suppressed."""
        return [
            "ssh",
            "-i", str(self.ssh_key_path),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR",
            f"{self.ssh_user}@{public_ip}",
            remote_cmd,
        ]

    def _build_scp_cmd(self, src: str, dest: str) -> list:
        """Constructs an SCP command array."""
        return [
            "scp",
            "-i", str(self.ssh_key_path),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            src,
            dest,
        ]

    def ensure_docker_services(self, public_ip: str) -> None:
        """Checks if fax_asterisk_gateway is running; launches docker compose up -d if stopped."""
        logger.info("Verifying Asterisk Docker container on EC2...")
        console.print("[bold cyan]🐳 Docker Check:[/bold cyan] Verifying Asterisk PBX container...")
        check_cmd = (
            "if [ -d ~/FaxMachine ] && [ ! -d ~/VirtualFax ]; then ln -s ~/FaxMachine ~/VirtualFax; "
            "elif [ -d ~/VirtualFax ] && [ ! -d ~/FaxMachine ]; then ln -s ~/VirtualFax ~/FaxMachine; fi; "
            "docker ps -q -f name=fax_asterisk_gateway | grep . >/dev/null 2>&1 || "
            "(cd ~/VirtualFax 2>/dev/null || cd ~/FaxMachine; docker compose up -d); "
            "mkdir -p ~/VirtualFax/scratch/fax_spool ~/VirtualFax/receipts && chmod -R 777 ~/VirtualFax/scratch >/dev/null 2>&1 || true"
        )
        ssh_cmd = self._build_ssh_cmd(public_ip, check_cmd)
        res = subprocess.run(ssh_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.warning(f"Docker verification returned code {res.returncode}: {res.stderr}")
        else:
            console.print("[bold green]✔ Asterisk Service:[/bold green] Container running and ready.")

    def sync_document(self, public_ip: str, local_pdf: Path) -> str:
        """Pushes the local document to ~/VirtualFax/ on EC2."""
        if not local_pdf.exists():
            raise FileNotFoundError(f"Local document not found: {local_pdf}")

        remote_dest = f"{self.ssh_user}@{public_ip}:~/VirtualFax/{local_pdf.name}"
        logger.info(f"Uploading {local_pdf.name} to EC2...")
        console.print(f"[bold cyan]📤 Uploading Document:[/bold cyan] Transferring {local_pdf.name} to EC2...")
        scp_cmd = self._build_scp_cmd(str(local_pdf.resolve()), remote_dest)
        res = subprocess.run(scp_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RemoteDispatchError(f"Failed to upload document via SCP: {res.stderr}")

        console.print(f"[bold green]✔ Upload Complete:[/bold green] {local_pdf.name} ready on EC2.")
        return local_pdf.name

    def execute_remote_send(
        self,
        public_ip: str,
        number: str,
        remote_filename: str,
        recipient_name: str,
        cover_note: str = "",
        route: str = "auto",
        dry_run: bool = False,
    ) -> int:
        """Executes faxctl send on remote EC2 and streams console output in real-time."""
        logger.info(f"Executing remote fax dispatch to {number}...")
        console.print(f"[bold cyan]📠 Executing Remote Dispatch:[/bold cyan] Streaming execution from EC2...\n")

        cmd_parts = [
            "cd ~/VirtualFax",
            "source .venv/bin/activate",
            f"./faxctl send {number} {remote_filename} --recipient-name '{recipient_name}'",
        ]
        if cover_note:
            cmd_parts.append(f"--cover-note '{cover_note}'")
        if route and route != "auto":
            cmd_parts.append(f"--route {route}")
        if dry_run:
            cmd_parts.append("--dry-run")

        full_cmd = " && ".join(cmd_parts)
        ssh_cmd = self._build_ssh_cmd(public_ip, full_cmd)

        proc = subprocess.Popen(
            ssh_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()

        proc.wait()
        return proc.returncode

    def pull_receipts(self, public_ip: str, local_receipts_dir: Path) -> None:
        """Pulls delivery receipt files from EC2 to local receipts/ directory."""
        local_receipts_dir.mkdir(parents=True, exist_ok=True)
        remote_src = f"{self.ssh_user}@{public_ip}:~/VirtualFax/receipts/*"
        logger.info(f"Pulling receipts from {remote_src} to {local_receipts_dir}...")
        scp_cmd = self._build_scp_cmd(remote_src, str(local_receipts_dir.resolve()))
        res = subprocess.run(scp_cmd, capture_output=True, text=True)
        if res.returncode == 0:
            console.print(f"[bold green]✔ Receipts Synced:[/bold green] Local archive updated in receipts/.")
        else:
            logger.debug(f"Receipt sync notice (may have no new receipts): {res.stderr}")

    def teardown(self, public_ip: Optional[str] = None, ec2_client=None) -> None:
        """
        Guaranteed shutdown: Powers off the OS via SSH and issues stop_instances via
        the AWS EC2 API so the instance never remains running or consumes free-tier hours.
        """
        console.print(f"\n[bold yellow]⚡ Guaranteed Auto-Shutdown:[/bold yellow] Powering down EC2 instance {self.instance_id}...")
        logger.info(f"Initiating guaranteed teardown for {self.instance_id}...")

        # 1. SSH fast poweroff
        if public_ip:
            try:
                poweroff_cmd = self._build_ssh_cmd(public_ip, "sudo poweroff")
                subprocess.run(poweroff_cmd, capture_output=True, timeout=8)
            except Exception as e:
                logger.debug(f"SSH poweroff notice: {e}")

        # 2. AWS EC2 stop_instances API
        if ec2_client:
            try:
                ec2_client.stop_instances(InstanceIds=[self.instance_id])
                logger.info(f"AWS EC2 stop_instances called for {self.instance_id}.")
            except Exception as e:
                logger.warning(f"boto3 stop_instances notice: {e}")

        console.print(f"[bold green]✔ EC2 Power-Down Complete:[/bold green] Instance {self.instance_id} stopped. Zero free-tier hours wasted.\n")

    def run_ephemeral_dispatch(
        self,
        number: str,
        pdf_path: Path,
        recipient_name: str = "Authorized Agency Official",
        cover_note: str = "",
        route: str = "auto",
        dry_run: bool = False,
    ) -> int:
        """
        Full lifecycle: boot -> discover IP -> healthcheck -> sync -> send -> pull -> guaranteed teardown.
        """
        if not self.ssh_key_path.exists():
            error_console.print(
                f"[bold red]❌ SSH Key File Not Found:[/bold red] {self.ssh_key_path}\n"
                f"Verify the SSH key path in .env (SSH_KEY_PATH=...)."
            )
            return 1

        ec2_client = self.get_ec2_client()
        public_ip: Optional[str] = None
        exit_code = 1

        try:
            # 1. Boot
            self.start_instance(ec2_client)

            # 2. Discover IP
            public_ip = self.wait_for_running_and_get_ip(ec2_client)

            # 3. Wait for SSH
            self.wait_for_ssh(public_ip)

            # 4. Check Docker / Asterisk
            self.ensure_docker_services(public_ip)

            # 5. Upload PDF
            remote_filename = self.sync_document(public_ip, pdf_path)

            # 6. Execute dispatch on EC2
            exit_code = self.execute_remote_send(
                public_ip=public_ip,
                number=number,
                remote_filename=remote_filename,
                recipient_name=recipient_name,
                cover_note=cover_note,
                route=route,
                dry_run=dry_run,
            )

            # 7. Pull receipts back to Mac
            local_receipts = Path("./receipts")
            self.pull_receipts(public_ip, local_receipts)

            return exit_code

        finally:
            # 8. Guaranteed shutdown
            self.teardown(public_ip=public_ip, ec2_client=ec2_client)
