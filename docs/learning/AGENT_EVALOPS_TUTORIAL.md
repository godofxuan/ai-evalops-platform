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
