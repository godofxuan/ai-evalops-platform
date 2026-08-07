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
