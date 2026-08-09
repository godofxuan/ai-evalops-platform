# Resume-safe metrics

## VERIFIED_CURRENT

- Real PostgreSQL push/PR CI passed 20 isolated 10-worker/100-job `limit=1` drains: 2,000 unique durable claims,
  2,000 Attempts, zero first-wave empty requests. Source `ed095cc`; runs `31318294569`/`31318298660`.
- After a RED exposed a Run→Job / Job→Run deadlock, a key-preserving Run guard passed real PostgreSQL push/PR CI.
  Source `3350c23`; runs `31319292162`/`31319295583`.
- Targeted source `246252e` completed 12 production-worker arms with 1,200/1,200 unique terminal Jobs and zero
  lost/duplicate durable result/orphan/empty-while-eligible counts before the fairness gate stopped execution.

## VERIFIED_HISTORICAL

- Pre-fair 32-arm/16,000-job scaling and its throughput values belong only to source `15e7ac2`, run `31177702100`.
- A-I ×3 27/27 fault evidence, stale success/failure accepted 0 and idempotency evidence belong only to historical
  source/run `70a9b2b`/`31275450353`.
- Complete 1k/10k/100k capacity belongs only to historical source/run `9987a28`/`31272789199`.

## LIMITED

- Targeted attempt 2 has one incomplete repetition. Its 4→8 ratios (0.8952 single, 0.9083 balanced, 0.8907 20:1)
  are diagnostic only and must include the incomplete-protocol limitation.

## FAILED

- Current concurrent 20:1 fairness: w8 secondary durable claim position 4, required `<= 2`.
- Historical broken-fair formal release comparison failed the >15% regression gate.

## NOT_SAFE

- Any current Candidate 2 throughput, linear scaling, production capacity SLO or strong fairness SLO.
- Historical -63.44%, 41s p95 and 0.628 Jobs/s in resume正文; keep them in engineering/interview evidence only.
- Calling historical fault/capacity/formal values current.

## NOT_RUN

- Current 1k/10k/100k capacity qualification.
- Current A/B/C same-runner paired benchmark.
- Current A-I ×3 fault rerun.
- Current formal 32-arm/16,000-job worker scaling.
