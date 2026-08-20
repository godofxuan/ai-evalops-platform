# Resume Evidence Map

Current branch: `codex/final-evidence-hardening-v1`. Agent rows are `CURRENT_POSITIVE_RESUME`; scheduler experiment rows
are bounded `INTERVIEW_ONLY`/`HISTORICAL_NEGATIVE`; unsupported expansions are `FORBIDDEN`.

| Claim family | Code | Test | Artifact / decision | Boundary |
| --- | --- | --- | --- | --- |
| orchestration | `app/runs/`, `app/jobs/`, ORM models | Run idempotency, Job concurrency | targeted arms/assessment | at-least-once |
| fencing | heartbeat/results/failures | stale heartbeat/result tests | stale accepted counters | tested races only |
| recovery | Reaper/retry/cancellation | unit + dual-Reaper + fault matrix | historical A–I CSV | no SLO/deadlock proof |
| fair scheduling | `app/jobs/claiming.py` | durable fairness/parallelism | receipt vectors | frozen 20:1 only |
| false-empty | `app/jobs/claiming.py` exists probe | locked eligible Job test | RED/GREEN workflow IDs | no universal liveness |
| evidence v2 | release/targeted evidence scripts | adversarial assessor tests | 598-file manifest | integrity, not signature |
| scaling gate | assessor scripts | scaling/arm/counter tests | four ratios/decision | negative CI result |
| measurement validity | attribution/measurement/telemetry scripts | assessor/collector tests | three rejected designs | no root cause |
| Agent trajectory identity | schemas/ingestion/artifact storage | unit/API/PostgreSQL+MinIO workflow | source `22fda896`, CI `32282462281` | canonical hash is not verified truth |
| deterministic metrics | Agent evaluators/result provenance | unit/workflow tests | exactly seven kinds; reported/derived | not “seven verified evaluators” |
| common-case regression | regression + immutable manifest service | unit/API/workflow tests | case-set/coverage/sufficiency fail closed | caller policy, not universal quality |
| MCP stdio auth | MCP server/stdio/service adapter | real-process revoke integration | per-call revalidation | no remote/OAuth MCP |
| review/reconciliation/RLS | review, tenant context, reconciler | PostgreSQL/MinIO/RLS integrations | hash-bound review; compensating cleanup | no atomic stores or complete prod roles |

Detailed map: [`PROJECT_EVIDENCE_MAP.md`](../PROJECT_EVIDENCE_MAP.md).
