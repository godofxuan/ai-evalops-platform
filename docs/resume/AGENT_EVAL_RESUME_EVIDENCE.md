# Agent Eval Resume Evidence

This file maps claims to evidence. It is not a finished personal résumé. Final-hardening claims are bound to successful
GitHub Actions run [`32282462281`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/32282462281) at source
`22fda896a1b24b0cf41cd1402ead521f74758ac6`.

Current branch: `codex/final-evidence-hardening-v1`. The capability sections below are `CURRENT_POSITIVE_RESUME` when their
Known limitation is retained. Scheduler experiment/failure details are `INTERVIEW_ONLY` or `HISTORICAL_NEGATIVE`.
Production-ready, exactly-once, seven verified evaluators, all-framework/live-LangGraph, remote/OAuth MCP, atomic
PostgreSQL/S3, complete production RLS and linear-scaling statements are `FORBIDDEN`.

## Durable orchestration and recovery

**Claim**
PostgreSQL-backed Run/Job/Attempt orchestration with lease, heartbeat, fencing and Reaper recovery.

**Status**
VERIFIED on the prior `main` baseline and reverified by final-hardening CI.

**Exact code paths**
`app/jobs/claiming.py`, `app/jobs/heartbeat.py`, `app/jobs/results.py`, `app/jobs/failures.py`, `app/jobs/reaper.py`.

**Exact tests**
`tests/concurrency/test_job_claiming.py`, `tests/concurrency/test_stale_worker.py`,
`tests/concurrency/test_reaper_concurrency.py`.

**CI step**
`Integration - job claiming, trace propagation, and lease fencing`; final run `32282462281` passed.

**Known limitation**
Execution is at-least-once; external side effects can repeat. Historical 4→8 Worker performance evidence is negative.

**Safe Chinese wording**
“基于 PostgreSQL 设计 Run/Job/Attempt 持久化编排，通过租约、心跳、fencing 与 Reaper 拒绝陈旧写入并恢复过期任务。”

**Safe English wording**
“Built PostgreSQL-backed Run/Job/Attempt orchestration with lease heartbeat, fenced commits and Reaper recovery.”

**Forbidden wording**
“Exactly-once execution”, “production-ready scheduler”, “linear scaling”.

**Likely interview follow-up**
Why fencing protects database state but cannot make an external tool side effect exactly once.

## Immutable Agent artifact and evaluator evidence

**Claim**
Versioned trajectory artifacts use canonical JSON/SHA-256 identity; extractor results bind artifact, implementation
version, config SHA and metric provenance.

**Status**
VERIFIED: unit/API evidence passed locally and the real PostgreSQL/MinIO workflow passed remotely.

**Exact code paths**
`app/agent_eval/schema.py`, `app/agent_eval/service.py`, `app/agent_eval/evaluators.py`, migration
`20260820_0025_metric_provenance.py`.

**Exact tests**
`tests/unit/agent_eval/test_artifact_schema.py`, `tests/unit/agent_eval/test_evaluators.py`,
`tests/integration/test_agent_http_minio_e2e.py`.

**CI step**
`Integration - authenticated Agent HTTP PostgreSQL MinIO workflow` — run `32282462281` passed.

**Known limitation**
Current metrics are reported or derived; no extractor currently produces independently verified evidence.

**Safe Chinese wording**
“定义版本化 Agent 轨迹证据，以 canonical JSON/SHA-256 固化内容身份，并持久化实现版本、配置摘要和指标来源等级。”

**Safe English wording**
“Defined versioned Agent trajectory evidence with canonical JSON/SHA-256 identity and persisted implementation,
configuration and metric-provenance metadata.”

**Forbidden wording**
“Seven verified evaluators”, “supports every Agent framework”, “independently validates model truth.”

**Likely interview follow-up**
The difference between producer-reported, trajectory-derived and authority-verified metrics.

## Reproducible regression manifest

**Claim**
Regression gates use an explicit common-case policy, fail closed on insufficient evidence and pin artifact/result IDs.

**Status**
VERIFIED: unit/API tests and immutable PostgreSQL replay passed.

**Exact code paths**
`app/agent_eval/regression.py`, `app/agent_eval/regression_service.py`, migration
`20260820_0021_agent_regression_manifest.py`.

**Exact tests**
`tests/unit/agent_eval/test_failure_and_regression.py`, `tests/api/test_agent_regression.py`,
`tests/integration/test_agent_eval_workflow.py`.

**CI step**
`Integration - Agent evaluation, regression, and review workflow` — run `32282462281` passed.

**Known limitation**
Thresholds are caller policy, not universal quality standards; reported task success requires explicit opt-in.

**Safe Chinese wording**
“实现显式 case-set 策略和缺失证据 fail-closed 的回归门禁，并用不可变 manifest 固定每次比较使用的 artifact/result ID。”

**Safe English wording**
“Implemented fail-closed common-case regression gates and immutable manifests that pin the artifact/result identities
used by each comparison.”

**Forbidden wording**
“Universal release gate”, “latest evidence always means reproducible”, “statistically significant performance result.”

**Likely interview follow-up**
How right-only tool errors previously polluted a common-case denominator and why one latency sample is insufficient.

## MCP stdio credential revocation

**Claim**
Local MCP stdio tools revalidate scrypt API-key and tenant state per call, order revocation with shared row locks and emit
bounded audit events.

**Status**
VERIFIED for the stated local-stdio boundary: official in-memory client and real stdio subprocess/PostgreSQL tests pass.

**Exact code paths**
`app/agent_eval/mcp_server.py`, `app/agent_eval/mcp_stdio.py`, `app/agent_eval/mcp_service_adapter.py`.

**Exact tests**
`tests/unit/agent_eval/test_mcp_server.py`, `tests/integration/test_mcp_stdio_auth.py`.

**CI step**
`Integration - MCP stdio credential revocation` — run `32282462281` passed.

**Known limitation**
stdio is a local-host boundary. There is no MCP HTTP listener, OAuth resource server, network rate limiter or remote
multi-tenant MCP boundary. Environment variables can leak on the host.

**Safe Chinese wording**
“基于官方 MCP SDK 暴露本地 stdio 工具，每次调用复验 API Key/租户状态，并通过数据库锁明确撤销与在途调用顺序。”

**Safe English wording**
“Exposed local stdio tools with the official MCP SDK, per-call credential/tenant revalidation and lock-ordered
revocation semantics.”

**Forbidden wording**
“Production MCP server”, “secure remote multi-tenant MCP”, “OAuth-protected MCP HTTP endpoint.”

**Likely interview follow-up**
Why rechecking without holding a lock still leaves a revoke-versus-service race.

## Source-bound human review

**Claim**
Human Review tasks bind immutable source/packet identities and hide evaluator evidence from an unsubmitted reviewer.

**Status**
VERIFIED: packet/API tests, staged visibility and PostgreSQL source-conflict tests passed.

**Exact code paths**
`app/reviews/service.py`, `app/reviews/schemas.py`, `app/agent_eval/review_packet.py`, migration
`20260820_0022_human_review_source_identity.py`.

**Exact tests**
`tests/unit/agent_eval/test_review_packet.py`, `tests/integration/test_agent_eval_workflow.py`.

**CI step**
`Integration - Agent evaluation, regression, and review workflow` — run `32282462281` passed.

**Known limitation**
Allowlisting omits selected runtime identifiers; it does not guarantee anonymity or eliminate all reviewer bias.

**Safe Chinese wording**
“将人工评审任务绑定到不可变 source/artifact/packet 摘要，并在首轮独立判断前由服务层隐藏机器评估结论。”

**Safe English wording**
“Bound review tasks to immutable source/artifact/packet identities and withheld machine evaluation evidence until the
reviewer's independent submission.”

**Forbidden wording**
“Fully anonymous review”, “eliminated reviewer bias”, “identity-blinded in every field.”

**Likely interview follow-up**
Why `run_id + case_id` could not distinguish an ordinary result from multiple Agent artifacts.

## Object reconciliation and Agent RLS

**Claim**
Added conservative orphan-object reconciliation and RLS/composite constraints for Agent evidence tables.

**Status**
VERIFIED for tested behavior; deployment credential separation remains incomplete.

**Exact code paths**
`app/artifacts/reconciliation.py`, migrations `20260820_0023_agent_rls_constraints.py` and
`20260820_0024_artifact_reconciliation_audit.py`.

**Exact tests**
`tests/integration/test_artifact_reconciliation.py`, `tests/integration/test_agent_eval_workflow.py`.

**CI step**
`Integration - orphan artifact reconciliation` and Agent workflow — run `32282462281` passed.

**Known limitation**
PostgreSQL and S3 are not atomic. Compose does not yet separate long-lived runtime and migration-owner credentials.

**Safe Chinese wording**
“实现默认 dry-run、带 grace period 和删除前引用复查的孤儿对象 reconciliation，并为 Agent 证据增加 RLS 与复合归属约束。”

**Safe English wording**
“Implemented dry-run-first orphan reconciliation with grace-period/reference rechecks, plus RLS and composite
ownership constraints for Agent evidence.”

**Forbidden wording**
“Atomic PostgreSQL/S3 transaction”, “complete production RLS deployment”, “zero orphan objects.”

**Likely interview follow-up**
What race remains across object storage and the database, and why the system uses reconciliation instead of 2PC.

## Fixture adapter evidence

**Claim**
Fixed eight-family Custom Controller/LangGraph-callback fixture replay with source-bound JSON evidence.

**Status**
VERIFIED as deterministic fixture replay on the prior baseline.

**Exact code paths**
`app/agent_eval/benchmark.py`, `scripts/run_agent_adapter_benchmark.py`,
`docs/agent_eval/adapter_comparison_evidence.json`.

**Exact tests**
`tests/unit/agent_eval/test_benchmark.py`.

**CI step**
`Verify deterministic Agent adapter evidence`.

**Known limitation**
The recorded `0.875` success and approximately `83 ms` p95 are fixture values, not live runtime or performance data.

**Safe Chinese wording**
“构建固定八类场景的适配器契约回放，并以 source-bound JSON 固化确定性证据。”

**Safe English wording**
“Built a deterministic eight-family adapter-contract fixture replay with source-bound JSON evidence.”

**Forbidden wording**
“Benchmarked LangGraph runtime performance”, “proved faster framework performance.”

**Likely interview follow-up**
Why fixture latency cannot support a performance claim and why the historical scheduler 4→8 negative result remains.
