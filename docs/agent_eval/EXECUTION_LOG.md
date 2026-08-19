# Agent Eval vNext Execution Log

## Baseline

- Branch: `codex/agent-eval-vnext`
- Baseline SHA: `2f45f4ca0f77a910c67b7930de33acccdd64d099`
- Working tree before work: clean.
- Existing non-integration suite: `783 passed, 33 deselected` on Python 3.12.13 using the repository `.venv`.
- Environment note: global `uv` was unavailable in this PowerShell session. The repository virtual environment already
  contained the locked dependencies, so validation used `.venv\\Scripts\\python.exe`; no system dependency was
  installed or changed.
- Historical scheduler benchmark baseline: v0.1 remains `NOT_READY_TARGETED_NEGATIVE_SCALING`. It is preserved as
  historical scheduler evidence and is not reused as an Agent performance claim.

## Stage A — Agent Run Artifact contract

### RED

`tests/unit/agent_eval/test_artifact_schema.py` initially failed during collection because `app.agent_eval` did not
exist. The test describes one external behavior: a framework-neutral v1 artifact validates semantic tool trajectory
events and has a stable canonical content SHA-256 identity.

### GREEN

Added strict Pydantic v1 contract models and canonical hashing in `app/agent_eval/schema.py`. Unknown fields are
rejected, and the only runtime-specific value is a bounded `framework` label. No scheduler, Worker, Redis or
PostgreSQL behavior changed.

### Validation

- targeted test: passed;
- Ruff check and format check: passed;
- strict mypy: passed.
