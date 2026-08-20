# AI EvalOps Platform — Final portfolio synchronization report

Date: 2026-08-20

Repository: `https://github.com/godofxuan/ai-evalops-platform`

Branch: `codex/final-evidence-hardening-v1`

PRE_SYNC_HEAD: `0b7c1a340a0dc362ff1af6948664e3a95ac06f19`

Final-hardening implementation baseline: `22fda896a1b24b0cf41cd1402ead521f74758ac6`

Migration head: `20260820_0025`

## Status

- `PORTFOLIO_DOCS_SYNCED`
- `RESUME_HANDOFF_SYNCED`
- `TEACHING_HANDOFF_SYNCED`
- `PROVENANCE_REVIEWED`
- Release remains `NOT_READY_TARGETED_NEGATIVE_SCALING`.
- Production readiness remains `NOT_VERIFIED`.
- `portfolio-ready != release-ready != production-ready`.

These synchronization statuses mean the repository surfaces now reflect the verified implementation and boundaries. They
do not create a release, tag, production qualification, new schema, migration, runtime behavior or benchmark result.

## Review scope and method

The review read repository-level instructions (none of `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md` or `README_FIRST*`
exists at the root), README/status/config/lockfile/workflows, the Alembic chain, final-hardening report, Agent architecture/
schema/metrics/regression/review/MCP documents, benchmark fixtures/evidence, requested resume/teaching/handoff surfaces,
relevant Run/Job/Attempt/CaseResult/claim/heartbeat/fencing/Reaper/artifact/Agent/review/MCP/RLS/reconciliation source, and
the corresponding tests.

Facts were accepted in this order: code/migrations/tests; checked-in evidence/manifests; current CI workflow and successful
run; final-hardening report; current Agent documentation; README; historical handoffs. Conflicts were resolved to the weaker,
better-supported wording. Frozen experiments were not rerun or edited.

## Startup state

| Check | Result |
| --- | --- |
| repository root | verified repository checkout (local absolute path intentionally omitted from public documentation) |
| target branch | `codex/final-evidence-hardening-v1` |
| PRE_SYNC_HEAD | `0b7c1a340a0dc362ff1af6948664e3a95ac06f19` |
| initial worktree | clean |
| user changes | none |
| branch safety | no switch, reset, merge, tag, release or force push required |

## Stale surfaces found and resolution

| Conflict | Why it was unsafe or incomplete | Resolution | Result |
| --- | --- | --- | --- |
| `PROJECT_STATUS.md` began with 2026-08-11 / `codex/evidence-gate-1` / `39f381e` | presented scheduler archive as whole-project current state | inserted final-hardening current top and relabeled old body historical | current Agent layer leads; archive remains intact |
| Evidence/consistency maps were scheduler-only | omitted migrations `0019`–`0025` and current CI | added claim→code→test→scope Agent rows and current identity | claims now resolve to implementation evidence |
| Resume entrypoints led with scheduler/release failure | hid later positive Agent engineering and mixed claim audiences | created five claim tiers and current Agent bullets; kept failures in ledger/interview | recruiter summary is positive but not misleading |
| `783 passed, 33 skipped` looked current | it is a 2026-08-11 local run | explicitly dated it historical; added implementation CI 826 and this sync's local 833 | old and current totals no longer conflict |
| Teaching handoff had ten scheduler modules | did not teach current Agent infrastructure | added nine-step reading order and 21 ten-field workshop cards | every requested mechanism has code/transaction/test/exercise context |
| Tutorial implied comparison could keep selecting newest rows | obscured immutable manifest replay | clarified resolve-once, pin IDs, replay manifest | selection identity is explicit and immutable |
| Interview bank stopped at Candidate 4 | no defense for current resume claims | added trajectory, regression, review, MCP and reconciliation stories | current bullets expand into evidence-backed answers |
| No consolidated provenance record | origin/license/tool-assistance boundary was not reviewable | added path/source/use/license/evidence/action/risk table | confirmed facts separated from `UNKNOWN` |
| No cross-document gate | future edits could silently regress identities/claims/links | added focused unit tests through RED→GREEN slices | status, tiers, curriculum, provenance and links are checked |

The full term-by-term and file-by-file classification is in
[`FINAL_HARDENING_CROSS_SURFACE_AUDIT_20260820.md`](FINAL_HARDENING_CROSS_SURFACE_AUDIT_20260820.md).

## Files changed

- `PROJECT_STATUS.md`
- `README.md`
- `docs/handoffs/CROSS_SURFACE_CONSISTENCY.md`
- `docs/handoffs/EVALOPS_RESUME_BULLET_POOL.md`
- `docs/handoffs/FINAL_HARDENING_CROSS_SURFACE_AUDIT_20260820.md` (new)
- `docs/handoffs/FINAL_PORTFOLIO_SYNC_REPORT_20260820.md` (new)
- `docs/handoffs/INTERVIEW_STORY_BANK.md`
- `docs/handoffs/PROJECT_EVIDENCE_MAP.md`
- `docs/handoffs/RESUME_CODEX_HANDOFF.md`
- `docs/handoffs/RESUME_INTERVIEW_CONSISTENCY.md`
- `docs/handoffs/RESUME_METRIC_LEDGER.md`
- `docs/handoffs/TEACHING_CODEX_HANDOFF.md`
- `docs/handoffs/TEACHING_CODEX_UPDATE.md`
- all eight files under `docs/handoffs/resume_package/`
- `docs/handoffs/THIRD_PARTY_PROVENANCE.md` (new)
- `docs/learning/AGENT_EVALOPS_TUTORIAL.md`
- `docs/learning/EVALOPS_INTERVIEW_UPDATE.md`
- `docs/resume/AGENT_EVAL_RESUME_EVIDENCE.md`
- `tests/unit/test_portfolio_documentation.py` (new)

No application code, migration, workflow, frozen JSON, manifest, benchmark parameter or historical result was changed.

## Canonical current state

The platform combines durable multi-tenant asynchronous evaluation orchestration with current Agent Evaluation
Infrastructure:

- immutable DatasetVersion and Run→Job→lease-bound Attempt→CaseResult state;
- owner/version/live-expiry/Attempt fencing, stale success/failure rejection and Reaper recovery;
- real PostgreSQL `SKIP LOCKED` false-empty repair and durable fair-turn state;
- framework-neutral Agent trajectory artifact, canonical JSON/SHA-256 and immutable ingestion;
- exactly seven deterministic trajectory metric extractor kinds with `reported`/`derived` provenance;
- common-case-only comparison, explicit case-set policy, immutable manifest and coverage/sample sufficiency fail-closed;
- source/result/artifact/packet hash-bound review with staged evaluator visibility;
- per-call credential revalidation through a local MCP stdio process;
- Agent evidence RLS/composite ownership foreign keys in the tested topology;
- dry-run-first object reconciliation with grace/recheck/retry/audit.

## Resume claim layers

### `CURRENT_POSITIVE_RESUME`

- durable asynchronous orchestration and tested fencing/recovery;
- canonical immutable Agent trajectory evidence and seven deterministic reported/derived metric extractors;
- manifest-pinned fail-closed common-case regression;
- source-bound staged human review;
- per-call local MCP stdio authorization;
- bounded RLS/composite-FK hardening and compensating orphan reconciliation.

### `JD_SPECIFIC_BACKUP`

- deterministic real-PostgreSQL concurrency repair;
- tenant ownership/identity constraints;
- evidence manifests and release-gate automation;
- fixed adapter-contract replay, only when explicitly described as fixture evidence.

### `INTERVIEW_ONLY`

- false-empty interleaving and remaining observation window;
- exact frozen fairness receipt definition;
- observer-effect reasoning and stop decisions;
- external-side-effect and cross-store half-commit windows.

### `HISTORICAL_NEGATIVE`

- frozen 4→8 ratios `0.782511 / 0.772797 / 0.796214 / 1.014063`, with 3/4 below 0.95;
- observer claim-p95 perturbations `11.3194%`, `13.4906%`, `28.0396%` exceeding the frozen 10% budget;
- H1/H2/H3 `NOT_RUN`/`INCONCLUSIVE` and no claimed root cause;
- v0.1.0 untagged/unreleased and `NOT_READY_TARGETED_NEGATIVE_SCALING`;
- historical local result `783 passed, 33 skipped` dated 2026-08-11.

### `FORBIDDEN`

Production-ready/scale/SLO, exactly-once, universal fairness, starvation/deadlock freedom, linear scaling, seven verified
evaluators, authority-verified Agent truth, all-framework/live-LangGraph support, remote/OAuth MCP, atomic PostgreSQL/S3,
complete production RLS role isolation, security certification and released v0.1.0.

## Teaching reading order

1. `PROJECT_STATUS.md`
2. `PROJECT_EVIDENCE_MAP.md`
3. core domain/state-machine source and documentation
4. scheduler/concurrency teaching handoff
5. `FINAL_HARDENING_REPORT.md`
6. `AGENT_EVALOPS_TUTORIAL.md`
7. `AGENT_EVAL_RESUME_EVIDENCE.md`
8. `RESUME_METRIC_LEDGER.md`
9. `INTERVIEW_STORY_BANK.md`

Each of the 21 curriculum cards requires Concept → Real code chain → SQL/transaction boundary → Test → Failure mode →
Trade-off → Observed result → Interview follow-up → Independent answer → Small modification exercise.

## Provenance and license result

- Official MCP Python SDK: confirmed `API_USAGE`; `mcp==2.0.0` is hash-locked; upstream project identifies MIT.
- LangGraph: `CONCEPT_ONLY` callback-name compatibility fixture; no declared/locked LangGraph runtime dependency.
- Agent harness/case inspiration: no concrete upstream recorded, so `UNKNOWN`; no origin was invented.
- Claude assistance: no file-specific repository evidence, so `UNKNOWN`.
- Codex assistance: confirmed by Git author/execution logs, but that does not identify training sources or third-party origin.
- No inspected path established `COPIED` or `ADAPTED` code. This is a bounded finding, not proof of complete idea history.
- No repository-root project license/NOTICE exists. Choosing a project license and performing full transitive/container SBOM
  review remain explicit pre-distribution actions.

Detailed evidence and risk wording: [`THIRD_PARTY_PROVENANCE.md`](THIRD_PARTY_PROVENANCE.md).

## Local validation before commit

| Command | Exit | Result / environment |
| --- | ---: | --- |
| `git diff --check` | 0 | no whitespace errors |
| `.venv/Scripts/ruff.exe format --check .` (first run) | 1 | new test file required import/line formatting; formatter applied, rules unchanged |
| `.venv/Scripts/ruff.exe format --check .` (after fix) | 0 | 490 files formatted |
| `.venv/Scripts/ruff.exe check .` (after fix) | 0 | all checks passed |
| `.venv/Scripts/mypy.exe app scripts tests/integration tests/concurrency` | 0 | strict check: 165 source files, no issues |
| `.venv/Scripts/python.exe -m compileall -q app scripts tests` | 0 | compilation passed |
| `.venv/Scripts/alembic.exe heads` | 0 | single head `20260820_0025` (metadata check; no database migration executed locally) |
| `.venv/Scripts/pytest.exe tests/unit/test_portfolio_documentation.py -q` | 0 | 7 passed; identity/tier/curriculum/provenance/links gates |
| `.venv/Scripts/pytest.exe tests/unit/agent_eval ... -q` | 0 | 42 focused Agent/MCP/API tests passed |
| `.venv/Scripts/python.exe -m scripts.run_agent_adapter_benchmark` + evidence diff | 0 | deterministic replay; checked-in JSON unchanged |
| `.venv/Scripts/pytest.exe -m "not integration" -q` | 0 | 833 passed, 37 deselected in 259.24 s |

The initial format failure was resolved as a normal RED→GREEN/refactor outcome: the new test behavior was already green,
then the repository formatter reordered imports and normalized expressions; the full format/lint gate passed afterward.

## Remote existing evidence

- Workflow [`32282462281`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/32282462281) passed at implementation
  baseline `22fda896a1b24b0cf41cd1402ead521f74758ac6`. It recorded 826 non-integration tests and successful named PostgreSQL,
  Redis, MinIO, MCP stdio, concurrency, Agent workflow, RLS, reconciliation, migration downgrade/re-upgrade, image and
  Compose gates.
- Workflow [`32341372636`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/32341372636) passed at documentation
  head `0b7c1a340a0dc362ff1af6948664e3a95ac06f19` before this synchronization.

These are `REMOTE_EXISTING_EVIDENCE`, not local results and not a production topology.

## Gates not run locally

Environment audit found no `docker` command, closed local ports 5432/6379/9000, and no integration opt-in variables.
Accordingly, the following are `NOT_RUN_ENVIRONMENT`, not pass or failure:

- PostgreSQL concurrency/fairness/RLS/Agent workflow tests requiring the real service;
- Redis and MinIO integrations;
- Alembic database upgrade/downgrade/re-upgrade execution;
- application image build and full Compose smoke/hardening/observability checks;
- real MCP stdio revocation integration because it is tied to the real PostgreSQL credential store.

The frozen 64-arm/6,400-Job scheduler experiment, scaling benchmark and performance attribution were intentionally
`NOT_RUN_BY_SCOPE` and unchanged.

## Remaining release and production gaps

- historical negative 4→8 scaling still blocks the frozen v0.1.0 gate;
- measurement validity failed and no scheduler root cause was established;
- execution remains at-least-once and external Target/tool effects may repeat;
- current Agent metrics are reported or derived, not independently authority-verified;
- fixed adapters are not live framework runtime/performance evidence;
- MCP is local stdio only;
- PostgreSQL and object storage have no atomic commit; reconciliation is compensating cleanup;
- Compose does not establish separate production migration/runtime RLS roles;
- no production capacity, SLO, on-call record, security certification, release tag or GitHub Release exists;
- repository licensing and a complete dependency/container SBOM require explicit maintainer work before distribution.
