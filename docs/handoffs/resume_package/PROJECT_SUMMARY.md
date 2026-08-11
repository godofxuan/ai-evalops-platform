# Project Summary

## One-line positioning

AI EvalOps Platform is a multi-tenant asynchronous AI evaluation backend that demonstrates durable orchestration,
distributed-state correctness and evidence-based release gating; it is portfolio-ready, while v0.1.0 remains NOT_READY.

## Problem and flow

Local evaluation scripts need trusted tenant identity, immutable inputs, asynchronous execution, retry/recovery, auditable
results and reproducible release evidence.

```text
FastAPI -> Run -> Job -> Attempt -> Worker -> Target/Evaluator -> CaseResult -> Artifact/Evidence
```

PostgreSQL is authoritative; Redis is only a lossy event path. Execution is at-least-once. Lease owner/version/expiry and
Attempt identity fence stale writes; competing Reapers recover expired work.

## Strongest evidence

- Frozen schema-v2 run: 64 arms, 6,400 submitted/unique/terminal Jobs, all protected correctness counters zero.
- Exact 20:1 workload: fair secondary receipt position 2 in all w1/w2/w4/w8 × four repetitions; legacy 953.
- Deterministic real PostgreSQL false-empty race: one RED and two GREEN workflows.
- Fail-closed assessor: raw EXPLAIN semantics plus 598/598 manifest rehash.

## Negative result that must remain visible

Three of four frozen 4→8 ratios missed 0.95, so release was blocked. Three instrumentation designs failed qualification;
H1/H2/H3 remain NOT_RUN/INCONCLUSIVE. PR #1 stays Draft; no tag/Release; production readiness is not verified.

Authority: [`PROJECT_STATUS.md`](../../../PROJECT_STATUS.md).
