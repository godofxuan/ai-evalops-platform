# Final scheduler CI qualification

Date: 2026-08-09  
Qualified source: `9ac70886c03c2d3a21ae667f47c5b5971c90ed4d`

## Outcome first

The candidate scheduler and its initial production-shaped PostgreSQL contracts passed both independent CI entry
points at the same source:

| Entry point | Actions run | Result | Duration |
|---|---:|---|---:|
| push CI | [31315634340](https://github.com/godofxuan/ai-evalops-platform/actions/runs/31315634340) | SUCCESS | 4m02s |
| PR CI | [31315639504](https://github.com/godofxuan/ai-evalops-platform/actions/runs/31315639504) | SUCCESS | 3m58s |

This closes the six-hour hang and initial correctness-qualification blocker. It does **not** close the performance or
release gate.

## What the green run actually proved

- lock-sensitive PostgreSQL tests now fail in seconds at the transaction/Python layers and have a 10-minute CI step
  safety net;
- the Job selector remains independent of the Tenant scheduler row lock;
- the external `Tenant FOR UPDATE` negative diagnostic still produces the expected FK-related lock timeout;
- the external `FOR NO KEY UPDATE` control allows a complete durable claim;
- a bounded production fair-turn transaction can overlap a complete durable claim;
- same-row fair-turn reservations remain mutually exclusive;
- a locked Tenant does not stop another Tenant from being reserved through `SKIP LOCKED`;
- a crash after Phase-A commit leaves the Job queued, without Attempt or lease, and recoverably claimable;
- priority remains ordered ahead of equal-priority Tenant fairness;
- the initial 10W/100J `limit=1` test drained 100 unique Jobs with 100 Attempts;
- the 8-worker diagnostic returned eight unique Jobs and emitted contention data.

The 10W/100J test has since been strengthened to 20 complete repetitions, so that stronger contract must pass the next
CI source before final correctness promotion.

## Artifact integrity

Run `31315634340` uploaded `final-scheduler-lock-diagnostics-31315634340-1`:

| Field | Value |
|---|---|
| artifact id | `9038687051` |
| compressed bytes | `1,589` |
| expanded JSONL bytes | `14,768` |
| GitHub SHA-256 | `fc87667fba75230e916b5302bce818db49ced9fc41589fcf8040240c17fbc124` |
| independently downloaded ZIP SHA-256 | same |
| retention | 90 days, expires `2026-11-07T13:22:17Z` |

A source-controlled metric projection is in `raw/ci-qualification-31315634340.json`. The complete lock rows remain in
the digest-bound artifact instead of being silently truncated in documentation.

## Six-state interpretation

| State | Result at `9ac7088` | Boundary |
|---|---|---|
| `WORKFLOW_EXECUTED` | PASS | both push and PR workflows completed |
| `TESTS_PASS` | PASS | complete CI jobs green |
| `CORRECTNESS_PASS` | PASS for initial contracts | stronger 20-repetition 10W contract awaits re-run |
| `EVIDENCE_COMPLETE` | PASS for CI scope | targeted/capacity/fault/formal evidence not included |
| `PERFORMANCE_PASS` | NOT RUN | one 8-worker diagnostic is not a benchmark |
| `RELEASE_READY` | NO | release performance chain is still open |

## Local validation supporting the push

Before the qualifying push, the related local set reported `35 passed, 12 skipped`; the skips were real-PostgreSQL
tests and were not counted as GREEN. Ruff passed, MyPy passed 134 source files, and formatting passed. GitHub Actions is
the authoritative result for the skipped integration contracts.
