import json
from contextlib import contextmanager, AbstractContextManager, nullcontext
from datetime import timedelta
from io import BytesIO
from logging import Logger, DEBUG
from os import PathLike, environ
from subprocess import (
    Popen,
    DEVNULL,
    PIPE,
    CalledProcessError,
    CompletedProcess,
    TimeoutExpired,
)
from threading import Thread
from time import sleep, monotonic
from typing import Optional, Union, Generator, IO, Tuple

from ._deadline import monitor_process
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
    stdin_io: Union[None, int, BytesIO, IO[bytes]] = None,
    extra_env: Optional[dict[str, str]] = None,
    creationflags: int = 0,
    timeouts: Tuple[timedelta, timedelta] | None = None,
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
        creationflags: See the `subprocess.Popen` documentation for details.
        timeouts:
            A tuple of (terminate_after, kill_after) to use for monitoring the process.
            If the process does not complete in time, `TimeoutExpired` will be raised.
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
        creationflags=creationflags,
    ) as process:
        t_start = monotonic()

        # Set up `stdout` handler.
        stdout_cm: AbstractContextManager[None]
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
            stdout_cm = nullcontext()

        # Set up `stderr` handler.
        stderr_cm: AbstractContextManager[None]
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
            stderr_cm = nullcontext()

        info = RunningProcessInfo(
            process=process,
            stdout_buffer=stdout_buffer,
            stderr_buffer=stderr_buffer,
            completed=None,  # assigned later
        )

        def get_stdout() -> Optional[bytes]:
            return stdout_buffer.getvalue() if stdout_buffer else None

        def get_stderr() -> Optional[bytes]:
            return stderr_buffer.getvalue() if stderr_buffer else None

        with stdout_cm, stderr_cm:
            try:
                _write_stdin_data(
                    process=process,
                    stdin_data=stdin_data,
                    timeouts=timeouts,
                    t_start=t_start,
                )
                try:
                    yield info
                finally:
                    if timeouts:
                        monitor_process(
                            process=process,
                            poll_interval=0.1,
                            terminate_after=timeouts[0],
                            kill_after=timeouts[1],
                            t_start=t_start,
                        )
                    else:
                        # According to https://docs.python.org/3/library/subprocess.html#subprocess.Popen.wait ,
                        # `process.wait` can cause a deadlock when using `stdout=PIPE` or `stderr=PIPE`.
                        # So we simply poll the process until it is done and sleep so that the threads can do their work.
                        while process.poll() is None:
                            sleep(0.1)

            except TimeoutExpired as e:
                # Fill in the streams that we have captured so far.
                if e.output is None:
                    e.output = get_stdout()
                if e.stderr is None:
                    e.stderr = get_stderr()
                raise e

    if check and process.returncode:
        raise CalledProcessError(
            returncode=process.returncode,
            cmd=process.args,
            output=get_stdout(),
            stderr=get_stderr(),
        )

    info["completed"] = CompletedProcess(
        args=process.args,
        returncode=process.returncode,
        stdout=get_stdout(),
        stderr=get_stderr(),
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
    stdin_io: Union[None, int, BytesIO, IO[bytes]] = None,
    extra_env: Optional[dict[str, str]] = None,
    creationflags: int = 0,
    timeouts: Tuple[timedelta, timedelta] | None = None,
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
        creationflags: See the `subprocess.Popen` documentation for details.
        timeouts:
            A tuple of (terminate_after, kill_after) to use for monitoring the process.
            If the process does not complete in time, `TimeoutExpired` will be raised.
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
        creationflags=creationflags,
        timeouts=timeouts,
    ) as info:
        pass

    completed = info["completed"]
    assert completed is not None
    return completed


def _write_stdin_data(
    *,
    process: Popen[bytes],
    stdin_data: Optional[bytes],
    timeouts: Tuple[timedelta, timedelta] | None,
    t_start: float,
) -> None:
    """
    Write stdin data to a process while optionally preventing it from running for too long.

    Args:
        process: Write to the stdin of this process.
        stdin_data: The data to write to the stdin of the process.
        timeouts: A tuple of (terminate_after, kill_after) to use for monitoring the process.
        t_start: The time at which the process started.
    """
    if process.stdin is None or stdin_data is None:
        # Nothing to write.
        return

    def write_stdin() -> None:
        assert process.stdin is not None
        assert stdin_data is not None
        with process.stdin as f:
            f.write(stdin_data)

    if not timeouts:
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
        monitor_process(
            process=process,
            poll_interval=0.1,
            terminate_after=timeouts[0],
            kill_after=timeouts[1],
            # Only wait for the thread to finish, not the process.
            stop=lambda: not thread.is_alive(),
            t_start=t_start,
        )
    finally:
        thread.join(timeout=1)

    if errors:
        raise errors[0]
