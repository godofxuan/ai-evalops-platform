# Negative and non-results

## Confirmed blockers and gaps

- Local Docker/Compose is unavailable. Local real-service experiments are `NOT-RUN`, not passed.
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
