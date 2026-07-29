# Gate 1 Worker scaling protocol

This file is copied byte-for-byte into every prepared evidence directory. Its SHA-256 is
recorded in that run's immutable manifest.

## Scope

Measure a controlled, single-host Compose deployment with 1, 2, 4, and 8 Worker replicas.
The result is not a production-capacity, distributed-resilience, or exactly-once claim.
Negative scaling is a valid result and must be retained.

## Frozen defaults

- Measurement dataset: 500 deterministic `load-*` cases.
- Warm-up dataset: 50 deterministic `warmup-*` cases, excluded from summaries.
- Workloads: `io_latency_v1` and `transient_5pct_v1`.
- MockTarget fixed delay: 25 ms.
- Transient workload: deterministic 5% first-attempt HTTP 503 failures.
- Worker counts: 1, 2, 4, 8.
- Repetitions: 4, with every Worker count occupying every within-block position once.
- Arm block order: deterministic SHA-256 order using recorded seed 1729.
- Collector interval: 1 second.
- Arm deadline: 900 seconds.

CLI overrides must be recorded in the manifest and create a new run ID. A measured run
must never overwrite another run.

## Execution

For each arm: verify the requested replica count and health; wait for an empty queue; run
and reconcile the excluded warm-up; start collectors; submit the 500-case run; wait on
terminal state or deadline; stop collectors; query PostgreSQL; reconcile; preserve raw
success, failure, timeout, and partial evidence.

Correctness is decided from durable Run, Job, Attempt, and CaseResult rows. API rows alone
cannot prove uniqueness. Missing measurements are `UNKNOWN`; a behavior that was not
induced is `NOT_TESTED`; sampled lock waits without continuous timing are `DIRECTIONAL`.

## Frozen plots

The formal finalization step must create all five PNG files together:
`throughput.png`, `latency.png`, `queue_and_claim.png`, `database.png`, and
`cpu_and_rss.png`. It must also create `plots/manifest.json` with every plotted arm,
line grouping, evidence state, renderer version, non-interactive backend, and DPI.

Lines are grouped by workload and repetition, ordered by Worker count, and never connect
different repetitions. Case latency and end-to-end duration use separate y axes. CPU and
RSS use separate y axes. Missing values remain absent/`UNKNOWN`, not zero. Plot files and
the manifest are create-new evidence and must never be partially overwritten.

The renderer is the Matplotlib version resolved by the run's source commit and `uv.lock`,
using the non-interactive `Agg` backend at 144 DPI. Matplotlib is a development dependency
and is excluded from the production image by `UV_NO_DEV=1`.

## Correctness gate

Every measured arm must contain exactly the expected Job rows, exactly one CaseResult for
each succeeded Job, no duplicate result by `job_id` or `(run_id, case_id)`, contiguous
Attempt numbers matching `attempt_count`, Run counters matching a fresh Job group-by, no
unexplained nonterminal Job, and a Run terminal state consistent with Job aggregation.
Any violation makes the arm ineligible for capacity comparison without deleting it.

## Adoption gate

The harness never changes the deployed Worker count automatically. It reports all raw
repetitions and candidate interpretations. A human must review correctness, evidence
completeness, throughput, p95/p99 latency, database waits, and resource headroom before
selecting a deployment value.
