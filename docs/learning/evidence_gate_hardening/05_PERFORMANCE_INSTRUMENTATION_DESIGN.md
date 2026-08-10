# Performance Instrumentation Design

## Goal

Locate where w4→w8 time accumulates without changing scheduler policy. The production candidate
budget is zero. The exact code lock is `f1ecbf20d8e266eddadd85391d2c782c581ecad2`.

## Mechanism

`SQLAlchemyJobClaimer` accepts an optional synchronous phase observer. With instrumentation OFF,
the observer is `None` and each boundary performs only a branch. With ON, the benchmark's
`ClaimPhaseRecorder` uses `perf_counter_ns()` and stores process-local numeric observations.

Boundaries cover claim entry/return, SchedulerCoordination acquisition, Tenant permit acquisition,
Job row acquisition/skip, Job/Attempt mutation, durable sequence acquisition/update and
transaction completion. Per arm the runner emits count/sum/p50/p95/p99 for six registered stages,
plus low-cardinality counters for permit outcomes, round/generation changes and SKIP LOCKED misses.

The sum divided by `submitted_count` is used for wait-per-success attribution. Raw observations are
kept in the per-arm experiment JSON, while CSV contains aggregates. Entity IDs are not added to
Prometheus labels or diagnostic field names.

## Independent assessor

`scripts/performance_attribution_evidence.py` validates exact source, 16-arm sets, ON/OFF mode,
finite numeric domains, zero correctness fields and repetition counts. It provides an
`--overhead-only` mode so formal execution cannot start before the 3 OFF/3 ON gate is VALID. The
formal mode derives H1/H2/H3 from four ON repetitions using preregistered calculations.

Focused verification after implementation: Ruff and mypy passed; 50 tests passed. The dedicated
workflow also verifies that no `app/` or `scripts/` file differs after the instrumentation code lock
before running measurements.

## Known limitation

Wall-clock stage waits include database execution plus local async scheduling around that await.
They localize a transaction stage but do not alone identify a PostgreSQL lock holder or prove
causality. Optional pg_locks sampling was not added because the existing interval sampler cannot
reliably correlate short waits without either high overhead or entity-level identifiers.
