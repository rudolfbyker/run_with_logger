from io import BytesIO
from os import PathLike
from subprocess import Popen, CompletedProcess
from typing import Literal, Union, Sequence, TypedDict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import paramiko

PopenArgsT = Union[
    str,
    bytes,
    PathLike[str],
    PathLike[bytes],
    Sequence[
        Union[
            str,
            bytes,
            PathLike[str],
            PathLike[bytes],
        ]
    ],
]

PopenCwdT = Union[str, bytes, PathLike[str], PathLike[bytes], None]

StreamActionT = Literal["log", "capture", "discard"]
"""
What to do with a stream:
    - "log": Pipe to the logger.
    - "capture": Capture and return as part of `CompletedProcess`.
    - "discard": Ignore it (like piping it to `/dev/null`).
"""


class RunningProcessInfo(TypedDict):
    """
    Information about a running process.
    """

    process: Popen[bytes]
    """
    The `Popen` object representing the running process.
    """

    stdout_buffer: Optional[BytesIO]
    """
    If `stdout_action` was "capture", this is a `BytesIO` buffer containing the captured stdout of the process.
    """

    stderr_buffer: Optional[BytesIO]
    """
    If `stderr_action` was "capture", this is a `BytesIO` buffer containing the captured stderr of the process.
    """

    completed: Optional[CompletedProcess[bytes]]
    """
    The `CompletedProcess` object representing the completed process.
    This is only assigned after the context manager has been exited (not as soon as the process exits).
    """


class RunningSshChannelInfo(TypedDict):
    """
    Information about a running SSH channel.
    """

    channel: "paramiko.Channel"
    """
    The `Popen` object representing the running process.
    """

    stdout_buffer: Optional[BytesIO]
    """
    If `stdout_action` was "capture", this is a `BytesIO` buffer containing the captured stdout of the process.
    """

    stderr_buffer: Optional[BytesIO]
    """
    If `stderr_action` was "capture", this is a `BytesIO` buffer containing the captured stderr of the process.
    """

    completed: Optional[CompletedProcess[bytes]]
    """
    The `CompletedProcess` object representing the completed process.
    This is only assigned after the context manager has been exited (not as soon as the process exits).
    """
