# Evidence contract v2 — RED/GREEN and local validation

Date: 2026-08-10

Status: local implementation GREEN; remote qualification not yet established

## Why this stage exists

Candidate 3 did not fail targeted qualification because the 16 completed worker arms lost Jobs or violated the
frozen 20:1 fairness position. It failed because schema v1 compared two different dimensions as though both were
Jobs. The fair EXPLAIN measures eligible Tenant round members; the legacy EXPLAIN measures eligible Jobs. This stage
repairs that evidence contract without changing production scheduling or any benchmark parameter.

## Initial deterministic reproduction

The preserved schema-v1 rep1 bundle was assessed twice before code changes. Both runs returned:

```json
{"schema_version":1,"status":"FAILED","blockers":["postgres_explain_candidate_cardinality_mismatch"],"observed_arm_count":16}
```

This proved that the local feedback loop reproduced the exact remote failure. The old bundle was never rewritten.

## RED 1 — selector-specific dimensions

The first test change added a schema-v2 fixture and negative mutations before modifying the assessor.

Expected v2 positive:

- fair selector: `candidate_unit=eligible_tenant_round_members`, cardinality 1;
- legacy selector: `candidate_unit=eligible_jobs`, cardinality 1000;
- arm row: `tenant_count=1`, `queue_size=1000`.

Negative mutations covered:

- fair cardinality drift;
- legacy cardinality drift;
- missing fair unit;
- swapped or incorrect units;
- tenant count 0, 2 or 1001 for a single-Tenant arm.

Observed RED: `7 failed, 24 passed`. The positive still reported schema 1, unit mismatches were not recognized and
invalid Tenant counts were accepted. These failures matched the missing implementation rather than an unrelated
test problem.

## GREEN 1 — versioned producer and assessor

Implementation changes:

1. `scripts/release_evidence.py`
   - supports legacy schema 1 and current schema 2 explicitly;
   - preserves schema-1 queue-size semantics instead of reinterpreting old evidence;
   - requires `tenant_count` in schema 2;
   - maps fair to `eligible_tenant_round_members` and legacy FIFO to `eligible_jobs`;
   - chooses expected cardinality independently from selector and arm data;
   - emits explicit unit/count blockers and reports the evaluated manifest version.
2. `scripts/run_fair_capacity_test.py`
   - writes schema 2 in configuration and manifest;
   - records the real fixture Tenant count in every arm row;
   - writes a selector-specific unit into every raw EXPLAIN record.
3. `scripts/fair_capacity_evidence.py`
   - accepts an explicit supported manifest version;
   - keeps schema 1 as the default for callers that intentionally produce the legacy format.

Observed GREEN after this implementation: `55 passed` in the two evidence-focused unit modules.

## Problem found while extending the positive matrix

The initial four-distribution positive test failed twice for the 20:1 fixture:

1. the fixture omitted both secondary-Tenant position fields;
2. after adding them, it incorrectly set both fair and legacy positions to 2.

The existing contract intentionally requires different outcomes: fair must be at most 2, while the legacy FIFO
baseline must be greater than 2. The test was corrected to fair 2 and legacy 3. No production threshold or assessor
rule was relaxed. The resulting four-distribution matrix verified the frozen Tenant counts 1/4/2/100.

## Adversarial review and RED 2

Before committing, two additional fail-closed weaknesses were found:

1. Python `bool` is a subclass of `int`, so JSON `schema_version: true` compared equal to integer version 1;
2. schema 2 initially trusted the CSV row's queue/distribution when deriving cardinality. A corrupted package could
   change both CSV metadata and EXPLAIN values while retaining a preregistered arm ID.

Six adversarial tests were added before the second fix:

- boolean manifest version rejected by assessor;
- boolean version rejected by manifest writer;
- queue size, distribution, worker concurrency and claim batch size each spoofed independently.

Observed RED: all six tests failed. Four spoofed packages incorrectly verified; the boolean assessor case failed
for a secondary cardinality reason rather than `manifest_invalid`; the writer accepted `True`.

## GREEN 2 — arm identity binding

The assessor now parses schema-v2 expected arm IDs using the production shape:

`fair-q{queue_size}-{distribution}-w{worker_concurrency}-b{claim_batch_size}`

It independently freezes queue size, distribution, worker concurrency and claim batch size from that preregistered
ID, checks every CSV row against those values and derives expected Tenant count/cardinality from the frozen values.
The CSV can no longer self-certify those dimensions. Schema versions must be exact integers; booleans are rejected.

This stronger check exposed old unit-test-only arm names such as `...-single-...` and one test that reused the single
arm ID for every distribution. Tests were corrected to the exact production naming produced by
`build_fair_capacity_plan()`; the parser was not weakened.

Observed GREEN after hardening: `65 passed` in the focused evidence modules.

## Compatibility and immutability replay

After both fixes, the original Candidate 3 rep1 bundle was assessed again with its exact source, 16 observed arm IDs
and four expected EXPLAIN repetitions. The output remained:

```json
{"schema_version":1,"status":"FAILED","blockers":["postgres_explain_candidate_cardinality_mismatch"],"observed_arm_count":16}
```

No file below `docs/results/release/v0.1.0/targeted-gh-31327388006-1/` is modified in this change.

## Local gates

Completed before remote execution:

| Gate | Result |
|---|---|
| focused evidence tests before adversarial hardening | 59 passed |
| focused evidence tests after hardening | 65 passed |
| Ruff check | PASS |
| Ruff format check | PASS |
| MyPy on three changed source scripts | PASS |
| complete unit suite before adversarial hardening | 627 passed in 269.98s |
| complete unit suite after adversarial hardening | 633 passed in 256.97s |

Pytest repeatedly reported that `.pytest_cache` could not be written because of local Windows permissions. Test
execution and assertions completed; the warning is retained here and is not reported as a product/test failure.

## What this local GREEN does and does not prove

It proves the new package format is dimensionally explicit, source/arm bound, fail-closed under the tested
mutations, backward compatible with schema 1 and unable to convert the preserved failure into a pass.

It does not prove Candidate 3 targeted fairness or performance. Promotion still requires a pushed exact source,
ordinary GitHub CI and a new four-repetition source-bound targeted workflow. Until that remote chain passes, the
release remains `NOT_READY` and PR #1 remains Draft.
