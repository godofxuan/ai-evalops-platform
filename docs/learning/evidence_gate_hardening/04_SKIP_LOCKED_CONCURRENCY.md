# SKIP LOCKED Concurrency Boundary

## Deterministic interleaving

The real PostgreSQL test creates one Tenant and one eligible Job, creates the current fair round,
then performs this interleaving:

1. Tx1 locks the Job row with `SELECT ... FOR UPDATE` and keeps the transaction open.
2. Tx2 locks the Tenant's current PENDING permit.
3. Tx2's Job selector uses `FOR UPDATE SKIP LOCKED` and returns no row.
4. A separate committed read captures permit status, Job status and active generation while Tx1
   still holds the Job lock.
5. Tx1 releases; a normal claim must eventually obtain the same Job.

No sleep or mocked lock is used.

## Real RED

Test commit `db89a67` was pushed because the local host had no PostgreSQL. Push CI run
`31397416017` passed migration, job claiming, multi-Tenant fairness and same-Tenant parallelism, but
failed only step 18, durable multi-Tenant fairness. The code path unconditionally set
`state.status = "empty"` when the SKIP LOCKED selector returned no rows.

Public API exposed the step verdict but GitHub rejected unauthenticated log download. Attempts to
use the Windows credential helper failed because PowerShell 5.1 lost the protocol/blank-line
boundary and the installed .NET lacked `StandardInputEncoding`. The attempts were stopped; no token
was printed or stored.

## State-machine repair

Commit `c5e8368` kept the existing three states. After an empty SKIP LOCKED result, a nonlocking
existence query checks the same Tenant, frozen priority and eligibility predicate:

- eligible Job still visible: retain PENDING;
- no eligible Job: mark EMPTY as before.

To avoid a PENDING busy loop, the waiting fallback selects the Job row without `SKIP LOCKED`; it
waits for release and then consumes the same permit. The fast path remains nonblocking. No new
state, migration, retry parameter or fairness policy was introduced.

The first local implementation accidentally placed the original `return statement` after the new
helper, making the SQL builder return `None`. Ruff, mypy and three unit tests caught it immediately;
moving the existing lines back across the function boundary restored 89 passing focused tests.

## Real GREEN and properties

Push run `31398322919` and PR run `31398332668` both completed successfully; step 18 passed in both.
The stage regression was 706 passed / 29 local skips. The test records PENDING before, non-EMPTY
after the miss, unchanged generation, QUEUED Job, and a final claim of that Job after unlock.

This is a tested interleaving, not a formal proof of all lock schedules. The fix preserves one turn
per permit, transaction rollback, crash recovery and generation semantics under the tested paths.
