import socket
import sys
import unittest
from contextlib import contextmanager, closing
from logging import getLogger, INFO
from subprocess import CalledProcessError, run
from time import sleep, monotonic
from typing import ClassVar, ContextManager, Generator
from uuid import uuid4

from fabric import Connection
from paramiko import SSHClient, AutoAddPolicy

from run_with_logger import run_with_logger__ssh, run_with_logger__ssh__cm


class TestRunWithLoggerSsh(unittest.TestCase):
    ssh_host: ClassVar[str] = "localhost"
    ssh_port: ClassVar[int] = 54321
    ssh_username: ClassVar[str] = "user"
    ssh_password: ClassVar[str] = "password"
    ssh_server: ClassVar[ContextManager[None] | None] = None

    @classmethod
    def ensure_ssh_server(cls) -> None:
        if cls.ssh_server is not None:
            return

        ssh_server_cm = ssh_server(
            port=cls.ssh_port,
            username=cls.ssh_username,
            password=cls.ssh_password,
        )
        ssh_server_cm.__enter__()
        cls.ssh_server = ssh_server_cm
        cls.addClassCleanup(cls.stop_ssh_server)

    @classmethod
    def stop_ssh_server(cls) -> None:
        ssh_server_cm = cls.ssh_server
        cls.ssh_server = None
        if ssh_server_cm is not None:
            ssh_server_cm.__exit__(None, None, None)

    @contextmanager
    def paramiko_client(self) -> Generator[SSHClient, None, None]:
        self.ensure_ssh_server()
        with closing(SSHClient()) as ssh_client:
            ssh_client.set_missing_host_key_policy(policy=AutoAddPolicy())
            ssh_client.connect(
                hostname=self.ssh_host,
                port=self.ssh_port,
                username=self.ssh_username,
                password=self.ssh_password,
            )
            yield ssh_client

    @contextmanager
    def fabric_connection(self) -> Generator[Connection, None, None]:
        self.ensure_ssh_server()
        with Connection(
            host=self.ssh_host,
            port=self.ssh_port,
            user=self.ssh_username,
            connect_kwargs={
                "password": self.ssh_password,
            },
        ) as conn:
            yield conn

    def test_invalid_client_type__raises_value_error(self) -> None:
        """
        The `client` argument must be `paramiko.SSHClient` or `fabric.Connection`.
        """
        logger = getLogger(__name__)

        with self.assertRaisesRegex(
            ValueError,
            "`client` must be either a `paramiko.SSHClient` or a `fabric.Connection`.",
        ):
            with run_with_logger__ssh__cm(
                logger=logger,
                client=object(),
                command="whoami",
            ):
                pass

    def test_disconnected_paramiko_client__raises_value_error(self) -> None:
        """
        The `paramiko.SSHClient` must be connected.
        """
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
        """
        Pass bytes to `stdin` while capturing `stdout` and `stderr`.
        """
        logger = getLogger(__name__)

        with self.paramiko_client() as ssh_client:
            completed = run_with_logger__ssh(
                logger=logger,
                client=ssh_client,
                command='cat; echo "ERR" >&2',
                stdin_data=b"IN\n",
                stdout_action="capture",
                stderr_action="capture",
            )

            self.assertEqual(0, completed.returncode)
            self.assertEqual(["IN"], completed.stdout.decode().splitlines())
            self.assertEqual(["ERR"], completed.stderr.decode().splitlines())

    def test_paramiko__nonzero_exit_raises_called_process_error_with_captured_streams(
        self,
    ) -> None:
        """
        Using `check=True` while capturing streams should still raise `CalledProcessError` for non-zero exit codes.
        """
        logger = getLogger(__name__)

        with self.paramiko_client() as ssh_client:
            command = '/bin/sh -c \'echo "OUT"; echo "ERR" >&2; exit 5\''
            with self.assertRaises(CalledProcessError) as cm:
                run_with_logger__ssh(
                    logger=logger,
                    client=ssh_client,
                    command=command,
                    stdout_action="capture",
                    stderr_action="capture",
                )

        e = cm.exception
        self.assertEqual(5, e.returncode)
        self.assertEqual(command, e.cmd)
        self.assertEqual(b"OUT\n", e.output)
        self.assertEqual(b"ERR\n", e.stderr)

    def test_paramiko__capture_stdout(self) -> None:
        """
        Capture `stdout` from a successful command with a `paramiko.SSHClient`.
        """
        logger = getLogger(__name__)

        with self.paramiko_client() as ssh_client:
            completed = run_with_logger__ssh(
                logger=logger,
                client=ssh_client,
                command="whoami",
                stdout_action="capture",
                stderr_action="capture",
            )

            self.assertEqual(0, completed.returncode)
            self.assertEqual(self.ssh_username, completed.stdout.decode().strip())
            self.assertEqual("", completed.stderr.decode().strip())

    def test_paramiko__capture_stderr(self) -> None:
        """
        Capture `stderr` from a successful command with a `paramiko.SSHClient`.
        """
        logger = getLogger(__name__)

        with self.paramiko_client() as ssh_client:
            completed = run_with_logger__ssh(
                logger=logger,
                client=ssh_client,
                command="whoami >&2",
                stdout_action="capture",
                stderr_action="capture",
            )

            self.assertEqual(0, completed.returncode)
            self.assertEqual("", completed.stdout.decode().strip())
            self.assertEqual(self.ssh_username, completed.stderr.decode().strip())

    def test_fabric__capture_stdout(self) -> None:
        """
        Capture `stdout` from a successful command with a `fabric.Connection`.
        """
        logger = getLogger(__name__)

        with self.fabric_connection() as conn:
            completed = run_with_logger__ssh(
                logger=logger,
                client=conn,
                command="whoami",
                stdout_action="capture",
                stderr_action="capture",
            )

            self.assertEqual(0, completed.returncode)
            self.assertEqual(self.ssh_username, completed.stdout.decode().strip())
            self.assertEqual("", completed.stderr.decode().strip())

    def test_fabric__capture_stderr(self) -> None:
        """
        Capture `stderr` from a successful command with a `fabric.Connection`.
        """
        logger = getLogger(__name__)

        with self.fabric_connection() as conn:
            completed = run_with_logger__ssh(
                logger=logger,
                client=conn,
                command="whoami >&2",
                stdout_action="capture",
                stderr_action="capture",
            )

            self.assertEqual(0, completed.returncode)
            self.assertEqual("", completed.stdout.decode().strip())
            self.assertEqual(self.ssh_username, completed.stderr.decode().strip())

    def test_paramiko__log_stdout(self) -> None:
        """
        Test logging `stdout` while discarding `stderr` with a `paramiko.SSHClient`.
        """
        logger = getLogger(__name__)

        with self.paramiko_client() as ssh_client:
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

    def test_paramiko__log_stderr(self) -> None:
        """
        Test logging `stderr` while discarding `stdout` with a `paramiko.SSHClient`.
        """
        logger = getLogger(__name__)

        with self.paramiko_client() as ssh_client:
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

    def test_fabric__log_stdout(self) -> None:
        """
        Test logging `stdout` while discarding `stderr` with a `fabric.Connection`.
        """
        logger = getLogger(__name__)

        with self.fabric_connection() as conn:
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
        """
        Test logging `stderr` while discarding `stdout` with a `fabric.Connection`.
        """
        logger = getLogger(__name__)

        with self.fabric_connection() as conn:
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
    if sys.platform == "win32":
        raise unittest.SkipTest("SSH integration tests require Linux containers.")

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
