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
