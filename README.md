# run_with_logger

Like `subprocess.run`, but with the ability to pipe `stdout` and/or `stderr` to a `Logger` or capture each stream
independently while the process is running.

## Examples

### Log `stderr` and capture `stdout`

The main process will wait for the subprocess while:
- forwarding `stderr` line by line to the logger
- capturing `stdout` in a `CompletedProcess` object, which is returned when the process finishes
 
```python
from run_with_logger import run_with_logger
from logging import getLogger

logger = getLogger(__name__)

completed = run_with_logger(
    args=['foo', 'bar'],
    logger=logger,
    stdout_action="capture",
    stderr_action="log",
    check=False,
)

print(completed.stdout)
```

### Log `stdout` and discard `stderr`

The main process will wait for the subprocess while:
- forwarding `stdout` line by line to the logger
- discarding `stderr`
 
```python
from run_with_logger import run_with_logger
from logging import getLogger

logger = getLogger(__name__)

completed = run_with_logger(
    args=['foo', 'bar'],
    logger=logger,
    stdout_action="log",
    stderr_action="discard",
    check=False,
)

print(completed.stdout)
```
