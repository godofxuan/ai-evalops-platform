# Candidate 3 final release decision

Status: `NOT_READY_TARGETED_EVIDENCE`; scheduler development stopped

Candidate 3 is the one authorized bounded redesign. Its deterministic fairness RED, priority and ordinary
PostgreSQL correctness obligations passed at source `02f5e68`, but targeted workflow `31327388006` failed the frozen
release-bundle evidence contract after one diagnostic repetition. Four repetitions, capacity, same-runner, current
fault and formal scaling are incomplete or `NOT_RUN`.

PR #1 remains Draft. There is no merge, tag or GitHub Release. No Candidate 4, parameter tuning, threshold/workload
change or gate redefinition is allowed in this stage.

The current blocker is precise: Candidate 3's round-membership EXPLAIN cardinality no longer matches the frozen
Job-queue-cardinality evidence contract, so targeted evidence cannot verify. The one executed repetition's 20:1
positions `2/2/2/2` are retained as `LIMITED`, not promoted to a complete fairness claim.
