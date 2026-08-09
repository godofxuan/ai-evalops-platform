# Final scheduler test-contract analysis

Date: 2026-08-09  
Scope: claim SQL, PostgreSQL concurrency tests and fail-fast behavior

## Outcome first

The six-hour hang was partly a product-lock interaction and partly a test-contract defect. The database behavior was
real, but the old test name and assertion treated a complete durable transaction as if it were only the Job selector.
The correction is to retain the real behavior as a negative diagnostic while separating the selector and compatible
lock control into their own tests.

No assertion was weakened to make CI green. The still-red 8-worker contention threshold remains
`retry_per_success <= 0.25`; diagnostic commit `86767e7` observed `0.625`, so it continued to fail quickly.

## Old contract and why it was misleading

The removed test was named `test_job_claim_does_not_serialize_on_locked_tenant_row`, but it invoked the complete
`_claim_reserved_tenant` transaction. That transaction deliberately writes more than the selected Job:

1. Job status, attempt count, lease owner/expiry, heartbeat and fencing version;
2. one unique `JobAttempt`;
3. Run transition when the first Job starts;
4. `AuditEvent` rows;
5. transactional `ProgressEventOutbox` rows.

Audit and Outbox Tenant foreign keys make the full transaction sensitive to an external `Tenant FOR UPDATE` even
though the explicit selector is `FOR UPDATE OF evaluation_jobs SKIP LOCKED`. Expecting the full transaction to ignore
that artificial strong lock encoded a false boundary. With no timeout, the false boundary became a six-hour hang.

## Replacement contracts

| Contract | What it proves | What it does not claim |
|---|---|---|
| `test_job_selector_is_independent_of_tenant_scheduler_lock` | Explicit Phase B selection locks only Job and can run under an external Tenant lock | Full durable writes have no Tenant FK locks |
| `test_external_tenant_for_update_exposes_fk_lock_diagnostic` | Strong external Tenant lock blocks the complete durable claim through FK semantics and yields captured `55P03` evidence | `FOR UPDATE` is the correct production reservation mode |
| `test_external_tenant_no_key_update_allows_full_durable_claim` | A key-preserving Tenant lock is compatible with the full durable claim | Same-tenant contention is already below the release threshold |
| `test_same_tenant_eight_worker_contention_diagnostics` | Eight requests must claim eight unique Jobs and stay at or below the retry threshold | One successful sample alone proves capacity |

The diagnostic case expects a `DBAPIError` with SQLSTATE `55P03`; this is an intentional negative test, not a swallowed
production exception. It writes its lock snapshot before awaiting the timeout and always cancels an unfinished task in
`finally`, so failure cleanup itself cannot recreate the old unbounded wait.

## H3 RED→GREEN SQL contract

Before changing production code, the unit SQL contract was changed to require:

```sql
FOR NO KEY UPDATE OF tenants SKIP LOCKED
```

and to reject:

```sql
FOR UPDATE OF tenants
```

The focused RED failed because compiled SQL still ended in `FOR UPDATE OF tenants SKIP LOCKED`. The minimal GREEN is
one SQLAlchemy option change on Phase A: `key_share=True` with `read=False`, which compiles to `FOR NO KEY UPDATE`.
The focused claiming suite then passed `10/10` and the broader Job/Worker/config support set passed `76/76`.

## Preserved invariants

- Phase A remains a separate short transaction.
- Tenant selection remains mutually exclusive among schedulers and remains nonblocking through `SKIP LOCKED`.
- Only `last_scheduler_turn_at` is updated in Phase A; no Tenant key changes.
- Phase B still uses `FOR UPDATE OF evaluation_jobs SKIP LOCKED`.
- Job, Attempt, lease/version, Run transition, Audit and Outbox remain one atomic Phase B transaction.
- No retry threshold, uniqueness assertion, priority rule, fairness rule or failure expectation was relaxed.

## Remaining qualification work

The SQL compile GREEN is necessary but not sufficient. The candidate still needs:

1. real PostgreSQL CI proving the H2 negative/control tests and 8-worker threshold under the production H3 lock mode;
2. explicit reservation mutual-exclusion and production-shaped Phase A/Phase B overlap coverage;
3. multi-tenant nonblocking, 10W/100J `limit=1`, priority and reservation-crash contracts;
4. lock-order audit against completion, failure, heartbeat and Reaper paths;
5. only after full CI GREEN, the required paired and formal performance/fairness protocols.
