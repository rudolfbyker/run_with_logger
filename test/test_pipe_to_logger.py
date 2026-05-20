import unittest
from logging import DEBUG, getLogger

from run_with_logger._pipe_to_logger import pipe_to_logger__thread


class TestPipeToLogger(unittest.TestCase):
    def test_pipe_to_logger_thread__accepts_none_pipe(self) -> None:
        logger = getLogger(__name__)

        with self.assertNoLogs(logger=logger):
            with pipe_to_logger__thread(pipe=None, logger=logger, level=DEBUG):
                pass
