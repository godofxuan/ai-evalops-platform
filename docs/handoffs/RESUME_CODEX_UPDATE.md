# AI EvalOps Platform — Resume Codex Update

Updated: 2026-08-10<br>
Branch: `codex/evidence-gate-1`<br>
Evidence HEAD before documentation closure: `90a4e03ae75d0ae391f16f32934c144430de196d`<br>
Candidate 3 production source: `02f5e680e71d05c76c145da6895122a2cf04ba14`<br>
PR: [#1 (Draft)](https://github.com/godofxuan/ai-evalops-platform/pull/1)<br>
Release: **`NOT_READY_TARGETED_EVIDENCE`**

The final documentation-sync commit necessarily cannot embed its own SHA. At handoff, run `git rev-parse HEAD` and
confirm it is at or after evidence commit `90a4e03`; do not substitute a historical source.

## Current status in one minute

Candidate 3 is the only authorized new scheduler design. It uses durable fair rounds and reusable per-Tenant state,
and its ordinary PostgreSQL correctness chain passed. Targeted run `31327388006` then failed the preregistered
release-bundle check `postgres_explain_candidate_cardinality_mismatch` after one diagnostic repetition. Stop rules
forbid Candidate 4 or downstream capacity/same-runner/fault/formal runs. PR #1 remains Draft; no tag or release.

Do not write that fair scheduling is solved. Rep1 observed 20:1 secondary position `2/2/2/2`, but the four required
repetitions did not verify. Resume正文 should use the positive correctness, state-machine, fencing and lock-diagnosis
facts below.

## Current CI, fairness and performance

| Surface | State | Evidence |
|---|---|---|
| ordinary CI | PASS | `31327012832`/`31327016117`, source `02f5e68` |
| scheduler correctness | PASS | priority, 2,000 unique claims/Attempts, crash, liveness, fencing, deadlock |
| frozen fairness | INCOMPLETE | rep1 observed `2/2/2/2`; required four repetitions not complete |
| targeted qualification | FAILED | `31327388006`; EXPLAIN cardinality contract mismatch |
| performance | NOT_ESTABLISHED | rep1 only; three diagnostic 4→8 ratios below 0.95 |
| capacity/same-runner/fault/formal | NOT_RUN | stop rule |

## Top verified positive claims

| Claim | Metric/value | Workload/protocol | Execution / Actions | Evidence path | Limitation |
|---|---|---|---|---|---|
| PostgreSQL concurrent claim correctness | 2,000 unique Jobs and 2,000 Attempts; zero first-wave empty | 20×10W/100J, `limit=1` | `02f5e68`; `31327012832`/`31327016117` | `05_RED_GREEN.md` + ordinary CI | correctness, not throughput/fairness SLO |
| durable state and stale-worker fencing | owner/version/live-expiry checks preserved; stale success/failure regressions PASS | Job/Attempt/CaseResult, lease/heartbeat/retry/reaper | `02f5e68`; ordinary CI | `app/jobs/claiming.py`, integration tests | not exactly-once or universal fault tolerance |
| deterministic concurrency diagnosis | Candidate 2 secondary receipt 8; Candidate 3 same test <=2 | Barrier/Event, 8 Worker identities, real PostgreSQL | RED `551f6b4`/`31325521253`; GREEN `02f5e68`/`31327012832` | `02_CANDIDATE2_OVERTAKE_TRACE.md`, `05_RED_GREEN.md` | test scope; complete targeted fairness failed |
| deadlock/lock-mode diagnosis | reproduced Run→Job / Job→Run cycle removed with key-preserving `FOR NO KEY UPDATE` | `pg_stat_activity`, `pg_locks`, `pg_blocking_pids`, fail-fast timeouts | `3350c23`; `31319292162`/`31319295583`; retained in Candidate 3 CI | `final_scheduler/LOCK_ORDER.md` | not proof of all possible deadlocks |
| targeted rep1 correctness | 16/16 raw arms individually VERIFIED; 1,600/1,600 terminal | queue1k, 4 distributions × 4 Worker counts, rep1 | `02f5e68`; `31327388006` | `docs/results/.../targeted-gh-31327388006-1/rep1` | overall targeted FAILED; use only as diagnostic |

## Resume wording classes

### FORBIDDEN / NOT_SAFE

- current fair scheduling solved, strong fairness, complete four-repetition fairness;
- Candidate 3 current capacity, linear scaling, performance SLO or production-ready;
- v0.1.0 READY, production-grade, exactly-once or universal deadlock freedom;
- using historical `-63.44%`, `41s`, `504`, `0.628 Jobs/s` as current numbers.

### HISTORICAL_ONLY

- `9987a28`/`31272789199` complete 1k/10k/100k capacity;
- `70a9b2b`/`31275450353` A–I ×3 fault;
- `6acf72c`/`31274490704` broken-fair formal 32-arm;
- `15e7ac2`/`31177702100` pre-fair formal scaling;
- Candidate 2 position 4 targeted failure `31319556885`.

### LIMITED

- Candidate 3 rep1 20:1 positions `2/2/2/2`;
- Candidate 3 rep1 4→8 ratios `0.678104/0.785456/0.749962/0.954809`;
- 1,600/1,600 targeted rep1 correctness inside an overall failed qualification.

### FAILED

- Candidate 3 targeted run `31327388006`: `postgres_explain_candidate_cardinality_mismatch`, zero verified
  repetitions at top level.

### NOT_RUN

- Candidate 3 current capacity, same-runner, A–I fault and formal 32-arm.

## Resume source synchronization

The current resume source workspace was unambiguous:
`D:/文档/工具/秋招冲刺_2026/resume_project_evidence_sync_20260810`. New sources were written to the sibling
`D:/文档/工具/秋招冲刺_2026/resume_scheduler_evidence_sync_20260810`, so old V1.4/V1.5 sources remain unchanged.
The new AI/RAG/Agent, Python Backend and Bank/SOE sources add only an AI EvalOps project section with correctness/
fencing/lock-diagnosis bullets; personal/contact/education/GPA/CET and the RAG project are copied unchanged. Read the
new directory's `RESUME_CHANGELOG.md` before rendering DOCX/PDF.

## Operational handoff

1. Read `fairness_redesign/11_FINAL_DECISION.md`, `06_TARGETED.md` and the saved assessment files.
2. Confirm PR Draft, current branch HEAD and current CI before editing claims.
3. Keep the current resume bullet pool conservative; do not convert diagnostic fairness into a positive headline.
4. Do not retrigger targeted/capacity/fault/formal in this stage.
5. If a future separately authorized stage repairs evidence semantics, preregister the new assessor contract before
   execution and preserve this failed bundle unchanged.
