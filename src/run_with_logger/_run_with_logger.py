import json
from io import BytesIO
from logging import Logger, DEBUG
from subprocess import CompletedProcess, Popen, DEVNULL, PIPE, CalledProcessError
from time import sleep
from typing import Optional, Union, IO

from ._pipe_capture import pipe_capture__thread
from ._pipe_to_logger import pipe_to_logger__thread
from ._types import PopenArgsT, PopenCwdT, StreamActionT


def run_with_logger(
    *,
    args: PopenArgsT,
    logger: Logger,
    cwd: PopenCwdT = None,
    shell: bool = False,
    level: int = DEBUG,
    encoding: Optional[str] = None,
    check: bool = True,
    stdout_action: StreamActionT = "log",
    stderr_action: StreamActionT = "log",
    stdin_data: Optional[bytes] = None,
    stdin_io: Union[None, int, IO[bytes]] = None,
) -> CompletedProcess[bytes]:
    """
    Like `subprocess.run`, but with the ability to pipe `stdout` and/or `stderr` to a `Logger` or capture each stream
    independently while the process is running.

    Args:
        args: The command line program and arguments.
        cwd: The working directory.
        shell: Whether to run the command in a shell.
        logger: The logger to which to pipe stdout and/or stderr.
        level: The logging level to use.
        encoding: The encoding to use for stdout and stderr when logging. Defaults to "utf-8".
        check: Whether to raise an exception if the process returns a non-zero exit code.
        stdout_action: What to do with stdout. See `StreamActionT`.
        stderr_action: What to do with stderr. See `StreamActionT`.
        stdin_data: Data to write to the stdin of the process.
        stdin_io: A file object to pass directly to Popen.
    """
    stdout_buffer: Optional[IO[bytes]] = None
    stderr_buffer: Optional[IO[bytes]] = None

    if stdin_io is not None and stdin_data is not None:
        raise ValueError("Only one of `stdin_io` or `stdin_data` may be specified.")

    logger.debug(f"Starting process: {json.dumps(args)}")
    with Popen(
        cwd=cwd,
        args=args,
        shell=shell,
        stdout=DEVNULL if stdout_action == "discard" else PIPE,
        stderr=DEVNULL if stderr_action == "discard" else PIPE,
        stdin=PIPE if stdin_data is not None else stdin_io,
    ) as process:
        if process.stdin and stdin_data is not None:
            with process.stdin as f:
                f.write(stdin_data)

        if stdout_action == "log" and process.stdout:
            stdout_cm = pipe_to_logger__thread(
                pipe=process.stdout,
                logger=logger,
                level=level,
                encoding=encoding,
            )
        elif stdout_action == "capture" and process.stdout:
            stdout_buffer = BytesIO()
            stdout_cm = pipe_capture__thread(
                pipe=process.stdout,
                destination=stdout_buffer,
            )
        else:
            stdout_cm = nullcontext()  # type: ignore

        if stderr_action == "log" and process.stderr:
            stderr_cm = pipe_to_logger__thread(
                pipe=process.stderr,
                logger=logger,
                level=level,
                encoding=encoding,
            )
        elif stderr_action == "capture" and process.stderr:
            stderr_buffer = BytesIO()
            stderr_cm = pipe_capture__thread(
                pipe=process.stderr,
                destination=stderr_buffer,
            )
        else:
            stderr_cm = nullcontext()  # type: ignore

        with stdout_cm, stderr_cm:
            # According to https://docs.python.org/3/library/subprocess.html#subprocess.Popen.wait , `process.wait` can
            # cause a deadlock. So we simply poll the process until it is done, and sleep so that the threads can do
            # their work.
            while process.poll() is None:
                sleep(0.1)

            code = process.returncode

    stdout_result = stdout_buffer.getvalue() if stdout_buffer else None  # type: ignore
    stderr_result = stderr_buffer.getvalue() if stderr_buffer else None  # type: ignore

    if check and code:
        raise CalledProcessError(
            returncode=code,
            cmd=process.args,
            output=stdout_result,
            stderr=stderr_result,
        )

    return CompletedProcess(
        args=process.args,
        returncode=code,
        stdout=stdout_result,
        stderr=stderr_result,
    )
