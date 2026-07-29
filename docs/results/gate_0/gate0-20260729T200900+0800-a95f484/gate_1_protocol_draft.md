# Gate 1 protocol draft: 500-case Worker scaling

Status: draft only. It does not authorize a formal run.

Baseline binding: `a95f484d0d2e0f659a442efa5b8d4ad6ddece644`

## Question and evidence boundary

The experiment asks: on one controlled Compose host, how do throughput, latency, queueing,
database contention, and resource use change as Worker count moves through 1/2/4/8?

It may support a controlled single-host capacity curve. It must not be described as a
production throughput claim, distributed resilience result, or exactly-once guarantee.

## Preconditions

Before any measured arm:

1. The user approves a success/adoption gate. Correctness invariants below are fixed and
   cannot be weakened automatically; performance thresholds are user-owned.
2. Docker/Compose, PostgreSQL, and Redis are available on an exclusive experiment host.
3. Runtime versions, image digests, Compose config, CPU, memory, disk, limits, and baseline
   SHA are captured.
4. Ruff, mypy, non-integration tests, real-service integration, Alembic online head, and
   Compose smoke pass on that host.
5. Host power mode and competing workload are fixed and recorded.
6. A dry run of at most 20 cases validates the collector. It is not a warm-up or measured
   result and is preserved separately.
7. RED contracts prove that the collector refuses overwrite, detects missing samples, and
   fails an arm when correctness reconciliation fails.

If a prerequisite fails, preserve it under a fresh run ID and stop. Do not start the
500-case matrix.

## Frozen dataset and workloads

Create one canonical UTF-8 JSONL Dataset Version with exactly 500 ordered case IDs
`load-0000` through `load-0499`. Save:

- raw JSONL;
- byte count;
- SHA-256;
- Dataset Version ID and server-reported digest;
- schema and generator version;
- source commit.

Use deterministic `MockTarget` with two named profiles in case metadata:

- `io_latency`: every case succeeds after a fixed 50 ms delay;
- `transient_5pct`: the same delay, with exactly 25 preselected case IDs failing with HTTP
  503 on attempt 1 and succeeding on attempt 2.

The 25 cases are selected by a documented deterministic rule and written into the dataset,
not sampled during execution. `max_attempts=3`; retry/backoff/jitter configuration is frozen
in the arm manifest. If 50 ms is changed after the collector dry run, freeze the new value
before the first measured arm and create a new protocol revision and run ID.

Warm-up uses a separate, clearly named 50-case Dataset Version with its own hash. It runs
once after every Worker scaling change and is excluded from summaries.

## Matrix and order

Measured factors:

- workload: `io_latency`, `transient_5pct`;
- Workers: 1, 2, 4, 8;
- repetitions: 3 per workload/Worker pair;
- total measured arms: 24.

Generate the complete arm order once with a recorded PRNG algorithm and seed. Reject an
order containing all three repetitions of one Worker count consecutively. Save the order
before execution. Never reorder after seeing results.

For every arm:

1. scale Worker replicas;
2. verify the exact replica count and health;
3. wait for queue depth/running jobs to return to zero;
4. run the excluded 50-case warm-up;
5. confirm the warm-up reconciles;
6. start collectors;
7. submit one measured Run against the frozen 500-case Dataset Version;
8. collect until terminal or the fixed deadline;
9. stop collectors and reconcile PostgreSQL;
10. preserve success, failure, timeout, and partial evidence alike.

No `sleep` is used to decide correctness. Polling uses explicit state/deadline conditions.
The only fixed wait is MockTarget's declared workload latency.

## Measurement definitions

- End-to-end latency: server acceptance timestamp to first observation of terminal Run
  state. Also preserve client request timing separately.
- Throughput: terminal Jobs divided by the measured interval; report successful-result
  throughput separately.
- Case latency: persisted `CaseResult.latency_ms`; p50/p95/p99 use the repository's linear
  interpolation definition.
- Queue wait: first Job `started_at - created_at`; retry queue waits are reported separately
  from Attempt boundaries.
- Claim latency: duration of the `job.claim` database operation, not the polling interval.
- DB transaction latency: claim/result/failure/reaper transaction durations as separate
  series.
- DB lock wait: sampled `pg_stat_activity.wait_event_type='Lock'` plus `pg_locks` blockers.
  If continuous duration cannot be derived, report sample counts and windows as
  `DIRECTIONAL`, not milliseconds.
- Retry count: sum of durable Attempt counts minus one, reconciled with retry metrics.
- Duplicate result count: PostgreSQL counts grouped by both `job_id` and `(run_id, case_id)`;
  API row uniqueness alone is insufficient evidence.
- Stale submission rejection: stable rejection events/counter if induced. If the workload
  induces none, record zero observed and `NOT_TESTED`; do not call zero proof of fencing.
- CPU/RSS: per-container one-second samples, including API, every Worker replica, Reaper,
  PostgreSQL, and Redis.
- PostgreSQL connections: one-second active/idle/idle-in-transaction counts.
- Redis publish failures: per-process counter deltas with every Worker replica scraped.
- Completion status: final Run and every Job status from PostgreSQL.

Clock source, timestamp precision, sample interval, missed-sample count, and collector
overhead must be included in the manifest.

## Correctness acceptance

Every measured arm must satisfy:

1. all 500 Jobs reach an explainable terminal state before the fixed deadline;
2. every succeeded Job has exactly one durable CaseResult;
3. no Job and no `(run_id, case_id)` has duplicate CaseResults;
4. Run counters equal a fresh PostgreSQL group-by of Job states;
5. Attempt sequence and retry counts reconcile;
6. no unexplained running/cancelling Job remains;
7. the final Run status is consistent with Job aggregation;
8. Redis publication failure never rolls back durable Job/Run state;
9. the arm is bound to environment, dataset hash, config hashes, image digests, and commit.

A correctness failure invalidates the arm for capacity comparison but does not delete it.
Performance may regress at higher Worker counts; the negative scaling point is a required
result.

## Raw collection

Each arm preserves:

- API submission/terminal snapshots and all case pages;
- PostgreSQL reconciliation queries and results;
- `pg_stat_activity`/`pg_locks` samples;
- Prometheus text snapshots from API, every Worker, and Reaper;
- container CPU/RSS samples and replica inventory;
- structured log excerpts keyed by run/job/attempt IDs;
- collector gaps/errors;
- timestamps and command exit codes.

The current repository exposes no claim-duration, transaction-duration, connection-count,
or resource-sampling experiment stream. Before a formal run, Gate 1 therefore needs
test-first measurement harness work. Observability-only additions may be proposed, but
production semantics remain unchanged.

## Immutable output layout

Use a fresh, collision-resistant run ID:

```text
docs/results/load/<run_id>/
  manifest.json
  protocol.md
  dataset/
    measurement.jsonl
    warmup.jsonl
    hashes.json
  arm_order.json
  raw/
    <arm_id>/
      api.json
      cases.jsonl
      postgres.jsonl
      prometheus/
      resources.jsonl
      logs.jsonl
      commands.jsonl
  summary/
    arms.csv
    aggregate.json
  failures/
    index.json
  plots/
    throughput.png
    latency.png
    queue_and_claim.png
    db_wait.png
    cpu_rss.png
```

All writers use create-new semantics. A rerun always gets a new run ID. Summary generation
reads raw files and never mutates them.

## Required plots and reporting

Report every repetition as points and median/range as overlays; do not show only the best
run. Required views:

- throughput versus Worker count by workload;
- end-to-end and case p50/p95/p99;
- queue wait and claim latency;
- lock-wait windows and PostgreSQL connections;
- CPU/RSS by process;
- retry, duplicate, stale-rejection, Redis-failure, and terminal-state table.

Any capacity knee is a user-reviewed interpretation. The report supplies raw points and
candidate explanations; it does not automatically change the success/adoption gate.

## Gaps in the current `run_load_test.py`

The current script is an entry point, not yet this protocol:

- one workload and one pass per Worker count;
- fixed sequential order and no separated warm-up;
- no saved Dataset hash or runtime/image manifest;
- no p99, queue/claim/transaction/lock measurements;
- no CPU/RSS, PostgreSQL connection, per-replica Prometheus, or collector-gap samples;
- duplicate detection relies on API case IDs rather than durable SQL reconciliation;
- stale rejection is not induced or classified;
- output is one flat JSON file rather than the required immutable evidence tree.

These gaps must be closed with RED contracts before the first formal 500-case arm.
