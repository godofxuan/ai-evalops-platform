# Candidate 3 RED/GREEN ledger

Status: `RED_VERIFIED`; Candidate 3 ordinary CI and PostgreSQL correctness `GREEN`

## Environment

The local host has no PostgreSQL or Docker runtime. Local format/lint/mypy passed and the integration test collected then explicitly skipped. The authoritative database result is PostgreSQL-backed GitHub Actions; SQLite and mocks were not substituted.

## Target RED

| Property | Result |
|---|---|
| deterministic coordination | PASS: `Barrier` plus explicit `Event` gates, no random sleep |
| equal-priority primary queue | 21 Jobs |
| equal-priority secondary queue | 1 Job |
| Worker identities | 8 |
| Candidate 2 B reservation | early and committed |
| later A receipts while B paused | 6 |
| B committed receipt position | 8 |
| frozen requirement | <=2 |
| RED outcome | expected FAIL |
| source | `551f6b4fe01fec8ec8550527579772040f1a7b20` |
| Actions | `31325521253` |
| assertion | `FAIR_RESERVATION_NOT_SUFFICIENT_RED` |

## Candidate 3 test obligations

| RED/GREEN | Test source | Entry state |
|---|---|---|
| 1. frozen 20:1/8W receipt <=2 | targeted harness + durable fairness test | Candidate 2 FAIL |
| 2. deterministic overtaking schedule | `test_tenant_durable_fairness.py` | Candidate 2 FAIL at position 8 |
| 3. priority preservation | existing real-PG priority regression, extended for round priority | Candidate 3 PASS in `31327012832`/`31327016117` |
| 4. same Tenant 10W/100J limit=1 | 20-repetition production-shaped regression | Candidate 3 PASS: 2,000 unique Jobs/Attempts |
| 5. permit crash | new round/permit rollback and post-refill recovery regression | Candidate 3 PASS |
| 6. cross-Tenant progress | different pending state rows under `SKIP LOCKED` | Candidate 3 PASS |
| 7. no duplicate Job | first-wave plus complete drain reconciliation | Candidate 3 PASS |
| 8. deadlock regression | PostgreSQL lock timeouts and lock diagnostics | Candidate 3 PASS |

Production implementation started only after this RED and the proposal/state-machine commits. The exact GREEN source
and ordinary CI identities are recorded below. Complete release qualification is separate and later failed at the
targeted evidence gate.

## Vertical TDD implementation ledger

### Slice 1 — schema and migration

1. Added offline upgrade/downgrade expectations before revision `0018` existed.
2. RED: 2/2 tests failed with `Can't locate revision identified by '20260810_0018'`.
3. Implemented only the singleton, reusable per-Tenant state, constraints/index, singleton seed and nullable Attempt sequence.
4. First GREEN attempt exposed a test bug: the assertion compared SQLAlchemy `Column` objects with strings. The production metadata was correct; changing the test to compare `columns.keys()` made the oracle valid.
5. GREEN: migration/ORM subset 19 passed. Upgrade, downgrade, FK, unique permit identity, bounded row shape, active-permit index and positive nullable sequence are asserted.

Effect: Candidate 3 state is durable and bounded without changing a Job claim yet.

### Slice 2 — SQL lock interfaces

1. Added compile-level tests before the new statement builders existed.
2. RED: collection failed because `build_pending_scheduler_permit_statement` did not exist.
3. Implemented highest-priority round membership, current-generation pending permit selection and exact-priority Tenant Job locking.
4. First compile attempt exposed ambiguous ORM join origin in the aggregate membership query. Adding explicit `.select_from(EvaluationJob)` fixed the SQL source without changing the invariant.
5. GREEN: 4/4 SQL contract tests passed; mypy passed.

Effect: lock targets and priority scope are reviewable before concurrency execution.

### Slice 3 — production claim transaction

The one Candidate 3 implementation:

- opens a round under the singleton only when no current pending state exists;
- upserts one ordered pending state per highest-priority eligible Tenant;
- uses `SKIP LOCKED` fast selection plus the same-row blocking fallback;
- preserves the existing atomic Job/lease/version/Attempt/Audit/Outbox writes;
- commits permit `CONSUMED` with the Job or rolls both back;
- marks a vanished member `EMPTY` and rechecks liveness;
- assigns `JobAttempt.scheduler_claim_sequence` under a tail-only singleton lock;
- leaves the frozen application receipt timestamp untouched.

An implementation issue appeared in five old unit tests: their hand-built sessions modeled Candidate 2's two transactions and returned `(Job, Run, Tenant)` for every SQL statement. Extending those fakes to mimic singleton MVCC, per-Tenant row locks, blocking fallback and tail sequencing would test the fake rather than PostgreSQL. The shared Job-write assertions were retained through `_persist_claim_rows`; fast/wait SQL contracts moved to compile tests; fairness, crash, liveness and deadlock remain real-PostgreSQL tests.

Effect: production changes stay in migration/ORM/claiming plus tests and evidence instrumentation. Worker, Result, Reaper, Evaluator, API, lease duration and fencing code are unchanged.

### Slice 4 — local verification before push

| Check | Result |
|---|---|
| `ruff format --check .` | 369 files formatted |
| `ruff check .` | PASS |
| `mypy app scripts tests/integration tests/concurrency` | PASS, 136 source files |
| high-risk scheduler/migration/evidence subset | PASS, 100 tests |
| durable fairness integration collection | 3 tests collected, locally SKIPPED because PostgreSQL is unavailable |
| full `pytest -m 'not integration'` | environment-limited: two wrapper timeouts (about 124s and 304s) with no reported assertion failure |

The full-suite timeout is not promoted to PASS or FAIL. GitHub Actions ordinary CI is the authoritative full-unit/PostgreSQL/Compose execution.

## Candidate 3 authoritative GREEN

| Field | Result |
|---|---|
| source | `02f5e680e71d05c76c145da6895122a2cf04ba14` |
| push run | `31327012832` — PASS, total 6m14s |
| quality/integration job | `93278884302` — PASS, 6m04s |
| Compose job | `93278884327` — PASS, 56s |
| lock diagnostic artifact | `final-scheduler-lock-diagnostics-31327012832-1` |
| artifact digest | `sha256:fe1dd4651f40ea9b8ce3ea1507549ea608d57d251283ef0e07b6869135c622a6` |
| PR run | `31327016117` — PASS, total 5m59s |

The PostgreSQL job passed the unchanged 20-repetition 10W/100J test, deterministic receipt fairness GREEN, priority, permit-crash rollback/recovery, cross-Tenant progress, Job/Attempt uniqueness, full drain, lock/deadlock diagnostics, result/lease fencing, every other integration suite and the downgrade/re-upgrade migration. The deterministic Candidate 3 test simultaneously checks the frozen application receipt and the database diagnostic sequence: B is the second sequence and its application receipt remains within position 2 while six later A Workers have already reached permit selection.

Gate classification at this point:

- `WORKFLOW_EXECUTED = true`;
- `TESTS_PASS = true` for ordinary CI;
- `CORRECTNESS_PASS = true` for the preregistered scheduler correctness chain;
- `EVIDENCE_COMPLETE = false` because targeted `31327388006` later failed and downstream gates were stopped;
- `PERFORMANCE_PASS = false/not established`; rep1 diagnostics are not a complete protocol;
- `RELEASE_READY = false`.

## Subsequent stop condition

Candidate 3 ordinary correctness GREEN did not authorize release. Targeted run `31327388006` completed one
diagnostic repetition, then the release-bundle assessor failed
`postgres_explain_candidate_cardinality_mismatch`. The frozen execution rule therefore stopped capacity,
same-runner, fault and formal stages. See `06_TARGETED.md`; no production Candidate 4 or gate relaxation followed.
