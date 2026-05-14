import json
import sys
import unittest
from io import BytesIO
from logging import getLogger, DEBUG, INFO
from os import environ
from pathlib import Path
from subprocess import CalledProcessError
from tempfile import TemporaryDirectory
from typing import List

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
        self.assertEqual(b"OUT\n", e.output)
        self.assertEqual(b"ERR\n", e.stderr)

    def test_discard_both_streams_returns_none_streams(self) -> None:
        logger = getLogger(__name__)
        completed = run_with_logger(
            logger=logger,
            args=[sys.executable, "-c", 'print("OUT"); import sys; print("ERR", file=sys.stderr)'],
            stdout_action="discard",
            stderr_action="discard",
            check=False,
        )
        self.assertEqual(0, completed.returncode)
        self.assertIsNone(completed.stdout)
        self.assertIsNone(completed.stderr)
