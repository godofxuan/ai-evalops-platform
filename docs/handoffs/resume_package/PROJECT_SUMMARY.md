# Project Summary

## 2026-09-02 usable product candidate

Branch `codex/usable-eval-product-v1`, implementation
`41de043f40c02c0d1349332c6bd19e9116202838`, adds a runnable product loop on top of the durable
control plane: strict declarative baseline/candidate specs, exact dataset/repository SHA binding,
safe provider/evaluator registries, 120-case paired bootstrap, case-level JSON/HTML comparison,
and rehashable output manifests. The tracked result is a deterministic `DEMO_PASS` whose formal
decision remains `INPUT_BLOCKED`; it does not upgrade real RAG quality, human review, scaling, or
production claims. Exact implementation CI `33589528112` succeeded, and the same implementation
SHA was non-force fast-forwarded to default `main`; the scoped product implementation claim is
therefore resume-safe while the synthetic metric values remain demo-only.

Current branch: `codex/final-evidence-hardening-v1`; implementation baseline: `22fda896a1b24b0cf41cd1402ead521f74758ac6`;
migration head: `20260820_0025`. Claim tiers are `CURRENT_POSITIVE_RESUME`, `JD_SPECIFIC_BACKUP`, `INTERVIEW_ONLY`,
`HISTORICAL_NEGATIVE` and `FORBIDDEN`.

## One-line positioning

AI EvalOps Platform is a multi-tenant asynchronous AI evaluation backend that demonstrates durable orchestration,
distributed-state correctness, framework-neutral Agent trajectory evidence and evidence-based release gating; it is
portfolio-ready, while v0.1.0 remains NOT_READY.

## Problem and flow

Local evaluation scripts need trusted tenant identity, immutable inputs, asynchronous execution, retry/recovery, auditable
results and reproducible release evidence.

```text
FastAPI -> Run -> Job -> Attempt -> Worker -> Target/Evaluator -> CaseResult -> Artifact/Evidence
```

PostgreSQL is authoritative; Redis is only a lossy event path. Execution is at-least-once. Lease owner/version/expiry and
Attempt identity fence stale writes; competing Reapers recover expired work.

The current Agent layer adds canonical JSON/SHA-256 immutable trajectory ingestion, seven deterministic metric extractors
with reported/derived provenance, manifest-pinned common-case regression, source-bound review, per-call MCP stdio
authorization, Agent evidence RLS/composite FKs and dry-run-first orphan reconciliation.

## Strongest evidence

- Frozen schema-v2 run: 64 arms, 6,400 submitted/unique/terminal Jobs, all protected correctness counters zero.
- Exact 20:1 workload: fair secondary receipt position 2 in all w1/w2/w4/w8 × four repetitions; legacy 953.
- Deterministic real PostgreSQL false-empty race: one RED and two GREEN workflows.
- Fail-closed assessor: raw EXPLAIN semantics plus 598/598 manifest rehash.

## Negative result that must remain visible

Three of four frozen 4→8 ratios missed 0.95, so release was blocked. Three instrumentation designs failed qualification;
H1/H2/H3 remain NOT_RUN/INCONCLUSIVE. PR #1 stays Draft; no tag/Release; production readiness is not verified.

Authority: [`PROJECT_STATUS.md`](../../../PROJECT_STATUS.md).
