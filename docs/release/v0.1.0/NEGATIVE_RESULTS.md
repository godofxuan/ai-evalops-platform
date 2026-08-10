# v0.1.0 RC negative results

Failed evidence is retained and never rewritten as success.

## Current release blocker

Targeted run `31352270523`, source `91acdba`, completed all four repetitions but returned
`NEGATIVE_SCALING`. Median w8/w4 Jobs/s ratios were single `0.782511`, balanced `0.772797`, 20:1 `0.796214` and
many-small `1.014063`; the frozen contract requires every distribution to be at least 0.95. The first three are
formal current negative results, not limited diagnostics.

Correctness and fairness were clean: 64/64 arms, 6,400/6,400 terminal, protected counters zero and every 20:1
position vector `2/2/2/2`. This separation matters: correctness/fairness success does not cancel a performance gate.

## Preserved evidence-contract negative

Historical run `31327388006`, source `02f5e68`, remains failed with
`postgres_explain_candidate_cardinality_mismatch` after one repetition. Schema v2 was preregistered and implemented
without rewriting that bundle. New run `31352270523` closed the mismatch and verified all four bundles, proving the
current blocker is genuine scaling rather than the old evidence incompatibility.

## Other preserved negatives

- Candidate 2 deterministic RED: secondary application receipt position 8;
- Candidate 2 targeted `31319556885`: 20:1/w8 position `4 > 2`;
- targeted `31318923861`: real Run-to-Job / Job-to-Run deadlock, later removed;
- run `31317179594`: false empty under eligible same-Tenant work;
- historical broken-fair formal: severe scaling regression;
- historical 100k: approximately 41s claim p95, 504 retries and 0.628 Jobs/s.

## Stop rule

Targeted performance failure activates the frozen stop. No Candidate 4, threshold/workload/Worker/seed change,
parameter gamble or immediate targeted retry is allowed in this stage. Current capacity, same-runner, fault and
formal are `NOT_RUN_STOPPED`.
