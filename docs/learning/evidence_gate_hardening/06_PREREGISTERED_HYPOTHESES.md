# Preregistered Hypotheses

The normative thresholds are in
`docs/release/v0.1.0/performance_attribution/00_PREREGISTRATION.md`. This learning summary explains
how to read them.

## H1 — singleton coordination

Prediction: low-Tenant-cardinality workloads at w8 spend much more wait per successful claim on
SchedulerCoordination than w4, and this increase explains a material share of claim-latency growth.
At least two failing distributions must meet the 2x and 25% criteria, while many-small must not show
the same signature.

Falsifier: the ratio is below 2, the stage explains less than 25%, or many-small shows an equivalent
signature. A high absolute value without the registered contrast is not enough.

## H2 — Tenant permit contention

Prediction: permit wait per success grows stably from w4 to w8 in single/balanced/20:1, with greater
growth than many-small. This directly tests competition over a small set of pending permits.

Falsifier: no growth, inconsistent direction, or many-small growth of equal/larger magnitude.

## H3 — SKIP LOCKED/retry feedback

Prediction: w8 Job-row SKIP LOCKED misses per success are at least 2x w4 and grow together with
retry, waiting fallback and claim latency. The new counter distinguishes an actual locked eligible
Job from a generic empty permit.

Falsifier: miss rate remains near zero or the other three signals do not jointly grow. In that case
the hypothesis is explicitly REJECTED rather than silently omitted.

## Interpretation rule

Multiple hypotheses may be supported and none may be sufficient. `SUPPORTED` means the frozen data
matches the preregistered signature; it does not mean a causal root cause is formally proven.
