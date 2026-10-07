"""
Unit Tests - Ephemeral EC2 Lifecycle Dispatcher
Verifies:
  - AWS credentials detection
  - EC2 instance booting and dynamic IP discovery
  - SSH socket availability check
  - Docker service verification
  - Document upload and receipt pulling via SCP
  - Remote faxctl command execution streaming
  - Guaranteed auto-shutdown in finally block (on both success and failure)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from click.testing import CliRunner
from pypdf import PdfReader, PdfWriter

from gateway.cli import cli, EXIT_SUCCESS, EXIT_INVALID_INPUT
from gateway.remote_dispatcher import (
    EphemeralEC2Dispatcher,
    MissingAWSCredentialsError,
    RemoteDispatchError,
)


@pytest.fixture
def dummy_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "test_doc.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


@pytest.fixture
def dummy_key(tmp_path: Path) -> Path:
    key_path = tmp_path / "test_key.pem"
    key_path.write_text("dummy private key")
    return key_path


@pytest.fixture
def dispatcher(dummy_key: Path):
    return EphemeralEC2Dispatcher(
        instance_id="i-test1234567890",
        region="us-east-2",
        ssh_key_path=str(dummy_key),
        ssh_user="ec2-user",
        aws_access_key_id="TEST_KEY",
        aws_secret_access_key="TEST_SECRET",
    )


def test_missing_aws_credentials():
    disp = EphemeralEC2Dispatcher(
        aws_access_key_id=None,
        aws_secret_access_key=None,
    )
    with patch("boto3.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.get_credentials.return_value = None
        mock_session_cls.return_value = mock_session

        with pytest.raises(MissingAWSCredentialsError) as exc_info:
            disp.get_ec2_client()
        assert "AWS Credentials Not Detected" in str(exc_info.value)


def test_start_instance(dispatcher):
    mock_client = MagicMock()
    dispatcher.start_instance(mock_client)
    mock_client.start_instances.assert_called_once_with(
        InstanceIds=["i-test1234567890"]
    )


def test_wait_for_running_and_get_ip(dispatcher):
    mock_client = MagicMock()
    mock_client.describe_instances.side_effect = [
        # First call: pending
        {
            "Reservations": [
                {"Instances": [{"State": {"Name": "pending"}, "PublicIpAddress": None}]}
            ]
        },
        # Second call: running with dynamic IP
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "State": {"Name": "running"},
                            "PublicIpAddress": "3.14.15.92",
                        }
                    ]
                }
            ]
        },
    ]

    with patch("time.sleep", return_value=None):
        ip = dispatcher.wait_for_running_and_get_ip(mock_client, timeout_sec=10)
    assert ip == "3.14.15.92"


def test_wait_for_ssh(dispatcher):
    with patch("socket.create_connection") as mock_conn, patch("time.sleep", return_value=None):
        mock_conn.return_value.__enter__.return_value = MagicMock()
        # Should complete without error
        dispatcher.wait_for_ssh("3.14.15.92", timeout_sec=5)
        mock_conn.assert_called_with(("3.14.15.92", 22), timeout=3)


def test_sync_document(dispatcher, dummy_pdf):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        filename = dispatcher.sync_document("3.14.15.92", dummy_pdf)
        assert filename == dummy_pdf.name
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "scp" in cmd
        assert f"ec2-user@3.14.15.92:~/FaxMachine/{dummy_pdf.name}" in cmd


def test_execute_remote_send(dispatcher):
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.stdout = ["Transmitting fax page 1...\n", "Completed!\n"]
        mock_proc.wait.return_value = 0
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        code = dispatcher.execute_remote_send(
            public_ip="3.14.15.92",
            number="510-272-6982",
            remote_filename="test_doc.pdf",
            recipient_name="Test Office",
        )
        assert code == 0
        cmd = mock_popen.call_args[0][0]
        assert "ssh" in cmd
        assert "./faxctl send 510-272-6982 test_doc.pdf" in cmd[-1]


def test_pull_receipts(dispatcher, tmp_path):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        receipts_dir = tmp_path / "receipts"
        dispatcher.pull_receipts("3.14.15.92", receipts_dir)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "scp" in cmd
        assert str(receipts_dir.resolve()) in cmd


def test_teardown_stops_instance(dispatcher):
    mock_client = MagicMock()
    with patch("subprocess.run") as mock_run:
        dispatcher.teardown(public_ip="3.14.15.92", ec2_client=mock_client)
        mock_client.stop_instances.assert_called_once_with(
            InstanceIds=["i-test1234567890"]
        )
        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "sudo poweroff" in cmd[-1]


def test_guaranteed_teardown_on_success(dispatcher, dummy_pdf):
    mock_client = MagicMock()
    with patch.object(dispatcher, "get_ec2_client", return_value=mock_client), \
         patch.object(dispatcher, "start_instance") as mock_start, \
         patch.object(dispatcher, "wait_for_running_and_get_ip", return_value="3.14.15.92"), \
         patch.object(dispatcher, "wait_for_ssh"), \
         patch.object(dispatcher, "ensure_docker_services"), \
         patch.object(dispatcher, "sync_document", return_value="test_doc.pdf"), \
         patch.object(dispatcher, "execute_remote_send", return_value=0), \
         patch.object(dispatcher, "pull_receipts"), \
         patch.object(dispatcher, "teardown") as mock_teardown:

        exit_code = dispatcher.run_ephemeral_dispatch("510-272-6982", dummy_pdf)
        assert exit_code == 0
        mock_start.assert_called_once_with(mock_client)
        # Teardown MUST be called unconditionally
        mock_teardown.assert_called_once_with(public_ip="3.14.15.92", ec2_client=mock_client)


def test_guaranteed_teardown_on_failure(dispatcher, dummy_pdf):
    mock_client = MagicMock()
    with patch.object(dispatcher, "get_ec2_client", return_value=mock_client), \
         patch.object(dispatcher, "start_instance"), \
         patch.object(dispatcher, "wait_for_running_and_get_ip", return_value="3.14.15.92"), \
         patch.object(dispatcher, "wait_for_ssh"), \
         patch.object(dispatcher, "ensure_docker_services"), \
         patch.object(dispatcher, "sync_document", side_effect=RuntimeError("SCP upload error")), \
         patch.object(dispatcher, "teardown") as mock_teardown:

        with pytest.raises(RuntimeError):
            dispatcher.run_ephemeral_dispatch("510-272-6982", dummy_pdf)

        # Teardown MUST still be called even on failure
        mock_teardown.assert_called_once_with(public_ip="3.14.15.92", ec2_client=mock_client)


def test_cli_remote_send_missing_credentials(dummy_pdf, dummy_key):
    runner = CliRunner()
    with patch("gateway.config.settings.ssh_key_path", str(dummy_key)), \
         patch("gateway.remote_dispatcher.EphemeralEC2Dispatcher.get_ec2_client") as mock_get:
        mock_get.side_effect = MissingAWSCredentialsError("Credentials missing")
        result = runner.invoke(cli, ["remote-send", "510-272-6982", str(dummy_pdf)])
        assert result.exit_code == EXIT_INVALID_INPUT
        assert "Credentials missing" in result.output


def test_cli_remote_send_multi_doc(dummy_pdf, tmp_path):
    runner = CliRunner()
    second_pdf = tmp_path / "second.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(second_pdf, "wb") as f:
        writer.write(f)

    with patch("gateway.remote_dispatcher.EphemeralEC2Dispatcher.run_ephemeral_dispatch") as mock_dispatch:
        mock_dispatch.return_value = 0
        result = runner.invoke(cli, ["remote-send", "510-272-6982", str(dummy_pdf), str(second_pdf), "--recipient-name", "County Clerk"])

        assert result.exit_code == EXIT_SUCCESS
        assert "Merging Documents" in result.output
        assert "Consolidating 2 documents" in result.output
        mock_dispatch.assert_called_once()
        passed_pdf = mock_dispatch.call_args.kwargs["pdf_path"]
        assert passed_pdf.exists()
        reader = PdfReader(str(passed_pdf))
        assert len(reader.pages) == 2

