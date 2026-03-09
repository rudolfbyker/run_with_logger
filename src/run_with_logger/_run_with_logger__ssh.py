from contextlib import contextmanager, nullcontext, AbstractContextManager
from io import BytesIO
from logging import Logger, DEBUG
from subprocess import CompletedProcess, CalledProcessError
from typing import Optional, TYPE_CHECKING, Generator

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
) -> Generator[RunningSshChannelInfo, None, None]:
    """
    Like `run_with_logger`, but via SSH.

    This is a context manager that lets the process run in the background while the context is active.
    When the context is exited, the process will be waited for.

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
    )

    # Write to `stdin`.
    if stdin_data is not None:
        stdin_stream.write(stdin_data)
        stdin_stream.close()

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

    with stdout_cm, stderr_cm:
        try:
            yield info

        finally:
            # Wait for command completion
            code = channel.recv_exit_status()

    if check and code:
        raise CalledProcessError(
            returncode=code,
            cmd=command,
            output=stdout_buffer.getvalue() if stdout_buffer else None,
            stderr=stderr_buffer.getvalue() if stderr_buffer else None,
        )

    info["completed"] = CompletedProcess(
        args=command,
        returncode=channel.recv_exit_status(),
        stdout=stdout_buffer.getvalue() if stdout_buffer else None,
        stderr=stderr_buffer.getvalue() if stderr_buffer else None,
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
    ) as info:
        pass

    completed = info["completed"]
    assert completed is not None
    return completed
