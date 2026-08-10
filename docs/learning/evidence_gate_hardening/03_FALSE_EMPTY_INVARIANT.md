# No-False-Empty Invariant

## Gap

`empty_while_eligible` was measured by the runner and named in Candidate 3 preregistration, but it
was neither a required schema-v2 release CSV field nor a zero-correctness blocker in the final
targeted assessor. Merely exporting a metric does not make it a gate.

## RED/GREEN

RED covered schema-v2 nonzero, missing and bool values; targeted nonzero; schema-v1 missing-field
compatibility; and the real historical schema-v1 failed rep bundle. Before the fix, schema v2 with
nonzero/missing/bool all returned `VERIFIED`.

Commit `0bcd162` made schema-v2 parse the field as a nonnegative integer and require zero. Missing or
invalid values emit `empty_while_eligible_invalid`; nonzero emits
`empty_while_eligible_nonzero`. The targeted assessor applies the same distinction to every arm.
Schema v1 does not gain a new required field.

The combined evidence suites then passed 71/71. The actual schema-v1 rep from workflow
`31327388006` remained schema 1, status FAILED, with its original
`postgres_explain_candidate_cardinality_mismatch` and no new false-empty blocker.

## Effect and trade-off

New schema-v2 evidence produced without the field now fails closed. This is intentionally stricter
and may reject old schema-v2-like ad hoc files; immutable official schema-v2 evidence already
contained zero and continued to verify. The result supports “no false empty observed in the frozen
gated arms,” not universal starvation freedom.
