# Resume-safe metrics

Status: the following scoped claims are backed by post-Git hash-verified evidence.

## Admitted claims

- Executed a real Docker Compose worker-scaling matrix with 500 measured cases per arm, Worker counts
  1/2/4/8, two workloads, and four repetitions: 32 arms and 16,000 Jobs, with 16,000 successful,
  zero failed/lost/orphan Jobs, zero duplicate durable results, and 400 successful retry events.
- Observed median throughput scaling from 21.48 to 66.80 Jobs/s for the I/O workload (3.11× speedup
  at eight Workers) and from 19.59 to 60.76 Jobs/s for the 5% transient-failure workload (3.10×).
- Ran a nine-scenario fault matrix three times after the database reconnect change: 84/84 logical
  Jobs succeeded, 72 deliberate retries completed, and failed/lost/duplicate/orphan counts were zero.
- Deliberately attempted three stale success commits and three stale failure commits after lease
  recovery; zero were accepted. Sixty concurrent duplicate-idempotency-key HTTP submissions all
  succeeded and resolved to one Run per repetition.
- Recovered from three 3-second PostgreSQL outages without restarting the Worker; median recovery
  after PostgreSQL restart was 6.83 seconds (range 6.28–6.83 seconds), with zero Job retries or
  correctness violations.
- In a real-PostgreSQL equal-priority 20:1 tenant-starvation test, the legacy FIFO candidate position
  for the later Tenant B Job was 21; the fair claimant served B within the first two concurrent
  claims with zero duplicate first-wave Jobs.

## Scope rules

These are experiment results, not universal production guarantees. Keep the workload names, Worker
counts, repetition count, source/evidence reference, and “observed” wording. Do not claim linear
scaling: eight-Worker parallel efficiency was about 0.39. Do not claim the reconnect backoff made
recovery faster; the before/after difference is too small and based on only three repetitions.
The fairness result is a controlled 20:1 first-wave test, not a general queue-latency SLO.
