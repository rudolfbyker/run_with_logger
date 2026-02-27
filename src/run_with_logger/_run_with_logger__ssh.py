from io import BytesIO
from logging import Logger, DEBUG
from subprocess import CompletedProcess, CalledProcessError
from typing import Optional, TYPE_CHECKING

from ._pipe_capture import pipe_capture__thread
from ._pipe_to_logger import pipe_to_logger__thread
from ._types import StreamActionT

if TYPE_CHECKING:
    from paramiko import SSHClient
    from fabric import Connection


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

    # Handle stdout
    stdout_buffer: Optional[BytesIO] = None
    if stdout_action == "log":
        pipe_to_logger__thread(
            pipe=stdout_stream,
            logger=logger,
            level=level,
            encoding=encoding,
        )
    elif stdout_action == "capture":
        stdout_buffer = BytesIO()
        pipe_capture__thread(
            pipe=stdout_stream,
            destination=stdout_buffer,
        )

    # Handle stderr
    stderr_buffer: Optional[BytesIO] = None
    if stderr_action == "log":
        pipe_to_logger__thread(
            pipe=stderr_stream,
            logger=logger,
            level=level,
            encoding=encoding,
        )
    elif stderr_action == "capture":
        stderr_buffer = BytesIO()
        pipe_capture__thread(
            pipe=stderr_stream,
            destination=stderr_buffer,
        )

    # Write stdin data if provided
    if stdin_data is not None:
        stdin_stream.write(stdin_data)
        stdin_stream.close()

    # Wait for command completion
    code = stdout_stream.channel.recv_exit_status()

    if stdout_buffer:
        # Capture the remaining stdout data after the command has completed
        stdout_buffer.write(stdout_stream.read())
        stdout_result = stdout_buffer.getvalue()
    else:
        stdout_result = None

    if stderr_buffer:
        # Capture the remaining stderr data after the command has completed
        stderr_buffer.write(stderr_stream.read())
        stderr_result = stderr_buffer.getvalue()
    else:
        stderr_result = None

    if check and code:
        raise CalledProcessError(
            returncode=code,
            cmd=command,
            output=stdout_result,
            stderr=stderr_result,
        )

    return CompletedProcess(
        args=command,
        returncode=code,
        stdout=stdout_result,
        stderr=stderr_result,
    )
