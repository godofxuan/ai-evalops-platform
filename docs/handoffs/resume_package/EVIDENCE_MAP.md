# Resume Evidence Map

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

Detailed map: [`PROJECT_EVIDENCE_MAP.md`](../PROJECT_EVIDENCE_MAP.md).
