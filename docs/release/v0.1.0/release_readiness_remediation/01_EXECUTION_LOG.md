# Release Readiness Remediation — execution log

## 2026-09-02 — Stage opened

### Starting state

- Created `codex/release-readiness-remediation-v1` from clean default
  `main@aea8044061e678fb8e0d5312222987c5499ea83d`.
- Confirmed the RAG working tree contains unrelated in-progress changes. It is read-only for this
  stage and cannot supply formal input until a clean exact SHA and successful CI exist.
- Confirmed the local EvalOps environment has Python 3.12 but no Docker or `psql`.

### Quality-gate implementation

- Added strict, versioned baseline/candidate case contracts with exact Git and dataset SHA binding.
- Added exact common-set and category-drift checks.
- Added paired bootstrap intervals for task success, citation correctness and tool error rate.
- Added paired bootstrap p95 latency and mean-cost comparisons.
- Added a policy-driven fail-closed decision that reuses the existing `FormalEvidenceDecision` and
  cannot silently promote insufficient evidence.
- Added deterministic blinded packets with a separately stored unblinding map. The blinding key is
  accepted only through `EVALOPS_REVIEW_BLINDING_KEY_HEX`, not a command-line argument.
- Added two empty reviewer CSV templates; synthetic unit data never becomes review evidence.

### Problems encountered and decisions

1. Strict Pydantic validation rejected JSON arrays for an internal tuple after JSON was first
   converted to a Python dictionary. The CLI now validates the original JSON text directly, which
   preserves strict Python validation while correctly interpreting JSON arrays.
2. The first blind-packet test embedded the words `baseline` and `candidate` inside synthetic answer
   text. That tested answer content rather than metadata leakage. The fixture was corrected; the
   packet continues to exclude source-arm identity and keeps mapping in the restricted file.
3. Pytest cannot write `.pytest_cache` in this workspace and reports a warning. Tests themselves run
   from the virtual environment and pass; no permission workaround or global configuration change
   was made.

### Verification so far

- `tests/unit/external_harness/test_formal_quality.py`: 3 passed.
- `tests/unit/scripts/test_formal_agent_quality.py`: 2 passed.
- Ruff: passed for the new quality files.
- mypy strict: passed for the new quality implementation and CLI.

No formal A/B, human review or scheduler rerun has occurred yet. Current release status is unchanged.

## 2026-09-02 — Performance route correction before candidate code

The first draft proposed another external PostgreSQL observer. A full historical read showed that
the repository already implemented and remotely qualified that exact architectural direction. The
passive 5 Hz observer changed claim p95 by an absolute 28.039623%, so it was correctly marked
`MEASUREMENT_SYSTEM_INVALID`; synchronous observers had already failed at 11.3194% and 13.4906%.

Repeating the same idea would violate the existing stop rule. The stage therefore switched to one
pre-registered, uninstrumented candidate: remove the extra active-round existence query from the
successful Claim common path by trying a pending permit first. This is a falsifiable transaction-
overhead hypothesis, not a claimed root cause. The unchanged targeted gate remains the only remote
performance decision.

## 2026-09-02 — Single scheduler candidate implemented

### Red test and observed cause

Three new control-flow tests first failed because both non-blocking and waiting Claim paths emitted
`ensure-round` before their first permit claim. This reproduced the exact extra round-trip described
in the preregistration without relying on timing or a local PostgreSQL installation.

### Minimal change

Both paths now attempt to claim an already-created active permit first. Only an empty result enters
the existing round-creation check and retries the same claim operation. No query definition, lock
mode, ordering, state transition, retry policy, schema or benchmark threshold changed.

### Local effect and validation

- Existing-permit paths now emit one claim operation and no round-existence operation.
- Missing-permit paths still emit claim, ensure-round and claim in that order.
- Focused claiming/fair-round regression suite: 22 passed.
- Full local non-integration suite: 913 passed, 39 external-service tests explicitly deselected.
- Ruff and strict mypy: passed for the candidate and its tests.
- Pytest still reports only the known workspace `.pytest_cache` permission warning.

### Remote feedback-loop design

A new branch-scoped workflow runs the real PostgreSQL concurrency suites and four unchanged
q1000/sample100/batch1 repetitions. It has `contents: read`, writes output only beneath the runner
temporary directory and uploads a 90-day Artifact even when assessment fails. A final step fails
the workflow only after upload, so a negative result remains inspectable and cannot cause a bot
commit or an unreviewed branch mutation.

## 2026-09-02 — Exact-SHA remote decision

- Candidate source: `5687fbdfcd0835ffdf1f1884ddaa27f8c411eb51`.
- Ordinary CI [33584967564](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33584967564): success, including both jobs.
- Targeted run [33584967622](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33584967622): intentional failure after evidence upload.
- All four repetitions, concurrency regressions, assessment, Artifact upload and cleanup succeeded.
- Assessment: `NEGATIVE_SCALING`; ratios single `0.704519`, balanced `0.791907`, 20:1
  `0.706258`, many-small `0.863996`, required floor `0.95`.
- Artifact `release-readiness-targeted-33584967622-1` contains four repetitions and 598/598
  top-level Manifest-bound files with matching size and SHA-256.

The common-path round-trip hypothesis is therefore insufficient. Per the preregistered stop rule,
there is no second candidate or threshold change. `main`, release, production and resume-positive
claims are unchanged. Detailed evidence and the next diagnosis boundary are in
[`02_TARGETED_RESULT.md`](02_TARGETED_RESULT.md).
