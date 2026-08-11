# Resume-safe metrics

> **Historical benchmark snapshot:** current resume authority is
> [`docs/handoffs/RESUME_METRIC_LEDGER.md`](../handoffs/RESUME_METRIC_LEDGER.md). Do not copy a value from this file without
> its source SHA and historical/current classification.

## VERIFIED_CURRENT

- Qualification source `91acdba` passed real PostgreSQL push/PR CI `31351821014`/`31351825433`.
- The ordinary 20-repetition 10-worker/100-job `limit=1` contract remains green with 2,000 unique Jobs/Attempts and
  zero first-wave empty requests.
- Deterministic PostgreSQL coordination reproduced Candidate 2 application receipt position 8 and made Candidate 3
  pass the same receipt/database-sequence oracles within position 2.
- Targeted run `31352270523` completed four schema-v2 `VERIFIED` rep bundles: 64/64 arms, 6,400/6,400 unique terminal
  Jobs and zero protected correctness/fencing counters.
- Every targeted 20:1 w1/w2/w4/w8 vector was `2/2/2/2` in every repetition. This is an exact-workload result, not a
  universal fairness or production SLO claim.
- Schema v2 manifest/unit/arm-identity checks verified all 512 EXPLAIN records and rejected tested spoofing cases.
- The hardened schema-v2 assessor independently recomputes selector-specific candidate cardinality from each
  preserved raw PostgreSQL plan and cross-checks it with the summary and arm contract.
- True PostgreSQL push/PR runs `31398322919`/`31398332668` passed the locked-eligible-Job no-false-empty regression.

## FAILED_CURRENT

- Overall targeted result is `NEGATIVE_SCALING`.
- Median w8/w4 ratios: single `0.782511`, balanced `0.772797`, 20:1 `0.796214`, many-small `1.014063`; required
  minimum is 0.95 for every distribution.
- PR #1 remains Draft and v0.1.0 remains `NOT_READY_TARGETED_NEGATIVE_SCALING`.
- Performance diagnostic `31400658653` is `INSTRUMENTATION_TOO_INTRUSIVE`: OFF/ON claim-p95 medians changed by
  11.3194% in absolute terms against a preregistered 10% budget.
- Formal H1/H2/H3 attribution is `NOT_RUN_STOPPED`; all three hypotheses are `INCONCLUSIVE`.
- Counterbalanced exact-arm requalification `31407782154` also returned
  `INSTRUMENTATION_TOO_INTRUSIVE`: throughput changed +0.5446%, while absolute claim-p95 change was
  13.4906% against the unchanged 10% budget.

## HISTORICAL_ONLY

- Old Candidate 3 targeted run `31327388006` is the preserved schema-v1 cardinality-contract failure.
- Complete 1k/10k/100k capacity belongs only to `9987a28`/`31272789199`.
- A-I x3 fault belongs only to `70a9b2b`/`31275450353`.
- Broken-fair and pre-fair formal bundles belong only to `6acf72c`/`31274490704` and
  `15e7ac2`/`31177702100`.
- Candidate 2 targeted position 4 belongs to `246252e`/`31319556885`.

## NOT_SAFE

- production-ready, production capacity, linear scaling, universal fairness, strong fairness SLO or exactly once;
- hiding current negative scaling while quoting bounded fairness success;
- using historical `-63.44%`, `41s`, `504`, `0.628 Jobs/s` as current numbers;
- calling the new workflow failure an infrastructure failure.
- calling the stopped overhead diagnostic root-cause attribution, or treating its favourable latency direction as
  permission to ignore the absolute-change gate.
- claiming the locally 31%-cheaper recorder qualified remote measurement; local observer cost and
  remote perturbation are separate claims.

## NOT_RUN_STOPPED

- Candidate 3 current 1k/10k/100k capacity;
- Candidate 3 current A/B/C same-runner comparison;
- Candidate 3 current A-I x3 fault;
- Candidate 3 current formal 32-arm/16,000-Job scaling.
