from os import PathLike
from typing import Literal, Union, Sequence

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
