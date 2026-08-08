# AI EvalOps before/after evidence

Status: database reconnect baseline and post-change rerun `VERIFIED`.

Sources:

- Before: `fault-gh-31181816878-1`, source `da92532`, GitHub Actions `31181816878`.
- After: `fault-gh-31247720668-1`, source `03d6987`, GitHub Actions `31247720668`.

Both retained bundles passed post-Git manifest and SHA-256 validation and contain the complete A–I
matrix: nine scenarios, three repetitions, 27 records.

## PostgreSQL outage comparison

Scenario F stopped PostgreSQL for 3.00 seconds while a real Worker was executing a Job. PostgreSQL
was restarted without restarting the Worker.

| Metric | Before | After |
|---|---:|---:|
| recovery median after PostgreSQL restart | 6.910767 s | 6.827549 s |
| recovery range | 6.350567–6.951565 s | 6.281487–6.831259 s |
| successful recoveries | 3 / 3 | 3 / 3 |
| Worker restart required | 0 / 3 | 0 / 3 |
| Job retries | 0 | 0 |
| failed/lost/duplicate/orphan Jobs | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |

The 0.083-second median difference is not treated as a performance improvement: three repetitions
cannot establish that claim, and the change was not intended to shorten recovery. The admitted
effect is operational: SQLAlchemy `pool_pre_ping` remains responsible for reconnecting, while Worker
and Reaper now classify database connectivity failures separately and wait with bounded exponential
backoff plus jitter instead of hot-looping.

## Shutdown and retry contract

The configurable defaults are a 0.5-second base, 30-second maximum, and 0.2 jitter ratio. Successful
or idle iterations reset the consecutive-failure counter. Backoff waits use the existing stop event,
so SIGTERM/SIGINT can interrupt even a 30-second wait. Focused tests prove exponential growth,
maximum bounding after jitter, invalid configuration rejection, failure reset, and prompt shutdown.

## Full-matrix regression result

The After run completed all 84 logical Jobs successfully with 72 deliberate retries, rejected all
three stale success commits and all three stale failure commits, and recorded zero failed, lost,
duplicate-result, duplicate-terminal, or orphan-running Jobs. Scenario I also completed 60/60
concurrent HTTP submissions while producing one Run per repetition.

Machine-readable rows are in `FAULT_RESULTS.csv` and `EVALOPS_FAULT_INJECTION.csv`.
