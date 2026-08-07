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
- The existing `scripts.run_failure_scenarios` covers four coarse scenarios, not the required A–I
  matrix, and does not perform database-level invariant reconciliation for every scenario.
- The initial local integration command skipped all nine integration tests because no real
  PostgreSQL/Redis endpoints were configured.
- The first documentation lookup assumed `docs/phase_9_environment_and_blockers.md`; the actual file
  is `docs/results/phase_9_environment_and_blockers.md`. No repository state was changed by the
  failed read.
- Recursive PowerShell discovery encountered access-denied pytest temporary directories. A bounded
  `rg --files` lookup was used instead; those directories were not deleted.

## Reporting rule

An empty CSV is not evidence of zero failures. Until a real scenario is deliberately induced and its
durable state reconciled, the status is `NOT-RUN` or `UNKNOWN`, never `VERIFIED_ZERO`.
