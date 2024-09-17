import json
import sys
import unittest
from logging import getLogger

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
