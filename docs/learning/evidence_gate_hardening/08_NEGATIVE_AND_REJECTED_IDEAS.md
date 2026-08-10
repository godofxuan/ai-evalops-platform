# Negative and Rejected Ideas

## Wrong Python environment

The first full pytest used system Python 3.13.5 and produced 51 import/config collection errors.
`pip check` on that interpreter passed, demonstrating why a green dependency command can still
describe the wrong environment. The locked `.venv` Python 3.12.13 was used thereafter.

## Reusing producer EXPLAIN summarization

Rejected because producer and assessor would share the same bug. A maximum-rows-anywhere parser was
also rejected because fair and legacy candidate units live at different plan nodes.

## Metadata spoof as observation-count test

The initial test changed CSV Worker metadata. Once grouping correctly derives Worker from arm ID,
that cannot change the group count. The test was replaced by a duplicated complete arm, which
directly produces five observations.

## Always retain PENDING after no row

Rejected because a genuinely stale permit would leak and a fast retry could spin forever. The final
design probes eligibility and makes the waiting fallback block on the Job row.

## New deferred state

Rejected because existing PENDING can express the temporary condition when paired with a blocking
fallback. Adding schema/migration/recovery semantics was unnecessary.

## First concurrency GREEN placement

The new helper was inserted before the old builder's priority/return tail, producing three unit
failures plus Ruff/mypy errors. The function boundary was corrected; no algorithm change was made.

## CI log credential workarounds

Unauthenticated job-log download returned 403. PowerShell 5.1 piping and old .NET process encoding
prevented safe credential-helper input. After bounded attempts, log download was abandoned; step
verdicts and the deterministic code/test path were retained without exposing credentials.

## High-cardinality Prometheus labels

Rejected. Per-claim samples stay in experiment artifacts; Tenant/Job/Run/Attempt identifiers do not
become labels.

## Interval-only pg_locks attribution

Not adopted because short lock waits can occur between samples and query/identity correlation would
raise overhead or cardinality. Stage timings and deterministic counters are used first. This means
the experiment can support a stage hypothesis but not name every blocking transaction.

## Treating a favourable latency shift as zero overhead

Rejected after remote measurement. Instrumentation ON improved the median claim p95 by 11.32%, but
the preregistered contract limits the *absolute* change to 10%. A favourable shift can still mean
the observer perturbed lock scheduling or transaction timing. Reclassifying only regressions as
intrusive after seeing the sign would be outcome-dependent threshold drift.

## Continuing formal attribution after overhead failure

Rejected by the frozen stop rule. Workflow `31400658653` skipped formal repetitions and H1/H2/H3
assessment after the overhead failure, while still sealing and committing the negative evidence.
Running the formal matrix anyway would produce inadmissible measurements rather than more evidence.

## Assuming counterbalancing alone would qualify the observer

The first workflow executed all OFF runs before all ON runs, so temporal drift was a strong
hypothesis. The second workflow froze `off1/on1/on2/off2/off3/on3`, ran only the representative arm
and reduced recorder clock work. Claim-p95 still changed by 13.4906% in absolute terms. The order
hypothesis was useful but insufficient; it was not rewritten as success.

## Automatically attempting a third observer design

Rejected by the second preregistration. Repeatedly changing the measurement seam until the same
10% gate happens to pass would create researcher degrees of freedom. A future design requires a new
explicit user authorization and should consider a materially different measurement mechanism, not
another small synchronous callback tweak.
