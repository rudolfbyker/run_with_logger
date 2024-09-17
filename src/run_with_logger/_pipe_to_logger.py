from contextlib import contextmanager
from logging import Logger
from threading import Thread
from typing import Union, IO, Optional, Generator


def pipe_to_logger(
    *,
    pipe: Union[IO[bytes], IO[str]],
    logger: Logger,
    level: int,
    encoding: Optional[str] = None,
) -> None:
    """
    Pipe the STDERR or STDOUT of a Process to a logger.

    Run this function in a separate thread.

    See https://stackoverflow.com/questions/35488927/send-subprocess-popen-stdout-stderr-to-logging-module

    Args:
        pipe: The STDERR or STDOUT pipe of a subprocess.
        logger: The logger to which to pipe the output line by line.
        level: The logging level to use.
        encoding:
            An optional encoding to use when decoding bytes to strings. Defaults to UTF-8. Ignored if the pipe is a
            text pipe.
    """
    encoding = encoding or "utf-8"

    with pipe:
        for line in pipe:
            if isinstance(line, bytes):
                line = line.decode(
                    encoding=encoding,
                    errors="replace",
                ).strip()
            logger.log(level=level, msg=line)


@contextmanager
def pipe_to_logger__thread(
    *,
    pipe: Union[IO[bytes], IO[str], None],
    logger: Logger,
    level: int,
    encoding: Optional[str] = None,
) -> Generator[None, None, None]:
    """
    Context manager that runs a separate thread to pipe the STDERR or STDOUT of a Process to a logger.

    See https://stackoverflow.com/questions/35488927/send-subprocess-popen-stdout-stderr-to-logging-module

    Args:
        pipe: The STDERR or STDOUT pipe of a subprocess.
        logger: The logger to which to pipe the output line by line.
        level: The logging level to use.
        encoding:
            An optional encoding to use when decoding bytes to strings. Defaults to UTF-8. Ignored if the pipe is a
            text pipe.
    """
    if not pipe:
        # This context manager becomes a dummy.
        yield
        return

    thread = Thread(
        target=pipe_to_logger,
        kwargs=dict(
            pipe=pipe,
            logger=logger,
            level=level,
            encoding=encoding,
        ),
    )
    try:
        thread.start()
        yield
    finally:
        thread.join()
