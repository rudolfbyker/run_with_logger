import unittest
from contextlib import contextmanager, closing
from datetime import timedelta
from logging import getLogger, INFO
from subprocess import CalledProcessError, CompletedProcess
from typing import ClassVar, ContextManager, Generator, Tuple

from fabric import Connection
from paramiko import SSHClient, AutoAddPolicy, SSHException

from run_with_logger import run_with_logger__ssh, run_with_logger__ssh__cm
from .ssh_util import ssh_server, SshServerController


class TestRunWithLoggerSsh(unittest.TestCase):
    ssh_host: ClassVar[str] = "localhost"
    ssh_port: ClassVar[int] = 54321
    ssh_username: ClassVar[str] = "user"
    ssh_password: ClassVar[str] = "password"
    ssh_server: ClassVar[
        Tuple[ContextManager[SshServerController], SshServerController] | None
    ] = None

    @classmethod
    def ensure_ssh_server(
        cls,
    ) -> Tuple[ContextManager[SshServerController], SshServerController]:
        if cls.ssh_server is not None:
            return cls.ssh_server

        cm = ssh_server(
            port=cls.ssh_port,
            username=cls.ssh_username,
            password=cls.ssh_password,
        )
        control = cm.__enter__()
        cls.ssh_server = cm, control
        cls.addClassCleanup(cls.stop_ssh_server)
        return cls.ssh_server

    @classmethod
    def stop_ssh_server(cls) -> None:
        if cls.ssh_server is None:
            return
        cm, control = cls.ssh_server
        cm.__exit__(None, None, None)

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

    def test_channel_timeout(self) -> None:
        """
        Test the channel timeout.
        """
        logger = getLogger(__name__)

        _, ssh_server_control = self.ensure_ssh_server()

        for client_cm in [self.paramiko_client, self.fabric_connection]:
            with self.subTest():
                # We are not testing the timeout for the initial connection.
                # That happens before our function is called!
                with client_cm() as ssh_client:

                    def run() -> CompletedProcess:
                        return run_with_logger__ssh(
                            logger=logger,
                            level=INFO,
                            client=ssh_client,
                            command="whoami",
                            stdout_action="log",
                            stderr_action="log",
                            check=False,
                            channel_timeout=timedelta(seconds=0.1),
                        )

                    with self.assertLogs(level=INFO, logger=logger) as logs:

                        # The server is still responsive at this point:
                        first_run = run()
                        self.assertEqual(0, first_run.returncode)

                        # The server goes unresponsive at this point:
                        with ssh_server_control.temporarily_paused():
                            with self.assertRaises(SSHException):
                                run()

                    self.assertEqual(
                        ["user"], [r.message.strip() for r in logs.records]
                    )
