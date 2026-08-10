# Targeted Assessor Fail-Closed Hardening

## Original problem

The repeated targeted assessor checked the expected arm-ID set, but grouped observations using CSV
`distribution` and `worker_concurrency`. It did not fullmatch each arm ID and compare q,
distribution, Worker and batch with CSV. `_number()` also accepted NaN, positive/negative Infinity,
zero/negative throughput and domain-invalid rates/counts.

## RED evidence

Commit `03bc78a` added named tests for NaN, ±Infinity, zero/negative throughput, bool numeric values,
all four metadata dimensions, complete arm-set spoofing, exact four observations per group and
domain-invalid latency/count/rate values. The initial focused run was 24 failed / 47 passed.

One test idea was corrected during GREEN: spoofing Worker metadata cannot legitimately create an
observation-count failure once grouping uses the arm-derived Worker. The exact-count test was
changed to duplicate one complete arm in one repetition, which produces five observations while
preserving the observed arm set. This tests the intended invariant rather than the unsafe old
grouping method.

## Minimal repair

Commit `5c5ed31` added a local fullmatch grammar and derives q/distribution/Worker/batch from every
arm ID. CSV metadata must exactly equal that contract. Aggregation uses the derived contract, never
the untrusted CSV grouping values.

Numeric fields are validated by domain:

- `jobs_per_second`: finite and strictly positive;
- latency and CPU-like values: finite and nonnegative;
- counts: nonnegative integers, with bool rejected;
- reservation miss rate: within `[0, 1]`;
- each group/metric: exactly four observations.

The first GREEN was 19 passed / 1 failed; the one remaining failure was the intentionally separate
P1-03 nonzero false-empty test. Ruff passed.

## Trade-off and public claim

Strict validators may reject a newly added metric until its numeric domain is explicitly
registered. That is preferable to allowing NaN to corrupt medians or metadata to move a result to a
different group. This supports a fail-closed targeted assessor for its registered schema; it does
not prove benchmark truth outside the bound source/workload/evidence chain.
