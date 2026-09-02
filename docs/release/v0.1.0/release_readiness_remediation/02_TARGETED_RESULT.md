# Release Readiness Remediation — targeted scheduler result

Decision date: 2026-09-02 (Asia/Shanghai)

## Decision

`NEGATIVE_SCALING`. The single preregistered claim-first candidate did not resolve the frozen
four-to-eight Worker regression and must not be merged into `main` as a performance fix.

The workflow's red status is an intentional release-gate rejection, not an execution or
infrastructure failure. Every preparation, PostgreSQL concurrency regression, benchmark repetition,
assessment, Artifact upload and cleanup step succeeded. Only the final post-upload enforcement step
failed because the assessment was not `VERIFIED`.

## Exact identities

| Item | Exact value |
| --- | --- |
| Candidate source | `5687fbdfcd0835ffdf1f1884ddaa27f8c411eb51` |
| Ordinary CI | [run 33584967564](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33584967564) — success |
| Targeted gate | [run 33584967622](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33584967622) — intentional failure |
| Artifact | `release-readiness-targeted-33584967622-1`, ID `9829874030`, 90-day retention |
| Artifact top-level Manifest SHA-256 | `9ccbc722eed4331940356e4b786c8291a5946ed70f225457f046206d4e449828` |
| Assessment source binding | exact candidate source, four repetitions |

The downloaded Artifact contained exactly the 598 files declared by its top-level Manifest; every
declared byte size and SHA-256 matched. A first diagnostic attempt reused a bundle verifier that
intentionally ignores every nested file named `manifest.json`, so it reported four false file-set
mismatches for the repetition manifests. Rechecking the top-level contract with only the top-level
Manifest excluded produced 598/598 set, size and digest matches. The verifier was not changed and no
evidence file was repaired or overwritten.

## Frozen 4→8 result

Protocol: q1000, sample100, batch1, four workload distributions, Workers 1/2/4/8, four exact
repetitions, self-scaling floor `0.95`.

| Distribution | Median w4 Jobs/s | Median w8 Jobs/s | w8/w4 | Result |
| --- | ---: | ---: | ---: | --- |
| single Tenant | 23.682351 | 16.684666 | 0.704519 | `NEGATIVE_SCALING` |
| balanced multi-Tenant | 50.284600 | 39.820725 | 0.791907 | `NEGATIVE_SCALING` |
| 20:1 skew | 38.835274 | 27.427739 | 0.706258 | `NEGATIVE_SCALING` |
| many small Tenants | 63.041586 | 54.467687 | 0.863996 | `NEGATIVE_SCALING` |

The assessment's only failures were the four negative-scaling decisions. The ordinary PostgreSQL
correctness/fairness regressions passed, all 16 assessment groups contained four observations and
`empty_while_eligible` remained zero.

## What the evidence says about the hypothesis

Trying an existing permit before round creation removes the targeted extra round-trip in deterministic
control-flow tests, but it is not sufficient to make w8 self-scale. The data rejects the claim that
this round-trip was the dominant release blocker.

- single Tenant w4→w8: claim p95 rose from 462.83 ms to 1352.84 ms, contention retries from 281 to
  549 and waiting fallbacks from 164 to 303;
- balanced: claim p95 rose from 58.45 ms to 470.06 ms and previously absent retries appeared;
- 20:1: claim p95 rose from 228.20 ms to 886.04 ms, with retries and fallbacks both more than doubling;
- many-small: no contention retries, waiting fallbacks or observed PostgreSQL lock waiters appeared,
  yet reservation/job-claim p95 and throughput still regressed at w8.

This supports a future diagnosis that separates hot-state contention from broader transaction,
connection or runner/topology saturation. It does **not** prove which of those mechanisms is causal;
worker CPU was already about 91–97% in the compared arms and the run was not a qualified causal A/B.

## Stop decision and project state

The preregistered budget allowed one candidate. Therefore:

- no second scheduler candidate, threshold change, benchmark retry or post-result tuning is made;
- `main` is unchanged and the failed candidate is not promoted;
- performance remains `NEGATIVE_SCALING`;
- formal RAG/Agent quality remains `QUALITY_EVIDENCE_INSUFFICIENT` until real exact-source arm outputs
  and two real blinded reviewers exist;
- portfolio remains `READY_WITH_EXPLICIT_LIMITS`, release remains
  `NOT_READY_NEGATIVE_SCALING_AND_QUALITY_INPUT_BLOCKED`, and production remains `NOT_VERIFIED`.

The failed hypothesis is still useful engineering evidence: it narrows what is not sufficient and
demonstrates a controlled stop rule. It is an interview diagnosis story, not a positive throughput
claim for a resume.
