# v0.1.0 RC fairness and capacity

Current conclusion: `FAIRNESS_FAILED`; current 1k/10k/100k capacity qualification is `NOT_RUN`.

Targeted run `31319556885` completed 12 1k arms before fail-closed. At 1/2/4 workers the 20:1 secondary Tenant first
durable claim positions were 2/1/2. At 8 workers the position was 4, exceeding the frozen maximum 2. The order uses a
global monotonic timestamp after each claim transaction returns committed, so it is a durable-claim completion order.

All completed arms had 100 submitted, unique and terminal Jobs. Aggregate current counts were 1,200/1,200, with zero
lost Jobs, duplicate durable results, orphans and empty-while-eligible claims. Correctness does not cancel the
fairness failure.

Historical run `31272789199` still contains complete 1k/10k/100k capacity evidence and historical 20:1 positions 1 or
2. It is now labeled `VERIFIED_HISTORICAL` because its source predates Candidate 2 and the Run guard fix. Historical
100k single-Tenant/w8 values (about 0.628 Jobs/s, 504 retries and 41s claim p95) remain negative engineering evidence,
not current measurements.

No current capacity or strong fairness SLO is supported.
