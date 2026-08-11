# AI EvalOps Platform — Recruiter Summary

## 15 seconds

I built a multi-tenant asynchronous AI evaluation backend that emphasizes durable job orchestration, concurrency
correctness and evidence-based release decisions—and its release gate deliberately blocked v0.1.0 when the frozen
scaling contract failed.

## 30 seconds

The system turns an API request into a Run, durable Jobs and lease-bound Attempts, then persists evaluator results and
artifacts through fenced transactions. In a frozen 64-arm/6,400-Job experiment, all protected correctness counters were
zero and the exact 20:1 fairness contract passed; however, 3/4 4→8 Worker scaling ratios missed the 0.95 gate, so the
release remains `NOT_READY`.

## 90 seconds

**Problem:** turn local AI evaluation scripts into an auditable multi-tenant asynchronous backend.

**System:** FastAPI creates immutable evaluation Runs and Jobs; PostgreSQL is the state authority; Workers claim with
leases and Attempts, heartbeat while executing, and commit results through owner/version/expiry fencing; Reapers recover
expired work; Redis is only a lossy notification path.

**Concurrency challenge:** a durable fair scheduler had a `SKIP LOCKED` false-empty race: when the only eligible Job was
temporarily locked, the old path consumed the tenant permit as empty. A deterministic real-PostgreSQL RED test reproduced
it; an independent existence probe preserved the permit as pending and the GREEN runs passed.

**Evidence:** the frozen schema-v2 targeted run covered 64 arms and 6,400 submitted/unique/terminal Jobs with zero
protected correctness violations; every 20:1 fair receipt-position vector was `2/2/2/2`.

**Negative scaling:** only one of four 4→8 workload ratios met the frozen 0.95 threshold.

**Release decision:** v0.1.0 is intentionally `NOT_READY`. Three observer/telemetry designs also failed measurement
qualification, so I stopped H1/H2/H3 attribution instead of presenting an unsupported root cause. This is the project’s
central reliability and evidence-engineering story—not a claim of production readiness.

## Positioning boundary versus the RAG project

- **AI EvalOps Platform:** distributed backend, job orchestration, multi-tenancy, concurrency, fencing, release evidence
  and measurement discipline.
- **RAG project:** retrieval, grounding, citation, agent/guard behavior and multi-document failure attribution.

Do not describe both as generic “enterprise AI systems”; they demonstrate different engineering capabilities.
