# Candidate 3 RED/GREEN ledger

Status: `RED_VERIFIED`; GREEN not yet implemented

## Environment

The local host has no PostgreSQL or Docker runtime. Local format/lint/mypy passed and the integration test collected then explicitly skipped. The authoritative database result is PostgreSQL-backed GitHub Actions; SQLite and mocks were not substituted.

## Target RED

| Property | Result |
|---|---|
| deterministic coordination | PASS: `Barrier` plus explicit `Event` gates, no random sleep |
| equal-priority primary queue | 21 Jobs |
| equal-priority secondary queue | 1 Job |
| Worker identities | 8 |
| Candidate 2 B reservation | early and committed |
| later A receipts while B paused | 6 |
| B committed receipt position | 8 |
| frozen requirement | <=2 |
| RED outcome | expected FAIL |
| source | `551f6b4fe01fec8ec8550527579772040f1a7b20` |
| Actions | `31325521253` |
| assertion | `FAIR_RESERVATION_NOT_SUFFICIENT_RED` |

## Candidate 3 test obligations

| RED/GREEN | Test source | Entry state |
|---|---|---|
| 1. frozen 20:1/8W receipt <=2 | targeted harness + durable fairness test | Candidate 2 FAIL |
| 2. deterministic overtaking schedule | `test_tenant_durable_fairness.py` | Candidate 2 FAIL at position 8 |
| 3. priority preservation | existing real-PG priority regression, extended for round priority | Candidate 2 PASS; Candidate 3 pending |
| 4. same Tenant 10W/100J limit=1 | 20-repetition production-shaped regression | Candidate 2 PASS; Candidate 3 pending |
| 5. permit crash | new round/permit rollback and post-refill recovery regression | pending |
| 6. cross-Tenant progress | different pending state rows under `SKIP LOCKED` | pending |
| 7. no duplicate Job | first-wave plus complete drain reconciliation | Candidate 2 PASS; Candidate 3 pending |
| 8. deadlock regression | PostgreSQL lock timeouts and lock diagnostics | Candidate 2 PASS; Candidate 3 pending |

Production implementation may start only after this RED and the proposal/state machine commits. GREEN will record exact test counts, source SHA and ordinary CI run IDs here; until then all Candidate 3 claims remain `NOT_RUN`.
