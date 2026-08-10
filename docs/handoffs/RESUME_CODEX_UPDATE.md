# AI EvalOps Platform — Resume Codex Update

Updated: 2026-08-10<br>
Branch: `codex/evidence-gate-1`<br>
Qualification source: `91acdba9f5b5f1a84fb03640382c9e4871364afe`<br>
Evidence commit: `15bab58150385c9a39778d64a3e4163c10892ecc`<br>
PR: [#1 (Draft)](https://github.com/godofxuan/ai-evalops-platform/pull/1)<br>
Release: **`NOT_READY_TARGETED_NEGATIVE_SCALING`**

## Current status in one minute

Candidate 3 uses durable fair rounds and reusable per-Tenant state. Ordinary PostgreSQL correctness passed. After a
preregistered evidence schema repair, targeted run `31352270523` completed four verified repetitions, 64 arms and
6,400 terminal Jobs; every 20:1 w1/w2/w4/w8 vector was `2/2/2/2`. The same complete evidence rejected 4-to-8 Worker
scaling in single, balanced and 20:1. PR #1 remains Draft; no tag or release; downstream gates stopped.

## Current CI, fairness and performance

| Surface | State | Evidence |
|---|---|---|
| ordinary CI | PASS | `31351821014`/`31351825433`, source `91acdba` |
| scheduler correctness | PASS | priority, 2,000 unique claims/Attempts, crash, progress, fencing, deadlock |
| frozen targeted fairness | PASS FOR EXACT WORKLOAD | four reps; each position vector `2/2/2/2` |
| targeted correctness | PASS | 64/64 arms; 6,400/6,400 terminal; protected counters zero |
| targeted performance | NEGATIVE_SCALING | ratios 0.782511/0.772797/0.796214/1.014063 |
| capacity/same-runner/fault/formal | NOT_RUN_STOPPED | targeted performance prerequisite failed |

## Resume-safe positive claims

- Designed a PostgreSQL-backed multi-Tenant scheduler using durable fair rounds, transactional permit consumption
  and reusable per-Tenant state while preserving lease/version/result fencing.
- Built deterministic Barrier/Event concurrency regressions that reproduced an overtaking position of 8 and made
  the same application-visible receipt contract pass within position 2.
- Executed a source-bound four-repetition qualification across 64 workload/Worker arms and 6,400 Jobs with zero
  lost/duplicate/orphan/stale-accepted/illegal-transition counts; all frozen 20:1 positions were 2.
- Implemented a versioned, manifest-bound evidence contract that distinguishes eligible Tenant round members from
  eligible Jobs, rejects metadata spoofing and preserves historical failed evidence unchanged.
- Kept the release blocked when complete performance evidence showed three 4-to-8 Worker scaling regressions.

Every bullet must retain workload/evidence scope. Do not say production capacity, production-ready, linear scaling,
universal fairness or exactly once.

## Classification ledger

### VERIFIED_CURRENT

- ordinary Candidate 3 correctness at source `91acdba`;
- 4/4 targeted rep bundles, 64 arms, 6,400 terminal Jobs;
- frozen exact-workload 20:1 fairness positions `2/2/2/2` in every repetition;
- schema-v2 selector-unit/cardinality and manifest binding.

### FAILED_CURRENT

- targeted self-scaling: single `0.782511`, balanced `0.772797`, 20:1 `0.796214`; threshold `0.95`;
- overall run `31352270523`: `NEGATIVE_SCALING`.

### VERIFIED_HISTORICAL / FAILED_HISTORICAL

- capacity: `9987a28`/`31272789199`, historical only;
- A-I x3 fault: `70a9b2b`/`31275450353`, historical only;
- formal: `6acf72c`/`31274490704` and `15e7ac2`/`31177702100`, historical only;
- old schema-v1 targeted `31327388006`: cardinality mismatch, preserved failed history;
- Candidate 2 targeted `31319556885`: position 4 > 2, preserved failed history.

### NOT_RUN_STOPPED

- Candidate 3 current capacity, same-runner, A-I fault and formal 32-arm.

## Operational handoff

1. Read `evidence_contract_v2/03_REMOTE_TARGETED_DECISION.md` and the saved assessment.
2. Confirm PR remains Draft and no tag/release exists.
3. Keep fairness success and scaling failure in the same account; neither cancels the other.
4. Do not retrigger targeted or downstream workflows in this stage.
5. A future production optimization requires separately authorized deterministic diagnosis and a new candidate
   budget; this handoff grants neither.
