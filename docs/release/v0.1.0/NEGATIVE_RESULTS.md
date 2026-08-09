# v0.1.0 RC negative results

失败证据不删除、不改写为成功。

## Current and only release blocker

Targeted run `31319556885`, source `246252e`, failed `skew_20_to_1/w8`: secondary Tenant first durable claim
position 4 > frozen maximum 2. This is the only current v0.1.0 blocker.

## Preserved final-sprint negatives

- old runs `31297535370`/`31297538171`: six-hour cancellation caused by an incorrect long external Tenant-lock test
  cycle; retained to show why fail-fast diagnostics were required;
- run `31317179594`: one 10W/100J first wave returned 9/10 while work remained, proving fixed retry-budget
  false-empty behavior;
- targeted `31318923861`: real Run→Job / Job→Run deadlock; artifact retained, then fixed with key-preserving Run
  guard;
- targeted `31319556885`: 12 correctness-clean arms, followed by the frozen fairness failure; repetitions 2–4 did not
  run and must not be imputed;
- partial repetition 1 showed 4→8 throughput changes of -10.48%, -9.17% and -10.93% for the three completed
  distributions. These are `LIMITED`, not a formal four-repetition verdict.

## Historical negatives

Historical 100k 41s p95/504 retries/0.628 Jobs/s, broken-fair formal regression (including worst cross-runner
-63.44%), failed manifests, oversized logs and non-fast-forward bot commits remain in their immutable bundles. They
explain the engineering path but are not current resume metrics.

## Stop rule

Candidate 2 is the second and final scheduler production iteration. No Candidate 3, parameter gamble or relaxed
fairness gate is allowed. Current capacity, same-runner paired, fault and formal runs are `NOT_RUN` because their
targeted prerequisite failed.
