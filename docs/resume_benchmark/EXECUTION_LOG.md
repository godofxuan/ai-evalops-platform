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
