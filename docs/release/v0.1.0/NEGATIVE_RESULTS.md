# v0.1.0 RC negative results

Failed evidence is retained and never rewritten as success.

## Current release blocker

Targeted workflow `31327388006`, source `02f5e68`, failed the source-bound release-bundle check
`postgres_explain_candidate_cardinality_mismatch`. Candidate 3 round-membership EXPLAIN returns active Tenant
cardinality, but the unchanged assessor expects Job queue cardinality. Sixty-four fair summaries disagreed with the
queue size; repetitions 2–4 were not run. The release is `NOT_READY` because targeted evidence is incomplete/failed,
not because ordinary correctness failed.

Rep1 also showed diagnostic 4→8 ratios below the 0.95 self-scaling floor in single (`0.678104`), balanced
(`0.785456`) and 20:1 (`0.749962`) distributions. Because no repetition verified and four repetitions did not run,
these are `LIMITED` negative observations, not a formal performance verdict.

## Preserved Candidate 2/Candidate 3 negatives

- Candidate 2 deterministic RED: early committed secondary reservation was overtaken; its application receipt was
  position `8` after six later primary claims.
- Candidate 2 targeted `31319556885`: 20:1/w8 secondary receipt position `4 > 2`; only 12 arms of rep1 completed.
- old runs `31297535370`/`31297538171`: six-hour cancellation from an incorrect long external Tenant-lock test
  cycle, motivating fail-fast diagnostics.
- run `31317179594`: one 10W/100J first wave returned 9/10 while eligible work remained, proving the fixed-budget
  false-empty path.
- targeted `31318923861`: real Run→Job / Job→Run deadlock, later removed with a key-preserving Run guard.
- Candidate 3 targeted `31327388006`: all 16 rep1 arms were correctness-clean and 20:1 positions were observed at 2,
  but the evidence contract failed and no formal PASS may be inferred.

## Historical negatives

Historical `-63.44%`, 100k `41s` p95, `504` retries and `0.628 Jobs/s`, failed manifests, oversized logs and
non-fast-forward evidence-bot commits remain in their immutable bundles. They explain the engineering path but are
not current resume metrics.

## Stop rule

Candidate 3 was the only authorized new production design. Because targeted qualification failed, no Candidate 4,
assessor relaxation, threshold/workload/Worker/seed change or parameter gamble is allowed in this stage. Current
capacity, same-runner, fault and formal runs are `NOT_RUN`.
