# v0.1.0 release decision

## Decision: NOT_READY_TARGETED_NEGATIVE_SCALING

As of 2026-08-10, PR #1 must remain Draft. Do not merge it and do not create a `v0.1.0` tag or GitHub Release.

Candidate 3 scheduler correctness and the repaired schema-v2 evidence contract both passed. Exact-source targeted
run `31352270523` completed four repetitions, 64/64 arms and 6,400/6,400 unique terminal Jobs with all four 20:1
position vectors equal to `2/2/2/2`. The overall targeted result is nevertheless `NEGATIVE_SCALING`: median
eight-Worker throughput divided by four-Worker throughput was below the required 0.95 floor for single Tenant
(`0.782511`), balanced (`0.772797`) and 20:1 (`0.796214`). Many-small passed at `1.014063`.

| Gate | Current result | Evidence |
|---|---|---|
| ordinary CI | PASS | source `91acdba`; push `31351821014`; PR `31351825433` |
| scheduler correctness | PASS | priority, 20x10W/100J, uniqueness, drain, crash, progress, fencing, deadlock regressions |
| schema-v2 evidence contract | PASS | 4/4 manifest-bound rep bundles VERIFIED; selector units and cardinalities correct |
| frozen 20:1 targeted fairness | PASS FOR FROZEN WORKLOAD | four repetitions, every w1/w2/w4/w8 vector `2/2/2/2` |
| targeted correctness | PASS | 64/64 arms; 6,400/6,400 terminal; all protected counters zero |
| targeted self-scaling | **NEGATIVE_SCALING** | three required distributions below 0.95 |
| targeted workflow | FAILED BY DESIGN | run `31352270523`; assessment returned nonzero for negative scaling |
| current 1k/10k/100k capacity | NOT_RUN_STOPPED | targeted performance prerequisite failed |
| current same-runner A/B/C | NOT_RUN_STOPPED | targeted performance prerequisite failed |
| current A-I x3 fault | NOT_RUN_STOPPED | targeted performance prerequisite failed |
| current formal 32-arm | NOT_RUN_STOPPED | targeted performance prerequisite failed |
| release | **NOT_READY** | performance gate failed; downstream release evidence intentionally absent |

## Evidence identity

- Candidate 3 scheduler source: `02f5e680e71d05c76c145da6895122a2cf04ba14`;
- schema-v2 qualification source: `91acdba9f5b5f1a84fb03640382c9e4871364afe`;
- workflow: `31352270523`;
- evidence commit: `15bab58150385c9a39778d64a3e4163c10892ecc`;
- artifact: `targeted-gh-31352270523-1`, 1,395,629 bytes;
- artifact digest: `sha256:6b5f68821b90ee6bdbb36d66aba0087864ca2048ac356ec3cb701e378d0c120f`.

Source `91acdba` changes only evidence generation/assessment and documentation on top of Candidate 3. No scheduler,
Worker, migration, threshold, workload, repetition, seed, batch, retry, pool, sleep or lease parameter changed.

## Why the prior blocker is closed but release still fails

Historical run `31327388006` remains an immutable schema-v1 failure with
`postgres_explain_candidate_cardinality_mismatch`. The preregistered schema-v2 contract made the dimensions explicit:
fair counts eligible Tenant round members, legacy FIFO counts eligible Jobs. All four new rep bundles verify under
that contract, so the old cardinality blocker is closed for the new run.

Completing the evidence chain exposed the actual performance verdict. Three of four distributions regress when
Worker count rises from four to eight, and the 0.95 floor requires all distributions to pass. A complete negative
result cannot be reclassified as incomplete or ignored because correctness/fairness passed.

## Stop decision

The frozen protocol requires `targeted fail -> STOP`. No Candidate 4, threshold change, workload change, parameter
tuning or immediate retry is authorized. Historical capacity/fault/formal bundles remain
`VERIFIED_HISTORICAL` only. See `evidence_contract_v2/03_REMOTE_TARGETED_DECISION.md` for the full observation and
diagnostic ledger.
