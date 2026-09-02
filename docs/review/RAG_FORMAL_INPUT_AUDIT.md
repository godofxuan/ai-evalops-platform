# RAG formal-quality and aggregate-evidence input audit

Observed on: 2026-09-02  
Mode: read-only; no RAG file, ref, index, branch, worktree, or working-tree change was made.

## Current exact RAG main

| Item | Observed value |
| --- | --- |
| Repository | `https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot` |
| Current public branch | `main` |
| Exact remote SHA | `bd71cb3ca8de4e1899a4ea0e09d3c1c677c77a7e` |
| Exact-SHA CI | GitHub Actions [`33588082333`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/33588082333), completed successfully |
| Successful CI jobs | Windows deterministic, Ubuntu deterministic, PostgreSQL checkpointer integration, Linux container contract |
| R5 public artifact | `docs/r5/evidence/uda_finance_r5_public_v1.json` |
| R5 artifact SHA-256 | `97aa582d996194171004964acfbda46732f685998dd3227b3730a8b778c404ce` |

The remote ref, exact workflow head SHA and all four job conclusions were independently read.
The local RAG checkout was clean and matched the remote main, and its public R5 artifact matched
both the exact commit and declared byte digest. The older `2065e571...` producer remains a valid
historical Final Pair input, but it is no longer the current RAG main.

## Real R5 aggregate evidence found

R5 is a frozen, one-shot comparison on all 41 remaining eligible companies and 192 public-label
questions that were not used by earlier UDA rounds. It compares Dense retrieval with a fixed
Dense + original BM25 + focused BM25 page-fusion candidate for known finance-report page
localization.

| Metric | Baseline | Candidate | Observed change |
| --- | ---: | ---: | ---: |
| Page Hit@5 | 80.21% | 88.02% | +7.8125pp |
| Page nDCG@5 | 70.95% | 77.60% | +6.6459pp |
| Misses | 38 | 23 | -39.47% relative |
| p95 latency | 130.04 ms | 137.60 ms | 1.058x |

The paired table contains 154 both-hit, 15 candidate-only rescue, 0 baseline-only hit and 23
both-miss observations. Company-cluster bootstrap lower bounds are +4.10pp for Hit@5 and
+3.32pp for nDCG@5. Every source-side preregistered gate is `true`.

This supports only a public-label, fresh-company, known-report **page-localization** claim. It is
not answer accuracy, a blind or third-party benchmark, open-corpus document discovery, or a
general production-readiness result. “88.02%” must be called Hit@5, never “RAG accuracy 88%”.

## EvalOps external aggregate verification

EvalOps now has a fail-closed aggregate evidence verifier:

```powershell
./.venv/Scripts/python.exe -m scripts.verify_external_aggregate_evidence `
  benchmarks/external_evidence/rag_r5_reference.json `
  <exact-rag-checkout>/docs/r5/evidence/uda_finance_r5_public_v1.json `
  --output artifacts/rag-r5-verification.json
```

The verifier binds repository/source/CI references, raw artifact SHA-256, artifact schema,
producer code revision, protocol digest, evaluation scope, case counts, paired accounting,
Hit@5 arithmetic, nDCG/Hit confidence intervals, latency ratio, source gates and claim limits.
It recursively rejects private/per-case payload keys. The checked-in verification record is
[`verification.json`](../results/rag_r5_external_evidence/verification.json).
The implementation SHA `5f6aa5a996062d4423b94aa4f7c2a15c38fd41b3` passed exact-main
CI [`33592493933`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33592493933).

Observed result:

```text
AGGREGATE_EVIDENCE=VERIFIED
FORMAL_CASE_RESULTS=INPUT_REQUIRED
FORMAL_AB_BY_EVALOPS=NOT_RUN
FORMAL_QUALITY_CLAIM_ALLOWED=FALSE
HUMAN_REVIEW=PENDING
PRODUCTION_READY=FALSE
```

This is useful because EvalOps can accept and audit a real external aggregate without pretending
it executed the underlying cases. Offline byte verification binds the CI reference but does not
query GitHub; the live exact-SHA CI status above was separately checked out of band.

## Why this still is not an EvalOps formal case-level A/B

The public R5 JSON intentionally excludes questions, answers, company/document identities,
paths and per-case failures. It contains hashes and aggregates, not 192 baseline/candidate
`CaseResult` pairs. Manufacturing those rows from totals would destroy traceability and paired
review semantics, so the importer refuses to promote aggregate evidence into formal results.

The historical RAG `2065e571...` / EvalOps `4040fa1d...` Final Pair remains 18 mechanism cases
and 15 converted/source events. It verifies interoperability, not current R5 quality and not the
new 120-case answer-quality policy.

## Exact inputs still required for a real EvalOps formal run

```text
BASELINE_REPOSITORY=https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot
BASELINE_SHA=<exact 40-character serving revision chosen before the run>
BASELINE_ENDPOINT=<running HTTPS endpoint for that exact revision>
BASELINE_AUTH_ENV=<environment variable name; never the secret value>

CANDIDATE_REPOSITORY=https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot
CANDIDATE_SHA=<exact 40-character serving revision chosen before the run>
CANDIDATE_ENDPOINT=<running HTTPS endpoint for that exact revision>
CANDIDATE_AUTH_ENV=<environment variable name; never the secret value>

DATASET_PATH=<frozen 120+ case JSON dataset with permitted per-case access>
DATASET_SHA256=<exact digest before either arm runs>
SPEND_APPROVED=<provider/model budget approval if either endpoint makes paid calls>
REVIEWER_1=<first real independent reviewer after automated execution>
REVIEWER_2=<second real independent reviewer after automated execution>
```

Both arms must serve the same frozen case set. The formal policy requires 120 common cases, 20
in each of six categories, 10,000 paired-bootstrap resamples, exact case-set equality, candidate
absolute quality/error thresholds, non-regression bounds, and latency/cost increases no greater
than 25%.

## Audit problems and resolution

The first audit used the then-current final branch `2065e571...`; a later cross-project update
made `main@bd71cb3...` authoritative, so the audit was reopened instead of preserving a stale
claim. During inspection, guessed `docs/r5/RESULTS.md` and `PROTOCOL.md` paths did not exist.
The tree was enumerated rather than assuming filenames, revealing the real sources:
`ENGINEERING_JOURNAL.md`, `uda_finance_r5_protocol_v1.json` and
`uda_finance_r5_public_v1.json`.

## Current truthful state

```text
RAG_CURRENT_MAIN_IDENTITY=VERIFIED
RAG_CURRENT_MAIN_CI=SUCCESS
RAG_R5_PUBLIC_AGGREGATE=VERIFIED
RAG_R5_PER_CASE_PAYLOAD=NOT_PUBLIC_AND_NOT_IMPORTED
RAG_HISTORICAL_FINAL_PAIR=VERIFIED_AT_OLDER_SHA
RAG_FORMAL_BASELINE_ENDPOINT=INPUT_REQUIRED
RAG_FORMAL_CANDIDATE_ENDPOINT=INPUT_REQUIRED
FROZEN_FORMAL_CASE_DATASET=INPUT_REQUIRED
AUTOMATED_FORMAL_AB_BY_EVALOPS=NOT_RUN
HUMAN_REVIEW=PENDING
EVALOPS_QUALITY_IMPROVEMENT=NOT_ESTABLISHED
PRODUCTION_READY=FALSE
```
