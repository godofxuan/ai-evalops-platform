# Final scheduler CI qualification

Date: 2026-08-09  
Current qualified source: `ed095cc338ac6708bf5d9cce71bf509b5447358e`

Initial qualified source: `9ac70886c03c2d3a21ae667f47c5b5971c90ed4d`

## Outcome first

The initial candidate scheduler and its production-shaped PostgreSQL contracts passed both independent CI entry
points at source `9ac7088`:

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

## Strengthened-contract RED

Source `5261e56` deliberately promoted the 10W/100J test from one drain to 20 independent complete drains. Its two CI
entry points disagreed in a useful way:

| Entry point | Actions run | Result | Observation |
|---|---:|---|---|
| push CI | [31317175140](https://github.com/godofxuan/ai-evalops-platform/actions/runs/31317175140) | SUCCESS | all 20 repetitions passed |
| PR CI | [31317179594](https://github.com/godofxuan/ai-evalops-platform/actions/runs/31317179594) | FAILURE | one first wave returned 9 claims for 10 requests |

The failure had no duplicate claim and no deadlock; it was a false empty return while the 100-Job fixture still had
eligible work. Therefore `CORRECTNESS_PASS` is revoked for the strengthened contract, targeted performance remains
blocked, and candidate 2 at `e4dcb5e` must pass both CI entry points.

## Candidate 2 GREEN

After correcting only the diagnostic counter placement, exact source `ed095cc` passed both entry points:

| Entry point | Actions run | Result | Quality duration |
|---|---:|---|---:|
| push CI | [31318294569](https://github.com/godofxuan/ai-evalops-platform/actions/runs/31318294569) | SUCCESS | 4m36s |
| PR CI | [31318298660](https://github.com/godofxuan/ai-evalops-platform/actions/runs/31318298660) | SUCCESS | 4m18s |

The PR artifact independently downloaded with matching SHA-256. Across 20 repetitions the first waves produced
200/200 successful requests and 200 unique Jobs, with zero empty requests; every 100-Job queue then drained to 100
unique claims and 100 Attempts, for 2,000/2,000 across isolated fixtures. The source-controlled projection is
`raw/candidate2-ci-31318298660.json`.

The first Candidate-2 artifact (`31317940732`) had correct behavioral assertions but an incorrect test-only
`waiting_fallbacks` counter placement. That known-bad field is excluded from promoted metrics. The corrected artifact
reports 148 waiting fallbacks across 200 first-wave requests; the per-repetition range is 6–9.

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

| State | Current result at `ed095cc` | Boundary |
|---|---|---|
| `WORKFLOW_EXECUTED` | PASS | push `31318294569` and PR `31318298660` completed |
| `TESTS_PASS` | PASS | complete CI jobs green at both entry points |
| `CORRECTNESS_PASS` | PASS | strengthened 20-repetition 10W contract passed twice |
| `EVIDENCE_COMPLETE` | PASS for CI scope | targeted/capacity/fault/formal evidence remain separate |
| `PERFORMANCE_PASS` | NOT RUN | one 8-worker diagnostic is not a benchmark |
| `RELEASE_READY` | NO | release performance chain is still open |

## Local validation supporting the push

Before the qualifying push, the related local set reported `35 passed, 12 skipped`; the skips were real-PostgreSQL
tests and were not counted as GREEN. Ruff passed, MyPy passed 134 source files, and formatting passed. GitHub Actions is
the authoritative result for the skipped integration contracts.
