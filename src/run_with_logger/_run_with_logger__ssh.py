from contextlib import contextmanager, nullcontext, AbstractContextManager
from datetime import timedelta
from io import BytesIO
from logging import Logger, DEBUG
from subprocess import CompletedProcess, CalledProcessError, TimeoutExpired
from threading import Thread
from time import monotonic
from typing import Optional, TYPE_CHECKING, Generator, Any, Callable

from ._deadline import monitor_deadlines, DeadlineSpec
from ._pipe_capture import pipe_capture__thread
from ._pipe_to_logger import pipe_to_logger__thread
from ._types import StreamActionT, RunningSshChannelInfo

if TYPE_CHECKING:
    from paramiko import SSHClient
    from fabric import Connection


@contextmanager
def run_with_logger__ssh__cm(
    *,
    client: "SSHClient | Connection",
    command: str,
    logger: Logger,
    level: int = DEBUG,
    encoding: Optional[str] = None,
    check: bool = True,
    stdout_action: StreamActionT = "log",
    stderr_action: StreamActionT = "log",
    stdin_data: Optional[bytes] = None,
    extra_env: Optional[dict[str, str]] = None,
    command_timeout: Optional[timedelta] = None,
    channel_timeout: Optional[timedelta] = None,
) -> Generator[RunningSshChannelInfo, None, None]:
    """
    Like `run_with_logger`, but via SSH.

    This is a context manager that lets the process run in the background while the context is active.
    When the context is exited, the process will be waited for.

    This function does not provide a `connection_timeout` argument because you should set it on `client`.

    Args:
        client:
            The `paramiko.SSHClient` or `fabric.Connection` to use for running the command.
            For `paramiko.SSHClient`, the connection must already be open.
            For `fabric.Connection`, the connection will be opened automatically.
        command: The command line program and arguments.
        logger: The logger to which to pipe stdout and/or stderr.
        level: The logging level to use.
        encoding: The encoding to use for stdout and stderr when logging. Defaults to "utf-8".
        check: Whether to raise an exception if the process returns a non-zero exit code.
        stdout_action: What to do with stdout. See `StreamActionT`.
        stderr_action: What to do with stderr. See `StreamActionT`.
        stdin_data: Data to write to the stdin of the process.
        extra_env:
            Extra environment variables to set for the process.
            These will be added to the current environment.
            This only works if the server's `AcceptEnv` setting allows the provided environment variable names.
            Others are silently ignored.
            To work around this, set the environment variables in the command itself, e.g. `VAR=value my_command`.
        command_timeout:
            Maximum time to wait for the remote command to complete.
            If the command does not complete in time, its SSH channel is closed and `TimeoutExpired` is raised.
        channel_timeout:
            Maximum time for blocking read/write operations over the SSH channel.
            This is passed to `SSHClient.exec_command`.
    """
    from paramiko import SSHClient

    if not isinstance(client, SSHClient):
        from fabric import Connection

        if isinstance(client, Connection):
            # Open the connection and get the underlying Paramiko client.
            client.open()
            client = client.client

        else:
            raise ValueError(
                "`client` must be either a `paramiko.SSHClient` or a `fabric.Connection`."
            )

    if client.get_transport() is None or not client.get_transport().is_active():
        raise ValueError("SSH client is not connected.")

    logger.debug(f"Starting remote process: {command}")

    stdin_stream, stdout_stream, stderr_stream = client.exec_command(
        command=command,
        environment=extra_env,
        timeout=channel_timeout.total_seconds() if channel_timeout else None,
    )
    t_start = monotonic()

    # Set up `stdout` handler.
    stdout_buffer: Optional[BytesIO] = None
    stdout_cm: AbstractContextManager[None]
    if stdout_action == "log":
        stdout_cm = pipe_to_logger__thread(
            pipe=stdout_stream,
            logger=logger,
            level=level,
            encoding=encoding,
        )
    elif stdout_action == "capture":
        stdout_buffer = BytesIO()
        stdout_cm = pipe_capture__thread(
            pipe=stdout_stream,
            destination=stdout_buffer,
        )
    else:
        stdout_cm = nullcontext()

    # Set up `stderr` handler.
    stderr_buffer: Optional[BytesIO] = None
    stderr_cm: AbstractContextManager[None]
    if stderr_action == "log":
        stderr_cm = pipe_to_logger__thread(
            pipe=stderr_stream,
            logger=logger,
            level=level,
            encoding=encoding,
        )
    elif stderr_action == "capture":
        stderr_buffer = BytesIO()
        stderr_cm = pipe_capture__thread(
            pipe=stderr_stream,
            destination=stderr_buffer,
        )
    else:
        stderr_cm = nullcontext()

    channel = stdout_stream.channel
    info = RunningSshChannelInfo(
        channel=channel,
        stdout_buffer=stdout_buffer,
        stderr_buffer=stderr_buffer,
        completed=None,  # assigned later
    )

    def get_stdout() -> Optional[bytes]:
        return stdout_buffer.getvalue() if stdout_buffer else None

    def get_stderr() -> Optional[bytes]:
        return stderr_buffer.getvalue() if stderr_buffer else None

    def handle_command_timeout() -> None:
        channel.close()
        assert command_timeout is not None
        raise TimeoutExpired(cmd=command, timeout=command_timeout.total_seconds())

    with stdout_cm, stderr_cm:
        try:
            _write_stdin_data(
                stdin_stream=stdin_stream,
                stdin_data=stdin_data,
                on_timeout=handle_command_timeout,
                timeout=command_timeout,
                t_start=t_start,
            )
            try:
                yield info
            finally:
                if command_timeout:
                    monitor_deadlines(
                        specs=[
                            DeadlineSpec(
                                timeout=command_timeout,
                                callback=handle_command_timeout,
                            )
                        ],
                        poll_interval=0.1,
                        stop=lambda: channel.exit_status_ready(),
                        t_start=t_start,
                    )
                code = channel.recv_exit_status()
        except TimeoutExpired as e:
            # Fill in the streams that we have captured so far.
            if e.output is None:
                e.output = get_stdout()
            if e.stderr is None:
                e.stderr = get_stderr()
            raise e

    if check and code:
        raise CalledProcessError(
            returncode=code,
            cmd=command,
            output=get_stdout(),
            stderr=get_stderr(),
        )

    info["completed"] = CompletedProcess(
        args=command,
        returncode=code,
        stdout=get_stdout(),
        stderr=get_stderr(),
    )


def run_with_logger__ssh(
    *,
    client: "SSHClient | Connection",
    command: str,
    logger: Logger,
    level: int = DEBUG,
    encoding: Optional[str] = None,
    check: bool = True,
    stdout_action: StreamActionT = "log",
    stderr_action: StreamActionT = "log",
    stdin_data: Optional[bytes] = None,
    extra_env: Optional[dict[str, str]] = None,
    command_timeout: Optional[timedelta] = None,
    channel_timeout: Optional[timedelta] = None,
) -> CompletedProcess[bytes]:
    """
    Like `run_with_logger`, but via SSH.

    Args:
        client: The `paramiko` SSH client to use for running the command.
        command: The command line program and arguments.
        logger: The logger to which to pipe stdout and/or stderr.
        level: The logging level to use.
        encoding: The encoding to use for stdout and stderr when logging. Defaults to "utf-8".
        check: Whether to raise an exception if the process returns a non-zero exit code.
        stdout_action: What to do with stdout. See `StreamActionT`.
        stderr_action: What to do with stderr. See `StreamActionT`.
        stdin_data: Data to write to the stdin of the process.
        extra_env:
            Extra environment variables to set for the process.
            These will be added to the current environment.
            This only works if the server's `AcceptEnv` setting allows the provided environment variable names.
            Others are silently ignored.
            To work around this, set the environment variables in the command itself, e.g. `VAR=value my_command`.
        command_timeout:
            Maximum time to wait for the remote command to complete.
            If the command does not complete in time, its SSH channel is closed and `TimeoutExpired` is raised.
        channel_timeout:
            Maximum time for blocking read/write operations over the SSH channel.
            This is passed to `SSHClient.exec_command`.
    """
    with run_with_logger__ssh__cm(
        client=client,
        command=command,
        logger=logger,
        level=level,
        encoding=encoding,
        check=check,
        stdout_action=stdout_action,
        stderr_action=stderr_action,
        stdin_data=stdin_data,
        extra_env=extra_env,
        command_timeout=command_timeout,
        channel_timeout=channel_timeout,
    ) as info:
        pass

    completed = info["completed"]
    assert completed is not None
    return completed


def _write_stdin_data(
    *,
    stdin_stream: Any,
    stdin_data: Optional[bytes],
    on_timeout: Callable[[], None],
    timeout: timedelta | None,
    t_start: float,
) -> None:
    if stdin_data is None:
        # Nothing to write.
        return

    def write_stdin() -> None:
        stdin_stream.write(stdin_data)
        stdin_stream.close()

    if timeout is None:
        # Take as much time as we need.
        write_stdin()
        return

    # (mis)use a list to capture a single value from the thread.
    errors: list[BaseException] = []

    def write_stdin_with_error_capture() -> None:
        try:
            write_stdin()
        except BaseException as e:
            errors.append(e)

    # Do the writing in a separate thread so that we can monitor the deadlines in this thread.
    thread = Thread(target=write_stdin_with_error_capture, daemon=True)
    thread.start()

    try:
        monitor_deadlines(
            specs=[
                DeadlineSpec(
                    timeout=timeout,
                    callback=on_timeout,
                )
            ],
            poll_interval=0.1,
            # Only wait for the thread to finish, not the process.
            stop=lambda: not thread.is_alive(),
            t_start=t_start,
        )
    finally:
        thread.join(timeout=1)

    if errors:
        raise errors[0]
