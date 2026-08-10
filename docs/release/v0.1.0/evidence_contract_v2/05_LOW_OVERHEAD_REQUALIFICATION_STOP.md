# Evidence contract v2 — low-overhead requalification stop

## Identity

- preregistration: `785272d`;
- recorder/exact-arm implementation: `63c8fa9`;
- final code lock: `0fd5376300155ee4fdfa3cfd248d636bdeca3100`;
- workflow source: `f2f20b797b65d1d49d62cbadbc5b858d6420595f`;
- workflow: `31407782154`;
- evidence commit: `b9aee04d10aeafa088876a68b9895d5a8d0ab180`.

## Contract-preserving changes

The recorder no longer reads its monotonic clock for counter-only or ignored markers. The benchmark
can select one exact arm already present in the frozen plan. The assessor explicitly distinguishes
single-arm overhead evidence from full-matrix formal evidence. None of these changes touches
scheduler behaviour, SQL, state, queue, batch, Worker count, distribution, sample size, threshold or
repetition count.

The exact overhead order was `off1/on1/on2/off2/off3/on3`. Each repetition contained only
`fair-q1000-skew_20_to_1-w8-b1` and passed its schema-v2 release-bundle assessment.

## Result

OFF medians were 27.153355 Jobs/s and 627.587034 ms claim p95. ON medians were 27.301233 Jobs/s and
542.922064 ms. Throughput changed +0.5446%, but claim p95 changed -13.4906%. Because the contract uses
absolute change and permits at most 10%, the verdict remains `INSTRUMENTATION_TOO_INTRUSIVE`.

CPU changed +1.7709% and RSS +0.0681%; both are reporting-only. Formal attribution and hypothesis
assessment were skipped. H1/H2/H3 remain `INCONCLUSIVE`.

An independent top-manifest audit matched all 84 listed and actual files and found zero missing,
extra, size-mismatched or hash-mismatched entries. Historical targeted Git trees remain unchanged.

## Stop boundary

The requalification preregistration prohibits another automatic observer redesign after failure.
There is no Candidate 4, no formal attribution, no downstream release qualification and no change to
the official targeted `NEGATIVE_SCALING` result. v0.1.0 remains `NOT_READY`; PR #1 remains Draft.
