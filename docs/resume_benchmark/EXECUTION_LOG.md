# Evidence-gate execution log

## 2026-08-07 — Source freeze and feasibility audit

### What changed

- Switched from `codex/gate1-evidence-hardening` to the requested
  `codex/evidence-gate-1` branch.
- Fast-forwarded the target branch from `f6a3a28` to `18f995e` and pushed the alignment to GitHub.
- Added a dedicated worker-scaling evidence workflow and evidence index skeleton.

### Why

The target branch was 108 commits behind the completed hardening branch. A fast-forward preserves a
linear history and exact commit identity; a merge commit or rebase would create an unnecessary new
source identity before measurement.

The local host has no Docker CLI. A GitHub-hosted Linux runner is already proven by `compose-smoke`
to support this repository's real Compose topology, so it is the least invasive available execution
environment.

### Problems encountered and decisions

1. The first Docker probe terminated as `CommandNotFound`. The follow-up probe used
   `Get-Command -ErrorAction SilentlyContinue` and confirmed absence without changing the host.
2. A document was first read from an outdated path. Repository discovery found the current path under
   `docs/results/`.
3. Recursive PowerShell file discovery crossed pytest temp directories with denied ACLs. The audit was
   repeated with bounded ripgrep patterns.
4. The old fault script was initially a candidate for the requested matrix. Line-by-line audit showed
   only four scenarios and insufficient durable reconciliation, so it was rejected as final evidence.

### Expected effect

The dedicated workflow prepares the protocol on a clean commit, builds and labels the exact image,
starts PostgreSQL/Redis/API/Worker/Reaper, executes 32 balanced arms (two workloads, four worker
counts, four repetitions), preserves failures and diagnostics, uploads the artifact, and commits the
evidence directory. The workflow is triggered only by its workflow file or explicit trigger file, so
the evidence commit does not recursively launch another experiment.

### Baseline outcome

GitHub Actions run `31174201772` completed successfully against source SHA `18f995e`:
`compose-smoke` completed at `11:29:02Z`, and `quality-and-integration` completed at `11:30:37Z`.
This closes the pre-experiment quality baseline without claiming any capacity result.

## 2026-08-07 — First formal run and evidence-transport defect

### What ran

GitHub Actions run `31174970193` executed all 32 balanced load arms and committed raw evidence as
`gate1-gh-31174970193-1` in commit `eb7f85c`. Every workflow step completed successfully.

### Problem found after pull

Independent local validation of the committed `final/` directory failed on `summary/arms.csv`.
The finalizer wrote CSV rows with the platform-default CRLF terminator and hashed 4100 bytes. During
`git add`, `.gitattributes` (`* text=auto eol=lf`) normalized the 33 lines to LF, leaving a 4067-byte
repository blob. The manifest therefore no longer authenticated the bytes transported by Git.

### Why the run is not reported

Workflow success proves execution completion, not post-transport immutability. Because the checked-out
bundle cannot pass its own SHA-256 validation, all load numbers from this run are withheld and the run
is classified `INVALID-AFTER-GIT-TRANSPORT`.

### Fix and effect

A regression test first reproduced CRLF output through the public finalization function. The CSV
writer now specifies LF explicitly. The new test and all 17 finalization/plot tests pass. A second
formal run is scheduled; only its checked-out bundle may become the reporting source.

## 2026-08-07 — Second formal run and zero-series metrics defect

### Outcome

Run `gate1-gh-31176423383-1` was committed as `6883b552`. Independent post-Git validation succeeded:
the bundle is `complete`, contains 664 hashed payload files, and contains all 32 expected arms.

The automatic capacity quality gate still rejected exactly eight deterministic 4/8-worker arms. In
each rejected arm, one or more idle workers exposed no `operation="result"` histogram at all. The
collector correctly treated absence as `UNKNOWN`; it did not invent zero.

### Decision and fix

Changing the collector to interpret any missing series as zero would hide instrumentation failures.
Instead, `PlatformMetrics` now creates the four fixed, low-cardinality database-operation histogram
children at process startup. A process with no observations therefore exposes an explicit zero count,
while a failed scrape or truly absent metric remains `UNKNOWN`. Unit coverage verifies both the
startup exposition and multi-worker busy/idle aggregation. A third formal run is required.

## 2026-08-07 — Third formal run accepted

### What ran

GitHub Actions run `31177702100` built the image from frozen source `15e7ac2`, started the real
PostgreSQL/Redis/API/Worker/Reaper Compose topology, and executed all 32 balanced arms. The evidence
bot committed `gate1-gh-31177702100-1` in `ab97e61`.

### Independent post-transport verification

After a fast-forward pull, local validation recomputed the committed bytes rather than trusting the
runner workspace. The final bundle is `complete`; all 664 payload hashes matched; all 32 planned arms
were present; the quality gate was `VERIFIED`; and zero arms were invalid.

Database reconciliation across 16,000 measured Jobs found 16,000 unique terminal successes, 400
expected retries, zero failures, zero lost or nonterminal Jobs, zero duplicate durable results, zero
binding mismatches, and zero collector gaps.

### Reporting decision and effect

A tested exporter now fails closed on missing/invalid arms, duplicates, nonterminal Jobs, binding
mismatches, collector gaps, or incomplete repetitions. It generated 32 per-arm rows and eight
all-repetition scaling rows. The report records the observed 3.1× 1-to-8 Worker speedup together with
the drop to about 39% parallel efficiency. It does not choose a Worker count automatically.

The load experiment did not induce an expired Worker submission. Therefore the report leaves stale
success/failure acceptance as `NOT_RUN`; résumé admission remains blocked until fault scenarios C and
D prove both accepted counts are zero.

### Validation problems encountered

1. The first exporter version used `csv.DictWriter`'s default CRLF terminator. Git warned that both
   generated CSV files would be normalized to LF. A RED byte-level regression test reproduced the
   mismatch; setting `lineterminator="\n"` made the test GREEN. The regenerated 33-line arm CSV and
   9-line scaling CSV contain no CRLF bytes.
2. An ad-hoc `mypy --strict app scripts tests` command treated unit-test files in separate namespace
   directories as duplicate top-level modules (`test_repository`). The repository's CI contract is
   `mypy app scripts tests/integration tests/concurrency`; rerunning that exact command passed 120
   source files. No mypy rule or application code was changed to hide the command mistake.

Final checkpoint validation: lock check passed; all repository files passed Ruff format and lint;
strict mypy passed 120 source files; the exporter/finalizer/collector focus set passed 44 tests; and
the complete non-integration suite passed `518 passed, 9 deselected` in 243.38 seconds.

## 2026-08-07 — A–I fault-matrix harness design

### Why the previous script was not extended superficially

The previous `scripts.run_failure_scenarios` stopped Redis/PostgreSQL and killed a Worker, but mainly
reported API final status. That cannot prove result uniqueness, contiguous attempts, zero lost Jobs,
or rejection of a write from an expired lease. Treating those four coarse scenarios as the requested
A–I matrix would have produced an attractive but unverifiable report.

The replacement uses two execution modes against the same real PostgreSQL schema:

- A/E/F/G/I disturb actual Compose services or submit concurrent HTTP requests;
- B/C/D/H stop autonomous Worker/Reaper containers, create Runs through the real API, and invoke the
  project's Claimer/Reaper/Committer services with a controlled logical clock. The clock removes a
  30-second wait but does not replace PostgreSQL locks, transactions, unique constraints, or fencing
  predicates.

Every record includes raw Run/Job/Attempt/CaseResult rows and a derived invariant verdict. C submits
a late success from Worker A after Worker B has reclaimed and committed; D does the same with a late
failure. Either accepted count makes both the record and the complete matrix fail.

### RED/GREEN work

1. Reconciliation tests first failed because `scripts.fault_matrix_evidence` did not exist. The new
   implementation counts terminal/nonterminal Jobs, retries, duplicate result keys, attempt gaps,
   stale accepts, and Run counter mismatches. Six tests passed after implementation.
2. Bundle tests first failed because `scripts.fault_bundle` did not exist. The finalizer now requires
   a verified complete A–I matrix, hashes every payload file, refuses overwrite, and detects byte
   tampering or file-set drift. The combined bundle/reconciliation set passes seven tests.
3. The old CLI-default test expected a single `lease_recovery_wait_seconds=40`. It correctly failed
   after the protocol changed. The contract now checks three repetitions, a three-second dependency
   outage, and 20 concurrent idempotent submissions. Source SHA can be parsed as `UNSPECIFIED` for
   help/tests but execution fails closed unless an exact SHA is supplied.

### Problems and corrections

- A broad test command included expensive prepared-evidence tests and reached the 184-second tool
  limit without an assertion failure. Focused tests isolated the changed contracts; the later full
  suite remains the final gate.
- Ruff found only mechanical import ordering and line wrapping; the project formatter fixed them
  without semantic changes.
- Redis recovery now requires at least one durable unpublished outbox row before Redis restarts, then
  waits for that Run's outbox to drain. This distinguishes actual outage recovery from a no-op stop.
- Direct lease scenarios propagate the same frozen source SHA into each API Run rather than relying
  only on workflow metadata.

### Expected formal evidence

The dedicated workflow runs 9 scenarios × 3 repetitions, retains runner and Compose diagnostics,
and commits both success and failure artifacts. Only a successful 27-record matrix receives a
`complete` SHA-256 manifest. Evidence commits do not retrigger the workflow because only the workflow
and its explicit trigger file are watched.

Pre-trigger validation passed: all 284 repository files passed Ruff format, lint passed, strict mypy
passed 123 source files, the focused fault/concurrency set passed 12 tests, and the complete
non-integration suite passed `525 passed, 9 deselected` in 272.29 seconds.

## 2026-08-07 — First formal A–I matrix and database reconnect baseline

### Formal result

GitHub Actions run `31181816878` executed source `da92532` and committed
`fault-gh-31181816878-1` as `7f0738d`. Independent validation after Git transport found a complete
five-payload bundle and 27/27 scenario/repetition records.

Across 84 Jobs: 84 were unique and terminal, 84 succeeded, 72 retries were recorded, and failed,
lost, duplicate-result, and orphan-running counts were all zero. Scenario C attempted three stale
results and accepted zero; scenario D attempted three stale failures and accepted zero. Dual Reapers
recovered 20 unique Jobs per repetition without overlap. Sixty concurrent duplicate-key HTTP requests
all succeeded and resolved to exactly one Run per repetition.

Observed recovery medians were: Worker kill 39.88 s; logical lease-expiry recovery operation 0.04 s;
Redis outbox drain after restart 0.01 s; PostgreSQL recovery 6.91 s; Worker restart 5.41 s; dual Reaper
recovery 0.31 s; and duplicate-key Run completion 0.62 s. Logical-clock B/C/D/H timings measure the
eligible database recovery transaction, not real lease-wall-clock waiting, and are labeled accordingly.

### Database resilience decision

PostgreSQL scenario F passed 3/3 with a three-second outage, no Worker restart, no Job retry, and no
correctness violation. Therefore the connection layer was not replaced. Inspection found a separate
operational gap: unhandled database iteration failures returned the same boolean as processed work,
so the Worker could retry immediately throughout an outage.

RED tests required an exponential, bounded, jittered backoff; explicit database-failure outcome; safe
cross-field settings; and shutdown-interruptible waits. The first run failed because those interfaces
did not exist. The implementation preserves `pool_pre_ping`, adds shared Worker/Reaper reconnect
backoff, resets failures after recovery, and prevents unknown exceptions from hot-looping by applying
the normal poll delay. Focused GREEN result: 30 tests; Ruff and strict mypy passed. A second full A–I
run is required for comparable After evidence.

Pre-rerun full validation passed: lock resolved 70 packages; all 286 files passed Ruff format and
lint; strict mypy passed 124 source files; and non-integration pytest passed
`532 passed, 9 deselected` in 244.57 seconds.

## 2026-08-08 — Database reconnect After evidence and CI failure diagnosis

### Remote execution and admitted effect

Local commit `03d6987` was pushed after verifying the worktree was clean and exactly one commit ahead
of `7f0738d`. GitHub Actions fault run `31247720668` executed the exact source SHA and committed
`fault-gh-31247720668-1` as `0901f9d`. A fast-forward pull preserved linear history. Independent
post-Git validation reported `complete: 27 scenarios, 5 payload files`; manifest source, payload set,
and SHA-256 records all matched.

The post-change matrix completed 84/84 Jobs successfully with 72 deliberate retries. Failed, lost,
duplicate CaseResult, duplicate terminal commit, stale accepted, and orphan counts were all zero.
Scenarios C and D attempted three stale successes and three stale failures respectively; none were
accepted. Scenario I completed 60/60 concurrent HTTP submissions and produced one Run per repetition.

Scenario F recovered after each three-second PostgreSQL outage without a Worker restart. Its median
changed from 6.910767 seconds (range 6.350567–6.951565) to 6.827549 seconds (range
6.281487–6.831259). The small difference is not admitted as a speed improvement. The verified change
is the bounded retry contract during disconnection and stop-aware shutdown, with no observed
correctness or recovery regression.

### Evidence exporter RED/GREEN

The existing fault CSVs contained headers only. RED tests required 27 per-repetition rows, nine
scenario summaries, complete source/run binding, LF-only output, and fail-closed rejection of an
unverified report, source mismatch, failed invariant, lost Job, or accepted stale result. The first
test failed at import because `scripts.export_fault_evidence` did not exist.

The GREEN implementation validates each immutable bundle before reading it, revalidates A–I matrix
completeness, and requires submitted=unique=completed=succeeded for every record. It preserves
scenario-specific outage, Outbox, Reaper, HTTP idempotency, container identity, and explicit Worker
restart fields instead of conflating them. Seven exporter tests, Ruff, and strict mypy passed. Running
the exporter against the two retained bundles produced 54 verified result rows and 18 summary rows.

### CI failure and diagnosis

The same push started CI run `31247720679`. Compose smoke passed, but `quality-and-integration`
failed. GitHub's public API showed the first failure was `Run tests without external services`.
`Prepare artifact directory` and `Apply migrations` then skipped because they used the implicit
success condition, while every integration step explicitly used `!cancelled()`. Eight database tests
therefore continued against an empty schema and emitted `UndefinedTable`; these were secondary, not
eight independent regressions.

GitHub refused unauthenticated raw-log download with HTTP 403, and the public browser page required
sign-in for log text. Focused reproduction with the exact CI environment passed all 30 changed tests,
then 149 artifact/auth/core/dataset/domain/evaluator/event/job tests, 89
observability/persistence/result/review/run/worker tests, and 51 target tests. Directory bisection
found local slowness in a prepared-evidence test whose build-context helper enumerates every path
before applying `.dockerignore`; the local repository has many ignored tool and pytest directories,
unlike a clean GitHub checkout. Several externally terminated `uv` parents left six test children;
their exact PIDs and start times were verified and only those processes were stopped.

The workflow now runs artifact preparation and migrations under `!cancelled()`, matching the
integration steps. This removes misleading empty-schema cascades on future independent unit failures.
A new workflow contract test failed before the YAML change and passes after it. The next pushed CI
run remains the authority on whether the original non-integration failure was transient.

## 2026-08-08 — PostgreSQL RLS spike design and local GREEN

### Design judgment

PostgreSQL documentation confirms that missing policies default-deny after RLS is enabled, table
owners normally bypass RLS, `FORCE ROW LEVEL SECURITY` subjects owners to policies, and roles with
`BYPASSRLS` always bypass. It also warns that policy subqueries can introduce concurrency races. The
current schema gave Dataset, DatasetVersion, and Run direct tenant columns, but CaseResult only
reached its tenant through Run.

The selected minimal design adds a direct, backfilled, non-null CaseResult tenant column, a composite
Run/tenant foreign key, and a tenant/run index. All four policies use the same row-local predicate and
transaction-local `app.current_tenant_id`. This is preferable to a CaseResult policy subquery because
the policy has no cross-table snapshot dependency and the database independently checks lineage.

The migration deliberately enables but does not force RLS. The application still uses one table-owner
credential for migrations and all processes; forcing the owner without first wiring API tenant
context and a background-worker access model would default-deny legitimate work. The spike is scoped
to proving a non-owner runtime boundary, and its document explicitly withholds a production
enforcement claim.

### RED/GREEN and problems

RED migration tests first failed because 0015 and the CaseResult tenant column did not exist. The
first downgrade run then failed due to a test typo (`20260802_0014` instead of the real
`20260803_0014`); only the test range was corrected. The next ORM run showed that `tenant_id` has two
intentional FK targets—Tenant directly and Run through the composite constraint—so the incomplete
test expectation was expanded rather than removing a constraint. Ruff requested import/line wrapping,
and MyPy required narrowing an update result to `CursorResult[Any]` before checking `rowcount`.

Local GREEN: lock check resolved 70 packages; 291 files passed Ruff format and lint; strict MyPy
passed 126 source files; and 29 focused tests passed. Three service tests were correctly skipped
without local PostgreSQL. The dedicated GitHub test will create a temporary non-owner/non-BYPASSRLS
role and prove fail-closed reads, four-table tenant filtering, rejected cross-tenant writes, hidden-row
updates, and accepted same-tenant writes against migrated PostgreSQL.

### CI diagnostic correction

The earlier CI failure was not transient. After the prerequisite fix, run `31249058658` proved
Compose smoke, migrations, and every integration group passed; only non-integration pytest failed.
Adding `/tmp/junit-unit.xml` to the existing annotation flow exposed the exact failure in run
`31249326439`: a parser-default test assumed `GITHUB_SHA` was absent even though GitHub Actions sets
it. The production parser correctly binds that SHA for evidence provenance. The test now explicitly
deletes the variable when checking the offline `UNSPECIFIED` default and separately proves that a
present 40-character GitHub SHA is adopted.

### Remote RLS authority

Commit `5f9ccbb` started GitHub Actions run `31249605065`. Compose smoke completed successfully. In
the quality-and-integration job, dependency installation, lock checking, formatting, Ruff, strict
MyPy, and the complete non-integration suite all passed. Migrations then applied successfully to the
real PostgreSQL service.

The dedicated `Integration - PostgreSQL row-level tenant isolation` step passed. It exercised the
temporary non-owner/non-`BYPASSRLS` role and verified fail-closed reads without tenant context,
tenant-filtered reads across Dataset, DatasetVersion, Run, and CaseResult, hidden-row UPDATE
isolation, rejected cross-tenant writes, and accepted same-tenant writes. Every later integration
group and the application image build also passed; the overall workflow concluded `success`.

Effect: the minimum RLS spike is now evidence-backed rather than locally inferred. Limitation: this
does not promote the current shared owner credential to a production RLS boundary because PostgreSQL
owners normally bypass enabled policies unless RLS is forced. Runtime/migration role separation and
transaction tenant-context wiring remain explicit future rollout work.

## 2026-08-08 — S3-compatible artifact backend local GREEN

### Judgment before modification

Inspection found that `ArtifactStore` already separated physical bytes from Dataset/Run/Result/Review
services, and PostgreSQL already separated global `artifact_blobs` from tenant-owned
`artifact_references`. Replacing that design would expand risk without solving the requested shared
storage gap. The selected change retains Local storage and adds S3 behind the same interface.

Official boto3 documentation defines `PutObject IfNoneMatch="*"` as create-only, returning 412 when
the key exists and 409 for a concurrent conflict; MinIO's S3 compatibility documentation lists
`If-None-Match` support for `PutObject`. This supports server-side atomic publication without the
check-then-write race of a separate HEAD followed by an unconditional PUT.

Tenant ID was not added to physical object metadata. One content digest can legitimately have
references from multiple tenants, so tenant authorization remains in PostgreSQL rather than being
collapsed into one ambiguous object metadata value.

### RED/GREEN sequence

1. The first S3 tests failed during collection because `S3ArtifactStore` and the bounded publish
   conflict error did not exist. Implementation added digest keys, Content-MD5, SHA metadata,
   conditional writes, 412 verification, bounded 409 retry, verified reads/deletes, stream closing,
   prefix validation, and thread offloading.
2. The next run passed all 13 storage tests but failed two configuration tests. Settings then gained
   a Local/S3 selector, bucket/prefix/endpoint/region/addressing fields, secret credentials, required
   bucket validation, and paired-credential validation. The combined set passed 31 tests.
3. Factory/wiring tests next failed because `build_artifact_store` did not exist. The factory now
   creates Local roots or a configured boto3 client; the API uses it once and passes the same store to
   all services and readiness. Focused wiring/readiness tests passed.
4. Deployment tests failed five times because MinIO and its CI proof were absent. Compose now defines
   a pinned MinIO service with non-root identity, read-only rootfs, dropped capabilities, resource
   limits, health check, and persistent volume. CI has a real MinIO integration step and Compose
   smoke explicitly selects S3 and provisions its bucket.

### Problems and corrections

- The first two `apply_patch` attempts were rejected atomically because their anchors guessed an
  existing test function name. No partial files were written; exact context was read and the patches
  were split.
- Ruff rejected broad `pytest.raises(Exception)` assertions in the real-service failure test. They
  were narrowed to `botocore.exceptions.ClientError`, preventing unrelated failures from satisfying
  the test.
- Strict MyPy rejected boto3/botocore because the runtime packages are not typed. Adding
  `boto3-stubs[s3]` as a development dependency preserved the strict gate instead of suppressing
  import checking.
- The host has no Docker daemon, so real MinIO behavior cannot be labeled verified locally. The
  workflow retains JUnit output and annotations; its next remote result is the authority.

### Local result and current effect

The focused artifact/config/wiring/deployment set passed 66 tests. Full validation resolved 79 locked
packages; 295 files passed Ruff format and lint; strict MyPy passed 127 source files; and
non-integration pytest passed `561 passed, 12 deselected` in 368.12 seconds.

The project can now select a shared S3-compatible backend without changing upper services, while
Local remains the default. This is local GREEN only until GitHub verifies real MinIO conditional
writes, corruption/failure behavior, and S3-backed Compose readiness.

### First remote MinIO failure and evidence-based correction

Commit `a98a5fb` started CI run `31250560395`. Compose image build, Python dependency sync, lock,
format, lint, and MyPy gates succeeded. Both jobs then failed at MinIO startup: Compose reported
PostgreSQL and Redis healthy while MinIO exited with status 1 immediately after logging
`API: SYSTEM.storage`. Because integration steps use `!cancelled()`, the dedicated MinIO test also
ran and failed after its prerequisite service was unavailable; that was a secondary failure.

Unauthenticated raw GitHub job-log download returned HTTP 403. The bounded Compose annotation kept
only the beginning and end of combined logs, truncating the detailed MinIO storage message from its
middle. Rather than guess, the Docker registry manifest/config for the exact official image was
queried. It declared no runtime `User`, used `/` as its workdir, and declared `/data` as a parent
volume. The first Compose version overrode the process to UID/GID 1000 but mounted a fresh `/data`
volume whose ownership had not been prepared for that UID.

New RED deployment tests required a thin derived image, an owned non-parent-volume data path, the
same non-root runtime identity, and MinIO-first failure diagnostics. They failed twice against the old
Compose definition. The correction creates `/var/lib/evalops-minio` and assigns UID/GID 1000 during
image build, switches to `USER 1000:1000`, mounts `minio_data` at that path, and leaves the runtime
rootfs read-only with all capabilities dropped. Focused deployment/hardening GREEN: 17 tests. A new
remote run is required; the result is not yet admitted as MinIO verification.

### Remote MinIO authority

Corrected commit `05d6681` started GitHub Actions run `31250798443`. The Compose job successfully
built the thin MinIO image, started and health-checked PostgreSQL/Redis/MinIO, applied migrations,
provisioned the configured bucket, and started API/Worker/Reaper with the S3 backend selected. API
readiness succeeded through `HeadBucket`, and runtime inspection verified non-root identity,
read-only rootfs, dropped capabilities, no-new-privileges, and positive CPU/memory/PID limits for
MinIO and the other services.

The quality job passed non-integration tests and started the same MinIO topology. Its dedicated
integration issued 12 concurrent publishes of identical bytes and observed exactly one
`created=true`, then verified download integrity, corruption rejection, refusal to delete corrupt
content, idempotent deletion, and missing-bucket readiness/publish failures. Every later integration,
migration downgrade/re-upgrade, cleanup, and application image build passed. The overall workflow
concluded `success`; the S3-compatible/MinIO backend is now `VERIFIED` for the tested contract.
