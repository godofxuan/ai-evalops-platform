# Multi-tenant job-claim fairness

Status: `LOCAL-GREEN` (real PostgreSQL concurrency proof pending)

## Judgment before modification

The existing claimant orders every eligible Job globally by priority, creation time, and ID. This
is deterministic and safe with `SKIP LOCKED`, but it is not tenant-fair. With equal priority, if
Tenant A queues 20 Jobs before Tenant B queues one, B is candidate 21. A continuous older backlog
can therefore delay B without a bound.

The project already uses PostgreSQL as the durable scheduling authority. Adding Kafka, Celery,
Temporal, or a second Redis queue would replace rather than improve the lease/fencing design. The
minimum policy uses one nullable timestamp on Tenant and the existing PostgreSQL transaction.

## Policy

Each eligible Job receives `tenant_candidate_rank` using `row_number()` partitioned by tenant. The
outer order is:

1. explicit Job priority descending;
2. per-tenant candidate rank ascending;
3. Tenant `last_job_claimed_at` ascending, with never-served tenants first;
4. Job creation time and ID for a stable tie-break.

The claim locks both `evaluation_jobs` and `tenants` with `SKIP LOCKED`, then updates
`last_job_claimed_at` in the same short transaction. This has two intended effects:

- a batch takes one equal-priority candidate per available tenant before taking a second candidate
  from one tenant;
- concurrent Workers cannot independently treat the same Tenant scheduling state as unlocked.

Explicit priority remains stronger than tenant fairness. A deliberately higher-priority Job can run
before lower-priority tenants; fairness is defined within a priority band.

## RED/GREEN sequence

RED tests first required a tenant-partitioned rank, Tenant join/order, Job+Tenant row locks, and
scheduling timestamp update. They failed because the old SQL only locked Jobs and the Claimer only
returned `(job, run)` rows.

Implementation added migration `20260808_0016`, the nullable scheduling timestamp and index, the
ranked candidate CTE, and atomic timestamp update. The first GREEN attempt stopped at test
collection because the new migration test referenced a nonexistent helper module. The test was
corrected to reuse the repository's existing Alembic `Config` pattern rather than adding a new
production helper. Focused unit and offline migration tests then passed `7 passed`.

Strict MyPy next rejected a cleanup helper typed as `object`; narrowing it to `AsyncSession` fixed
the test boundary. Focused strict MyPy and Ruff then passed.

Local repository gate:

- migration/ORM/claiming/deployment-focused tests: `54 passed`;
- complete non-integration suite: `572 passed, 13 deselected` in `348.72s`;
- after adding an ORM column/index drift assertion, the affected focused set passed `22 passed`;
- Ruff: 307 files formatted and lint-clean;
- strict MyPy: 130 source files passed.

## First remote failure and correction

Commit `e43e785` triggered GitHub Actions run `31252705647`. Compose smoke passed, but the
quality/integration job failed for two independent reasons:

1. The new fairness fixture flushed Tenant and APIKey/Dataset dependants together. Real PostgreSQL
   rejected the APIKey inserts because the Tenant rows were not yet present. The fixture now flushes
   both Tenant rows first, matching the established integration setup pattern.
2. Tenant row locking exposed a throughput regression in the existing 10-Worker/100-Job claim test.
   One transaction claimed 20 Jobs and locked the Tenant; nine simultaneous claim calls skipped the
   Tenant and returned empty, so the one-shot total was 20 rather than 100.

The Tenant lock is required for strong first-wave fairness, so it was not removed. Instead,
`claim()` now distinguishes an empty queue from lock contention: after an empty locked selection it
runs a non-locking eligible-job probe. No eligible Job returns immediately; an eligible Job causes a
10 ms retry, bounded at 20 retries. A unit regression proves empty-first/probe/second-attempt success.

Corrected local gate: `574 passed, 13 deselected` in `352.50s`; Ruff passed 307 files; strict MyPy
passed 130 source files. A corrected remote run remains required.

## Real-service proof contract

The PostgreSQL integration test creates:

- Tenant A: 20 older equal-priority queued Jobs;
- Tenant B: one later equal-priority queued Job;
- two concurrent Worker claimers, each claiming one Job.

It retains both comparisons in the same test:

- legacy FIFO candidate position for B must equal `21`;
- the fair first claim wave must contain one unique Job from each Tenant, so B is served no later
  than claim wave `2`;
- claimed Job IDs must remain unique.

The test is wired into GitHub Actions after real migrations. Because local Docker/PostgreSQL is not
available and the first remote attempt failed before the fairness assertions, the numeric
improvement is not yet admitted as evidence. Corrected remote success is required to promote this
document to `VERIFIED`.

## Trade-offs and limits

- The windowed candidate query and Tenant join/lock cost more than the former index-friendly global
  FIFO query. No large-queue query-plan or throughput comparison has been run yet.
- This is fair scheduling, not an API rate limit, submission quota, storage quota, or billing policy.
- One Tenant row becomes a coordination point for that tenant's concurrent claims. That is an
  intentional bound. Bounded contention retries preserve the existing concurrent batch contract,
  but their high-concurrency latency/DB-query cost is not yet measured.
- A disabled Tenant's already queued Runs are not filtered by this scheduler; admission and
  cancellation policy remain separate concerns.
- The current shared owner database role can see all tenants. A future RLS rollout for background
  workers must deliberately preserve cross-tenant scheduling authority without giving API requests
  the same privilege.
