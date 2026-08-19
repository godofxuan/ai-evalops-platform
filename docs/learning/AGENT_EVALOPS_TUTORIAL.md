# Agent EvalOps Tutorial

## Why Agent evaluation is not answer evaluation

An answer-only evaluator sees final text. An Agent evaluator also asks how the system reached it: which tool was
called, whether a permission was denied, whether evidence was admitted, whether a citation maps to evidence, and why
the run stopped. The trajectory is semantic execution history; OpenTelemetry is system-level distributed tracing. They
share IDs but do not replace one another.

## How this repository models it

An external runtime emits the framework-neutral `AgentRunArtifact`. EvalOps validates its schema, hashes canonical JSON,
stores the large immutable payload through the existing artifact backend, and records tenant/run/job/case metadata in
PostgreSQL. The existing Run → Job → Attempt ownership path remains responsible for durable scheduling and recovery.

## Evaluators and attribution

v1 deterministic evaluators report task-success availability, tool validity, trajectory counts, citation signals,
permission-boundary signals, terminal state, and provider-supplied cost/latency. They do not claim that fewer steps are
better, fabricate unavailable cost, or use lexical metrics as semantic truth. Failure taxonomy is evidence-led and
preserves the underlying trajectory for debugging and human review.

## Regression and human review

Compare frozen runs on common cases. A project configuration may block on task success, permission violations, latency
regression or tool-error rate, but no default threshold is advertised as industry universal. When success or grounding
lacks a reliable automatic oracle, the existing dual-review/adjudication workflow receives a blinded packet with final
answer, citations, a limited semantic trajectory and evaluator results—not model/framework identity.

Evaluator evidence is immutable and reproducible by identity: artifact ID, evaluator kind, built-in implementation
version and canonical configuration hash. Repeating an identical evaluation returns the same row; changing evaluator
code version or configuration creates distinct evidence. Run comparison currently selects the newest artifact per case
and the newest result per evaluator kind, making that selection rule visible rather than silently merging every version.

A correct permission denial is not automatically a security violation. The taxonomy may call it a permission-related
failure for diagnosis, while the release gate counts only observed unauthorized-result leakage.

## MCP development loop

The official MCP SDK v2 exposes seven stdio tools. The process requires an existing API key, validates it through the
same lookup as HTTP and binds the resulting Principal before serving calls. The MCP adapter only translates JSON tool
arguments into typed Run/Result/Agent services; it does not own SQL or accept tenant identity. HTTP is not mounted until
its authentication and deployment boundary is separately qualified.

## What the fixed benchmark proves

The eight-family fixture proves that controller events and LangGraph-style callback events can be normalized into the
same artifact and evaluated identically. It does not execute a live model or LangGraph runtime. The checked-in success
and latency numbers are fixture-derived contract evidence, not a performance comparison.

## OTel and provenance

Use `agent.session_id`, `agent.framework`, `eval.run_id`, `eval.job_id`, `eval.attempt_id`, `eval.case_id` and
`tenant_id` to correlate spans. Do not put raw prompt, document, token or secret text in attributes. Content SHA-256,
schema version, framework label and source Run/Job metadata make an artifact reproducible without making object storage
authoritative.

## Interview explanation

Explain the separation: “The Agent runtime produces a semantic trajectory; EvalOps owns scheduling, tenancy and durable
evidence. A stale Worker may execute an external action again under at-least-once semantics, but lease fencing prevents
its stale database result from replacing the current Attempt. Agent evaluators read immutable evidence rather than
changing that correctness boundary.”
