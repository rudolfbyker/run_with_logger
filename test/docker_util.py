from contextlib import contextmanager
from logging import getLogger
from subprocess import run, CalledProcessError
from typing import Generator

logger = getLogger(__name__)


class DockerPauseController:
    """
    Pause and unpause a Docker container.
    """

    def __init__(self, *, container_name: str) -> None:
        self.container_name = container_name

    def set_paused(self, value: bool) -> None:
        """
        Pause or unpause the docker container.
        """
        if self.is_paused() == value:
            return

        try:
            run(
                args=[
                    "docker",
                    "container",
                    "pause" if value else "unpause",
                    self.container_name,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except CalledProcessError as e:
            if e.stderr:
                logger.error(e.stderr)
            if e.stdout:
                logger.error(e.stdout)
            raise

    @contextmanager
    def temporarily_paused(self) -> Generator[None, None, None]:
        """
        Temporarily pause the container.
        """
        original = self.is_paused()
        self.set_paused(True)
        try:
            yield
        finally:
            self.set_paused(original)

    def is_paused(self) -> bool:
        """
        Check if the container is currently paused.
        """

        try:
            result = run(
                args=[
                    "docker",
                    "container",
                    "inspect",
                    "-f",
                    "{{.State.Paused}}",
                    self.container_name,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip().lower() == "true"
        except CalledProcessError as e:
            if e.stderr:
                logger.error(e.stderr)
            if e.stdout:
                logger.error(e.stdout)
            raise
