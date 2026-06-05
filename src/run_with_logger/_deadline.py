from datetime import timedelta
from subprocess import Popen, TimeoutExpired
from time import monotonic, sleep
from typing import Callable, TypedDict, Iterable, Tuple


class DeadlineSpec(TypedDict):
    timeout: timedelta
    callback: Callable[[], None]


class DeadlineState(TypedDict):
    spec: DeadlineSpec
    hit: bool


def monitor_deadlines(
    *,
    specs: Iterable[DeadlineSpec],
    poll_interval: float,
    stop: Callable[[], bool],
    t_start: float | None = None,
) -> Tuple[DeadlineState, ...]:
    """
    Call callbacks at the specified deadlines if something is running longer than it should.

    Args:
        poll_interval: How often to check the stop condition, in seconds.
        stop: A callback that should return True when we should stop monitoring.
        t_start:
            The time at which monitoring started.
            Defaults to the current time.
            Use `monotonic()` rather than `time()` for this.
            Useful for monitoring the same thing again after this function returned.
    """
    if poll_interval <= 0:
        raise ValueError("poll_interval must be positive")

    states = tuple(
        DeadlineState(
            spec=spec,
            hit=False,
        )
        for spec in sorted(specs, key=lambda s: s["timeout"])
    )

    if t_start is None:
        t_start = monotonic()

    def t_elapsed() -> float:
        return monotonic() - t_start

    def is_expired(s: DeadlineSpec) -> bool:
        return t_elapsed() >= s["timeout"].total_seconds()

    def next_deadline() -> DeadlineSpec | None:
        return next((s["spec"] for s in states if not s["hit"]), None)

    def t_before_next_deadline() -> float | None:
        n = next_deadline()
        if n is None:
            return None
        return max(n["timeout"].total_seconds() - t_elapsed(), 0)

    while not stop():
        for state in states:
            if state["hit"]:
                continue

            if is_expired(state["spec"]):
                state["hit"] = True
                state["spec"]["callback"]()

        t_next = t_before_next_deadline()
        sleep(poll_interval if t_next is None else min(t_next, poll_interval))

    return states


def monitor_process(
    *,
    poll_interval: float,
    process: Popen[bytes],
    terminate_after: timedelta,
    kill_after: timedelta,
    stop: Callable[[], bool] = lambda: False,
    t_start: float | None = None,
) -> None:
    """
    Monitor the given process.

    Terminate and/or kill it if it runs too long.

    If the process was terminated, `TimeoutExpired` will be raised
    as soon as the process stops or `is_done` returns `True`.

    If the process was killed, `TimeoutExpired` will be raised immediately.

    Args:
        poll_interval: How often to call `is_done`, in seconds.
        process: The process to monitor.
        terminate_after: After this time, terminate the process.
        kill_after: After this time, kill the process. This should be longer than `terminate_after`.
        stop:
            A callback that should return True when we should stop monitoring.
            If the process completes, we will stop anyway, so this is optional.
        t_start:
            The time at which the process started.
            Defaults to the current time.
            Use `monotonic()` rather than `time()` for this.
            Useful for monitoring the same process again after this function returned.
    """
    terminated = False

    def terminate() -> None:
        process.terminate()

        nonlocal terminated
        terminated = True

    def kill() -> None:
        process.kill()
        raise TimeoutExpired(
            cmd=process.args,
            timeout=kill_after.total_seconds(),
        )

    monitor_deadlines(
        t_start=t_start,
        specs=[
            DeadlineSpec(
                timeout=terminate_after,
                callback=terminate,
            ),
            DeadlineSpec(
                timeout=kill_after,
                callback=kill,
            ),
        ],
        poll_interval=poll_interval,
        stop=lambda: process.poll() is not None or stop(),
    )

    if terminated:
        # We reached the `terminate` deadline, but not the `kill` deadline.
        raise TimeoutExpired(
            cmd=process.args,
            timeout=terminate_after.total_seconds(),
        )
