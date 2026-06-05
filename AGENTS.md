## Environment

- Always activate the `venv`.
- Always add `src` to `PYTHONPATH`.

## Code formatting

- Use `venv/bin/black`.
- Never run `black` on ignored files.
- Install `black` using `venv/bin/pip install black` if necessary.
- To format the entire repo: `venv/bin/black .`.

## Type checking

- Use `PYTHONPATH=src venv/bin/mypy`.
- Never run `mypy` on ignored files.
- Install requirements using `venv/bin/pip install -r mypy-requirements.txt` if necessary.
- To check the entire repo: `venv/bin/mypy .`.

## Unit testing

- To run all tests: `PYTHONPATH=src venv/bin/python -m unittest`.
- Install requirements using `venv/bin/pip install -r test-requirements.txt` if necessary.

## Ignored files

- Always respect `.gitignore`.
- Never run linters or tests on ignored files or folders.
