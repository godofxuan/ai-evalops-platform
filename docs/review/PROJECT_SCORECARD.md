# AI EvalOps Platform — Evidence-backed Project Scorecard

> This scorecard has no weighted total: mechanism, quality, scalability, and
> production evidence are non-substitutable gates.

| Category | Status | Scope |
| --- | --- | --- |
| `engineering_correctness` | `VERIFIED_CONTROLLED` | local regression plus controlled CI/PostgreSQL scheduler evidence |
| `agent_rag_quality` | `QUALITY_EVIDENCE_INSUFFICIENT` | exact-SHA interoperability only; no answer-quality delta |
| `performance_scalability` | `NEGATIVE_SCALING` | frozen q1000/sample100/batch1 controlled experiment |
| `reliability` | `VERIFIED_CONTROLLED` | bounded fault/concurrency and Final Pair contract evidence |
| `security` | `EXTERNAL_VALIDATION_REQUIRED` | mechanism tests, not penetration test or production certification |
| `evidence_sufficiency` | `QUALITY_EVIDENCE_INSUFFICIENT` | portfolio evidence is sufficient; formal quality/release evidence is not |

## Decision

- Portfolio: `READY_WITH_EXPLICIT_LIMITS`.
- Release: `NOT_READY_NEGATIVE_SCALING_AND_QUALITY_INPUT_BLOCKED`.
- Production: `NOT_VERIFIED`.

## Machine-readable details

All metric values, exact source identities, workload ratios and next gates are in
[`PROJECT_SCORECARD.json`](PROJECT_SCORECARD.json). Regenerate and verify with:

```bash
python -m scripts.project_scorecard --write
python -m scripts.project_scorecard
```
