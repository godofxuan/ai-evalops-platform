# AI EvalOps Platform — Resume Codex Update

Updated: 2026-08-09
Branch: `codex/evidence-gate-1`
PR: [#1 (Draft)](https://github.com/godofxuan/ai-evalops-platform/pull/1)
Release decision: **`NOT_READY`**

## 1. Resume in one minute

Do not implement Candidate 3. Candidate 2 is the second and final scheduler production iteration allowed by the final
qualification sprint. The current and only v0.1.0 blocker is a failed frozen concurrent 20:1 fairness invariant:
targeted run `31319556885`, `skew_20_to_1/w8`, secondary Tenant first durable-claim completion position `4`, required
`<= 2`.

State/fencing correctness is green for all work that actually ran. Performance evidence is incomplete, because the
targeted protocol stopped during repetition 1. Current capacity, same-runner A/B/C, current A–I fault and formal
32-arm workflows were deliberately not run. Do not infer their results from historical bundles.

## 2. Identity and immutable evidence

| Purpose | Identity |
|---|---|
| final production scheduler Candidate 2 | `e4dcb5ea0a337bf234e807ccde3a01e9eb988224` |
| corrected Candidate-2 qualification source | `ed095cc338ac6708bf5d9cce71bf509b5447358e` |
| Run-guard correctness fix | `3350c2315a8a7e92e97a73218de321582294fdc8` |
| targeted attempt-2 trigger source | `246252e30e63f046a4a1fb5d684a35449aaef9e3` |
| latest preserved evidence commit before closure docs | `f1a276f` |
| targeted attempt 1 | run `31318923861`, digest `78506cf95177e9f883c47f58be1253974da52a695ff5fc620e0aa970ab581b97` |
| targeted attempt 2 | run `31319556885`, digest `ed75825c310e52d31e8c0bb54432411bd31f57f520a244462c9aefdf06f68d58` |

At resume, obtain the documentation-closure HEAD with `git rev-parse HEAD`; it is intentionally not embedded as a
self-referential SHA in this file. Confirm branch, clean worktree, PR head and latest CI before making any change.

## 3. Evidence chain and decisions

1. Historical `Tenant FOR UPDATE` integration test could wait for six hours.
2. PostgreSQL evidence showed the Job selector itself did not need Tenant; the complete durable claim blocked when a
   Tenant-referencing FK insert requested `KEY SHARE` behind the external strong lock.
3. Tests were split into selector-only, bounded negative diagnostic, `FOR NO KEY UPDATE` control and
   production-shaped overlap. Database, Python and CI timeouts now fail fast.
4. Phase A uses `FOR NO KEY UPDATE OF tenants SKIP LOCKED`; Phase B separately locks
   `evaluation_jobs FOR UPDATE SKIP LOCKED` and commits lease/Attempt/Audit/Outbox atomically.
5. The strengthened 20×10W/100J test found a false-empty path. Candidate 2 added one waiting Phase-A fallback only
   after the nonblocking path returns none and an eligibility probe proves work remains.
6. Candidate 2 passed 20 isolated drains in both CI entry points: 2,000 unique Jobs, 2,000 Attempts, no first-wave
   empty request.
7. Targeted attempt 1 found a different real deadlock: Result held Run U then waited Job; Claim held Job then needed
   Run FK KS. Result now guards Run with NKU; push/PR real-PostgreSQL CI passed.
8. Targeted attempt 2 ran without the deadlock and reconciled 1,200/1,200 Jobs, then failed the w8 20:1 fairness gate.
9. The iteration limit and fail-closed ordering require stopping before capacity/fault/formal workflows.

## 4. Resume-safe claim ledger

| Class | Metric/value | Workload | Source / Actions | Evidence | Limitation |
|---|---|---|---|---|---|
| `VERIFIED_CURRENT` | 200/200 first-wave claims, zero empty; 2,000/2,000 unique drains/Attempts | 20 × 10W/100J, `limit=1` | `ed095cc`; `31318294569`/`31318298660` | corrected CI projection and artifact digest `2b3bc253…` | correctness/availability contract, not throughput SLO |
| `VERIFIED_CURRENT` | Run NKU permits concurrent Outbox Run-FK KS | Run guard + Job/Outbox regression | `3350c23`; `31319292162`/`31319295583` | real PostgreSQL push/PR CI | proves the reproduced cycle is removed, not universal deadlock freedom |
| `VERIFIED_CURRENT` | 1,200/1,200 unique terminal, zero lost/duplicate/orphan/empty-eligible | 12 targeted arms, rep 1 | `246252e`; `31319556885` | 117 manifest-bound files, digest `ed75825c…` | run stopped before rep 2 and many-small distribution |
| `FAILED` | secondary durable claim position 4, required `<=2` | 20:1, w8 | `246252e`; `31319556885` | `failure.json`, raw arm and assessment | current and sole release blocker |
| `LIMITED` | W1/W2/W4/W8 = 12.2278/60.7611/58.4173/52.2970 Jobs/s; 4→8 `0.8952` | single Tenant, rep 1 | `31319556885` | raw targeted arm files | one repetition only; no formal verdict |
| `LIMITED` | W1/W2/W4/W8 = 44.8921/61.0428/60.9768/55.3860 Jobs/s; 4→8 `0.9083` | balanced, rep 1 | `31319556885` | raw targeted arm files | one repetition only |
| `LIMITED` | W1/W2/W4/W8 = 43.2964/53.5194/58.9625/52.5172 Jobs/s; 4→8 `0.8907` | 20:1, rep 1 | `31319556885` | raw targeted arm files | failed fairness before protocol completion |
| `LIMITED` | retry/success `0.375`, claim p95 `137.596 ms`, 8/8 unique | same Tenant, 8W diagnostic | `ed095cc`; `31318298660` | corrected Candidate-2 artifact | diagnostic sample, not repeated benchmark |
| `VERIFIED_HISTORICAL` | 1k/10k/100k complete capacity | historical capacity protocol | `9987a28`; `31272789199` | immutable historical bundle | predates final Candidate 2 and Run fix |
| `VERIFIED_HISTORICAL` | A–I ×3 = 27/27; stale success/failure accepted 0 | historical fault matrix | `70a9b2b`; `31275450353` | immutable historical bundle | not rerun on current candidate |
| `VERIFIED_HISTORICAL` | 32 arms, 16,000 jobs | broken-fair formal load | `6acf72c`; `31274490704` | immutable historical bundle | historical performance failure, not current throughput |
| `VERIFIED_HISTORICAL` | pre-fair 32-arm scaling | pre-fair baseline | `15e7ac2`; `31177702100` | immutable historical bundle | different scheduler and runner CPU |
| `NOT_RUN` | 1k/10k/100k capacity | current Candidate 2 | none | no current bundle | blocked by targeted fairness failure |
| `NOT_RUN` | A/B/C same-runner paired | current Candidate 2 | none | no current bundle | blocked by targeted fairness failure |
| `NOT_RUN` | A–I ×3 fault rerun | current Candidate 2 | none | no current bundle | blocked by qualification order |
| `NOT_RUN` | formal 32-arm / 16,000 jobs | current Candidate 2 | none | no current bundle | blocked by incomplete targeted chain |

## 5. What must not be claimed

- Do not write that v0.1.0 is READY, production-ready, production-grade or exactly-once.
- Do not claim current 1/2/4/8 formal throughput, linear scaling, production capacity SLO or strong fairness SLO.
- Do not present historical 100k `41s` claim p95, `504` retries or `0.628 Jobs/s` as current Candidate 2 metrics.
- Do not present historical pre-fair 3.1× scaling or broken-fair `-63.44%` as a same-runner current comparison.
- Do not treat four green CI runs as release readiness; they prove tests/correctness scopes, not evidence completeness.
- Do not call attempt-2 partial ratios `NEGATIVE_SCALING`; four repetitions did not complete.
- Do not erase, rewrite or overwrite either failed targeted bundle.

## 6. Allowed next action

The project should stop scheduler implementation in this sprint. The one next phase is a **concurrent-fairness-
invariant-driven scheduler redesign proposal**. It must define the fairness property under committed claim ordering,
show how it composes with `SKIP LOCKED`, reservation races and durable claim transactions, and specify RED tests and a
same-runner evidence plan before authorizing code. It must not begin as Candidate 3 or parameter tuning.

## 7. Operational handoff checklist

1. Read `final_scheduler/11_FINAL_DECISION.md`, `06_TARGETED_PERFORMANCE.md`, `LOCK_ORDER.md` and both targeted
   `failure.json`/assessment files first.
2. Run `git status`, `git branch --show-current`, `git rev-parse HEAD`, inspect PR #1 and latest CI.
3. Keep PR Draft. Do not merge, tag or create a GitHub Release.
4. If documentation-only changes are made, ordinary CI may run; do not retrigger targeted/capacity/fault/formal.
5. If a future user authorizes a new implementation cycle, start with a written invariant and RED, not retry/sleep/
   pool/batch/lease adjustments.
