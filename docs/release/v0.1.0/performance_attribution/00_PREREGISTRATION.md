# Performance Attribution Preregistration

## Status and scope

- Preregistered on: 2026-08-10 (Asia/Shanghai)
- Scheduler-behaviour baseline SHA: `c5e8368e6588b7684a87e44d15c99e0d320744a7`
- Target branch: `codex/evidence-gate-1`
- Release state at registration: `NOT_READY_TARGETED_NEGATIVE_SCALING`
- Scheduler behaviour candidate budget: **0**
- Allowed change: low-intrusion diagnostic instrumentation and evidence tooling only
- Forbidden change: scheduler policy, fair-round semantics, workload, threshold, repetitions,
  Worker levels, queue size, claim batch, connection pool, retry/backoff, lease duration, or
  historical evidence

The experiment source SHA cannot be its own preregistration commit. Therefore the exact
instrumentation commit SHA will be written to `01_SOURCE_LOCK.md` immediately after the
instrumentation-only commit and before any overhead or attribution measurement. Every measured
arm must report that exact SHA. The scheduler-behaviour baseline above must remain an ancestor,
and the intervening production-code diff is limited to optional observation hooks plus the already
qualified locked-Job false-empty fix. Any other production behaviour drift stops the experiment.

## Preserved observed facts

The immutable targeted run `31352270523` remains the release decision input. Its formal medians
are not replaced by this diagnostic experiment:

| Distribution | w4 Jobs/s | w8 Jobs/s | w8/w4 | Formal status |
| --- | ---: | ---: | ---: | --- |
| single Tenant | 24.190086 | 18.929004 | 0.782511 | NEGATIVE_SCALING |
| balanced | 44.752825 | 34.584871 | 0.772797 | NEGATIVE_SCALING |
| 20:1 | 32.700255 | 26.036396 | 0.796214 | NEGATIVE_SCALING |
| many-small | 42.245796 | 42.839905 | 1.014063 | VERIFIED |

The formal scaling gate remains `w8_median / w4_median >= 0.95` for every distribution. This
instrumentation experiment cannot change release readiness even if it produces a faster run.

## Frozen workload contract

- Queue size (`q`): 1,000
- Claim batch: 1
- Worker levels: 1, 2, 4, 8
- Distributions: `single_tenant`, `balanced_multi_tenant`, `skew_20_to_1`,
  `many_small_tenants`
- Formal attribution repetitions: exactly 4 observations per `(distribution, Worker)` group
- Runner, PostgreSQL and service topology: same contract as final-scheduler targeted qualification
- Scaling threshold and median calculation: unchanged

A smoke run may validate plumbing but is not admissible for H1/H2/H3 or release claims.

## Claim-phase measurements

Instrumentation must distinguish these monotonic-clock boundaries where the real transaction
structure permits it:

1. claim entry;
2. scheduler coordination/generation acquisition start and completion;
3. Tenant permit selection start and acquisition;
4. Job row selection start and acquisition/skip;
5. Job and Attempt mutation completion;
6. durable claim-sequence coordination lock start and update completion;
7. transaction completion and claim return.

Per arm, preserve p50/p95/p99 for:

- `scheduler_coordination_wait_ms`
- `tenant_permit_wait_ms`
- `job_row_wait_ms`
- `durable_sequence_wait_ms`
- `transaction_commit_ms`
- `claim_total_ms`

Also preserve counts or per-success rates for claim retries, waiting fallbacks, Tenant turns without
a Job, `empty_while_eligible`, permit outcomes, round creation, generation advance and Job
`SKIP LOCKED` misses. Fine-grained samples belong in experiment artifacts, not Prometheus labels;
Tenant, Job, Run and Attempt IDs must not become metric labels.

## Instrumentation overhead gate

Before formal attribution, run one representative frozen arm:

- distribution: `skew_20_to_1`
- queue: 1,000
- claim batch: 1
- Workers: 8
- repetitions: 3 OFF and 3 ON
- same exact source, runner and PostgreSQL environment

Report all six observations plus medians for throughput, claim p95, Worker CPU and peak RSS.
Instrumentation is `VALID` only when both conditions hold:

- absolute median throughput regression is at most 5%; and
- absolute median claim-p95 change is at most 10%.

CPU/RSS differences are reported but are not an unregistered pass/fail escape hatch. Exceeding
either frozen threshold yields `INSTRUMENTATION_TOO_INTRUSIVE` and stops formal attribution.

## Preregistered hypotheses

### H1 — SchedulerCoordination singleton contention

`SUPPORTED` requires, in at least two currently failing distributions, w8 singleton coordination
wait per success at least 2x w4 and that stage explaining at least 25% of the claim-latency increase,
while many-small lacks an equivalent signature. Otherwise use `NOT_SUPPORTED`; contradictory or
insufficient data is `INCONCLUSIVE`.

### H2 — Tenant permit contention

`SUPPORTED` requires stable w8-versus-w4 Tenant-permit wait growth whose magnitude is greater for
single/balanced/20:1 than for many-small. A missing low-Tenant-cardinality contrast rejects the
hypothesis; contradictory or insufficient observations are `INCONCLUSIVE`.

### H3 — SKIP LOCKED/retry feedback

`SUPPORTED` requires w8/w4 Job `SKIP LOCKED` misses per success at least 2x together with growth in
retry, waiting fallback and claim latency. Near-zero misses reject H3. Contradictory or incomplete
measurements are `INCONCLUSIVE`.

Multiple hypotheses may be supported. No hypothesis is promoted from correlation to a proven
root cause by this experiment alone.

## Stop rule

Stop without auto-fixing or continuing the same formal experiment if any of these occurs:

1. lost, duplicate durable result, orphan, Attempt mismatch, stale accepted outcome or illegal
   transition count is nonzero;
2. `empty_while_eligible` is nonzero;
3. source SHA, workload, threshold or repetition drift;
4. manifest or independently parsed raw EXPLAIN mismatch;
5. instrumentation overhead exceeds its frozen budget;
6. either historical evidence tree changes;
7. instrumentation cannot distinguish the registered stages without changing scheduler behaviour.

The stage ends after a bounded evidence package and H1/H2/H3 attribution. It does not implement a
new scheduler candidate, merge PR #1, mark it Ready, create a tag/release, run downstream release
qualification or announce v0.1.0 READY.
