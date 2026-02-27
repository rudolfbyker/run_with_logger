import json
import sys
import unittest
from logging import getLogger, DEBUG, INFO
from os import environ
from pathlib import Path

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
            completed = run_with_logger(
                logger=logger,
                level=INFO,
                args=[
                    sys.executable,
                    "-c",
                    "import sys; print(sys.argv[1])",
                    Path("/foo/bar"),
                ],
            )

        self.assertEqual(
            [
                (
                    DEBUG,
                    f'Starting process: ["{sys.executable}", "-c", "import sys; print(sys.argv[1])", "/foo/bar"]',
                ),
                (
                    INFO,
                    "/foo/bar",
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
                args=f"{sys.executable} -c 'import sys; print(sys.argv[1])' /foo/bar",
                shell=True,
            )

        self.assertEqual(
            [
                (
                    DEBUG,
                    f"Starting process: {sys.executable} -c 'import sys; print(sys.argv[1])' /foo/bar",
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
