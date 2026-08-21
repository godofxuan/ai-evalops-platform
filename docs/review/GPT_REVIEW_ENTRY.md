# AI EvalOps Platform — GPT review entry

Use this page as the single entry point for an independent review. The repository is public, but reviewers should not
infer completion from the landing page alone. Follow the evidence links below and keep implemented mechanisms, executed
validation, and blocked release claims separate.

## Final handoff statement

The reviewed AI EvalOps implementation was merged into this repository's `main` branch by a conflict-free fast-forward.
The implementation evidence is bound to source commit
`ecb3c664609deca909fc8927036d1087857eacd1`. GitHub Actions run
[`32489399266`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/32489399266) completed successfully for that
exact SHA: both `quality-and-integration` and `compose-smoke` passed.

This does **not** merge the external RAG repository into EvalOps. RAG remains a separate project and is treated as a
system under evaluation through a versioned harness contract, subprocess boundary, trace propagation, and immutable
evidence artifacts.

The external A/B release decision is **`INPUT_BLOCKED`**, not `PASS`. Candidate RAG revision B exposes the required
harness contract, while frozen baseline revision A does not. A symmetric formal A/B run was therefore not executed;
quality, latency, cost, failure-rate deltas and bootstrap intervals were not fabricated. Real human review also remains
pending with zero submitted reviews.

## Frozen identities

| Item | Identity / result |
| --- | --- |
| EvalOps implementation source | `ecb3c664609deca909fc8927036d1087857eacd1` |
| Successful main CI | [`32489399266`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/32489399266) |
| RAG baseline A | `909a9710932c6c4744c462db0e33ed0d222ecb1a` |
| RAG candidate B | `e848d8e6090267b28d351758fe8d3cb557dcd586` |
| Contract dataset | 9 mechanism cases; canonical JSON SHA-256 `08ccad71d7c96cdd2d558018b480a1e421abd3781527a828793aa4430d517d11` |
| Automated A/B status | `INPUT_BLOCKED` |
| Human-review status | `PENDING`; 0 reviewers; 0 reviewed cases |
| Shadow-gate status | `INPUT_BLOCKED` |

## What was implemented and executed

- Inspect AI interoperability using pinned optional dependency `inspect-ai==0.3.259`; a real deterministic
  `inspect_ai.eval()` task was executed and its official `EvalLog` was converted into the framework-neutral artifact.
- A bounded cross-repository RAG harness client with strict JSON, timeout/output limits, exact producer SHA, case and
  W3C trace identity checks.
- Candidate RAG CLI interoperability was executed successfully, including tool events, policy decisions, trajectory
  events and propagated trace identity.
- Deterministic paired-bootstrap and common-case accounting utilities were implemented and tested, but not used to
  invent A/B metrics without comparable baseline input.
- A fail-closed shadow gate distinguishes `PASS`, `FAIL`, `HUMAN_REVIEW_PENDING`, and `INPUT_BLOCKED`.
- A two-reviewer blinded review kit and validation path were implemented; no synthetic review rows count as completion.
- The first Linux CI run exposed a Windows CRLF versus Linux LF evidence-hash mismatch. Dataset identity was corrected to
  canonical parsed JSON and regression-tested for formatting and line-ending independence.
- Final local non-integration regression recorded 845 passed and 37 deselected; Ruff and mypy passed. Exact-source main
  CI subsequently passed all workflow jobs, including external-service integration and Compose smoke.

## Required evidence reading order

1. [Repository overview](../../README.md)
2. [Current cross-layer status](../../PROJECT_STATUS.md)
3. [Detailed external-harness execution log](../external_harness/EXECUTION_LOG.md)
4. [Machine-readable automated result](../external_harness/AUTOMATED_RESULTS.json)
5. [Automated-result explanation](../external_harness/AUTOMATED_RESULTS.md)
6. [Dataset provenance and limits](../external_harness/DATASET_PROVENANCE.md)
7. [Human-review result](../external_harness/HUMAN_REVIEW_RESULTS.md)
8. [Shadow release gate](../external_harness/SHADOW_GATE.md)
9. [Inspect integration](../external_harness/INSPECT_INTEGRATION.md)
10. [Trace correlation](../external_harness/TRACE_CORRELATION.md)
11. [Production-failure matrix](../external_harness/PRODUCTION_FAILURE_MATRIX.md)
12. [Resume-safe external-harness claims](../external_harness/RESUME_SAFE_CLAIMS.md)
13. [Final-hardening report](../final_hardening/FINAL_HARDENING_REPORT.md)
14. [Project-wide claim-to-proof map](../handoffs/PROJECT_EVIDENCE_MAP.md)
15. [Forbidden resume claims](../handoffs/resume_package/FORBIDDEN_CLAIMS.md)
16. [Machine-readable review manifest](FINAL_EVIDENCE_MANIFEST.json)

## Independent-review instructions

Review code and evidence rather than accepting this summary as proof.

1. Confirm commit `ecb3c664609deca909fc8927036d1087857eacd1` exists in `main` history and CI run `32489399266`
   targets that exact SHA with both jobs successful.
2. Trace each positive claim to concrete code, tests, migrations, or immutable evidence. Mark unsupported claims clearly.
3. Treat `INPUT_BLOCKED`, `PENDING`, `NOT_RUN`, and missing metrics as honest negative/incomplete evidence, not success.
4. Check that baseline and candidate comparison inputs are symmetric before recommending any quality or performance claim.
5. Separate mechanism tests from production evidence, and deterministic fixtures from live-runtime or scale evidence.
6. Report findings by severity with file paths and line references, then list residual risks and the smallest justified next
   steps.
7. Produce a final claim table with `SAFE_NOW`, `SAFE_WITH_QUALIFIER`, `NOT_YET_SUPPORTED`, or `FORBIDDEN` for every
   proposed README, portfolio, interview, or resume statement.

## Claims that are safe now

- Built durable multi-tenant asynchronous evaluation orchestration with explicit Run, Job and lease-bound Attempt state.
- Implemented tested lease/heartbeat/version/Attempt fencing and selected crash/race recovery paths.
- Built a framework-neutral immutable Agent trajectory artifact and seven deterministic metric extractors with explicit
  reported/derived provenance; these are not seven independently verified evaluators.
- Implemented common-case, coverage and sufficiency fail-closed regression evidence.
- Added an authenticated local MCP stdio control plane with per-call credential revalidation.
- Built and executed an Inspect AI interoperability path plus a bounded cross-repository RAG harness client.
- Built a preregistered scheduler evidence gate that correctly blocked a historical v0.1.0 release when scaling evidence
  failed.

## Claims that remain unsupported

- Production-ready, production-scale, or enterprise-grade production deployment.
- Exactly-once execution, universal zero data loss, universal fairness, starvation freedom, or deadlock freedom.
- Linear Worker scaling, a solved scheduler bottleneck, or validated production capacity/SLOs.
- Improved RAG quality, groundedness, safety, latency, cost, or failure rate.
- A passed production release gate, completed human review, or any agreement/kappa result.
- Formal 100–200 case evaluation or AgentDojo integration.
- Support for every Agent framework, a live LangGraph performance benchmark, or seven verified evaluators.
- Streamable HTTP/OAuth remote MCP security, atomic PostgreSQL/S3 commits, or complete production DB-role isolation.
