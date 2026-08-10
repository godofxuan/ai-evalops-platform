# AI EvalOps Platform — cross-surface consistency

Updated: 2026-08-10

## Canonical current state

- branch: `codex/evidence-gate-1`;
- Candidate 3 scheduler source: `02f5e680e71d05c76c145da6895122a2cf04ba14`;
- schema-v2 qualification source: `91acdba9f5b5f1a84fb03640382c9e4871364afe`;
- evidence commit: `15bab58150385c9a39778d64a3e4163c10892ecc`;
- ordinary CI: `31351821014`/`31351825433`, both PASS;
- targeted: `31352270523`, four repetitions complete, overall `NEGATIVE_SCALING`;
- exact-workload correctness/fairness: PASS, 64 arms/6,400 Jobs, all four 20:1 vectors `2/2/2/2`;
- performance: single/balanced/20:1 fail 0.95; many-small passes;
- evidence hardening: independent raw-plan/arm/domain/no-false-empty gates PASS;
- locked eligible-Job regression: real PostgreSQL push/PR `31398322919`/`31398332668` PASS;
- attribution diagnostic: `31400658653`, `INSTRUMENTATION_TOO_INTRUSIVE`; formal H1/H2/H3
  `NOT_RUN_STOPPED`/`INCONCLUSIVE`;
- release: `NOT_READY_TARGETED_NEGATIVE_SCALING`;
- PR #1: Draft; merge/tag/release: none;
- scheduler development: STOP; no Candidate 4.

The final docs-sync commit cannot embed its own SHA. `git rev-parse HEAD` is authoritative for the branch tip, while
the immutable source/evidence identities above remain fixed.

## Surface comparison

| Surface | Release | Fairness/correctness | Performance | Downstream |
|---|---|---|---|---|
| GitHub PR #1 | NOT_READY, Draft | complete targeted PASS for frozen workload | NEGATIVE_SCALING | NOT_RUN_STOPPED |
| README | NOT_READY | 64/64 and repeated `2/2/2/2` | three ratios below 0.95 | stopped |
| `RELEASE_DECISION.md` | NOT_READY | bounded claim only | exact medians/ratios | NOT_RUN_STOPPED |
| Resume-safe metrics | no release claim | exact workload is safe with scope | negative result retained | no capacity claim |
| Teaching handoff | honest evidence repair + fair PASS | teaches bounded invariant | teaches orthogonal performance rejection | STOP |
| Attribution diagnostic | no release-state change | correctness counters stayed admissible | overhead gate failed before formal attribution | NOT_RUN_STOPPED |

## Shared wording

> Candidate 3 passed source-bound correctness and the frozen four-repetition fairness workload, but targeted run
> `31352270523` rejected four-to-eight Worker scaling in single, balanced and 20:1; v0.1.0 remains NOT_READY and
> downstream gates are NOT_RUN_STOPPED without Candidate 4.

## Facts that must never drift

1. Candidate 2 deterministic RED position is 8; Candidate 2 targeted position is 4 > 2.
2. Candidate 3 scheduler source is `02f5e68`; evidence-contract/qualification source is `91acdba`.
3. New targeted run has 4/4 verified rep bundles, 64/64 arms and 6,400/6,400 terminal Jobs.
4. Every new 20:1 position vector is `2/2/2/2`; this is a bounded workload claim, not universal fairness.
5. Current official blocker is `NEGATIVE_SCALING`, not the old cardinality mismatch.
6. Current ratios are `0.782511`, `0.772797`, `0.796214`, `1.014063`; threshold is 0.95 for every distribution.
7. Current capacity, same-runner, fault and formal are `NOT_RUN_STOPPED`, never filled by historical values.
8. Historical run `31327388006` remains the immutable schema-v1 evidence-contract failure.
9. PR remains Draft; no merge, tag or release exists.
10. No resume or teaching surface may claim production capacity, linear scaling, production readiness or
    exactly-once processing.
11. Diagnostic run `31400658653` is a preserved overhead failure, not an infrastructure failure and not
    H1/H2/H3 evidence.
12. Its OFF/ON claim-p95 median absolute change is 11.3194%, so instrumentation is not qualified.

## Verification checklist

- confirm branch/remote head and PR Draft state;
- keep run/source/evidence identities exact;
- separate bounded fairness success from performance failure;
- retain old schema-v1 failure as history;
- keep historical capacity/fault/formal classifications explicit;
- do not dispatch downstream workflows after targeted performance failure.
