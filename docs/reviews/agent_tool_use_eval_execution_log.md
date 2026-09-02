# Agent tool-use evaluation — execution log

Date: 2026-09-02  
Branch: `codex/agent-tool-use-eval-v1`

## Decisions

1. Preserved the existing 120-case formal sufficiency floor instead of weakening it to make the
   demo smaller. The Agent pack therefore uses six balanced categories with 20 cases each.
2. Extended the existing declarative paired runner rather than building a second harness. Dataset
   SHA, source SHAs, common-case comparison, bootstrap gates, HTML escaping and manifest behavior
   remain shared.
3. Kept Agent metrics code-registered. A tenant can select known evaluators but cannot upload and
   execute Python.
4. Made the Agent metric gate part of the product status. A formal-core pass cannot hide candidate
   tool-selection, argument, authorization, budget or error failures.

## Problems encountered and resolution

| Problem | Cause | Resolution | Effect |
| --- | --- | --- | --- |
| `uv` command unavailable | no global executable in this shell | used repository `.venv` | no system mutation |
| First Agent runner returned all failures | strict Pydantic fixture validation rejected JSON lists for tuple `tool_calls` | made runtime calls a strict list while expected calls remain immutable tuples | fixture and HTTP-shaped JSON share a valid envelope |
| Timing was measured instead of fixture latency | provider validation exception entered fail-closed fallback | fixed the envelope, retained fallback | declared fixture latency/cost is preserved; exceptions still become failed cases |

## Achieved behavior

- Versioned `QA` and `AGENT_TOOL_USE` experiment types with exact evaluator sets.
- Ordered tool-call and argument contracts plus allowlist, budget, terminal state and error fields.
- Six metrics, per-case baseline/candidate trace comparison, aggregate thresholds and status gate.
- Deterministic 120-case pack and portable escaped HTML trace report.
- Claim boundary remains `DEMO`, `HUMAN_REVIEW_PENDING`, `production_ready=false`.

## RAG native aggregate-contract consumer

During this work the RAG project published a separate WixQA negative-result contract. EvalOps now
pins publisher `7a7d0a1a8c454ff89bb8679e1b6a725ae7937fb2`, publisher CI `33605149099`,
the producer-reference bytes, source evidence `37792aa40c29c6e3accb2489bc2f7fb0da312e62`
and source CI `33603747873`. Verification against the real local producer checkout passed for the
reference SHA, artifact SHA, decision, protocol, repository-relative paths and absence of private
case payload.

The output is `AGGREGATE_EVIDENCE_VERIFIED` plus `formal_case_result_status=INPUT_REQUIRED`.
It does not create 200 `CaseResult` objects and does not turn the rejected reranker experiment into
an uplift. The source evidence CI page was independently readable as `Success`; GitHub's anonymous
page for the later publisher CI was stale at query time, so live publisher-CI confirmation remains
the producer's pinned contract plus the recorded cross-project handoff rather than a fresh API
assertion.
