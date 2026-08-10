# Passive PostgreSQL telemetry contract

## Architecture and isolation

The benchmark process creates Workers and fixtures normally. For ON repetitions it launches
`python -m scripts.postgres_wait_telemetry` as a separate operating-system process. The child opens
its own psycopg connection, sets that session read-only, announces readiness, and waits for a start
signal. The parent emits the signal immediately before the measured Worker period and emits a stop
signal immediately after it. OFF repetitions do not launch the child.

Collector startup, query or shutdown failure is converted to public error metadata. It is not
raised through the Worker claim path. The workload may finish, but any nonzero telemetry error makes
the measurement assessment invalid. This enforces `measurement failure != workload failure` while
still failing the evidence claim closed.

The existing synchronous `phase_observer` path is disabled for all eight repetitions. It remains
only for historical reproduction/local debugging and is `RETIRED_FOR_FORMAL_ATTRIBUTION`.

## Database contract

The collector uses one fixed parameterized SELECT over PostgreSQL core catalogs only:

```text
pg_catalog.pg_stat_activity
LEFT JOIN pg_catalog.pg_locks
LEFT JOIN pg_catalog.pg_class
```

The only parameter is the fixed row bound used by `LIMIT %s`. Relation, PID, query, Tenant, Run, Job
and Attempt values are never interpolated into SQL. The collector does not terminate/cancel a
backend, acquire or alter workload locks, run ANALYZE/VACUUM, change database parameters, or install
`pg_stat_statements`, `auto_explain`, `pg_wait_sampling` or any other extension.

The public projection contains only timestamp, PID, state, wait event type/name, backend type,
MD5 query fingerprint, safe query category, lock type/mode/granted state and safe relation name.
Categories are `scheduler_coordination_lock`, `tenant_permit_selection`, `job_selection`,
`durable_sequence_update` and `other`.

## Frequency and bounds

- Frozen frequency: **5 Hz**
- Interval: **0.2 seconds**
- Maximum projected rows per sample: **256**
- Maximum samples per repetition: **10,000**
- Output: one JSON object per sample, appended and flushed immediately to JSONL
- In-memory state: scalar aggregates plus a bounded set constrained by the row/sample maxima

The query requests at most 257 rows so one-row overflow can be detected without unbounded fetch.
Rows beyond 256 increment both drop and overflow evidence. Falling behind the fixed schedule
increments dropped samples. Reaching the total sample cap before stop increments drop and overflow.
No whole-experiment event list is accumulated in RAM.

Every summary records frequency, interval, successful samples, wait-bearing samples, distinct
observed waiting backend PIDs, rows written, query-latency mean/max, errors, drops, overflow and
elapsed time. Any error, drop or overflow is disqualifying.

## Public-data boundary

Raw `pg_stat_activity.query`, query parameters, DSNs, passwords, tokens, Tenant IDs, Run IDs, Job IDs
and Attempt IDs are not persisted. The projection is an explicit allowlist, so adding a sensitive
key to a database row cannot make it public. Exception messages are not persisted; only exception
class names are recorded. Child stdout/stderr are discarded. The workflow uploads only the named
experiment evidence root and does not upload `.env` files or the repository.

The query fingerprint is a one-way MD5 identifier for grouping only, not a secrecy guarantee for a
small known query universe. The artifact therefore also stores a coarse safe category and never the
underlying text.

## Interpretation limits

Sampling-based telemetry observes sufficiently long-lived waits visible at sample time; it is not
an exhaustive event trace. Short waits may occur entirely between 0.2-second samples. A sampled
wait proves that the backend exposed that state at the sample instant; it does not prove causal
dominance, total wait time, or that a specific lock is the scaling root cause. Query fingerprints
and categories may group statements but do not establish H1, H2 or H3.

Consequently even a valid 4+4 qualification authorizes only a future separately preregistered
attribution experiment. It does not make any causal claim and does not change release readiness.

