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

Only manifest schema v6 is executable. Before any service or arm interaction, the
executor must revalidate the source commit, strict Git state, Docker build-context
safety, configuration, measurement and warm-up datasets, dataset hash record, protocol,
arm plan, Compose file, Dockerfile, `.dockerignore`, every key execution script, and the
Docker build-context fingerprint.

Schema v6 also freezes result schema v4 and quality policy v1,
`all_expected_arms_valid_for_capacity_comparison`, as automatic and non-waivable. The
adoption decision, performance thresholds, and deployed Worker count remain human-owned.
The `--confirm-quality-gate` and `--confirm-adoption-gate` switches authorize a formal
run; they are not result evidence and cannot replace the automatic final evaluation.

The strict Git gate rejects every tracked or staged change, including changes to paths
excluded from Docker. Untracked and Git-ignored files block only when the root
`.dockerignore` would include them in the context. Git paths are read through NUL-delimited
machine interfaces so quoting, spaces, non-ASCII names, and rename syntax cannot change
the recorded path.

The root `.dockerignore` contract handles UTF-8 BOM removal, first-column comments,
component globs, standalone `**` components, and last-match negation. A compound `**`
inside another component is outside the audited subset and fails closed. A
Dockerfile-specific ignore file also fails closed because Docker gives it precedence
over the root file while the manifest binds the root file. Included Git symlinks and
included `.env*` paths are unsafe; only excluded local environment overrides are allowed.

`docker-context-sha256-v2` hashes a canonical ordered list of every included regular-file
path, kind, byte length, and content SHA-256 (and records a symlink target only so the
audit can reject it). It is an application evidence binding, not a claim that the value
is Docker or BuildKit's internal tar/context digest.

Preparation has one bounded Docker side effect: from a clean build context it builds the
human-readable `ai-evalops-platform:phase9` reference with OCI revision/source/created
labels plus Dockerfile, build-context, and Python-version labels. It inspects the result,
records the immutable local `sha256:...` image ID, OS, architecture, Python runtime, and
all cross-bound metadata in the manifest. Before and after `docker build`, preparation
reruns the complete context audit and verifies that repository `HEAD` still equals the
manifest source commit. Preparation does not start Compose services, upload a Dataset,
scale a Worker, or start a formal arm.

A local image ID is reported only as `LOCAL_IMAGE_ID_VERIFIED`; it is never described as
a registry digest. Before execution, the preflight inspects the exact running
API/Worker/Reaper containers returned by the frozen Compose project. Every application
container must use the manifest image ID and carry matching revision, Compose project,
Dockerfile, and build-context labels. A mutable tag match by itself is insufficient.

The preflight outcome is one of `READY`, `HASH_MISMATCH`, `SOURCE_MISMATCH`,
`DIRTY_BUILD_CONTEXT`, `UNSAFE_BUILD_CONTEXT`, `MANIFEST_INVALID`, `ENVIRONMENT_BLOCKED`,
`IMAGE_IDENTITY_KIND_UNSUPPORTED`, `IMAGE_ID_MISMATCH`,
`IMAGE_REVISION_LABEL_MISSING`, `IMAGE_REVISION_MISMATCH`,
`COMPOSE_PROJECT_MISMATCH`, or `IMAGE_BUILD_INPUT_MISMATCH`, with all failed checks
retained. Schema v1/v2/v3/v4 bundles remain historical, read-only evidence and must be
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

New Gate 1 result artifacts use result schema v4. Embedded Prometheus evidence continues
to use its independent schema v2: every Prometheus-derived metric records `status`,
`observation`, `value`, `reason`, `source`, and `sample_count`; the legacy `evidence`
field remains present for evidence strength and read compatibility.

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

## Worker cluster resource semantics

Every Docker stats call is one explicit snapshot. The collector must bind the full Docker
container ID and actual name to Compose `ID`, `Name`, and `Service` metadata; service
identity must never be inferred from a container-name pattern. A snapshot is complete only
when every Compose experiment container is returned exactly once with a matching identity.

Within each snapshot, CPU percent and RSS bytes are summed only across containers whose
Compose service is `worker`. Distributions and peaks are then derived from those snapshot
totals. Per-container peaks may be retained for diagnosis, but they must never be summed
across different timestamps or used as the Worker-cluster value. API, Reaper, PostgreSQL,
and Redis samples must not contribute to Worker-cluster totals.

The frozen arm plan supplies the expected Worker count. A missing Worker replica makes
resource evidence `UNKNOWN` with null values; a duplicate, invalid, or over-counted Worker
sample makes it `FAILED` with null values. Any non-`VERIFIED` Worker resource evidence makes
the arm ineligible for capacity comparison. Missing evidence must never be converted to
zero.

## Frozen plots

The formal finalization step must create all five PNG files together:
`throughput.png`, `latency.png`, `queue_and_claim.png`, `database.png`, and
`cpu_and_rss.png`. It must also create `plots/manifest.json` with every plotted arm,
line grouping, evidence state, renderer version, non-interactive backend, and DPI.

Lines are grouped by workload and repetition, ordered by Worker count, and never connect
different repetitions. Case latency and end-to-end duration use separate y axes. Worker-
cluster CPU and RSS peaks use separate y axes. Missing values remain absent/`UNKNOWN`, not
zero. Plot files and the manifest are create-new evidence and must never be partially
overwritten.

The renderer is the Matplotlib version resolved by the run's source commit and `uv.lock`,
using the non-interactive `Agg` backend at 144 DPI. Matplotlib is a development dependency
and is excluded from the production image by `UV_NO_DEV=1`.

## Frozen final-bundle publication

Root-level `raw/<arm_id>/` and `summary/<arm_id>.json` are execution-time working
evidence. Their presence does not mean that a formal result was published. The only
published result is the complete `<run_id>/final/` directory.

Finalization uses final-bundle schema v1 while the enclosed result artifacts use result
schema v4. These are independent version axes: the bundle schema describes
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

The final aggregate evaluates the frozen expected arm plan rather than only the summaries
that happen to exist. Any invalid arm yields quality status `FAILED`; missing expected
arms without a known invalid arm yield `UNKNOWN`; complete valid evidence yields
`VERIFIED`. Duplicate, unexpected, or identity-mismatched arms fail closed. Negative
scaling remains evidence for human review and does not by itself fail correctness.

## Adoption gate

The harness never changes the deployed Worker count automatically. It reports all raw
repetitions and candidate interpretations. When objective quality is `VERIFIED`, it may
mark the bundle `READY_FOR_HUMAN_REVIEW`; this is not an adoption decision. The adoption
status remains `NOT_RUN`, and both the automatic decision and selected Worker count remain
null. A human must review correctness, evidence completeness, throughput, p95/p99 latency,
database waits, and resource headroom before selecting a deployment value.
