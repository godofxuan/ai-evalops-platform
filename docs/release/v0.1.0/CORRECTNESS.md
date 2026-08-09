# v0.1.0 RC correctness

Current state/fencing correctness is `PASS`; release fairness is separately `FAIL`.

## Current Candidate 2 evidence

- push/PR CI `31318294569` and `31318298660`: 20 isolated 10W/100J `limit=1` drains, 2,000 unique claims and
  2,000 Attempts; zero first-wave empty requests;
- push/PR CI `31319292162` and `31319295583`: result-completion Run guard FK compatibility regression passed real
  PostgreSQL and Compose;
- targeted attempt 2 `31319556885`: 12 completed arms, 1,200/1,200 unique terminal successes; zero lost,
  duplicate durable result, orphan, attempt mismatch, stale accepted, illegal transition and empty-while-eligible;
- no Run/Job deadlock recurred after `3350c23`.

The current targeted run failed the independent 20:1 fairness invariant at w8. `CORRECTNESS_PASS` here means durable
state, uniqueness, lease/version fencing and reconciliation; it does not mean release READY.

## Historical fault boundary

Run `31275450353` remains `VERIFIED_HISTORICAL`: A-I ×3, 27/27 records, zero lost/duplicate/orphan/invariant failures,
stale success attempted/accepted 3/0 and stale failure 3/0. Because the current fault workflow was not run after the
targeted failure, these values cannot be promoted as current Candidate 2 fault evidence.

No exactly-once, unlimited fault tolerance or production reliability certification is claimed.
