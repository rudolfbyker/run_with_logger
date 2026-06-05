import socket
import sys
import unittest
from contextlib import contextmanager
from logging import getLogger
from subprocess import run, CalledProcessError
from time import monotonic, sleep
from typing import Generator

from test.docker_util import DockerPauseController

logger = getLogger(__name__)


class SshServerController(DockerPauseController):
    """
    Control handle for a Dockerized SSH server used by tests.
    """

    def __init__(self, *, container_name: str, host: str, port: int) -> None:
        super().__init__(container_name=container_name)
        self.host = host
        self.port = port

    def set_paused(self, value: bool) -> None:
        super().set_paused(value)
        if not value:
            self.wait_for_banner(timeout=10, poll_period=0.1)

    def wait_for_banner(
        self,
        *,
        timeout: float,
        poll_period: float,
    ) -> None:
        """
        Poll until the SSH server responds with a banner.
        """
        deadline = monotonic() + timeout
        while True:
            try:
                with socket.create_connection(
                    (self.host, self.port), timeout=1
                ) as sock:
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
                    raise RuntimeError(
                        f"Timed out waiting for SSH server on {self.host}:{self.port}"
                    )
                sleep(poll_period)


@contextmanager
def ssh_server(
    *,
    port: int,
    username: str,
    password: str,
) -> Generator[SshServerController, None, None]:
    """
    Spin up a temporary SSH server for testing.
    """
    if sys.platform == "win32":
        raise unittest.SkipTest("SSH integration tests require Linux containers.")

    container_name = f"ssh-server-{port}"
    stop_and_remove_container(name=container_name)
    control = SshServerController(
        container_name=container_name,
        host="localhost",
        port=port,
    )
    try:
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

        except CalledProcessError as e:
            if e.stderr:
                logger.error(e.stderr)
            if e.stdout:
                logger.error(e.stdout)
            raise

        control.wait_for_banner(timeout=10, poll_period=0.1)

        yield control

    finally:
        try:
            control.set_paused(False)
        finally:
            stop_and_remove_container(name=container_name)


def stop_and_remove_container(*, name: str) -> None:
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
