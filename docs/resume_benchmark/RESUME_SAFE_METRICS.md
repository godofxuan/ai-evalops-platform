# Resume-safe metrics

The load measurements are hash-verified and internally reportable, but no combined reliability and
scaling claim is yet résumé-safe.

Completed admission checks:

- raw bundle retained and post-Git hash-verified;
- all 32 arms pass durable reconciliation;
- no required collector samples are missing;
- environment, source/image identity, protocol, and commands are retained; and
- aggregation includes all four repetitions.

Remaining blocking check: stale result and stale failure acceptance must both be zero in explicitly
induced real-service scenarios. Until that matrix completes, use the numbers in
`EVALOPS_LOAD_REPORT.md` for engineering analysis only; do not copy them into the repository README,
a résumé, or a reliability claim.
