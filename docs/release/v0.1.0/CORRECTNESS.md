# v0.1.0 RC correctness

Candidate 3 scheduler/state/fencing correctness and the frozen targeted fairness workload are `PASS`; complete
release qualification is separately `FAILED` by targeted performance scaling.

## Current evidence

- source `91acdba` passed push CI `31351821014` and PR CI `31351825433` on real PostgreSQL/Redis/Compose;
- unchanged ordinary 20-repetition 10W/100J `limit=1` correctness remains green;
- deterministic Candidate 2 RED position 8 remains green for Candidate 3 within position 2;
- priority, uniqueness, full drain, cross-Tenant progress, permit rollback/recovery, false-empty, deadlock and
  result/lease/version fencing regressions passed;
- targeted run `31352270523` completed four verified schema-v2 repetitions;
- 64/64 arms reconciled 6,400/6,400 unique terminal Jobs;
- all lost, duplicate durable result, orphan, Attempt mismatch, stale-success accepted, stale-failure accepted,
  illegal transition and empty-while-eligible counters were zero;
- each repetition's 20:1 w1/w2/w4/w8 positions were `2/2/2/2`.

These facts support a bounded exact-workload correctness/fairness claim. They do not override the negative 4-to-8
Worker scaling verdict, establish universal fairness, prove exactly-once processing or certify production
reliability.

Historical A-I x3 fault run `31275450353` remains `VERIFIED_HISTORICAL`; Candidate 3 current fault qualification is
`NOT_RUN_STOPPED` because the targeted performance prerequisite failed.
