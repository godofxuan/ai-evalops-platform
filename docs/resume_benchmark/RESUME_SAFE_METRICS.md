# Resume-safe metrics

No capacity, latency, recovery-time, or scale claim is currently résumé-safe.

The formal 500-case worker-scaling experiment is `PENDING`. Metrics will be admitted here only when:

1. the raw bundle is retained and hash-verified;
2. every contributing arm passes durable correctness reconciliation;
3. required collectors have no missing samples;
4. stale result/failure acceptance is zero in explicitly induced scenarios;
5. the environment and command are recorded; and
6. aggregation includes every repetition rather than selecting the best run.
