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

## Prepared evidence gate

Only manifest schema v2 is executable. Before Docker or any arm interaction, the
executor must revalidate the source commit, tracked workspace state, untracked or
Git-ignored files that would enter the Docker build context, configuration, measurement
and warm-up datasets, dataset hash record, protocol, arm plan, Compose file, Dockerfile,
`.dockerignore`, and every key execution script.

The preflight outcome is one of `READY`, `HASH_MISMATCH`, `SOURCE_MISMATCH`,
`DIRTY_BUILD_CONTEXT`, `MANIFEST_INVALID`, or `ENVIRONMENT_BLOCKED`, with all failed
checks retained. Schema v1 bundles remain historical, read-only evidence and must be
prepared again rather than migrated or silently rewritten.

## Execution

For each arm: verify the requested replica count and health; wait for an empty queue; run
and reconcile the excluded warm-up; start collectors; submit the 500-case run; wait on
terminal state or deadline; stop collectors; query PostgreSQL; reconcile; preserve raw
success, failure, timeout, and partial evidence.

Correctness is decided from durable Run, Job, Attempt, and CaseResult rows. API rows alone
cannot prove uniqueness. Missing measurements are `UNKNOWN`; a behavior that was not
induced is `NOT_RUN`; sampled lock waits without continuous timing are `DIRECTIONAL`.

## Prometheus evidence semantics

New Gate 1 result artifacts use result schema v2. Every Prometheus-derived metric records
`status`, `observation`, `value`, `reason`, `source`, and `sample_count`; the legacy
`evidence` field remains present for evidence strength and read compatibility.

- `OBSERVED_ZERO` means the same finite series existed in paired before/after scrapes and
  its cumulative delta was exactly zero. It is `VERIFIED` with numeric value `0`.
- `OBSERVED_VALUE` means the paired finite series had a positive delta.
- `MISSING` means a successful scrape did not contain every required paired series. It is
  `UNKNOWN` with `value: null`; zero must never be substituted.
- `COLLECTION_FAILED` means the endpoint request, exposition parsing, uniqueness check,
  finite-number check, or frozen label contract failed. Its value is always `null`.

Claim and result database-operation histograms must be complete on every Worker source.
The unlabelled Redis publication-failure counter must be complete on every scraped
API/Worker/Reaper source. These are required comparison evidence: a missing or failed
required metric makes the arm ineligible for capacity comparison.

Failure histograms on Workers and reaper histograms on Reapers are event-conditional and
optional. Their absence or collection failure remains `UNKNOWN` and does not by itself
invalidate otherwise complete required evidence.

Endpoint failures are preserved beside raw `.prom` files as machine-readable reason
codes. Result schema v1 artifacts remain read-only: a historical `VERIFIED 0` cannot be
reliably migrated because v1 did not retain whether the source series was observed.

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

## Frozen final-bundle publication

Root-level `raw/<arm_id>/` and `summary/<arm_id>.json` are execution-time working
evidence. Their presence does not mean that a formal result was published. The only
published result is the complete `<run_id>/final/` directory.

Finalization uses final-bundle schema v1 while the enclosed metric artifacts continue to
use result schema v2. These are independent version axes: the bundle schema describes
layout, hashes, and publication; the result schema describes metric meaning.

The finalizer must:

1. acquire the run-local finalization lock and reject an existing `final/` target;
2. create staging on the same filesystem as the run directory;
3. copy every raw arm directory and matching per-arm summary into staging;
4. write aggregate JSON and CSV, all five PNG files, and the plot manifest in staging;
5. write `final/manifest.json` metadata in staging with every payload path, byte size,
   and SHA-256 digest;
6. re-read the manifest and independently validate the exact file count, required paths,
   schemas, arm cross-references, PNG signatures, byte sizes, and every SHA-256 digest;
7. recheck the formal target and publish with one same-filesystem atomic directory rename.

Any build, render, write, hash, validation, conflict, or rename failure must remove
staging and leave no new formal bundle. Existing partial or complete `final/` directories
are immutable conflicts and must remain byte-for-byte unchanged. Concurrent finalizers
must not publish twice.

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
