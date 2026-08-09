# Final scheduler lock-mode experiment

Date: 2026-08-09  
Candidate production commit: `18fb876d280e43e8e9eaec70a50cca046dc84049`

## Decision

Use `FOR NO KEY UPDATE OF tenants SKIP LOCKED` for the short Phase-A fair-turn transaction. This is the minimum
sufficient explicit Tenant row lock because Phase A changes only `last_scheduler_turn_at`, never a Tenant key.

Do not use `FOR UPDATE` for the production fair-turn lock. It needlessly conflicts with the key-preserving locks that
PostgreSQL foreign-key checks acquire for Phase-B Audit and Outbox writes.

## RED→GREEN

The SQL compile contract was changed first. It required the exact PostgreSQL suffix:

```sql
FOR NO KEY UPDATE OF tenants SKIP LOCKED
```

and rejected `FOR UPDATE OF tenants`. The RED showed the old compiled suffix. The production GREEN was one SQLAlchemy
option (`key_share=True` with `read=False`), after which 10/10 claiming unit tests passed.

## PostgreSQL compatibility experiments

| Producer of Tenant lock | Competing operation | Result |
|---|---|---|
| External `FOR UPDATE` | Job-only selector | PASS; selector is independent |
| External `FOR UPDATE` | Complete durable claim | Expected `55P03`; FK-related blocking captured |
| External `FOR NO KEY UPDATE` | Complete durable claim | PASS and commit |
| Production Phase A `FOR NO KEY UPDATE` | Same-row Phase A writer | Must remain mutually exclusive; real CI contract added |
| Production Phase A `FOR NO KEY UPDATE` | Phase B FK writes | Must overlap and commit; real CI contract added |

The raw lock graph and artifact digest are in `01_LOCK_DIAGNOSTIC.md`.

## H3 same-tenant samples before the full benchmark

These are diagnostic CI samples, not a release benchmark:

| Source/run | Attempts | Retries | Retry/success | p50 ms | max ms | Correctness |
|---|---:|---:|---:|---:|---:|---|
| `1b6a2f8` / push #98, strong Phase A | 17 | 9 | 1.125 | 151.639 | 171.872 | 8/8 unique |
| `86767e7` / push #100, pre-H3 diagnostic | 13 | 5 | 0.625 | 128.250 | 157.404 | 8/8 unique |
| `18fb876` / PR #103, H3 | 14 | 6 | 0.750 | 99.560 | 131.190 | 8/8 unique |
| `18fb876` / push #102, H3 | threshold passed | threshold passed | `<=0.25` in that run | not emitted | not emitted | full CI success |
| `9ac7088` / push #104, final contract | 12 | 4 | 0.500 | 117.400 | 164.373 | 8/8 unique; p95 157.049 ms |

The exact same H3 source passed push CI but failed PR CI solely on the old `<=0.25` one-sample threshold. That makes
the threshold unsuitable as a CI correctness gate. It does not make the performance automatically acceptable. The
candidate must be evaluated by same-runner, counterbalanced, repeated A/B/current benchmarks and the unchanged release
regression gate.

## Rejected alternatives

- Removing the Tenant lock: rejects the required fair-turn mutual-exclusion invariant.
- Removing `SKIP LOCKED`: lets one hot Tenant block progress to other Tenants.
- Increasing retries or changing sleep/pool/lease values: parameter gambling without root-cause evidence.
- Moving Job/Attempt/lease writes into Phase A: enlarges the critical section and breaks the two-phase purpose.
- Adding Redis/Kafka/Celery/Temporal coordination: outside scope and unnecessary for the demonstrated lock relation.

## Status

Lock-mode hypothesis: `VERIFIED`.  
Production-shaped overlap, mutual exclusion, cross-Tenant progress, reservation-crash, priority and initial 10W/100J
contracts: `VERIFIED_REAL_POSTGRESQL_CI` by push run `31315634340` and PR run `31315639504` at source `9ac7088`.
The 10W/100J contract was subsequently strengthened from one complete drain to 20 complete repetitions and therefore
requires one more CI qualification before it may replace this initial result.  
Release performance: `NOT_YET_QUALIFIED`.
