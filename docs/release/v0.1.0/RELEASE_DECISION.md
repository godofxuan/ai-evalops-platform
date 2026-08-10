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
| evidence-gate hardening | PASS | independent raw-plan parser, arm-derived metadata/domain checks, no-false-empty blocker |
| locked-Job false-empty regression | PASS | true PostgreSQL push/PR runs `31398322919`/`31398332668` |
| attribution instrumentation overhead | **INSTRUMENTATION_TOO_INTRUSIVE** | run `31400658653`; absolute claim-p95 change 11.3194% > 10% |
| formal H1/H2/H3 attribution | NOT_RUN_STOPPED | overhead prerequisite failed; all hypotheses INCONCLUSIVE |
| low-overhead requalification | **INSTRUMENTATION_TOO_INTRUSIVE** | run `31407782154`; counterbalanced exact-arm claim-p95 change 13.4906% > 10% |
| passive PostgreSQL measurement qualification | **MEASUREMENT_SYSTEM_INVALID** | run `31421039618`; throughput 0.4292% PASS, absolute claim-p95 28.0396% FAIL |
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

The bounded diagnostic evidence is separate from that formal release input:

- instrumentation code lock: `f1ecbf20d8e266eddadd85391d2c782c581ecad2`;
- diagnostic execution source: `f0cfd8e341bca94586a75cecce74430330ffd12b`;
- workflow: `31400658653`;
- evidence commit: `4f1fd8bf37d5b440c40684208332116f9d90de0d`;
- manifest audit: 893 listed/actual files, zero missing, extra, size or SHA-256 mismatches.

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

## Attribution stop result

The preregistered representative arm was `fair-q1000-skew_20_to_1-w8-b1`, with exactly three
instrumentation-OFF and three instrumentation-ON repetitions. OFF medians were 30.125681 Jobs/s and
519.208889 ms claim p95; ON medians were 31.192255 Jobs/s and 460.437420 ms. Throughput changed
+3.5404%, while claim p95 changed -11.3194%. The contract gates on absolute change, so claim p95
exceeded the 10% budget even though its sampled direction improved.

The workflow correctly skipped the formal four-repetition attribution and hypothesis assessment.
H1 singleton coordination, H2 Tenant-permit contention and H3 SKIP LOCKED/retry feedback are all
`INCONCLUSIVE`; none is a proven root cause or a sufficient basis for Candidate 4. See
`performance_attribution/00_PREREGISTRATION.md` and
`evidence_contract_v2/04_HARDENING_AND_ATTRIBUTION_STOP.md`.

## Low-overhead requalification

A separately authorized and preregistered second stage reduced unnecessary recorder clock reads,
added fail-closed exact-arm execution and counterbalanced the six measurements as
`off1/on1/on2/off2/off3/on3`. It retained q1000, skew20:1, w8, b1, 100 measured Jobs, three
observations per mode and the original 5%/10% gates.

Workflow `31407782154` produced OFF medians of 27.153355 Jobs/s and 627.587034 ms claim p95, and ON
medians of 27.301233 Jobs/s and 542.922064 ms. Throughput changed +0.5446%; claim p95 changed
-13.4906%. The latter again exceeds the absolute 10% budget, so requalification is
`INSTRUMENTATION_TOO_INTRUSIVE`. Evidence commit `b9aee04` preserves 84 manifest-bound files with an
independent zero-mismatch audit.

Formal attribution and H1/H2/H3 assessment were again skipped. The second preregistration forbids an
automatic third observer redesign. This strengthens the stop decision; it does not alter the formal
targeted `NEGATIVE_SCALING` input or authorize Candidate 4.

## Passive PostgreSQL measurement-system qualification

The separately preregistered final measurement candidate moved collection out of the claim
transaction into a separate process and read-only PostgreSQL connection. Workflow `31421039618`
executed exactly four OFF and four ON observations in the frozen counterbalanced order. All eight
exact-arm bundles were `VERIFIED`; all correctness, false-empty, telemetry-error, dropped-sample and
overflow counters were zero; the 151-file root manifest independently had zero file-set, size or
SHA-256 mismatches.

OFF/ON throughput medians were 29.918848 and 29.790450 Jobs/s, an absolute change of 0.4292%, which
passed the 5% gate. OFF/ON claim-p95 medians were 708.689593 and 509.975702 ms, a -28.0396% relative
change whose absolute magnitude exceeded the unchanged 10% gate. The faster ON direction is still
measurement perturbation under the preregistered direction-independent rule.

The final measurement verdict is `MEASUREMENT_SYSTEM_INVALID`, and the terminal decision is
`PERFORMANCE_ATTRIBUTION_STOPPED_BY_MEASUREMENT_VALIDITY`. H1/H2/H3 were not run. No fourth observer,
additional repetition, threshold adjustment, scheduler candidate or formal attribution run is
authorized. See `measurement_system_v2/04_RESULTS.md` for the strict 18-section report.
