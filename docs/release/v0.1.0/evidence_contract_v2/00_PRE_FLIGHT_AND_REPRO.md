# Evidence contract v2 — pre-flight and reproduction

Date: 2026-08-10

## Scope authorization

This is a new evidence-only improvement stage. It does not authorize Candidate 4 or any change to Candidate 3
production scheduling, fairness threshold, workload, Worker count, repetition count, batch, seed, retry, pool,
sleep or lease parameters.

## Pre-flight

- branch: `codex/evidence-gate-1`
- HEAD: `a4d43db35ab62102f756d37bdd3608759485b881`
- worktree: clean
- Candidate 3 production source: `02f5e680e71d05c76c145da6895122a2cf04ba14`
- preserved failed targeted evidence: `90a4e03ae75d0ae391f16f32934c144430de196d`
- PR #1: Open Draft, head `a4d43db`
- final push/PR CI: `31328599409` / `31328602508`, both PASS
- tag/release: none
- ADR/AGENTS override in scope: none found

## Deterministic feedback loop

The original rep1 bundle is reassessed in place without modifying any payload:

`docs/results/release/v0.1.0/targeted-gh-31327388006-1/rep1/bundle`

Expected arms come from the frozen queue-1000 plan and expected EXPLAIN coverage remains four fair plus four legacy
records per arm. Two consecutive executions produced the same result:

| Attempt | Status | Blockers | Arms |
|---:|---|---|---:|
| 1 | FAILED | `postgres_explain_candidate_cardinality_mismatch` | 16 |
| 2 | FAILED | `postgres_explain_candidate_cardinality_mismatch` | 16 |

The loop takes about 1.9 seconds per assessment and reaches the exact user-visible failure, so it is suitable for
RED/GREEN work.

## Ranked falsifiable hypotheses

1. **Stale assessor candidate-unit model.** Prediction: a versioned selector-specific contract will accept fair
   cardinalities 1/2/4/100 and legacy cardinality 1000 while continuing to reject altered values.
2. **Summarizer incorrectly counts fair rows.** Prediction: raw fair plans would contain 1000 round-member rows.
   Falsified: plan/root cardinalities are exactly the fixture Tenant counts.
3. **Round-membership SQL drops eligible Tenants.** Prediction: at least one distribution would be below its frozen
   Tenant count. Falsified: single/balanced/skew/many-small are exactly 1/4/2/100 across all repetitions.
4. **Fixture queue creation is incomplete.** Prediction: legacy FIFO would also be below 1000. Falsified: all 64
   legacy summaries report 1000.

## Immutability rule

The failed schema-v1 artifact and assessment stay byte-for-byte unchanged and FAILED. The fix applies only to a new
schema-v2 source and newly generated evidence. No existing manifest is regenerated.
