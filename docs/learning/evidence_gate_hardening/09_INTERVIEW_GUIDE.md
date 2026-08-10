# Interview Guide

## Two-minute story

“I inherited a multi-Tenant PostgreSQL scheduler whose bounded correctness tests passed but whose
4→8 Worker throughput regressed. I did not tune the benchmark. I first hardened the evidence: an
independent raw-plan parser removed a producer/verifier common-mode failure; the repeated assessor
fullmatched arm IDs and rejected NaN/metadata drift; and a preregistered false-empty metric became a
real gate. Then a deterministic two-transaction PostgreSQL test found that SKIP LOCKED could mark a
still-eligible Tenant permit EMPTY. I kept the existing state machine, retained PENDING only when a
separate eligibility probe succeeded, and made the waiting fallback block instead of spin. CI
showed RED then GREEN. Only after that did I preregister low-overhead phase timings and H1/H2/H3
criteria. The release stayed NOT_READY throughout.”

## Questions to expect

### Why is a manifest insufficient?

It proves file-set and byte integrity, not that a top-level summary agrees with semantic content.
An independently implemented parser closes that specific common-mode path.

### Why not mark the permit EMPTY when SKIP LOCKED returns no row?

SKIP LOCKED means “no lockable row now,” not “no eligible row exists.” Those are different state
facts. A nonlocking eligibility probe distinguishes them under MVCC.

### Why does the fallback remove SKIP LOCKED?

Retaining PENDING with another nonblocking attempt can busy-loop. The ordered fallback already
accepts waiting for a turn, so waiting for the locked Job preserves the permit and guarantees
progress after release in the tested interleaving.

### Did this prove exactly-once or universal fairness?

No. It proved bounded invariants in registered workloads and specific real PostgreSQL
interleavings. Durable result uniqueness in 6,400 Jobs is evidence, not an exactly-once theorem.

### Can the performance experiment prove causality?

No. It can localize stable wait signatures to transaction stages and reject hypotheses. A supported
signature justifies at most one future preregistered candidate, followed by another controlled test.

## Resume-safe bullets

- Hardened an immutable release-evidence gate with selector-specific independent PostgreSQL EXPLAIN
  parsing and fail-closed manifest/arm/numeric cross-binding.
- Reproduced and fixed a real `FOR UPDATE SKIP LOCKED` false-empty scheduler interleaving using
  deterministic transaction barriers; preserved existing fair-round state and recovery semantics.
- Designed preregistered, overhead-gated contention attribution with low-cardinality phase metrics
  and immutable GitHub Actions evidence.

Do not write “production-ready,” “exactly-once,” “universal fairness,” “linear scaling” or “formal
proof.”
