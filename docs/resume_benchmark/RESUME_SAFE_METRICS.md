# Resume-safe metrics

## VERIFIED_CURRENT

- Candidate 3 source `02f5e68` passed real PostgreSQL push/PR CI (`31327012832`/`31327016117`), including
  priority, lease/version fencing, crash rollback/recovery, cross-Tenant progress, migration and deadlock regressions.
- The unchanged 20-repetition 10-worker/100-job `limit=1` contract completed 2,000 unique durable Job claims and
  2,000 Attempts with zero first-wave empty requests in Candidate 3 ordinary CI.
- The deterministic PostgreSQL schedule proves the engineering method: Candidate 2 allowed an early committed
  secondary reservation to reach application receipt position 8; Candidate 3 passes the same receipt and database
  sequence oracles within position 2 in ordinary CI. This is a test-scope claim, not complete release fairness.
- Targeted rep1 produced 16 individually `VERIFIED` arms and 1,600/1,600 unique terminal Jobs with zero correctness
  failures. It remains a completed diagnostic repetition inside a failed overall qualification.

## VERIFIED_HISTORICAL

- Pre-fair 32-arm/16,000-job scaling belongs only to `15e7ac2`/`31177702100`.
- A–I ×3 27/27 fault evidence and stale success/failure accepted 0 belong only to `70a9b2b`/`31275450353`.
- Complete 1k/10k/100k capacity belongs only to `9987a28`/`31272789199`.
- Candidate 2 targeted fairness failure (w8 position 4) belongs to `246252e`/`31319556885` and remains historical
  negative evidence after Candidate 3 was implemented.

## LIMITED

- Candidate 3 targeted rep1 observed 20:1 secondary application and DB-sequence positions `2/2/2/2` for
  w1/w2/w4/w8. The release bundle failed and repetitions 2–4 did not run, so this is not complete fairness evidence.
- Candidate 3 rep1 4→8 ratios were `0.678104` single, `0.785456` balanced, `0.749962` 20:1 and `0.954809`
  many-small. They are one-repetition diagnostics, not formal performance metrics.

## FAILED

- Current Candidate 3 targeted qualification: run `31327388006`, blocker
  `postgres_explain_candidate_cardinality_mismatch`, top-level verified repetition count `0/4`.
- Candidate 2 concurrent 20:1 fairness: w8 secondary durable receipt position `4`, required `<=2`.
- Historical broken-fair formal release comparison failed the >15% regression gate.

## NOT_SAFE

- “Candidate 3 solved current fair scheduling,” “strong fairness SLO,” “linear scaling,” “production capacity” or
  “v0.1.0 release ready.”
- Promoting rep1 `2/2/2/2` to a four-repetition fairness PASS.
- Historical `-63.44%`, `41s` p95, `504` retries or `0.628 Jobs/s` in resume body.
- Calling historical fault/capacity/formal values current.

## NOT_RUN

- Candidate 3 current 1k/10k/100k capacity qualification.
- Candidate 3 current A/B/C same-runner paired benchmark.
- Candidate 3 current A–I ×3 fault rerun.
- Candidate 3 current formal 32-arm/16,000-job worker scaling.
