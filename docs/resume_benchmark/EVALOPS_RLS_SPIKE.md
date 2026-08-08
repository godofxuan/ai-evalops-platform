# PostgreSQL row-level security spike

Status: migration and local contracts `VERIFIED`; real PostgreSQL non-owner execution `PENDING`.

## Scope

The spike adds tenant policies to four core evaluation tables:

- `datasets`
- `dataset_versions`
- `evaluation_runs`
- `case_results`

Every policy compares the row's own `tenant_id` to
`current_setting('app.current_tenant_id', true)`. The missing-ok form returns null when the setting is
absent; the comparison is then not true, so a policy-bound role sees no rows. Callers set the value
with transaction-local `set_config(..., true)` so pooled connections do not retain one tenant's
context into a later transaction.

## CaseResult design decision

`CaseResult` previously had no direct tenant column. A policy could have used a subquery through
`evaluation_runs`, but PostgreSQL documents concurrency and information-leak risks for policy
expressions that consult other tables. The spike instead:

1. adds nullable `case_results.tenant_id`;
2. backfills it from the referenced Run;
3. makes it non-null;
4. adds `(tenant_id, run_id)` index; and
5. adds `(run_id, tenant_id) → evaluation_runs(id, tenant_id)` plus direct Tenant foreign keys.

The result committer now copies the already-fenced claim's `tenant_id` into the durable CaseResult.
This keeps policy evaluation local to each row and makes cross-tenant lineage independently
constraint-checked.

## Test contract

Offline migration tests require direct policies on all four tables, forbid a subquery policy, verify
upgrade backfill/constraints/indexes, and verify complete downgrade removal. ORM and result-commit
tests require the new tenant lineage.

The GitHub integration test creates a temporary `NOLOGIN NOSUPERUSER NOBYPASSRLS` role, grants only
the four-table DML privileges, and verifies against real PostgreSQL that:

- without a tenant setting, all four tables return zero rows;
- tenant A can see only tenant A rows in all four tables;
- an UPDATE targeting a hidden tenant B row affects zero rows;
- cross-tenant INSERT and visible-row tenant reassignment are rejected by RLS; and
- a same-tenant INSERT succeeds.

The role is removed with `DROP OWNED` and `DROP ROLE` in test cleanup.

## Deliberate limitation

The migration uses `ENABLE ROW LEVEL SECURITY`, not `FORCE ROW LEVEL SECURITY`. PostgreSQL table
owners normally bypass RLS. The current Compose topology uses one database owner account for
migrations, API, Worker, and Reaper, so forcing these policies immediately would default-deny normal
application work before transaction tenant/bypass context is wired across every process.

Therefore this spike proves the database policy boundary for a correct non-owner runtime role; it
does not claim that the current shared owner credential is production-enforced. Production rollout
requires separate migration-owner and runtime roles, least-privilege grants, tenant context in API
transactions, an explicitly audited background-worker access model, and then an enforcement decision
about `FORCE ROW LEVEL SECURITY`.
