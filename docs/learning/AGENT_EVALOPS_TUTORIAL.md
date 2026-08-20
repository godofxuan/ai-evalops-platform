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
code version or configuration creates distinct evidence. On a new comparison request, the service resolves the selected
artifact/result identities once, writes them into an immutable comparison manifest, and replays that manifest thereafter;
it does not dynamically merge or silently replace versions on later reads.

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

## Final hardening lessons

### An intersection count does not guarantee intersection metrics

The first comparison implementation computed `intersection_count` correctly but passed the complete left and right
maps into the metric functions. That creates a subtle numerator/denominator mismatch: a right-only tool failure can
change a gate whose denominator is described as common cases. The repaired contract materializes one sorted common
case set first, then derives success, latency, distributions, leak count and tool-error rate from that set only.

`exact` refuses different case sets. `intersection` gates the overlap and reports omissions. `allow-diff` permits the
diagnostic difference but still never mixes sets. Zero overlap, missing configured metrics, low coverage and small p95
samples produce `insufficient_evidence`, not a quiet pass.

### Resolve latest once, then pin IDs

“Latest artifact” is useful while creating a comparison, but it is not a stable evidence contract. Creation resolves
artifact and evaluator rows with `created_at DESC, id DESC`, persists every selected ID in a manifest, and stores the
report/decision snapshot. Later uploads cannot change an old comparison. Idempotency is the canonical request SHA, not
another dynamic read.

### Human review needs source identity and staged machine evidence

A case can have a normal `CaseResult` and several immutable Agent artifacts. Therefore `run_id + case_id` cannot
identify the review evidence. Tasks bind source type/record/content SHA and packet SHA; Agent tasks also bind artifact
ID/SHA. First-round reviewers receive no evaluator score, pass/fail or taxonomy. Their own submission unlocks the
machine evidence for comparison, while an unsubmitted second reviewer remains unanchored. A disputed task exposes it
to the third reviewer.

The packet is not “anonymous.” It uses explicit allowlists and omits selected runtime identifiers, tool names and
arbitrary nested metadata. Content may still identify a system through ordinary language, URLs or domain facts.

### MCP revocation is a transaction-ordering problem

Startup-only authentication leaves a long-lived Principal valid after key revocation. Per-call lookup closes most of
the gap, but a revoke can still race between lookup and service work. The stdio authorizer holds PostgreSQL shared locks
on the key and tenant through the service call. A revoke that already committed makes the new call fail; a revoke that
arrives after authorization waits for that in-flight call. This is a clear linearization point, not instantaneous
cancellation of work already authorized.

### Object storage cleanup is reconciliation, not atomic commit

An S3 put can succeed before the PostgreSQL transaction fails. The safe response is an observable reconciler: dry-run
by default, grace period, initial scan, new-transaction reference recheck, shared-SHA protection, bounded delete and an
audit row. A newly created reference before recheck blocks deletion. There is still no fictional atomic transaction
across PostgreSQL and S3.

### Reported, derived and verified are different claims

`output.task_success` and usage latency are producer-reported. Counts derived from trajectory events are derived from
the submitted record. A verified metric would need a server-owned schema, permission decision or authoritative audit
log. This revision persists provenance and deliberately produces no `verified` metric. A release gate must explicitly
opt into reported task success.
