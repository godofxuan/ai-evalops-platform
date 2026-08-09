# AI EvalOps Platform — cross-surface consistency

Updated: 2026-08-10

## Canonical current state

- branch: `codex/evidence-gate-1`
- Candidate 3 production source: `02f5e680e71d05c76c145da6895122a2cf04ba14`
- workflow-preserved evidence commit: `90a4e03ae75d0ae391f16f32934c144430de196d`
- ordinary CI: `31327012832`/`31327016117` PASS
- targeted: `31327388006` FAILED, `postgres_explain_candidate_cardinality_mismatch`
- release: `NOT_READY_TARGETED_EVIDENCE`
- PR: #1 Draft
- merge/tag/release: none
- scheduler development: STOP; no Candidate 4

The final docs-sync commit is intentionally not self-embedded; `git rev-parse HEAD` is authoritative for the branch
tip, while the immutable production/evidence identities above remain fixed.

## Surface comparison

| Surface | Release | Fairness | Performance | Current/historical boundary | Downstream |
|---|---|---|---|---|---|
| GitHub PR #1 | NOT_READY, Draft | rep1 `2/2/2/2` is LIMITED; targeted FAILED | not established | current Candidate 3 first; old bundles historical | capacity/same-runner/fault/formal NOT_RUN |
| README | NOT_READY | no complete fairness claim | no current SLO | historical 100k/formal/fault labeled historical | stopped |
| `RELEASE_DECISION.md` | NOT_READY | incomplete due failed bundle | rep1 diagnostics only | exact source/run/digest | NOT_RUN |
| `RESUME_SAFE_METRICS.md` | no release claim | forbidden as current positive | forbidden as current positive | classification ledger | NOT_RUN |
| `RESUME_CODEX_UPDATE.md` | NOT_READY | do not write solved | use correctness bullets only | sources/runs/limitations per claim | NOT_RUN |
| Teaching handoff | NOT_READY | teaches invariant and failure honestly | orthogonal gate | PART 53–54 source/history | STOP |
| Interview update | NOT_READY | question 26–43 cover observation/gate | no formal claim | explicit historical/current | STOP |

## Shared wording

Use this sentence when a compact current status is required:

> Candidate 3 passed ordinary PostgreSQL correctness, but source-bound targeted qualification `31327388006` failed
> its EXPLAIN candidate-cardinality evidence contract after one diagnostic repetition; v0.1.0 remains NOT_READY,
> downstream gates are NOT_RUN, and scheduler development stopped without Candidate 4.

## Facts that must never drift

1. Candidate 2 deterministic RED position is `8`; historical targeted position is `4 > 2`.
2. Candidate 3 ordinary CI is PASS at `02f5e68`.
3. Candidate 3 targeted rep1 positions `2/2/2/2` are LIMITED, not complete PASS.
4. Current targeted official blocker is `postgres_explain_candidate_cardinality_mismatch`.
5. Current capacity, same-runner, fault and formal are `NOT_RUN`, never zero and never filled by historical values.
6. Historical `-63.44%`, `41s`, `504`, `0.628 Jobs/s` remain negative history.
7. PR remains Draft; no merge/tag/release exists.
8. Resume正文 must not claim current fairness, scaling, capacity, production readiness or exactly-once.

## Verification checklist

- `git status`, branch, HEAD and remote branch are checked before handoff.
- PR title/body uses current facts first and separates historical evidence.
- README links to `fairness_redesign/11_FINAL_DECISION.md`.
- release docs and fairness-redesign docs use the same run IDs and classifications.
- resume/teaching/interview handoffs use the same stop decision.
- actual resume source versions are additive; old final DOCX/PDF and personal facts are unchanged.
