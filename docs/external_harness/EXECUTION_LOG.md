# Detailed execution log

## 1. Identity and scope

Confirmed EvalOps base `2fdd09d21eaaf7f597f5f77a93e90c13375b7663` and created `codex/inspect-harness-and-release-gate-v1`. Confirmed RAG A=`909a9710932c6c4744c462db0e33ed0d222ecb1a`, B=`e848d8e6090267b28d351758fe8d3cb557dcd586`. Exact SHAs prevent moving-branch evidence.

## 2. RAG interface inspection

Read the candidate harness models, runner, CLI, schemas, and tests. The interface is strict JSON over stdin/stdout with deterministic and local-real modes. A tree check then found the baseline has no `harness_contract.py`; the candidate adds it. Effect: formal A/B was stopped before measurement, avoiding asymmetric evidence.

## 3. Inspect dependency and converter

Added an `inspect` group and locked `inspect-ai==0.3.259`. First test failed because the adapter module did not exist (RED); the minimal converter passed (GREEN). A real `EvalLog` Pydantic model then passed. Finally `inspect_ai.eval()` executed a deterministic Task and its official log converted successfully.

## 4. Candidate interop

Executed the RAG candidate CLI with an explicit attempt ID, exact SHA, and incoming traceparent. It returned a grounded deterministic answer, citation details, two policy decisions, tool events, a 13-event hash-chained trajectory, and matching trace identity. The first strict EvalOps producer model rejected additional real fields. Those fields were added explicitly and case/trace consistency checks were strengthened; tests then passed.

## 5. Statistics and gate

Added deterministic paired bootstrap intervals with a frozen seed, common-case digest, and explicit A-only/B-only lists. Added shadow decisions `PASS`, `FAIL`, `HUMAN_REVIEW_PENDING`, and `INPUT_BLOCKED`. Tests verify missing comparison input cannot become PASS.

## 6. Human review

The initial review test incorrectly assumed two rows per case. The RED result exposed that both reviewers must rate both A and B. The contract was corrected to four rows per case and agreement is paired by `(case, answer_label)`. No real rows were created; status remains pending.

## 7. Trace and failure behavior

Added W3C parsing into a remote OpenTelemetry Span Link, bounded low-cardinality attributes, and exporter exception isolation. Added strict subprocess JSON, timeout, output-size, Git-SHA, trace, and case identity boundaries. Production-like A/B fault scenarios remain unexecuted and are labeled accordingly.

## 8. Tooling issue

The Windows sandbox helper intermittently failed before file reads, and Git reported repository ownership differences between sandbox and desktop accounts. Read-only Git commands used a per-command `safe.directory`; global Git config was not changed. When the dedicated patch helper remained unavailable, changes were applied through verified Git patches; two precise single-file replacements were required for CRLF-affected newly added files and were immediately regression-tested.

## 9. Validation

New external-harness tests: 11 passed. Full non-integration regression: 844 passed, 37 deselected in 273.56 seconds. Full repository ruff lint passed; CI-scope mypy passed across 174 source files; uv resolved the locked 144-package graph. Human-review validation returned PENDING with zero reviewers and zero cases. The final cross-repository client smoke successfully executed candidate `e848d8e...`, preserved the supplied trace ID, validated the producer SHA, and converted two tool events into an EvalOps artifact. Frozen capability preflight returned baseline=false, candidate=true, status=INPUT_BLOCKED and exit code 2 as designed.
