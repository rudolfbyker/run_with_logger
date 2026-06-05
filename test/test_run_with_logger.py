import json
import re
import sys
import unittest
from contextlib import contextmanager
from datetime import timedelta
from io import BytesIO
from logging import getLogger, DEBUG, INFO, WARNING
from os import environ
from pathlib import Path
from subprocess import CalledProcessError, TimeoutExpired
from tempfile import TemporaryDirectory
from typing import List, Generator, IO
from unittest.mock import patch

from comparable_pattern import ComparablePattern

from run_with_logger import run_with_logger


class TestRunWithLogger(unittest.TestCase):
    maxDiff = None

    def test_log_stderr_and_capture_stdout(self) -> None:
        """
        This would cause a deadlock if `run_with_logger` used `process.wait` internally.
        See https://docs.python.org/3/library/subprocess.html#subprocess.Popen.wait
        """
        n = 10000  # The deadlock only happens for large values of `n`.
        logger = getLogger(__name__)
        with self.assertLogs(logger=logger, level="DEBUG") as cm:
            # This needs to be a program that produces a lot of output on both stdout and stderr.
            args = [
                sys.executable,
                "-c",
                f"""\
import sys
for i in range({n}):
    print(f"stdout {{i+1}}")
    print(f"stderr {{i+1}}", file=sys.stderr)
""",
            ]

            completed = run_with_logger(
                args=args,
                logger=logger,
                stdout_action="capture",
                stderr_action="log",
                check=False,
            )

        self.assertEqual(
            [f"Starting process: {json.dumps(args)}"]
            + [f"stderr {i+1}" for i in range(n)],
            [r.getMessage() for r in cm.records],
        )
        self.assertEqual(
            [f"stdout {i+1}" for i in range(n)],
            completed.stdout.decode().splitlines(),
        )
        self.assertEqual(0, completed.returncode)

    def test_log_capture_stderr_and_log_stdout(self) -> None:
        """
        This would cause a deadlock if `run_with_logger` used `process.wait` internally.
        See https://docs.python.org/3/library/subprocess.html#subprocess.Popen.wait
        """
        n = 10000  # The deadlock only happens for large values of `n`.
        logger = getLogger(__name__)
        with self.assertLogs(logger=logger, level="DEBUG") as cm:
            # This needs to be a program that produces a lot of output on both stdout and stderr.
            args = [
                sys.executable,
                "-c",
                f"""\
import sys
for i in range({n}):
    print(f"stdout {{i+1}}")
    print(f"stderr {{i+1}}", file=sys.stderr)
""",
            ]

            completed = run_with_logger(
                args=args,
                logger=logger,
                stdout_action="log",
                stderr_action="capture",
                check=False,
            )

        self.assertEqual(
            [f"Starting process: {json.dumps(args)}"]
            + [f"stdout {i+1}" for i in range(n)],
            [r.getMessage() for r in cm.records],
        )
        self.assertEqual(
            [f"stderr {i+1}" for i in range(n)],
            completed.stderr.decode().splitlines(),
        )
        self.assertEqual(0, completed.returncode)

    def test_path_arguments(self) -> None:
        """
        This tests that `run_with_logger` can handle `Path` objects in the `args` list.
        """

        logger = getLogger(__name__)
        with self.assertLogs(logger=logger, level="DEBUG") as cm:
            args: List[str | Path] = [
                sys.executable,
                "-c",
                "import sys; print(sys.argv[1])",
                Path("/foo/bar"),
            ]
            completed = run_with_logger(
                logger=logger,
                level=INFO,
                args=args,
            )

        self.assertEqual(
            [
                (
                    DEBUG,
                    f"Starting process: {json.dumps([str(a) for a in args])}",
                ),
                (
                    INFO,
                    str(Path("/foo/bar")),
                ),
            ],
            [(r.levelno, r.getMessage()) for r in cm.records],
        )
        self.assertEqual(0, completed.returncode)

    def test_shell_string(self) -> None:
        """
        Test with a string passed to a shell.
        """
        logger = getLogger(__name__)
        with self.assertLogs(logger=logger, level="DEBUG") as cm:
            completed = run_with_logger(
                logger=logger,
                level=INFO,
                args=f'{sys.executable} -c "import sys; print(sys.argv[1])" /foo/bar',
                shell=True,
            )

        self.assertEqual(
            [
                (
                    DEBUG,
                    f'Starting process: {sys.executable} -c "import sys; print(sys.argv[1])" /foo/bar',
                ),
                (
                    INFO,
                    "/foo/bar",
                ),
            ],
            [(r.levelno, r.getMessage()) for r in cm.records],
        )
        self.assertEqual(0, completed.returncode)

    def test_shell_path(self) -> None:
        """
        Test with a Path passed to a shell.
        """
        logger = getLogger(__name__)
        with self.assertLogs(logger=logger, level="DEBUG") as cm:
            with self.assertRaises(TypeError):
                # TypeError: path-like args is not allowed when shell is true
                run_with_logger(
                    logger=logger,
                    level=INFO,
                    args=Path(sys.executable),
                    shell=True,
                )

        self.assertEqual(
            [(DEBUG, f"Starting process: {sys.executable}")],
            [(r.levelno, r.getMessage()) for r in cm.records],
        )

    def test_extra_env(self) -> None:
        """
        Test that `extra_env` is passed correctly.
        """
        logger = getLogger(__name__)

        py_code = "import os; import json; print(json.dumps(dict(os.environ)))"

        with self.assertNoLogs(logger=logger):
            completed = run_with_logger(
                logger=logger,
                level=INFO,
                args=[sys.executable, "-c", py_code],
                extra_env=None,
                stdout_action="capture",
            )
            baseline = json.loads(completed.stdout)

        with self.assertNoLogs(logger=logger):
            completed = run_with_logger(
                logger=logger,
                level=INFO,
                args=[sys.executable, "-c", py_code],
                extra_env={},
                stdout_action="capture",
            )
            empty_extras = json.loads(completed.stdout)

        with self.assertNoLogs(logger=logger):
            completed = run_with_logger(
                logger=logger,
                level=INFO,
                args=[sys.executable, "-c", py_code],
                extra_env={
                    "FOO": "BAR",
                    "BAZ": "QUX",
                },
                stdout_action="capture",
            )
            with_extras = json.loads(completed.stdout)

        self.assertTrue(len(environ) > 0)
        self.assertEqual(baseline.keys(), environ.keys())
        self.assertEqual(empty_extras.keys(), environ.keys())
        self.assertEqual({"BAZ", "FOO"}, with_extras.keys() - environ.keys())

    def test_stdin_data(self) -> None:
        """
        Test passing bytes to stdin.
        """
        logger = getLogger(__name__)
        script = """\
import sys
a,b = sys.stdin.read().split()
print(a, file=sys.stdout)
print(b, file=sys.stderr)
"""
        completed = run_with_logger(
            logger=logger,
            args=[sys.executable, "-c", script],
            stdin_data=b"Hello World",
            stderr_action="capture",
            stdout_action="capture",
        )
        self.assertEqual("Hello", completed.stdout.decode().strip())
        self.assertEqual("World", completed.stderr.decode().strip())

    def test_stdin_io_file(self) -> None:
        """
        Test streaming a file to stdin.
        """
        logger = getLogger(__name__)
        script = """\
import sys
a,b = sys.stdin.read().split()
print(a, file=sys.stdout)
print(b, file=sys.stderr)
"""

        with TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            stdin_file = tmp_dir / "stdin.txt"
            stdin_file.write_text("Hello World")

            with stdin_file.open(mode="rb") as f:
                completed = run_with_logger(
                    logger=logger,
                    args=[sys.executable, "-c", script],
                    stdin_io=f,
                    stderr_action="capture",
                    stdout_action="capture",
                )
                self.assertEqual("Hello", completed.stdout.decode().strip())
                self.assertEqual("World", completed.stderr.decode().strip())

    def test_stdin_data_and_stdin_io_conflict(self) -> None:
        """
        Only one of `stdin_io` or `stdin_data` may be specified.
        """
        logger = getLogger(__name__)
        with self.assertRaisesRegex(
            ValueError,
            r"Only one of `stdin_io` or `stdin_data` may be specified\.",
        ):
            run_with_logger(
                logger=logger,
                args=[sys.executable, "-c", "print('ok')"],
                stdin_data=b"Hello World",
                stdin_io=BytesIO(b"Hello World"),
            )

    def test_check_true_raises_called_process_error_with_captured_streams(self) -> None:
        """
        Using `check=True` while capturing streams should still raise `CalledProcessError` for non-zero exit codes.
        """
        logger = getLogger(__name__)
        script = """\
import sys
print("OUT")
print("ERR", file=sys.stderr)
sys.exit(7)
"""
        with self.assertRaises(CalledProcessError) as cm:
            run_with_logger(
                logger=logger,
                args=[sys.executable, "-c", script],
                check=True,
                stdout_action="capture",
                stderr_action="capture",
            )

        e = cm.exception
        self.assertEqual(7, e.returncode)
        self.assertEqual(["OUT"], e.output.decode().splitlines())
        self.assertEqual(["ERR"], e.stderr.decode().splitlines())

    def test_discard_both_streams_returns_none_streams(self) -> None:
        """
        We can discard both streams, even if they have data.
        """
        logger = getLogger(__name__)
        script = """\
import sys
print("OUT")
print("ERR", file=sys.stderr)
"""
        completed = run_with_logger(
            logger=logger,
            args=[sys.executable, "-c", script],
            stdout_action="discard",
            stderr_action="discard",
            check=False,
        )
        self.assertEqual(0, completed.returncode)
        self.assertIsNone(completed.stdout)
        self.assertIsNone(completed.stderr)

    def test_timeout__command_completes_in_time(self) -> None:
        """
        Test timeout. Command completes in time.
        """
        completed = run_with_logger(
            logger=getLogger(__name__),
            args=[sys.executable, "-c", "from time import sleep; sleep(0.1)"],
            stdout_action="discard",
            stderr_action="discard",
            check=False,
            timeouts=(timedelta(seconds=1), timedelta(seconds=2)),
        )
        self.assertEqual(0, completed.returncode)

    def test_timeout__command_terminated(self) -> None:
        """
        Test timeout. Command is terminated and stops before the kill timeout.
        """
        with self.assertLogs(level=WARNING) as logs:
            with self.assertRaises(TimeoutExpired):
                run_with_logger(
                    logger=getLogger(__name__),
                    args=[sys.executable, "-c", "from time import sleep; sleep(1)"],
                    stdout_action="discard",
                    stderr_action="discard",
                    check=False,
                    timeouts=(timedelta(seconds=0.1), timedelta(seconds=0.2)),
                )
        self.assertEqual(
            [
                "Terminating process "
                + ComparablePattern(re.compile(r"\d+"))
                + " because it took longer than 0:00:00.100000"
            ],
            [r.message for r in logs.records],
        )

    def test_timeout__command_killed(self) -> None:
        """
        Test timeout. Command is killed. The terminate timeout has no effect when it's longer than the kill timeout.
        """
        with self.assertLogs(level=WARNING) as logs:
            with self.assertRaises(TimeoutExpired):
                run_with_logger(
                    logger=getLogger(__name__),
                    args=[sys.executable, "-c", "from time import sleep; sleep(1)"],
                    stdout_action="discard",
                    stderr_action="discard",
                    check=False,
                    timeouts=(timedelta(seconds=0.2), timedelta(seconds=0.1)),
                )
        self.assertEqual(
            [
                "Killing process "
                + ComparablePattern(re.compile(r"\d+"))
                + " because it took longer than 0:00:00.100000"
            ],
            [r.message for r in logs.records],
        )

    def test_timeout__command_terminated_killed__log_streams(self) -> None:
        """
        Test timeout. Command does not respond to being terminated, so it has to be killed. Streams are logged.
        """
        if sys.platform == "win32":
            raise unittest.SkipTest(
                "On Windows, `Popen.terminate()` and `Popen.kill()` are the same thing."
            )

        script = """\
import signal
import time

def print_signal(signum, frame):
    sig = signal.Signals(signum)
    print(f"Received {sig.name}")

for sig in signal.Signals:
    try:
        signal.signal(sig, print_signal)
    except (OSError, RuntimeError, ValueError):
        pass

while True:
    print("Sleeping")
    time.sleep(1)
"""

        with self.assertLogs(level=INFO) as logs:
            with self.assertRaises(TimeoutExpired):
                run_with_logger(
                    logger=getLogger(__name__),
                    level=INFO,
                    args=[sys.executable, "-u", "-c", script],
                    stdout_action="log",
                    stderr_action="log",
                    check=False,
                    timeouts=(timedelta(seconds=0.1), timedelta(seconds=0.2)),
                )
        self.assertEqual(
            [
                "Sleeping",
                "Terminating process "
                + ComparablePattern(re.compile(r"\d+"))
                + " because it took longer than 0:00:00.100000",
                "Received SIGTERM",
                "Killing process "
                + ComparablePattern(re.compile(r"\d+"))
                + " because it took longer than 0:00:00.200000",
            ],
            [r.message for r in logs.records],
        )

    def test_timeout__command_terminated_killed__capture_streams(self) -> None:
        """
        Test timeout. Command does not respond to being terminated, so it has to be killed. Streams are captured.
        """
        if sys.platform == "win32":
            raise unittest.SkipTest(
                "On Windows, `Popen.terminate()` and `Popen.kill()` are the same thing."
            )

        script = """\
import signal
import time

def print_signal(signum, frame):
    sig = signal.Signals(signum)
    print(f"Received {sig.name}")

for sig in signal.Signals:
    try:
        signal.signal(sig, print_signal)
    except (OSError, RuntimeError, ValueError):
        pass

while True:
    print("Sleeping")
    time.sleep(1)
"""

        with self.assertLogs(level=INFO) as logs:
            with self.assertRaises(TimeoutExpired) as e:
                run_with_logger(
                    logger=getLogger(__name__),
                    level=INFO,
                    args=[sys.executable, "-u", "-c", script],
                    stdout_action="capture",
                    stderr_action="capture",
                    check=False,
                    timeouts=(timedelta(seconds=0.1), timedelta(seconds=0.2)),
                )

        self.assertEqual(
            [
                "Terminating process "
                + ComparablePattern(re.compile(r"\d+"))
                + " because it took longer than 0:00:00.100000",
                "Killing process "
                + ComparablePattern(re.compile(r"\d+"))
                + " because it took longer than 0:00:00.200000",
            ],
            [r.message for r in logs.records],
        )

        assert e.exception.stdout is not None
        self.assertEqual(
            ["Sleeping", "Received SIGTERM"], e.exception.stdout.decode().splitlines()
        )
        assert e.exception.stderr is not None
        self.assertEqual([], e.exception.stderr.decode().splitlines())

    def test_timeout__exception_streams_include_reader_cleanup_capture(self) -> None:
        """
        Regression for timeout exceptions snapshotting streams too early.
        `TimeoutExpired` should include bytes captured before the reader context has fully exited.

        In real use, a process can write final stdout/stderr just before timeout termination,
        leaving those bytes in the pipe until the capture thread drains them during context-manager cleanup.
        This test fakes that late drain to make the expected behavior deterministic.
        """
        stdout_tail = b"stdout drained during reader cleanup\n"
        stderr_tail = b"stderr drained during reader cleanup\n"
        cleanup_chunks = [stdout_tail, stderr_tail]
        destinations: List[BytesIO] = []

        @contextmanager
        def delayed_capture_thread(
            *,
            pipe: IO[bytes] | IO[str],
            destination: BytesIO,
        ) -> Generator[None, None, None]:
            del pipe
            chunk_index = len(destinations)
            destinations.append(destination)
            try:
                yield
            finally:
                destination.write(cleanup_chunks[chunk_index])

        with patch(
            "run_with_logger._run_with_logger.pipe_capture__thread",
            delayed_capture_thread,
        ):
            with self.assertLogs(level=WARNING):
                with self.assertRaises(TimeoutExpired) as cm:
                    run_with_logger(
                        logger=getLogger(__name__),
                        args=[
                            sys.executable,
                            "-c",
                            "from time import sleep; sleep(10)",
                        ],
                        stdout_action="capture",
                        stderr_action="capture",
                        check=False,
                        timeouts=(
                            timedelta(seconds=0.01),
                            timedelta(seconds=0.01),
                        ),
                    )

        self.assertEqual(
            [stdout_tail, stderr_tail],
            [destination.getvalue() for destination in destinations],
        )
        self.assertEqual(stdout_tail, cm.exception.output)
        self.assertEqual(stderr_tail, cm.exception.stderr)
