# RAG formal-quality input audit

Observed on: 2026-09-02  
Mode: read-only; no RAG file, ref, index, worktree, or working-tree change was made.

## Exact remote evidence found

| Item | Observed value |
| --- | --- |
| Repository | `https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot` |
| Final branch | `codex/final-resume-readiness-closeout-v1` |
| Final remote SHA | `2065e571d77439babf76a763ac459a618950f218` |
| Exact-SHA CI supplied by the prior cross-repository closeout | GitHub Actions `32555135411`, successful |
| Producer artifact | `enterprise.agent-run/1.0` |
| Existing deterministic A/B artifact | `docs/agent_runtime/evidence/agent_runtime_ab_v1.json` |
| Existing A/B dataset | 5 fixed mechanism cases |
| Existing A/B arms | `bounded`, `langgraph` |

The producer implementation recomputes the trajectory event chain, final trajectory root, and
artifact SHA-256. EvalOps already consumes that contract through its separately verified harness
envelope and the 18-case Final Pair Contract.

## Why this is not the formal quality input

The existing five-case RAG experiment uses no generation model and a deterministic extractive
response builder. It checks answer/refusal/permission/injection behavior and reports behavioral
parity. It is valuable contract evidence, but it does not contain the preregistered 120 paired
quality cases across six categories and does not establish answer-quality uplift.

The RAG repository also records that WixQA validation and expert-written cohorts have already
been consumed, while some development candidates were rejected. Reusing those observations as
an untouched holdout or choosing a favorable historical candidate after seeing its outcome would
introduce selection bias.

## Exact inputs still required for a real formal run

The product runner can execute as soon as the following manifest is supplied:

```text
BASELINE_REPOSITORY=https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot
BASELINE_SHA=<exact 40-character serving revision>
BASELINE_ENDPOINT=<running HTTPS endpoint for that exact revision>
BASELINE_AUTH_ENV=<environment variable name; never the secret value>

CANDIDATE_REPOSITORY=https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot
CANDIDATE_SHA=<exact 40-character candidate serving revision chosen before the run>
CANDIDATE_ENDPOINT=<running HTTPS endpoint for that exact revision>
CANDIDATE_AUTH_ENV=<environment variable name; never the secret value>

DATASET_PATH=<frozen 120+ case JSON dataset>
DATASET_SHA256=<exact digest before either arm runs>
SPEND_APPROVED=<provider/model budget approval if either endpoint makes paid calls>
REVIEWER_1=<first real independent reviewer, supplied after automated execution>
REVIEWER_2=<second real independent reviewer, supplied after automated execution>
```

The baseline and candidate must serve the same frozen case set. The formal policy requires 120
common cases, 20 cases in each of six categories, 10,000 paired-bootstrap resamples, exact case
set equality, quality non-regression bounds, and latency/cost increases no greater than 25%.

## Current truthful state

```text
RAG_FINAL_CONTRACT_INPUT=VERIFIED
RAG_FORMAL_BASELINE_ENDPOINT=INPUT_REQUIRED
RAG_FORMAL_CANDIDATE_SHA=INPUT_REQUIRED
RAG_FORMAL_CANDIDATE_ENDPOINT=INPUT_REQUIRED
FROZEN_FORMAL_DATASET=INPUT_REQUIRED
PAID_MODEL_SPEND_APPROVAL=INPUT_REQUIRED_IF_APPLICABLE
AUTOMATED_FORMAL_AB=NOT_RUN
HUMAN_REVIEW=PENDING
QUALITY_IMPROVEMENT=NOT_ESTABLISHED
PRODUCTION_READY=FALSE
```

This is an actionable input boundary, not a project failure: the deterministic product demo can
verify the complete workflow without cost, while the formal mode refuses to upgrade that demo
into a real quality claim.
