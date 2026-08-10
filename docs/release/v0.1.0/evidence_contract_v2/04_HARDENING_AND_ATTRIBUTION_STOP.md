# Evidence contract v2 — hardening and attribution stop

## Contract changes

Schema v2 now binds three previously incomplete boundaries:

1. the assessor derives candidate cardinality independently from the raw PostgreSQL plan and checks
   it against both the producer summary and the arm-derived expected unit;
2. the targeted assessor derives queue, distribution, Worker count and batch from a full-match arm
   identity, rejects metadata drift and validates finite/domain-correct metrics with exactly four
   observations per group;
3. `empty_while_eligible` is required to be a non-boolean, nonnegative integer equal to zero in both
   per-repetition schema-v2 assessment and final targeted assessment.

These are schema-v2 rules. Schema-v1 run `31327388006` retains its original interpretation and
failure blocker.

## Concurrency boundary

True PostgreSQL run `31397416017` reproduced a false-empty transition when another transaction held
the only eligible Job row: the claimant acquired the Tenant permit, `FOR UPDATE SKIP LOCKED` returned
no Job, and the permit was committed as `EMPTY`. The minimal fix probes the same frozen eligibility
predicate without a row lock. An eligible-but-locked Job keeps the permit `PENDING`; the waiting
fallback then performs a non-`SKIP LOCKED` Job selection. Truly empty permits still become `EMPTY`.

Exact-source GREEN runs `31398322919` (push) and `31398332668` (PR) passed the real PostgreSQL durable
fairness job. This proves the tested interleaving, not universal concurrency correctness.

## Independent history replay

- `31327388006`: tree `234347cce8872b75595b2cf312baaf25b74091ce`, unchanged, schema-v1
  `FAILED`;
- `31352270523`: tree `e321f63661645f728481ef11587f94fec9a0547a`, unchanged, all four
  schema-v2 rep bundles reassessed `VERIFIED`, top-level result still `NEGATIVE_SCALING`.

The strengthened raw-plan wording is now permitted for schema-v2 evidence: candidate cardinality is
independently recomputed from the preserved raw plan under selector-specific rules. This remains a
bounded contract check, not proof against every possible evidence manipulation.

## Performance diagnostic stop

Dedicated diagnostic workflow `31400658653` completed exactly three instrumentation-OFF and three
instrumentation-ON repetitions on `fair-q1000-skew_20_to_1-w8-b1`. Its evidence commit is
`4f1fd8bf37d5b440c40684208332116f9d90de0d`; an independent audit matched all 893 manifest entries and
found no missing, extra, size-mismatched or SHA-256-mismatched file.

Throughput median changed from 30.125681 to 31.192255 Jobs/s (+3.5404%). Claim-p95 median changed
from 519.208889 to 460.437420 ms (-11.3194%). The latter exceeds the preregistered 10% absolute-change
budget, so the only valid verdict is `INSTRUMENTATION_TOO_INTRUSIVE`. Formal attribution and H1/H2/H3
assessment were skipped; all three hypotheses remain `INCONCLUSIVE`.

The stop does not modify the formal targeted verdict. v0.1.0 remains
`NOT_READY_TARGETED_NEGATIVE_SCALING`, PR #1 remains Draft, downstream gates remain
`NOT_RUN_STOPPED`, and scheduler candidate budget remains zero.
