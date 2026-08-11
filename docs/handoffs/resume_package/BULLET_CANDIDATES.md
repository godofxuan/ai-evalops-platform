# Bullet Candidates

Select three primary bullets from one role family; two backups are replacement inventory, not extra resume content.

## AI Evaluation

1. Built a multi-tenant async AI evaluation backend binding immutable inputs/target/evaluator identities into auditable Run→Job→Attempt→Result workflows.
2. Designed a fail-closed evidence contract independently assessing raw PostgreSQL plans and manifests across 64 arms/6,400 Jobs with zero protected violations.
3. Built a preregistered performance gate that blocked v0.1.0 when 3/4 frozen 4→8 workloads missed 0.95.
4. Backup: stopped causal attribution after three measurement systems exceeded the frozen validity budget.
5. Backup: built reproducible evaluators, metrics, comparison and human-review flows.

## Python Backend

1. Engineered a FastAPI/PostgreSQL Run/Job/Attempt backend with fenced result/artifact transactions and lossy Redis notifications.
2. Fenced stale Workers by owner/version/live-expiry/Attempt; zero stale success/failure accepted in the frozen 6,400-Job run.
3. Implemented competing `SKIP LOCKED` Reapers and bounded retry; historical A–I matrices recorded 54/54 successful repetitions.
4. Backup: tenant-derived identity, immutable Dataset Versions and consistency constraints, with explicit RLS limitation.
5. Backup: SHA-256 blob/reference artifact model and S3-compatible path with cross-system atomicity limitation.

## Distributed Systems

1. Modeled at-least-once execution using durable Job/Attempt generations and lease-version fencing.
2. Deterministically reproduced and fixed a real PostgreSQL `SKIP LOCKED` false-empty permit race (one RED, two GREEN).
3. Built a durable fair round whose frozen 20:1 secondary receipt position was 2 in every observation, versus legacy 953.
4. Backup: coordinated Worker/Reaper transitions with zero protected violations across frozen 64-arm evidence.
5. Backup: independently parsed raw EXPLAIN candidate nodes and rehashed 598/598 evidence files.

## Reliability / Infrastructure

1. Automated fail-closed CI gates for source/workload/plan/counter/manifest integrity.
2. Enforced a stop rule that preserved NEGATIVE_SCALING, Draft PR and untagged v0.1.0.
3. Rejected three instruments after 11.3194%, 13.4906% and 28.0396% absolute claim-p95 perturbation exceeded 10%.
4. Backup: 54/54 historical controlled fault repetitions with zero recorded violations.
5. Backup: structured/redacted logging, metrics, tracing and readiness without production-operation claims.

Canonical full wording: [`RESUME_CODEX_HANDOFF.md`](../RESUME_CODEX_HANDOFF.md).
