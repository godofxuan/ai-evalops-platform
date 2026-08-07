# AI EvalOps before/after evidence

Status: database reconnect baseline `VERIFIED`; post-change rerun `PENDING`.

## Before bounded reconnect backoff

Source: `fault-gh-31181816878-1`, frozen source `da92532`, scenario F repeated three times.

| Metric | Before |
|---|---:|
| injected PostgreSQL outage | 3.00 s |
| recovery median after PostgreSQL restart | 6.91 s |
| recovery range | 6.35–6.95 s |
| Worker restart required | 0 / 3 |
| Job retries | 0 |
| failed/lost/duplicate/orphan Jobs | 0 / 0 / 0 / 0 |

The baseline proves SQLAlchemy `pool_pre_ping` and the existing process loop can reconnect without a
Worker restart. It does not bound the retry rate while PostgreSQL is unavailable: the Worker classified
an unhandled iteration exception as “processed” and immediately looped.

## Change under test

Worker and Reaper now share bounded exponential reconnect backoff with configurable base, maximum,
and jitter. Successful or idle iterations reset the consecutive-failure counter. All waits use the
existing stop event, so SIGTERM/SIGINT can interrupt a long reconnect delay. The post-change full
A–I matrix must pass before the After column is admitted.
