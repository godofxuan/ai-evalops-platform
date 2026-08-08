# Negative and non-results

## Confirmed blockers and gaps

- Local Docker/Compose is unavailable. Local real-service experiments are `NOT-RUN`, not passed.
- Formal load run `gate1-gh-31174970193-1` completed all 32 arms, but its committed final bundle is
  `INVALID-AFTER-GIT-TRANSPORT`. `summary/arms.csv` was hashed as a 4100-byte CRLF file, then Git's
  repository-wide `eol=lf` clean filter committed a 4067-byte LF file. The expected SHA-256 was
  `2e193d02...`, while the committed blob is `05f07c13...`. The raw run is retained as a negative
  result, and none of its performance numbers are résumé-safe.
- Formal load run `gate1-gh-31176423383-1` fixed post-Git hash verification (`complete`, 664 files,
  32 arms) but failed the capacity quality gate for the same deterministic eight 4/8-worker arms.
  Idle worker processes did not expose zero-valued `operation="result"` histograms, so successful
  scrapes were classified `UNKNOWN`. The run remains valid correctness/raw evidence but is not used
  for capacity or résumé metrics.
- Before commit `da92532`, `scripts.run_failure_scenarios` covered four coarse scenarios rather than
  A–I and lacked per-scenario database reconciliation. This historical gap is resolved by the two
  retained 27-record matrices; the original limitation remains recorded to explain the redesign.
- The initial local integration command skipped all nine integration tests because no real
  PostgreSQL/Redis endpoints were configured.
- The first documentation lookup assumed `docs/phase_9_environment_and_blockers.md`; the actual file
  is `docs/results/phase_9_environment_and_blockers.md`. No repository state was changed by the
  failed read.
- Recursive PowerShell discovery encountered access-denied pytest temporary directories. A bounded
  `rg --files` lookup was used instead; those directories were not deleted.
- CI run `31247720679` failed first in the non-integration pytest step. Because artifact preparation
  and migrations used the default success condition while later integration steps used
  `!cancelled()`, migration was skipped and eight later PostgreSQL tests produced misleading
  `UndefinedTable` failures. Public annotations exposed the cascade but GitHub required sign-in for
  the first step's raw log. The workflow prerequisites were changed to `!cancelled()`; the next CI
  run must determine whether the original unit failure was transient or reproducible.
- CI run `31250560395` was the first real MinIO attempt for source `a98a5fb`. PostgreSQL and Redis
  became healthy, but MinIO exited during `SYSTEM.storage`; both jobs therefore failed their MinIO
  startup gate, and the continued MinIO integration test failed secondarily. Public raw-log download
  returned 403, while the bounded combined-log annotation omitted the detailed storage line. Exact
  registry metadata showed the official image defaults to root and declares `/data` as a parent
  volume; forcing UID/GID 1000 onto an unprepared fresh volume was the diagnosed configuration bug.
  A thin derived image now prepares a non-parent-volume directory for UID/GID 1000, and MinIO-first
  diagnostics prevent the same evidence loss. This run is retained as `FAILED`, not success evidence.

## Reporting rule

An empty CSV is not evidence of zero failures. Until a real scenario is deliberately induced and its
durable state reconciled, the status is `NOT-RUN` or `UNKNOWN`, never `VERIFIED_ZERO`.
