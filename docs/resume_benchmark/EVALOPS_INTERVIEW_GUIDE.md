# AI EvalOps interview guide

## Current defensible statement

The project implements explicit PostgreSQL-backed job claiming, lease heartbeat and fencing,
retry/recovery, idempotent Run creation, durable result uniqueness, and real-service CI contracts.

The formal load matrix is also defensible as an engineering result: on the captured 4-vCPU GitHub
runner, 8 Workers reached median 66.80 jobs/s for fixed 25 ms I/O and 60.76 jobs/s for the deterministic
5% retry workload, approximately 3.1× the 1-Worker throughput. Say immediately that efficiency fell
to about 39%, the runner is not production hardware, and stale-write rejection still needs the
deliberate fault matrix before this becomes a résumé reliability claim.

## Claims deliberately withheld

Production capacity, production reliability, recovery-time objectives, stale-write fault claims, and
multi-tenant fairness remain withheld until the corresponding real-service evidence is complete.
