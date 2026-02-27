import socket
import unittest
from contextlib import contextmanager
from logging import getLogger
from subprocess import run
from time import sleep, monotonic
from typing import Generator
from uuid import uuid4

from paramiko import SSHClient, AutoAddPolicy

from run_with_logger import run_with_logger__ssh


class TestRunWithLoggerSsh(unittest.TestCase):
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

        logger.error(f"Failed to remove container `{name}`:\n{completed.stderr}")
