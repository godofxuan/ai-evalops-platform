# v0.1.0 RC correctness

Candidate 3 scheduler/state/fencing correctness is `PASS`; complete release qualification is separately `FAILED`.

## Current Candidate 3 evidence

- source `02f5e68`, push CI `31327012832` and PR CI `31327016117` both passed real PostgreSQL, Redis, migration and
  Compose paths;
- the unchanged 20-repetition 10W/100J `limit=1` contract completed 2,000 unique Job claims and Attempts with no
  first-wave empty return;
- deterministic Candidate 2 overtaking RED used Barrier/Event coordination and observed secondary receipt position
  `8`; Candidate 3 passed the same application receipt oracle and database sequence oracle within position `2`;
- priority preservation, first-wave uniqueness, complete drain, cross-Tenant progress, permit rollback/recovery,
  false-empty, lock/deadlock and result/lease/version fencing regressions passed;
- targeted rep1 ran 16 arms and reconciled 1,600/1,600 terminal Jobs with zero lost, duplicate durable result,
  orphan, attempt mismatch, stale success/failure accepted, illegal transition and empty-while-eligible counts.

`CORRECTNESS_PASS` means the completed correctness obligations are green. It does not override the targeted evidence
failure, complete four-repetition fairness requirement, missing current capacity/fault/formal bundles or the release
decision.

## Historical fault boundary

Run `31275450353` remains `VERIFIED_HISTORICAL`: A–I ×3, 27/27 records, zero lost/duplicate/orphan/invariant
failures, stale success attempted/accepted 3/0 and stale failure 3/0. Candidate 3 fault qualification is `NOT_RUN`, so
these values cannot be promoted as current.

No exactly-once, unlimited fault tolerance, universal deadlock freedom or production reliability certification is
claimed.
