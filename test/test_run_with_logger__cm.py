import sys
import sys
import unittest
from io import BytesIO
from logging import getLogger, INFO
from typing import List

from run_with_logger._run_with_logger import run_with_logger__cm


class TestRunWithLoggerContextManager(unittest.TestCase):
    maxDiff = None

    def test_context_manager_incremental_capture_stdout(self) -> None:
        """
        Test that we can access the captured `stdout` of the process incrementally as it runs.
        """
        logger = getLogger(__name__)

        py_code = """\
from time import sleep

sleep(0.1)
print("A")

sleep(0.1)
print("B")
"""

        with self.assertNoLogs(logger=logger):
            with run_with_logger__cm(
                logger=logger,
                level=INFO,
                args=[sys.executable, "-c", py_code],
                stdout_action="capture",
                stderr_action="capture",
                check=False,
            ) as info:
                stdout_buffer = info["stdout_buffer"]
                assert isinstance(stdout_buffer, BytesIO)

                incremental_capture: List[bytes] = []
                while info["process"].poll() is None:
                    latest_stdout = stdout_buffer.getvalue()
                    if (
                        not len(incremental_capture)
                        or latest_stdout != incremental_capture[-1]
                    ):
                        incremental_capture.append(latest_stdout)

                self.assertEqual(
                    [
                        b"",
                        b"A\r\n",
                        b"A\r\nB\r\n",
                    ],
                    incremental_capture,
                )

    def test_context_manager_incremental_capture_stderr(self) -> None:
        """
        Test that we can access the captured `stderr` of the process incrementally as it runs.
        """
        logger = getLogger(__name__)

        py_code = """\
from time import sleep
from sys import stderr

sleep(0.1)
print("A", file=stderr)

sleep(0.1)
print("B", file=stderr)
"""

        with self.assertNoLogs(logger=logger):
            with run_with_logger__cm(
                logger=logger,
                level=INFO,
                args=[sys.executable, "-c", py_code],
                stdout_action="capture",
                stderr_action="capture",
                check=False,
            ) as info:
                stderr_buffer = info["stderr_buffer"]
                assert isinstance(stderr_buffer, BytesIO)

                incremental_capture: List[bytes] = []
                while info["process"].poll() is None:
                    latest_stderr = stderr_buffer.getvalue()
                    if (
                        not len(incremental_capture)
                        or latest_stderr != incremental_capture[-1]
                    ):
                        incremental_capture.append(latest_stderr)

                self.assertEqual(
                    [
                        b"",
                        b"A\r\n",
                        b"A\r\nB\r\n",
                    ],
                    incremental_capture,
                )
