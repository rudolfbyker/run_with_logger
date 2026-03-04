import json
from contextlib import contextmanager
from io import BytesIO
from logging import Logger, DEBUG
from os import PathLike, environ
from subprocess import Popen, DEVNULL, PIPE, CalledProcessError, CompletedProcess
from time import sleep
from typing import Optional, Union, Generator

from ._pipe_capture import pipe_capture__thread
from ._pipe_to_logger import pipe_to_logger__thread
from ._types import PopenArgsT, PopenCwdT, StreamActionT, RunningProcessInfo


@contextmanager
def run_with_logger__cm(
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
    stdin_io: Union[None, int, BytesIO] = None,
    extra_env: Optional[dict[str, str]] = None,
) -> Generator[RunningProcessInfo, None, None]:
    """
    Like `subprocess.run`, but with the ability to pipe `stdout` and/or `stderr` to a `Logger` or capture each stream
    independently while the process is running.

    This is a context manager that lets the process run in the background while the context is active.
    When the context is exited, the process will be waited for.

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
        extra_env:
            Extra environment variables to set for the process.
            These will be added to the current environment.
    """
    stdout_buffer: Optional[BytesIO] = None
    stderr_buffer: Optional[BytesIO] = None

    if stdin_io is not None and stdin_data is not None:
        raise ValueError("Only one of `stdin_io` or `stdin_data` may be specified.")

    if isinstance(args, (str, bytes, PathLike)):
        args_str = str(args)
    else:
        args_str = json.dumps([str(a) for a in args])
    logger.debug(f"Starting process: {args_str}")

    with Popen(
        cwd=cwd,
        args=args,
        shell=shell,
        stdout=DEVNULL if stdout_action == "discard" else PIPE,
        stderr=DEVNULL if stderr_action == "discard" else PIPE,
        stdin=PIPE if stdin_data is not None else stdin_io,
        env=None if extra_env is None else {**environ, **extra_env},
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

        info = RunningProcessInfo(
            process=process,
            stdout_buffer=stdout_buffer,
            stderr_buffer=stderr_buffer,
            completed=None,  # assigned later
        )

        with stdout_cm, stderr_cm:
            try:
                yield info

            finally:
                # According to https://docs.python.org/3/library/subprocess.html#subprocess.Popen.wait ,
                # `process.wait` can cause a deadlock when using `stdout=PIPE` or `stderr=PIPE`.
                # So we simply poll the process until it is done, and sleep so that the threads can do their work.
                while process.poll() is None:
                    sleep(0.1)

    if check and process.returncode:
        raise CalledProcessError(
            returncode=process.returncode,
            cmd=process.args,
            output=stdout_buffer.getvalue() if stdout_buffer else None,
            stderr=stderr_buffer.getvalue() if stderr_buffer else None,
        )

    info["completed"] = CompletedProcess(
        args=process.args,
        returncode=process.returncode,
        stdout=stdout_buffer.getvalue() if stdout_buffer else None,
        stderr=stderr_buffer.getvalue() if stderr_buffer else None,
    )


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
    stdin_io: Union[None, int, BytesIO] = None,
    extra_env: Optional[dict[str, str]] = None,
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
        extra_env:
            Extra environment variables to set for the process.
            These will be added to the current environment.
    """
    with run_with_logger__cm(
        args=args,
        logger=logger,
        cwd=cwd,
        shell=shell,
        level=level,
        encoding=encoding,
        check=check,
        stdout_action=stdout_action,
        stderr_action=stderr_action,
        stdin_data=stdin_data,
        stdin_io=stdin_io,
        extra_env=extra_env,
    ) as info:
        pass

    completed = info["completed"]
    assert completed is not None
    return completed
