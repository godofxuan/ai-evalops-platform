# Candidate 2 durable-claim overtaking trace

Status: `ROOT_CAUSE_VERIFIED_ON_POSTGRESQL`

## Source-bound observed failure

- production candidate: `e4dcb5ea0a337bf234e807ccde3a01e9eb988224`;
- targeted execution source: `246252e30e63f046a4a1fb5d684a35449aaef9e3`;
- Actions run: `31319556885`;
- arm: `skew_20_to_1`, queue 1,000, sample 100, 8 Workers, limit 1;
- reconciliation: 100/100 unique terminal Jobs, zero lost/duplicate/orphan/false-empty failures;
- secondary first post-commit `claim()` receipt: position 4;
- frozen maximum: position 2;
- decision: `FAIRNESS_FAILED`.

The surviving evidence records application receipt order and aggregate scheduler counters, not every per-Worker transaction timestamp. Exact timestamps or Job IDs that are not present in the artifact are therefore not invented below. The new deterministic PostgreSQL RED adds those stage events.

## The actual Candidate 2 transaction split

```text
Phase A transaction                         Phase B transaction
---------------------------------------     -----------------------------------
rank eligible Job heads by Tenant           select one Job for reserved Tenant
lock Tenant FOR NO KEY UPDATE               lock Job FOR UPDATE SKIP LOCKED
set Tenant.last_scheduler_turn_at            mutate Job state/version/lease
COMMIT reservation                           insert Attempt/Audit/Outbox
return tenant_id                             COMMIT durable claim
                                             return ClaimedJob to application
```

The Phase A commit releases the Tenant row before Phase B begins. Nothing in durable state says “this Tenant's admitted claim must complete before a later turn is admitted.” `last_scheduler_turn_at` remembers selection recency only.

## Minimal causal schedule for position 4

The following is a source-derived causal trace that the deterministic RED coordinates with `Barrier`/`Event`. `rN` denotes reservation order and `cN` denotes durable committed receipt order; they are deliberately different counters.

| Logical event | Worker | Tenant | Reservation | Phase B / receipt | Consequence |
|---|---|---|---|---|---|
| T0 | W-A1 | A | attempts and commits `r1` | starts A Job lock/write | A is the first fair turn. |
| T1 | W-B1 | B | attempts and commits early `r2` | intentionally paused before Phase B | Reservation is fair, but it creates no completion fence. |
| T2 | W-A2 | A | commits `r3` after A is again least-recently selected | commits and returns `c1` or `c2` | A overtakes B after B's fair reservation. |
| T3 | W-A3 | A | commits `r4` | commits and returns before B | A overtakes B a second time. |
| T4 | W-A4 | A | may commit a later turn | commits and returns before B | The observed targeted run can reach three A receipts first. |
| T5 | W-B1 | B | reservation was already durable at T1 | finally locks/writes/commits and returns `c4` | Frozen receipt position is 4, despite early reservation. |

Depending on scheduling, A1 can commit before or after B's Phase A; that detail does not repair the invariant. The decisive edge is:

```text
B reservation COMMIT
    does not happen-before
B Job transaction COMMIT / claim() return

and it does not block
A later reservation -> A later durable claim COMMIT / return
```

## Where B is overtaken

- Not before reservation: B can receive an early fair turn.
- Not necessarily at Job-lock competition: A and B lock different Job rows.
- **Between B's reservation commit and B's Phase B durable claim commit**, later A reservations can be issued and completed.
- The existing harness then observes the same failure after `claim()` returns. This is not result-completion order.

## Waiting fallback and misses

Candidate 2's one bounded waiting fallback repairs a different liveness problem: when `SKIP LOCKED` sees only locked fair-turn rows, a Worker can wait once instead of returning false empty. It does not order already-reserved Phase B transactions. Thus a low miss count or zero empty-while-eligible count cannot prove F2.

## Evidence completion plan

`tests/concurrency/test_tenant_durable_fairness.py` emits, for each coordinated Worker, reservation attempt/commit, selected Tenant, Phase B start/pause/release, Job transaction return and application receipt, plus a monotonic event sequence. Candidate 2 failed the unchanged `position <= 2` assertion on real PostgreSQL before production code changes. After Candidate 3, the same receipt oracle must turn GREEN; any database-linearized sequence is reported alongside it, never substituted for it.

## Deterministic PostgreSQL RED result

| Field | Value |
|---|---|
| source | `551f6b4fe01fec8ec8550527579772040f1a7b20` |
| push Actions run | `31325521253` |
| job | `quality-and-integration` (`93275134510`) |
| environment | GitHub-hosted runner, PostgreSQL 18.4 service |
| compose-smoke | PASS in 1m00s |
| quality job | expected FAIL in 3m53s |
| artifact | `final-scheduler-lock-diagnostics-31325521253-1` |
| artifact digest | `sha256:0342e7c7562d5ec294747355c8bf929550ee49fbd3149a210df9c2440d8d8e1e` |
| secondary receipt | position 8 |
| frozen threshold | position <=2 |

The decisive observed events were:

| Event | Monotonic ns | Worker | Meaning |
|---:|---:|---|---|
| 2 | 215385576122 | `primary-1` | A reservation committed. |
| 5 | 215394975044 | `primary-1` | A first committed receipt became application-visible. |
| 7 | 215400044979 | `secondary-1` | B reservation committed early. |
| 9 | 215400052040 | `secondary-1` | B paused before Phase B. |
| 10–39 | bounded trace middle | `primary-2` through `primary-7` | Six later A reservation/Job transaction/receipt chains completed. |
| 40 | 215452326843 | `secondary-1` | B Phase B was released. |
| 41 | 215456675569 | `secondary-1` | B Job transaction committed/returned. |
| 42 | 215456680316 | `secondary-1` | B committed receipt became application-visible at position 8. |

No random sleep participates in the schedule. An `asyncio.Barrier` proves six overtaking Worker tasks are ready; six individual `Event` gates advance them one at a time while B remains paused. That makes the causal order deterministic and separates the design failure from runner speed.
