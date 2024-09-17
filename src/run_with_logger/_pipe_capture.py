from contextlib import contextmanager
from threading import Thread
from typing import IO, Generator


def pipe_capture(
    *,
    pipe: IO[bytes],
    destination: IO[bytes],
) -> None:
    """
    Capture the STDERR or STDOUT of a Process.

    Run this function in a separate thread.

    Args:
        pipe: The STDERR or STDOUT pipe of a subprocess.
        destination: The destination to which to pipe the output line by line.
    """
    with pipe:
        for line in pipe:
            destination.write(line)


@contextmanager
def pipe_capture__thread(
    *,
    pipe: IO[bytes],
    destination: IO[bytes],
) -> Generator[None, None, None]:
    """
    Context manager that runs a separate thread to capture the STDERR or STDOUT of a Process.

    Args:
        pipe: The STDERR or STDOUT pipe of a subprocess.
        destination: The destination to which to pipe the output line by line.
    """
    thread = Thread(
        target=pipe_capture,
        kwargs=dict(
            pipe=pipe,
            destination=destination,
        ),
    )
    try:
        thread.start()
        yield
    finally:
        thread.join()
