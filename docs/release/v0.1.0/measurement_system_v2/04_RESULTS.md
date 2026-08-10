# Measurement-System Analysis V2 final report

## 1. HEAD / ENVIRONMENT

- `OBSERVED` starting audit SHA: `8a093a735333fe3e54bc6238e0a8d4949b73ccf6`.
- `OBSERVED` evidence-preservation SHA before this report: `2959ccdc2dd4a9789e0aed9c4e99166c1edad357`.
- `OBSERVED` branch: `codex/evidence-gate-1`; worktree was clean and synchronized before report edits.
- `OBSERVED` local Python: system 3.13.5; project virtual environment 3.12.13.
- `OBSERVED` remote Python: 3.12.13.
- `OBSERVED` remote PostgreSQL: 18.4, x86_64 Alpine build.
- `OBSERVED` local OS: Windows NT 10.0.26200.0; remote runner: Linux x86_64.
- `OBSERVED` local Docker/Compose/psql: unavailable; remote Docker Engine 28.0.4 and Compose 2.38.2.
- `OBSERVED` final pushed SHA is reported by Git after the documentation commit; a file cannot embed
  the hash of the commit that contains itself without changing that hash.

## 2. BASELINE

All timings are wall-clock observations on the local Windows workspace at starting SHA `8a093a7`.

| Command | Result | Runtime |
|---|---|---:|
| `.venv Python --version` | Python 3.12.13 | <1 s |
| system `python -m pip check` | exit 0, compatible | 1.334 s |
| `.venv Python -m compileall app scripts tests` | exit 0 | 0.312 s |
| `.venv Python -m pytest -q` | 716 passed, 29 skipped | 415.586 s process wall time; pytest 414.22 s |

`NOT_RUN`: Local true-PostgreSQL integrations, because this host has no PostgreSQL, Docker or `psql`.
Those tests were subsequently run on the real PostgreSQL service in ordinary remote CI.

## 3. HISTORICAL STATE REVALIDATION

The listed file counts and hashes were independently recomputed from preserved evidence.

| Run | Status / schema | Role | Immutable audit |
|---:|---|---|---|
| 31327388006 | `FAILED`, schema v1 | historical targeted contract failure | 155/155 files; zero mismatches; tree `234347cce8872b75595b2cf312baaf25b74091ce` |
| 31352270523 | `NEGATIVE_SCALING`, schema v2; 4 reps `VERIFIED` | formal targeted release input | 598/598 files; zero mismatches; tree `e321f63661645f728481ef11587f94fec9a0547a` |
| 31400658653 | `INSTRUMENTATION_TOO_INTRUSIVE` | first synchronous-observer qualification | 893/893 files; zero mismatches; tree `e2eecf765fba7300ecd8d48f0e301c78c5cbcf96` |
| 31407782154 | `INSTRUMENTATION_TOO_INTRUSIVE` | low-overhead synchronous requalification | 84/84 files; zero mismatches; tree `adab7f560790f840f9db60eb4fbc23e62201e81b` |

`OBSERVED`: The two historical absolute claim-p95 changes remain 11.3194% and 13.4906%, both over
the unchanged 10% limit. No historical evidence directory was edited during this stage.

## 4. EVIDENCE-GATE HARDENING

### Workload identity

`TEST_FACT`: RED tests demonstrated that the old attribution assessor could accept queue,
distribution, worker or batch metadata drift. GREEN binds every known arm ID to its derived frozen
metadata and rejects unknown or malformed IDs.

### sample_jobs

`TEST_FACT`: A dedicated RED used arm `fair-q1000-skew_20_to_1-w8-b1` with `sample_jobs=20`.
GREEN requires the registered value 100 and fails closed on drift.

### Behavioral source lock

`CODE_FACT`: The old workflow compared only `app/` and `scripts/`. The deterministic source-lock
helper now covers `app/`, `scripts/`, `alembic/`, `deploy/`, `.python-version`, `alembic.ini`,
`pyproject.toml` and `uv.lock`. Documentation, result preservation and workflow-trigger-only changes
remain allowed; malformed change paths fail closed.

## 5. SYNCHRONOUS OBSERVER STATUS

```text
RETIRED_FOR_FORMAL_ATTRIBUTION
```

`DERIVED`: Both independently audited remote qualifications exceeded the absolute claim-p95 budget.
The callback may remain for local debugging and historical reproduction, but is not a formal
measurement candidate. Local recorder microbenchmark improvement is `LOCAL_MICROBENCHMARK_ONLY`,
not remote validity evidence.

## 6. PASSIVE TELEMETRY DESIGN

- `CODE_FACT` architecture: a separate Python OS process and independent psycopg connection observe
  PostgreSQL while benchmark Workers keep their normal claim transactions.
- `CODE_FACT` views: static parameterized read-only SQL over `pg_stat_activity`, `pg_locks` and
  `pg_class`; the session is explicitly read-only.
- `CODE_FACT` frequency: frozen 5 Hz. The local 1/5/10/20-Hz engineering study selected a conservative
  query rate; actual validity was decided only by the remote OFF/ON qualification.
- `CODE_FACT` bounds: maximum 256 projected rows/sample and 10,000 samples; output streams and flushes
  one JSONL record at a time.
- `CODE_FACT` public projection: timestamp, pid, state, wait type/event, backend type, query
  fingerprint/category and safe lock/relation fields.
- `CODE_FACT` privacy: raw query text, DSN, credentials and workload identifiers are not persisted.
- `CODE_FACT` isolation: collector exceptions do not abort the workload, but nonzero errors, drops or
  overflow make assessment invalid.
- `CODE_FACT` the collector starts immediately before and stops immediately after the measured Worker
  interval; no production scheduler decision flow or SQL was changed.

## 7. TELEMETRY TESTS

| Test/contract | Purpose | Result |
|---|---|---|
| separate connection integration | observer is outside the workload transaction | PASS in ordinary remote CI |
| visible wait without transaction mutation | passive read observes but does not alter lock/transaction state | PASS in ordinary remote CI |
| bounded streaming output | no unbounded in-memory event list | PASS |
| workload survives collector failure | measurement failure is isolated | PASS in ordinary remote CI |
| sensitive raw query rejected | public schema cannot contain query text | PASS |
| sampling metadata recorded | samples, errors, drops and bounds are assessable | PASS |
| clean stop | stop signal joins collector and seals summary | PASS in ordinary remote CI |
| telemetry error rejects assessment | fail-closed measurement validity | PASS |
| wrong arm/workload/order/repetition/domain | prevents identity and numeric spoofing | PASS |
| correctness/false-empty/manifest drift | prevents a performance verdict over invalid evidence | PASS |

`OBSERVED`: Ordinary CI runs `31419669297` and `31419676791` both passed quality and Compose jobs,
including the PostgreSQL telemetry integrations and durable-fairness regression.

Final local validation after the result documentation was assembled:

| Command | Result | Runtime |
|---|---|---:|
| performance-attribution assessor unit file | 12 passed | 0.683 s process wall time |
| measurement-system assessor unit file | 30 passed | 0.438 s process wall time |
| PostgreSQL telemetry unit file | 6 passed | 0.945 s process wall time |
| PostgreSQL telemetry integration file | 4 skipped: real PostgreSQL unavailable locally | 0.464 s process wall time |
| durable-fairness concurrency file | 4 skipped: migrated PostgreSQL unavailable locally | 1.128 s process wall time |
| full `.venv Python -m pytest -q` | 783 passed, 33 skipped | 423.829 s process wall time; pytest 422.82 s |
| `.venv Python -m compileall app scripts tests` | exit 0 | 0.112 s |
| system `python -m pip check` | exit 0, no broken requirements | 1.258 s |

`OBSERVED`: `.venv\Scripts\python.exe -m pip check` is not a valid command for this uv-created
environment because that interpreter has no `pip` module. No package was installed to hide this
fact. The remote workflow uses `uv pip check`, which passed against its actual uv environment;
local `uv` is not installed on PATH.

## 8. PREREGISTERED EXPERIMENT

| Contract | Frozen value |
|---|---|
| arm | `fair-q1000-skew_20_to_1-w8-b1` |
| queue | 1,000 |
| distribution | `skew_20_to_1` |
| workers | 8 |
| batch | 1 |
| sample Jobs | 100 |
| OFF / ON count | exactly 4 / exactly 4 |
| order | Block A OFF/ON/ON/OFF; Block B ON/OFF/OFF/ON |
| warm-up | no workload-claim warm-up, identical for OFF/ON |
| telemetry | 5 Hz external PostgreSQL polling in ON only |
| thresholds | absolute throughput <=5%; absolute claim p95 <=10% |
| stop rule | stop after eight; invalid => stop attribution; valid => stop pending new preregistration |

The preregistration SHA `1c87fb218e334790812080701bd74b81488bf19c` precedes both formal
workflow runs. The integration fix was separately preregistered at
`2180646802d41abfb5b9fdb6abd7b203cbced1fb` before retriggering.

## 9. RAW OBSERVATIONS

### Performance and resource observations

| Pos | Block | Mode | Rep | Jobs/s | Claim p50/p95/p99 ms | CPU % | Peak RSS bytes | Retries | Retry/success | Waiting fallback | Lock-wait peak |
|---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | A | OFF | 1 | 29.937430 | 144.162 / 582.003 / 873.772 | 93.634 | 101634048 | 265 | 2.65 | 158 | 5 |
| 2 | A | ON | 1 | 31.180970 | 144.274 / 466.961 / 702.634 | 95.187 | 96378880 | 243 | 2.43 | 148 | 7 |
| 3 | A | ON | 2 | 29.691850 | 210.937 / 321.749 / 466.999 | 96.250 | 96440320 | 284 | 2.84 | 167 | 7 |
| 4 | A | OFF | 2 | 29.900266 | 91.333 / 659.328 / 1223.547 | 91.867 | 96247808 | 258 | 2.58 | 151 | 6 |
| 5 | B | ON | 3 | 29.889049 | 104.878 / 693.985 / 877.073 | 93.177 | 96378880 | 266 | 2.66 | 153 | 7 |
| 6 | B | OFF | 3 | 29.138523 | 87.363 / 758.051 / 1107.953 | 93.191 | 96333824 | 274 | 2.74 | 159 | 6 |
| 7 | B | OFF | 4 | 30.451013 | 80.470 / 863.945 / 1140.900 | 93.497 | 96174080 | 250 | 2.50 | 147 | 5 |
| 8 | B | ON | 4 | 29.052526 | 201.546 / 552.990 / 719.447 | 94.307 | 96358400 | 283 | 2.83 | 164 | 7 |

### Correctness and telemetry observations

All rows had submitted/unique/terminal = 100/100/100 and all protected correctness counters plus
`empty_while_eligible` = 0.

| Pos | Mode | Samples | Wait-observing samples | Waiting backends | Rows | Errors | Drops | Overflow |
|---:|:---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | OFF | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2 | ON | 17 | 16 | 10 | 1286 | 0 | 0 | 0 |
| 3 | ON | 17 | 16 | 9 | 1350 | 0 | 0 | 0 |
| 4 | OFF | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 5 | ON | 17 | 16 | 8 | 1243 | 0 | 0 | 0 |
| 6 | OFF | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 7 | OFF | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 8 | ON | 18 | 17 | 8 | 1514 | 0 | 0 | 0 |

## 10. CALCULATION AUDIT

`DERIVED` independently from the eight committed CSV rows:

| Metric | OFF median | ON median | Relative change | Absolute gate | Result |
|---|---:|---:|---:|---:|---|
| Jobs/s | 29.918848 | 29.790450 | -0.429156% | <=5% | PASS |
| Claim p95 ms | 708.689593 | 509.975702 | -28.039623% | <=10% | **FAIL** |

| Metric | Mode | Min | Max | Mean | Median | Range | Range/mean | MAD |
|---|:---:|---:|---:|---:|---:|---:|---:|---:|
| Jobs/s | OFF | 29.138523 | 30.451013 | 29.856808 | 29.918848 | 1.312490 | 0.043959 | 0.275373 |
| Jobs/s | ON | 29.052526 | 31.180970 | 29.953599 | 29.790450 | 2.128444 | 0.071058 | 0.418261 |
| Claim p95 ms | OFF | 582.003366 | 863.944845 | 715.831849 | 708.689593 | 281.941479 | 0.393866 | 88.023791 |
| Claim p95 ms | ON | 321.748555 | 693.985425 | 508.921346 | 509.975702 | 372.236871 | 0.731423 | 113.512028 |

`DERIVED`: Claim p95 misses the gate by 18.039623 percentage points. The absolute-value contract
forbids treating the negative direction as a pass.

## 11. TELEMETRY INTEGRITY

- `OBSERVED` successful samples: 69; wait-observing samples: 65; projected rows: 5,393.
- `OBSERVED` telemetry errors/drops/overflows: 0/0/0.
- `OBSERVED` raw query persisted: `NO` in every ON summary.
- `OBSERVED` public sample keys are only `query_latency_ms`, `record_type`, `rows`, `sample_index`;
  row keys match the allowlisted safe projection.
- `OBSERVED` root manifest: 151 expected / 151 actual, zero missing, extra, size or hash mismatch.
- `OBSERVED` artifact digest: `c9c46bbe33f9581b921bbc6289814bf59270b271d276e93eaab584db81e76b35`.
- `OBSERVED` evidence subtree at preservation commit: `02134ba3822d88a3685755439c381bd1450fad73`.

Sampling-based telemetry observes sufficiently long-lived waits visible at sample time; it is not an
exhaustive event trace. The 69 snapshots cannot prove that every lock wait was observed.

## 12. MEASUREMENT VERDICT

```text
MEASUREMENT_SYSTEM_INVALID
```

`DERIVED`: Workload, correctness, telemetry integrity, order, source and manifest checks pass, and
throughput perturbation is within budget. Absolute claim-p95 perturbation is 28.039623%, above 10%.
This single failed mandatory condition is sufficient for fail-closed rejection.

## 13. CAUSAL CLAIM BOUNDARY

| Hypothesis | Status |
|---|---|
| H1 SchedulerCoordination singleton contention | `NOT_RUN` |
| H2 Tenant-permit contention | `NOT_RUN` |
| H3 SKIP LOCKED / retry feedback | `NOT_RUN` |

`OBSERVED`: Wait and lock samples exist. `NOT_VERIFIED`: none is a causal root cause. The workflow
contains no formal-attribution job, and the invalid instrument cannot support formal attribution.

## 14. RELEASE STATE

| Item | State |
|---|---|
| Candidate 3 bounded correctness | PASS |
| frozen 20:1 fairness | PASS FOR FROZEN WORKLOAD |
| formal targeted 4-to-8 scaling | `NEGATIVE_SCALING` |
| passive measurement validity | `MEASUREMENT_SYSTEM_INVALID` |
| H1 / H2 / H3 | `INCONCLUSIVE`; current formal run `NOT_RUN` |
| v0.1.0 | `NOT_READY` |
| PR #1 | Draft; do not merge or mark Ready |
| capacity / same-runner / fault / formal downstream | `NOT_RUN_STOPPED` |
| scheduler candidate budget | 0 |

No tag or GitHub Release is authorized. Diagnostic telemetry does not replace the formal negative
targeted result.

## 15. SECURITY / PRIVACY REVIEW

- `CODE_FACT` SQL is fixed and parameterized; no relation, pid, Tenant or identifier is concatenated.
- `CODE_FACT` the telemetry connection is read-only and cannot cancel backends or alter locks.
- `CODE_FACT` Tenant, Run, Job and Attempt identifiers and SQL parameters are omitted.
- `CODE_FACT` raw PostgreSQL query text and DSN are not persisted in public evidence.
- `OBSERVED` committed sample rows contain only allowlisted fields; no `.env`, token, password or
  connection credential is included.
- `CODE_FACT` measurement job permission is `contents: read`; only the separate preservation job has
  `contents: write`.
- `CODE_FACT` preservation checks the remote tip, uses a non-force push and fails closed with
  `PRESERVATION_CONFLICT` on a race.

## 16. LEARNING DOCUMENTATION

Added `docs/learning/evidence_gate_hardening/11_PASSIVE_MEASUREMENT_SYSTEM.md`. It explains the
observer effect, absolute thresholds, passive-polling limitations, the real 4+4 data, why validity
and attribution are separate, why Candidate 4 stays prohibited, and how to present an intentionally
rejected instrument in an interview.

## 17. COMMITS

| SHA | Title | Purpose |
|---|---|---|
| `8e5c2b9` | test(evidence): harden performance attribution workload identity | RED workload-spoof tests |
| `a1a5339` | fix(evidence): bind performance attribution to frozen workload | GREEN arm/sample identity |
| `667daba` | test(evidence): specify complete behavioral source lock | RED source-scope contract |
| `5636a2a` | fix(evidence): enforce complete behavioral source lock | fail-closed behavioral helper |
| `7c1f274` | test(perf): specify passive measurement validity contract | RED telemetry/assessor contract |
| `7d89ebd` | feat(perf): add passive postgres wait telemetry | collector, runner and assessor |
| `7dca971` | test(perf): validate passive telemetry isolation and bounds | integration/frequency validation |
| `1c87fb2` | docs(perf): preregister passive measurement qualification | immutable protocol before run |
| `4f6e4ca` | ci(perf): add passive measurement qualification workflow | read/measure/preserve split |
| `ee03a13` | test(perf): reproduce psycopg telemetry wildcard failure | RED for literal-percent bug |
| `0915c10` | fix(perf): escape telemetry query wildcards | production telemetry code lock |
| `2180646` | docs(perf): preregister telemetry integration fix | immutable fix addendum |
| `0b68539` | ci(perf): bind telemetry workflow to integration fix | update code/source identity |
| `16bc33b` | ci(perf): trigger passive measurement qualification | first formal trigger |
| `bb8366a` | evidence(perf): preserve ...31420616109-1 | preserve failed preflight evidence |
| `d4778dc` | fix(ci): use uv for measurement preflight check | use `uv pip check` in uv venv |
| `aa8b29c` | ci(perf): retrigger passive measurement after preflight fix | second and final trigger |
| `2959ccd` | evidence(perf): preserve ...31421039618-1 | preserve exact 4+4 evidence |

The final `docs(perf): record measurement-system verdict` commit follows this chain and is reported
by the final Git handoff. The preregistration and evidence commits were not squashed.

## 18. FINAL DECISION

```text
PERFORMANCE_ATTRIBUTION_STOPPED_BY_MEASUREMENT_VALIDITY
```

No Candidate 4 design is produced. No Observer v4, async observer, eBPF candidate, frequency sweep,
extra repetition, threshold adjustment or scheduler modification follows. Documentation and learning
are the terminal actions for this performance-attribution direction.

This result is an engineering success in evidence discipline: the project rejected its own
instrument because it could not demonstrate sufficiently low perturbation.
