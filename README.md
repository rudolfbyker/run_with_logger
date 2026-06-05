# run_with_logger

Like `subprocess.run`, but with the ability to pipe `stdout` and/or `stderr` to a `Logger` or capture each stream
independently while the process is running.

## What it can do

- Run local commands.
- Run remote commands over SSH.
- For each output stream (`stdout` and `stderr`), choose independently whether to log, capture, or discard it.
- Pipe bytes or files to `stdin`.
- Pass environment variables to the subprocess (even via SSH if the server's `AcceptEnv` setting allows it).
- Enforce configurable timeouts for local subprocesses, remote SSH commands, and SSH network operations.
- Support many of the same arguments as `subprocess.run`.
- Provide access to the running process and incrementally captured output via a context manager.

## Examples

### Log `stderr` and capture `stdout`

The main process will wait for the subprocess while:
- forwarding `stderr` line by line to the logger
- capturing `stdout` in a `CompletedProcess` object, which is returned when the process finishes

```python
from logging import getLogger
from run_with_logger import run_with_logger

logger = getLogger(__name__)

completed = run_with_logger(
    args=["foo", "bar"],
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
from logging import getLogger
from run_with_logger import run_with_logger

logger = getLogger(__name__)

completed = run_with_logger(
    args=["foo", "bar"],
    logger=logger,
    stdout_action="log",
    stderr_action="discard",
    check=False,
)
```

### Capture both streams

Use `"capture"` for both streams when you want the final `CompletedProcess` to contain bytes from `stdout` and `stderr`.

```python
from logging import getLogger
from run_with_logger import run_with_logger

logger = getLogger(__name__)

completed = run_with_logger(
    args=["python", "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
    logger=logger,
    stdout_action="capture",
    stderr_action="capture",
)

print(completed.stdout.decode().strip())  # "out"
print(completed.stderr.decode().strip())  # "err"
```

### Choose the log level and decoding

```python
from logging import INFO, getLogger
from run_with_logger import run_with_logger

logger = getLogger(__name__)

run_with_logger(
    args=["python", "-c", "print('hello')"],
    logger=logger,
    level=INFO,
    encoding="utf-8",
    stdout_action="log",
    stderr_action="discard",
)
```

### Send bytes to `stdin`

```python
from logging import getLogger
from run_with_logger import run_with_logger

logger = getLogger(__name__)

completed = run_with_logger(
    args=["python", "-c", "import sys; print(sys.stdin.read().upper())"],
    logger=logger,
    stdin_data=b"hello",
    stdout_action="capture",
    stderr_action="capture",
)

print(completed.stdout.decode().strip())  # "HELLO"
```

### Pipe a file to `stdin`

```python
from logging import getLogger
from pathlib import Path
from run_with_logger import run_with_logger

logger = getLogger(__name__)
input_path = Path("input.txt")

with input_path.open("rb") as stdin:
    completed = run_with_logger(
        args=["python", "-c", "import sys; print(sys.stdin.read())"],
        logger=logger,
        stdin_io=stdin,
        stdout_action="capture",
        stderr_action="capture",
    )
```

### Add environment variables

`extra_env` is merged with the current environment.

```python
from logging import getLogger
from run_with_logger import run_with_logger

logger = getLogger(__name__)

completed = run_with_logger(
    args=["python", "-c", "import os; print(os.environ['APP_MODE'])"],
    logger=logger,
    extra_env={"APP_MODE": "production"},
    stdout_action="capture",
    stderr_action="capture",
)

print(completed.stdout.decode().strip())  # "production"
```

### Use a shell command

Like `subprocess.Popen`, pass a string and `shell=True` when you intentionally want shell parsing.

```python
from logging import getLogger
from run_with_logger import run_with_logger

logger = getLogger(__name__)

completed = run_with_logger(
    args="printf 'hello from the shell\n'",
    shell=True,
    logger=logger,
    stdout_action="capture",
    stderr_action="capture",
)
```

### Handle non-zero exit codes

With the default `check=True`, non-zero exits raise `CalledProcessError`.
Captured streams are attached to the exception.

```python
from logging import getLogger
from subprocess import CalledProcessError
from run_with_logger import run_with_logger

logger = getLogger(__name__)

try:
    run_with_logger(
        args=["python", "-c", "import sys; print('bad'); sys.exit(2)"],
        logger=logger,
        stdout_action="capture",
        stderr_action="capture",
    )
except CalledProcessError as error:
    print(error.returncode)       # 2
    print(error.output.decode())  # captured stdout
```

Set `check=False` when you want to inspect the return code yourself:

```python
from logging import getLogger
from run_with_logger import run_with_logger

logger = getLogger(__name__)

completed = run_with_logger(
    args=["python", "-c", "import sys; print('bad'); sys.exit(2)"],
    logger=logger,
    stdout_action="capture",
    stderr_action="capture",
    check=False,
)
print(completed.returncode)       # 2
print(completed.stdout.decode())  # captured stdout
```

### Inspect a running process

Use `run_with_logger__cm` if you need access to the `Popen` object while the process is still running.
Captured streams are available as `BytesIO` buffers.

```python
import time
from io import BytesIO
from logging import getLogger
from run_with_logger import run_with_logger__cm

logger = getLogger(__name__)

with run_with_logger__cm(
    args=["python", "-uc", "import time; print('one'); time.sleep(1); print('two')"],
    logger=logger,
    stdout_action="capture",
    stderr_action="capture",
) as info:
    stdout_buffer = info["stdout_buffer"]
    assert isinstance(stdout_buffer, BytesIO)

    while info["process"].poll() is None:
        partial_stdout = stdout_buffer.getvalue()
        # Do something with partial_stdout while the process runs.
        time.sleep(0.1)

completed = info["completed"]
```

### Run a remote command over SSH

Install SSH support first:

```bash
python -m pip install "run_with_logger[ssh]"
```

Then pass either a connected `paramiko.SSHClient` or a `fabric.Connection`.

```python
from contextlib import closing
from logging import getLogger
from paramiko import SSHClient
from run_with_logger import run_with_logger__ssh

logger = getLogger(__name__)
with closing(SSHClient()) as client:
    
    # Configure and connect the client as appropriate for your environment.
    
    completed = run_with_logger__ssh(
        client=client,
        command="whoami",
        logger=logger,
        stdout_action="capture",
        stderr_action="capture",
    )

print(completed.stdout.decode().strip())
```

`run_with_logger__ssh__cm` provides the same context-manager pattern for SSH channels.
