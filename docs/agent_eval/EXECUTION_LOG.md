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

## Stage C/D/E — Trajectory evaluators, attribution and regression decision

### RED

The evaluator test initially failed because `app.agent_eval.evaluators` did not exist. The regression/taxonomy test
then failed because no failure classifier or configured Agent gate existed.

### GREEN

- implemented seven deterministic trajectory metric extractors: task success, tool-call validity, trajectory efficiency,
  grounding/citation, permission boundary, terminal state and cost/latency;
- implemented a small evidence-led failure taxonomy; unsupported metrics do not become invented categories;
- implemented run-to-run intersection/distribution comparison and a configuration-only regression gate for task
  success, permission violations, latency p95 change and tool-error rate.

### Important boundary

The evaluators report counts and explicitly available values. They do not claim that fewer steps are better, infer a
provider cost when none is supplied, or assert a universal release threshold. Gate thresholds are caller configuration
and tests use fixed fixture values only.

### Validation

- trajectory evaluator and failure/regression tests: passed;
- Ruff and strict mypy: passed.

## Stage F/G/I — Control plane, trace correlation and blinded review support

### RED

The MCP control-plane, safe trace-attribute and Agent review-packet tests each failed during import because those
contracts did not exist.

### GREEN

- added a seven-tool MCP dispatcher whose only execution route is an authenticated service-layer adapter;
- added an allow-listed Agent/EvalOps correlation attribute helper;
- added a blinded, limited trajectory review-packet builder that omits framework and session identity.

### Design decision

The local environment has no MCP SDK. Rather than adding an unvalidated dependency or exposing an unauthenticated
listener, the repository now has a transport-independent core with a testable Principal boundary. A future stdio/HTTP
transport adapter must use this core and the existing API/service auth contract.

## Stage H follow-up — ingestion span propagation

### RED

The API trace test initially found no `agent_artifact.ingest` span.

### GREEN

The ingestion route now creates that span through the existing `Telemetry` implementation and records only framework,
session/case/Run identifiers and tenant identity. The regression test asserts that the input message cannot appear in
span attributes.

### Validation

The full non-integration suite passed: `796 passed, 33 deselected`.

## Stage J — Benchmark contract

The benchmark is deliberately a fixed eight-family specification rather than synthetic volume. It covers lookup,
multi-step retrieval, denied access, missing/conflicting evidence, tool failure, budget boundary and adversarial input.
The same artifact contract accepts `custom-controller` and `langgraph-adapter` labels, while comparison requires model,
dataset, tools, retrieval, budget and prompt policy to be frozen first. No benchmark score is claimed until that run is
actually executed and source-bound.

## Stage K — Persisted evaluator evidence and exact reads

### Design judgement

Pure evaluator functions were insufficient for auditability: MCP, human review and regression needed a durable result
identity. The chosen identity is Agent artifact + evaluator kind + server-owned implementation version + canonical
configuration SHA-256. This allows implementation or configuration changes to create new evidence while exact retries
reuse the existing row. A composite foreign key binds result, tenant and Run to the same Agent artifact.

### RED / problems / correction

- the API tracer initially failed because evaluation request/result contracts did not exist;
- the ORM constraint tracer failed because the result model did not exist;
- the first ORM edit accidentally placed the new class between `AgentExecutionArtifact` constraints and fields, so
  SQLAlchemy correctly rejected a foreign key referencing a missing `run_id`; the class boundary was repaired before
  proceeding;
- the regression HTTP model initially used global strict mode and rejected UUID strings, which are the only UUID
  representation JSON can carry; strict mode was removed only at that HTTP boundary while field/range checks remain;
- the denied-access benchmark exposed that a correct `permission_denied` terminal was being counted as a permission
  violation. The gate now counts observed `unauthorized_result_leak_count`; failure attribution remains separate.

### Effect

`20260819_0020` adds immutable result rows, the API can execute/list evaluator evidence and read exact trajectories,
and Agent Run comparison applies caller-configured gates to the newest artifact and newest result per evaluator kind.
An exact case-result endpoint was added so MCP does not scan paginated data.

## Stage L — Official MCP stdio server

### Design judgement

The official MCP Python SDK v2 was selected after checking its current stable documentation. The locked dependency is
`mcp>=2,<3`. The runnable transport is stdio because a local host can launch it without opening a network listener.
Streamable HTTP remains disabled until an OAuth/resource-server deployment boundary is implemented and tested.

### RED / problems / correction

- the SDK protocol test first failed because no server adapter existed;
- `uv` was not globally installed, but the repository’s ignored `.codex-tools` contained uv 0.11.32, so the lock was
  updated without changing system Python;
- the entry point fails before database/service startup when `EVALOPS_MCP_API_KEY` is missing;
- a concrete adapter maps all seven tools to existing typed services and never accepts `tenant_id`.

### Effect

The official in-memory client discovers and calls all tools. At that stage the stdio process authenticated once through
the existing scrypt lookup. The 2026-08-20 hardening section below supersedes that startup-only behavior with per-call
revalidation. Database and telemetry resources are still disposed when the protocol exits.

## Stage M — Agent evidence in the existing human-review state machine

### Design judgement

Creating a second Agent-only review system would duplicate permissions, task locking and adjudication. Instead,
`CreateReviewTasks.source=agent_artifact` selects the latest immutable artifact per case and the latest evidence per
evaluator kind, verifies content identity and writes the existing `HumanReviewTask` shape.

### Effect

Packets expose the question, final answer, citations/sources, terminal state, bounded semantic tool/citation events and
evaluator evidence. They omit tenant, framework, session and raw model-step content. The existing double review,
dispute and third-reviewer adjudication paths remain unchanged.

## Stage N — Executable fixed adapter benchmark

### RED / problems / correction

The benchmark test first failed because only a prose specification existed. After implementation, directly executing
`python scripts/run_agent_adapter_benchmark.py` failed to import the top-level app package; the supported reproducible
entry is `python -m scripts.run_agent_adapter_benchmark`.

### Effect and evidence boundary

The fixed eight-family fixture replays controller-style and LangGraph-style callback mappings into the same artifact
schema. Canonical evidence records the fixture and artifact SHA-256 values, 8/8 case intersection, equal fixture-derived
success `0.875`, equal interpolated p95 about `83 ms`, and zero unauthorized-result leaks. The evidence labels itself
as adapter-contract replay, not live runtime performance.

## Stage O — Local and remote qualification

The local environment still has no Docker executable. The new real PostgreSQL integration test therefore reports an
explicit skip locally; local qualification is `810 passed, 34 deselected`, not a claim that Docker ran locally. Lock
check, repository formatting, Ruff and strict mypy over 161 source files passed.

GitHub Actions run `32261125781` at source `6aef986` completed both jobs successfully. Its dedicated Agent workflow
step covered artifact ingestion, seven persisted evaluators, idempotent replay, cross-tenant hiding, regression gating
and Agent human-review packet creation after applying migrations to real PostgreSQL. The same run passed the existing
concurrency/fairness, RLS, MinIO, Outbox, downgrade/re-upgrade, image build and full Compose smoke contracts. This closes
the remote validation gap for the vNext feature branch; it does not change the historical v0.1 scheduler performance
decision or create a production SLO.

## 2026-08-20 — final evidence hardening

### Baseline and environment

- Required base `8fb89bd383433d9e1b00b0b84df4522639e208c9` matched clean `main`.
- Created `codex/final-evidence-hardening-v1`. Git first rejected the elevated command because the sandbox and desktop
  users have different SIDs; a command-local `safe.directory` was used instead of changing global trust.
- Global `pytest` lacked the locked asyncio plugin, so validation used `.venv\Scripts\python.exe` (Python 3.12).

### Regression evidence

Root cause: the old report returned an intersection count but calculated success, p95, distributions and leak counts
over complete Runs. It also reselected the latest artifact/result on every request.

Changes and effects:

- every gated numerator and denominator now uses one sorted common-case set;
- left/right-only cases remain full-run diagnostics;
- explicit `exact`, `intersection` and `allow-diff` policies replace implicit tolerance;
- count, coverage, missing count, stable case-ID digest and fail-closed insufficiency are returned;
- migration `20260820_0021` persists comparison decisions and artifact/result manifests;
- `created_at DESC, id DESC` is the deterministic creation-time resolver; replay uses request SHA-256.

The first RED test observed `0.5` instead of `1.0` for `{A,B}` versus `{A,C}`. It passed after common-set isolation.

### Human Review evidence

Root cause: `run_id + case_id` plus conflict-ignore could return the wrong source, first-round packets contained machine
scores, and only a few top-level identifiers were removed.

Migration `20260820_0022` and service changes bind source record/content SHA, artifact ID/SHA, packet schema/SHA and
visibility policy. Ordinary and Agent tasks can coexist; identical source replay is idempotent. Evaluator evidence is
stored separately and shown only after the current reviewer submits or at dispute/adjudication. Reads verify packet
SHA. Input/citation/source/trajectory data now use bounded allowlists; the claim is “selected runtime identifiers
omitted,” not anonymity.

### MCP, HTTP, RLS and object reconciliation

- MCP now revalidates scrypt key hash, active/revoked/expiry state, tenant state and current permissions per call. A
  shared PostgreSQL row lock is held through service execution, ordering revocation against in-flight calls. Audit rows
  contain key ID, tenant, tool, outcome and trace ID, never plaintext key or arguments.
- A real stdio subprocess/PostgreSQL test and a real FastAPI/scrypt/PostgreSQL/MinIO test were added. The HTTP test uses
  20 concurrent identical uploads and evaluator calls, plus an instrumented store proving tenant rejection before blob
  read.
- Migration `20260820_0023` adds Agent/Human Review RLS policies and composite reference/tenant/Run/SHA binding. The
  restricted-role test uses `NOBYPASSRLS`. Compose still does not split long-lived runtime and migration credentials,
  so deployment-role separation remains partially verified.
- Reconciliation defaults to dry-run, honors a grace period, rechecks global references in a new transaction, protects
  shared SHA objects, records audit rows and supports deletion retry. It is not cross-system atomicity.

### Metric trust

Current metric extractors persist `reported` or `derived` provenance; none claims `verified`. Unsupported non-empty
configs fail validation. Negative and non-finite latency, cost, token, model-call, step and depth evidence is rejected.
Reported task success requires explicit gate opt-in.

### Validation record

- Focused Agent unit/API set after provenance work: `38 passed`.
- First full non-integration run: `816 passed, 10 failed, 37 deselected`. The failures shared one offline migration
  backfill cause plus old schema constructors/assertions.
- Corrected affected subset: `38 passed`.
- Docker CLI is unavailable locally. PostgreSQL/MinIO/subprocess tests were therefore pending remote CI at this local
  checkpoint and are not counted as local passes.

### Remote evidence closure

The first branch run (`32280535475`) failed for concrete reasons: evidence-pin `RESTRICT` constraints required the
integration fixtures to delete their owned regression/review graph before deleting tenants, and the MCP fixture used a
zero case count forbidden by the established dataset invariant. After that repair, run `32281558165` passed Agent
workflow, HTTP/MinIO and both migration paths, then exposed a missing non-null `AuditEvent.resource_id` in the real MCP
subprocess path. The auditor now uses the per-call trace UUID as that bounded resource identity and the integration test
checks the trace/resource binding.

Final GitHub Actions run
[`32282462281`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/32282462281) at exact source
`22fda896a1b24b0cf41cd1402ead521f74758ac6` completed both `quality-and-integration` and `compose-smoke` successfully.
It passed all focused PostgreSQL/Redis/MinIO/MCP/RLS/reconciliation/concurrency steps, both downgrade/re-upgrade paths,
the image build and the complete Compose smoke topology. This verifies the stated behaviors in one CI topology; it is
not production-scale, SLO or universal performance evidence.
