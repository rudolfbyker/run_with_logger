import socket
import unittest
from contextlib import contextmanager
from io import BytesIO
from logging import getLogger, INFO
from subprocess import CalledProcessError, run
from time import sleep, monotonic
from typing import Generator
from unittest.mock import patch
from uuid import uuid4

from paramiko import SSHClient, AutoAddPolicy

from run_with_logger import run_with_logger__ssh, run_with_logger__ssh__cm


class TestRunWithLoggerSsh(unittest.TestCase):
    def test_invalid_client_type_raises_value_error(self) -> None:
        logger = getLogger(__name__)

        with self.assertRaisesRegex(
            ValueError,
            "`client` must be either a `paramiko.SSHClient` or a `fabric.Connection`.",
        ):
            with run_with_logger__ssh__cm(
                logger=logger,
                client=object(),  # type: ignore[arg-type]
                command="whoami",
            ):
                pass

    def test_disconnected_paramiko_client_raises_value_error(self) -> None:
        logger = getLogger(__name__)
        ssh_client = SSHClient()

        with self.assertRaisesRegex(ValueError, "SSH client is not connected."):
            with run_with_logger__ssh__cm(
                logger=logger,
                client=ssh_client,
                command="whoami",
            ):
                pass

    def test_paramiko__stdin_data(self) -> None:
        logger = getLogger(__name__)
        ssh_client = SSHClient()
        channel = FakeChannel(exit_status=0)
        stdin_stream = RecordingBytesIO()
        stdout_stream = FakeChannelBytesIO(b"OUT\n", channel=channel)
        stderr_stream = FakeChannelBytesIO(b"ERR\n", channel=channel)

        with (
            patch.object(ssh_client, "get_transport", return_value=FakeTransport()),
            patch.object(
                ssh_client,
                "exec_command",
                return_value=(stdin_stream, stdout_stream, stderr_stream),
            ) as exec_command,
        ):
            completed = run_with_logger__ssh(
                logger=logger,
                client=ssh_client,
                command="cat",
                stdin_data=b"IN\n",
                stdout_action="capture",
                stderr_action="capture",
            )

        exec_command.assert_called_once_with(command="cat", environment=None)
        self.assertEqual([b"IN\n"], stdin_stream.writes)
        self.assertTrue(stdin_stream.closed_by_run_with_logger)
        self.assertEqual(0, completed.returncode)
        self.assertEqual(b"OUT\n", completed.stdout)
        self.assertEqual(b"ERR\n", completed.stderr)

    def test_paramiko__check_true_raises_called_process_error_with_captured_streams(
        self,
    ) -> None:
        logger = getLogger(__name__)
        ssh_client = SSHClient()
        channel = FakeChannel(exit_status=5)
        stdout_stream = FakeChannelBytesIO(b"OUT\n", channel=channel)
        stderr_stream = FakeChannelBytesIO(b"ERR\n", channel=channel)

        with (
            patch.object(ssh_client, "get_transport", return_value=FakeTransport()),
            patch.object(
                ssh_client,
                "exec_command",
                return_value=(RecordingBytesIO(), stdout_stream, stderr_stream),
            ),
        ):
            with self.assertRaises(CalledProcessError) as cm:
                run_with_logger__ssh(
                    logger=logger,
                    client=ssh_client,
                    command="exit 5",
                    stdout_action="capture",
                    stderr_action="capture",
                )

        e = cm.exception
        self.assertEqual(5, e.returncode)
        self.assertEqual("exit 5", e.cmd)
        self.assertEqual(b"OUT\n", e.output)
        self.assertEqual(b"ERR\n", e.stderr)

    def test_paramiko__capture_stdout(self) -> None:
        logger = getLogger(__name__)

        port = 54321
        username = "user"
        password = "password"

        with ssh_server(
            port=port,
            username=username,
            password=password,
        ):
            ssh_client = SSHClient()
            try:
                ssh_client.set_missing_host_key_policy(policy=AutoAddPolicy)
                ssh_client.connect(
                    hostname="localhost",
                    port=port,
                    username=username,
                    password=password,
                )
                completed = run_with_logger__ssh(
                    logger=logger,
                    client=ssh_client,
                    command="whoami",
                    stdout_action="capture",
                    stderr_action="capture",
                )

                self.assertEqual(0, completed.returncode)
                self.assertEqual(username, completed.stdout.decode().strip())
                self.assertEqual("", completed.stderr.decode().strip())
            finally:
                ssh_client.close()

    def test_paramiko__capture_stderr(self) -> None:
        logger = getLogger(__name__)

        port = 54321
        username = "user"
        password = "password"

        with ssh_server(
            port=port,
            username=username,
            password=password,
        ):
            ssh_client = SSHClient()
            try:
                ssh_client.set_missing_host_key_policy(policy=AutoAddPolicy)
                ssh_client.connect(
                    hostname="localhost",
                    port=port,
                    username=username,
                    password=password,
                )
                completed = run_with_logger__ssh(
                    logger=logger,
                    client=ssh_client,
                    command="whoami >&2",
                    stdout_action="capture",
                    stderr_action="capture",
                )

                self.assertEqual(0, completed.returncode)
                self.assertEqual("", completed.stdout.decode().strip())
                self.assertEqual(username, completed.stderr.decode().strip())
            finally:
                ssh_client.close()

    def test_fabric__capture_stdout(self) -> None:
        from fabric import Connection

        logger = getLogger(__name__)

        port = 54321
        username = "user"
        password = "password"

        with ssh_server(
            port=port,
            username=username,
            password=password,
        ):
            with Connection(
                host="localhost",
                port=port,
                user=username,
                connect_kwargs={
                    "password": password,
                },
            ) as conn:
                completed = run_with_logger__ssh(
                    logger=logger,
                    client=conn,
                    command="whoami",
                    stdout_action="capture",
                    stderr_action="capture",
                )

            self.assertEqual(0, completed.returncode)
            self.assertEqual(username, completed.stdout.decode().strip())
            self.assertEqual("", completed.stderr.decode().strip())

    def test_fabric__capture_stderr(self) -> None:
        from fabric import Connection

        logger = getLogger(__name__)

        port = 54321
        username = "user"
        password = "password"

        with ssh_server(
            port=port,
            username=username,
            password=password,
        ):
            with Connection(
                host="localhost",
                port=port,
                user=username,
                connect_kwargs={
                    "password": password,
                },
            ) as conn:
                completed = run_with_logger__ssh(
                    logger=logger,
                    client=conn,
                    command="whoami >&2",
                    stdout_action="capture",
                    stderr_action="capture",
                )

            self.assertEqual(0, completed.returncode)
            self.assertEqual("", completed.stdout.decode().strip())
            self.assertEqual(username, completed.stderr.decode().strip())

    def test_paramiko__log_stdout(self) -> None:
        logger = getLogger(__name__)

        port = 54321
        username = "user"
        password = "password"

        with ssh_server(
            port=port,
            username=username,
            password=password,
        ):
            ssh_client = SSHClient()
            try:
                ssh_client.set_missing_host_key_policy(policy=AutoAddPolicy)
                ssh_client.connect(
                    hostname="localhost",
                    port=port,
                    username=username,
                    password=password,
                )
                with self.assertLogs(level=INFO) as logs:
                    completed = run_with_logger__ssh(
                        logger=logger,
                        level=INFO,
                        client=ssh_client,
                        command='/bin/sh -c \'echo "One"; echo "Two"; sleep 0.1; echo "Three";\'',
                        stdout_action="log",
                        stderr_action="discard",
                        check=False,
                    )

                self.assertEqual(
                    [
                        (INFO, "One\n"),
                        (INFO, "Two\n"),
                        (INFO, "Three\n"),
                    ],
                    [(r.levelno, r.message) for r in logs.records],
                )

                self.assertEqual(0, completed.returncode)
                self.assertIsNone(completed.stdout)
                self.assertIsNone(completed.stderr)
            finally:
                ssh_client.close()

    def test_paramiko__log_stderr(self) -> None:
        logger = getLogger(__name__)

        port = 54321
        username = "user"
        password = "password"

        with ssh_server(
            port=port,
            username=username,
            password=password,
        ):
            ssh_client = SSHClient()
            try:
                ssh_client.set_missing_host_key_policy(policy=AutoAddPolicy)
                ssh_client.connect(
                    hostname="localhost",
                    port=port,
                    username=username,
                    password=password,
                )
                with self.assertLogs(level=INFO) as logs:
                    completed = run_with_logger__ssh(
                        logger=logger,
                        level=INFO,
                        client=ssh_client,
                        command='/bin/sh -c \'echo "One"; echo "Two"; sleep 0.1; echo "Three";\' >&2',
                        stdout_action="discard",
                        stderr_action="log",
                        check=False,
                    )

                self.assertEqual(
                    [
                        (INFO, "One\n"),
                        (INFO, "Two\n"),
                        (INFO, "Three\n"),
                    ],
                    [(r.levelno, r.message) for r in logs.records],
                )

                self.assertEqual(0, completed.returncode)
                self.assertIsNone(completed.stdout)
                self.assertIsNone(completed.stderr)
            finally:
                ssh_client.close()

    def test_fabric__log_stdout(self) -> None:
        from fabric import Connection

        logger = getLogger(__name__)

        port = 54321
        username = "user"
        password = "password"

        with ssh_server(
            port=port,
            username=username,
            password=password,
        ):
            with Connection(
                host="localhost",
                port=port,
                user=username,
                connect_kwargs={
                    "password": password,
                },
            ) as conn:
                with self.assertLogs(level=INFO, logger=logger) as logs:
                    completed = run_with_logger__ssh(
                        logger=logger,
                        level=INFO,
                        client=conn,
                        command='/bin/sh -c \'echo "One"; echo "Two"; sleep 0.1; echo "Three";\'',
                        stdout_action="log",
                        stderr_action="discard",
                        check=False,
                    )

                self.assertEqual(
                    [
                        (INFO, "One\n"),
                        (INFO, "Two\n"),
                        (INFO, "Three\n"),
                    ],
                    [(r.levelno, r.message) for r in logs.records],
                )

                self.assertEqual(0, completed.returncode)
                self.assertIsNone(completed.stdout)
                self.assertIsNone(completed.stderr)

    def test_fabric__log_stderr(self) -> None:
        from fabric import Connection

        logger = getLogger(__name__)

        port = 54321
        username = "user"
        password = "password"

        with ssh_server(
            port=port,
            username=username,
            password=password,
        ):
            with Connection(
                host="localhost",
                port=port,
                user=username,
                connect_kwargs={
                    "password": password,
                },
            ) as conn:
                with self.assertLogs(level=INFO, logger=logger) as logs:
                    completed = run_with_logger__ssh(
                        logger=logger,
                        level=INFO,
                        client=conn,
                        command='/bin/sh -c \'echo "One"; echo "Two"; sleep 0.1; echo "Three";\' >&2',
                        stdout_action="discard",
                        stderr_action="log",
                        check=False,
                    )

                self.assertEqual(
                    [
                        (INFO, "One\n"),
                        (INFO, "Two\n"),
                        (INFO, "Three\n"),
                    ],
                    [(r.levelno, r.message) for r in logs.records],
                )

                self.assertEqual(0, completed.returncode)
                self.assertIsNone(completed.stdout)
                self.assertIsNone(completed.stderr)


@contextmanager
def ssh_server(
    *,
    port: int,
    username: str,
    password: str,
) -> Generator[None, None, None]:
    """
    Spin up a temporary SSH server for testing.
    """
    container_name = f"ssh-server-{uuid4()}"
    try:
        run(
            args=[
                "docker",
                "container",
                "run",
                "--name",
                container_name,
                "--rm",
                "-d",
                "-p",
                f"{port}:2222",
                "-e",
                f"USER_NAME={username}",
                "-e",
                f"USER_PASSWORD={password}",
                "-e",
                f"PASSWORD_ACCESS=true",
                "linuxserver/openssh-server",
            ],
            check=True,
            capture_output=True,
        )

        # Poll until the port is open.
        wait_for_ssh_server(host="localhost", port=port, timeout=10)

        yield

    finally:
        stop_and_remove_container(name=container_name)


def wait_for_ssh_server(*, host: str, port: int, timeout: float) -> None:
    deadline = monotonic() + timeout
    while True:
        try:
            with socket.create_connection((host, port), timeout=1) as sock:
                # Read the SSH banner to verify the server is ready
                sock.settimeout(1)
                banner = sock.recv(1024).decode("utf-8", errors="ignore").strip()
                if banner.startswith("SSH-"):
                    # Valid SSH banner received
                    break
                else:
                    raise ValueError(f"Invalid SSH banner: {banner}")
        except (OSError, ValueError):
            if monotonic() >= deadline:
                raise RuntimeError(f"Timed out waiting for SSH server on {host}:{port}")
            sleep(0.1)


def stop_and_remove_container(*, name: str) -> None:
    logger = getLogger(__name__)

    completed = run(
        args=[
            "docker",
            "container",
            "stop",
            name,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        if "No such container" in completed.stderr:
            return

        if "is already in progress" in completed.stderr:
            return

        logger.error(f"Failed to stop container `{name}`:\n{completed.stderr}")

    completed = run(
        args=[
            "docker",
            "container",
            "rm",
            name,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        if "No such container" in completed.stderr:
            return

        if "is already in progress" in completed.stderr:
            return

        logger.error(f"Failed to remove container `{name}`:\n{completed.stderr}")


class FakeTransport:
    def is_active(self) -> bool:
        return True


class FakeChannel:
    def __init__(self, *, exit_status: int):
        self.exit_status = exit_status

    def recv_exit_status(self) -> int:
        return self.exit_status


class FakeChannelBytesIO(BytesIO):
    def __init__(self, initial_bytes: bytes, *, channel: FakeChannel):
        super().__init__(initial_bytes)
        self.channel = channel


class RecordingBytesIO(BytesIO):
    def __init__(self) -> None:
        super().__init__()
        self.writes: list[bytes] = []
        self.closed_by_run_with_logger = False

    def write(self, b: bytes) -> int:
        self.writes.append(b)
        return super().write(b)

    def close(self) -> None:
        self.closed_by_run_with_logger = True
        super().close()
