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
