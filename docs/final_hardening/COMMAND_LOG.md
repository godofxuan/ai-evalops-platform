# Command Log

Commands are recorded with observed results, not intended results. Repeated formatting commands are grouped when their
inputs and outcome were identical.

| Command | Result summary |
| --- | --- |
| `git status --short` | Empty at start; exact required baseline was clean. |
| `git branch --show-current` | `main`. |
| `git rev-parse HEAD` | `8fb89bd383433d9e1b00b0b84df4522639e208c9`. |
| `git log -5 --oneline` | Head `8fb89bd`; previous Agent vNext commits present. |
| `git switch -c codex/final-evidence-hardening-v1` | First elevated run failed Git dubious-ownership check. |
| `git -c safe.directory=D:/文档/ai-evalops-platform switch -c ...` | Branch created; no global trust change. |
| `pytest tests/unit/agent_eval/test_failure_and_regression.py -q` | Global Python failed before collection: unknown `asyncio_mode`. |
| `.venv\Scripts\python.exe -m pytest ...test_failure_and_regression.py -q` | RED: common success returned 0.5/0.5; after fix, focused tests passed. |
| focused Ruff/format/mypy commands | Passed after import/line/type corrections; no suppressions retained. |
| `.venv\Scripts\python.exe -m pytest tests/unit/agent_eval tests/api/test_agent_artifacts.py tests/api/test_agent_regression.py -q` | `38 passed`. |
| `.venv\Scripts\python.exe -m pytest -m "not integration" -q` (first hardening run) | `816 passed, 10 failed, 37 deselected` in 294.68s. |
| affected migration/ORM/review subset after repair | `38 passed`. |
| `docker version` | Failed: Docker executable not installed in the desktop environment. |
| `docker compose -f deploy/compose.yaml config --quiet` | Not executed because Docker executable was unavailable. |
| new PostgreSQL/MinIO/MCP integration files run without integration env | Explicitly skipped by their declared environment guards. |
| `git diff --check` | Passed at the pre-documentation checkpoint. |

Pending commands and their actual results are appended after final local validation, commit/push and remote CI.

## Final local qualification

| Command | Result summary |
| --- | --- |
| `.venv\Scripts\ruff.exe format --check .` | `487 files already formatted`. |
| `.venv\Scripts\ruff.exe check .` | `All checks passed`. |
| `.venv\Scripts\mypy.exe app scripts tests/integration tests/concurrency` | `Success: no issues found in 165 source files`. |
| second `.venv\Scripts\python.exe -m pytest -m "not integration" -q` | `826 passed, 37 deselected in 292.04s`. |
| `.venv\Scripts\python.exe -m pytest tests/unit/agent_eval -q` | `31 passed in 2.02s`. |
| artifact API / regression API focused commands | `6 passed in 1.80s`; `1 passed in 1.59s`. |
| Agent workflow / Human Review integration commands | Each explicitly skipped because `EVALOPS_RUN_INTEGRATION` was not set. |
| new HTTP-MinIO / MCP-stdio / reconciliation command | `3 skipped in 8.01s`; required services unavailable. |
| `.venv\Scripts\python.exe -m pytest tests/concurrency -q` | `18 skipped`; PostgreSQL integration flag unavailable. |
| `.venv\Scripts\python.exe -m pytest -q` | `826 passed, 37 skipped in 290.73s`. |
| `.venv\Scripts\python.exe --version` | `Python 3.12.13`. |
| SHA-256 of `uv.lock` | `8ed48f1d7a65f08df458a1752bceb9c9a61fcd95ea571db877cd01ed8c7c72c5`. |
| `.venv\Scripts\alembic.exe heads` | `20260820_0025 (head)`. |
| implementation commit | `d9dd809b57879eddd2a2e8f89a8c9b7164cadfdc`. |
