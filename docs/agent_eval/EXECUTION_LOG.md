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

## Stage B — Trajectory ingestion persistence

### RED

The first API test could not import `AgentArtifactUpload`, so no ingestion endpoint or externally visible request
contract existed. A second migration test initially failed because PostgreSQL rejected an overlong foreign-key name;
this caught a real portability issue before a database upgrade.

### GREEN

- added `POST /api/v1/runs/{run_id}/agent-artifacts` using the same server-derived Principal boundary as existing APIs;
- added `agent_execution_artifacts` metadata with Run/Job composite ownership foreign keys and a content identity unique
  constraint;
- widened the existing artifact-type check to include `agent_execution` rather than creating a parallel store;
- stored canonical JSON through the existing content-addressed backend, while PostgreSQL stores only queryable metadata;
- corrected migration constraint identifiers to stay within PostgreSQL's 63-character limit.

### Semantics

The service checks that the authenticated tenant owns the Run and matching case Job before writing to object storage.
Repeated identical content reuses the content-addressed object and returns the existing metadata row. A different
trajectory is a separate immutable artifact; v1 intentionally does not overwrite prior execution evidence. As with
the existing artifact contract, a database failure after object publication can leave an unreferenced object for the
existing orphan-cleanup flow; it does not create an unauthorized database reference.

### Validation

- API contract, schema contract, ORM metadata and offline migration tests: passed;
- Ruff, format and strict mypy checks: passed.
