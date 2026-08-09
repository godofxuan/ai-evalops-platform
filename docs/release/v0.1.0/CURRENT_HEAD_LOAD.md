# v0.1.0 RC current-candidate load status

Conclusion: Candidate 3 has no complete formal load qualification. Current formal status is `NOT_RUN`, not
`VERIFIED`.

## Current evidence

- production source: `02f5e680e71d05c76c145da6895122a2cf04ba14`;
- ordinary CI: push `31327012832` and PR `31327016117`, both PASS;
- targeted workflow: `31327388006`, FAILED after repetition 1;
- evidence bot commit: `90a4e03ae75d0ae391f16f32934c144430de196d`;
- artifact: `targeted-gh-31327388006-1`, 404 KB;
- artifact digest: `b9db8fc934b3e736c5a30868833218cc470ab011fcfa24f12dc4892cdfe47a1a`;
- completed: 16/16 arms in rep1, 1,600/1,600 unique terminal Jobs;
- per-arm assessment: 16 `VERIFIED`, with zero lost, duplicate durable result, orphan, attempt mismatch,
  stale-accepted, illegal transition and empty-while-eligible counts;
- observed 20:1 secondary application receipt positions: w1/w2/w4/w8 = `2/2/2/2`;
- database sequence diagnostics: complete, with the same `2/2/2/2` positions;
- formal targeted blocker: `postgres_explain_candidate_cardinality_mismatch`;
- top-level status: `FAILED`, `repetition_count=0` because no repetition-level bundle verified.

Observed rep1 4→8 ratios were `0.678104` single-Tenant, `0.785456` balanced, `0.749962` 20:1 and `0.954809`
many-small-Tenants. They are `LIMITED` diagnostics, not a four-repetition verdict. The frozen formal capacity,
same-runner, fault and 32-arm workflows were not dispatched after the stop condition.

## Historical evidence boundary

Source `6acf72c3aa73c9fdc1664fe4e847fc8b8e90efd7`, run `31274490704`, remains a complete historical broken-fair
32-arm bundle with 16,000 unique terminal Jobs and severe 4/8-worker regression. Source
`15e7ac2e28b70430acd0bff88ee6cc78e5b86a86` remains the historical pre-fair baseline. Complete historical capacity
belongs to `9987a28`/`31272789199`; historical A–I ×3 fault belongs to `70a9b2b`/`31275450353`.

Allowed claim: Candidate 3 passed ordinary correctness and generated one complete diagnostic repetition whose 16
arms reconciled correctly. Forbidden claim: current formal scaling, complete targeted fairness, current capacity,
linear scaling or a production performance SLO.
