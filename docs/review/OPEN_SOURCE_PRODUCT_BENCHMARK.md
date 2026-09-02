# Open-source product benchmark and adoption record

Observed on: 2026-09-02

This record answers a narrow engineering question: which proven ideas make AI EvalOps
easier to use without replacing its multi-tenant PostgreSQL queue, evidence contracts, or
tenant isolation with a second platform. It is a design and provenance record, not a claim
that third-party source code was copied into this repository.

## Decision summary

AI EvalOps remains an evaluation **control plane and durable execution backend**. The next
product layer will add an original, small workflow around the existing core:

1. a strict declarative experiment specification;
2. provider and evaluator protocols with built-in HTTP and deterministic demo adapters;
3. paired baseline/candidate execution with exact dataset and source identities;
4. case-level traces plus quality, latency, error, and cost comparisons;
5. a self-contained report/dashboard and a one-command demo;
6. explicit `INPUT_REQUIRED` and `HUMAN_REVIEW_PENDING` states when real credentials,
   endpoints, spend approval, or two independent reviewers are unavailable.

We will not add Temporal, ClickHouse, Kafka, or a full JavaScript frontend in this phase.
Those choices would increase deployment and maintenance cost before workload evidence shows
that the current PostgreSQL/Redis design or server-rendered report is insufficient.

## Projects reviewed

| Project | Official source | Useful product/engineering pattern | License boundary observed | Decision |
| --- | --- | --- | --- | --- |
| Langfuse | <https://github.com/langfuse/langfuse> | Trace-first debugging, dataset experiments, evaluator and prompt workflows | MIT except separately marked `ee` directories | Learn the workflow and terminology; do not copy enterprise code |
| Phoenix | <https://github.com/Arize-ai/phoenix> | OpenTelemetry traces, versioned datasets, experiments, evaluator results | Elastic License 2.0 | Concepts and interoperable telemetry only; no source copying |
| DeepEval | <https://github.com/confident-ai/deepeval> | Pytest-like evaluator interface; evaluates answers, retrieval, tools, and complete trajectories | Apache-2.0 | Learn the compact evaluator protocol; keep it optional |
| Ragas | <https://github.com/vibrantlabsai/ragas> | RAG-specific metrics, test generation, iterative feedback loop | Apache-2.0 | Provide an integration seam later; built-ins stay dependency-light |
| Promptfoo | <https://github.com/promptfoo/promptfoo> | Declarative configs, provider abstraction, CLI/CI workflow, red-team checks | MIT | Adopt the declarative workflow as an original strict Pydantic schema |
| OpenAI Evals | <https://github.com/openai/evals> | Case registry, JSON/YAML-driven evaluations, completion-function protocol | MIT (repository README) | Learn registry/protocol separation; no required runtime dependency |
| Temporal | <https://github.com/temporalio/temporal> | Durable workflow/activity semantics, retries, explicit failure handling | MIT | Retain these semantics as design checks; do not replace the current queue |

## Adopt, integrate, defer

### Adopt now as original implementation

- A versioned `ExperimentSpec` that rejects unknown fields and binds the dataset, both arms,
  evaluators, thresholds, and source revisions before execution.
- A small provider protocol. HTTP RAG/Agent endpoints and deterministic fixtures use the same
  request/result envelope, so the product can demonstrate itself without paid credentials.
- A small evaluator protocol. Deterministic reference/citation/error metrics are always
  available; model-graded metrics remain opt-in and must record model and prompt identity.
- Paired case execution and paired-bootstrap decision rules. Missing or drifting cases fail
  closed instead of disappearing from averages.
- Case drill-down with answer, citations, tool failures, latency, estimated cost, and trace ID.
- Machine-readable and human-readable reports generated from one canonical result document.

### Integrate through stable interfaces when justified

- OpenTelemetry semantic attributes for traces; this project already exports OTLP.
- Optional DeepEval/Ragas evaluator adapters after a real use case selects their metrics and
  accepts their dependency and model-call costs.
- Promptfoo import/export only if users bring existing configs; its permissive execution model
  must not become a tenant security boundary.

### Explicitly defer

- A second orchestration engine. Temporal demonstrates sound semantics, but adopting it now
  would duplicate the existing lease, retry, cancellation, and evidence work.
- A second analytics database. Current evidence does not justify ClickHouse operational cost.
- Prompt management and a general observability suite. These are adjacent products, not the
  narrow problem this release needs to solve.
- Claims of production readiness, formal human quality approval, or positive RAG uplift until
  the exact inputs and required reviewers exist and the corresponding gates pass.

## Originality and security rules

- No third-party implementation is copied by this work item.
- Licenses are checked at the official repository, and license-restricted directories are
  excluded from implementation research.
- Provider credentials are environment references, never values stored in an experiment file.
- HTTP targets continue to use the existing allowlist/SSRF controls.
- Custom evaluators are registered Python components, not arbitrary source from uploaded
  tenant configuration.
- Every external claim must point to an exact dataset hash, source SHA, result digest, and CI
  run; an ordinary green CI run is not evidence that a quality or scaling gate passed.

## Success test for this phase

A new reader must be able to run a deterministic paired experiment with one command, open a
clear report, explain why the candidate passed or failed, and replace the demo arms with two
real RAG endpoints without changing evaluation logic. If real endpoints or reviewers are
missing, the same workflow must produce a precise input manifest rather than a fabricated
`PASS`.
